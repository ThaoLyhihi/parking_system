"""Tính phí theo khung giờ — mô phỏng lại ý tưởng TblBieuPhi của phần mềm cũ
(nhiều mốc giá MucGia01..14 theo khung giờ GioBatDau0x/GioKetThuc0x). Bản này
đơn giản hoá thành "giờ đầu / giờ tiếp theo" (xem config/config.example.yaml),
đủ cho demo — khi triển khai thật nên nhập đúng biểu phí thật của bãi xe.
"""
from __future__ import annotations

import datetime as dt
import math


def calculate_fee(vehicle_type: str, time_in: dt.datetime, time_out: dt.datetime,
                   fee_schedule: dict) -> int:
    rules = fee_schedule.get(vehicle_type)
    if not rules:
        return 0
    # Demo: dùng rule đầu tiên khớp cả ngày (00:00-24:00). Biểu phí thật có thể
    # có nhiều khung giờ khác nhau trong ngày — cần tách theo time_in.time().
    rule = rules[0]
    duration = time_out - time_in
    hours = max(math.ceil(duration.total_seconds() / 3600), 1)
    if hours <= 1:
        return rule["first_hour"]
    return rule["first_hour"] + (hours - 1) * rule["next_hour"]


# ---- Biểu phí lưu trong DB (bảng tariffs), quản lý từ giao diện admin ---------

def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _in_window(tariff, minute_of_day: int) -> bool:
    start, end = _minutes(tariff.start_time), _minutes(tariff.end_time)
    if start <= end:
        return start <= minute_of_day < end
    return minute_of_day >= start or minute_of_day < end  # khung qua nửa đêm, vd 22:00-06:00


def fee_from_tariff(tariff, time_in: dt.datetime, time_out: dt.datetime, tz_offset_hours: float = 7) -> int:
    seconds = max((time_out - time_in).total_seconds(), 0)
    if tariff.mode == "flat":
        fee = tariff.first_fee
    else:
        blocks = max(math.ceil(seconds / 60 / max(tariff.block_minutes, 1)), 1)
        fee = tariff.first_fee + (blocks - 1) * tariff.next_fee
    if tariff.max_fee_per_day:
        fee = min(fee, tariff.max_fee_per_day * max(math.ceil(seconds / 86400), 1))
    if tariff.overnight_fee:
        offset = dt.timedelta(hours=tz_offset_hours)
        nights = (time_out + offset).date() - (time_in + offset).date()
        fee += tariff.overnight_fee * nights.days
    return int(fee)


def calculate_fee_db(db, vehicle_type: str, time_in: dt.datetime, time_out: dt.datetime,
                     fee_schedule: dict | None = None, tz_offset_hours: float = 7) -> int:
    """Chọn khung giờ theo giờ VÀO xe; chưa có biểu phí nào trong DB cho loại này
    thì dùng fee_schedule trong config.yaml (cách cũ)."""
    from app.db.models import Tariff

    rules = db.query(Tariff).filter(Tariff.vehicle_type_code == vehicle_type, Tariff.is_active.is_(True)).all()
    if not rules:
        return calculate_fee(vehicle_type, time_in, time_out, fee_schedule or {})
    local_in = time_in + dt.timedelta(hours=tz_offset_hours)
    minute = local_in.hour * 60 + local_in.minute
    rule = next((r for r in rules if _in_window(r, minute)), rules[0])
    return fee_from_tariff(rule, time_in, time_out, tz_offset_hours)
