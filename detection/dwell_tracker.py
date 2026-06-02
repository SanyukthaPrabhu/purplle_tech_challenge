"""
dwell_tracker.py — Per-Track Dwell Time State Machine
CV Engineer Agent | Phase 2

Responsibilities:
  - Track cumulative dwell time per visitor per zone
  - Detect "stationary" visitors (ZONE_DWELL events)
  - Calculate total store dwell time on EXIT
  - Handle entry/exit timestamps

State per track:
  entry_time    → set on ENTRY event
  zone_times    → dict[zone_id, cumulative_seconds]
  position_history → last N centroids for stationary detection
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DwellRecord:
    """Accumulated dwell data for one visitor session."""
    track_id: int
    store_entry_time: float = field(default_factory=time.time)  # epoch seconds
    store_exit_time: float | None = None
    zone_entry_times: dict[str, float] = field(default_factory=dict)     # zone_id → epoch
    zone_dwell_seconds: dict[str, float] = field(default_factory=dict)   # zone_id → seconds
    # Stationary detection
    position_history: deque = field(default_factory=lambda: deque(maxlen=30))
    last_dwell_emit: dict[str, float] = field(default_factory=dict)       # zone_id → epoch

    @property
    def total_store_dwell_sec(self) -> float:
        exit = self.store_exit_time or time.time()
        return exit - self.store_entry_time

    @property
    def total_zone_dwell_sec(self) -> dict[str, float]:
        return dict(self.zone_dwell_seconds)


@dataclass
class DwellEvent:
    event_type: str          # ZONE_DWELL
    track_id: int
    zone_id: str
    zone_name: str
    dwell_sec: float
    is_stationary: bool
    frame_number: int


class DwellTracker:
    """
    Manages dwell time tracking for all active visitors.

    Called on:
      - ENTRY → start session timer
      - ZONE_ENTER → start zone timer
      - ZONE_EXIT → stop zone timer, accumulate
      - frame update → check for ZONE_DWELL emission
      - EXIT → finalize session
    """

    def __init__(
        self,
        emit_interval_sec: float = 5.0,
        stationary_px_threshold: float = 20.0,
        stationary_window_frames: int = 15,
    ):
        self.emit_interval_sec = emit_interval_sec
        self.stationary_px = stationary_px_threshold
        self.stationary_window = stationary_window_frames
        self._records: dict[int, DwellRecord] = {}

    # ── Session Lifecycle ────────────────────────────────────────────────────

    def on_entry(self, track_id: int, timestamp: float | None = None) -> None:
        """Call when a visitor ENTRY event is confirmed."""
        ts = timestamp or time.time()
        self._records[track_id] = DwellRecord(
            track_id=track_id,
            store_entry_time=ts,
        )
        logger.debug(f"Track {track_id}: dwell session started at {ts:.1f}")

    def on_exit(self, track_id: int, timestamp: float | None = None) -> DwellRecord | None:
        """
        Call when a visitor EXIT event is confirmed.
        Returns the completed DwellRecord.
        """
        rec = self._records.get(track_id)
        if rec is None:
            logger.warning(f"Track {track_id}: EXIT without prior ENTRY in dwell tracker")
            return None

        ts = timestamp or time.time()
        rec.store_exit_time = ts

        # Close any open zone timers
        for zone_id, entry_ts in list(rec.zone_entry_times.items()):
            elapsed = ts - entry_ts
            rec.zone_dwell_seconds[zone_id] = (
                rec.zone_dwell_seconds.get(zone_id, 0.0) + elapsed
            )
            del rec.zone_entry_times[zone_id]

        logger.info(
            f"Track {track_id}: EXIT dwell={rec.total_store_dwell_sec:.1f}s "
            f"zones={rec.zone_dwell_seconds}"
        )
        completed = rec
        del self._records[track_id]
        return completed

    # ── Zone Lifecycle ───────────────────────────────────────────────────────

    def on_zone_enter(self, track_id: int, zone_id: str, timestamp: float | None = None) -> None:
        """Call when ZONE_ENTER event fires."""
        rec = self._get_or_create(track_id)
        ts = timestamp or time.time()
        rec.zone_entry_times[zone_id] = ts
        logger.debug(f"Track {track_id}: zone {zone_id} enter at {ts:.1f}")

    def on_zone_exit(
        self,
        track_id: int,
        zone_id: str,
        zone_name: str,
        timestamp: float | None = None,
    ) -> float:
        """
        Call when ZONE_EXIT event fires.
        Returns dwell seconds spent in this zone visit.
        """
        rec = self._get_or_create(track_id)
        ts = timestamp or time.time()
        entry_ts = rec.zone_entry_times.pop(zone_id, ts)
        elapsed = ts - entry_ts
        rec.zone_dwell_seconds[zone_id] = (
            rec.zone_dwell_seconds.get(zone_id, 0.0) + elapsed
        )
        logger.debug(f"Track {track_id}: zone {zone_id} exit dwell={elapsed:.1f}s")
        return elapsed

    # ── Per-Frame Update ─────────────────────────────────────────────────────

    def update_position(
        self,
        track_id: int,
        centroid: tuple[float, float],
        current_zone_ids: list[str],
        zone_names: dict[str, str],
        frame_number: int,
        timestamp: float | None = None,
    ) -> list[DwellEvent]:
        """
        Called every frame for each tracked person.
        Returns ZONE_DWELL events if emit interval elapsed.

        Args:
            track_id: ByteTrack ID
            centroid: (cx, cy) pixel position
            current_zone_ids: zone IDs the track is currently inside
            zone_names: {zone_id: zone_name} lookup
            frame_number: current frame
            timestamp: epoch time (defaults to now)
        """
        rec = self._get_or_create(track_id)
        ts = timestamp or time.time()
        rec.position_history.append(centroid)

        events: list[DwellEvent] = []

        for zone_id in current_zone_ids:
            entry_ts = rec.zone_entry_times.get(zone_id)
            if entry_ts is None:
                continue

            elapsed = ts - entry_ts
            last_emit = rec.last_dwell_emit.get(zone_id, entry_ts)

            if ts - last_emit >= self.emit_interval_sec:
                is_stat = self._is_stationary(rec.position_history)
                events.append(DwellEvent(
                    event_type="ZONE_DWELL",
                    track_id=track_id,
                    zone_id=zone_id,
                    zone_name=zone_names.get(zone_id, zone_id),
                    dwell_sec=round(elapsed, 1),
                    is_stationary=is_stat,
                    frame_number=frame_number,
                ))
                rec.last_dwell_emit[zone_id] = ts

        return events

    # ── Stationary Detection ─────────────────────────────────────────────────

    def _is_stationary(self, history: deque) -> bool:
        """
        Returns True if the track has moved less than stationary_px
        pixels over the last stationary_window frames.

        Algorithm: compare bounding box of last N centroids.
        If max span < threshold → stationary.
        """
        if len(history) < self.stationary_window:
            return False

        recent = list(history)[-self.stationary_window:]
        xs = [p[0] for p in recent]
        ys = [p[1] for p in recent]
        span = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
        return span < self.stationary_px

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_or_create(self, track_id: int) -> DwellRecord:
        if track_id not in self._records:
            logger.debug(f"Track {track_id}: auto-creating dwell record (no prior ENTRY)")
            self._records[track_id] = DwellRecord(track_id=track_id)
        return self._records[track_id]

    def get_current_dwell(self, track_id: int, zone_id: str | None = None) -> float:
        """Get cumulative dwell in seconds for a track (optionally per zone)."""
        rec = self._records.get(track_id)
        if rec is None:
            return 0.0
        if zone_id:
            acc = rec.zone_dwell_seconds.get(zone_id, 0.0)
            # Add ongoing
            if zone_id in rec.zone_entry_times:
                acc += time.time() - rec.zone_entry_times[zone_id]
            return acc
        return rec.total_store_dwell_sec

    def active_track_ids(self) -> list[int]:
        return list(self._records.keys())
