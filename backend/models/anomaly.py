from sqlalchemy import Column, String, DateTime, ForeignKey, Float, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timezone
from backend.database import Base

class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    anomaly_type = Column(String, nullable=False) # QUEUE_SPIKE | CONVERSION_DROP | DEAD_ZONE
    severity = Column(String, nullable=False) # LOW | MEDIUM | HIGH | CRITICAL
    description = Column(String, nullable=True)
    metric_value = Column(Float, nullable=True)
    threshold_value = Column(Float, nullable=True)
    suggested_action = Column(String, nullable=True)
    zone_id = Column(UUID(as_uuid=True), ForeignKey("zones.id"), nullable=True)
    resolved = Column(Boolean, nullable=False, default=False)
    detected_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    store = relationship("Store", back_populates="anomalies")
    zone = relationship("Zone", back_populates="anomalies")
