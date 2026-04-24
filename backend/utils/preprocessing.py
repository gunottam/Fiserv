"""Input normalization and feature preparation.

This layer sits between the raw request payload and the inference model so that
downstream services can assume cleaned, typed values. Keeping it here means any
retrained model can reuse the exact same encoding.

The ``item_idx`` feature is populated from ``models/item_stats.json`` which is
produced by ``scripts/train_model.py``. If that file is missing (first run, no
training yet), we fall back to a deterministic hash so the feature vector
shape is still correct and the API keeps working.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

DAY_OF_WEEK_MAP: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

WEEKEND_DAYS: frozenset[int] = frozenset({5, 6})

# Feature order MUST match scripts/train_model.py FEATURE_ORDER.
FEATURE_ORDER: tuple[str, ...] = (
    "day_idx",
    "hour",
    "is_peak_hour",
    "is_weekend",
    "current_stock",
    "threshold",
    "item_idx",
)

ITEM_STATS_PATH = Path(os.getenv("ITEM_STATS_PATH", "../models/item_stats.json"))


def _load_item_stats() -> dict[str, Any]:
    """Read the item stats JSON written by the training script.

    Returns an empty dict on any failure — the caller must be robust to that.
    """
    if not ITEM_STATS_PATH.is_file():
        logger.info(
            "No item_stats.json at %s — item features will use a hash fallback.",
            ITEM_STATS_PATH,
        )
        return {}
    try:
        return json.loads(ITEM_STATS_PATH.read_text())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read %s (%s) — using empty stats.", ITEM_STATS_PATH, exc)
        return {}


_ITEM_STATS: dict[str, Any] = _load_item_stats()


def encode_day(day_of_week: str | None) -> int:
    """Map a day name to an integer index (Monday=0 … Sunday=6).

    Unknown or missing inputs fall back to Monday (0) so the pipeline never
    crashes on a malformed request — the preference is "always answer".
    """
    if not day_of_week:
        return 0
    return DAY_OF_WEEK_MAP.get(day_of_week.strip().lower(), 0)


def is_weekend(day_of_week: str | None) -> bool:
    return encode_day(day_of_week) in WEEKEND_DAYS


def clamp_hour(hour: Any) -> int:
    """Coerce hour to a safe 0-23 integer."""
    try:
        h = int(hour)
    except (TypeError, ValueError):
        return 12
    return max(0, min(23, h))


def safe_float(value: Any, default: float = 0.0) -> float:
    """Parse floats tolerantly — empty strings and None become the default."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def encode_item(item_id: str) -> int:
    """Return the integer index the model was trained on for this SKU.

    Unknown items get the deterministic hash-based fallback. This keeps the
    feature vector shape stable even for items that weren't in the training
    set — the model predictions will be less accurate for them, but the API
    still responds and the pipeline never throws.
    """
    items = _ITEM_STATS.get("items", {})
    info = items.get(item_id)
    if info is not None and "index" in info:
        return int(info["index"])

    # Fallback: stable hash bucketed into a small space. We use a small
    # modulus so unknown items land near the known index range and don't
    # surprise the tree splits too dramatically.
    return abs(hash(item_id)) % 16


def historical_stockout_rate_for(item_id: str) -> float:
    """Look up the dataset-derived historical stockout rate for a SKU.

    Returns 0.0 when the item is unknown. Used by the route to auto-fill the
    ``historical_stockout_rate`` input when the client didn't provide one.
    """
    info = _ITEM_STATS.get("items", {}).get(item_id, {})
    return float(info.get("stockout_rate", 0.0))


def item_stats_loaded() -> bool:
    """Small helper for the health endpoint."""
    return bool(_ITEM_STATS.get("items"))


def prepare_features(
    *,
    item_id: str,
    current_stock: float,
    threshold: float,
    day_of_week: str | None,
    hour: int,
    is_peak_hour: bool,
) -> dict[str, Any]:
    """Return a normalized feature dict + numpy row for the inference model.

    ``vector`` has shape (1, 7) matching ``FEATURE_ORDER``.
    """
    day_idx = encode_day(day_of_week)
    safe_hour = clamp_hour(hour)
    stock = max(0.0, safe_float(current_stock))
    thresh = max(1.0, safe_float(threshold, default=1.0))
    peak = bool(is_peak_hour)
    weekend = day_idx in WEEKEND_DAYS
    item_idx = encode_item(item_id)

    vector = np.array(
        [[day_idx, safe_hour, int(peak), int(weekend), stock, thresh, item_idx]],
        dtype=float,
    )

    return {
        "day_idx": day_idx,
        "hour": safe_hour,
        "is_peak_hour": peak,
        "is_weekend": weekend,
        "current_stock": stock,
        "threshold": thresh,
        "item_id": item_id,
        "item_idx": item_idx,
        "vector": vector,
    }
