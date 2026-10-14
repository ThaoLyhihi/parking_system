"""Interface + driver giả lập cho barie — tách riêng khỏi controller.py/safety_zone.py
(không import cv2/numpy) để scripts/windows_hardware_agent.py không phải kéo theo
OpenCV khi đóng gói .exe (agent không xử lý camera — việc đó nằm ở AI service trong
Docker, xem README mục "Triển khai trên Windows")."""
from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("barrier")


class BarrierHardware(Protocol):
    def send_open(self, barrier_id: str) -> None: ...
    def send_close(self, barrier_id: str) -> None: ...


class LoggingHardware:
    """Driver giả lập — chỉ log, dùng khi chưa nối phần cứng thật."""

    def send_open(self, barrier_id: str) -> None:
        logger.info("BARIE %s: MỞ", barrier_id)

    def send_close(self, barrier_id: str) -> None:
        logger.info("BARIE %s: ĐÓNG", barrier_id)
