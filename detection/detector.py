"""
detector.py — YOLOv8 Person Detection Wrapper
CV Engineer Agent | Phase 2

Responsibilities:
  - Load YOLOv8 model (lazy, singleton)
  - Run inference on a single frame
  - Return structured Detection objects (only persons)
  - Handle device selection (CPU / CUDA / MPS)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """Represents a single person detection in a frame."""
    bbox: tuple[int, int, int, int]   # (x1, y1, x2, y2) in pixels
    confidence: float
    class_id: int = 0                  # 0 = person (COCO)
    # Derived helpers
    centroid: tuple[float, float] = field(init=False)
    area: float = field(init=False)

    def __post_init__(self):
        x1, y1, x2, y2 = self.bbox
        self.centroid = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        self.area = float((x2 - x1) * (y2 - y1))

    @property
    def xyxy(self) -> list[float]:
        return list(self.bbox)

    @property
    def xywh(self) -> tuple[float, float, float, float]:
        x1, y1, x2, y2 = self.bbox
        return x1, y1, x2 - x1, y2 - y1

    def to_dict(self) -> dict:
        x1, y1, x2, y2 = self.bbox
        return {
            "x": int(x1), "y": int(y1),
            "w": int(x2 - x1), "h": int(y2 - y1),
        }


class YOLODetector:
    """
    Thin wrapper around YOLOv8 (ultralytics) for person detection.

    Design decisions:
      - Model loaded once at init (lazy-loadable via factory).
      - Only class 0 (person) returned — avoids false positives.
      - Confidence + NMS thresholds fully configurable.
      - Half-precision (FP16) enabled on CUDA for speed.
    """

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        conf_threshold: float = 0.45,
        iou_threshold: float = 0.45,
        device: str = "cpu",
        img_size: int = 640,
        target_classes: list[int] | None = None,
        min_box_area: float = 100.0,
    ):
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.device = device
        self.img_size = img_size
        self.target_classes = target_classes or [0]  # person
        self.min_box_area = min_box_area
        self._model = None
        self._model_path = model_path
        self._half = device.startswith("cuda")

    def _load_model(self):
        """Lazy-load model on first inference call."""
        try:
            from ultralytics import YOLO
            logger.info(f"Loading YOLOv8 model: {self._model_path} on {self.device}")
            self._model = YOLO(self._model_path)
            self._model.to(self.device)
            if self._half:
                self._model.model.half()
            logger.info("Model loaded successfully.")
        except ImportError:
            raise RuntimeError(
                "ultralytics package not found. Run: pip install ultralytics"
            )

    def detect(self, frame: np.ndarray, frame_number: int = 0) -> list[Detection]:
        """
        Run inference on a single BGR frame.

        Args:
            frame: numpy array (H, W, 3) BGR
            frame_number: for logging / debug

        Returns:
            List of Detection objects for persons above conf threshold
        """
        if self._model is None:
            self._load_model()

        results = self._model.predict(
            source=frame,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            classes=self.target_classes,
            imgsz=self.img_size,
            verbose=False,
            half=self._half,
        )

        detections: list[Detection] = []
        if not results or results[0].boxes is None:
            return detections

        boxes = results[0].boxes
        for i in range(len(boxes)):
            xyxy = boxes.xyxy[i].cpu().numpy().astype(int)
            conf = float(boxes.conf[i].cpu().numpy())
            cls = int(boxes.cls[i].cpu().numpy())

            if cls not in self.target_classes:
                continue

            x1, y1, x2, y2 = xyxy
            area = (x2 - x1) * (y2 - y1)
            if area < self.min_box_area:
                logger.debug(f"Frame {frame_number}: Skipping tiny box area={area}")
                continue

            # Clamp to frame boundaries
            h, w = frame.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            detections.append(Detection(
                bbox=(int(x1), int(y1), int(x2), int(y2)),
                confidence=round(conf, 3),
                class_id=cls,
            ))

        logger.debug(f"Frame {frame_number}: {len(detections)} persons detected")
        return detections

    def warmup(self, frame_size: tuple[int, int] = (640, 640)):
        """Run a dummy inference to warm up the model."""
        dummy = np.zeros((*frame_size, 3), dtype=np.uint8)
        self.detect(dummy, frame_number=-1)
        logger.info("YOLOv8 warmup complete.")
