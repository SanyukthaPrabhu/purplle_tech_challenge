"""
main.py — Detection Service Entry Point
CV Engineer Agent | Phase 2

Data Flow:
  VideoSource
    → frame
    → YOLODetector.detect(frame)          → [Detection]
    → StaffFilter.evaluate(detections)     → filter staff
    → ByteTracker.update(detections)       → [TrackedObject]
    → ZoneEngine.update(tracks)            → [ZoneEvent]
    → DwellTracker.update_position(tracks) → [DwellEvent]
    → QueueDetector.update_frame()         → [QueueEvent]
    → EntryExitMonitor.check(tracks)       → [EntryExitEvent]
    → EventEmitter.emit_*(events)

All events → POST /events/ingest → FastAPI backend
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import cv2

from .config import DetectionConfig, load_zone_config, settings
from .detector import YOLODetector
from .dwell_tracker import DwellTracker
from .event_emitter import EventEmitter
from .queue_detector import QueueDetector
from .staff_filter import StaffFilter
from .tracker import ByteTracker
from .zone_engine import Zone, ZoneEngine, ZoneType

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("detection.main")


# ─────────────────────────────────────────────────────────────────────────────
# Entry/Exit Monitor
# ─────────────────────────────────────────────────────────────────────────────

class EntryExitMonitor:
    """
    Detects ENTRY and EXIT events by monitoring ENTRY and EXIT zone crossings.

    ENTRY: track confirmed in ENTRY zone → emit ENTRY
    EXIT:  track confirmed in EXIT zone  → emit EXIT

    Reentry: track_id seen again after EXIT within reentry_window_sec
    """

    def __init__(self, reentry_window_sec: float = 300.0):
        self.reentry_window_sec = reentry_window_sec
        self._entered: set[int] = set()
        self._exited: dict[int, float] = {}   # track_id → exit_time
        self._reentry_count: dict[int, int] = {}

    def on_zone_enter(self, track_id: int, zone_type: str, frame_number: int) -> list[dict]:
        """Returns list of events to emit."""
        events = []

        if zone_type == ZoneType.ENTRY.value:
            if track_id not in self._entered:
                self._entered.add(track_id)
                # Check for reentry
                exit_time = self._exited.get(track_id)
                if exit_time and (time.time() - exit_time) < self.reentry_window_sec:
                    count = self._reentry_count.get(track_id, 0) + 1
                    self._reentry_count[track_id] = count
                    events.append({
                        "type": "REENTRY",
                        "track_id": track_id,
                        "reentry_count": count,
                        "gap_sec": round(time.time() - exit_time, 1),
                        "frame": frame_number,
                    })
                    logger.info(f"Track {track_id}: REENTRY #{count}")
                else:
                    events.append({"type": "ENTRY", "track_id": track_id, "frame": frame_number})
                    logger.info(f"Track {track_id}: ENTRY")

        elif zone_type == ZoneType.EXIT.value:
            if track_id in self._entered:
                self._entered.discard(track_id)
                self._exited[track_id] = time.time()
                events.append({"type": "EXIT", "track_id": track_id, "frame": frame_number})
                logger.info(f"Track {track_id}: EXIT")

        return events


# ─────────────────────────────────────────────────────────────────────────────
# Main Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def build_pipeline(cfg: DetectionConfig):
    """Factory: build all pipeline components from config."""

    # Load zones
    layout = load_zone_config(cfg.zone_config_path)
    zones = [Zone.from_dict(z) for z in layout.get("zones", [])]
    zone_name_map = {z.id: z.name for z in zones}

    # Find billing zone
    billing_zones = [z for z in zones if z.zone_type == ZoneType.BILLING]
    billing_zone = billing_zones[0] if billing_zones else None

    # Components
    detector = YOLODetector(
        model_path=cfg.yolo_model,
        conf_threshold=cfg.yolo_conf,
        iou_threshold=cfg.yolo_iou,
        device=cfg.yolo_device,
        img_size=cfg.yolo_img_size,
        min_box_area=cfg.min_box_area,
    )
    tracker = ByteTracker(
        track_thresh=cfg.track_thresh,
        track_buffer=cfg.track_buffer,
        match_thresh=cfg.match_thresh,
    )
    zone_engine = ZoneEngine(
        zones=zones,
        enter_frames=cfg.zone_enter_frames,
        exit_frames=cfg.zone_exit_frames,
        track_buffer=cfg.track_buffer,
    )
    dwell_tracker = DwellTracker(
        emit_interval_sec=cfg.dwell_emit_interval_sec,
        stationary_px_threshold=cfg.dwell_stationary_px,
    )
    staff_filter = StaffFilter(
        staff_roi_polygons=cfg.staff_roi_polygons or [],
        badge_color_hsv=tuple(cfg.staff_badge_color_hsv),
        badge_tolerance=cfg.staff_badge_tolerance,
        roi_enabled=cfg.staff_roi_enabled,
        badge_enabled=cfg.staff_exclude_enabled,
    )
    queue_detector = QueueDetector(
        billing_zone_id=billing_zone.id if billing_zone else "",
        billing_zone_name=billing_zone.name if billing_zone else "Billing",
        abandon_patience_sec=cfg.queue_abandon_patience_sec,
    ) if billing_zone else None

    entry_exit_monitor = EntryExitMonitor(reentry_window_sec=cfg.reentry_window_sec)

    emitter = EventEmitter(
        backend_url=cfg.backend_url,
        store_id=cfg.store_id,
        camera_id=cfg.camera_id,
        batch_size=cfg.emit_batch_size,
        timeout_sec=cfg.emit_timeout_sec,
        retry_count=cfg.emit_retry_count,
        retry_delay_sec=cfg.emit_retry_delay_sec,
    )

    return dict(
        detector=detector,
        tracker=tracker,
        zone_engine=zone_engine,
        dwell_tracker=dwell_tracker,
        staff_filter=staff_filter,
        queue_detector=queue_detector,
        entry_exit_monitor=entry_exit_monitor,
        emitter=emitter,
        zone_name_map=zone_name_map,
        zones=zones,
    )


def run_pipeline(cfg: DetectionConfig = settings):
    """
    Main detection loop.

    Reads video source frame by frame, runs the full pipeline,
    and emits events to the FastAPI backend.
    """
    logger.info(f"Starting detection pipeline for store={cfg.store_id} camera={cfg.camera_id}")
    logger.info(f"Video source: {cfg.video_source}")

    components = build_pipeline(cfg)
    detector: YOLODetector = components["detector"]
    tracker: ByteTracker = components["tracker"]
    zone_engine: ZoneEngine = components["zone_engine"]
    dwell_tracker: DwellTracker = components["dwell_tracker"]
    staff_filter: StaffFilter = components["staff_filter"]
    queue_detector: QueueDetector | None = components["queue_detector"]
    entry_exit: EntryExitMonitor = components["entry_exit_monitor"]
    emitter: EventEmitter = components["emitter"]
    zone_name_map: dict = components["zone_name_map"]

    # Warm up model
    detector.warmup()

    # Open video
    source = cfg.video_source
    if source.isdigit():
        source = int(source)
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        logger.error(f"Cannot open video source: {cfg.video_source}")
        return

    actual_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_skip = max(1, int(actual_fps / cfg.fps_target))
    logger.info(f"Video FPS={actual_fps:.1f} processing every {frame_skip} frame(s)")

    frame_number = 0
    fps_timer = time.time()
    frames_processed = 0
    last_seen_frame: dict[int, int] = {}

    with emitter:
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    logger.info("End of video stream.")
                    break

                frame_number += 1
                if frame_number % frame_skip != 0:
                    continue

                ts = time.time()
                frames_processed += 1

                # ── 1. Detect ─────────────────────────────────────────────
                detections = detector.detect(frame, frame_number)

                # ── 2. Filter staff detections ────────────────────────────
                # Note: staff filter works per-track; we pass all detections
                # and filter after tracking assigns IDs

                # ── 3. Track ──────────────────────────────────────────────
                tracked_objects = tracker.update(detections, frame, frame_number)

                # ── 4. Staff evaluation (per new track) ───────────────────
                visitor_tracks = []
                for obj in tracked_objects:
                    decision = staff_filter.evaluate(
                        track_id=obj.track_id,
                        centroid=obj.centroid,
                        bbox=obj.bbox,
                        frame=frame,
                        is_new=obj.is_new,
                    )
                    if not decision.is_staff:
                        visitor_tracks.append(obj)
                        last_seen_frame[obj.track_id] = frame_number

                # ── 5. Zone engine ────────────────────────────────────────
                zone_events = zone_engine.update(visitor_tracks, frame_number)
                current_occupancy = zone_engine.get_zone_occupancy()

                for ze in zone_events:
                    # Entry / Exit monitor
                    store_events = entry_exit.on_zone_enter(
                        ze.track_id, ze.zone_type, frame_number
                    )
                    for ev in store_events:
                        if ev["type"] == "ENTRY":
                            dwell_tracker.on_entry(ev["track_id"], ts)
                            emitter.emit_entry(
                                track_id=ev["track_id"],
                                frame_number=frame_number,
                            )
                        elif ev["type"] == "EXIT":
                            record = dwell_tracker.on_exit(ev["track_id"], ts)
                            emitter.emit_exit(
                                track_id=ev["track_id"],
                                frame_number=frame_number,
                                dwell_sec=record.total_store_dwell_sec if record else 0.0,
                                visited_zones=list(record.zone_dwell_seconds.keys()) if record else [],
                            )
                        elif ev["type"] == "REENTRY":
                            dwell_tracker.on_entry(ev["track_id"], ts)
                            emitter.emit_reentry(
                                track_id=ev["track_id"],
                                frame_number=frame_number,
                                reentry_count=ev["reentry_count"],
                                gap_sec=ev["gap_sec"],
                            )

                    # Zone dwell tracker
                    if ze.event_type == "ZONE_ENTER":
                        dwell_tracker.on_zone_enter(ze.track_id, ze.zone_id, ts)
                        emitter.emit_zone_enter(
                            track_id=ze.track_id,
                            frame_number=frame_number,
                            zone_id=ze.zone_id,
                            zone_name=ze.zone_name,
                            zone_type=ze.zone_type,
                        )
                    elif ze.event_type == "ZONE_EXIT":
                        dwell_sec = dwell_tracker.on_zone_exit(
                            ze.track_id, ze.zone_id, ze.zone_name, ts
                        )
                        emitter.emit_zone_exit(
                            track_id=ze.track_id,
                            frame_number=frame_number,
                            zone_id=ze.zone_id,
                            zone_name=ze.zone_name,
                            dwell_in_zone_sec=dwell_sec,
                        )

                    # Queue detector
                    if queue_detector:
                        if ze.event_type == "ZONE_ENTER":
                            q_ev = queue_detector.on_zone_enter(
                                ze.track_id, ze.zone_id, ze.zone_name, frame_number, ts
                            )
                            if q_ev:
                                emitter.emit_queue_join(
                                    track_id=ze.track_id,
                                    frame_number=frame_number,
                                    zone_id=ze.zone_id,
                                    zone_name=ze.zone_name,
                                    queue_depth=q_ev.queue_depth,
                                )
                        elif ze.event_type == "ZONE_EXIT":
                            q_ev = queue_detector.on_zone_exit(
                                ze.track_id, ze.zone_id, ze.zone_name, frame_number, ts
                            )
                            if q_ev:
                                emitter.emit_queue_abandon(
                                    track_id=ze.track_id,
                                    frame_number=frame_number,
                                    zone_id=ze.zone_id,
                                    zone_name=ze.zone_name,
                                    wait_sec=q_ev.wait_sec,
                                    queue_depth=q_ev.queue_depth,
                                )

                # ── 6. Per-frame dwell updates ────────────────────────────
                for obj in visitor_tracks:
                    current_zones = [
                        zid for zid in zone_engine._state.get(obj.track_id, {})
                        if zone_engine.is_inside(obj.track_id, zid)
                    ]
                    dwell_events = dwell_tracker.update_position(
                        track_id=obj.track_id,
                        centroid=obj.centroid,
                        current_zone_ids=current_zones,
                        zone_names=zone_name_map,
                        frame_number=frame_number,
                        timestamp=ts,
                    )
                    for de in dwell_events:
                        emitter.emit_zone_dwell(
                            track_id=de.track_id,
                            frame_number=frame_number,
                            zone_id=de.zone_id,
                            zone_name=de.zone_name,
                            dwell_sec=de.dwell_sec,
                            is_stationary=de.is_stationary,
                        )

                # ── 7. Queue frame update ────────────────────────────────
                if queue_detector:
                    q_abandons = queue_detector.update_frame(frame_number, ts)
                    for qa in q_abandons:
                        emitter.emit_queue_abandon(
                            track_id=qa.track_id,
                            frame_number=frame_number,
                            zone_id=qa.zone_id,
                            zone_name=qa.zone_name,
                            wait_sec=qa.wait_sec,
                            queue_depth=qa.queue_depth,
                        )

                # ── 8. Debug display ──────────────────────────────────────
                if cfg.debug_display:
                    _draw_debug(frame, visitor_tracks, zone_engine, current_occupancy)
                    cv2.imshow("RetailAnalytics Debug", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                # ── FPS logging ───────────────────────────────────────────
                if frames_processed % 100 == 0:
                    elapsed = time.time() - fps_timer
                    fps = 100 / elapsed if elapsed > 0 else 0
                    logger.info(
                        f"Frame {frame_number} | processed_fps={fps:.1f} | "
                        f"tracks={len(visitor_tracks)} | "
                        f"emitter={emitter.stats}"
                    )
                    fps_timer = time.time()

                # ── 9. Check for lost tracks and force EXIT ──────────────
                lost_tracks = []
                for tid in list(entry_exit._entered):
                    if frame_number - last_seen_frame.get(tid, 0) > cfg.track_buffer:
                        lost_tracks.append(tid)

                for tid in lost_tracks:
                    entry_exit._entered.discard(tid)
                    gap_frames = frame_number - last_seen_frame.get(tid, frame_number)
                    exit_ts = ts - (gap_frames / actual_fps)
                    record = dwell_tracker.on_exit(tid, exit_ts)
                    emitter.emit_exit(
                        track_id=tid,
                        frame_number=last_seen_frame.get(tid, frame_number),
                        dwell_sec=record.total_store_dwell_sec if record else 0.0,
                        visited_zones=list(record.zone_dwell_seconds.keys()) if record else [],
                    )
                    logger.info(f"Track {tid}: forced EXIT due to track loss (inactive for {gap_frames} frames)")

        except KeyboardInterrupt:
            logger.info("Pipeline interrupted by user.")
        finally:
            # Force EXIT for any visitor tracks still inside the store at shutdown
            for tid in list(entry_exit._entered):
                entry_exit._entered.discard(tid)
                record = dwell_tracker.on_exit(tid, ts)
                emitter.emit_exit(
                    track_id=tid,
                    frame_number=frame_number,
                    dwell_sec=record.total_store_dwell_sec if record else 0.0,
                    visited_zones=list(record.zone_dwell_seconds.keys()) if record else [],
                )
                logger.info(f"Track {tid}: forced EXIT at end of stream")
            cap.release()
            if cfg.debug_display:
                cv2.destroyAllWindows()
            logger.info(f"Pipeline stopped. Emitter stats: {emitter.stats}")
            logger.info(f"Total unique tracks: {tracker.total_unique_tracks}")


def _draw_debug(frame, tracked_objects, zone_engine, occupancy):
    """Draw bounding boxes and track IDs for debug visualization."""
    for obj in tracked_objects:
        x1, y1, x2, y2 = obj.bbox
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"ID:{obj.track_id}"
        cv2.putText(frame, label, (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    # Show queue depth
    y_off = 30
    for zone_id, count in occupancy.items():
        cv2.putText(frame, f"Zone {zone_id[:8]}: {count}p",
                    (10, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        y_off += 25


if __name__ == "__main__":
    run_pipeline()
