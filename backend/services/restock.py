"""Restock quantity, urgency, and stockout-risk computation.

Given an adjusted velocity and current stock level, derive:
  * recommended restock quantity (integer, never negative)
  * urgency bucket (HIGH / MEDIUM / LOW)
  * hours of coverage remaining
  * stockout risk expressed as a 0-100 percentage

These are kept in a single module because they all key off the same
(velocity, stock) pair and sharing the intermediate math keeps them
internally consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Urgency = Literal["HIGH", "MEDIUM", "LOW"]

# Hours of coverage we aim for when topping up stock.
PEAK_COVERAGE_HOURS = 5
OFFPEAK_COVERAGE_HOURS = 3

# Urgency thresholds expressed as coverage hours remaining. Tuning these is
# the main lever a product manager would pull to change recommendation
# aggressiveness.
HIGH_URGENCY_MAX_COVERAGE = 1.0   # less than 1 hour left -> HIGH
MEDIUM_URGENCY_MAX_COVERAGE = 3.0  # less than 3 hours left -> MEDIUM


@dataclass(frozen=True)
class RestockOutcome:
    restock_units: int
    urgency: Urgency
    coverage_hours: float
    stockout_risk: float  # percentage 0-100


def compute_coverage_hours(adjusted_velocity: float, current_stock: float) -> float:
    """How many hours of sales the current stock can support at current demand."""
    if adjusted_velocity <= 0:
        # Zero demand means effectively infinite coverage; clamp so downstream
        # math doesn't explode and a reasonable number gets rendered.
        return 999.0
    return max(0.0, current_stock / adjusted_velocity)


def compute_stockout_risk(coverage_hours: float) -> float:
    """Map coverage-hours to a stockout-risk percentage.

    Curve:
      * <= 0 coverage  → 95% risk (floor below 100 to avoid false certainty)
      * 1 hour         → ~55%
      * 3 hours        → ~20%
      * 6+ hours       → 5% (floor)
    """
    if coverage_hours <= 0:
        return 95.0

    # Exponential-ish decay tuned by hand to hit the anchor points above.
    # We don't need statistical rigor here — it's a UI signal.
    risk = 95.0 * (0.55 ** coverage_hours)
    return round(max(5.0, min(95.0, risk)), 1)


def compute_urgency(coverage_hours: float) -> Urgency:
    """Classify based on coverage buckets — no fancy blending needed."""
    if coverage_hours < HIGH_URGENCY_MAX_COVERAGE:
        return "HIGH"
    if coverage_hours < MEDIUM_URGENCY_MAX_COVERAGE:
        return "MEDIUM"
    return "LOW"


def compute_restock_quantity(
    adjusted_velocity: float,
    current_stock: float,
    *,
    is_peak_hour: bool,
) -> int:
    """Top-up math: enough units to cover the target window from here.

    ``restock = (adjusted_velocity * hours) - current_stock``, floored at 0,
    rounded to the nearest whole unit.
    """
    hours = PEAK_COVERAGE_HOURS if is_peak_hour else OFFPEAK_COVERAGE_HOURS
    raw = adjusted_velocity * hours - current_stock
    return max(0, round(raw))


def compute_restock(
    adjusted_velocity: float,
    current_stock: float,
    *,
    is_peak_hour: bool,
) -> RestockOutcome:
    """One-shot helper: compute all restock-related outputs together."""
    coverage = compute_coverage_hours(adjusted_velocity, current_stock)
    return RestockOutcome(
        restock_units=compute_restock_quantity(
            adjusted_velocity, current_stock, is_peak_hour=is_peak_hour
        ),
        urgency=compute_urgency(coverage),
        coverage_hours=round(coverage, 2),
        stockout_risk=compute_stockout_risk(coverage),
    )
