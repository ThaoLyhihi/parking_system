"""ORM models cho phần mềm mới.

Đây là bản viết lại từ đầu (không migrate dữ liệu từ CSDL cũ), nhưng vẫn giữ
tương đương nghiệp vụ với schema thật đã đọc được từ phần mềm cũ, để dễ đối
chiếu khi cần. Bảng cũ tương ứng được ghi trong docstring mỗi class
(xem NCKH_he_thong_giu_xe_tu_dong/QUY_TRINH_LAM_LAI_PHAN_MEM.md mục 2).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class VehicleType(Base):
    """Loại thẻ/loại xe — tương ứng TblLoaiThe cũ (OTO, XeMay, XeDap, OTOThang, XeMayThang, VIP, NhanVien...)
    kết hợp phần InOutConf trong app.config.xml (bật LPR + barie riêng cho từng loại thẻ)."""

    __tablename__ = "vehicle_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # vd "XeMay", "OTO"
    display_name: Mapped[str] = mapped_column(String(50))
    is_monthly_pass: Mapped[bool] = mapped_column(Boolean, default=False)
    monthly_fee: Mapped[int] = mapped_column(Integer, default=0)           # TblLoaiThe.MenhGia: giá 1 kỳ vé tháng
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)   # TblLoaiThe.SoLuot
    expiry_warning_days: Mapped[int] = mapped_column(Integer, default=5)   # TblLoaiThe.SoNgay: báo sắp hết hạn
    capacity: Mapped[int] = mapped_column(Integer, default=0)              # sức chứa (trước đây ở config.yaml)
    # InOutConf cũ: bật nhận diện biển số + barie dùng khi vào/ra cho loại thẻ này
    lpr_in_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    lpr_out_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    lpr_confirm_on_match: Mapped[bool] = mapped_column(Boolean, default=True)
    barrier_in_id: Mapped[str] = mapped_column(String(10), default="1")
    barrier_out_id: Mapped[str] = mapped_column(String(10), default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Tariff(Base):
    """Biểu phí — thay TblBieuPhi cũ (MucGia01..14 + giờ bắt đầu/kết thúc khó hiểu) bằng
    mỗi dòng = 1 khung giờ trong ngày của 1 loại xe, tên cột rõ nghĩa.

    mode "flat": thu first_fee mỗi lượt. mode "block": first_fee cho block đầu
    (block_minutes phút), next_fee cho mỗi block tiếp theo."""

    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_type_code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(50), default="Mặc định")
    start_time: Mapped[str] = mapped_column(String(5), default="00:00")  # HH:MM, giờ vào xe thuộc khung này
    end_time: Mapped[str] = mapped_column(String(5), default="24:00")
    mode: Mapped[str] = mapped_column(String(10), default="flat")
    first_fee: Mapped[int] = mapped_column(Integer, default=0)
    next_fee: Mapped[int] = mapped_column(Integer, default=0)
    block_minutes: Mapped[int] = mapped_column(Integer, default=60)
    max_fee_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)  # trần phí mỗi 24h
    overnight_fee: Mapped[int] = mapped_column(Integer, default=0)  # phụ thu mỗi đêm (qua 00:00)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Setting(Base):
    """[MỚI] Cài đặt phần mềm chỉnh được từ giao diện (ghi đè config.yaml), theo từng mục (section)."""

    __tablename__ = "settings"

    section: Mapped[str] = mapped_column(String(30), primary_key=True)
    value_json: Mapped[str] = mapped_column(String)


class Card(Base):
    """Thẻ/vé tháng — tương ứng TblQuanLyThe cũ."""

    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_number: Mapped[str] = mapped_column(String(24), unique=True)
    vehicle_type_code: Mapped[str] = mapped_column(String(20))
    plate_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    room_number: Mapped[str | None] = mapped_column(String(50), nullable=True)  # TblQuanLyThe.SoPhong
    start_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    expire_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | locked
    label: Mapped[str | None] = mapped_column(String(20), nullable=True)  # TblQuanLyThe.SoThe: số in trên thẻ
    description: Mapped[str | None] = mapped_column(String(100), nullable=True)  # TblQuanLyThe.MoTaXe
    remaining_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)  # TblQuanLyThe.SoLuot
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class MonthlyPayment(Base):
    """[MỚI] Lần đóng/gia hạn vé tháng — tương ứng TblDoanhThuVeThang (cũ chưa có dòng nào)."""

    __tablename__ = "monthly_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"))
    amount: Mapped[int] = mapped_column(Integer, default=0)
    paid_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    period_start: Mapped[dt.date]
    period_end: Mapped[dt.date]
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Staff(Base):
    """Nhân viên — tương ứng TblNhanVien."""

    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    staff_code: Mapped[str] = mapped_column(String(20), unique=True)
    full_name: Mapped[str] = mapped_column(String(50))
    department: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="active")


class Shift(Base):
    """Ca trực — tương ứng TblCaTruc."""

    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(20))
    start_time: Mapped[dt.time]
    end_time: Mapped[dt.time]


class VehicleSession(Base):
    """Lượt xe đang gửi / phiên chưa hoàn tất — tương ứng TblVanHanh.

    AI service ghi plate_in/image_in_path ngay khi ALPR nhận diện được xe vào;
    khi xe ra, cập nhật plate_out/image_out_path rồi (nếu khớp) chuyển dữ liệu
    sang bảng Transaction và xoá/đóng dòng này — mô phỏng đúng luồng
    TblVanHanh -> TblDoanhThu của phần mềm cũ (mục 2 trong tài liệu quy trình).
    """

    __tablename__ = "vehicle_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_number: Mapped[str | None] = mapped_column(String(24), nullable=True)
    vehicle_type_code: Mapped[str] = mapped_column(String(20))
    time_in: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    time_out: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    plate_in: Mapped[str | None] = mapped_column(String(20), nullable=True)
    plate_out: Mapped[str | None] = mapped_column(String(20), nullable=True)
    plate_in_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    plate_out_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Lưu đường dẫn file ảnh, KHÔNG lưu blob trong DB như cột `image` cũ (đã deprecated,
    # xem mục 4 trong tài liệu quy trình làm lại).
    image_in_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_out_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True)
    # Ca làm việc (đăng nhập thực tế của bảo vệ) đã quét thẻ cho xe VÀO.
    work_shift_id: Mapped[int | None] = mapped_column(ForeignKey("work_shifts.id"), nullable=True)


class Transaction(Base):
    """Giao dịch đã hoàn tất — tương ứng TblDoanhThu."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle_sessions.id"), nullable=True)
    card_number: Mapped[str | None] = mapped_column(String(24), nullable=True)
    time_in: Mapped[dt.datetime]
    time_out: Mapped[dt.datetime]
    amount: Mapped[int] = mapped_column(Integer, default=0)
    plate_in: Mapped[str | None] = mapped_column(String(20), nullable=True)
    plate_out: Mapped[str | None] = mapped_column(String(20), nullable=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True)
    staff_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Ca làm việc đã quét thẻ cho xe RA (tiền thu thuộc ca này).
    work_shift_id: Mapped[int | None] = mapped_column(ForeignKey("work_shifts.id"), nullable=True)


class ShiftSummary(Base):
    """Tổng kết mỗi ca trực — tương ứng TblTongDoanhThu.

    Đây là nơi đã có sẵn SoXeVao/SoXeRa trong phần mềm cũ — chính là "Hướng B"
    (đếm theo luồng vào/ra) trong thuyết minh đề tài (mục 4.2/6.4).
    """

    __tablename__ = "shift_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"))
    start_time: Mapped[dt.datetime]
    end_time: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    vehicles_in: Mapped[int] = mapped_column(Integer, default=0)
    vehicles_out: Mapped[int] = mapped_column(Integer, default=0)
    # Chi tiết theo loại xe, lưu dạng JSON string — tương đương XML <counterList> cũ.
    counts_by_type_json: Mapped[str | None] = mapped_column(String, nullable=True)


class AuditLog(Base):
    """Nhật ký thao tác — tương ứng TblNhatKi."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    staff_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class BarrierSafetyLog(Base):
    """[MỚI] Log của module an toàn barie — AI đóng vai trò cảm biến duy nhất
    (xác nhận: bãi xe không có cảm biến vật lý nào, xem mục 1d/4 tài liệu quy trình).

    Mỗi dòng là một lần hệ thống kiểm tra vùng ROI trước khi cho phép đóng barie.
    """

    __tablename__ = "barrier_safety_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    barrier_id: Mapped[str] = mapped_column(String(20))
    roi_clear: Mapped[bool] = mapped_column(Boolean)
    action_taken: Mapped[str] = mapped_column(String(20))  # "allow_close" | "hold_open" | "force_open"
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)


class User(Base):
    """[MỚI] Tài khoản đăng nhập hệ thống. role: "admin" (quản lý) | "guard" (bảo vệ).

    Mật khẩu chỉ lưu dạng băm (scrypt + salt), xem app/auth.py."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10), default="guard")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class AuthToken(Base):
    """[MỚI] Phiên đăng nhập. Chỉ lưu SHA-256 của token, không lưu token gốc."""

    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)


class WorkShift(Base):
    """[MỚI] Ca làm việc thực tế: mở khi bảo vệ đăng nhập, đóng khi bấm "Kết ca".
    Mọi lượt xe vào/ra và tiền thu được gắn vào ca này để thống kê/xuất PDF."""

    __tablename__ = "work_shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
