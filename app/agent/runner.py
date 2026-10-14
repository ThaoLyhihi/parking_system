"""Logic hardware agent: đọc đầu đọc thẻ + gửi lệnh barie qua COM, hỏi server để lấy quyết định.

Tách khỏi scripts/windows_hardware_agent.py thành class có start()/stop() để ứng dụng desktop
(desktop/) chạy được ngay trong tiến trình, không cần cửa sổ dòng lệnh riêng. Hành vi giữ nguyên
như script gốc: server không gọi được -> KHÔNG mở barie; cấu hình ưu tiên lấy từ server."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

from app.barrier.factory import build_barrier_hardware
from app.card_reader.factory import build_card_reader

logger = logging.getLogger("agent")


class HardwareAgent:
    def __init__(self, api_base_url: str, api_key: str, fallback_cfg: dict[str, Any] | None = None):
        self.api_base_url = api_base_url.rstrip("/")
        self.headers = {"X-Agent-Key": api_key}
        fb = fallback_cfg or {}
        self._barrier_cfg: dict = fb.get("barrier_hardware", {"type": "logging"})
        self._reader_cfg: dict = fb.get("card_reader", {"type": "simulated"})
        self._poll_interval: float = fb.get("poll_interval_seconds", 0.5)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._barrier_hardware = None
        self._card_reader = None
        self.running = False
        self._last_open: dict[str, float] = {}
        self._open_lock = threading.Lock()
        self.on_card_seen = None  # callback(card_number) — UI hiển thị mã thẻ vừa quẹt (kể cả khi server từ chối)

    # ---- cấu hình ----------------------------------------------------------
    def _load_remote_config(self) -> None:
        try:
            remote = requests.get(f"{self.api_base_url}/agent/config", headers=self.headers, timeout=5).json()
            self._barrier_cfg, self._reader_cfg = remote["barrier_hardware"], remote["card_reader"]
            self._poll_interval = remote["hardware_agent"]["poll_interval_seconds"]
            logger.info("Đã nạp cấu hình từ server")
        except (requests.RequestException, KeyError, ValueError):
            logger.warning("Không lấy được cấu hình từ server, dùng cấu hình dự phòng")

    # ---- vòng đời ----------------------------------------------------------
    def start(self) -> None:
        """Khởi động. Lỗi phần cứng (sai cổng COM, thiếu quyền...) được raise cho nơi gọi hiển thị."""
        self._load_remote_config()
        self._barrier_hardware = build_barrier_hardware(self._barrier_cfg)
        self._card_reader = build_card_reader(self._reader_cfg)
        self._stop.clear()
        for bid in self._barrier_cfg.get("barriers", {}):
            self._spawn(self._poll_pending_open, bid)
        self._card_reader.start(self.handle_card)
        self.running = True
        logger.info("Agent đang chạy (đầu đọc thẻ: %s, barie: %s)",
                    self._reader_cfg.get("type"), self._barrier_cfg.get("type"))

    def stop(self) -> None:
        self._stop.set()
        self.running = False
        if self._card_reader is not None:
            try:
                self._card_reader.stop()
            except Exception:
                logger.exception("Lỗi khi dừng đầu đọc thẻ")
            self._card_reader = None
        logger.info("Agent đã dừng")

    def _spawn(self, fn, *args) -> None:
        t = threading.Thread(target=fn, args=args, daemon=True)
        t.start()
        self._threads.append(t)

    # ---- xử lý -------------------------------------------------------------
    def open_barrier(self, barrier_id: str) -> None:
        """Gửi lệnh mở rồi chờ an toàn để tự đóng (dùng chung cho thẻ, web/UI, nút mở tay).
        Bỏ qua lệnh mở lặp trong 2 giây: một lần quẹt có thể tới agent từ 2 đường (đầu đọc + ô nhập mã
        trên giao diện) và không được gửi 2 lệnh mở/2 luồng chờ đóng cho cùng 1 xe."""
        with self._open_lock:
            now = time.monotonic()
            if now - self._last_open.get(barrier_id, -10) < 2.0:
                return
            self._last_open[barrier_id] = now
        self._barrier_hardware.send_open(barrier_id)
        self._spawn(self._wait_and_close, barrier_id)

    def handle_card(self, card_number: str) -> None:
        if self.on_card_seen:
            self.on_card_seen(card_number)
        try:
            resp = requests.post(f"{self.api_base_url}/card/scan", json={"card_number": card_number},
                                 headers=self.headers, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            logger.exception("Không gọi được server cho thẻ %s — KHÔNG mở barie", card_number)
            return
        logger.info("Thẻ %s: %s, biển số=%r, barie=%s", card_number, data["action"], data["plate_text"], data["barrier_id"])
        self.open_barrier(data["barrier_id"])

    def _wait_and_close(self, barrier_id: str) -> None:
        """Hỏi server liên tục tới khi an toàn mới gửi lệnh đóng (debounce nằm ở server)."""
        while not self._stop.is_set():
            try:
                resp = requests.get(f"{self.api_base_url}/barrier/{barrier_id}/status", headers=self.headers, timeout=3)
                if resp.json().get("safe_to_close"):
                    self._barrier_hardware.send_close(barrier_id)
                    return
            except requests.RequestException:
                logger.warning("Mất kết nối tới server, chưa đóng barie %s", barrier_id)
            self._stop.wait(self._poll_interval)

    def _poll_pending_open(self, barrier_id: str) -> None:
        """Mở barie khi lệnh đến từ giao diện (bảo vệ bấm quét thẻ/khách vào) thay vì đầu đọc của agent."""
        while not self._stop.is_set():
            try:
                resp = requests.get(f"{self.api_base_url}/barrier/{barrier_id}/pending-open", headers=self.headers, timeout=3)
                if resp.json().get("open"):
                    logger.info("Lệnh mở barie %s từ giao diện", barrier_id)
                    self.open_barrier(barrier_id)
            except requests.RequestException:
                logger.warning("Mất kết nối tới server khi hỏi lệnh mở barie %s", barrier_id)
            self._stop.wait(self._poll_interval)
