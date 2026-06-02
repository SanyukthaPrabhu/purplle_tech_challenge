"""
staff_filter.py — Staff Exclusion Module
CV Engineer Agent | Phase 2

Responsibilities:
  - Exclude staff from visitor counts
  - Two strategies: ROI polygon exclusion + badge color detection
  - Both can be enabled independently or combined

Strategy 1: ROI Exclusion
  Define polygon zones where staff typically enter (e.g. staff entrance).
  Any track that enters ONLY through a staff ROI polygon = mark as staff.

Strategy 2: Badge Color Detection
  Staff wear visible color badges/vests.
  Sample a region above the detection centroid (torso area).
  If HSV mean matches configured staff badge color → mark as staff.

Design Decision:
  Staff tracks are NOT removed from tracker — they are flagged
  so that event emitter skips them. This allows future "staff
  presence" analytics if needed.

Edge Cases:
  - Partial badge visibility: use confidence threshold
  - Group detection: each track evaluated independently
  - Staff ROI: track must originate (first N frames) in ROI
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class StaffDecision:
    track_id: int
    is_staff: bool
    reason: str        # "roi_entry" | "badge_color" | "manual" | "visitor"
    confidence: float  # 0.0 → 1.0


class StaffFilter:
    """
    Determines whether each tracked person is a staff member.

    Integration:
        - Called on new tracks (is_new=True) + periodically for badge check
        - Results cached per track_id
        - Pipeline skips events for is_staff=True tracks

    Usage:
        filter = StaffFilter(config)
        for obj in tracked_objects:
            if filter.is_staff(obj.track_id):
                continue  # skip staff
    """

    def __init__(
        self,
        staff_roi_polygons: list[list[tuple[float, float]]] | None = None,
        badge_color_hsv: tuple[int, int, int] = (110, 150, 100),
        badge_tolerance: int = 30,
        roi_enabled: bool = True,
        badge_enabled: bool = True,
        roi_entry_frames: int = 5,         # must appear in ROI for N frames
    ):
        self.staff_roi_polygons = staff_roi_polygons or []
        self.badge_color_hsv = np.array(badge_color_hsv, dtype=np.uint8)
        self.badge_tolerance = badge_tolerance
        self.roi_enabled = roi_enabled
        self.badge_enabled = badge_enabled
        self.roi_entry_frames = roi_entry_frames

        self._staff_cache: dict[int, bool] = {}         # track_id → is_staff
        self._roi_frame_count: dict[int, int] = {}      # track_id → frames in ROI
        self._new_track_frames: dict[int, int] = {}     # track_id → total new frames seen

    # ── Public API ───────────────────────────────────────────────────────────

    def evaluate(
        self,
        track_id: int,
        centroid: tuple[float, float],
        bbox: tuple[int, int, int, int],
        frame: np.ndarray,
        is_new: bool,
    ) -> StaffDecision:
        """
        Evaluate a single tracked object for staff status.
        Results are cached once a definitive decision is made.

        Args:
            track_id: ByteTrack ID
            centroid: (cx, cy) pixel position
            bbox: (x1, y1, x2, y2) bounding box
            frame: current BGR frame
            is_new: True if this is the first time we see this track

        Returns:
            StaffDecision with is_staff flag
        """
        # Return cached decision if already determined
        if track_id in self._staff_cache:
            return StaffDecision(
                track_id=track_id,
                is_staff=self._staff_cache[track_id],
                reason="cached",
                confidence=1.0,
            )

        # ROI check: accumulate frames in staff ROI
        if self.roi_enabled and self.staff_roi_polygons:
            in_roi = self._centroid_in_staff_roi(centroid)
            if in_roi:
                self._roi_frame_count[track_id] = (
                    self._roi_frame_count.get(track_id, 0) + 1
                )
                if self._roi_frame_count[track_id] >= self.roi_entry_frames:
                    self._staff_cache[track_id] = True
                    logger.info(f"Track {track_id}: STAFF (roi_entry)")
                    return StaffDecision(
                        track_id=track_id,
                        is_staff=True,
                        reason="roi_entry",
                        confidence=0.95,
                    )

        # Badge color check
        if self.badge_enabled and frame is not None:
            badge_conf = self._check_badge_color(bbox, frame)
            if badge_conf >= 0.7:
                self._staff_cache[track_id] = True
                logger.info(f"Track {track_id}: STAFF (badge_color conf={badge_conf:.2f})")
                return StaffDecision(
                    track_id=track_id,
                    is_staff=True,
                    reason="badge_color",
                    confidence=badge_conf,
                )

        # Default: visitor
        return StaffDecision(
            track_id=track_id,
            is_staff=False,
            reason="visitor",
            confidence=0.85,
        )

    def is_staff(self, track_id: int) -> bool:
        """Quick lookup — returns False if unknown (benefit of doubt = visitor)."""
        return self._staff_cache.get(track_id, False)

    def mark_staff(self, track_id: int, reason: str = "manual") -> None:
        """Manually mark a track as staff (e.g. from operator UI)."""
        self._staff_cache[track_id] = True
        logger.info(f"Track {track_id}: manually marked as STAFF ({reason})")

    def clear_track(self, track_id: int) -> None:
        """Remove track state when track is lost."""
        self._staff_cache.pop(track_id, None)
        self._roi_frame_count.pop(track_id, None)

    def staff_track_ids(self) -> set[int]:
        return {tid for tid, is_s in self._staff_cache.items() if is_s}

    # ── Private ──────────────────────────────────────────────────────────────

    def _centroid_in_staff_roi(self, centroid: tuple[float, float]) -> bool:
        """Check if centroid falls within any staff ROI polygon."""
        cx, cy = centroid
        for polygon in self.staff_roi_polygons:
            if self._point_in_polygon(cx, cy, polygon):
                return True
        return False

    @staticmethod
    def _point_in_polygon(x: float, y: float, polygon: list) -> bool:
        """Ray-casting point-in-polygon (same algorithm as zone_engine)."""
        n = len(polygon)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-10) + xi):
                inside = not inside
            j = i
        return inside

    def _check_badge_color(
        self,
        bbox: tuple[int, int, int, int],
        frame: np.ndarray,
    ) -> float:
        """
        Sample the torso region of the bounding box.
        Check if mean HSV color matches staff badge color.

        Returns confidence [0.0, 1.0]

        Torso region: middle 1/3 of bbox height, full width
        This avoids head and legs which are less discriminative.
        """
        try:
            import cv2
            x1, y1, x2, y2 = bbox
            h = y2 - y1
            w = x2 - x1

            if h < 30 or w < 20:
                return 0.0  # bbox too small for reliable sampling

            # Torso: y in [y1 + h//3 : y1 + 2*h//3], full width
            ty1 = y1 + h // 3
            ty2 = y1 + 2 * h // 3
            ty1 = max(0, ty1)
            ty2 = min(frame.shape[0], ty2)
            tx1 = max(0, x1)
            tx2 = min(frame.shape[1], x2)

            torso_bgr = frame[ty1:ty2, tx1:tx2]
            if torso_bgr.size == 0:
                return 0.0

            torso_hsv = cv2.cvtColor(torso_bgr, cv2.COLOR_BGR2HSV)
            mean_hsv = torso_hsv.mean(axis=(0, 1)).astype(np.uint8)

            diff = np.abs(mean_hsv.astype(int) - self.badge_color_hsv.astype(int))
            # H channel wraps at 180 in OpenCV
            diff[0] = min(diff[0], 180 - diff[0])

            # Euclidean distance in HSV space
            dist = float(np.linalg.norm(diff))
            max_dist = self.badge_tolerance * np.sqrt(3)
            confidence = max(0.0, 1.0 - dist / max_dist)
            return confidence

        except Exception as e:
            logger.debug(f"Badge color check failed: {e}")
            return 0.0
