"""Đếm chỗ trống — Hướng B (đếm theo luồng vào/ra), xem mục 4.2/6.4 thuyết minh.

Tương đương trực tiếp với SoXeVao/SoXeRa trong TblTongDoanhThu của phần mềm
cũ — ở đó phần mềm cũ ĐÃ làm đúng việc này, chỉ là không tách thành module AI
riêng. Hướng A (phân loại theo ô cố định, per-slot) KHÔNG nằm trong module
này — xem app/occupancy/slot_classifier.py (chưa triển khai, cần dữ liệu ảnh
camera toàn cảnh + nhãn ô mới làm được, xem mục 6.4 thuyết minh).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FlowCounter:
    capacity_by_type: dict[str, int]
    vehicles_in: dict[str, int] = field(default_factory=dict)
    vehicles_out: dict[str, int] = field(default_factory=dict)

    def record_entry(self, vehicle_type: str) -> None:
        self.vehicles_in[vehicle_type] = self.vehicles_in.get(vehicle_type, 0) + 1

    def record_exit(self, vehicle_type: str) -> None:
        self.vehicles_out[vehicle_type] = self.vehicles_out.get(vehicle_type, 0) + 1

    def current_count(self, vehicle_type: str) -> int:
        return self.vehicles_in.get(vehicle_type, 0) - self.vehicles_out.get(vehicle_type, 0)

    def vacant_slots(self, vehicle_type: str) -> int:
        capacity = self.capacity_by_type.get(vehicle_type, 0)
        return max(capacity - self.current_count(vehicle_type), 0)

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {
            vt: {
                "in": self.vehicles_in.get(vt, 0),
                "out": self.vehicles_out.get(vt, 0),
                "current": self.current_count(vt),
                "vacant": self.vacant_slots(vt),
                "capacity": capacity,
            }
            for vt, capacity in self.capacity_by_type.items()
        }
