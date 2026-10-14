"""Smoke test — không có ảnh biển số thật trong môi trường dev này, nên chỉ
kiểm tra pipeline KHÔNG CRASH và trả về kiểu dữ liệu đúng trên ảnh ngẫu nhiên.
Đây KHÔNG phải test độ chính xác model (cần ảnh thật, xem scripts/test_alpr_on_image.py)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.alpr.plate_detector import PlateDetector  # noqa: E402
from app.barrier.controller import BarrierController  # noqa: E402
from app.barrier.safety_zone import BarrierSafetyZone, SafetyZoneConfig  # noqa: E402
from app.occupancy.flow_counter import FlowCounter  # noqa: E402

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "licenseplate" / "detect.onnx"


def test_plate_detector_runs_on_random_image():
    detector = PlateDetector(model_path=str(MODEL_PATH))
    random_image = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
    detections = detector.detect(random_image)
    assert isinstance(detections, list)


def test_flow_counter_basic():
    counter = FlowCounter(capacity_by_type={"XeMay": 10})
    counter.record_entry("XeMay")
    counter.record_entry("XeMay")
    counter.record_exit("XeMay")
    assert counter.current_count("XeMay") == 1
    assert counter.vacant_slots("XeMay") == 9


def test_barrier_controller_blocks_close_without_camera():
    safety = BarrierSafetyZone(SafetyZoneConfig(roi_polygon=[(0.1, 0.5), (0.9, 0.5), (0.9, 1.0), (0.1, 1.0)]))
    controller = BarrierController(barrier_id="B1", safety_zone=safety)
    # Không có frame camera (None) -> fail-safe, không bao giờ cho phép đóng.
    closed = controller.try_close_barrier(None)
    assert closed is False


def _fresh_client(monkeypatch, tmp_path):
    """TestClient trên DB SQLite tạm, có sẵn 1 admin; mỗi test độc lập."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.db.base as dbbase
    from app.db.models import Base

    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setattr(dbbase, "_engine", engine)
    monkeypatch.setattr(dbbase, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    Base.metadata.create_all(engine)
    monkeypatch.setenv("AGENT_API_KEY", "k-test")
    from app.auth import ROLE_ADMIN, ROLE_GUARD, create_user
    db = dbbase.get_session()
    create_user(db, "boss", "bosspass123", "Quản lý", ROLE_ADMIN)
    create_user(db, "bv1", "guardpass123", "Bảo Vệ Một", ROLE_GUARD)
    from app import settings as app_settings
    from app.db.seed import seed_defaults
    seed_defaults(db)
    # test cũ quét thẻ chưa đăng ký liên tiếp -> cho phép thẻ lạ + tắt chống quẹt trùng
    app_settings.save_section(db, "general", {"allow_unregistered_cards": True, "duplicate_swipe_seconds": 0})
    db.close()

    # _pending_open/_last_scan là dict toàn cục trong app.api.main (sống suốt tiến trình
    # pytest, không theo từng DB tạm) — xoá sạch để test sau không thấy rác của test trước.
    import app.api.main as _m
    _m._pending_open.clear()
    _m._last_scan.clear()

    from app.api.main import _flow_counter, app
    from fastapi.testclient import TestClient
    # _flow_counter là biến toàn cục của module -> reset để test không ảnh hưởng nhau.
    _flow_counter.vehicles_in.clear()
    _flow_counter.vehicles_out.clear()
    import app.api.main as m
    m._last_scan.clear()
    return TestClient(app)


def _login(client, user, pw):
    r = client.post("/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_auth_and_role_separation(monkeypatch, tmp_path):
    c = _fresh_client(monkeypatch, tmp_path)
    assert c.post("/auth/login", json={"username": "bv1", "password": "sai"}).status_code == 401
    assert c.post("/card/scan", json={"card_number": "X"}).status_code == 401  # chưa đăng nhập
    guard, admin = _login(c, "bv1", "guardpass123"), _login(c, "boss", "bosspass123")
    # bảo vệ không vào được khu admin / ALPR debug
    assert c.get("/admin/users", headers=guard).status_code == 403
    assert c.post("/admin/users", headers=guard, json={"username": "x", "password": "12345678", "full_name": "x"}).status_code == 403
    assert c.get("/admin/users", headers=admin).status_code == 200
    # admin không có ca; bảo vệ có
    assert c.get("/shift/current", headers=admin).status_code == 404
    assert c.get("/shift/current", headers=guard).status_code == 200
    # khoá tài khoản -> token cũ mất hiệu lực
    uid = next(u["id"] for u in c.get("/admin/users", headers=admin).json() if u["username"] == "bv1")
    assert c.patch(f"/admin/users/{uid}", headers=admin, json={"is_active": False}).status_code == 200
    assert c.get("/me", headers=guard).status_code == 401


def test_guard_scan_stats_pdf(monkeypatch, tmp_path):
    c = _fresh_client(monkeypatch, tmp_path)
    guard = _login(c, "bv1", "guardpass123")
    assert c.post("/card/scan", headers=guard, json={"card_number": "A1"}).json()["action"] == "entry"
    assert c.post("/card/scan", headers=guard, json={"card_number": "A2"}).json()["action"] == "entry"
    out = c.post("/card/scan", headers=guard, json={"card_number": "A1"}).json()
    assert out["action"] == "exit" and out["amount"] == 3000
    s = c.get("/shift/current", headers=guard).json()
    assert (s["vehicles_in"], s["vehicles_out"], s["vehicles_remaining"], s["total_amount"]) == (2, 1, 1, 3000)
    pdf = c.get(f"/shift/{s['shift_id']}/report.pdf", headers=guard)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # bảo vệ khác không xem được báo cáo ca của người này
    from app.auth import ROLE_GUARD, create_user
    import app.db.base as dbbase
    create_user(dbbase.get_session(), "bv2", "guardpass123", "BV Hai", ROLE_GUARD)
    other = _login(c, "bv2", "guardpass123")
    assert c.get(f"/shift/{s['shift_id']}/report.pdf", headers=other).status_code == 404
    assert c.post("/shift/close", headers=guard).json()["status"] == "closed"


def test_agent_key_needs_open_shift(monkeypatch, tmp_path):
    c = _fresh_client(monkeypatch, tmp_path)
    agent = {"X-Agent-Key": "k-test"}
    assert c.post("/card/scan", headers={"X-Agent-Key": "sai"}, json={"card_number": "Z"}).status_code == 401
    assert c.post("/card/scan", headers=agent, json={"card_number": "Z"}).status_code == 409  # chưa ai mở ca
    _login(c, "bv1", "guardpass123")
    assert c.post("/card/scan", headers=agent, json={"card_number": "Z"}).json()["action"] == "entry"


def test_status_overview_for_management_dashboard(monkeypatch, tmp_path):
    """Trang quản lý (mục "Tình trạng bãi xe") dùng endpoint này — phải đòi đăng
    nhập, và phản ánh đúng số xe hiện tại sau khi bảo vệ quét thẻ."""
    c = _fresh_client(monkeypatch, tmp_path)
    assert c.get("/status/overview").status_code == 401  # chưa đăng nhập
    guard, admin = _login(c, "bv1", "guardpass123"), _login(c, "boss", "bosspass123")
    c.post("/card/scan", headers=guard, json={"card_number": "B1", "vehicle_type": "XeMay"})
    s = c.get("/status/overview", headers=admin).json()
    assert s["occupancy"]["XeMay"]["current"] == 1
    assert s["cameras"]["gate_in_connected"] is False  # URL giả trong config.example.yaml, không kết nối được
    assert s["cameras"]["gate_out_shares_gate_in"] is True  # mặc định chỉ cấu hình 1 camera cổng (1 làn)
    assert s["cameras"]["barrier_connected"] is False


def test_close_shift_sends_email(monkeypatch, tmp_path):
    import app.api.main as m
    sent = []
    monkeypatch.setattr(m, "email_enabled", lambda cfg: True)
    monkeypatch.setattr(m, "send_shift_report", lambda cfg, **kw: sent.append(kw))
    c = _fresh_client(monkeypatch, tmp_path)
    guard = _login(c, "bv1", "guardpass123")
    c.post("/card/scan", headers=guard, json={"card_number": "E1"})
    r = c.post("/shift/close", headers=guard).json()
    assert r["email_queued"] is True
    assert len(sent) == 1 and sent[0]["pdf"].startswith(b"%PDF") and "Bảo Vệ Một" in sent[0]["subject"]


def _cardmgmt_client(monkeypatch, tmp_path):
    """Như _fresh_client nhưng thẻ lạ bị từ chối (chế độ chạy thật)."""
    c = _fresh_client(monkeypatch, tmp_path)
    import app.db.base as dbbase
    from app import settings as app_settings
    db = dbbase.get_session()
    app_settings.save_section(db, "general", {"allow_unregistered_cards": False})
    db.close()
    return c, _login(c, "boss", "bosspass123"), _login(c, "bv1", "guardpass123")


def test_card_and_tariff_management(monkeypatch, tmp_path):
    c, admin, guard = _cardmgmt_client(monkeypatch, tmp_path)
    # bảo vệ không được quản lý thẻ/biểu phí/cài đặt
    for path in ("/admin/cards", "/admin/tariffs", "/admin/vehicle-types", "/admin/settings"):
        assert c.get(path, headers=guard).status_code == 403
    # thẻ chưa đăng ký bị từ chối
    assert c.post("/card/scan", headers=guard, json={"card_number": "T1"}).status_code == 404
    # tạo thẻ lượt, quét vào/ra, tiền theo biểu phí XeMay seed (3000 giờ đầu)
    r = c.post("/admin/cards", headers=admin, json={"card_number": "T1", "vehicle_type_code": "XeMay"})
    assert r.status_code == 201
    assert c.post("/admin/cards", headers=admin, json={"card_number": "T1", "vehicle_type_code": "XeMay"}).status_code == 409
    assert c.post("/card/scan", headers=guard, json={"card_number": "T1"}).json()["action"] == "entry"
    assert c.post("/card/scan", headers=guard, json={"card_number": "T1"}).json()["amount"] == 3000
    # đổi biểu phí qua API -> áp dụng ngay lượt sau
    tid = next(t["id"] for t in c.get("/admin/tariffs", headers=admin).json() if t["vehicle_type_code"] == "XeMay")
    body = {"vehicle_type_code": "XeMay", "mode": "flat", "first_fee": 5000}
    assert c.put(f"/admin/tariffs/{tid}", headers=admin, json=body).status_code == 200
    c.post("/card/scan", headers=guard, json={"card_number": "T1"})
    assert c.post("/card/scan", headers=guard, json={"card_number": "T1"}).json()["amount"] == 5000
    # khoá thẻ -> từ chối
    cid = r.json()["id"]
    c.put(f"/admin/cards/{cid}", headers=admin, json={"card_number": "T1", "vehicle_type_code": "XeMay", "status": "locked"})
    assert c.post("/card/scan", headers=guard, json={"card_number": "T1"}).status_code == 403
    # thẻ đã có lịch sử không xoá được
    assert c.delete(f"/admin/cards/{cid}", headers=admin).status_code == 409


def test_monthly_pass_flow(monkeypatch, tmp_path):
    import datetime as dt
    c, admin, guard = _cardmgmt_client(monkeypatch, tmp_path)
    today = dt.date.today()
    # thẻ tháng bắt buộc có ngày bắt đầu/hết hạn
    bad = {"card_number": "M1", "vehicle_type_code": "XeMayThang"}
    assert c.post("/admin/cards", headers=admin, json=bad).status_code == 422
    ok = {**bad, "start_date": str(today - dt.timedelta(days=40)), "expire_date": str(today - dt.timedelta(days=10)),
          "plate_number": "59A1-123.45"}
    cid = c.post("/admin/cards", headers=admin, json=ok).json()["id"]
    assert c.post("/card/scan", headers=guard, json={"card_number": "M1"}).status_code == 403  # hết hạn
    # gia hạn 1 tháng từ hôm nay (vì đã hết hạn) -> quét được, không thu tiền lượt
    r = c.post(f"/admin/cards/{cid}/renew", headers=admin, json={"months": 1}).json()
    assert r["amount"] == 12000 and r["card"]["expire_date"] > str(today)
    assert c.post("/card/scan", headers=guard, json={"card_number": "M1"}).json()["action"] == "entry"
    assert c.post("/card/scan", headers=guard, json={"card_number": "M1"}).json()["amount"] == 0
    assert c.get(f"/admin/cards/{cid}/payments", headers=admin).json()[0]["amount"] == 12000
    assert c.get("/admin/cards?kind=monthly", headers=admin).json()["total"] == 1
    assert c.get("/admin/cards?kind=daily", headers=admin).json()["total"] == 0


def test_tariff_rules_and_settings(monkeypatch, tmp_path):
    import datetime as dt
    from app.core.fee import fee_from_tariff
    from app.db.models import Tariff
    t_in = dt.datetime(2030, 1, 1, 10)
    block = Tariff(mode="block", first_fee=3000, next_fee=2000, block_minutes=60, max_fee_per_day=10000, overnight_fee=0)
    assert fee_from_tariff(block, t_in, t_in + dt.timedelta(minutes=30)) == 3000
    assert fee_from_tariff(block, t_in, t_in + dt.timedelta(hours=3)) == 7000
    assert fee_from_tariff(block, t_in, t_in + dt.timedelta(hours=10)) == 10000  # trần ngày
    night = Tariff(mode="flat", first_fee=5000, overnight_fee=10000, max_fee_per_day=None)
    assert fee_from_tariff(night, t_in, t_in + dt.timedelta(days=1)) == 15000  # qua 1 đêm

    c, admin, guard = _cardmgmt_client(monkeypatch, tmp_path)
    s = c.get("/admin/settings", headers=admin).json()
    assert s["email"]["values"]["password"] == "" and "fields" in s["general"]
    r = c.put("/admin/settings/email", headers=admin, json={"enabled": True, "recipients": "a@x.vn, b@x.vn", "password": "bi-mat"})
    assert r.json()["values"]["recipients"] == ["a@x.vn", "b@x.vn"] and r.json()["values"]["password"] == ""
    assert c.put("/admin/settings/email", headers=admin, json={"khong_co": 1}).status_code == 422
    assert c.put("/admin/settings/cameras", headers=admin, json={"gate_in_source": "rtsp://x"}).json()["restart_required"] is True


def test_gate_camera_fallback_supports_1_to_4_cameras(monkeypatch):
    """Mục cài đặt camera hỗ trợ 1-4 camera: bãi chỉ có 1 camera cổng (1 làn chung
    ra/vào) vẫn phải đọc được biển số cho cả lượt vào VÀ lượt ra bằng chính camera
    đó; bãi có camera cổng ra riêng thì phải dùng đúng camera riêng cho lượt ra."""
    import app.api.main as m

    monkeypatch.setattr(m, "_gate_in_camera", "CAM_IN")
    monkeypatch.setattr(m, "_gate_out_camera", None)
    assert m._gate_camera_for(is_entry=True) == "CAM_IN"
    assert m._gate_camera_for(is_entry=False) == "CAM_IN"  # không có cam riêng -> dùng lại cam cổng vào

    monkeypatch.setattr(m, "_gate_out_camera", "CAM_OUT")
    assert m._gate_camera_for(is_entry=True) == "CAM_IN"
    assert m._gate_camera_for(is_entry=False) == "CAM_OUT"  # có cam riêng cho làn ra -> dùng đúng cam đó


def test_barrier_pending_open_queue_for_windows_agent(monkeypatch, tmp_path):
    """Lượt quét từ WEB (không phải chính agent) vẫn phải xếp được lệnh mở vào
    hàng đợi — vì chỉ agent chạy trên Windows mới gửi được lệnh thật qua cổng COM."""
    c = _fresh_client(monkeypatch, tmp_path)
    agent = {"X-Agent-Key": "k-test"}
    guard = _login(c, "bv1", "guardpass123")
    # XeMay (loại mặc định khi không truyền vehicle_type) seed sẵn dùng barie "2" (giống InOutConf cũ).
    assert c.get("/barrier/2/pending-open", headers=agent).json() == {"open": False}
    c.post("/card/scan", headers=guard, json={"card_number": "Q1"})  # quét qua web, không qua agent
    assert c.get("/barrier/2/pending-open", headers=agent).json() == {"open": True}
    assert c.get("/barrier/2/pending-open", headers=agent).json() == {"open": False}  # lấy 1 lần rồi xoá
    assert c.get("/barrier/2/pending-open").status_code == 401  # không có agent key


def test_visitor_entry_and_exit_without_card(monkeypatch, tmp_path):
    """Nút "Khách vào" trên web (không cần thẻ) — mở barie, ghi nhận đúng số xe
    tồn, và thu phí đúng khi khách đó ra."""
    c = _fresh_client(monkeypatch, tmp_path)
    guard = _login(c, "bv1", "guardpass123")
    before = c.get("/status/overview", headers=guard).json()["occupancy"]["XeMay"]["current"]

    r = c.post("/visitor/entry", headers=guard, json={"vehicle_type": "XeMay"})
    assert r.status_code == 200 and r.json()["barrier_id"] == "2"  # XeMay seed: barie vào = "2"
    sid = r.json()["session_id"]
    after = c.get("/status/overview", headers=guard).json()["occupancy"]["XeMay"]["current"]
    assert after == before + 1
    assert c.get("/barrier/2/pending-open", headers={"X-Agent-Key": "k-test"}).json() == {"open": True}

    open_list = c.get("/visitor/open", headers=guard).json()
    assert [v["session_id"] for v in open_list] == [sid]

    out = c.post(f"/visitor/{sid}/exit", headers=guard)
    assert out.status_code == 200 and out.json()["amount"] == 3000  # biểu phí XeMay seed, giờ đầu
    assert c.get("/visitor/open", headers=guard).json() == []
    assert c.post(f"/visitor/{sid}/exit", headers=guard).status_code == 404  # đã ra rồi, quét lại thì từ chối


def test_realtime_events_broadcast_over_websocket(monkeypatch, tmp_path):
    """Web mở WebSocket để nhận biển số vào/ra realtime — phải nhận được sự kiện
    ngay khi có lượt quét, và phải đăng nhập mới kết nối được."""
    c = _fresh_client(monkeypatch, tmp_path)
    guard = _login(c, "bv1", "guardpass123")
    token = guard["Authorization"].split(" ", 1)[1]
    with c.websocket_connect(f"/ws/events?token={token}") as ws:
        c.post("/card/scan", headers=guard, json={"card_number": "W1", "vehicle_type": "OTO"})
        msg = ws.receive_json()
        assert msg["type"] == "entry" and msg["vehicle_type"] == "OTO" and msg["card_number"] == "W1"
    from starlette.websockets import WebSocketDisconnect
    try:
        with c.websocket_connect("/ws/events?token=sai"):
            assert False, "phải bị từ chối kết nối vì token sai"
    except WebSocketDisconnect as e:
        assert e.code == 4401


def test_serial_card_reader_parses_digits_until_line_ending(monkeypatch):
    """Đầu đọc thẻ qua cổng COM (bổ sung lại, song song với USB) — giả lập cổng
    serial gửi về số thẻ dạng ASCII kết thúc bằng \\r hoặc \\n, không cần phần
    cứng thật để kiểm tra logic tách số thẻ."""
    import time

    import app.card_reader.serial_reader as sr

    chunks = [b"12345\r", b"6789\n", b""]

    class FakeSerial:
        is_open = True

        def __init__(self, port, baudrate, timeout):
            assert port == "COM_TEST" and baudrate == 9600

        def read(self, n):
            return chunks.pop(0) if chunks else b""

        def close(self):
            self.is_open = False

    monkeypatch.setattr(sr.serial, "Serial", FakeSerial)

    received: list[str] = []
    reader = sr.SerialCardReader(port="COM_TEST", baudrate=9600)
    reader.start(received.append)
    time.sleep(0.3)
    reader.stop()
    assert received == ["12345", "6789"]


def test_build_card_reader_serial_requires_port():
    from app.card_reader.factory import build_card_reader

    with pytest.raises(ValueError, match="port"):
        build_card_reader({"type": "serial"})
    reader = build_card_reader({"type": "serial", "port": "COM7"})
    assert reader.port == "COM7"
