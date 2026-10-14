"""Đầu đọc thẻ USB trên Windows — dùng thư viện `keyboard` để hook bàn phím
toàn hệ thống, vì đầu đọc USB kiểu HID keyboard-wedge trên Windows xuất hiện
y như 1 bàn phím thường (không cần driver/`evdev` như trên Linux).

Chỉ chạy được trên Windows (và cần quyền phù hợp — thư viện `keyboard` trên
Windows thường chạy được với user thường, không cần admin, khác với Linux
cần root). Dùng trong `scripts/windows_hardware_agent.py`, KHÔNG chạy trong
Docker (container Linux không thấy bàn phím của Windows host).
"""
from __future__ import annotations

import logging
from typing import Callable

from app.card_reader.interface import CardReader

logger = logging.getLogger("card_reader.windows")

_DIGIT_NAMES = {str(i) for i in range(10)}


class WindowsKeyboardCardReader(CardReader):
    def __init__(self):
        import keyboard  # import trễ — chỉ cần có khi thực sự chạy trên Windows

        self._keyboard = keyboard
        self._buffer: list[str] = []
        self._on_card: Callable[[str], None] | None = None

    def _handle_key(self, event) -> None:
        if event.event_type != "down":
            return
        if event.name == "enter":
            if self._buffer and self._on_card:
                card_number = "".join(self._buffer)
                self._buffer.clear()
                logger.info("Quẹt thẻ: %s", card_number)
                self._on_card(card_number)
        elif event.name in _DIGIT_NAMES:
            self._buffer.append(event.name)

    def start(self, on_card: Callable[[str], None]) -> None:
        self._on_card = on_card
        self._keyboard.hook(self._handle_key)
        logger.info("Đang lắng nghe đầu đọc thẻ USB (keyboard hook toàn hệ thống)...")

    def stop(self) -> None:
        self._keyboard.unhook_all()
        self._on_card = None
