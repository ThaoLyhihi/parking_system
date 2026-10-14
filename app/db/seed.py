"""Dữ liệu khởi tạo, lấy từ CSDL cũ (TblLoaiThe, TblBieuPhi, TblCaTruc) khi bảng còn trống.

Chỉ nạp DANH MỤC (loại thẻ, biểu phí, ca) — không nạp thẻ/giao dịch/khách hàng thật của bãi cũ.
Biểu phí cũ dùng cột MucGia01..14 khó suy ra ý nghĩa, nên chỉ nạp những mức rõ ràng
(phí đồng giá theo lượt: OTO/XeHoi 20.000, XeDap 3.000; miễn phí: NhanVien/VIP). Xe máy
dùng giá trong config.example.yaml — admin cần kiểm tra lại ở mục Biểu phí."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.config import config
from app.db.models import Shift, Tariff, VehicleType

# code, tên, vé tháng, giá tháng, sức chứa, lpr vào, lpr ra, barie vào, barie ra
_TYPES = [
    ("XeMay", "Xe máy", False, 0, "XeMay", True, True, "2", "2"),
    ("XeDap", "Xe đạp", False, 0, "XeDap", False, False, "2", "2"),
    ("XeDapDien", "Xe đạp điện", False, 0, None, False, False, "2", "2"),
    ("OTO", "Ô tô", False, 0, "OTO", True, True, "1", "1"),
    ("XeHoi", "Xe hơi", False, 0, None, True, True, "1", "1"),
    ("NhanVien", "Nhân viên", False, 0, None, False, False, "1", "2"),
    ("VIP", "VIP", False, 0, None, False, False, "1", "1"),
    ("XeMayThang", "Xe máy vé tháng", True, 12000, None, False, True, "7", "8"),
    ("OTOThang", "Ô tô vé tháng", True, 700000, None, False, False, "9", "10"),
]


def seed_defaults(db: Session) -> None:
    if db.query(VehicleType).count() == 0:
        capacity = config.get("capacity", {}) or {}
        for code, name, monthly, fee, cap_key, lin, lout, bin_, bout in _TYPES:
            db.add(VehicleType(
                code=code, display_name=name, is_monthly_pass=monthly, monthly_fee=fee,
                max_uses=10000 if monthly else None, expiry_warning_days=5,
                capacity=capacity.get(cap_key or code, 0),
                lpr_in_enabled=lin, lpr_out_enabled=lout, lpr_confirm_on_match=True,
                barrier_in_id=bin_, barrier_out_id=bout))
        db.commit()
    if db.query(Tariff).count() == 0:
        xm = (config.get("fee_schedule", {}) or {}).get("XeMay", [{}])[0]
        db.add_all([
            Tariff(vehicle_type_code="XeMay", name="Mặc định", mode="block",
                   first_fee=xm.get("first_hour", 3000), next_fee=xm.get("next_hour", 2000), block_minutes=60),
            Tariff(vehicle_type_code="OTO", name="Đồng giá/lượt", mode="flat", first_fee=20000),
            Tariff(vehicle_type_code="XeHoi", name="Đồng giá/lượt", mode="flat", first_fee=20000),
            Tariff(vehicle_type_code="XeDap", name="Đồng giá/lượt", mode="flat", first_fee=3000),
        ])
        db.commit()
    if db.query(Shift).count() == 0:
        t = dt.time
        db.add_all([Shift(name="Ca 1", start_time=t(8), end_time=t(16)),
                    Shift(name="Ca 2", start_time=t(16), end_time=t(0)),
                    Shift(name="Ca 3", start_time=t(0), end_time=t(8))])
        db.commit()
