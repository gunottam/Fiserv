"""Multi-algorithm benchmark + trainer for the hourly-velocity regressor.

Trains a set of candidate models on the historical CSV, evaluates each on a
chronological hold-out split (so the score reflects real forecasting skill),
then saves the winner as the production ``models/model.pkl``.

Run from the backend directory:

    cd backend
    source .venv/bin/activate
    python -m scripts.train_model

Artifacts emitted into the repo-root ``models/`` folder:

* ``model.pkl``              — joblib-pickled winning model.
* ``item_stats.json``        — per-item encoding + historical stockout rate +
                               mean velocity + winner metrics + feature order.
* ``comparison_report.json`` — full side-by-side results for every candidate.

Key design choices:

1. **Chronological split** — we train on the earliest 80% of rows (sorted by
   timestamp) and evaluate on the most recent 20%. A random shuffle would
   leak future signal into the past and inflate scores.
2. **No ``is_stock_out`` in features** — that's the outcome variable, not an
   input you have at alert time. Including it is data leakage.
3. **Stateless features only** — no rolling lag features. The ``/predict``
   endpoint is called with a single JSON snapshot, so the model's feature
   set must be fully computable from that snapshot.

Feature vector (order is the contract with utils.preprocessing):

    [day_idx, hour, is_peak_hour, is_weekend, current_stock, threshold, item_idx]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

FEATURE_ORDER: list[str] = [
    "day_idx",
    "hour",
    "is_peak_hour",
    "is_weekend",
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
WEEKEND_IDS = {5, 6}


# ---------------------------------------------------------------------------
# CLI + data prep
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark candidate models and save the winner."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("../dataset/bakery_inventory.csv"),
        help="Training CSV (default: ../dataset/bakery_inventory.csv)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("../models"),
        help="Where to write model.pkl + stats (default: ../models)",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Fraction of rows (chronologically trailing) used for evaluation.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for the tree-based learners.",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Comma-separated list to restrict candidates (e.g. 'xgboost,lightgbm').",
    )
    return parser.parse_args()


def _to_bool(series: pd.Series) -> pd.Series:
    """Handle both ``TRUE/FALSE`` (old CSV) and ``True/False`` (new CSV)."""
    if series.dtype == bool:
        return series
    return series.astype(str).str.strip().str.upper().eq("TRUE")


def _prepare_frame(raw: pd.DataFrame) -> pd.DataFrame:
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

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["hour"] = df["timestamp"].dt.hour.astype(int)
    df["day_idx"] = (
        df["day_of_week"].astype(str).str.strip().str.lower().map(DAY_MAP).astype(int)
    )
    df["is_weekend"] = df["day_idx"].isin(WEEKEND_IDS).astype(int)
    df["is_peak_hour"] = _to_bool(df["is_peak_hour"]).astype(int)
    df["is_stock_out"] = _to_bool(df["is_stock_out"]).astype(int)

    df["hourly_velocity"] = df["hourly_velocity"].clip(lower=0).astype(float)
    df["current_stock"] = df["current_stock"].clip(lower=0).astype(float)
    df["threshold"] = df["threshold"].clip(lower=1).astype(float)

    # Sort chronologically — the train/test split relies on this order.
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _build_item_index(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
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


# ---------------------------------------------------------------------------
# Candidate registry
# ---------------------------------------------------------------------------


def _candidate_factories(seed: int) -> dict[str, Callable[[], Any]]:
    """Return a mapping of name → factory that produces an untrained estimator.

    We build each model lazily inside the factory so an ImportError on an
    optional dep (e.g. xgboost missing libomp) doesn't break the run — we
    just skip that candidate.
    """

    def _ridge() -> Any:
        return Ridge(alpha=1.0, random_state=seed)

    def _rf() -> Any:
        return RandomForestRegressor(
            n_estimators=200,
            max_depth=16,
            min_samples_leaf=4,
            n_jobs=-1,
            random_state=seed,
        )

    def _gbr() -> Any:
        return GradientBoostingRegressor(
            n_estimators=400,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.9,
            random_state=seed,
        )

    def _xgb() -> Any:
        from xgboost import XGBRegressor

        return XGBRegressor(
            n_estimators=500,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_lambda=1.0,
            objective="reg:squarederror",
            tree_method="hist",
            n_jobs=-1,
            random_state=seed,
        )

    def _lgbm() -> Any:
        from lightgbm import LGBMRegressor

        return LGBMRegressor(
            n_estimators=600,
            max_depth=-1,
            num_leaves=63,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=seed,
            n_jobs=-1,
            verbose=-1,
        )

    return {
        "ridge":            _ridge,
        "random_forest":    _rf,
        "gradient_boost":   _gbr,
        "xgboost":          _xgb,
        "lightgbm":         _lgbm,
    }


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _evaluate(
    name: str,
    factory: Callable[[], Any],
    X_tr: np.ndarray,
    y_tr: np.ndarray,
    X_te: np.ndarray,
    y_te: np.ndarray,
) -> dict[str, Any] | None:
    """Fit a model, score it, and return a metrics dict (or None on error)."""
    try:
        model = factory()
    except ImportError as exc:
        print(f"  [{name:<15}] skipped — {exc}")
        return None

    t0 = time.perf_counter()
    model.fit(X_tr, y_tr)
    fit_seconds = time.perf_counter() - t0

    t0 = time.perf_counter()
    pred = model.predict(X_te)
    predict_seconds = time.perf_counter() - t0

    mae = float(mean_absolute_error(y_te, pred))
    rmse = float(np.sqrt(mean_squared_error(y_te, pred)))
    r2 = float(r2_score(y_te, pred))

    print(
        f"  [{name:<15}] MAE={mae:6.3f}  RMSE={rmse:6.3f}  "
        f"R²={r2:6.4f}  fit={fit_seconds:5.1f}s  predict={predict_seconds:4.2f}s"
    )

    return {
        "name": name,
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "fit_seconds": round(fit_seconds, 2),
        "predict_seconds": round(predict_seconds, 3),
        "model": model,
    }


def _pretty_table(rows: list[dict[str, Any]]) -> str:
    headers = ["rank", "candidate", "MAE", "RMSE", "R²", "fit s", "pred s"]
    col_widths = [4, 16, 9, 9, 8, 8, 8]

    def line(parts: list[str]) -> str:
        return "  ".join(p.ljust(w) for p, w in zip(parts, col_widths))

    out = [line(headers), line(["─" * w for w in col_widths])]
    for i, r in enumerate(rows, start=1):
        out.append(
            line(
                [
                    str(i),
                    r["name"],
                    f"{r['mae']:.3f}",
                    f"{r['rmse']:.3f}",
                    f"{r['r2']:.4f}",
                    f"{r['fit_seconds']:.1f}",
                    f"{r['predict_seconds']:.2f}",
                ]
            )
        )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def train(
    dataset_path: Path,
    out_dir: Path,
    test_size: float,
    seed: int,
    only: set[str] | None,
) -> None:
    if not dataset_path.is_file():
        raise FileNotFoundError(f"Dataset not found at {dataset_path.resolve()}")

    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading dataset: {dataset_path}")
    raw = pd.read_csv(dataset_path)
    df = _prepare_frame(raw)
    print(f"  rows: {len(df):,}  date range: {df['timestamp'].min()} → {df['timestamp'].max()}")

    item_index = _build_item_index(df)
    df["item_idx"] = df["item_id"].map(lambda x: item_index[x]["index"])
    print(f"  items: {len(item_index)}  features: {FEATURE_ORDER}")

    X = df[FEATURE_ORDER].to_numpy(dtype=float)
    y = df["hourly_velocity"].to_numpy(dtype=float)

    # Chronological split — the frame is already sorted by timestamp.
    cut = int(len(df) * (1.0 - test_size))
    X_tr, X_te = X[:cut], X[cut:]
    y_tr, y_te = y[:cut], y[cut:]
    print(f"  train: {len(X_tr):,}  test: {len(X_te):,}  (chronological)")

    # Sanity baseline: always predict the training mean.
    baseline_mae = float(
        mean_absolute_error(y_te, np.full_like(y_te, float(np.mean(y_tr))))
    )
    print(f"  naive-mean-MAE baseline: {baseline_mae:.3f} (upper bound on useful error)")

    print()
    print("Benchmarking candidates on held-out tail:")
    factories = _candidate_factories(seed)
    if only:
        factories = {k: v for k, v in factories.items() if k in only}
        if not factories:
            raise ValueError(f"No candidates matched --only={only}")

    results: list[dict[str, Any]] = []
    for name, factory in factories.items():
        result = _evaluate(name, factory, X_tr, y_tr, X_te, y_te)
        if result is not None:
            results.append(result)

    if not results:
        raise RuntimeError("No candidates completed — nothing to save.")

    results.sort(key=lambda r: r["mae"])
    winner = results[0]

    print()
    print("Ranking by test MAE (lower is better):")
    print(_pretty_table(results))
    print()
    print(
        f"Winner: {winner['name']}  "
        f"(MAE {winner['mae']:.3f}, {(baseline_mae - winner['mae']) / baseline_mae * 100:.0f}% below naive baseline)"
    )

    model_path = out_dir / "model.pkl"
    stats_path = out_dir / "item_stats.json"
    report_path = out_dir / "comparison_report.json"

    joblib.dump(winner["model"], model_path)

    stats = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": str(dataset_path),
        "n_rows": int(len(df)),
        "feature_order": FEATURE_ORDER,
        "winner": {
            "name": winner["name"],
            "test_mae": winner["mae"],
            "test_rmse": winner["rmse"],
            "test_r2": winner["r2"],
            "baseline_mean_mae": round(baseline_mae, 3),
            "fit_seconds": winner["fit_seconds"],
        },
        "items": item_index,
    }
    stats_path.write_text(json.dumps(stats, indent=2))

    report = {
        "trained_at": stats["trained_at"],
        "dataset": str(dataset_path),
        "n_train": int(len(X_tr)),
        "n_test": int(len(X_te)),
        "baseline_mean_mae": round(baseline_mae, 3),
        "feature_order": FEATURE_ORDER,
        "candidates": [
            {k: v for k, v in r.items() if k != "model"} for r in results
        ],
        "winner": winner["name"],
    }
    report_path.write_text(json.dumps(report, indent=2))

    print()
    print(f"  saved model   : {model_path}")
    print(f"  saved stats   : {stats_path}")
    print(f"  saved report  : {report_path}")


def main() -> None:
    args = _parse_args()
    only = (
        {s.strip() for s in args.only.split(",") if s.strip()}
        if args.only
        else None
    )
    try:
        train(
            dataset_path=args.dataset,
            out_dir=args.out_dir,
            test_size=args.test_size,
            seed=args.seed,
            only=only,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
