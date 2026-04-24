"""Telegram notification service for high/medium urgency inventory alerts.

Design constraints (see /README):
- Token + chat id come from environment variables, never hardcoded.
- Sending is best-effort: failures are logged, never raised. The caller
  (predict route) schedules this via BackgroundTasks so the API response
  is already on the wire before we even try to reach Telegram.
- Only HIGH / MEDIUM urgencies fire — LOW is a no-op to avoid spam.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Mapping

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

# How long to wait for Telegram before giving up. Short on purpose — this
# runs post-response, but we still don't want long-lived tasks piling up
# if Telegram is slow or unreachable.
REQUEST_TIMEOUT_SEC = 5

# Urgency buckets that are allowed to trigger a notification.
NOTIFY_URGENCIES = frozenset({"HIGH", "MEDIUM"})

# Max length (chars) for the 1-line rationale we tuck under 🧠. Keeps the
# Telegram message scannable on a phone.
MAX_RATIONALE_CHARS = 140

# Cooldown between identical alerts. Without this, every dashboard refresh
# re-fires /predict for every alert and the operator's phone gets flooded
# with duplicates. Telegram also rate-limits ~1 msg/s per chat, so a burst
# of N alerts trickles in over N seconds and feels "slow". Keyed on the
# (item_id, urgency) tuple so a real escalation MEDIUM→HIGH still pages.
# Override with TELEGRAM_DEDUP_SECONDS=0 to disable.
DEFAULT_DEDUP_SECONDS = 300
_dedup_lock = threading.Lock()
_dedup_sent_at: dict[tuple[str, str], float] = {}

# Mute state — user can suspend notifications via the bot's /mute command
# without tearing down the whole pipeline. `_mute_until_wall` is a Unix
# timestamp. The separate lock keeps the mute state cheap to read on the
# hot path and from async command handlers.
_mute_lock = threading.Lock()
_mute_until_wall: float = 0.0

# Shared "last known decision" cache. /predict pushes the latest decision
# here (keyed by item_id); the bot's /status and /alerts commands read it
# to answer without needing to re-run the whole pipeline. Thread-safe.
_decision_lock = threading.Lock()
_recent_decisions: dict[str, dict[str, Any]] = {}
MAX_RECENT_DECISIONS = 100  # bounded so long-running processes don't grow


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def send_telegram_alert(data: Mapping[str, Any]) -> None:
    """Best-effort Telegram notification for a restock decision.

    `data` is expected to contain the fields produced by /predict:
      urgency, item_name, current_stock, adjusted_velocity, coverage_hours,
      restock, explanation, and optional store_id / context hints.

    No-op when:
      - urgency is not HIGH/MEDIUM
      - TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID env vars are missing
      - the HTTP call fails (errors are logged, not raised)
    """
    urgency = str(data.get("urgency", "")).upper().strip()

    # Always record the latest decision so /status and /alerts have data
    # to show — even for LOW urgencies that we won't notify about.
    item_id = str(data.get("item_id") or data.get("item_name") or "unknown")
    _record_decision(item_id, urgency, data)

    if urgency not in NOTIFY_URGENCIES:
        return

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        # Perfectly valid running state — the system still works without
        # Telegram, we just skip the notification leg quietly.
        logger.debug(
            "Telegram not configured; skipping %s alert for %s",
            urgency,
            data.get("item_name", "<unknown>"),
        )
        return

    # Mute: user ran /mute on the bot. Skip entirely; they'll see the
    # backlog via /alerts when they unmute.
    remaining = mute_remaining_seconds()
    if remaining > 0:
        logger.info(
            "Telegram %s alert for %s suppressed (muted %ds remaining)",
            urgency,
            data.get("item_name"),
            int(remaining),
        )
        return

    # Dedup: skip if we've already paged for this (item, urgency) recently.
    # Keeps the phone quiet when the dashboard polls/refreshes repeatedly.
    # `_claim_slot` atomically checks and reserves so concurrent background
    # tasks for the same key don't all pass the cooldown simultaneously.
    if not _claim_slot(item_id, urgency):
        logger.info(
            "Telegram %s alert for %s suppressed (cooldown active)",
            urgency,
            data.get("item_name"),
        )
        return

    message = _format_message(data)
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SEC)
        if not resp.ok:
            logger.warning(
                "Telegram sendMessage returned %s for %s: %s",
                resp.status_code,
                data.get("item_name"),
                resp.text[:200],
            )
            # Leave the slot reserved — treating a failed delivery as "seen"
            # is the safer default (backs off on flapping / rate limiting).
            return
        logger.info(
            "Telegram %s alert delivered for %s",
            urgency,
            data.get("item_name"),
        )
    except requests.RequestException as exc:
        # Network failure / timeout / DNS — never bubble up to the API layer.
        logger.warning(
            "Telegram alert failed for %s: %s",
            data.get("item_name"),
            exc,
        )


def telegram_is_configured() -> bool:
    """Whether both env vars are set. Surfaced on the /health endpoint."""
    return bool(
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        and os.getenv("TELEGRAM_CHAT_ID", "").strip()
    )


def reset_dedup_cache() -> None:
    """Clear the dedup cache. Useful for tests and for /admin endpoints."""
    with _dedup_lock:
        _dedup_sent_at.clear()


# ---------------------------------------------------------------------------
# Mute controls (called from the bot's /mute and /unmute handlers)
# ---------------------------------------------------------------------------


def mute_for(seconds: float) -> float:
    """Suspend notifications for `seconds` (min 1). Returns the mute deadline."""
    seconds = max(1.0, float(seconds))
    deadline = time.time() + seconds
    with _mute_lock:
        global _mute_until_wall
        _mute_until_wall = deadline
    return deadline


def unmute() -> bool:
    """Resume notifications. Returns True if we were actually muted."""
    with _mute_lock:
        global _mute_until_wall
        was_muted = _mute_until_wall > time.time()
        _mute_until_wall = 0.0
    return was_muted


def mute_remaining_seconds() -> float:
    """Seconds remaining on an active mute, else 0."""
    with _mute_lock:
        remaining = _mute_until_wall - time.time()
    return max(0.0, remaining)


# ---------------------------------------------------------------------------
# Decision cache accessors (bot commands read from these)
# ---------------------------------------------------------------------------


def recent_decisions() -> list[dict[str, Any]]:
    """Snapshot of the most recent decision per item, sorted by urgency.

    Returned as a plain list of dicts so the bot can format without holding
    the lock. HIGH first, then MEDIUM, then LOW; within each bucket the
    tightest coverage comes first (most urgent on top).
    """
    with _decision_lock:
        snapshot = list(_recent_decisions.values())
    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    snapshot.sort(
        key=lambda d: (
            rank.get(str(d.get("urgency", "LOW")).upper(), 3),
            _as_float(d.get("coverage_hours"), default=float("inf")),
        )
    )
    return snapshot


def decision_counts() -> dict[str, int]:
    """Counts of HIGH/MEDIUM/LOW across the cache. Used by /status."""
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for d in recent_decisions():
        urgency = str(d.get("urgency", "LOW")).upper()
        if urgency in counts:
            counts[urgency] += 1
    return counts


def _record_decision(
    item_id: str, urgency: str, data: Mapping[str, Any]
) -> None:
    """Store the latest decision for this item in the bounded cache."""
    record = {
        "item_id": item_id,
        "item_name": data.get("item_name") or item_id,
        "store_id": data.get("store_id"),
        "urgency": urgency,
        "current_stock": _as_float(data.get("current_stock")),
        "adjusted_velocity": _as_float(data.get("adjusted_velocity")),
        "coverage_hours": _as_float(data.get("coverage_hours")),
        "restock": _as_int(data.get("restock")),
        "recorded_at": time.time(),
    }
    with _decision_lock:
        _recent_decisions[item_id] = record
        # Bound the cache — drop oldest entries if we exceed the limit.
        if len(_recent_decisions) > MAX_RECENT_DECISIONS:
            oldest = min(
                _recent_decisions.items(),
                key=lambda kv: kv[1]["recorded_at"],
            )[0]
            _recent_decisions.pop(oldest, None)


# ---------------------------------------------------------------------------
# Dedup helpers
# ---------------------------------------------------------------------------


def _dedup_window_seconds() -> float:
    raw = os.getenv("TELEGRAM_DEDUP_SECONDS", "").strip()
    if not raw:
        return float(DEFAULT_DEDUP_SECONDS)
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(DEFAULT_DEDUP_SECONDS)


def _claim_slot(item_id: str, urgency: str) -> bool:
    """Check cooldown and reserve the slot in one critical section.

    Returns True when the caller is cleared to send. Returns False if a
    prior alert for the same (item, urgency) is still inside the dedup
    window. Reserving up-front prevents a thundering herd of concurrent
    background tasks from all passing the check and each sending.
    """
    window = _dedup_window_seconds()
    if window <= 0:
        return True
    key = (item_id, urgency)
    now = time.monotonic()
    with _dedup_lock:
        last = _dedup_sent_at.get(key)
        if last is not None and (now - last) < window:
            return False
        _dedup_sent_at[key] = now
        return True


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


def _format_message(data: Mapping[str, Any]) -> str:
    """Build the Markdown-formatted Telegram text.

    Layout (blank line separators to breathe on mobile):

        🚨 *HIGH URGENCY ALERT*

        📦 Item: Croissants
        📍 Store: IND-01
        📊 Stock: 7 units

        ⚡ Demand: 22.0 units/hr
        📉 Coverage: 0.8 hours

        📦 *Restock Now: +30 units*

        🧠 _Saturday morning peak with past stockouts and weekend surge_
    """
    urgency = str(data.get("urgency", "LOW")).upper()
    lines: list[str] = [f"🚨 *{urgency} URGENCY ALERT*", ""]

    lines.append(f"📦 Item: {_md_safe(data.get('item_name', '—'))}")
    store_id = data.get("store_id")
    if store_id:
        lines.append(f"📍 Store: {_md_safe(str(store_id))}")
    lines.append(f"📊 Stock: {_as_int(data.get('current_stock'))} units")
    lines.append("")

    lines.append(f"⚡ Demand: {_as_float(data.get('adjusted_velocity')):.1f} units/hr")
    lines.append(f"📉 Coverage: {_as_float(data.get('coverage_hours')):.1f} hours")
    lines.append("")

    lines.append(f"📦 *Restock Now: +{_as_int(data.get('restock'))} units*")

    rationale = _build_rationale(data)
    if rationale:
        lines.append("")
        lines.append(f"🧠 _{_md_safe(rationale)}_")

    return "\n".join(lines)


def _build_rationale(data: Mapping[str, Any]) -> str:
    """Produce the short 🧠 rationale line.

    Prefers a compact, factor-derived phrase (e.g. "Saturday morning peak
    with past stockouts") because it stays short and never drifts from the
    decision. Falls back to the first sentence of the Groq explanation if
    no context factors fired.
    """
    day = str(data.get("day_of_week", "")).strip()
    hour = data.get("hour")
    factors = data.get("context_factors") or []
    if isinstance(factors, str):
        factors = [factors]
    factors = {str(f).strip() for f in factors}

    pieces: list[str] = []
    if day:
        tod = _time_of_day(hour)
        head = f"{day} {tod}".strip() if tod else day
        if "Peak hour" in factors:
            head += " peak"
        pieces.append(head)

    causes: list[str] = []
    if "Historical stockouts" in factors:
        causes.append("past stockouts")
    # "Saturday morning" already implies the weekend — only call it out
    # when the day itself is a weekday.
    if "Weekend" in factors and day not in ("Saturday", "Sunday"):
        causes.append("weekend surge")

    if pieces:
        if causes:
            # Single serial-list join to avoid stacking "and"s
            # e.g. "rising demand, past stockouts and weekend surge".
            return f"{pieces[0]} with {_join_and(['rising demand'] + causes)}"
        if "Peak hour" in factors:
            return f"{pieces[0]} with rising demand"

    # Fallback: trim the full LLM explanation to one line.
    explanation = str(data.get("explanation") or "").strip()
    return _trim_to_one_line(explanation, MAX_RATIONALE_CHARS)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _join_and(parts: list[str]) -> str:
    """Human-style list join: ['a','b'] -> 'a and b', ['a','b','c'] -> 'a, b and c'."""
    if len(parts) <= 1:
        return parts[0] if parts else ""
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _time_of_day(hour: Any) -> str:
    try:
        h = int(hour)
    except (TypeError, ValueError):
        return ""
    if 5 <= h <= 11:
        return "morning"
    if 12 <= h <= 16:
        return "afternoon"
    if 17 <= h <= 21:
        return "evening"
    return "night"


def _trim_to_one_line(text: str, max_len: int) -> str:
    if not text:
        return ""
    text = " ".join(text.split())  # collapse whitespace / newlines
    first_period = text.find(". ")
    if 20 <= first_period <= max_len:
        return text[: first_period + 1].rstrip(".").strip()
    if len(text) <= max_len:
        return text.rstrip(".").strip()
    return text[: max_len - 1].rstrip() + "…"


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# Legacy Markdown (parse_mode=Markdown) treats `_` `*` `` ` `` and `[` as
# formatting chars. We defensively escape them in user-controlled strings so
# an SKU like "IND_01" or an item with "*" can't break the layout.
_MD_ESCAPES = str.maketrans({"_": r"\_", "*": r"\*", "`": r"\`", "[": r"\["})


def _md_safe(text: str) -> str:
    return str(text).translate(_MD_ESCAPES)
