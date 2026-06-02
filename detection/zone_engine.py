"""
zone_engine.py — Polygon Zone Detection Engine
CV Engineer Agent | Phase 2

Responsibilities:
  - Load zone definitions from store_layout.json
  - Determine if a track centroid is inside a zone polygon
  - Emit ZONE_ENTER / ZONE_EXIT events with hysteresis buffering
  - Support multiple zone types: ENTRY, EXIT, BILLING, GENERAL

Zone State Machine per track per zone:
  OUTSIDE ──[N frames inside]──▶ INSIDE  (emit ZONE_ENTER)
  INSIDE  ──[N frames outside]─▶ OUTSIDE (emit ZONE_EXIT)

Hysteresis prevents flickering at zone boundaries.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class ZoneType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    BILLING = "BILLING"
    GENERAL = "GENERAL"


@dataclass
class Zone:
    id: str
    name: str
    zone_type: ZoneType
    polygon: list[tuple[float, float]]  # [(x,y), ...]
    _np_polygon: np.ndarray = field(init=False, repr=False)

    def __post_init__(self):
        self._np_polygon = np.array(self.polygon, dtype=np.float32)

    def contains_point(self, x: float, y: float) -> bool:
        """
        Ray-casting algorithm for point-in-polygon test.
        O(n) per call — fast enough for <=20 polygon vertices per zone.
        """
        poly = self._np_polygon
        n = len(poly)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-10) + xi):
                inside = not inside
            j = i
        return inside

    @classmethod
    def from_dict(cls, data: dict) -> "Zone":
        return cls(
            id=data["id"],
            name=data["name"],
            zone_type=ZoneType(data["zone_type"]),
            polygon=[(float(p[0]), float(p[1])) for p in data["polygon"]],
        )


class _ZoneState(str, Enum):
    OUTSIDE = "OUTSIDE"
    ENTERING = "ENTERING"    # Candidate frames accumulating
    INSIDE = "INSIDE"
    EXITING = "EXITING"      # Candidate frames accumulating


@dataclass
class _TrackZoneState:
    """State machine for one (track, zone) pair."""
    zone_id: str
    state: _ZoneState = _ZoneState.OUTSIDE
    candidate_frames: int = 0          # frames in current transition
    frames_inside: int = 0             # total frames spent inside
    enter_frame: int = -1              # frame when INSIDE was confirmed


@dataclass
class ZoneEvent:
    """Output of zone engine for a single track update."""
    event_type: str                    # ZONE_ENTER | ZONE_EXIT
    track_id: int
    zone_id: str
    zone_name: str
    zone_type: str
    frame_number: int
    dwell_frames: int = 0              # frames spent inside (for EXIT events)
    extra: dict = field(default_factory=dict)


class ZoneEngine:
    """
    Polygon-based zone tracking engine.

    Usage:
        engine = ZoneEngine(zones, enter_frames=3, exit_frames=3)
        for frame_number, tracks in video_stream:
            events = engine.update(tracks, frame_number)
            for ev in events:
                emit(ev)
    """

    def __init__(
        self,
        zones: list[Zone],
        enter_frames: int = 3,
        exit_frames: int = 3,
        track_buffer: int = 30,
    ):
        self.zones = {z.id: z for z in zones}
        self.enter_frames = enter_frames
        self.exit_frames = exit_frames
        self.track_buffer = track_buffer
        # state: {track_id: {zone_id: _TrackZoneState}}
        self._state: dict[int, dict[str, _TrackZoneState]] = {}
        # last_seen: {track_id: frame_number}
        self._last_seen: dict[int, int] = {}

    @classmethod
    def from_config(cls, layout: dict, enter_frames: int = 3, exit_frames: int = 3, track_buffer: int = 30) -> "ZoneEngine":
        """Build ZoneEngine from store_layout.json data."""
        zones = [Zone.from_dict(z) for z in layout.get("zones", [])]
        logger.info(f"Loaded {len(zones)} zones: {[z.name for z in zones]}")
        return cls(zones, enter_frames, exit_frames, track_buffer)

    def update(
        self,
        tracked_objects: list[Any],  # TrackedObject from tracker.py
        frame_number: int,
    ) -> list[ZoneEvent]:
        """
        Check all tracked objects against all zones.

        Returns list of ZoneEvent (ZONE_ENTER / ZONE_EXIT) triggered this frame.
        """
        events: list[ZoneEvent] = []
        active_track_ids = {obj.track_id for obj in tracked_objects}

        # Update last seen frame for active tracks
        for obj in tracked_objects:
            self._last_seen[obj.track_id] = frame_number

        # Handle tracks that disappeared (force EXIT only after track_buffer frames)
        for track_id in list(self._state.keys()):
            if track_id not in active_track_ids:
                gap = frame_number - self._last_seen.get(track_id, frame_number)
                if gap > self.track_buffer:
                    forced = self._force_exit_all(track_id, frame_number)
                    events.extend(forced)
                    del self._state[track_id]
                    if track_id in self._last_seen:
                        del self._last_seen[track_id]

        for obj in tracked_objects:
            track_id = obj.track_id
            cx, cy = obj.centroid

            if track_id not in self._state:
                self._state[track_id] = {}

            for zone_id, zone in self.zones.items():
                inside = zone.contains_point(cx, cy)
                ev = self._transition(track_id, zone, inside, frame_number)
                if ev:
                    events.append(ev)

        return events

    def _transition(
        self,
        track_id: int,
        zone: Zone,
        inside: bool,
        frame_number: int,
    ) -> ZoneEvent | None:
        """State machine transition for (track, zone)."""
        if zone.id not in self._state[track_id]:
            self._state[track_id][zone.id] = _TrackZoneState(zone_id=zone.id)

        s = self._state[track_id][zone.id]

        if s.state == _ZoneState.OUTSIDE:
            if inside:
                s.state = _ZoneState.ENTERING
                s.candidate_frames = 1
            # else: stays OUTSIDE

        elif s.state == _ZoneState.ENTERING:
            if inside:
                s.candidate_frames += 1
                if s.candidate_frames >= self.enter_frames:
                    s.state = _ZoneState.INSIDE
                    s.enter_frame = frame_number
                    s.frames_inside = 0
                    logger.debug(f"Track {track_id} ZONE_ENTER {zone.name}")
                    return ZoneEvent(
                        event_type="ZONE_ENTER",
                        track_id=track_id,
                        zone_id=zone.id,
                        zone_name=zone.name,
                        zone_type=zone.zone_type.value,
                        frame_number=frame_number,
                    )
            else:
                # Reset — was a border flicker
                s.state = _ZoneState.OUTSIDE
                s.candidate_frames = 0

        elif s.state == _ZoneState.INSIDE:
            if inside:
                s.frames_inside += 1
            else:
                s.state = _ZoneState.EXITING
                s.candidate_frames = 1

        elif s.state == _ZoneState.EXITING:
            if not inside:
                s.candidate_frames += 1
                if s.candidate_frames >= self.exit_frames:
                    dwell = s.frames_inside
                    s.state = _ZoneState.OUTSIDE
                    s.candidate_frames = 0
                    s.frames_inside = 0
                    logger.debug(f"Track {track_id} ZONE_EXIT {zone.name} dwell={dwell}f")
                    return ZoneEvent(
                        event_type="ZONE_EXIT",
                        track_id=track_id,
                        zone_id=zone.id,
                        zone_name=zone.name,
                        zone_type=zone.zone_type.value,
                        frame_number=frame_number,
                        dwell_frames=dwell,
                    )
            else:
                # Re-entered before exit confirmed
                s.state = _ZoneState.INSIDE
                s.candidate_frames = 0

        return None

    def _force_exit_all(self, track_id: int, frame_number: int) -> list[ZoneEvent]:
        """Force EXIT for all zones where track was INSIDE when it disappears."""
        events = []
        for zone_id, s in self._state.get(track_id, {}).items():
            if s.state in (_ZoneState.INSIDE, _ZoneState.EXITING):
                zone = self.zones[zone_id]
                events.append(ZoneEvent(
                    event_type="ZONE_EXIT",
                    track_id=track_id,
                    zone_id=zone_id,
                    zone_name=zone.name,
                    zone_type=zone.zone_type.value,
                    frame_number=frame_number,
                    dwell_frames=s.frames_inside,
                    extra={"forced": True},
                ))
        return events

    def get_zone_occupancy(self) -> dict[str, int]:
        """Return current person count per zone (for queue detection)."""
        occupancy: dict[str, int] = {z_id: 0 for z_id in self.zones}
        for track_states in self._state.values():
            for zone_id, s in track_states.items():
                if s.state == _ZoneState.INSIDE:
                    occupancy[zone_id] = occupancy.get(zone_id, 0) + 1
        return occupancy

    def is_inside(self, track_id: int, zone_id: str) -> bool:
        """Check if a track is currently inside a specific zone."""
        s = self._state.get(track_id, {}).get(zone_id)
        if s is None:
            return False
        return s.state == _ZoneState.INSIDE


def load_zones_from_layout(layout_path: str) -> list[Zone]:
    """Convenience function to load zones from store layout JSON file."""
    import json
    with open(layout_path) as f:
        layout = json.load(f)
    return [Zone.from_dict(z) for z in layout.get("zones", [])]
