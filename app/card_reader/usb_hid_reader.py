"""Đọc đầu đọc thẻ USB kiểu "keyboard wedge" bằng `evdev` (chỉ chạy trên Linux).

Thiết bị loại này xuất hiện trong hệ thống như một bàn phím USB bình thường
(`/dev/input/eventX`), nên đọc trực tiếp ở mức thiết bị input — KHÔNG cần ứng
dụng phải đang có ô nhập liệu được focus (khác với cách làm keyboard-wedge
kiểu cũ là gõ vào 1 textbox) — phù hợp hơn cho 1 service chạy nền/Docker.

Yêu cầu: user chạy service phải có quyền đọc `/dev/input/eventX` tương ứng
(thường cần thêm vào group `input`, hoặc chạy trong Docker với
`--device=/dev/input/eventX`, xem README mục Docker).
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from app.card_reader.interface import CardReader

logger = logging.getLogger("card_reader.usb_hid")

# Map keycode -> ký tự, chỉ cần số + Enter vì thẻ chỉ gồm chữ số.
_DIGIT_KEYS = {
    "KEY_0": "0", "KEY_1": "1", "KEY_2": "2", "KEY_3": "3", "KEY_4": "4",
    "KEY_5": "5", "KEY_6": "6", "KEY_7": "7", "KEY_8": "8", "KEY_9": "9",
    "KEY_KP0": "0", "KEY_KP1": "1", "KEY_KP2": "2", "KEY_KP3": "3", "KEY_KP4": "4",
    "KEY_KP5": "5", "KEY_KP6": "6", "KEY_KP7": "7", "KEY_KP8": "8", "KEY_KP9": "9",
}
_ENTER_KEYS = {"KEY_ENTER", "KEY_KPENTER"}


class UsbHidCardReader(CardReader):
    def __init__(self, device_path: str | None = None, device_name_contains: str | None = None):
        """Chỉ định 1 trong 2: `device_path` (vd "/dev/input/event5") nếu đã biết chắc,
        hoặc `device_name_contains` để tự dò tìm theo tên thiết bị (vd "RFID", "HID Card Reader")
        — xem README mục "Dò tên đầu đọc thẻ" để biết cách lấy tên thiết bị thật."""
        self.device_path = device_path
        self.device_name_contains = device_name_contains
        self._buffer: list[str] = []
        self._thread: threading.Thread | None = None
        self._running = False

    def _find_device(self):
        import evdev

        if self.device_path:
            return evdev.InputDevice(self.device_path)

        for path in evdev.list_devices():
            dev = evdev.InputDevice(path)
            if self.device_name_contains and self.device_name_contains.lower() in dev.name.lower():
                return dev
        raise RuntimeError(
            f"Không tìm thấy đầu đọc thẻ USB khớp tên chứa {self.device_name_contains!r}. "
            "Chạy `python -c \"import evdev; [print(evdev.InputDevice(p).name) for p in evdev.list_devices()]\"` "
            "để xem danh sách thiết bị input hiện có."
        )

    def start(self, on_card: Callable[[str], None]) -> None:
        import evdev

        self._running = True

        def _loop():
            device = self._find_device()
            logger.info("Đang lắng nghe đầu đọc thẻ: %s (%s)", device.name, device.path)
            for event in device.read_loop():
                if not self._running:
                    break
                if event.type != evdev.ecodes.EV_KEY or event.value != 1:  # chỉ xử lý key-down
                    continue
                key = evdev.ecodes.KEY[event.code]
                key = key if isinstance(key, str) else key[0]
                if key in _ENTER_KEYS:
                    if self._buffer:
                        card_number = "".join(self._buffer)
                        self._buffer.clear()
                        logger.info("Quẹt thẻ: %s", card_number)
                        on_card(card_number)
                elif key in _DIGIT_KEYS:
                    self._buffer.append(_DIGIT_KEYS[key])

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
