from sqlalchemy import Column, String, JSON, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timezone
from backend.database import Base

class Store(Base):
    __tablename__ = "stores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    location = Column(String, nullable=True)
    timezone = Column(String, nullable=False, default="UTC")
    layout_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    zones = relationship("Zone", back_populates="store", cascade="all, delete-orphan")
    sessions = relationship("VisitorSession", back_populates="store")
    events = relationship("Event", back_populates="store")
    transactions = relationship("Transaction", back_populates="store")
    anomalies = relationship("Anomaly", back_populates="store")
