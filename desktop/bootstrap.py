"""Chuẩn bị môi trường + chạy server FastAPI nhúng (uvicorn trong thread) cho ứng dụng desktop.

PHẢI gọi prepare_environment() TRƯỚC KHI import bất kỳ module nào trong `app` (app.db.base đọc
DATABASE_URL lúc import). Mọi dữ liệu (CSDL, khoá agent) nằm trong thư mục dữ liệu người dùng
để cập nhật/cài lại ứng dụng không mất dữ liệu."""
from __future__ import annotations

import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import requests

APP_NAME = "ParkingAI"


def resource_dir() -> Path:
    """Thư mục chứa models/, config/, assets/ — thư mục bundle khi đóng gói, gốc project khi chạy từ mã nguồn."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    override = os.environ.get("PARKING_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
    else:
        base = Path.home() / ".local" / "share" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def prepare_environment() -> Path:
    """Đặt biến môi trường + thư mục làm việc. Trả về thư mục dữ liệu."""
    data = data_dir()
    os.chdir(resource_dir())  # config alpr.model_path là đường dẫn tương đối "models/..."
    os.environ.setdefault("DATABASE_URL", "sqlite:///" + (data / "parking.db").as_posix())
    key_file = data / "agent.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    os.environ.setdefault("AGENT_API_KEY", key_file.read_text(encoding="utf-8").strip())
    return data


def seed_first_run_settings() -> None:
    """Lần chạy đầu: bỏ các camera RTSP mẫu trong config.example.yaml (IP giả, gây báo lỗi mất kết nối liên tục)
    và đặt phần cứng về chế độ an toàn. Người dùng chỉnh lại trong Cài đặt; cờ first_run_done chặn ghi đè về sau."""
    marker = data_dir() / "first_run_done"
    if marker.exists():
        return
    from app import settings as app_settings
    from app.db.base import get_session, init_db

    init_db()
    db = get_session()
    try:
        app_settings.save_section(db, "cameras", {k: "" for k in ("gate_in_source", "gate_out_source", "overview_source", "barrier_source")})
        app_settings.save_section(db, "card_reader", {"type": "windows_keyboard" if sys.platform == "win32" else "simulated"})
        app_settings.save_section(db, "barrier_hardware", {"type": "logging"})
    finally:
        db.close()
    marker.write_text("1", encoding="utf-8")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class EmbeddedServer:
    """Chạy `app.api.main:app` trong thread nền, chỉ nghe 127.0.0.1 (không lộ ra mạng)."""

    def __init__(self) -> None:
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.error: Exception | None = None
        self.ready = threading.Event()
        self._server = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            seed_first_run_settings()
            import uvicorn
            from app.api.main import app  # import nặng (nạp model ONNX) nên làm trong thread nền

            cfg = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_config=None,
                                 loop="asyncio", http="h11", ws="websockets")
            self._server = uvicorn.Server(cfg)
            self._server.run()
        except Exception as e:  # lỗi hiển thị cho người dùng thay vì chết im lặng
            self.error = e
            self.ready.set()

    def wait_ready(self, timeout: float = 0.0) -> bool:
        """True khi /health trả lời. Gọi lặp lại (timeout ngắn) từ vòng lặp UI."""
        if self.error:
            return False
        try:
            if requests.get(self.base_url + "/health", timeout=0.5).ok:
                self.ready.set()
                return True
        except requests.RequestException:
            pass
        if timeout:
            time.sleep(timeout)
        return False

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
            self._thread.join(timeout=5)


def needs_first_admin() -> bool:
    from app.db.base import get_session
    from app.db.models import User

    db = get_session()
    try:
        return db.query(User).count() == 0
    finally:
        db.close()


def create_first_admin(username: str, password: str, full_name: str) -> None:
    from app import auth
    from app.db.base import get_session

    db = get_session()
    try:
        auth.create_user(db, username, password, full_name or "Quản lý", auth.ROLE_ADMIN)
    finally:
        db.close()
