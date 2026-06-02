from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import List, Optional

class AnomalyResponse(BaseModel):
    id: UUID
    type: str
    severity: str
    description: Optional[str] = None
    metric_value: Optional[float] = None
    threshold_value: Optional[float] = None
    suggested_action: Optional[str] = None
    detected_at: datetime
    resolved: bool
    resolved_at: Optional[datetime] = None

class AnomalyListResponse(BaseModel):
    anomalies: List[AnomalyResponse]
