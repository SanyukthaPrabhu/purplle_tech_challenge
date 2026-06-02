from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timezone
from backend.database import Base

class VisitorSession(Base):
    __tablename__ = "visitor_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True) # Mapped to internal store uuid
    store_code = Column(String, nullable=False) # e.g. "STORE_BLR_002"
    visitor_id = Column(String, nullable=False) # "VIS_c8a2f1"
    camera_id = Column(String, nullable=False)
    entry_time = Column(DateTime(timezone=True), nullable=True)
    exit_time = Column(DateTime(timezone=True), nullable=True)
    total_dwell_ms = Column(Integer, nullable=True)
    is_staff = Column(Boolean, nullable=False, default=False)
    reentry_count = Column(Integer, nullable=False, default=0)
    session_hash = Column(String, unique=True, nullable=False) # store_code + visitor_id + date
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    store = relationship("Store", back_populates="sessions")
    events = relationship("Event", back_populates="session")
    transactions = relationship("Transaction", back_populates="session")
