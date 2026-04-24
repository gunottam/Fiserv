"""POST /predict — runs the end-to-end contextual inventory pipeline."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from services.context_engine import adjust_velocity
from services.explain import generate_explanation
from services.inference import predict_velocity
from services.restock import compute_restock
from utils.preprocessing import (
    historical_stockout_rate_for,
    is_weekend,
    prepare_features,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PredictRequest(BaseModel):
    """Live inventory snapshot for a single SKU."""

    item_id: str = Field(..., examples=["BK-01"])
    item_name: str = Field(..., examples=["Croissants"])
    current_stock: float = Field(..., ge=0, examples=[7])
    threshold: float = Field(..., gt=0, examples=[10])
    day_of_week: str = Field(..., examples=["Saturday"])
    hour: int = Field(..., ge=0, le=23, examples=[9])
    is_peak_hour: bool = Field(..., examples=[True])

    # Optional: if the caller passes a historical stockout rate (0.0–1.0),
    # it's used as the third boost signal. When omitted, the route looks the
    # value up from the training-derived item stats so the context engine
    # still has something meaningful to reason about.
    historical_stockout_rate: float | None = Field(
        default=None, ge=0.0, le=1.0, examples=[0.25]
    )

    @field_validator("day_of_week")
    @classmethod
    def _strip_day(cls, v: str) -> str:
        return v.strip()


class PredictResponse(BaseModel):
    """Decision payload consumed by the dashboard."""

    # Core fields defined in the spec.
    urgency: str
    restock: int
    predicted_velocity: float
    adjusted_velocity: float
    explanation: str

    # Supporting fields used by the UI for the context / risk cards.
    item_id: str
    item_name: str
    current_stock: float
    threshold: float
    coverage_hours: float
    stockout_risk: float
    context_factors: list[str]

    # Inputs echoed back so the frontend can hand the response straight to
    # /chat as the decision context without having to remember the request.
    day_of_week: str
    hour: int
    is_peak_hour: bool
    historical_stockout_rate: float


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/predict",
    response_model=PredictResponse,
    summary="Contextual restock decision for a single SKU",
)
async def predict(request: PredictRequest) -> PredictResponse:
    """Pipeline: preprocess → predict → context-adjust → restock → explain."""
    try:
        # 1) Normalize the raw payload into model-ready features.
        features = prepare_features(
            item_id=request.item_id,
            current_stock=request.current_stock,
            threshold=request.threshold,
            day_of_week=request.day_of_week,
            hour=request.hour,
            is_peak_hour=request.is_peak_hour,
        )

        # 2) Base velocity from the model (or heuristic fallback).
        predicted = predict_velocity(features)

        # If the caller didn't supply a historical rate, fill it in from the
        # dataset-derived item stats. This lets the context engine make a
        # grounded decision even for minimal payloads.
        stockout_rate = request.historical_stockout_rate
        if stockout_rate is None:
            stockout_rate = historical_stockout_rate_for(request.item_id)

        # 3) Apply real-world context multipliers.
        context = adjust_velocity(
            predicted,
            is_peak_hour=features["is_peak_hour"],
            is_weekend=is_weekend(request.day_of_week),
            historical_stockout_rate=stockout_rate,
        )

        # 4) Derive restock qty, urgency, coverage, and stockout risk.
        restock = compute_restock(
            adjusted_velocity=context.adjusted_velocity,
            current_stock=features["current_stock"],
            is_peak_hour=features["is_peak_hour"],
        )

        # 5) Groq-backed rationale (falls back to a template if unavailable).
        explanation_params = {
            "item_id": request.item_id,
            "item_name": request.item_name,
            "current_stock": features["current_stock"],
            "threshold": features["threshold"],
            "day_of_week": request.day_of_week,
            "hour": features["hour"],
            "is_peak_hour": features["is_peak_hour"],
            "predicted_velocity": predicted,
            "adjusted_velocity": context.adjusted_velocity,
            "coverage_hours": restock.coverage_hours,
            "stockout_risk": restock.stockout_risk,
            "urgency": restock.urgency,
            "restock": restock.restock_units,
            "context_factors": context.factors,
            "historical_stockout_rate": stockout_rate,
        }
        explanation = await generate_explanation(explanation_params)

        return PredictResponse(
            urgency=restock.urgency,
            restock=restock.restock_units,
            predicted_velocity=round(predicted, 2),
            adjusted_velocity=round(context.adjusted_velocity, 2),
            explanation=explanation,
            item_id=request.item_id,
            item_name=request.item_name,
            current_stock=features["current_stock"],
            threshold=features["threshold"],
            coverage_hours=restock.coverage_hours,
            stockout_risk=restock.stockout_risk,
            context_factors=context.factors,
            day_of_week=request.day_of_week,
            hour=features["hour"],
            is_peak_hour=features["is_peak_hour"],
            historical_stockout_rate=round(float(stockout_rate), 4),
        )

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — last-resort guard
        # Any unexpected failure in the pipeline gets logged with context and
        # surfaced as a 500 with a stable error shape. We never leak stack
        # traces to the client.
        logger.exception("Prediction pipeline failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Prediction pipeline failed. Check server logs for details.",
        ) from exc
