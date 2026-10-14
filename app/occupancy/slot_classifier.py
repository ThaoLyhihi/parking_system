"""Đếm chỗ trống — Hướng A (phân loại occupied/empty theo từng ô ROI cố định).

CHƯA TRIỂN KHAI. Khác với Module ALPR (đã có model sẵn từ phần mềm cũ) và
Hướng B (suy ra trực tiếp từ log ALPR, không cần model riêng), hướng này cần:
1. Camera toàn cảnh cố định góc, bãi có kẻ ô rõ ràng (mục 4.2 thuyết minh).
2. Một bộ dữ liệu ảnh toàn cảnh + nhãn occupied/empty theo từng ô (ví dụ theo
   kiểu PKLot/CNRPark-EXT) — hiện CHƯA có cho bãi xe của bạn.

Vì vậy đây chỉ là interface placeholder để kiến trúc tổng thể (mục 6.3
thuyết minh) có đủ 2 lựa chọn A/B khi bạn thực nghiệm so sánh — không giả vờ
đã có model. Khi có dữ liệu, cài đặt `classify()` bằng 1 CNN nhỏ (ví dụ
MobileNetV3) nhận vào crop của từng ô, trả về occupied/empty.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParkingSlotROI:
    slot_id: str
    polygon: list[tuple[float, float]]  # toạ độ tỉ lệ (0-1) trên khung camera toàn cảnh


class SlotClassifier:
    def __init__(self, slots: list[ParkingSlotROI]):
        self.slots = slots

    def classify(self, overview_frame) -> dict[str, bool]:
        raise NotImplementedError(
            "Hướng A chưa triển khai — cần dataset ảnh toàn cảnh + nhãn occupied/empty "
            "theo từng ô trước (xem docstring module này và mục 6.4 thuyết minh đề tài)."
        )
