"""Interactive Telegram bot — commands the operator can type at the bot.

The push-side (`send_telegram_alert`) delivers unsolicited alerts. This
module is the *listener*: it long-polls Telegram for incoming messages
and dispatches commands like /help, /status, /alerts, /mute, etc.

Design notes:
- Long-polling is handled by python-telegram-bot. One HTTP connection is
  held open to Telegram; messages arrive ~200ms after the user hits send.
- Runs inside the same asyncio loop as FastAPI via the lifespan hook in
  `app.py`. `start()` / `stop()` are idempotent no-ops when the bot is
  not configured, so deployments without TELEGRAM_BOT_TOKEN still work.
- Replies are `ChatAction.TYPING` → message so the user sees immediate
  feedback (the "typing..." indicator shows within a few ms).
- `/mute` and `/unmute` mutate shared state in `services/telegram.py`,
  which the push-side reads on every alert. No extra coordination.
- Only the configured chat id (TELEGRAM_CHAT_ID) is authorised. Messages
  from any other chat are ignored — this is a single-operator bot.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from telegram import BotCommand, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from services import telegram as telegram_push

logger = logging.getLogger(__name__)

# Singleton — one Application per process. Guarded by `_start_lock` so
# concurrent startup calls can't race.
_app: Application | None = None
_start_lock = asyncio.Lock()

# Set of commands surfaced in the Telegram UI menu (the "/" popup).
_BOT_COMMANDS: list[BotCommand] = [
    BotCommand("start", "Welcome + quick tour"),
    BotCommand("help", "Show all commands"),
    BotCommand("status", "System snapshot (counts by urgency)"),
    BotCommand("alerts", "Top active HIGH/MEDIUM alerts"),
    BotCommand("mute", "Pause alerts, e.g. /mute 30 (minutes)"),
    BotCommand("unmute", "Resume alerts immediately"),
    BotCommand("ping", "Round-trip latency check"),
]


# ---------------------------------------------------------------------------
# Lifecycle (called from app.py lifespan)
# ---------------------------------------------------------------------------


async def start() -> None:
    """Launch the bot in the current event loop.

    No-op when TELEGRAM_BOT_TOKEN is missing. Safe to call multiple times —
    subsequent calls return immediately if the bot is already running.
    """
    global _app
    async with _start_lock:
        if _app is not None:
            return

        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            logger.info("Telegram bot listener disabled (no TELEGRAM_BOT_TOKEN)")
            return

        app = (
            ApplicationBuilder()
            .token(token)
            # Shorter connect/read timeouts so a Telegram blip doesn't stall
            # shutdown. The default long-poll timeout (30s) is set below.
            .connect_timeout(10.0)
            .read_timeout(35.0)
            .build()
        )

        app.add_handler(CommandHandler("start", _cmd_start))
        app.add_handler(CommandHandler("help", _cmd_help))
        app.add_handler(CommandHandler("status", _cmd_status))
        app.add_handler(CommandHandler("alerts", _cmd_alerts))
        app.add_handler(CommandHandler("mute", _cmd_mute))
        app.add_handler(CommandHandler("unmute", _cmd_unmute))
        app.add_handler(CommandHandler("ping", _cmd_ping))
        # Any non-command text → gentle nudge to /help. Bots without this
        # feel broken when the user sends plain text.
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_text)
        )
        app.add_error_handler(_on_error)

        await app.initialize()
        # Publish the command menu so the Telegram app shows the "/" popup.
        # Best-effort — a network hiccup here must not block listener startup.
        try:
            await app.bot.set_my_commands(_BOT_COMMANDS)
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("Failed to set bot command menu: %s", exc)
        # start_polling returns immediately; polling runs as a background task.
        await app.updater.start_polling(
            poll_interval=0.0,        # drain updates as fast as they arrive
            timeout=30,               # long-poll window (Telegram holds open)
            drop_pending_updates=True # ignore messages queued before we booted
        )
        await app.start()
        _app = app
        logger.info("Telegram bot listener started")


async def stop() -> None:
    """Tear the bot down cleanly. Safe to call when not running."""
    global _app
    async with _start_lock:
        if _app is None:
            return
        app = _app
        _app = None
    try:
        if app.updater and app.updater.running:
            await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("Telegram bot listener stopped")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram bot shutdown error (ignoring): %s", exc)


def is_running() -> bool:
    return _app is not None


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorised(update):
        return
    text = (
        "👋 *Contextual Inventory Intelligence*\n\n"
        "I'll ping you when any item needs restocking.\n"
        "Try `/status` for a snapshot or `/help` for everything I can do."
    )
    await _reply(update, text)


async def _cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorised(update):
        return
    text = (
        "*Commands*\n\n"
        "`/status` — counts by urgency (HIGH / MEDIUM / LOW)\n"
        "`/alerts` — top active HIGH + MEDIUM alerts\n"
        "`/mute [minutes]` — silence alerts (default 15, max 1440)\n"
        "`/unmute` — resume alerts now\n"
        "`/ping` — round-trip latency check\n"
        "`/help` — this message\n\n"
        "Push notifications fire automatically on HIGH or MEDIUM urgency. "
        "Repeat alerts for the same item are de-duplicated within a 5 min "
        "cooldown so your phone doesn't melt."
    )
    await _reply(update, text)


async def _cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorised(update):
        return

    counts = telegram_push.decision_counts()
    total = sum(counts.values())
    muted_for = telegram_push.mute_remaining_seconds()

    if total == 0:
        await _reply(
            update,
            "📊 *Status*\n\nNo decisions cached yet. "
            "Run some `/predict` calls from the dashboard and I'll have "
            "something to show.",
        )
        return

    lines = [
        "📊 *System Snapshot*",
        "",
        f"🔴 HIGH:    {counts['HIGH']}",
        f"🟠 MEDIUM:  {counts['MEDIUM']}",
        f"🟢 LOW:     {counts['LOW']}",
        "",
        f"Tracked items: {total}",
    ]
    if muted_for > 0:
        lines.append("")
        lines.append(f"🔕 Alerts muted for {_fmt_duration(muted_for)}")
    await _reply(update, "\n".join(lines))


async def _cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorised(update):
        return

    decisions = telegram_push.recent_decisions()
    urgent = [
        d for d in decisions
        if str(d.get("urgency", "")).upper() in ("HIGH", "MEDIUM")
    ]

    if not urgent:
        await _reply(
            update,
            "✅ *No active alerts*\n\nEverything is LOW urgency or untracked.",
        )
        return

    lines = ["🚨 *Active alerts*", ""]
    for d in urgent[:10]:  # cap at 10 — keep the message phone-readable
        urgency = str(d.get("urgency", "?")).upper()
        icon = "🔴" if urgency == "HIGH" else "🟠"
        name = _md_safe(str(d.get("item_name", "?")))
        stock = int(d.get("current_stock") or 0)
        coverage = float(d.get("coverage_hours") or 0.0)
        restock = int(d.get("restock") or 0)
        lines.append(
            f"{icon} *{name}* — {stock} units · {coverage:.1f}h cover · "
            f"restock +{restock}"
        )

    if len(urgent) > 10:
        lines.append("")
        lines.append(f"…and {len(urgent) - 10} more.")

    await _reply(update, "\n".join(lines))


async def _cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorised(update):
        return

    minutes = 15  # sensible default if the user just types `/mute`
    args = context.args or []
    if args:
        try:
            minutes = int(args[0])
        except ValueError:
            await _reply(
                update,
                "❌ Usage: `/mute [minutes]` — e.g. `/mute 30`",
            )
            return

    minutes = max(1, min(minutes, 1440))  # 1 min .. 24h
    telegram_push.mute_for(minutes * 60)
    await _reply(
        update,
        f"🔕 *Muted* for {minutes} min.\nI'll stay quiet until then. "
        "Use `/unmute` to resume early.",
    )


async def _cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorised(update):
        return
    was_muted = telegram_push.unmute()
    if was_muted:
        await _reply(update, "🔔 *Alerts resumed.*")
    else:
        await _reply(update, "🔔 Alerts were already on.")


async def _cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorised(update):
        return
    # Round-trip latency: we can't measure Telegram→client, but we can
    # measure how long our handler+send takes, which is the part the
    # operator perceives.
    t0 = time.perf_counter()
    sent = await _reply(update, "pong")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if sent is not None:
        try:
            await sent.edit_text(f"pong · {elapsed_ms:.0f}ms")
        except Exception:  # noqa: BLE001 — latency reporting is best-effort
            pass


async def _handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Non-command text → nudge toward /help."""
    if not await _authorised(update):
        return
    await _reply(
        update,
        "Hmm, I only speak in commands. Try `/help` to see what I know.",
    )


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler — never let an exception kill the poller."""
    logger.warning("Telegram handler error: %s", context.error)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _authorised(update: Update) -> bool:
    """Reject messages from chats other than the configured operator.

    Leaves a one-line warning log so an unexpected chat is visible, but
    never responds (silent drop is the right UX for a private bot).
    """
    allowed = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    chat = update.effective_chat
    if not allowed or chat is None:
        return False
    if str(chat.id) != allowed:
        logger.warning(
            "Ignoring Telegram message from unauthorised chat %s (%s)",
            chat.id,
            chat.type,
        )
        return False
    return True


async def _reply(update: Update, text: str) -> Any:
    """Send a typing action + Markdown reply. Returns the sent Message, or None."""
    chat = update.effective_chat
    if chat is None:
        return None
    # Fire-and-forget typing indicator — makes the bot feel instant even
    # if the reply takes a few hundred ms to serialize.
    try:
        await chat.send_chat_action(ChatAction.TYPING)
    except Exception:  # noqa: BLE001 — purely cosmetic
        pass
    try:
        return await chat.send_message(
            text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send Telegram reply: %s", exc)
        return None


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


# Reuse the same Markdown escape set as the push-side so formatting is
# consistent between unsolicited alerts and bot replies.
_MD_ESCAPES = str.maketrans({"_": r"\_", "*": r"\*", "`": r"\`", "[": r"\["})


def _md_safe(text: str) -> str:
    return str(text).translate(_MD_ESCAPES)
