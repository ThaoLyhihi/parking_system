"""Ghép detect -> rectify -> split 2 dòng -> OCR thành 1 pipeline nhận biển số
đầy đủ từ 1 khung hình camera cổng."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.alpr.ocr import NotImplementedOCR, PlateOCR
from app.alpr.plate_detector import PlateDetection, PlateDetector
from app.alpr.plate_rectify import rectify_plate, split_lines_if_needed


@dataclass
class PlateReading:
    text: str
    confidence: float
    detection: PlateDetection


class AlprPipeline:
    def __init__(self, detector: PlateDetector, ocr: PlateOCR | None = None):
        self.detector = detector
        self.ocr = ocr or NotImplementedOCR()

    def read(self, frame: np.ndarray) -> list[PlateReading]:
        readings: list[PlateReading] = []
        for detection in self.detector.detect(frame):
            rectified = rectify_plate(frame, detection.corners)
            lines = split_lines_if_needed(rectified)
            texts: list[str] = []
            confidences: list[float] = []
            for line in lines:
                text, conf = self.ocr.read_line(line)
                if text:
                    texts.append(text)
                    confidences.append(conf)
            plate_text = "".join(texts)
            # Độ tin cậy cuối = min(confidence phát hiện biển, confidence OCR trung bình)
            # — tuyệt đối không "lạc quan hoá" bằng cách chỉ lấy max.
            ocr_conf = min(confidences) if confidences else 0.0
            readings.append(
                PlateReading(
                    text=plate_text,
                    confidence=min(detection.confidence, ocr_conf) if plate_text else 0.0,
                    detection=detection,
                )
            )
        return readings
