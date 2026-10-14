"""Thống kê theo ca làm việc + xuất PDF báo cáo gửi quản lý."""
from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import config
from app.db.models import Transaction, User, VehicleSession, WorkShift

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
pdfmetrics.registerFont(TTFont("DejaVu", str(_FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(_FONT_DIR / "DejaVuSans-Bold.ttf")))

# DB lưu UTC (naive); hiển thị theo giờ địa phương của bãi xe.
_TZ_OFFSET = dt.timedelta(hours=config.get("timezone_offset_hours", 7))


def local(t: dt.datetime | None) -> dt.datetime | None:
    return t + _TZ_OFFSET if t else None


def fmt_dt(t: dt.datetime | None) -> str:
    return local(t).strftime("%d/%m/%Y %H:%M") if t else "—"


def fmt_money(v: int) -> str:
    return f"{v:,}".replace(",", ".") + " đ"


def shift_stats(db: Session, ws: WorkShift) -> dict:
    """Số liệu của 1 ca: xe vào/ra do ca này quét, tiền thu, và số xe còn tồn
    trong bãi tại thời điểm xem (tồn là trạng thái toàn bãi, không riêng ca)."""
    in_by_type = dict(
        db.query(VehicleSession.vehicle_type_code, func.count())
        .filter(VehicleSession.work_shift_id == ws.id)
        .group_by(VehicleSession.vehicle_type_code).all()
    )
    out_rows = (
        db.query(VehicleSession.vehicle_type_code, func.count(), func.coalesce(func.sum(Transaction.amount), 0))
        .join(Transaction, Transaction.session_id == VehicleSession.id)
        .filter(Transaction.work_shift_id == ws.id)
        .group_by(VehicleSession.vehicle_type_code).all()
    )
    out_by_type = {t: c for t, c, _ in out_rows}
    amount_by_type = {t: int(a) for t, _, a in out_rows}
    remain_by_type = dict(
        db.query(VehicleSession.vehicle_type_code, func.count())
        .filter(VehicleSession.status == "open")
        .group_by(VehicleSession.vehicle_type_code).all()
    )
    types = sorted(set(in_by_type) | set(out_by_type) | set(remain_by_type))
    return {
        "shift_id": ws.id,
        "status": ws.status,
        "started_at": ws.started_at.isoformat(),
        "ended_at": ws.ended_at.isoformat() if ws.ended_at else None,
        "vehicles_in": sum(in_by_type.values()),
        "vehicles_out": sum(out_by_type.values()),
        "vehicles_remaining": sum(remain_by_type.values()),
        "total_amount": sum(amount_by_type.values()),
        "by_type": [
            {"type": t, "in": in_by_type.get(t, 0), "out": out_by_type.get(t, 0),
             "remaining": remain_by_type.get(t, 0), "amount": amount_by_type.get(t, 0)}
            for t in types
        ],
    }


def shift_transactions(db: Session, ws: WorkShift) -> list[dict]:
    rows = (
        db.query(Transaction, VehicleSession.vehicle_type_code, VehicleSession.card_number)
        .join(VehicleSession, Transaction.session_id == VehicleSession.id)
        .filter(Transaction.work_shift_id == ws.id)
        .order_by(Transaction.time_out).all()
    )
    return [{"card": card, "type": vt, "plate_in": t.plate_in, "plate_out": t.plate_out,
             "time_in": t.time_in, "time_out": t.time_out, "amount": t.amount}
            for t, vt, card in rows]


def build_shift_pdf(db: Session, ws: WorkShift) -> bytes:
    stats = shift_stats(db, ws)
    guard = db.get(User, ws.user_id)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                            title=f"Báo cáo ca #{ws.id}", author=guard.full_name if guard else "")
    base = ParagraphStyle("base", fontName="DejaVu", fontSize=10, leading=14)
    h1 = ParagraphStyle("h1", parent=base, fontName="DejaVu-Bold", fontSize=16, leading=20, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=base, fontName="DejaVu-Bold", fontSize=12, spaceBefore=12, spaceAfter=4)

    def table(data, widths, align_right_from=1):
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "DejaVu"), ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return t

    story = [
        Paragraph("BÁO CÁO CA TRỰC BÃI GIỮ XE", h1),
        Paragraph(f"Ca #{ws.id} — Nhân viên: <b>{guard.full_name if guard else '?'}</b> "
                  f"({guard.username if guard else '?'})", base),
        Paragraph(f"Bắt đầu: {fmt_dt(ws.started_at)} &nbsp;&nbsp; Kết thúc: "
                  f"{fmt_dt(ws.ended_at) if ws.ended_at else 'chưa kết ca'}", base),
        Paragraph("Tổng hợp", h2),
        table([["Xe vào", "Xe ra", "Xe còn tồn trong bãi", "Tiền thu"],
               [stats["vehicles_in"], stats["vehicles_out"], stats["vehicles_remaining"],
                fmt_money(stats["total_amount"])]], [3.5 * cm, 3.5 * cm, 5 * cm, 4.5 * cm], 0),
        Paragraph("Theo loại xe", h2),
        table([["Loại xe", "Vào", "Ra", "Tồn", "Tiền thu"]] +
              [[r["type"], r["in"], r["out"], r["remaining"], fmt_money(r["amount"])] for r in stats["by_type"]],
              [4.5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 4.5 * cm]),
        Paragraph("Chi tiết xe ra trong ca", h2),
    ]
    txs = shift_transactions(db, ws)
    if txs:
        story.append(table(
            [["Giờ ra", "Thẻ", "Loại", "Biển số", "Tiền"]] +
            [[fmt_dt(x["time_out"]), x["card"] or "", x["type"], x["plate_out"] or x["plate_in"] or "—",
              fmt_money(x["amount"])] for x in txs],
            [3.6 * cm, 3.4 * cm, 2.6 * cm, 3.6 * cm, 3.6 * cm], 4))
    else:
        story.append(Paragraph("Chưa có xe ra trong ca.", base))
    story += [Spacer(1, 10), Paragraph(
        f"Xuất lúc {fmt_dt(dt.datetime.utcnow())}. Số xe tồn là số xe còn trong bãi tại thời điểm xuất.", base)]
    doc.build(story)
    return buf.getvalue()
