"""
tracker.py — ByteTrack Wrapper
CV Engineer Agent | Phase 2

Responsibilities:
  - Wrap ByteTrack (supervision library) for multi-object tracking
  - Accept Detection list, return TrackedObject list
  - Maintain track ID continuity across frames
  - Handle lost tracks and re-identification

ByteTrack Algorithm:
  1. Match high-confidence detections to existing tracks via IoU (Hungarian)
  2. For unmatched tracks: try matching with low-confidence detections
  3. New tracks initialized for remaining unmatched detections
  4. Tracks killed after track_buffer frames without a match
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from .detector import Detection

logger = logging.getLogger(__name__)


@dataclass
class TrackedObject:
    """Represents a tracked person across frames."""
    track_id: int
    bbox: tuple[int, int, int, int]    # (x1, y1, x2, y2)
    confidence: float
    frame_number: int
    centroid: tuple[float, float] = field(init=False)
    is_new: bool = False               # True on the first frame this track appears
    frames_tracked: int = 1

    def __post_init__(self):
        x1, y1, x2, y2 = self.bbox
        self.centroid = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    def to_dict(self) -> dict:
        x1, y1, x2, y2 = self.bbox
        return {
            "track_id": self.track_id,
            "bbox": {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
            "confidence": self.confidence,
            "centroid": {"x": self.centroid[0], "y": self.centroid[1]},
        }


class ByteTracker:
    """
    ByteTrack wrapper using the `supervision` library.

    The supervision library provides a production-ready ByteTrack
    implementation (ByteTracker) that works directly with numpy arrays.

    Fallback: if supervision is not installed, a simple IoU-based tracker
    is used (good enough for testing without GPU).

    Design decisions:
      - track_buffer: how many frames a lost track is kept alive.
        Set to fps * 2 for a 2-second grace period on occlusion.
      - match_thresh: IoU needed to match detection → existing track.
        Higher = stricter identity, fewer ID switches.
      - lost_track_thresh: frames without match before track killed.
    """

    def __init__(
        self,
        track_thresh: float = 0.50,
        track_buffer: int = 30,
        match_thresh: float = 0.80,
        frame_rate: int = 30,
    ):
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh
        self.frame_rate = frame_rate
        self._tracker = None
        self._seen_ids: set[int] = set()
        self._frames_per_id: dict[int, int] = {}
        self._use_supervision = False

    def _init_tracker(self):
        """Initialize ByteTrack backend (supervision preferred, fallback to simple)."""
        try:
            import supervision as sv
            self._tracker = sv.ByteTrack(
                track_activation_threshold=self.track_thresh,
                lost_track_buffer=self.track_buffer,
                minimum_matching_threshold=self.match_thresh,
                frame_rate=self.frame_rate,
            )
            self._use_supervision = True
            logger.info("ByteTrack initialized via supervision library.")
        except ImportError:
            logger.warning(
                "supervision not installed — using fallback IoU tracker. "
                "Install: pip install supervision"
            )
            self._tracker = _FallbackIoUTracker(
                match_thresh=self.match_thresh,
                track_buffer=self.track_buffer,
            )
            self._use_supervision = False

    def update(
        self,
        detections: list[Detection],
        frame: np.ndarray,
        frame_number: int = 0,
    ) -> list[TrackedObject]:
        """
        Update tracker with new detections for this frame.

        Args:
            detections: list of Detection objects from YOLOv8
            frame: current BGR frame (needed by supervision)
            frame_number: current frame index

        Returns:
            list of TrackedObject with stable track IDs
        """
        if self._tracker is None:
            self._init_tracker()

        if not detections:
            # Still update tracker to advance lost-track counters
            if self._use_supervision:
                import supervision as sv
                empty = sv.Detections.empty()
                self._tracker.update_with_detections(empty)
            else:
                self._tracker.update([], frame_number)
            return []

        if self._use_supervision:
            tracked = self._update_supervision(detections, frame, frame_number)
        else:
            tracked = self._tracker.update(
                [(d.xyxy, d.confidence) for d in detections], frame_number
            )
            tracked = self._wrap_fallback(tracked, frame_number)

        # Mark new tracks
        for obj in tracked:
            if obj.track_id not in self._seen_ids:
                obj.is_new = True
                self._seen_ids.add(obj.track_id)
                self._frames_per_id[obj.track_id] = 1
            else:
                self._frames_per_id[obj.track_id] = (
                    self._frames_per_id.get(obj.track_id, 0) + 1
                )
                obj.frames_tracked = self._frames_per_id[obj.track_id]

        logger.debug(
            f"Frame {frame_number}: {len(tracked)} active tracks "
            f"({sum(1 for o in tracked if o.is_new)} new)"
        )
        return tracked

    def _update_supervision(
        self,
        detections: list[Detection],
        frame: np.ndarray,
        frame_number: int,
    ) -> list[TrackedObject]:
        import supervision as sv

        xyxy = np.array([d.xyxy for d in detections], dtype=np.float32)
        confs = np.array([d.confidence for d in detections], dtype=np.float32)
        class_ids = np.array([d.class_id for d in detections], dtype=int)

        sv_detections = sv.Detections(
            xyxy=xyxy,
            confidence=confs,
            class_id=class_ids,
        )
        tracked_sv = self._tracker.update_with_detections(sv_detections)

        objects = []
        if tracked_sv.tracker_id is None:
            return objects

        for i, tid in enumerate(tracked_sv.tracker_id):
            x1, y1, x2, y2 = tracked_sv.xyxy[i].astype(int)
            conf = float(tracked_sv.confidence[i]) if tracked_sv.confidence is not None else 0.9
            objects.append(TrackedObject(
                track_id=int(tid),
                bbox=(x1, y1, x2, y2),
                confidence=conf,
                frame_number=frame_number,
            ))
        return objects

    def _wrap_fallback(self, raw_tracks: list, frame_number: int) -> list[TrackedObject]:
        objects = []
        for tid, xyxy, conf in raw_tracks:
            x1, y1, x2, y2 = [int(v) for v in xyxy]
            objects.append(TrackedObject(
                track_id=tid,
                bbox=(x1, y1, x2, y2),
                confidence=conf,
                frame_number=frame_number,
            ))
        return objects

    @property
    def total_unique_tracks(self) -> int:
        return len(self._seen_ids)


# ─────────────────────────────────────────────────────────────────────────────
# Fallback IoU Tracker (no external deps)
# ─────────────────────────────────────────────────────────────────────────────

class _FallbackIoUTracker:
    """
    Simple greedy IoU tracker for environments without supervision.
    NOT production-grade — use supervision ByteTrack for real deployments.
    """

    def __init__(self, match_thresh: float = 0.3, track_buffer: int = 30):
        self.match_thresh = match_thresh
        self.track_buffer = track_buffer
        self._next_id = 1
        self._tracks: dict[int, dict] = {}  # id → {xyxy, conf, lost_frames}

    def update(
        self,
        detections: list[tuple[list[float], float]],
        frame_number: int,
    ) -> list[tuple[int, list[float], float]]:
        # Age existing tracks
        to_delete = []
        for tid, t in self._tracks.items():
            t["lost_frames"] += 1
            if t["lost_frames"] > self.track_buffer:
                to_delete.append(tid)
        for tid in to_delete:
            del self._tracks[tid]

        if not detections:
            return []

        matched, unmatched_dets = self._match(detections)
        results = []

        # Update matched tracks
        for tid, det_idx in matched:
            xyxy, conf = detections[det_idx]
            self._tracks[tid] = {"xyxy": xyxy, "conf": conf, "lost_frames": 0}
            results.append((tid, xyxy, conf))

        # Create new tracks for unmatched detections
        for det_idx in unmatched_dets:
            xyxy, conf = detections[det_idx]
            tid = self._next_id
            self._next_id += 1
            self._tracks[tid] = {"xyxy": xyxy, "conf": conf, "lost_frames": 0}
            results.append((tid, xyxy, conf))

        return results

    def _iou(self, a: list[float], b: list[float]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        union = (ax2-ax1)*(ay2-ay1) + (bx2-bx1)*(by2-by1) - inter
        return inter / union if union > 0 else 0.0

    def _match(self, detections):
        track_ids = list(self._tracks.keys())
        matched, unmatched_dets = [], list(range(len(detections)))
        used_tracks = set()

        for det_idx, (xyxy, _) in enumerate(detections):
            best_iou, best_tid = 0.0, None
            for tid in track_ids:
                if tid in used_tracks:
                    continue
                iou = self._iou(xyxy, self._tracks[tid]["xyxy"])
                if iou > best_iou:
                    best_iou, best_tid = iou, tid
            if best_tid and best_iou >= self.match_thresh:
                matched.append((best_tid, det_idx))
                used_tracks.add(best_tid)
                unmatched_dets.remove(det_idx)

        return matched, unmatched_dets
