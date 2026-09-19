from datetime import datetime
from pydantic import BaseModel, Field


class HallOut(BaseModel):
    id: int
    name: str
    rows: int
    cols: int
    aisle_cols: list[int]
    model_config = {"from_attributes": True}


class ShowtimeOut(BaseModel):
    id: int
    hall_id: int
    film_title: str
    start_at: datetime
    hall_name: str | None = None
    model_config = {"from_attributes": True}


class HoldOut(BaseModel):
    id: int
    showtime_id: int
    order_code: str
    row: int
    start_col: int
    end_col: int
    party_size: int
    status: str
    model_config = {"from_attributes": True}


class HoldRequest(BaseModel):
    showtime_id: int
    party_size: int = Field(ge=1, le=12)
    preferred_row: int | None = None


class PreviewRequest(BaseModel):
    showtime_id: int
    party_size: int = Field(ge=1, le=12)
    preferred_row: int | None = None


class PlanOut(BaseModel):
    plan_id: str  # "leftmost" | "center"
    label: str
    row: int
    start_col: int
    end_col: int
    score: float  # center preference score, 0-100, higher = closer to hall centerline
    distance_to_center: float  # columns from span midpoint to hall centerline


class PreviewResponse(BaseModel):
    token: str
    expires_at: datetime
    ttl_seconds: int
    merged: bool  # true when both strategies picked the same coordinates
    plans: list[PlanOut]


class ConfirmRequest(BaseModel):
    token: str
    plan_id: str


class CancelRequest(BaseModel):
    token: str


class ConflictOut(BaseModel):
    id: int
    showtime_id: int
    party_size: int
    reason: str
    created_at: datetime
    model_config = {"from_attributes": True}


class SeatMapCell(BaseModel):
    row: int
    col: int
    is_aisle: bool
    occupied: bool
    heat: float


class SeatMapOut(BaseModel):
    showtime_id: int
    hall_name: str
    rows: int
    cols: int
    cells: list[SeatMapCell]
