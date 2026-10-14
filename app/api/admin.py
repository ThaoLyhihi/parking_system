"""API quản trị (chỉ admin): loại thẻ/xe, biểu phí, thẻ lượt, thẻ tháng, cài đặt phần mềm."""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import settings as app_settings
from app.auth import get_db, require_admin, require_agent
from app.config import config
from app.core.fee import calculate_fee_db
from app.db.models import Card, MonthlyPayment, Tariff, User, VehicleSession, VehicleType

router = APIRouter()
admin = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def _row(obj, cols: list[str]) -> dict:
    return {c: getattr(obj, c) for c in cols}


def _refresh_capacity(db: Session) -> None:
    from app.api.main import refresh_capacity  # import muộn để tránh vòng lặp import
    refresh_capacity(db)


# ---- Loại thẻ / loại xe -----------------------------------------------------

_VT_COLS = ["id", "code", "display_name", "is_monthly_pass", "monthly_fee", "max_uses", "expiry_warning_days",
            "capacity", "lpr_in_enabled", "lpr_out_enabled", "lpr_confirm_on_match",
            "barrier_in_id", "barrier_out_id", "is_active"]


class VehicleTypeIn(BaseModel):
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_]+$")
    display_name: str = Field(min_length=1, max_length=50)
    is_monthly_pass: bool = False
    monthly_fee: int = Field(0, ge=0)
    max_uses: int | None = Field(None, ge=0)
    expiry_warning_days: int = Field(5, ge=0)
    capacity: int = Field(0, ge=0)
    lpr_in_enabled: bool = True
    lpr_out_enabled: bool = True
    lpr_confirm_on_match: bool = True
    barrier_in_id: str = "1"
    barrier_out_id: str = "1"
    is_active: bool = True


@admin.get("/vehicle-types")
def list_vehicle_types(db: Session = Depends(get_db)) -> list[dict]:
    return [_row(v, _VT_COLS) for v in db.query(VehicleType).order_by(VehicleType.id)]


@admin.post("/vehicle-types", status_code=201)
def create_vehicle_type(p: VehicleTypeIn, db: Session = Depends(get_db)) -> dict:
    if db.query(VehicleType).filter(VehicleType.code == p.code).first():
        raise HTTPException(409, "Mã loại đã tồn tại")
    v = VehicleType(**p.model_dump())
    db.add(v)
    db.commit()
    _refresh_capacity(db)
    return _row(v, _VT_COLS)


@admin.put("/vehicle-types/{vt_id}")
def update_vehicle_type(vt_id: int, p: VehicleTypeIn, db: Session = Depends(get_db)) -> dict:
    v = db.get(VehicleType, vt_id)
    if v is None:
        raise HTTPException(404, "Không tìm thấy loại")
    if p.code != v.code:
        raise HTTPException(400, "Không đổi mã loại (đã gắn với thẻ, biểu phí, lượt xe) — hãy tạo loại mới")
    for k, val in p.model_dump().items():
        setattr(v, k, val)
    db.commit()
    _refresh_capacity(db)
    return _row(v, _VT_COLS)


@admin.delete("/vehicle-types/{vt_id}", status_code=204)
def delete_vehicle_type(vt_id: int, db: Session = Depends(get_db)) -> None:
    v = db.get(VehicleType, vt_id)
    if v is None:
        raise HTTPException(404, "Không tìm thấy loại")
    if db.query(Card).filter(Card.vehicle_type_code == v.code).first() or \
            db.query(VehicleSession).filter(VehicleSession.vehicle_type_code == v.code).first():
        raise HTTPException(409, "Loại này đã có thẻ/lượt xe — hãy bỏ chọn 'Đang sử dụng' thay vì xoá")
    db.query(Tariff).filter(Tariff.vehicle_type_code == v.code).delete()
    db.delete(v)
    db.commit()
    _refresh_capacity(db)


# ---- Biểu phí ---------------------------------------------------------------

_TF_COLS = ["id", "vehicle_type_code", "name", "start_time", "end_time", "mode", "first_fee", "next_fee",
            "block_minutes", "max_fee_per_day", "overnight_fee", "is_active"]
_HHMM = r"^([01]\d|2[0-4]):[0-5]\d$"


class TariffIn(BaseModel):
    vehicle_type_code: str
    name: str = "Mặc định"
    start_time: str = Field("00:00", pattern=_HHMM)
    end_time: str = Field("24:00", pattern=_HHMM)
    mode: str = Field("flat", pattern=r"^(flat|block)$")
    first_fee: int = Field(0, ge=0)
    next_fee: int = Field(0, ge=0)
    block_minutes: int = Field(60, ge=1)
    max_fee_per_day: int | None = Field(None, ge=0)
    overnight_fee: int = Field(0, ge=0)
    is_active: bool = True


def _check_type(db: Session, code: str) -> None:
    if not db.query(VehicleType).filter(VehicleType.code == code).first():
        raise HTTPException(422, f"Loại xe '{code}' không tồn tại")


@admin.get("/tariffs")
def list_tariffs(db: Session = Depends(get_db)) -> list[dict]:
    return [_row(t, _TF_COLS) for t in db.query(Tariff).order_by(Tariff.vehicle_type_code, Tariff.start_time)]


@admin.post("/tariffs", status_code=201)
def create_tariff(p: TariffIn, db: Session = Depends(get_db)) -> dict:
    _check_type(db, p.vehicle_type_code)
    t = Tariff(**p.model_dump())
    db.add(t)
    db.commit()
    return _row(t, _TF_COLS)


@admin.put("/tariffs/{tariff_id}")
def update_tariff(tariff_id: int, p: TariffIn, db: Session = Depends(get_db)) -> dict:
    t = db.get(Tariff, tariff_id)
    if t is None:
        raise HTTPException(404, "Không tìm thấy biểu phí")
    _check_type(db, p.vehicle_type_code)
    for k, val in p.model_dump().items():
        setattr(t, k, val)
    db.commit()
    return _row(t, _TF_COLS)


@admin.delete("/tariffs/{tariff_id}", status_code=204)
def delete_tariff(tariff_id: int, db: Session = Depends(get_db)) -> None:
    t = db.get(Tariff, tariff_id)
    if t is None:
        raise HTTPException(404, "Không tìm thấy biểu phí")
    db.delete(t)
    db.commit()


@admin.get("/tariffs/preview")
def preview_tariff(vehicle_type: str, hours: float = 1, hour_in: int = 9, db: Session = Depends(get_db)) -> dict:
    """Tính thử: xe `vehicle_type` vào lúc `hour_in` giờ (giờ địa phương), gửi `hours` giờ thì phí bao nhiêu."""
    tz = config.get("timezone_offset_hours", 7)
    t_in = dt.datetime(2030, 1, 1, hour_in % 24) - dt.timedelta(hours=tz)
    t_out = t_in + dt.timedelta(hours=hours)
    return {"amount": calculate_fee_db(db, vehicle_type, t_in, t_out, config.get("fee_schedule", {}), tz)}


# ---- Thẻ lượt + thẻ tháng ---------------------------------------------------

_CARD_COLS = ["id", "card_number", "label", "vehicle_type_code", "plate_number", "owner_name", "room_number",
              "description", "start_date", "expire_date", "remaining_uses", "status"]


class CardIn(BaseModel):
    card_number: str = Field(min_length=1, max_length=24)
    label: str | None = Field(None, max_length=20)
    vehicle_type_code: str
    plate_number: str | None = Field(None, max_length=20)
    owner_name: str | None = Field(None, max_length=100)
    room_number: str | None = Field(None, max_length=50)
    description: str | None = Field(None, max_length=100)
    start_date: dt.date | None = None
    expire_date: dt.date | None = None
    remaining_uses: int | None = Field(None, ge=0)
    status: str = Field("active", pattern=r"^(active|locked)$")


def _card_out(c: Card, types: dict[str, VehicleType]) -> dict:
    d = _row(c, _CARD_COLS)
    vt = types.get(c.vehicle_type_code)
    d["is_monthly_pass"] = bool(vt and vt.is_monthly_pass)
    d["type_name"] = vt.display_name if vt else c.vehicle_type_code
    return d


def _validate_card(db: Session, p: CardIn) -> VehicleType:
    vt = db.query(VehicleType).filter(VehicleType.code == p.vehicle_type_code).first()
    if vt is None:
        raise HTTPException(422, f"Loại thẻ '{p.vehicle_type_code}' không tồn tại")
    if vt.is_monthly_pass and (p.start_date is None or p.expire_date is None):
        raise HTTPException(422, "Thẻ tháng phải có ngày bắt đầu và ngày hết hạn")
    if p.start_date and p.expire_date and p.expire_date < p.start_date:
        raise HTTPException(422, "Ngày hết hạn phải sau ngày bắt đầu")
    return vt


@admin.get("/cards")
def list_cards(kind: str | None = None, q: str | None = None, status: str | None = None,
               expiring_days: int | None = None, limit: int = 100, offset: int = 0,
               db: Session = Depends(get_db)) -> dict:
    """kind: "daily" (thẻ lượt) | "monthly" (thẻ tháng). q tìm theo mã thẻ/số thẻ/biển số/chủ xe/phòng."""
    types = {v.code: v for v in db.query(VehicleType)}
    query = db.query(Card)
    if kind in ("daily", "monthly"):
        codes = [c for c, v in types.items() if v.is_monthly_pass == (kind == "monthly")]
        query = query.filter(Card.vehicle_type_code.in_(codes))
    if status:
        query = query.filter(Card.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Card.card_number.like(like), Card.label.like(like), Card.plate_number.like(like),
                                 Card.owner_name.like(like), Card.room_number.like(like)))
    if expiring_days is not None:
        today = dt.date.today()
        query = query.filter(Card.expire_date.is_not(None), Card.expire_date <= today + dt.timedelta(days=expiring_days))
    total = query.count()
    rows = query.order_by(Card.id.desc()).offset(max(offset, 0)).limit(min(limit, 500)).all()
    return {"total": total, "items": [_card_out(c, types) for c in rows]}


@admin.post("/cards", status_code=201)
def create_card(p: CardIn, db: Session = Depends(get_db)) -> dict:
    _validate_card(db, p)
    if db.query(Card).filter(Card.card_number == p.card_number).first():
        raise HTTPException(409, "Mã thẻ đã tồn tại")
    c = Card(**p.model_dump())
    db.add(c)
    db.commit()
    return _card_out(c, {v.code: v for v in db.query(VehicleType)})


@admin.put("/cards/{card_id}")
def update_card(card_id: int, p: CardIn, db: Session = Depends(get_db)) -> dict:
    c = db.get(Card, card_id)
    if c is None:
        raise HTTPException(404, "Không tìm thấy thẻ")
    _validate_card(db, p)
    if p.card_number != c.card_number:
        if db.query(Card).filter(Card.card_number == p.card_number).first():
            raise HTTPException(409, "Mã thẻ đã tồn tại")
        if db.query(VehicleSession).filter(VehicleSession.card_number == c.card_number,
                                           VehicleSession.status == "open").first():
            raise HTTPException(409, "Thẻ đang có xe trong bãi, không đổi mã thẻ được")
    for k, val in p.model_dump().items():
        setattr(c, k, val)
    db.commit()
    return _card_out(c, {v.code: v for v in db.query(VehicleType)})


@admin.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: int, db: Session = Depends(get_db)) -> None:
    c = db.get(Card, card_id)
    if c is None:
        raise HTTPException(404, "Không tìm thấy thẻ")
    if db.query(VehicleSession).filter(VehicleSession.card_number == c.card_number).first():
        raise HTTPException(409, "Thẻ đã có lịch sử gửi xe — hãy khoá thẻ thay vì xoá")
    db.query(MonthlyPayment).filter(MonthlyPayment.card_id == c.id).delete()
    db.delete(c)
    db.commit()


class RenewIn(BaseModel):
    months: int = Field(1, ge=1, le=36)
    amount: int | None = Field(None, ge=0)  # bỏ trống = đơn giá loại thẻ x số tháng


def _add_months(d: dt.date, months: int) -> dt.date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    last = (dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(year, month, min(d.day, last))


@admin.post("/cards/{card_id}/renew")
def renew_card(card_id: int, p: RenewIn, who: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Gia hạn vé tháng: cộng thêm p.months tháng tính từ ngày hết hạn (nếu còn hạn) hoặc từ hôm nay (nếu đã hết)."""
    c = db.get(Card, card_id)
    vt = db.query(VehicleType).filter(VehicleType.code == c.vehicle_type_code).first() if c else None
    if c is None:
        raise HTTPException(404, "Không tìm thấy thẻ")
    if not (vt and vt.is_monthly_pass):
        raise HTTPException(400, "Chỉ gia hạn được thẻ tháng")
    today = (dt.datetime.utcnow() + dt.timedelta(hours=config.get("timezone_offset_hours", 7))).date()
    base = c.expire_date if c.expire_date and c.expire_date >= today else today
    new_expire = _add_months(base, p.months)
    amount = p.amount if p.amount is not None else vt.monthly_fee * p.months
    db.add(MonthlyPayment(card_id=c.id, amount=amount, period_start=base, period_end=new_expire, user_id=who.id))
    c.start_date = c.start_date or today
    c.expire_date = new_expire
    c.status = "active"
    db.commit()
    return {"card": _card_out(c, {v.code: v for v in db.query(VehicleType)}), "amount": amount}


@admin.get("/cards/{card_id}/payments")
def card_payments(card_id: int, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(MonthlyPayment).filter(MonthlyPayment.card_id == card_id).order_by(MonthlyPayment.paid_at.desc())
    return [_row(r, ["id", "amount", "paid_at", "period_start", "period_end"]) for r in rows]


@admin.get("/monthly-revenue")
def monthly_revenue(year: int | None = None, db: Session = Depends(get_db)) -> list[dict]:
    """Doanh thu vé tháng theo tháng (tách riêng doanh thu thu theo lượt trong báo cáo ca)."""
    year = year or dt.date.today().year
    rows = db.query(MonthlyPayment).filter(MonthlyPayment.paid_at >= dt.datetime(year, 1, 1),
                                           MonthlyPayment.paid_at < dt.datetime(year + 1, 1, 1)).all()
    by_month: dict[int, list[int]] = {}
    for r in rows:
        by_month.setdefault(r.paid_at.month, []).append(r.amount)
    return [{"month": m, "count": len(v), "amount": sum(v)} for m, v in sorted(by_month.items())]


# ---- Cài đặt phần mềm -------------------------------------------------------

@admin.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict:
    """Schema (để giao diện tự vẽ form) + giá trị hiện tại; secret không trả về."""
    return {name: {"title": sec["title"], "note": sec.get("note"), "fields": sec["fields"],
                   "values": app_settings.public_section(db, name)}
            for name, sec in app_settings.SCHEMA.items()}


@admin.put("/settings/{section}")
def put_settings(section: str, values: dict[str, Any], db: Session = Depends(get_db)) -> dict:
    if section not in app_settings.SCHEMA:
        raise HTTPException(404, "Không có mục cài đặt này")
    try:
        app_settings.save_section(db, section, values)
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        raise HTTPException(422, f"Giá trị không hợp lệ: {e}")
    restart = any(f.get("restart") for f in app_settings.SCHEMA[section]["fields"] if f["key"] in values)
    return {"values": app_settings.public_section(db, section), "restart_required": restart}


# ---- Hardware agent kéo cấu hình từ server ----------------------------------

@router.get("/agent/config", dependencies=[Depends(require_agent)])
def agent_config(db: Session = Depends(get_db)) -> dict:
    """Agent trên máy Windows lấy cấu hình barie/đầu đọc thẻ đã chỉnh trên giao diện (khỏi sửa file tay)."""
    return {s: app_settings.get_section(db, s) for s in ("barrier_hardware", "card_reader", "hardware_agent")}


router.include_router(admin)
