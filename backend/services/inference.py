"""Hourly-velocity prediction.

Loads a joblib-pickled sklearn regressor from ``MODEL_PATH`` at import time;
if the file is missing or the model's expected input shape doesn't match our
feature vector, we fall back to a deterministic heuristic based on day-of-week
and hour-of-day (optionally scaled by per-item mean velocity). The fallback
is good enough for demos and keeps the API contract stable while the ML
pipeline is still being built.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = Path(os.getenv("MODEL_PATH", "../models/model.pkl"))
ITEM_STATS_PATH = Path(os.getenv("ITEM_STATS_PATH", "../models/item_stats.json"))

BASE_HOURLY_VELOCITY = 10.0

# Weekly seasonality: bakeries skew heavy on the weekend.
DAY_MULTIPLIERS: dict[int, float] = {
    0: 0.90,  # Monday
    1: 0.95,  # Tuesday
    2: 1.00,  # Wednesday
    3: 1.05,  # Thursday
    4: 1.15,  # Friday
    5: 1.30,  # Saturday
    6: 1.20,  # Sunday
}

# Intra-day seasonality: tuned for food-retail patterns (morning rush, lunch,
# early-evening bump, dead of night).
HOUR_MULTIPLIERS: dict[range, float] = {
    range(0, 6): 0.30,
    range(6, 8): 0.90,
    range(8, 11): 1.50,   # morning peak
    range(11, 14): 1.30,  # lunch
    range(14, 17): 1.00,
    range(17, 20): 1.15,  # early evening
    range(20, 24): 0.70,
}


def _hour_multiplier(hour: int) -> float:
    for bucket, mult in HOUR_MULTIPLIERS.items():
        if hour in bucket:
            return mult
    return 1.0


def _load_model() -> Any | None:
    """Attempt to load a joblib model; return None on any failure.

    We import joblib lazily so the rest of the API is not blocked if the
    package is unavailable in a minimal deployment.
    """
    if not MODEL_PATH.is_file():
        logger.info("No model file at %s — using heuristic fallback.", MODEL_PATH)
        return None
    try:
        import joblib  # local import keeps startup light

        model = joblib.load(MODEL_PATH)
        logger.info("Loaded inference model from %s", MODEL_PATH)
        return model
    except Exception as exc:  # noqa: BLE001 — we want to swallow all load errors
        logger.warning("Could not load model from %s (%s). Using fallback.", MODEL_PATH, exc)
        return None


def _load_item_means() -> dict[str, float]:
    """Per-item mean velocity from the training set — used by the fallback."""
    if not ITEM_STATS_PATH.is_file():
        return {}
    try:
        data = json.loads(ITEM_STATS_PATH.read_text())
        return {
            item_id: float(info.get("mean_velocity", 0.0))
            for item_id, info in data.get("items", {}).items()
        }
    except Exception:  # noqa: BLE001
        return {}


_MODEL: Any | None = _load_model()
_ITEM_MEANS: dict[str, float] = _load_item_means()


def _dummy_predict(day_idx: int, hour: int, item_id: str | None = None) -> float:
    """Heuristic predictor used when no trained model is available.

    ``velocity = base * day_multiplier * hour_multiplier``

    When we have item-level stats from a previous training run, we replace
    the global base rate with that item's mean velocity — this keeps the
    magnitudes realistic without needing the model itself to be loadable.
    """
    day_m = DAY_MULTIPLIERS.get(day_idx, 1.0)
    hour_m = _hour_multiplier(hour)
    base = _ITEM_MEANS.get(item_id or "", BASE_HOURLY_VELOCITY)
    return base * day_m * hour_m


def predict_velocity(features: dict[str, Any]) -> float:
    """Return predicted hourly velocity for the given feature dict.

    Uses the loaded model if available. Any exception at prediction time
    degrades gracefully to the heuristic so the endpoint never 500s because
    of an ML issue.
    """
    if _MODEL is not None:
        try:
            vector: np.ndarray = features["vector"]
            prediction = float(_MODEL.predict(vector)[0])
            return max(0.0, prediction)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Model prediction failed (%s). Falling back.", exc)

    return _dummy_predict(
        day_idx=features["day_idx"],
        hour=features["hour"],
        item_id=features.get("item_id"),
    )


def model_is_loaded() -> bool:
    """Small helper so the health endpoint can report model status."""
    return _MODEL is not None
