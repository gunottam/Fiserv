"""Chat service — grounded conversational reasoning about a decision.

This is the "why / what-if" interface on top of ``/predict``. The caller sends:

* ``context``: the PredictResponse (or equivalent) for the SKU being discussed.
* ``messages``: prior turns in the conversation, plus the new user message.

We forward both to Groq with a strong system prompt that pins the assistant to
the numbers in ``context`` and forbids hallucinating new data. If Groq isn't
configured or the call fails, we degrade to a deterministic rule-based reply
so the endpoint is always usable (just less articulate).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterable

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Hard caps so a misbehaving client can't drive token costs or latency up.
MAX_HISTORY_MESSAGES = 20
MAX_MESSAGE_CHARS = 2000
MAX_COMPLETION_TOKENS = 600


SYSTEM_PROMPT = """You are the analytical layer behind Contextual Inventory Intelligence, an operations co-pilot for a retail bakery. A store manager is looking at a single restock decision and wants to understand *why* the system produced it, or explore *what-if* variations.

You have access to a DECISION_CONTEXT block with the exact numbers the pipeline used:
- item, current_stock, threshold, day/hour, is_peak_hour
- predicted_velocity (model output, units/hr)
- adjusted_velocity (after context boosts; each rule that fires multiplies by 1.20)
- context_factors (which of "Peak hour", "Weekend", "Historical stockouts" fired)
- coverage_hours (= current_stock / adjusted_velocity)
- stockout_risk % (exponential decay on coverage: high when coverage is tiny)
- urgency bucket (HIGH if coverage <= 1.0h, MEDIUM if <= 3.0h, else LOW)
- restock_units ( = ceil(adjusted_velocity * hours_to_cover - current_stock), clamped at 0 )
  where hours_to_cover is 5 for peak, 3 otherwise.
- historical_stockout_rate (0.0–1.0, item-level; triggers a boost at >= 0.15)

Rules you MUST follow:
1. Every numeric claim must come from DECISION_CONTEXT. Do not invent stats.
2. Be direct and tight — short paragraphs, no filler, no apologies.
3. When asked "why", walk the path: prediction → boosts applied → coverage → urgency → restock qty, citing the numbers.
4. When asked "what if" (e.g. "what if it weren't peak hour"), recompute verbally using the +20% rule and the 5h/3h coverage switch. Show the arithmetic briefly.
5. If the operator pushes back on the recommendation, first steelman it with the numbers, then name the specific condition that would flip urgency (e.g. "coverage would need to rise above 3h, which means stock >= X or adjusted velocity <= Y").
6. Keep answers under ~120 words unless asked to go deeper.
7. Plain text only — no markdown headers, no bullet spam."""


def _truncate(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "… [truncated]"


def _format_context(context: dict[str, Any]) -> str:
    """Render the decision context as compact JSON-ish text for the LLM."""
    keys = [
        "item_id",
        "item_name",
        "current_stock",
        "threshold",
        "day_of_week",
        "hour",
        "is_peak_hour",
        "predicted_velocity",
        "adjusted_velocity",
        "context_factors",
        "coverage_hours",
        "stockout_risk",
        "urgency",
        "restock",
        "historical_stockout_rate",
    ]
    lines = []
    for k in keys:
        if k in context and context[k] is not None:
            lines.append(f"{k}: {context[k]}")
    return "DECISION_CONTEXT:\n" + "\n".join(lines)


def _normalize_history(history: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """Validate, coerce, and cap the history before sending to the LLM."""
    allowed_roles = {"user", "assistant"}
    clean: list[dict[str, str]] = []
    for turn in history:
        role = str(turn.get("role", "")).strip().lower()
        content = str(turn.get("content", "")).strip()
        if role not in allowed_roles or not content:
            continue
        clean.append({"role": role, "content": _truncate(content)})
    return clean[-MAX_HISTORY_MESSAGES:]


def _fallback_reply(context: dict[str, Any], user_message: str) -> str:
    """Deterministic answer used when Groq isn't reachable."""
    item = context.get("item_name", "this item")
    urgency = context.get("urgency", "LOW")
    pred = context.get("predicted_velocity", 0.0)
    adj = context.get("adjusted_velocity", 0.0)
    cov = context.get("coverage_hours", 0.0)
    risk = context.get("stockout_risk", 0.0)
    restock = context.get("restock", 0)
    factors = context.get("context_factors") or []

    factor_text = ", ".join(factors).lower() if factors else "no extra context boosts"
    factor_multiplier = 1.2 ** len(factors) if factors else 1.0

    return (
        f"(Groq unavailable — rule-based answer.) {urgency} urgency on {item} because "
        f"the model predicted {pred:.1f} units/hr and {factor_text} "
        f"pushed the adjusted rate to {adj:.1f} units/hr (×{factor_multiplier:.2f}). "
        f"That leaves {cov:.1f}h of coverage with a {risk:.0f}% stockout risk, "
        f"so the pipeline recommends restocking {restock} units. "
        f"Configure GROQ_API_KEY in backend/.env for richer reasoning."
    )


async def generate_chat_reply(
    *,
    context: dict[str, Any],
    history: list[dict[str, str]],
    user_message: str,
) -> str:
    """Return a grounded reply to the operator's question.

    The caller has already appended the new user message to ``history``'s
    tail, but to stay resilient we accept both shapes — if the last history
    entry isn't the current user_message we append it here.
    """
    user_message = _truncate(user_message.strip())
    if not user_message:
        return "Ask a question about the decision and I'll walk you through the reasoning."

    clean_history = _normalize_history(history)
    if not clean_history or clean_history[-1]["content"] != user_message:
        clean_history.append({"role": "user", "content": user_message})

    if not GROQ_API_KEY:
        logger.info("GROQ_API_KEY not set — returning chat fallback.")
        return _fallback_reply(context, user_message)

    try:
        from groq import AsyncGroq  # lazy import so missing deps don't break boot

        client = AsyncGroq(api_key=GROQ_API_KEY)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": _format_context(context)},
            *clean_history,
        ]

        completion = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=MAX_COMPLETION_TOKENS,
        )
        text = (completion.choices[0].message.content or "").strip()
        if not text:
            logger.warning("Groq returned an empty chat response; using fallback.")
            return _fallback_reply(context, user_message)
        return text

    except Exception as exc:  # noqa: BLE001 — degrade rather than 500
        logger.warning("Groq chat call failed (%s); using fallback.", exc)
        return _fallback_reply(context, user_message)


def chat_is_configured() -> bool:
    """Small helper for the health endpoint."""
    return bool(GROQ_API_KEY)
