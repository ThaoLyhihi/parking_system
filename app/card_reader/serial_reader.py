"""Đầu đọc thẻ qua cổng COM/RS232 — đúng kiểu phần cứng phần mềm cũ dùng
(`coms.config`: `SwipePort port="COM7"`), cho những đầu đọc KHÔNG phải USB
keyboard-wedge (xem usb_hid_reader.py/windows_keyboard_reader.py cho loại đó).

Chạy được trên cả Windows (`COM7`, `COM19`...) và Linux (`/dev/ttyUSB0`...) vì
dùng `pyserial` — không cần biết trước OS như 2 loại USB reader kia.

Giao thức giả định: đầu đọc gửi số thẻ dạng ký tự ASCII, kết thúc bằng \r hoặc
\n (kiểu phổ biến nhất của đầu đọc RS232 giá rẻ). Nếu đầu đọc thật của bạn
dùng giao thức khác (có byte mở/đóng khung riêng...), cần sửa lại `_loop()`
— CHƯA xác minh được với phần cứng thật, xem README mục "Việc chưa làm".
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import serial

from app.card_reader.interface import CardReader

logger = logging.getLogger("card_reader.serial")


class SerialCardReader(CardReader):
    def __init__(self, port: str, baudrate: int = 9600, reconnect_delay: float = 3.0):
        self.port = port
        self.baudrate = baudrate
        self._reconnect_delay = reconnect_delay
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self, on_card: Callable[[str], None]) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, args=(on_card,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self, on_card: Callable[[str], None]) -> None:
        buffer: list[str] = []
        ser: serial.Serial | None = None
        while self._running:
            if ser is None or not ser.is_open:
                try:
                    ser = serial.Serial(self.port, self.baudrate, timeout=1)
                    logger.info("Đang lắng nghe đầu đọc thẻ qua %s (%d baud)", self.port, self.baudrate)
                except serial.SerialException:
                    logger.warning("Không mở được cổng %s, thử lại sau %.0fs", self.port, self._reconnect_delay)
                    time.sleep(self._reconnect_delay)
                    continue
            try:
                chunk = ser.read(64)
            except serial.SerialException:
                logger.warning("Mất kết nối cổng %s, thử kết nối lại", self.port)
                ser.close()
                ser = None
                time.sleep(self._reconnect_delay)
                continue
            for b in chunk:
                ch = chr(b)
                if ch in ("\r", "\n"):
                    if buffer:
                        card_number = "".join(buffer)
                        buffer.clear()
                        logger.info("Quẹt thẻ: %s", card_number)
                        on_card(card_number)
                elif ch.isdigit():
                    buffer.append(ch)
                # Ký tự khác số/xuống dòng (byte điều khiển khung nếu có) -> bỏ qua.
        if ser is not None:
            ser.close()
