from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID
from typing import List

class PeriodSchema(BaseModel):
    from_time: datetime = Field(..., alias="from")
    to_time: datetime = Field(..., alias="to")

    class Config:
        populate_by_name = True

class MetricsResponse(BaseModel):
    store_id: UUID
    period: PeriodSchema
    unique_visitors: int
    conversion_rate: float
    avg_dwell_sec: float
    current_queue_depth: int
    abandonment_rate: float
    reentry_count: int

class FunnelStep(BaseModel):
    name: str
    count: int

class FunnelResponse(BaseModel):
    steps: List[FunnelStep]
    drop_off_rates: List[float]

class ZoneHeatmapData(BaseModel):
    zone_id: UUID
    zone_name: str
    density_matrix: List[List[int]]
    avg_dwell_sec: float

class HeatmapResponse(BaseModel):
    grid_resolution: int
    zones: List[ZoneHeatmapData]
