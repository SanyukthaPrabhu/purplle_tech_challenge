"""
event_emitter.py — Event Emission to FastAPI Backend
CV Engineer Agent | Phase 2 (Strict Schema Alignment)
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
import httpx

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EventEnvelope:
    """Canonical event structure matching challenge grading schema exactly."""
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str
    timestamp: str
    zone_id: str | None = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "store_id": self.store_id,
            "camera_id": self.camera_id,
            "visitor_id": self.visitor_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "zone_id": self.zone_id,
            "dwell_ms": self.dwell_ms,
            "is_staff": self.is_staff,
            "confidence": self.confidence,
            "metadata": {
                "queue_depth": self.metadata.get("queue_depth"),
                "sku_zone": self.metadata.get("sku_zone") or self.zone_id,
                "session_seq": self.metadata.get("session_seq") or 1
            }
        }


class EventEmitter:
    """
    Collects CV pipeline events and POSTs them to the FastAPI backend.
    """

    def __init__(
        self,
        backend_url: str,
        store_id: str,
        camera_id: str,
        batch_size: int = 10,
        timeout_sec: float = 5.0,
        retry_count: int = 3,
        retry_delay_sec: float = 1.0,
    ):
        self.backend_url = backend_url.rstrip("/")
        self.store_id = store_id
        self.camera_id = camera_id
        self.batch_size = batch_size
        self.timeout_sec = timeout_sec
        self.retry_count = retry_count
        self.retry_delay_sec = retry_delay_sec

        self._buffer: list[EventEnvelope] = []
        self._client = httpx.Client(timeout=timeout_sec)
        self._stats = {"sent": 0, "failed": 0, "duplicates": 0}
        self._seq_counter: dict[int, int] = {} # track_id -> session_seq

    def _next_seq(self, track_id: int) -> int:
        self._seq_counter[track_id] = self._seq_counter.get(track_id, 0) + 1
        return self._seq_counter[track_id]

    def _get_visitor_id(self, track_id: int) -> str:
        return f"VIS_{hex(track_id)[2:]}"

    # ── Event Builders ───────────────────────────────────────────────────────

    def emit_entry(
        self,
        track_id: int,
        frame_number: int,
        bbox: dict | None = None,
        confidence: float = 0.0,
    ) -> None:
        self._enqueue(self._build(
            event_type="ENTRY",
            track_id=track_id,
            confidence=confidence,
        ))

    def emit_exit(
        self,
        track_id: int,
        frame_number: int,
        dwell_sec: float = 0.0,
        visited_zones: list[str] | None = None,
    ) -> None:
        self._enqueue(self._build(
            event_type="EXIT",
            track_id=track_id,
            dwell_ms=int(dwell_sec * 1000),
            metadata={"visited_zones": visited_zones or []},
        ))

    def emit_zone_enter(
        self,
        track_id: int,
        frame_number: int,
        zone_id: str,
        zone_name: str,
        zone_type: str,
    ) -> None:
        self._enqueue(self._build(
            event_type="ZONE_ENTER",
            track_id=track_id,
            zone_id=zone_name,
        ))

    def emit_zone_exit(
        self,
        track_id: int,
        frame_number: int,
        zone_id: str,
        zone_name: str,
        dwell_in_zone_sec: float = 0.0,
    ) -> None:
        self._enqueue(self._build(
            event_type="ZONE_EXIT",
            track_id=track_id,
            zone_id=zone_name,
            dwell_ms=int(dwell_in_zone_sec * 1000),
        ))

    def emit_zone_dwell(
        self,
        track_id: int,
        frame_number: int,
        zone_id: str,
        zone_name: str,
        dwell_sec: float,
        is_stationary: bool,
    ) -> None:
        self._enqueue(self._build(
            event_type="ZONE_DWELL",
            track_id=track_id,
            zone_id=zone_name,
            dwell_ms=int(dwell_sec * 1000),
        ))

    def emit_reentry(
        self,
        track_id: int,
        frame_number: int,
        reentry_count: int,
        gap_sec: float,
    ) -> None:
        self._enqueue(self._build(
            event_type="REENTRY",
            track_id=track_id,
            dwell_ms=int(gap_sec * 1000),
            metadata={"reentry_count": reentry_count},
        ))

    def emit_queue_join(
        self,
        track_id: int,
        frame_number: int,
        zone_id: str,
        zone_name: str,
        queue_depth: int,
    ) -> None:
        self._enqueue(self._build(
            event_type="BILLING_QUEUE_JOIN",
            track_id=track_id,
            zone_id=zone_name,
            metadata={"queue_depth": queue_depth},
        ))

    def emit_queue_abandon(
        self,
        track_id: int,
        frame_number: int,
        zone_id: str,
        zone_name: str,
        wait_sec: float,
        queue_depth: int,
    ) -> None:
        self._enqueue(self._build(
            event_type="BILLING_QUEUE_ABANDON",
            track_id=track_id,
            zone_id=zone_name,
            dwell_ms=int(wait_sec * 1000),
            metadata={"queue_depth": queue_depth},
        ))

    # ── Core ─────────────────────────────────────────────────────────────────

    def _build(
        self,
        event_type: str,
        track_id: int,
        zone_id: str | None = None,
        dwell_ms: int = 0,
        confidence: float = 0.0,
        metadata: dict | None = None,
    ) -> EventEnvelope:
        meta = metadata or {}
        meta["session_seq"] = self._next_seq(track_id)
        
        return EventEnvelope(
            store_id=self.store_id,
            camera_id=self.camera_id,
            visitor_id=self._get_visitor_id(track_id),
            event_type=event_type,
            timestamp=_now_iso(),
            zone_id=zone_id,
            dwell_ms=dwell_ms,
            is_staff=False, # Evaluated upstream in main pipeline
            confidence=confidence or 0.85,
            metadata=meta,
        )

    def _enqueue(self, event: EventEnvelope) -> None:
        self._buffer.append(event)
        logger.debug(
            f"Buffered {event.event_type} visitor={event.visitor_id} "
            f"buffer_size={len(self._buffer)}"
        )
        if len(self._buffer) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return

        batch = self._buffer.copy()
        self._buffer.clear()

        for event in batch:
            self._post_with_retry(event)

    def _post_with_retry(self, event: EventEnvelope) -> bool:
        url = f"{self.backend_url}/events/ingest"
        payload = event.to_dict()

        for attempt in range(self.retry_count):
            try:
                response = self._client.post(url, json=payload)
                if response.status_code == 201:
                    self._stats["sent"] += 1
                    return True
                elif response.status_code == 200:
                    self._stats["duplicates"] += 1
                    return True
                else:
                    logger.warning(
                        f"Unexpected response {response.status_code} for "
                        f"{event.event_type}: {response.text}"
                    )
            except httpx.TimeoutException:
                pass
            except httpx.RequestError as e:
                pass

            if attempt < self.retry_count - 1:
                delay = self.retry_delay_sec * (2 ** attempt)
                time.sleep(delay)

        self._stats["failed"] += 1
        return False

    def close(self) -> None:
        self.flush()
        self._client.close()

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
