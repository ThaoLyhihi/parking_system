"""Đầu đọc thẻ giả lập — dùng để test/demo khi chưa có đầu đọc USB thật cắm vào
máy (đúng tình huống môi trường phát triển hiện tại)."""
from __future__ import annotations

from typing import Callable

from app.card_reader.interface import CardReader


class SimulatedCardReader(CardReader):
    def __init__(self):
        self._on_card: Callable[[str], None] | None = None

    def start(self, on_card: Callable[[str], None]) -> None:
        self._on_card = on_card

    def stop(self) -> None:
        self._on_card = None

    def simulate_scan(self, card_number: str) -> None:
        """Gọi hàm này trong test/demo để giả lập 1 lượt quẹt thẻ."""
        if self._on_card:
            self._on_card(card_number)
