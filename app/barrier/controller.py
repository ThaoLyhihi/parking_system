"""State machine điều khiển barie.

Tên hàm (open_barrier/close_barrier) và khái niệm "BarrierController" lấy cảm
hứng từ phần mềm cũ (class `BarrierController`, hàm `OpenBarrierById`/
`CloseBarrierById` tìm thấy trong Debug_MSSQL/Debug/Parking_Manager_Sql_PCCOM_MonthFee_LPR.exe)
— viết lại bằng Python, có thêm điều kiện an toàn mà bản cũ không có (mục 1d
tài liệu quy trình: phần mềm cũ không có input từ cảm biến vật lý).

`hardware` là 1 interface để cắm driver thật sau (relay qua GPIO/ESP32/MQTT...);
mặc định dùng `LoggingHardware` chỉ in log, để chạy demo không cần phần cứng.
`BarrierHardware`/`LoggingHardware` định nghĩa ở `app/barrier/hardware.py` (không
phải ở đây) để tách khỏi `BarrierSafetyZone` (cần cv2/numpy) — xem docstring ở đó.
"""
from __future__ import annotations

import logging
from enum import Enum

from app.barrier.hardware import BarrierHardware, LoggingHardware
from app.barrier.safety_zone import BarrierSafetyZone

logger = logging.getLogger("barrier")


class BarrierState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"


class BarrierController:
    def __init__(self, barrier_id: str, safety_zone: BarrierSafetyZone,
                 hardware: BarrierHardware | None = None):
        self.barrier_id = barrier_id
        self.safety_zone = safety_zone
        self.hardware = hardware or LoggingHardware()
        self.state = BarrierState.CLOSED

    def open_barrier(self, reason: str) -> None:
        """Mở luôn không cần kiểm tra an toàn — mở không bao giờ gây va đập."""
        self.hardware.send_open(self.barrier_id)
        self.state = BarrierState.OPEN
        logger.info("BARIE %s mở (%s)", self.barrier_id, reason)

    def try_close_barrier(self, camera_frame) -> bool:
        """Chỉ đóng khi vùng an toàn xác nhận trống đủ lâu (mục 6.6 thuyết
        minh). Đây là lớp an toàn DUY NHẤT hiện có cho barie (không có cảm
        biến vật lý dự phòng, đã xác nhận) — nên AN_TOÀN == False phải luôn
        thắng, không có đường tắt nào bỏ qua kiểm tra này."""
        safe_to_close = self.safety_zone.update(camera_frame)
        if not safe_to_close:
            if self.state != BarrierState.OPEN:
                self.open_barrier(reason="vật cản/mất tín hiệu camera trong vùng an toàn")
            return False

        self.hardware.send_close(self.barrier_id)
        self.state = BarrierState.CLOSED
        logger.info("BARIE %s đóng (vùng an toàn đã xác nhận trống)", self.barrier_id)
        return True
