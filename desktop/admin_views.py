"""Các tab quản lý (chỉ admin): tổng quan, thẻ, loại thẻ/xe, biểu phí, tài khoản, ca & báo cáo."""
from __future__ import annotations

import datetime as dt
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLineEdit, QMessageBox,
                               QSpinBox, QVBoxLayout, QWidget)

from desktop.client import ApiClient, ApiError
from desktop.widgets import (Table, ask_form, button, confirm, guarded, label, local_time, money, show_error,
                             styled)


class Page(QWidget):
    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.setObjectName("page")
        self.api = api

    def reload(self) -> None:  # gọi khi tab được mở
        pass


# ---- Tổng quan --------------------------------------------------------------

class OverviewTab(Page):
    def __init__(self, api: ApiClient) -> None:
        super().__init__(api)
        lay = QVBoxLayout(self)
        self.cam = label("", "muted")
        self.barrier = label("", "muted")
        gb = QGroupBox("Hệ thống")
        gl = QVBoxLayout(gb)
        gl.addWidget(self.cam)
        gl.addWidget(self.barrier)
        lay.addWidget(gb)
        self.table = Table(["Loại xe", "Sức chứa", "Đang trong bãi", "Còn trống", "Tổng vào", "Tổng ra"])
        gb2 = QGroupBox("Chỗ trống theo loại xe (từ lúc khởi động)")
        QVBoxLayout(gb2).addWidget(self.table)
        lay.addWidget(gb2, 1)
        self.timer = QTimer(self, interval=4000)
        self.timer.timeout.connect(self.reload)
        self.timer.start()

    def reload(self) -> None:
        try:
            ov = self.api.get("/status/overview")
        except ApiError:
            return
        c, b = ov["cameras"], ov["barrier"]

        def st(configured: bool, connected: bool) -> str:
            return "chưa cấu hình" if not configured else ("đang kết nối ✔" if connected else "MẤT TÍN HIỆU ✖")
        self.cam.setText(f"Camera cổng vào: {st(c['gate_in_configured'], c['gate_in_connected'])}    •    "
                         f"Camera cổng ra: {'dùng chung cổng vào' if c['gate_out_shares_gate_in'] else st(c['gate_out_configured'], c['gate_out_connected'])}    •    "
                         f"Camera barie: {st(c['barrier_configured'], c['barrier_connected'])}")
        self.barrier.setText("An toàn barie: " + ("chưa cấu hình camera" if not b["configured"] else
                                                  ("an toàn để đóng" if b["safe_to_close"] else "đang có vật cản / chưa an toàn")))
        occ = ov["occupancy"]
        self.table.fill([[k, o["capacity"], o["current"], o["vacant"], o["in"], o["out"]] for k, o in occ.items()])


# ---- Khung CRUD dùng chung --------------------------------------------------

class CrudTab(Page):
    """Bảng + nút Thêm/Sửa/Xoá. Lớp con khai báo cột, hàm load, form, đường dẫn API."""
    headers: list[str] = []
    base_path = ""
    noun = ""

    def __init__(self, api: ApiClient) -> None:
        super().__init__(api)
        self.lay = QVBoxLayout(self)
        self.top = QHBoxLayout()
        self.lay.addLayout(self.top)
        self.table = Table(self.headers)
        self.table.doubleClicked.connect(lambda _: self.edit())
        self.lay.addWidget(self.table, 1)
        bar = QHBoxLayout()
        bar.addWidget(button(f"Thêm {self.noun}", self.add, primary=True))
        bar.addWidget(button("Sửa", self.edit))
        bar.addWidget(button("Xoá", self.delete, danger=True))
        self.extra_bar = QHBoxLayout()
        bar.addLayout(self.extra_bar)
        bar.addStretch(1)
        self.lay.addLayout(bar)

    # lớp con ghi đè
    def load(self) -> list[dict]: raise NotImplementedError
    def row(self, r: dict) -> list: raise NotImplementedError
    def fields(self) -> list[dict]: raise NotImplementedError
    def to_payload(self, vals: dict) -> dict: return vals
    def form_values(self, rec: dict) -> dict: return rec

    def reload(self) -> None:
        try:
            recs = self.load()
        except ApiError as e:
            show_error(self, e)
            return
        self.table.fill([self.row(r) for r in recs], recs)

    def add(self) -> None:
        vals = ask_form(self, f"Thêm {self.noun}", self.fields())
        if vals is not None and guarded(self, self.api.post, self.base_path, self.to_payload(vals)) is not None:
            self.reload()

    def edit(self) -> None:
        rec = self.table.current_record()
        if rec is None:
            return show_error(self, f"Hãy chọn {self.noun} cần sửa.")
        vals = ask_form(self, f"Sửa {self.noun}", self.fields(), self.form_values(rec))
        if vals is not None and guarded(self, self.api.put, f"{self.base_path}/{rec['id']}", self.to_payload(vals)) is not None:
            self.reload()

    def delete(self) -> None:
        rec = self.table.current_record()
        if rec is None:
            return show_error(self, f"Hãy chọn {self.noun} cần xoá.")
        if confirm(self, f"Xoá {self.noun} này?"):
            try:
                self.api.delete(f"{self.base_path}/{rec['id']}")
            except ApiError as e:
                return show_error(self, e)
            self.reload()


def _nullable_int(v: Any) -> int | None:
    v = (v or "").strip() if isinstance(v, str) else v
    return int(v) if v not in ("", None) else None


# ---- Thẻ lượt / thẻ tháng ---------------------------------------------------

class CardsTab(CrudTab):
    headers = ["Mã thẻ", "Nhãn", "Loại", "Biển số", "Chủ xe", "Phòng", "Hết hạn", "Lượt còn", "Trạng thái"]
    base_path = "/admin/cards"
    noun = "thẻ"

    def __init__(self, api: ApiClient) -> None:
        super().__init__(api)
        self.kind = QComboBox()
        for v, t in [("", "Tất cả thẻ"), ("daily", "Thẻ lượt"), ("monthly", "Thẻ tháng")]:
            self.kind.addItem(t, v)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm mã thẻ / biển số / chủ xe / phòng")
        self.expiring = QComboBox()
        for v, t in [(None, "Mọi hạn"), (0, "Đã hết hạn"), (7, "Hết hạn trong 7 ngày"), (30, "Hết hạn trong 30 ngày")]:
            self.expiring.addItem(t, v)
        self.top.addWidget(self.kind)
        self.top.addWidget(self.expiring)
        self.top.addWidget(self.search, 1)
        self.top.addWidget(button("Tìm", self.reload, primary=True))
        self.search.returnPressed.connect(self.reload)
        self.kind.currentIndexChanged.connect(lambda _: self.reload())
        self.expiring.currentIndexChanged.connect(lambda _: self.reload())
        self.extra_bar.addWidget(button("Gia hạn vé tháng", self.renew))
        self.extra_bar.addWidget(button("Lịch sử đóng tiền", self.payments))
        self.types: list[dict] = []

    def load(self) -> list[dict]:
        self.types = self.api.get("/admin/vehicle-types")
        return self.api.get("/admin/cards", kind=self.kind.currentData() or None, q=self.search.text().strip() or None,
                            expiring_days=self.expiring.currentData(), limit=500)["items"]

    def row(self, r: dict) -> list:
        return [r["card_number"], r["label"] or "", r["type_name"], r["plate_number"] or "", r["owner_name"] or "",
                r["room_number"] or "", r["expire_date"] or "", "" if r["remaining_uses"] is None else r["remaining_uses"],
                "Hoạt động" if r["status"] == "active" else "ĐÃ KHOÁ"]

    def fields(self) -> list[dict]:
        return [
            {"key": "card_number", "label": "Mã thẻ", "required": True},
            {"key": "label", "label": "Nhãn in trên thẻ", "nullable": True},
            {"key": "vehicle_type_code", "label": "Loại thẻ", "type": "select",
             "options": [(t["code"], t["display_name"]) for t in self.types]},
            {"key": "plate_number", "label": "Biển số", "nullable": True},
            {"key": "owner_name", "label": "Chủ xe", "nullable": True},
            {"key": "room_number", "label": "Phòng / căn hộ", "nullable": True},
            {"key": "description", "label": "Ghi chú", "nullable": True},
            {"key": "start_date", "label": "Ngày bắt đầu (vé tháng)", "type": "date"},
            {"key": "expire_date", "label": "Ngày hết hạn (vé tháng)", "type": "date"},
            {"key": "remaining_uses", "label": "Số lượt còn (trống = không giới hạn)", "nullable": True},
            {"key": "status", "label": "Trạng thái", "type": "select", "options": [("active", "Hoạt động"), ("locked", "Khoá")]},
        ]

    def to_payload(self, v: dict) -> dict:
        v["remaining_uses"] = _nullable_int(v.get("remaining_uses"))
        return v

    def add(self) -> None:
        if not self.types:
            self.reload()
        super().add()

    def renew(self) -> None:
        rec = self.table.current_record()
        if rec is None or not rec["is_monthly_pass"]:
            return show_error(self, "Hãy chọn một thẻ tháng để gia hạn.")
        vals = ask_form(self, f"Gia hạn thẻ {rec['card_number']}", [
            {"key": "months", "label": "Số tháng", "type": "int", "default": 1, "min": 1, "max": 36},
            {"key": "amount", "label": "Số tiền (0 = tính theo đơn giá loại thẻ)", "type": "int", "default": 0}],
            note=f"Hết hạn hiện tại: {rec['expire_date'] or '—'}")
        if vals is None:
            return
        body = {"months": vals["months"], "amount": vals["amount"] or None}
        r = guarded(self, self.api.post, f"/admin/cards/{rec['id']}/renew", body)
        if r:
            QMessageBox.information(self, "Gia hạn", f"Đã gia hạn tới {r['card']['expire_date']}. Thu {money(r['amount'])}.")
            self.reload()

    def payments(self) -> None:
        rec = self.table.current_record()
        if rec is None:
            return show_error(self, "Hãy chọn một thẻ.")
        rows = guarded(self, self.api.get, f"/admin/cards/{rec['id']}/payments") or []
        text = "\n".join(f"{local_time(r['paid_at'])}   {money(r['amount'])}   kỳ {r['period_start']} → {r['period_end']}" for r in rows)
        QMessageBox.information(self, f"Lịch sử đóng tiền — {rec['card_number']}", text or "Chưa có lần đóng tiền nào.")


# ---- Loại thẻ / loại xe -----------------------------------------------------

class VehicleTypesTab(CrudTab):
    headers = ["Mã", "Tên", "Vé tháng", "Giá tháng", "Sức chứa", "ALPR vào", "ALPR ra", "Barie vào", "Barie ra", "Đang dùng"]
    base_path = "/admin/vehicle-types"
    noun = "loại thẻ"

    def load(self) -> list[dict]:
        return self.api.get(self.base_path)

    def row(self, r: dict) -> list:
        yn = lambda b: "✔" if b else ""  # noqa: E731
        return [r["code"], r["display_name"], yn(r["is_monthly_pass"]), money(r["monthly_fee"]) if r["is_monthly_pass"] else "",
                r["capacity"], yn(r["lpr_in_enabled"]), yn(r["lpr_out_enabled"]), r["barrier_in_id"], r["barrier_out_id"],
                yn(r["is_active"])]

    def fields(self) -> list[dict]:
        return [
            {"key": "code", "label": "Mã (chữ/số, không đổi được sau khi tạo)", "required": True},
            {"key": "display_name", "label": "Tên hiển thị", "required": True},
            {"key": "is_monthly_pass", "label": "Là vé tháng", "type": "bool"},
            {"key": "monthly_fee", "label": "Giá 1 tháng", "type": "int"},
            {"key": "capacity", "label": "Sức chứa (0 = không đếm)", "type": "int"},
            {"key": "expiry_warning_days", "label": "Báo sắp hết hạn trước (ngày)", "type": "int", "default": 5},
            {"key": "lpr_in_enabled", "label": "Đọc biển số lúc vào", "type": "bool", "default": True},
            {"key": "lpr_out_enabled", "label": "Đọc biển số lúc ra", "type": "bool", "default": True},
            {"key": "lpr_confirm_on_match", "label": "Đối chiếu biển số vào/ra", "type": "bool", "default": True},
            {"key": "barrier_in_id", "label": "Mã barie vào", "default": "1"},
            {"key": "barrier_out_id", "label": "Mã barie ra", "default": "1"},
            {"key": "is_active", "label": "Đang sử dụng", "type": "bool", "default": True},
        ]

    def edit(self) -> None:
        rec = self.table.current_record()
        if rec is None:
            return show_error(self, "Hãy chọn loại thẻ cần sửa.")
        flds = [dict(f, readonly=True) if f["key"] == "code" else f for f in self.fields()]
        vals = ask_form(self, "Sửa loại thẻ", flds, rec)
        if vals is not None:
            vals["code"] = rec["code"]
            if guarded(self, self.api.put, f"{self.base_path}/{rec['id']}", self.to_payload(vals)) is not None:
                self.reload()


# ---- Biểu phí ---------------------------------------------------------------

class TariffsTab(CrudTab):
    headers = ["Loại xe", "Tên", "Từ", "Đến", "Cách tính", "Giá đầu", "Giá tiếp", "Block (phút)", "Trần/ngày", "Qua đêm", "Dùng"]
    base_path = "/admin/tariffs"
    noun = "biểu phí"

    def __init__(self, api: ApiClient) -> None:
        super().__init__(api)
        self.types: list[dict] = []
        self.extra_bar.addWidget(button("Tính thử", self.preview))

    def load(self) -> list[dict]:
        self.types = self.api.get("/admin/vehicle-types")
        return self.api.get(self.base_path)

    def row(self, r: dict) -> list:
        return [r["vehicle_type_code"], r["name"], r["start_time"], r["end_time"],
                "Đồng giá" if r["mode"] == "flat" else "Theo block", money(r["first_fee"]), money(r["next_fee"]),
                r["block_minutes"], money(r["max_fee_per_day"]) if r["max_fee_per_day"] else "", money(r["overnight_fee"]),
                "✔" if r["is_active"] else ""]

    def fields(self) -> list[dict]:
        return [
            {"key": "vehicle_type_code", "label": "Loại xe", "type": "select",
             "options": [(t["code"], t["display_name"]) for t in self.types]},
            {"key": "name", "label": "Tên khung giá", "default": "Mặc định"},
            {"key": "start_time", "label": "Từ giờ (HH:MM)", "default": "00:00"},
            {"key": "end_time", "label": "Đến giờ (HH:MM, 24:00 = hết ngày)", "default": "24:00"},
            {"key": "mode", "label": "Cách tính", "type": "select", "options": [("flat", "Đồng giá theo lượt"), ("block", "Theo block thời gian")]},
            {"key": "first_fee", "label": "Giá lượt đầu / block đầu", "type": "int"},
            {"key": "next_fee", "label": "Giá block tiếp theo", "type": "int"},
            {"key": "block_minutes", "label": "Độ dài 1 block (phút)", "type": "int", "default": 60, "min": 1},
            {"key": "max_fee_per_day", "label": "Trần phí mỗi ngày (0 = không trần)", "type": "int"},
            {"key": "overnight_fee", "label": "Phụ thu qua đêm", "type": "int"},
            {"key": "is_active", "label": "Đang áp dụng", "type": "bool", "default": True},
        ]

    def to_payload(self, v: dict) -> dict:
        v["max_fee_per_day"] = v["max_fee_per_day"] or None
        return v

    def add(self) -> None:
        if not self.types:
            self.reload()
        super().add()

    def preview(self) -> None:
        if not self.types:
            self.reload()
        vals = ask_form(self, "Tính thử phí gửi xe", [
            {"key": "vehicle_type", "label": "Loại xe", "type": "select", "options": [(t["code"], t["display_name"]) for t in self.types]},
            {"key": "hour_in", "label": "Giờ vào (0-23)", "type": "int", "default": 9, "max": 23},
            {"key": "hours", "label": "Số giờ gửi", "type": "float", "default": 2}])
        if vals:
            r = guarded(self, self.api.get, "/admin/tariffs/preview", **vals)
            if r:
                QMessageBox.information(self, "Kết quả", f"Phí gửi xe: {money(r['amount'])}")


# ---- Tài khoản --------------------------------------------------------------

class UsersTab(CrudTab):
    headers = ["Tên đăng nhập", "Họ tên", "Vai trò", "Trạng thái"]
    base_path = "/admin/users"
    noun = "tài khoản"

    def load(self) -> list[dict]:
        return self.api.get(self.base_path)

    def row(self, r: dict) -> list:
        return [r["username"], r["full_name"], "Quản lý" if r["role"] == "admin" else "Bảo vệ",
                "Hoạt động" if r["is_active"] else "ĐÃ KHOÁ"]

    def _roles(self) -> list:
        return [("guard", "Bảo vệ"), ("admin", "Quản lý")]

    def add(self) -> None:
        vals = ask_form(self, "Thêm tài khoản", [
            {"key": "username", "label": "Tên đăng nhập", "required": True},
            {"key": "password", "label": "Mật khẩu (≥ 8 ký tự)", "type": "password", "required": True},
            {"key": "full_name", "label": "Họ tên", "required": True},
            {"key": "role", "label": "Vai trò", "type": "select", "options": self._roles()}])
        if vals and guarded(self, self.api.post, self.base_path, vals) is not None:
            self.reload()

    def edit(self) -> None:
        rec = self.table.current_record()
        if rec is None:
            return show_error(self, "Hãy chọn tài khoản cần sửa.")
        vals = ask_form(self, f"Sửa tài khoản {rec['username']}", [
            {"key": "full_name", "label": "Họ tên", "required": True},
            {"key": "role", "label": "Vai trò", "type": "select", "options": self._roles()},
            {"key": "is_active", "label": "Đang hoạt động", "type": "bool"},
            {"key": "password", "label": "Mật khẩu mới (trống = giữ nguyên)", "type": "password"}], rec,
            note="Đổi mật khẩu hoặc khoá tài khoản sẽ buộc người đó đăng nhập lại.")
        if vals:
            if not vals["password"]:
                vals.pop("password")
            if guarded(self, self.api.patch, f"{self.base_path}/{rec['id']}", vals) is not None:
                self.reload()

    def delete(self) -> None:
        show_error(self, "Không xoá tài khoản (để giữ lịch sử ca trực). Hãy bỏ chọn 'Đang hoạt động' để khoá.")


# ---- Ca trực & báo cáo ------------------------------------------------------

class ReportsTab(Page):
    def __init__(self, api: ApiClient) -> None:
        super().__init__(api)
        lay = QVBoxLayout(self)
        gb = QGroupBox("Các ca trực")
        gl = QVBoxLayout(gb)
        self.shifts = Table(["Ca", "Bảo vệ", "Bắt đầu", "Kết thúc", "Trạng thái", "Xe vào", "Xe ra", "Tồn", "Tiền thu"])
        gl.addWidget(self.shifts)
        gl.addWidget(button("Xuất báo cáo PDF của ca đã chọn", self.export_pdf, primary=True))
        lay.addWidget(gb, 3)
        gb2 = QGroupBox("Doanh thu vé tháng")
        g2 = QVBoxLayout(gb2)
        yr = QHBoxLayout()
        yr.addWidget(label("Năm:"))
        self.year = QSpinBox()
        self.year.setRange(2020, 2100)
        self.year.setValue(dt.date.today().year)
        self.year.valueChanged.connect(lambda _: self.reload())
        yr.addWidget(self.year)
        yr.addStretch(1)
        g2.addLayout(yr)
        self.revenue = Table(["Tháng", "Số lần đóng", "Số tiền"])
        self.revenue.setMaximumHeight(220)
        g2.addWidget(self.revenue)
        lay.addWidget(gb2, 2)

    def reload(self) -> None:
        try:
            shifts = self.api.get("/admin/shifts", limit=200)
            rev = self.api.get("/admin/monthly-revenue", year=self.year.value())
        except ApiError as e:
            return show_error(self, e)
        self.shifts.fill([[s["shift_id"], s["guard"], local_time(s["started_at"]), local_time(s["ended_at"]),
                           "Đang mở" if s["status"] == "open" else "Đã kết", s["vehicles_in"], s["vehicles_out"],
                           s["vehicles_remaining"], money(s["total_amount"])] for s in shifts], shifts)
        self.revenue.fill([[f"Tháng {r['month']}", r["count"], money(r["amount"])] for r in rev]
                          + ([["TỔNG", sum(r["count"] for r in rev), money(sum(r["amount"] for r in rev))]] if rev else []))

    def export_pdf(self) -> None:
        rec = self.shifts.current_record()
        if rec is None:
            return show_error(self, "Hãy chọn một ca.")
        resp = guarded(self, self.api.request, "GET", f"/shift/{rec['shift_id']}/report.pdf", raw=True)
        if resp is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Lưu báo cáo", f"bao-cao-ca-{rec['shift_id']}.pdf", "PDF (*.pdf)")
        if path:
            Path(path).write_bytes(resp.content)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
