"""Agent phần cứng — chạy TRỰC TIẾP trên Windows (KHÔNG chạy trong Docker).

Lý do tách riêng: đầu đọc thẻ USB và cổng COM điều khiển barie là thiết bị
cục bộ của máy Windows. Docker Desktop trên Windows chạy container Linux qua
WSL2, không xuyên thiết bị USB/COM vào container một cách đơn giản/đáng tin
cậy được. Vì vậy:

  - AI Inference Service (ALPR, đếm chỗ trống, quyết định an toàn barie, CSDL)
    chạy trong Docker — xem docker-compose.yml, không đổi theo OS.
  - Agent này chạy ngay trên Windows, chỉ làm 2 việc: đọc đầu đọc thẻ USB, và
    gửi lệnh thật qua cổng COM cho barie — gọi HTTP vào Docker để lấy quyết
    định ("có phải xe vào/ra không, mở barie nào, lúc nào an toàn để đóng").

Cài đặt trên Windows:
    pip install -r requirements-windows-agent.txt
    python scripts/windows_hardware_agent.py

CHƯA TEST được với phần cứng Windows thật (môi trường phát triển là Linux,
không có đầu đọc thẻ/barie thật) — xem README mục "Việc chưa làm".
"""
from __future__ import annotations

import logging
import sys
import os
import threading
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.barrier.factory import build_barrier_hardware  # noqa: E402
from app.card_reader.factory import build_card_reader  # noqa: E402
from app.config import config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
logger = logging.getLogger("windows_hardware_agent")


def main() -> None:
    api_base_url = config.get("hardware_agent.api_base_url", "http://localhost:8000")
    poll_interval = config.get("hardware_agent.poll_interval_seconds", 0.5)
    # Khoá xác thực với AI service (hardware_agent.api_key trong config, hoặc biến AGENT_API_KEY).
    headers = {"X-Agent-Key": os.environ.get("AGENT_API_KEY") or config.get("hardware_agent.api_key", "")}

    barrier_cfg = config.get("barrier_hardware", {"type": "logging"})
    reader_cfg = config.get("card_reader", {"type": "simulated"})
    # Ưu tiên cấu hình admin đã chỉnh trên giao diện (mục Cài đặt); không gọi được server thì dùng config.yaml.
    try:
        remote = requests.get(f"{api_base_url}/agent/config", headers=headers, timeout=5).json()
        barrier_cfg, reader_cfg = remote["barrier_hardware"], remote["card_reader"]
        poll_interval = remote["hardware_agent"]["poll_interval_seconds"]
        logger.info("Đã nạp cấu hình từ server")
    except (requests.RequestException, KeyError, ValueError):
        logger.warning("Không lấy được cấu hình từ server, dùng config.yaml cục bộ")

    barrier_hardware = build_barrier_hardware(barrier_cfg)
    card_reader = build_card_reader(reader_cfg)

    def wait_and_close(barrier_id: str) -> None:
        """Hỏi AI service liên tục tới khi an toàn để đóng, rồi tự gửi lệnh
        đóng qua COM — độ trễ debounce (clear_frames_required) đã nằm bên AI
        service (mục 6.6 thuyết minh), agent chỉ cần hỏi lại định kỳ."""
        while True:
            try:
                resp = requests.get(f"{api_base_url}/barrier/{barrier_id}/status", headers=headers, timeout=3)
                if resp.json().get("safe_to_close"):
                    barrier_hardware.send_close(barrier_id)
                    return
            except requests.RequestException:
                logger.warning("Mất kết nối tới AI service, chưa đóng barie %s", barrier_id)
            time.sleep(poll_interval)

    def on_card(card_number: str) -> None:
        try:
            resp = requests.post(f"{api_base_url}/card/scan", json={"card_number": card_number}, headers=headers, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            logger.exception("Không gọi được AI service cho thẻ %s — KHÔNG mở barie", card_number)
            return

        barrier_id = data["barrier_id"]
        logger.info("Thẻ %s: %s, biển số=%r, barie=%s", card_number, data["action"], data["plate_text"], barrier_id)
        barrier_hardware.send_open(barrier_id)
        threading.Thread(target=wait_and_close, args=(barrier_id,), daemon=True).start()

    def poll_pending_open(barrier_id: str) -> None:
        """Mở khi lệnh KHÔNG đến từ chính đầu đọc thẻ của agent này — ví dụ bảo
        vệ bấm "Quét thẻ"/"Khách vào" trên trang web. Agent là nơi DUY NHẤT có
        quyền truy cập cổng COM nên phải tự hỏi liên tục xem có lệnh đang chờ."""
        while True:
            try:
                resp = requests.get(f"{api_base_url}/barrier/{barrier_id}/pending-open", headers=headers, timeout=3)
                if resp.json().get("open"):
                    logger.info("Lệnh mở barie %s từ web/API (không phải đầu đọc thẻ của agent)", barrier_id)
                    barrier_hardware.send_open(barrier_id)
                    threading.Thread(target=wait_and_close, args=(barrier_id,), daemon=True).start()
            except requests.RequestException:
                logger.warning("Mất kết nối tới AI service khi hỏi lệnh mở barie %s", barrier_id)
            time.sleep(poll_interval)

    for bid in barrier_cfg.get("barriers", {}):
        threading.Thread(target=poll_pending_open, args=(bid,), daemon=True).start()

    card_reader.start(on_card)
    logger.info("Agent đang chạy, lắng nghe đầu đọc thẻ... (Ctrl+C để dừng)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        card_reader.stop()


if __name__ == "__main__":
    main()
