"""Màn hình bảo vệ: camera trực tiếp, quét thẻ/nhập mã thẻ, khách không thẻ, sự kiện vào/ra realtime, kết ca."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests
from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLineEdit, QListWidget,
                               QVBoxLayout, QWidget)

from desktop.client import ApiClient, ApiError
from desktop.widgets import Table, button, confirm, guarded, label, local_time, money, show_error, styled

CAMERAS = [("gate_in", "Cổng vào"), ("gate_out", "Cổng ra"), ("barrier", "Barie")]


class CameraPoller(QThread):
    """Kéo khung hình JPEG từ server trong thread riêng để giao diện không bị khựng."""
    frame = Signal(str, bytes)

    def __init__(self, base_url: str, token: str, parent=None) -> None:
        super().__init__(parent)
        self._base, self._token = base_url, token
        self._running = True
        # zoom tạm do bảo vệ chọn trên từng ô camera; None = dùng zoom mặc định trong Cài đặt
        self.zooms: dict[str, float | None] = {}
        self.pans: dict[str, tuple[float, float]] = {}   # tâm vùng zoom (0-1), mặc định giữa khung
        self.eff_zoom: dict[str, float] = {}             # zoom thực tế server đang áp (kể cả mặc định)

    def run(self) -> None:
        s = requests.Session()
        while self._running:
            for name, _ in CAMERAS:
                if not self._running:
                    return
                try:
                    z = self.zooms.get(name)
                    cx, cy = self.pans.get(name, (0.5, 0.5))
                    params = {"cx": cx, "cy": cy}
                    if z:
                        params["zoom"] = z
                    r = s.get(f"{self._base}/camera/{name}/snapshot.jpg", timeout=2,
                              params=params,
                              headers={"Authorization": f"Bearer {self._token}"})
                    if r.status_code == 200:
                        self.eff_zoom[name] = float(r.headers.get("X-Zoom", 1))
                    self.frame.emit(name, r.content if r.status_code == 200 else b"")
                except requests.RequestException:
                    self.frame.emit(name, b"")
            self.msleep(250)

    def stop(self) -> None:
        self._running = False
        self.wait(3000)


class EventListener(QThread):
    """Nghe /ws/events (biển số vào/ra realtime), tự kết nối lại khi rớt."""
    event = Signal(dict)

    def __init__(self, base_url: str, token: str, parent=None) -> None:
        super().__init__(parent)
        self._url = base_url.replace("http", "ws", 1) + f"/ws/events?token={token}"
        self._running = True
        self._ws = None

    def run(self) -> None:
        from websockets.sync.client import connect
        while self._running:
            try:
                with connect(self._url, open_timeout=3) as ws:
                    self._ws = ws
                    for msg in ws:
                        self.event.emit(json.loads(msg))
            except Exception:
                pass
            finally:
                self._ws = None
            for _ in range(10):
                if not self._running:
                    return
                self.msleep(100)

    def stop(self) -> None:
        self._running = False
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        self.wait(3000)


class CameraBox(QGroupBox):
    pan_changed = Signal(float, float)   # tâm vùng zoom mới (0-1)
    pan_reset = Signal()

    def __init__(self, title: str) -> None:
        super().__init__(title)
        self.center = (0.5, 0.5)
        self.eff_zoom = 1.0     # do GuardView cập nhật từ header X-Zoom
        self._drag = None
        self.view = label("Chưa có tín hiệu")
        styled(self.view, role="cam")
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setMinimumSize(320, 180)
        self.view.setToolTip("Khi đã zoom: kéo chuột để dời vùng xem, nháy đúp để về giữa khung")
        self.view.mousePressEvent = self._press
        self.view.mouseMoveEvent = self._move
        self.view.mouseDoubleClickEvent = lambda e: self.pan_reset.emit()
        self.view.setSizePolicy(self.view.sizePolicy().horizontalPolicy(), self.view.sizePolicy().verticalPolicy())
        lay = QVBoxLayout(self)
        lay.addWidget(self.view)
        zr = QHBoxLayout()
        zr.addStretch(1)
        zr.addWidget(label("Zoom:", "muted"))
        self.zoom_box = QComboBox()
        self.zoom_box.addItem("Mặc định", None)
        for z in (1, 2, 4, 8):
            self.zoom_box.addItem(f"{z}x", float(z))
        zr.addWidget(self.zoom_box)
        lay.addLayout(zr)
        self._pix: QPixmap | None = None

    def _press(self, e) -> None:
        self._drag = e.position()

    def _move(self, e) -> None:
        # Kéo ảnh sang phải = xem phần bên trái -> tâm đi ngược chiều kéo. Đổi pixel trên ô hiển thị
        # sang tỉ lệ khung gốc: vùng đang xem chiếm 1/zoom khung nên nhân thêm 1/zoom.
        if self._drag is None or self.eff_zoom <= 1.0 or not self._pix or not (e.buttons() & Qt.MouseButton.LeftButton):
            return
        shown = self._pix.scaled(self.view.size(), Qt.AspectRatioMode.KeepAspectRatio)
        if shown.width() <= 0 or shown.height() <= 0:
            return
        dx, dy = e.position().x() - self._drag.x(), e.position().y() - self._drag.y()
        self._drag = e.position()
        cx = min(max(self.center[0] - dx / shown.width() / self.eff_zoom, 0.0), 1.0)
        cy = min(max(self.center[1] - dy / shown.height() / self.eff_zoom, 0.0), 1.0)
        self.pan_changed.emit(cx, cy)

    def set_jpeg(self, data: bytes) -> None:
        if not data:
            self._pix = None
            self.view.setPixmap(QPixmap())
            self.view.setText("Chưa có tín hiệu")
            return
        img = QImage.fromData(data)
        self._pix = QPixmap.fromImage(img)
        self._rescale()

    def _rescale(self) -> None:
        if self._pix:
            self.view.setPixmap(self._pix.scaled(self.view.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._rescale()


class GuardView(QWidget):
    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.setObjectName("page")
        self.api = api
        self._build()
        self.poller = CameraPoller(api.base_url, api.token or "", self)
        self.poller.frame.connect(self._on_frame)
        self.events = EventListener(api.base_url, api.token or "", self)
        self.events.event.connect(self._on_event)
        self.poller.start()
        self.events.start()
        self.timer = QTimer(self, interval=3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self._load_types()
        self.refresh()

    # ---- giao diện -----------------------------------------------------------
    def _build(self) -> None:
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.cams: dict[str, CameraBox] = {}
        grid = QGridLayout()
        for i, (name, title) in enumerate(CAMERAS):
            self.cams[name] = CameraBox(title)
            self.cams[name].zoom_box.currentIndexChanged.connect(
                lambda _i, n=name: self._set_zoom(n))
            self.cams[name].pan_changed.connect(lambda x, y, n=name: self._set_pan(n, x, y))
            self.cams[name].pan_reset.connect(lambda n=name: self._set_pan(n, 0.5, 0.5))
            grid.addWidget(self.cams[name], 0 if i < 2 else 1, i % 2)
        self.stats_box = QGroupBox("Chỗ trống trong bãi")
        self.stats_lay = QHBoxLayout(self.stats_box)
        grid.addWidget(self.stats_box, 1, 1)
        left.addLayout(grid)
        self.feed = QListWidget()
        gb = QGroupBox("Xe vào / ra (thời gian thực)")
        QVBoxLayout(gb).addWidget(self.feed)
        left.addWidget(gb, 1)
        root.addLayout(left, 3)

        right = QVBoxLayout()
        scan = QGroupBox("Quét thẻ")
        sl = QVBoxLayout(scan)
        row = QHBoxLayout()
        self.card_input = QLineEdit()
        self.card_input.setPlaceholderText("Quét thẻ hoặc nhập mã thẻ rồi nhấn Enter")
        self.card_input.returnPressed.connect(self.scan_card)
        row.addWidget(self.card_input, 1)
        row.addWidget(button("Quét", self.scan_card, primary=True))
        sl.addLayout(row)
        self.result_title = label("Chưa có lượt quét", "big")
        self.result_detail = label("", "muted")
        self.result_detail.setWordWrap(True)
        sl.addWidget(self.result_title)
        sl.addWidget(self.result_detail)
        right.addWidget(scan)

        visitor = QGroupBox("Khách không có thẻ")
        vl = QVBoxLayout(visitor)
        vr = QHBoxLayout()
        self.vtype = QComboBox()
        vr.addWidget(self.vtype, 1)
        vr.addWidget(button("Cho khách vào", self.visitor_in, primary=True))
        vl.addLayout(vr)
        self.visitors = Table(["Mã", "Loại", "Biển số", "Giờ vào"])
        self.visitors.setMaximumHeight(160)
        vl.addWidget(self.visitors)
        vl.addWidget(button("Cho khách đã chọn ra", self.visitor_out))
        right.addWidget(visitor)

        shift = QGroupBox("Ca trực của tôi")
        shl = QVBoxLayout(shift)
        self.shift_label = label("", "muted")
        shl.addWidget(self.shift_label)
        shl.addWidget(button("Kết ca và xuất báo cáo PDF", self.close_shift, danger=True))
        right.addWidget(shift)
        right.addStretch(1)
        root.addLayout(right, 2)

    def _load_types(self) -> None:
        try:
            for t in self.api.get("/vehicle-types"):
                self.vtype.addItem(t["display_name"], t["code"])
        except ApiError:
            pass

    # ---- cập nhật ------------------------------------------------------------
    def _set_zoom(self, name: str) -> None:
        self.poller.zooms[name] = self.cams[name].zoom_box.currentData()
        self._set_pan(name, 0.5, 0.5)   # đổi mức zoom thì về giữa khung

    def _set_pan(self, name: str, cx: float, cy: float) -> None:
        self.cams[name].center = (cx, cy)
        self.poller.pans[name] = (cx, cy)

    def _on_frame(self, name: str, data: bytes) -> None:
        self.cams[name].eff_zoom = self.poller.eff_zoom.get(name, 1.0)
        self.cams[name].set_jpeg(data)

    def _on_event(self, ev: dict) -> None:
        kind = "VÀO" if ev.get("type") == "entry" else "RA"
        extra = f"  —  {money(ev['amount'])}" if ev.get("amount") is not None and kind == "RA" else ""
        who = f"thẻ {ev['card_number']}" if ev.get("card_number") else "khách không thẻ"
        self.feed.insertItem(0, f"{local_time(ev.get('at'))}   {kind}   {ev.get('plate') or '(không đọc được biển)'}"
                                f"   {ev.get('vehicle_type', '')}   {who}{extra}")
        while self.feed.count() > 200:
            self.feed.takeItem(self.feed.count() - 1)
        self.refresh()

    def refresh(self) -> None:
        try:
            ov = self.api.get("/status/overview")
            visitors = self.api.get("/visitor/open")
        except ApiError:
            return
        try:
            sh = self.api.get("/shift/current")
        except ApiError:  # quản lý chưa có ca (ca chỉ mở khi bảo vệ đăng nhập hoặc khi quét thẻ)
            sh = None
        while self.stats_lay.count():
            w = self.stats_lay.takeAt(0).widget()
            if w:
                w.setParent(None)  # gỡ ngay (deleteLater còn vẽ chồng lên bản mới)
                w.deleteLater()
        occ = ov["occupancy"] or {}
        for code, o in occ.items():
            col = QVBoxLayout()
            box = QWidget()
            box.setLayout(col)
            col.addWidget(label(str(o["vacant"]), "big"))
            col.addWidget(label(f"{code}\n{o['current']}/{o['capacity']} xe", "muted"))
            self.stats_lay.addWidget(box)
        if not occ:
            self.stats_lay.addWidget(label("Chưa cấu hình sức chứa", "muted"))
        self.shift_label.setText("Chưa có ca đang mở (ca tự mở khi quét thẻ lần đầu)." if sh is None else
            f"Ca #{sh['shift_id']} từ {local_time(sh['started_at'])}\n"
            f"Xe vào: {sh['vehicles_in']}   Xe ra: {sh['vehicles_out']}   Còn tồn: {sh['vehicles_remaining']}\n"
            f"Tiền thu: {money(sh['total_amount'])}")
        keep = (self.visitors.current_record() or {}).get("session_id")
        self.visitors.fill([[v["session_id"], v["vehicle_type"], v["plate_in"] or "—", local_time(v["time_in"])]
                            for v in visitors], visitors)
        for r, v in enumerate(visitors):
            if v["session_id"] == keep:
                self.visitors.selectRow(r)

    # ---- thao tác ------------------------------------------------------------
    def _show_result(self, title: str, detail: str, role: str) -> None:
        self.result_title.setText(title)
        styled(self.result_title, role="big")
        self.result_detail.setText(detail)
        styled(self.result_detail, role=role)

    def scan_card(self) -> None:
        number = self.card_input.text().strip()
        if not number:
            return
        self.card_input.clear()
        try:
            r = self.api.post("/card/scan", {"card_number": number})
        except ApiError as e:
            self._show_result(f"Thẻ {number}: TỪ CHỐI", str(e), "bad")
            return
        head = "XE VÀO" if r["action"] == "entry" else "XE RA"
        detail = f"Thẻ {number}  •  Biển số: {r['plate_text'] or '(không đọc được)'}  •  Barie {r['barrier_id']} đang mở"
        if r.get("amount") is not None:
            detail += f"\nPhí gửi xe: {money(r['amount'])}"
        if r.get("message"):
            detail += f"\n⚠ {r['message']}"
        self._show_result(head, detail, "warn" if r.get("message") else "ok")
        self.refresh()

    def visitor_in(self) -> None:
        code = self.vtype.currentData()
        if not code:
            return
        r = guarded(self, self.api.post, "/visitor/entry", {"vehicle_type": code})
        if r:
            detail = f"Mã khách #{r['session_id']}  •  Biển số: {r['plate_text'] or '(không đọc được)'}  •  Barie {r['barrier_id']} đang mở"
            if r.get("message"):
                detail += f"\n⚠ {r['message']}"
            self._show_result("KHÁCH VÀO", detail, "warn" if r.get("message") else "ok")
            self.refresh()

    def visitor_out(self) -> None:
        rec = self.visitors.current_record()
        if not rec:
            show_error(self, "Hãy chọn khách trong danh sách.")
            return
        r = guarded(self, self.api.post, f"/visitor/{rec['session_id']}/exit")
        if r:
            self._show_result("KHÁCH RA", f"Biển số: {r['plate_text'] or '—'}  •  Thu: {money(r['amount'])}"
                              + (f"\n⚠ {r['message']}" if r.get("message") else ""), "ok")
            self.refresh()

    def close_shift(self) -> None:
        if not confirm(self, "Kết ca hiện tại? Sau khi kết ca bạn cần đăng nhập lại để mở ca mới."):
            return
        stats = guarded(self, self.api.post, "/shift/close")
        if not stats:
            return
        pdf = guarded(self, self.api.request, "GET", f"/shift/{stats['shift_id']}/report.pdf", raw=True)
        msg = f"Đã kết ca. Xe vào {stats['vehicles_in']}, ra {stats['vehicles_out']}, thu {money(stats['total_amount'])}."
        if pdf is not None:
            path, _ = QFileDialog.getSaveFileName(self, "Lưu báo cáo ca", f"bao-cao-ca-{stats['shift_id']}.pdf", "PDF (*.pdf)")
            if path:
                Path(path).write_bytes(pdf.content)
                msg += f"\nĐã lưu báo cáo: {path}"
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Kết ca", msg)
        self.window().logout()

    def shutdown(self) -> None:
        self.timer.stop()
        self.poller.stop()
        self.events.stop()
