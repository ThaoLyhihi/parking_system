"""Tab Cài đặt: form tự dựng từ schema của server (/admin/settings) + trang Phần cứng (cổng COM, thử barie/đầu đọc)."""
from __future__ import annotations

import json
from typing import Any

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLineEdit,
                               QListWidget, QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox, QStackedWidget,
                               QVBoxLayout, QWidget)

from desktop.admin_views import Page
from desktop.client import ApiClient, ApiError
from desktop.widgets import Table, button, guarded, label, show_error

# Các mục mà agent (đầu đọc thẻ/barie) tự nạp lại khi bấm "Áp dụng phần cứng" — không cần khởi động lại cả ứng dụng.
AGENT_SECTIONS = {"card_reader", "barrier_hardware", "hardware_agent"}


class SectionForm(QWidget):
    def __init__(self, name: str, spec: dict, on_save) -> None:
        super().__init__()
        self.name, self.spec = name, spec
        self._w: dict[str, QWidget] = {}
        lay = QVBoxLayout(self)
        if spec.get("note"):
            note = label(spec["note"], "muted")
            note.setWordWrap(True)
            lay.addWidget(note)
        form = QFormLayout()
        for f in spec["fields"]:
            w = self._make(f, spec["values"].get(f["key"], f.get("default")))
            self._w[f["key"]] = w
            form.addRow(f["label"] + ("  (cần khởi động lại)" if f.get("restart") else ""), w)
        lay.addLayout(form)
        lay.addWidget(button("Lưu mục này", lambda: on_save(self), primary=True))
        lay.addStretch(1)

    def _make(self, f: dict, val: Any) -> QWidget:
        t = f["type"]
        if t == "bool":
            w = QCheckBox()
            w.setChecked(bool(val))
        elif t == "int":
            w = QSpinBox()
            w.setRange(-2_000_000_000, 2_000_000_000)
            w.setValue(int(val or 0))
        elif t == "float":
            w = QDoubleSpinBox()
            w.setDecimals(3)
            w.setRange(-1e9, 1e9)
            w.setValue(float(val or 0))
        elif t == "select":
            w = QComboBox()
            w.addItems(f["options"])
            w.setCurrentText(str(val))
        elif t == "json":
            w = QPlainTextEdit(json.dumps(val, ensure_ascii=False, indent=2))
            w.setMinimumHeight(120)
        elif t == "list":
            w = QLineEdit(", ".join(val or []))
        else:
            w = QLineEdit("" if val is None else str(val))
            if t == "secret":
                w.setEchoMode(QLineEdit.EchoMode.Password)
                w.setPlaceholderText("(để trống = giữ nguyên)")
        return w

    def values(self) -> dict:
        out: dict[str, Any] = {}
        for f in self.spec["fields"]:
            w, t = self._w[f["key"]], f["type"]
            out[f["key"]] = (w.isChecked() if t == "bool" else w.value() if t in ("int", "float") else
                             w.currentText() if t == "select" else w.toPlainText() if t == "json" else w.text())
        return out


class SettingsTab(Page):
    def __init__(self, api: ApiClient, main) -> None:
        super().__init__(api)
        self.main = main
        root = QHBoxLayout(self)
        self.menu = QListWidget()
        self.menu.setMaximumWidth(210)
        self.stack = QStackedWidget()
        self.menu.currentRowChanged.connect(self.stack.setCurrentIndex)
        root.addWidget(self.menu)
        root.addWidget(self.stack, 1)
        self.hardware = HardwarePage(api, main)
        self._loaded = False

    def reload(self) -> None:
        if self._loaded:
            self.hardware.refresh()
            return
        try:
            settings = self.api.get("/admin/settings")
        except ApiError as e:
            return show_error(self, e)
        self._loaded = True
        self._add("Phần cứng (COM / thẻ / barie)", self.hardware)
        for name, spec in settings.items():
            form = SectionForm(name, spec, self.save)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(form)
            self._add(spec["title"], scroll)
        self.menu.setCurrentRow(0)
        self.hardware.refresh()

    def _add(self, title: str, widget: QWidget) -> None:
        self.menu.addItem(title)
        self.stack.addWidget(widget)

    def save(self, form: SectionForm) -> None:
        try:
            vals = form.values()
            for f in form.spec["fields"]:
                if f["type"] == "json":
                    json.loads(vals[f["key"]])
        except json.JSONDecodeError as e:
            return show_error(self, f"Trường JSON không hợp lệ: {e}")
        r = guarded(self, self.api.put, f"/admin/settings/{form.name}", vals)
        if r is None:
            return
        if not r["restart_required"]:
            return QMessageBox.information(self, "Đã lưu", "Đã lưu và có hiệu lực ngay.") and None
        if form.name in AGENT_SECTIONS:
            if QMessageBox.question(self, "Đã lưu", "Đã lưu. Áp dụng cho đầu đọc thẻ/barie ngay bây giờ?") == QMessageBox.StandardButton.Yes:
                self.main.restart_agent()
                self.hardware.refresh()
        elif QMessageBox.question(self, "Đã lưu", "Đã lưu. Cài đặt này cần khởi động lại ứng dụng mới có hiệu lực. Khởi động lại ngay?") == QMessageBox.StandardButton.Yes:
            self.main.restart_app()


class HardwarePage(QWidget):
    """Liệt kê cổng COM thật của máy + thử đầu đọc thẻ / mở barie ngay trong ứng dụng."""

    def __init__(self, api: ApiClient, main) -> None:
        super().__init__()
        self.api, self.main = api, main
        lay = QVBoxLayout(self)
        gb = QGroupBox("Cổng COM phát hiện trên máy này")
        gl = QVBoxLayout(gb)
        self.ports = Table(["Cổng", "Mô tả thiết bị"])
        self.ports.setMaximumHeight(170)
        gl.addWidget(self.ports)
        hint = label("Điền tên cổng (vd COM7) vào mục 'Đầu đọc thẻ' (loại serial) hoặc vào danh sách barie ở mục 'Barie (COM/TCP)'.", "muted")
        hint.setWordWrap(True)
        gl.addWidget(hint)
        gl.addWidget(button("Quét lại cổng COM", self.refresh))
        lay.addWidget(gb)

        st = QGroupBox("Trạng thái phần cứng và thử thiết bị")
        sl = QVBoxLayout(st)
        self.state = label("", "muted")
        self.state.setWordWrap(True)
        self.last_card = label("Đầu đọc thẻ: chưa có lần quẹt nào — hãy quẹt thử một thẻ.", "muted")
        sl.addWidget(self.state)
        sl.addWidget(self.last_card)
        row = QHBoxLayout()
        self.barrier_id = QLineEdit("1")
        self.barrier_id.setMaximumWidth(80)
        row.addWidget(label("Thử mở barie số:"))
        row.addWidget(self.barrier_id)
        row.addWidget(button("Mở barie thử", self.test_open, primary=True))
        row.addStretch(1)
        row.addWidget(button("Áp dụng cấu hình phần cứng", self.apply))
        sl.addLayout(row)
        lay.addWidget(st)
        lay.addStretch(1)
        main.card_seen.connect(self._card_seen)

    def refresh(self) -> None:
        try:
            from serial.tools import list_ports
            ports = [[p.device, p.description] for p in list_ports.comports()]
        except Exception:
            ports = []
        self.ports.fill(ports or [["—", "Không phát hiện cổng COM nào"]])
        self.state.setText(self.main.agent_status())

    def _card_seen(self, number: str) -> None:
        self.last_card.setText(f"Đầu đọc thẻ: lần quẹt gần nhất — mã thẻ  {number}")

    def test_open(self) -> None:
        try:
            self.main.agent_open_barrier(self.barrier_id.text().strip() or "1")
            QMessageBox.information(self, "Barie", "Đã gửi lệnh mở. Barie sẽ tự đóng khi vùng an toàn trống "
                                    "(hoặc không đóng nếu chưa cấu hình camera barie).")
        except Exception as e:
            show_error(self, e)

    def apply(self) -> None:
        self.main.restart_agent()
        self.refresh()
