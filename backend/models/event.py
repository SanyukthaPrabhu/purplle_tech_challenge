from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, BigInteger, Float, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timezone
from backend.database import Base

class Event(Base):
    __tablename__ = "events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True) # Mapped internal UUID
    store_code = Column(String, nullable=False) # e.g. "STORE_BLR_002"
    session_id = Column(UUID(as_uuid=True), ForeignKey("visitor_sessions.id"), nullable=True)
    camera_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    zone_id = Column(String, nullable=True) # string zone e.g. "SKINCARE"
    visitor_id = Column(String, nullable=False) # "VIS_c8a2f1"
    frame_number = Column(BigInteger, nullable=True)
    bbox = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=True)
    dwell_ms = Column(Integer, nullable=False, default=0)
    metadata_json = Column(JSON, nullable=True)
    idempotency_key = Column(String, unique=True, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    ingested_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    store = relationship("Store", back_populates="events")
    session = relationship("VisitorSession", back_populates="events")
