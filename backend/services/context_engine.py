"""Context engine — applies real-world rules on top of the base prediction.

Each rule that fires contributes a +20% multiplicative boost to the predicted
velocity. We also return the list of human-readable factors so the frontend
can surface them and the explanation prompt stays grounded.
"""

from __future__ import annotations

from dataclasses import dataclass

# Threshold above which we consider an item's historical stockout rate
# "elevated" and therefore worthy of a boost. Calibrated against the current
# dataset — per-item rates range from 9% (Coffee) to 20% (Muffins), so 15%
# fires for the riskiest SKUs without being trivially tripped by all of them.
HISTORICAL_STOCKOUT_THRESHOLD = 0.15

# Per-rule velocity multiplier — kept as a constant so it's easy to tune.
BOOST_PER_RULE = 1.20


@dataclass(frozen=True)
class ContextOutcome:
    adjusted_velocity: float
    factors: list[str]
    boost_multiplier: float


def adjust_velocity(
    predicted_velocity: float,
    *,
    is_peak_hour: bool,
    is_weekend: bool,
    historical_stockout_rate: float = 0.0,
) -> ContextOutcome:
    """Apply +20% per firing rule and return the boosted velocity.

    Rules (each multiplies velocity by ``BOOST_PER_RULE`` when true):
      * peak hour
      * weekend
      * historically elevated stockout rate for this item

    Rules compound multiplicatively, which matches how these signals
    reinforce each other in practice (a Saturday morning peak on a
    historically-out-of-stock item is worse than any single signal alone).
    """
    factors: list[str] = []
    multiplier = 1.0

    if is_peak_hour:
        multiplier *= BOOST_PER_RULE
        factors.append("Peak hour")

    if is_weekend:
        multiplier *= BOOST_PER_RULE
        factors.append("Weekend")

    if historical_stockout_rate >= HISTORICAL_STOCKOUT_THRESHOLD:
        multiplier *= BOOST_PER_RULE
        factors.append("Historical stockouts")

    adjusted = max(0.0, predicted_velocity * multiplier)

    return ContextOutcome(
        adjusted_velocity=adjusted,
        factors=factors,
        boost_multiplier=multiplier,
    )
