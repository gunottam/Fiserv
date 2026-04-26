"""POST /predict — HTTP shell over the inventory decision pipeline."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from schemas.predict import PredictRequest, PredictResponse
from services.pipeline import run_prediction
from services.telegram import send_telegram_alert

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/predict",
    response_model=PredictResponse,
    summary="Contextual restock decision for a single SKU",
)
async def predict(
    request: PredictRequest,
    background_tasks: BackgroundTasks,
) -> PredictResponse:
    """Pipeline: preprocess → predict → context-adjust → restock → explain.

    Telegram notifications (if configured) run in ``BackgroundTasks`` after
    the response is ready so the client never waits on external I/O.
    """
    try:
        response = await run_prediction(request)

        background_tasks.add_task(
            send_telegram_alert,
            {
                "urgency": response.urgency,
                "item_id": response.item_id,
                "item_name": response.item_name,
                "store_id": request.store_id,
                "current_stock": response.current_stock,
                "threshold": response.threshold,
                "adjusted_velocity": response.adjusted_velocity,
                "coverage_hours": response.coverage_hours,
                "restock": response.restock,
                "explanation": response.explanation,
                "context_factors": response.context_factors,
                "day_of_week": response.day_of_week,
                "hour": response.hour,
                "is_peak_hour": response.is_peak_hour,
            },
        )

        return response

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — last-resort guard
        logger.exception("Prediction pipeline failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Prediction pipeline failed. Check server logs for details.",
        ) from exc
