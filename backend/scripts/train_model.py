"""Train the hourly-velocity regressor and emit artifacts consumed by the API.

Run from the backend directory (so relative paths resolve):

    cd backend
    source .venv/bin/activate
    python -m scripts.train_model

Artifacts produced (both land in the repo-root ``models/`` folder):

* ``models/model.pkl``         — joblib-pickled sklearn regressor.
* ``models/item_stats.json``   — per-item metadata used at inference time
                                 (integer encoding, historical stockout
                                 rate, mean velocity, training metrics,
                                 feature order).

Feature vector (order must match inference.py exactly):

    [day_idx, hour, is_peak_hour, current_stock, threshold, item_idx]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

# The feature order is the contract between training and inference.
# Keep this list in lock-step with utils.preprocessing.prepare_features.
FEATURE_ORDER: list[str] = [
    "day_idx",
    "hour",
    "is_peak_hour",
    "current_stock",
    "threshold",
    "item_idx",
]

DAY_MAP: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the inventory velocity model.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("../dataset/dataset.csv"),
        help="Path to the training CSV (default: ../dataset/dataset.csv)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("../models"),
        help="Directory to write model.pkl + item_stats.json (default: ../models)",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Fraction of rows held out for the evaluation split.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )
    return parser.parse_args()


def _to_bool(series: pd.Series) -> pd.Series:
    """CSV booleans come in as strings like 'TRUE'/'FALSE' — normalize them."""
    return series.astype(str).str.upper().eq("TRUE")


def _prepare_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Decode raw CSV columns into typed features the model expects."""
    df = raw.copy()
    df.columns = [c.strip() for c in df.columns]

    required = {
        "timestamp",
        "item_id",
        "item_name",
        "current_stock",
        "threshold",
        "hourly_velocity",
        "day_of_week",
        "is_peak_hour",
        "is_stock_out",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {sorted(missing)}")

    df["hour"] = pd.to_datetime(df["timestamp"]).dt.hour.astype(int)
    df["day_idx"] = (
        df["day_of_week"].astype(str).str.strip().str.lower().map(DAY_MAP).astype(int)
    )
    df["is_peak_hour"] = _to_bool(df["is_peak_hour"]).astype(int)
    df["is_stock_out"] = _to_bool(df["is_stock_out"]).astype(int)

    # Keep training targets non-negative and stock/threshold well-defined.
    df["hourly_velocity"] = df["hourly_velocity"].clip(lower=0)
    df["current_stock"] = df["current_stock"].clip(lower=0)
    df["threshold"] = df["threshold"].clip(lower=1)

    return df


def _build_item_index(df: pd.DataFrame) -> dict[str, dict]:
    """Create the canonical item encoding + per-item historical stats."""
    # Sort deterministically so the integer index is stable across retrains.
    items = (
        df.groupby(["item_id", "item_name"])
        .agg(
            stockout_rate=("is_stock_out", "mean"),
            mean_velocity=("hourly_velocity", "mean"),
            n_rows=("item_id", "size"),
        )
        .reset_index()
        .sort_values("item_id")
        .reset_index(drop=True)
    )

    return {
        row.item_id: {
            "name": row.item_name,
            "index": int(idx),
            "stockout_rate": round(float(row.stockout_rate), 4),
            "mean_velocity": round(float(row.mean_velocity), 3),
            "n_rows": int(row.n_rows),
        }
        for idx, row in items.iterrows()
    }


def train(
    dataset_path: Path,
    out_dir: Path,
    test_size: float,
    seed: int,
) -> None:
    if not dataset_path.is_file():
        raise FileNotFoundError(f"Dataset not found at {dataset_path.resolve()}")

    out_dir.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(dataset_path)
    df = _prepare_frame(raw)

    item_index = _build_item_index(df)
    df["item_idx"] = df["item_id"].map(lambda x: item_index[x]["index"])

    X = df[FEATURE_ORDER].to_numpy(dtype=float)
    y = df["hourly_velocity"].to_numpy(dtype=float)

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=test_size, random_state=seed
    )

    # Gradient boosting handles the mix of integer-encoded categoricals and
    # numeric features nicely without needing one-hot encoding at this scale.
    model = GradientBoostingRegressor(
        n_estimators=400,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.9,
        random_state=seed,
    )
    model.fit(X_tr, y_tr)

    pred = model.predict(X_te)
    mae = mean_absolute_error(y_te, pred)
    r2 = r2_score(y_te, pred)

    baseline = float(np.mean(y_tr))
    baseline_mae = mean_absolute_error(y_te, np.full_like(y_te, baseline))

    model_path = out_dir / "model.pkl"
    stats_path = out_dir / "item_stats.json"

    joblib.dump(model, model_path)

    stats = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": str(dataset_path),
        "n_rows": int(len(df)),
        "feature_order": FEATURE_ORDER,
        "metrics": {
            "test_mae": round(float(mae), 3),
            "test_r2": round(float(r2), 4),
            "baseline_mean_mae": round(float(baseline_mae), 3),
        },
        "items": item_index,
    }
    stats_path.write_text(json.dumps(stats, indent=2))

    print("=" * 60)
    print("Training complete")
    print(f"  rows           : {len(df):,}")
    print(f"  features       : {FEATURE_ORDER}")
    print(f"  test MAE       : {mae:.3f} units/hr")
    print(f"  test R²        : {r2:.3f}")
    print(f"  naive-mean MAE : {baseline_mae:.3f} (upper bound on error)")
    print()
    print(f"  saved model    : {model_path}")
    print(f"  saved stats    : {stats_path}")
    print("=" * 60)


def main() -> None:
    args = _parse_args()
    try:
        train(
            dataset_path=args.dataset,
            out_dir=args.out_dir,
            test_size=args.test_size,
            seed=args.seed,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
