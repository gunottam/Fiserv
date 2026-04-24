"""Hourly demand series service — reads the historical CSV on demand.

We intentionally re-read the file per request rather than caching in memory:
the dataset is tiny (~2.2k rows, <200 KB) and this keeps hot-reloading during
demos dead simple. If the file grows, swap this for a module-level DataFrame
loaded at import time.
"""

from __future__ import annotations

import csv
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

DATASET_PATH = Path(os.getenv("DATASET_PATH", "../dataset/dataset.csv"))


def _parse_hour(timestamp: str) -> int | None:
    """CSV stores timestamps as ``M/D/YYYY H:MM`` — grab the hour part."""
    try:
        time_part = timestamp.split(" ", 1)[1]
        return int(time_part.split(":", 1)[0])
    except (IndexError, ValueError):
        return None


def _iter_rows(
    path: Path,
    item_id: str | None,
    day_of_week: str | None,
) -> Iterable[dict[str, str]]:
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if item_id and row.get("item_id") != item_id:
                continue
            if day_of_week and row.get("day_of_week", "").lower() != day_of_week.lower():
                continue
            yield row


def hourly_demand_profile(
    item_id: str,
    day_of_week: str,
    *,
    min_hour: int = 6,
    max_hour: int = 22,
) -> list[dict[str, float | int]]:
    """Return ``[{hour, demand}]`` with the mean hourly velocity per hour.

    Only hours in ``[min_hour, max_hour]`` (inclusive) are returned, and any
    gap is backfilled with 0 so downstream charting stays dense. This matches
    typical store hours — tweak the bounds if you add overnight SKUs.
    """
    if not DATASET_PATH.is_file():
        logger.warning("Dataset not found at %s", DATASET_PATH)
        return []

    sums: dict[int, float] = defaultdict(float)
    counts: dict[int, int] = defaultdict(int)

    for row in _iter_rows(DATASET_PATH, item_id=item_id, day_of_week=day_of_week):
        hour = _parse_hour(row.get("timestamp", ""))
        if hour is None:
            continue
        try:
            v = float(row.get("hourly_velocity", 0))
        except ValueError:
            continue
        sums[hour] += v
        counts[hour] += 1

    out: list[dict[str, float | int]] = []
    for h in range(min_hour, max_hour + 1):
        mean = (sums[h] / counts[h]) if counts[h] else 0.0
        out.append({"hour": h, "demand": round(mean, 2), "samples": counts[h]})
    return out


def baseline_velocity(item_id: str, day_of_week: str | None = None) -> float:
    """Overall mean velocity for the item (optionally filtered by day).

    Used by the frontend to draw the "baseline" reference line on the chart.
    """
    if not DATASET_PATH.is_file():
        return 0.0

    total = 0.0
    n = 0
    for row in _iter_rows(DATASET_PATH, item_id=item_id, day_of_week=day_of_week):
        try:
            total += float(row.get("hourly_velocity", 0))
            n += 1
        except ValueError:
            continue
    return round(total / n, 2) if n else 0.0


def dataset_is_available() -> bool:
    return DATASET_PATH.is_file()
