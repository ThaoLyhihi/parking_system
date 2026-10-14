"""Thành phần giao diện dùng chung: theme, hộp thoại form tổng quát, bảng, định dạng tiền/giờ."""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QSpinBox,
                               QTableWidget, QTableWidgetItem, QWidget)

from desktop.client import ApiError

TZ_HOURS = 7

STYLE = """
* { font-family: "Segoe UI", "Noto Sans", sans-serif; font-size: 13px; }
QMainWindow, QDialog, QWidget#page { background: #f4f6f9; }
QTabWidget::pane { border: 1px solid #d5dbe3; background: #f4f6f9; top: -1px; }
QTabBar::tab { padding: 9px 18px; background: #e6eaf0; border: 1px solid #d5dbe3; border-bottom: none; margin-right: 2px; }
QTabBar::tab:selected { background: #ffffff; font-weight: 600; color: #0b5cad; }
QGroupBox { background: #ffffff; border: 1px solid #d5dbe3; border-radius: 8px; margin-top: 14px; padding: 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #33415c; }
QPushButton { background: #ffffff; border: 1px solid #b8c1cf; border-radius: 6px; padding: 6px 14px; }
QPushButton:hover { background: #eef3fa; }
QPushButton:disabled { color: #9aa5b5; background: #eef0f3; }
QPushButton[primary="true"] { background: #0b5cad; color: white; border: 1px solid #094a8c; font-weight: 600; }
QPushButton[primary="true"]:hover { background: #0e6bc9; }
QPushButton[danger="true"] { background: #c0392b; color: white; border: 1px solid #962d22; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit { background: white; border: 1px solid #b8c1cf; border-radius: 5px; padding: 5px; }
QTableWidget { background: white; alternate-background-color: #f7f9fc; gridline-color: #e3e8ef; border: 1px solid #d5dbe3; }
QHeaderView::section { background: #e6eaf0; padding: 6px; border: none; border-right: 1px solid #d5dbe3; font-weight: 600; }
QLabel[role="cam"] { background: #1b2430; color: #8b97a8; border-radius: 6px; }
QLabel[role="big"] { font-size: 26px; font-weight: 700; }
QLabel[role="muted"] { color: #667085; }
QLabel[role="ok"] { color: #12805c; font-weight: 600; }
QLabel[role="warn"] { color: #b45309; font-weight: 600; }
QLabel[role="bad"] { color: #c0392b; font-weight: 600; }
"""


def local_time(iso: str | None) -> str:
    if not iso:
        return "—"
    t = dt.datetime.fromisoformat(iso.replace("Z", "")) + dt.timedelta(hours=TZ_HOURS)
    return t.strftime("%d/%m/%Y %H:%M")


def money(v: int | float | None) -> str:
    return "—" if v is None else f"{int(v):,}".replace(",", ".") + " đ"


def styled(widget: QWidget, **props: Any) -> QWidget:
    for k, v in props.items():
        widget.setProperty(k, v)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget


def label(text: str = "", role: str | None = None) -> QLabel:
    lb = QLabel(text)
    if role:
        styled(lb, role=role)
    return lb


def button(text: str, on_click: Callable | None = None, primary: bool = False, danger: bool = False) -> Any:
    from PySide6.QtWidgets import QPushButton
    b = QPushButton(text)
    if primary:
        styled(b, primary=True)
    if danger:
        styled(b, danger=True)
    if on_click:
        b.clicked.connect(lambda _=False: on_click())
    return b


def show_error(parent: QWidget | None, err: Exception | str) -> None:
    QMessageBox.warning(parent, "Có lỗi", str(err))


def confirm(parent: QWidget | None, text: str) -> bool:
    return QMessageBox.question(parent, "Xác nhận", text) == QMessageBox.StandardButton.Yes


def guarded(parent: QWidget | None, fn: Callable, *a: Any) -> Any:
    """Chạy fn, hiện hộp thoại nếu server trả lỗi (thay vì crash giao diện)."""
    try:
        return fn(*a)
    except ApiError as e:
        show_error(parent, e)
        return None


class Table(QTableWidget):
    def __init__(self, headers: list[str]) -> None:
        super().__init__(0, len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.records: list[Any] = []

    def fill(self, rows: list[list[Any]], records: list[Any] | None = None) -> None:
        self.setRowCount(len(rows))
        self.records = records if records is not None else rows
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QTableWidgetItem("" if val is None else str(val))
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.setItem(r, c, item)
        self.resizeColumnsToContents()
        for c in range(self.columnCount() - 1):
            self.setColumnWidth(c, min(self.columnWidth(c) + 16, 320))

    def current_record(self) -> Any | None:
        r = self.currentRow()
        return self.records[r] if 0 <= r < len(self.records) else None


# ---- Form tổng quát ---------------------------------------------------------
# field = {"key","label","type": text|int|float|bool|select|password|multiline|date,"options":[(value,label)],
#          "default","required","readonly"}

class FormDialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, fields: list[dict], values: dict | None = None,
                 note: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self._fields = fields
        self._widgets: dict[str, QWidget] = {}
        form = QFormLayout(self)
        if note:
            lb = label(note, "muted")
            lb.setWordWrap(True)
            form.addRow(lb)
        values = values or {}
        for f in fields:
            w = self._make(f, values.get(f["key"], f.get("default")))
            self._widgets[f["key"]] = w
            form.addRow(f["label"] + (" *" if f.get("required") else ""), w)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Lưu")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Huỷ")
        bb.accepted.connect(self._try_accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _make(self, f: dict, val: Any) -> QWidget:
        t = f.get("type", "text")
        if t == "int":
            w = QSpinBox()
            w.setRange(f.get("min", 0), f.get("max", 2_000_000_000))
            w.setGroupSeparatorShown(True)
            w.setValue(int(val or 0))
        elif t == "float":
            w = QDoubleSpinBox()
            w.setDecimals(3)
            w.setRange(0, 1e9)
            w.setValue(float(val or 0))
        elif t == "bool":
            w = QCheckBox()
            w.setChecked(bool(val))
        elif t == "select":
            w = QComboBox()
            for v, lab in f["options"]:
                w.addItem(lab, v)
            i = w.findData(val)
            w.setCurrentIndex(max(i, 0))
        elif t == "multiline":
            w = QPlainTextEdit(str(val if val is not None else ""))
            w.setMinimumHeight(110)
        else:
            w = QLineEdit("" if val is None else str(val))
            if t == "password":
                w.setEchoMode(QLineEdit.EchoMode.Password)
            if t == "date":
                w.setPlaceholderText("YYYY-MM-DD")
        if f.get("readonly"):
            w.setEnabled(False)
        return w

    def value(self, f: dict) -> Any:
        w, t = self._widgets[f["key"]], f.get("type", "text")
        if t in ("int", "float"):
            return w.value()
        if t == "bool":
            return w.isChecked()
        if t == "select":
            return w.currentData()
        if t == "multiline":
            return w.toPlainText()
        text = w.text().strip()
        if t == "date" or f.get("nullable"):
            return text or None
        return text

    def _try_accept(self) -> None:
        for f in self._fields:
            if f.get("required") and self.value(f) in ("", None):
                show_error(self, f"Vui lòng nhập: {f['label']}")
                return
        self.accept()

    def result_values(self) -> dict:
        return {f["key"]: self.value(f) for f in self._fields if not f.get("readonly")}


def ask_form(parent: QWidget | None, title: str, fields: list[dict], values: dict | None = None,
             note: str | None = None) -> dict | None:
    dlg = FormDialog(parent, title, fields, values, note)
    return dlg.result_values() if dlg.exec() == QDialog.DialogCode.Accepted else None
