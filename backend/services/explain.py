"""Natural-language explanation service.

Tries the Groq chat completions API first; if the API key is missing, the call
fails, or the response is empty, it falls back to a deterministic template so
the endpoint always returns something a store manager can act on.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()

SYSTEM_PROMPT = (
    "You are an inventory intelligence assistant embedded in a retail dashboard. "
    "You write crisp, action-oriented rationale for a store manager who has ~3 "
    "seconds to decide whether to approve a restock. "
    "Always respond in ONE or TWO sentences, plain prose, no markdown, no lists. "
    "Lead with the urgency word (High / Medium / Low) followed by a colon."
)


def _user_prompt(params: dict[str, Any]) -> str:
    """Build the user-side prompt from the pipeline outputs.

    Keeping this as a pure function makes it easy to snapshot-test the prompt
    and to reuse the same template for the offline fallback.
    """
    return (
        f"Item: {params['item_name']} ({params['item_id']})\n"
        f"Day: {params['day_of_week']}, Hour: {params['hour']:02d}:00, "
        f"Peak hour: {params['is_peak_hour']}\n"
        f"Current stock: {params['current_stock']:g} units, "
        f"Threshold: {params['threshold']:g} units\n"
        f"Predicted velocity: {params['predicted_velocity']:.1f} units/hr\n"
        f"Adjusted velocity (after context boost): "
        f"{params['adjusted_velocity']:.1f} units/hr\n"
        f"Coverage remaining: {params['coverage_hours']:.1f} hours\n"
        f"Stockout risk: {params['stockout_risk']:.0f}%\n"
        f"Urgency: {params['urgency']}\n"
        f"Recommended restock: {params['restock']} units\n"
        f"Context factors: {', '.join(params['context_factors']) or 'none'}\n\n"
        "Write the rationale now (1–2 sentences, action-oriented, specific to "
        "the day/hour and urgency)."
    )


def _fallback_explanation(params: dict[str, Any]) -> str:
    """Rule-based rationale used when Groq is unavailable.

    Reads well enough that the UI looks complete even without an API key.
    """
    period = _period_of_day(params["hour"])
    urgency_word = params["urgency"].capitalize()
    factors = params["context_factors"]

    # Match the verb to the subject (signals → plural, baseline demand → singular).
    if factors:
        subject = f"{' & '.join(factors).lower()} signals"
        verb = "are driving"
    else:
        subject = "baseline demand"
        verb = "is holding"

    lead = (
        f"{urgency_word} urgency: {params['day_of_week']} {period} {subject} "
        f"{verb} demand to {params['adjusted_velocity']:.0f} units/hr "
        f"(vs {params['predicted_velocity']:.0f} baseline), leaving "
        f"{params['coverage_hours']:.1f}h of coverage."
    )

    if params["restock"] > 0:
        tail = (
            f" Add {params['restock']} units now to prevent a "
            f"{params['stockout_risk']:.0f}% stockout risk on {params['item_name']}."
        )
    else:
        tail = (
            f" No restock needed — {params['item_name']} is comfortably "
            f"above the reorder threshold."
        )

    return lead + tail


def _period_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "late-night"


async def generate_explanation(params: dict[str, Any]) -> str:
    """Return a 1–2 sentence rationale.

    Calls Groq if ``GROQ_API_KEY`` is configured. Any failure (missing key,
    network, bad response) degrades silently to the template fallback so the
    API never fails because of the LLM leg.
    """
    if not GROQ_API_KEY:
        logger.info("GROQ_API_KEY not set — using rule-based explanation.")
        return _fallback_explanation(params)

    try:
        # Import lazily so the module loads cleanly in environments where the
        # groq package is not installed (e.g. first-run before pip install).
        from groq import AsyncGroq

        client = AsyncGroq(api_key=GROQ_API_KEY)
        completion = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _user_prompt(params)},
            ],
            temperature=0.3,
            max_tokens=180,
        )

        text = (completion.choices[0].message.content or "").strip()
        if not text:
            logger.warning("Groq returned an empty explanation — using fallback.")
            return _fallback_explanation(params)
        return text

    except Exception as exc:  # noqa: BLE001 — LLM failures must never 500 the API
        logger.warning("Groq call failed (%s) — using fallback.", exc)
        return _fallback_explanation(params)
