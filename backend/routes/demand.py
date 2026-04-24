"""GET /demand-series — hourly demand profile from the historical CSV."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from services.demand_series import baseline_velocity, hourly_demand_profile

logger = logging.getLogger(__name__)
router = APIRouter()


class DemandPoint(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    demand: float
    samples: int


class DemandSeriesResponse(BaseModel):
    item_id: str
    day_of_week: str
    baseline: float
    series: list[DemandPoint]


@router.get(
    "/demand-series",
    response_model=DemandSeriesResponse,
    summary="Hourly demand profile for a SKU on a given day",
)
def demand_series(
    item_id: str = Query(..., examples=["BK-01"]),
    day_of_week: str = Query(..., examples=["Saturday"]),
    min_hour: int = Query(6, ge=0, le=23),
    max_hour: int = Query(22, ge=0, le=23),
) -> DemandSeriesResponse:
    """Return the mean hourly velocity (and sample count) per hour of the day.

    The frontend uses this to render the demand chart, which is a critical
    piece of context for the operator — it turns the raw velocity numbers
    into a recognizable "shape of the day".
    """
    if max_hour < min_hour:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="max_hour must be >= min_hour",
        )

    try:
        series = hourly_demand_profile(
            item_id=item_id,
            day_of_week=day_of_week,
            min_hour=min_hour,
            max_hour=max_hour,
        )
        base = baseline_velocity(item_id=item_id)
        return DemandSeriesResponse(
            item_id=item_id,
            day_of_week=day_of_week,
            baseline=base,
            series=[DemandPoint(**p) for p in series],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("demand_series failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="demand_series failed. Check server logs.",
        ) from exc
