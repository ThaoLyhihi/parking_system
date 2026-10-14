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
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.runner import HardwareAgent  # noqa: E402
from app.config import config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")


def main() -> None:
    agent = HardwareAgent(
        api_base_url=config.get("hardware_agent.api_base_url", "http://localhost:8000"),
        api_key=os.environ.get("AGENT_API_KEY") or config.get("hardware_agent.api_key", ""),
        fallback_cfg={
            "barrier_hardware": config.get("barrier_hardware", {"type": "logging"}),
            "card_reader": config.get("card_reader", {"type": "simulated"}),
            "poll_interval_seconds": config.get("hardware_agent.poll_interval_seconds", 0.5),
        },
    )
    agent.start()
    logging.getLogger("agent").info("Đang lắng nghe đầu đọc thẻ... (Ctrl+C để dừng)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        agent.stop()


if __name__ == "__main__":
    main()
