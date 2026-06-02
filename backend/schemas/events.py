"""
schemas/events.py — Pydantic Event Models
Event Design Agent | Phase 3 (Strict Challenge Alignment)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Union
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class EventType(str, Enum):
    ENTRY                  = "ENTRY"
    EXIT                   = "EXIT"
    ZONE_ENTER             = "ZONE_ENTER"
    ZONE_EXIT              = "ZONE_EXIT"
    ZONE_DWELL             = "ZONE_DWELL"
    REENTRY                = "REENTRY"
    BILLING_QUEUE_JOIN     = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON  = "BILLING_QUEUE_ABANDON"


# ─────────────────────────────────────────────────────────────────────────────
# Metadata Model
# ─────────────────────────────────────────────────────────────────────────────

class EventMetadata(BaseModel):
    queue_depth: int | None = Field(None, description="Current queue depth for queue events")
    sku_zone: str | None = Field(None, description="SKU zone name/label from layout")
    session_seq: int = Field(1, ge=1, description="Sequential index of this event in visitor session")


# ─────────────────────────────────────────────────────────────────────────────
# Base Event Model
# ─────────────────────────────────────────────────────────────────────────────

class EventIngestRequest(BaseModel):
    """
    Ingest Request matching challenge schema exactly.
    """
    event_id:        UUID              = Field(default_factory=uuid4)
    store_id:        str               = Field(..., description="Store Code e.g. STORE_BLR_002")
    camera_id:       str               = Field(..., description="CCTV camera code")
    visitor_id:      str               = Field(..., description="Re-ID token e.g. VIS_c8a2f1")
    event_type:      EventType
    timestamp:       datetime          = Field(..., description="ISO-8601 UTC date string")
    zone_id:         str | None        = Field(None, description="Zone name/ID, null for ENTRY/EXIT")
    dwell_ms:        int               = Field(0, ge=0, description="Dwell time in milliseconds")
    is_staff:        bool              = Field(False, description="Flag for store employees")
    confidence:      float             = Field(0.0, ge=0.0, le=1.0)
    metadata:        EventMetadata     = Field(default_factory=EventMetadata)

    @field_validator("timestamp")
    @classmethod
    def ensure_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "event_id": "550e8400-e29b-41d4-a716-446655440000",
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_c8a2f1",
                "event_type": "ZONE_DWELL",
                "timestamp": "2026-03-03T14:22:10Z",
                "zone_id": "SKINCARE",
                "dwell_ms": 8400,
                "is_staff": False,
                "confidence": 0.91,
                "metadata": {
                    "queue_depth": None,
                    "sku_zone": "MOISTURISER",
                    "session_seq": 5
                }
            }
        }
    }


class EventIngestResponse(BaseModel):
    status: Literal["accepted", "duplicate"]
    event_id: UUID
