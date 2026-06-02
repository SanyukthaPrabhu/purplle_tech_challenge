"""
config.py — Detection Service Configuration
CV Engineer Agent | Phase 2
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import validator
from pydantic_settings import BaseSettings


class DetectionConfig(BaseSettings):
    # ── Source ──────────────────────────────────────────────────────────────
    video_source: str = "0"                    # RTSP URL, MP4 path, or "0" for webcam
    camera_id: str = "cam01"
    store_id: str = ""                         # UUID of monitored store
    fps_target: int = 15                       # process every Nth frame if needed

    # ── Model ────────────────────────────────────────────────────────────────
    yolo_model: str = "yolov8n.pt"             # nano=speed, medium=accuracy
    yolo_conf: float = 0.45                    # detection confidence threshold
    yolo_iou: float = 0.45                     # NMS IoU threshold
    yolo_classes: list[int] = [0]              # 0 = person in COCO
    yolo_device: str = "cpu"                   # "cpu" | "cuda:0" | "mps"
    yolo_img_size: int = 640

    # ── ByteTrack ────────────────────────────────────────────────────────────
    track_thresh: float = 0.50                 # minimum detection score for tracking
    track_buffer: int = 30                     # frames to keep lost track alive
    match_thresh: float = 0.80                 # IoU match threshold
    min_box_area: float = 100.0                # ignore tiny boxes (noise)

    # ── Zones ────────────────────────────────────────────────────────────────
    zone_config_path: str = "store_layout.json"
    zone_enter_frames: int = 3                 # frames inside zone to confirm ENTER
    zone_exit_frames: int = 3                  # frames outside zone to confirm EXIT

    # ── Dwell ────────────────────────────────────────────────────────────────
    dwell_emit_interval_sec: float = 5.0       # emit ZONE_DWELL every N seconds
    dwell_stationary_px: float = 20.0          # pixel movement threshold for "stationary"

    # ── Queue ────────────────────────────────────────────────────────────────
    queue_zone_name: str = "Billing Counter"
    queue_spike_threshold: int = 8             # persons in queue → trigger anomaly
    queue_abandon_patience_sec: float = 120.0  # seconds in queue before = potential abandon

    # ── Staff Filter ─────────────────────────────────────────────────────────
    staff_roi_enabled: bool = True             # exclude staff entry ROI
    staff_roi_polygons: list[Any] = []         # list of polygons marking staff areas
    staff_badge_color_hsv: list[int] = [110, 150, 100]  # HSV centroid of staff badge
    staff_badge_tolerance: int = 30
    staff_exclude_enabled: bool = True

    # ── Event Emitter ────────────────────────────────────────────────────────
    backend_url: str = "http://localhost:8000"
    emit_batch_size: int = 1                  # events per POST request
    emit_timeout_sec: float = 5.0
    emit_retry_count: int = 3
    emit_retry_delay_sec: float = 1.0

    # ── Reentry ──────────────────────────────────────────────────────────────
    reentry_window_sec: float = 300.0          # 5 min: same track within window = reentry

    # ── Debug ────────────────────────────────────────────────────────────────
    debug_display: bool = False                # show annotated frames on screen
    debug_save_frames: bool = False
    debug_output_dir: str = "debug_output"
    log_level: str = "INFO"

    @validator("staff_roi_polygons", pre=True, always=True)
    def parse_polygons(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

    @validator("yolo_classes", pre=True, always=True)
    def parse_classes(cls, v):
        if isinstance(v, str):
            return [int(c) for c in v.split(",")]
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def load_zone_config(path: str) -> dict:
    """Load store layout JSON containing zone polygon definitions."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Zone config not found: {path}")
    with p.open() as f:
        return json.load(f)


# Singleton
settings = DetectionConfig()
