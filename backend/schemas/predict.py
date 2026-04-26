"""Schemas for POST /predict — shared by the route and the pipeline service."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class PredictRequest(BaseModel):
    """Live inventory snapshot for a single SKU."""

    item_id: str = Field(..., examples=["BK-01"])
    item_name: str = Field(..., examples=["Croissants"])
    current_stock: float = Field(..., ge=0, examples=[7])
    threshold: float = Field(..., gt=0, examples=[10])
    day_of_week: str = Field(..., examples=["Saturday"])
    hour: int = Field(..., ge=0, le=23, examples=[9])
    is_peak_hour: bool = Field(..., examples=[True])

    historical_stockout_rate: float | None = Field(
        default=None, ge=0.0, le=1.0, examples=[0.25]
    )
    store_id: str | None = Field(default=None, examples=["IND-01"])

    @field_validator("day_of_week")
    @classmethod
    def _strip_day(cls, v: str) -> str:
        return v.strip()


class PredictResponse(BaseModel):
    """Decision payload consumed by the dashboard."""

    urgency: str
    restock: int
    predicted_velocity: float
    adjusted_velocity: float
    explanation: str

    item_id: str
    item_name: str
    current_stock: float
    threshold: float
    coverage_hours: float
    stockout_risk: float
    context_factors: list[str]

    day_of_week: str
    hour: int
    is_peak_hour: bool
    historical_stockout_rate: float
