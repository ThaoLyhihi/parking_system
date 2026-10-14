"""Điểm vào ứng dụng desktop all-in-one.

Chạy từ mã nguồn:   python -m desktop.main      (từ thư mục parking_system)
Đóng gói .exe:      xem parking_desktop.spec / scripts/build_desktop_exe.bat

Một tiến trình duy nhất chứa: server FastAPI (127.0.0.1) + CSDL SQLite + hardware agent (đầu đọc thẻ, barie)
+ giao diện cửa sổ. Không cần Docker, PostgreSQL hay Internet."""
from __future__ import annotations

import logging
import logging.handlers
import subprocess
import sys

from desktop.bootstrap import EmbeddedServer, prepare_environment

DATA_DIR = prepare_environment()  # PHẢI chạy trước khi import `app.*`

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog, QFormLayout, QLabel, QLineEdit, QMessageBox,  # noqa: E402
                               QPushButton, QVBoxLayout)

from desktop import bootstrap  # noqa: E402
from desktop.client import ApiClient, ApiError  # noqa: E402
from desktop.main_window import MainWindow  # noqa: E402
from desktop.widgets import STYLE, button, label, styled  # noqa: E402

logger = logging.getLogger("desktop")


def setup_logging() -> None:
    h = logging.handlers.RotatingFileHandler(DATA_DIR / "parking.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)


class LoginDialog(QDialog):
    def __init__(self, api: ApiClient, first_run: bool = False) -> None:
        super().__init__()
        self.api, self.first_run = api, first_run
        self.setWindowTitle("Thiết lập tài khoản quản lý" if first_run else "Đăng nhập")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        title = label("Hệ thống giữ xe tự động", "big")
        lay.addWidget(title)
        lay.addWidget(label("Lần chạy đầu tiên: hãy tạo tài khoản quản lý." if first_run else "Đăng nhập để bắt đầu ca trực.", "muted"))
        form = QFormLayout()
        self.user = QLineEdit("admin" if first_run else "")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Tên đăng nhập", self.user)
        form.addRow("Mật khẩu" + (" (≥ 8 ký tự)" if first_run else ""), self.password)
        self.name = QLineEdit("Quản lý")
        if first_run:
            form.addRow("Họ tên", self.name)
        lay.addLayout(form)
        self.error = label("", "bad")
        lay.addWidget(self.error)
        ok = button("Tạo tài khoản và đăng nhập" if first_run else "Đăng nhập", self.submit, primary=True)
        ok.setDefault(True)
        lay.addWidget(ok)
        self.password.returnPressed.connect(self.submit)

    def submit(self) -> None:
        u, p = self.user.text().strip(), self.password.text()
        try:
            if self.first_run:
                bootstrap.create_first_admin(u, p, self.name.text().strip())
            self.api.login(u, p)
        except (ApiError, ValueError) as e:
            self.error.setText(str(e))
            return
        self.accept()


class StartupDialog(QDialog):
    """Hiện trong lúc nạp model AI + khởi động server nội bộ (vài giây)."""

    def __init__(self, server: EmbeddedServer) -> None:
        super().__init__()
        self.server = server
        self.setWindowTitle("Đang khởi động")
        self.setMinimumWidth(360)
        lay = QVBoxLayout(self)
        lay.addWidget(label("Đang khởi động hệ thống...", "big"))
        lay.addWidget(label("Nạp mô hình nhận diện biển số và cơ sở dữ liệu.", "muted"))
        self.timer = QTimer(self, interval=300)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def _poll(self) -> None:
        if self.server.error:
            self.timer.stop()
            QMessageBox.critical(self, "Lỗi khởi động", f"Không khởi động được máy chủ nội bộ:\n{self.server.error}")
            self.reject()
        elif self.server.wait_ready():
            self.timer.stop()
            self.accept()


class Controller:
    def __init__(self, app: QApplication, server: EmbeddedServer) -> None:
        self.app, self.server = app, server
        self.api = ApiClient(server.base_url)
        self.window: MainWindow | None = None
        self.agent = None
        self.agent_error: str | None = None
        self._closing = False

    # ---- agent -----------------------------------------------------------------
    def start_agent(self) -> None:
        from app.agent.runner import HardwareAgent
        import os
        self.agent_error = None
        self.agent = HardwareAgent(self.server.base_url, os.environ["AGENT_API_KEY"])
        self.agent.on_card_seen = lambda n: self.window and self.window.card_seen.emit(n)
        try:
            self.agent.start()
        except Exception as e:  # sai cổng COM, thiếu quyền... -> báo trên UI, ứng dụng vẫn dùng được
            logger.exception("Không khởi động được agent phần cứng")
            self.agent_error = str(e)
            self.agent.stop()

    def restart_agent(self) -> None:
        if self.agent:
            self.agent.stop()
        self.start_agent()

    def agent_status(self) -> str:
        if self.agent_error:
            return f"Phần cứng: LỖI — {self.agent_error}"
        if self.agent and self.agent.running:
            return (f"Phần cứng: đang chạy (đầu đọc: {self.agent._reader_cfg.get('type')}, "
                    f"barie: {self.agent._barrier_cfg.get('type')})")
        return "Phần cứng: chưa chạy"

    def agent_open_barrier(self, barrier_id: str) -> None:
        if not (self.agent and self.agent.running):
            raise RuntimeError("Agent phần cứng chưa chạy — kiểm tra cấu hình ở mục Phần cứng.")
        self.agent.open_barrier(barrier_id)

    # ---- vòng đời --------------------------------------------------------------
    def show_login(self) -> None:
        self.api = ApiClient(self.server.base_url)
        first = bootstrap.needs_first_admin()
        dlg = LoginDialog(self.api, first_run=first)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return self.quit()
        if self.agent is None:
            self.start_agent()
        self.window = MainWindow(self.api, self)
        self.window.show()

    def logout(self) -> None:
        if self.window:
            w, self.window = self.window, None
            w.shutdown()
            self.api.logout()
            w.hide()
            w.deleteLater()
        QTimer.singleShot(0, self.show_login)

    def _stop_everything(self) -> None:
        if self.window:
            self.window.shutdown()
        if self.agent:
            self.agent.stop()
        self.server.stop()

    def quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._stop_everything()
        self.app.quit()

    def restart_app(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._stop_everything()
        args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
        subprocess.Popen([sys.executable, *args])
        self.app.quit()


def selftest() -> int:
    """`ParkingAI.exe --selftest`: kiểm tra bản đã đóng gói nạp được server, model biển số, font PDF và model khuôn mặt
    (không mở giao diện). In SELFTEST_OK và trả 0 nếu tất cả đúng."""
    import numpy as np
    import app.api.main  # noqa: F401  (nạp model ONNX biển số + khởi tạo FastAPI)
    import app.core.reports  # noqa: F401  (đăng ký font tiếng Việt cho PDF)
    from app.face import verify

    if verify._bundled_root("buffalo_s") is None:
        print("SELFTEST_FAIL: thiếu model khuôn mặt đóng gói sẵn")
        return 1
    verify.extract_embedding(np.zeros((320, 320, 3), np.uint8))  # nạp model; ảnh trống -> None
    print("SELFTEST_OK")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    setup_logging()
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    app.setApplicationName("Hệ thống giữ xe tự động")
    app.setQuitOnLastWindowClosed(False)

    server = EmbeddedServer()
    server.start()
    if StartupDialog(server).exec() != QDialog.DialogCode.Accepted:
        return 1
    ctl = Controller(app, server)
    QTimer.singleShot(0, ctl.show_login)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
