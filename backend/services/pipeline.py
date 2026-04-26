"""End-to-end inventory decision pipeline (preprocess → model → restock → LLM).

This is the deep module for `/predict`: the HTTP route is a thin shell that
validates input, delegates here, and schedules side effects. Unit tests and
callers that need a decision without going through FastAPI can import
`run_prediction` directly.
"""

from __future__ import annotations

from schemas.predict import PredictRequest, PredictResponse
from services.context_engine import adjust_velocity
from services.explain import generate_explanation
from services.inference import predict_velocity
from services.restock import compute_restock
from utils.preprocessing import (
    historical_stockout_rate_for,
    is_weekend,
    prepare_features,
)


async def run_prediction(request: PredictRequest) -> PredictResponse:
    """Run the full contextual inventory pipeline and return the decision body."""
    features = prepare_features(
        item_id=request.item_id,
        current_stock=request.current_stock,
        threshold=request.threshold,
        day_of_week=request.day_of_week,
        hour=request.hour,
        is_peak_hour=request.is_peak_hour,
    )

    predicted = predict_velocity(features)

    stockout_rate = request.historical_stockout_rate
    if stockout_rate is None:
        stockout_rate = historical_stockout_rate_for(request.item_id)

    context = adjust_velocity(
        predicted,
        is_peak_hour=features["is_peak_hour"],
        is_weekend=is_weekend(request.day_of_week),
        historical_stockout_rate=stockout_rate,
    )

    restock = compute_restock(
        adjusted_velocity=context.adjusted_velocity,
        current_stock=features["current_stock"],
        is_peak_hour=features["is_peak_hour"],
    )

    explanation_params = {
        "item_id": request.item_id,
        "item_name": request.item_name,
        "current_stock": features["current_stock"],
        "threshold": features["threshold"],
        "day_of_week": request.day_of_week,
        "hour": features["hour"],
        "is_peak_hour": request.is_peak_hour,
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
