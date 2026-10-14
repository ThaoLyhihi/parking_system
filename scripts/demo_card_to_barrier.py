"""Demo nối đầy đủ: quẹt thẻ (USB hoặc giả lập) -> ghi nhận vào/ra (DB) ->
mở barie thật (hoặc log nếu chưa cấu hình phần cứng).

Mặc định dùng SimulatedCardReader để chạy được không cần đầu đọc thẻ thật —
đổi `card_reader.type: "usb_hid"` trong config.yaml khi có phần cứng thật.

Dùng: python scripts/demo_card_to_barrier.py
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.alpr.pipeline import PlateReading  # noqa: E402
from app.alpr.plate_detector import PlateDetection  # noqa: E402
from app.barrier.controller import BarrierController  # noqa: E402
from app.barrier.factory import build_barrier_hardware  # noqa: E402
from app.barrier.safety_zone import BarrierSafetyZone, SafetyZoneConfig  # noqa: E402
from app.card_reader.factory import build_card_reader  # noqa: E402
from app.card_reader.simulated_reader import SimulatedCardReader  # noqa: E402
from app.config import config  # noqa: E402
from app.db.base import get_session, init_db  # noqa: E402
from app.core.session_manager import VehicleSessionManager  # noqa: E402
from app.occupancy.flow_counter import FlowCounter  # noqa: E402
import numpy as np  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")


def main() -> None:
    init_db()
    db = get_session()
    flow_counter = FlowCounter(capacity_by_type=config.get("capacity", {}))
    session_manager = VehicleSessionManager(db, flow_counter, fee_schedule=config.get("fee_schedule", {}))

    barrier_hardware = build_barrier_hardware(config.get("barrier_hardware", {"type": "logging"}))
    safety = BarrierSafetyZone(SafetyZoneConfig(roi_polygon=config.get(
        "barrier_safety.roi_polygon", [[0.1, 0.5], [0.9, 0.5], [0.9, 1.0], [0.1, 1.0]])))
    barrier = BarrierController(barrier_id="1", safety_zone=safety, hardware=barrier_hardware)

    open_sessions: dict[str, int] = {}  # card_number -> session_id, đơn giản hoá cho demo

    def on_card(card_number: str) -> None:
        # Demo: không có camera/ALPR thật ở đây, dùng PlateReading rỗng để minh hoạ luồng.
        fake_reading = PlateReading(
            text="", confidence=0.0,
            detection=PlateDetection(bbox_xyxy=(0, 0, 0, 0), confidence=0.0, corners=np.zeros((4, 2))),
        )
        if card_number not in open_sessions:
            session = session_manager.handle_entry(fake_reading, vehicle_type="XeMay")
            open_sessions[card_number] = session.id
            barrier.open_barrier(reason=f"the {card_number} vao")
        else:
            from app.db.models import VehicleSession
            session = db.get(VehicleSession, open_sessions.pop(card_number))
            session_manager.handle_exit(session, fake_reading)
            barrier.open_barrier(reason=f"the {card_number} ra")

    # Demo này LUÔN dùng SimulatedCardReader để chạy được không cần phần cứng thật,
    # bất kể config.yaml đang khai báo "usb_hid" cho máy vận hành thật. Muốn test với
    # đầu đọc USB thật, gọi build_card_reader(config.get("card_reader")) trực tiếp.
    card_reader = SimulatedCardReader()
    card_reader.start(on_card)

    if isinstance(card_reader, SimulatedCardReader):
        print("Dùng SimulatedCardReader — tự giả lập 1 lượt vào + 1 lượt ra, cách nhau 1s.")
        card_reader.simulate_scan("0001234567")
        time.sleep(1)
        card_reader.simulate_scan("0001234567")
    else:
        print("Đang lắng nghe đầu đọc thẻ USB thật, Ctrl+C để dừng...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    card_reader.stop()
    db.close()


if __name__ == "__main__":
    main()
