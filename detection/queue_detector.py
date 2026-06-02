"""
queue_detector.py — Billing Queue Detection
CV Engineer Agent | Phase 2

Responsibilities:
  - Monitor person count in BILLING zone
  - Detect queue joins and abandons
  - Emit BILLING_QUEUE_JOIN / BILLING_QUEUE_ABANDON events
  - Track queue depth time series

Queue Join Logic:
  When a track enters the BILLING zone → BILLING_QUEUE_JOIN

Queue Abandon Logic:
  When a track exits the BILLING zone AND:
    - No corresponding transaction event for that track
    - Time inside billing zone > abandon_patience_sec
  → BILLING_QUEUE_ABANDON

Edge Cases Handled:
  - Track briefly entering/exiting (noise filter via min_queue_frames)
  - Group entry: each track counted individually
  - Staff tracks excluded upstream via StaffFilter
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class QueueEvent:
    event_type: str                   # BILLING_QUEUE_JOIN | BILLING_QUEUE_ABANDON
    track_id: int
    zone_id: str
    zone_name: str
    queue_depth: int                  # current queue depth at time of event
    wait_sec: float                   # time spent in queue
    frame_number: int
    extra: dict = field(default_factory=dict)


@dataclass
class _QueueRecord:
    track_id: int
    join_time: float
    join_frame: int
    purchased: bool = False
    frames_in_queue: int = 0


class QueueDetector:
    """
    Monitors BILLING zones for queue join/abandon events.

    Integration:
        - Called by main pipeline on every ZONE_ENTER / ZONE_EXIT event
        - Also called per-frame to update queue depth
        - Transactions from POS system mark a session as "purchased"
          (so exit without purchase = abandon)
    """

    def __init__(
        self,
        billing_zone_id: str,
        billing_zone_name: str,
        abandon_patience_sec: float = 120.0,
        min_queue_frames: int = 5,        # debounce: min frames in zone to count
    ):
        self.billing_zone_id = billing_zone_id
        self.billing_zone_name = billing_zone_name
        self.abandon_patience_sec = abandon_patience_sec
        self.min_queue_frames = min_queue_frames

        self._in_queue: dict[int, _QueueRecord] = {}   # track_id → record
        self._purchased_tracks: set[int] = set()        # tracks with confirmed purchase

    # ── Zone Events ──────────────────────────────────────────────────────────

    def on_zone_enter(
        self,
        track_id: int,
        zone_id: str,
        zone_name: str,
        frame_number: int,
        timestamp: float | None = None,
    ) -> QueueEvent | None:
        """Returns BILLING_QUEUE_JOIN if track enters billing zone."""
        if zone_id != self.billing_zone_id:
            return None

        ts = timestamp or time.time()
        self._in_queue[track_id] = _QueueRecord(
            track_id=track_id,
            join_time=ts,
            join_frame=frame_number,
        )
        depth = len(self._in_queue)
        logger.info(f"Track {track_id}: BILLING_QUEUE_JOIN depth={depth}")

        return QueueEvent(
            event_type="BILLING_QUEUE_JOIN",
            track_id=track_id,
            zone_id=zone_id,
            zone_name=zone_name,
            queue_depth=depth,
            wait_sec=0.0,
            frame_number=frame_number,
        )

    def on_zone_exit(
        self,
        track_id: int,
        zone_id: str,
        zone_name: str,
        frame_number: int,
        timestamp: float | None = None,
    ) -> QueueEvent | None:
        """
        Returns BILLING_QUEUE_ABANDON if track exits billing zone
        without a purchase and waited long enough.
        Returns None if purchased or too brief.
        """
        if zone_id != self.billing_zone_id:
            return None

        record = self._in_queue.pop(track_id, None)
        if record is None:
            return None

        ts = timestamp or time.time()
        wait_sec = ts - record.join_time
        depth = len(self._in_queue)

        # Too brief → noise, not a real queue interaction
        if record.frames_in_queue < self.min_queue_frames:
            logger.debug(f"Track {track_id}: queue exit too brief ({record.frames_in_queue}f), ignoring")
            return None

        # Check if purchased
        if track_id in self._purchased_tracks:
            logger.info(f"Track {track_id}: queue exit with purchase (not abandon)")
            self._purchased_tracks.discard(track_id)
            return None

        # Abandon only if waited beyond patience threshold
        if wait_sec >= self.abandon_patience_sec:
            logger.warning(
                f"Track {track_id}: BILLING_QUEUE_ABANDON wait={wait_sec:.1f}s "
                f"threshold={self.abandon_patience_sec}s"
            )
            return QueueEvent(
                event_type="BILLING_QUEUE_ABANDON",
                track_id=track_id,
                zone_id=zone_id,
                zone_name=zone_name,
                queue_depth=depth,
                wait_sec=round(wait_sec, 1),
                frame_number=frame_number,
            )

        logger.debug(f"Track {track_id}: queue exit wait={wait_sec:.1f}s < patience, not abandon")
        return None

    # ── Per-Frame Update ─────────────────────────────────────────────────────

    def update_frame(self, frame_number: int, timestamp: float | None = None) -> list[QueueEvent]:
        """
        Called every frame. Handles tracks that have been in queue
        beyond patience but haven't formally exited yet (still in zone).

        Returns list of BILLING_QUEUE_ABANDON events for timed-out tracks.
        """
        ts = timestamp or time.time()
        abandons = []

        for track_id, record in list(self._in_queue.items()):
            record.frames_in_queue += 1
            wait = ts - record.join_time

            # Emit abandon if patience exceeded (track still inside)
            if wait >= self.abandon_patience_sec and not record.purchased:
                logger.warning(
                    f"Track {track_id}: in-zone abandon detected wait={wait:.1f}s"
                )
                self._in_queue.pop(track_id, None)
                abandons.append(QueueEvent(
                    event_type="BILLING_QUEUE_ABANDON",
                    track_id=track_id,
                    zone_id=self.billing_zone_id,
                    zone_name=self.billing_zone_name,
                    queue_depth=len(self._in_queue),
                    wait_sec=round(wait, 1),
                    frame_number=frame_number,
                    extra={"in_zone_timeout": True},
                ))

        return abandons

    # ── Transaction Integration ──────────────────────────────────────────────

    def mark_purchased(self, track_id: int) -> None:
        """
        Call this when POS system confirms a transaction for a session.
        Prevents this track's zone exit from being counted as abandon.
        """
        self._purchased_tracks.add(track_id)
        if track_id in self._in_queue:
            self._in_queue[track_id].purchased = True
        logger.info(f"Track {track_id}: marked as purchased")

    # ── Metrics ──────────────────────────────────────────────────────────────

    @property
    def current_depth(self) -> int:
        """Current number of people in the billing queue."""
        return len(self._in_queue)

    def get_wait_times(self) -> dict[int, float]:
        """Return current wait time in seconds for each track in queue."""
        now = time.time()
        return {
            tid: now - rec.join_time
            for tid, rec in self._in_queue.items()
        }

    def longest_wait_sec(self) -> float:
        waits = self.get_wait_times()
        return max(waits.values(), default=0.0)
