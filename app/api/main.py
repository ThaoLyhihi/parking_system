"""AI Inference Service (FastAPI) — đúng kiến trúc mục 6.3 thuyết minh đề tài:
tách rời khỏi phần mềm quản lý, expose API để ghi nhận kết quả AI.

Chạy demo: `uvicorn app.api.main:app --reload` (xem README.md).

Service này chạy trong Docker (cross-platform, không phụ thuộc OS triển khai).
Camera (RTSP) đọc trực tiếp từ đây vì là luồng MẠNG, container gọi ra ngoài
được bình thường dù chạy trên Windows (qua Docker Desktop/WSL2). Nhưng đầu
đọc thẻ USB và lệnh gửi ra cổng COM của barie là THIẾT BỊ CỤC BỘ của máy host
— không xuyên vào container được, nên 2 việc đó do
`scripts/windows_hardware_agent.py` (chạy ngay trên Windows, ngoài Docker)
đảm nhiệm, gọi vào các endpoint `/card/scan` và `/barrier/{id}/status` dưới
đây để lấy quyết định từ AI.
"""
from __future__ import annotations

import logging
import threading

import cv2
import numpy as np
import datetime as dt
import time
from pathlib import Path

from fastapi import (BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Query,
                     Response, UploadFile, WebSocket, WebSocketDisconnect)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.alpr.pipeline import AlprPipeline, PlateReading
from app.alpr.plate_detector import PlateDetection, PlateDetector
from app.barrier.safety_zone import BarrierSafetyZone, SafetyZoneConfig
from app import auth
from app import settings as app_settings
from app.auth import ROLE_ADMIN, ROLE_GUARD, current_user, get_db, require_admin, require_agent, user_or_agent
from app.config import config
from app.core.mailer import email_enabled, send_shift_report
from app.core.reports import build_shift_pdf, fmt_dt, fmt_money, shift_stats
from app.core.session_manager import VehicleSessionManager
from app.face import verify as face_verify
from app.db.base import get_session, init_db
from app.db.seed import seed_defaults
from app.db.models import AuthToken, Card, User, VehicleSession, VehicleType, WorkShift
from app.occupancy.flow_counter import FlowCounter
from app.vision.camera import CameraSpec, CameraStream

logger = logging.getLogger("api")

app = FastAPI(title="Parking AI Inference Service")

_detector = PlateDetector(
    model_path=config.get("alpr.model_path", "models/licenseplate/detect.onnx"),
    input_size=config.get("alpr.input_size", 896),
    conf_threshold=config.get("alpr.conf_threshold", 0.4),
    iou_threshold=config.get("alpr.iou_threshold", 0.45),
)
_pipeline = AlprPipeline(_detector)
_flow_counter = FlowCounter(capacity_by_type=config.get("capacity", {}))

_gate_in_camera: CameraStream | None = None
_gate_out_camera: CameraStream | None = None  # None -> dùng chung _gate_in_camera (1 làn ra/vào)
_barrier_cameras: dict[str, CameraStream] = {}
_safety_zones: dict[str, BarrierSafetyZone] = {}
_safety_lock = threading.Lock()

# Lệnh "mở barie" chờ scripts/windows_hardware_agent.py lấy — cần có hàng đợi riêng
# (không chỉ trả thẳng trong response của /card/scan) vì lượt quét có thể do WEB gọi
# (bảo vệ bấm trên trình duyệt), còn COM port vật lý thì chỉ agent trên Windows mới
# đụng tới được — xem README mục "Triển khai trên Windows".
_pending_open: dict[str, bool] = {}
_pending_lock = threading.Lock()


def _queue_open(barrier_id: str) -> None:
    with _pending_lock:
        _pending_open[barrier_id] = True


class EventBus:
    """Đẩy sự kiện xe vào/ra tới mọi trang web đang mở (mục "biển số vào ra realtime")."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, data: dict) -> None:
        for ws in list(self._clients):
            try:
                await ws.send_json(data)
            except Exception:
                self._clients.discard(ws)


events = EventBus()


class PlateReadingOut(BaseModel):
    text: str
    confidence: float
    bbox: tuple[float, float, float, float]


class CardScanIn(BaseModel):
    card_number: str
    vehicle_type: str | None = None  # ghi đè nếu client đã biết loại xe, không thì mặc định "XeMay"


class CardScanOut(BaseModel):
    action: str  # "entry" | "exit"
    barrier_id: str
    plate_text: str
    plate_confidence: float
    amount: int | None = None
    message: str | None = None  # cảnh báo cho bảo vệ: sắp hết hạn, biển số lệch, trùng biển...


def _safety_monitor_loop(barrier_id: str, camera: CameraStream, roi_cfg: SafetyZoneConfig) -> None:
    zone = BarrierSafetyZone(roi_cfg)
    with _safety_lock:
        _safety_zones[barrier_id] = zone
    while True:
        zone.update(camera.read())


@app.on_event("startup")
def _startup() -> None:
    """Hỗ trợ 1-4 camera: mỗi nguồn (gate_in/gate_out/overview/barrier) là TUỲ CHỌN,
    thiếu camera nào thì bỏ qua đúng chức năng gắn với nó, các phần khác vẫn chạy
    (xem mục "cameras" trong app/settings.py). Đọc cấu hình qua app_settings.get_section
    (không phải config.get trực tiếp) để giá trị admin chỉnh trên web (lưu DB) thật sự
    có hiệu lực sau khi khởi động lại — trước đây đọc thẳng config.yaml nên sửa trên
    web không ăn, đã sửa lại cho đúng."""
    global _gate_in_camera, _gate_out_camera
    init_db()
    auth.bootstrap_admin()
    db = get_session()
    try:
        seed_defaults(db)
        refresh_capacity(db)
        cam_cfg = app_settings.get_section(db, "cameras")
        safety_cfg = app_settings.get_section(db, "barrier_safety")
    finally:
        db.close()

    if cam_cfg.get("gate_in_source"):
        _gate_in_camera = CameraStream(CameraSpec(name="gate_in", source=cam_cfg["gate_in_source"])).start()
    else:
        logger.warning("Chưa cấu hình camera cổng vào (cameras.gate_in_source) — ALPR sẽ không đọc được biển số.")

    if cam_cfg.get("gate_out_source"):
        _gate_out_camera = CameraStream(CameraSpec(name="gate_out", source=cam_cfg["gate_out_source"])).start()
    # Không log cảnh báo nếu thiếu gate_out — đây là trường hợp BÌNH THƯỜNG (1 làn ra/vào
    # chung), tự dùng lại _gate_in_camera, xem _gate_camera_for().

    roi_cfg = SafetyZoneConfig(
        roi_polygon=safety_cfg.get("roi_polygon", [[0.1, 0.5], [0.9, 0.5], [0.9, 1.0], [0.1, 1.0]]),
        clear_frames_required=safety_cfg.get("clear_frames_required", 8),
        motion_threshold=safety_cfg.get("motion_threshold", 25),
    )
    if cam_cfg.get("barrier_source"):
        cam = CameraStream(CameraSpec(name="barrier", source=cam_cfg["barrier_source"])).start()
        _barrier_cameras["1"] = cam
        threading.Thread(target=_safety_monitor_loop, args=("1", cam, roi_cfg), daemon=True).start()
    else:
        logger.warning("Chưa cấu hình cameras.barrier — endpoint /barrier/{id}/status sẽ luôn trả về chưa an toàn.")


def _gate_camera_for(is_entry: bool) -> CameraStream | None:
    """Cổng ra dùng camera riêng nếu có cấu hình (bãi có làn ra riêng); không thì
    dùng lại camera cổng vào — đúng mô hình "1 camera cũng chạy được" (mục cameras)."""
    if is_entry:
        return _gate_in_camera
    return _gate_out_camera or _gate_in_camera


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/occupancy")
def occupancy(_: User = Depends(current_user)) -> dict:
    return _flow_counter.snapshot()


@app.get("/status/overview")
def status_overview(_: User = Depends(current_user)) -> dict:
    """Tình trạng bãi xe thời gian thực cho trang quản lý (mục "Tình trạng bãi xe"):
    chỗ trống theo loại xe + tình trạng camera/an toàn barie — để ban quản lý biết
    hệ thống AI có đang hoạt động/giám sát đúng không, không chỉ xem số liệu ca trực."""
    with _safety_lock:
        zone = _safety_zones.get("1")
    barrier_camera = _barrier_cameras.get("1")
    return {
        "occupancy": _flow_counter.snapshot(),
        "cameras": {
            "gate_in_configured": _gate_in_camera is not None,
            "gate_in_connected": bool(_gate_in_camera and _gate_in_camera.is_connected),
            "gate_out_configured": _gate_out_camera is not None,
            "gate_out_connected": bool(_gate_out_camera and _gate_out_camera.is_connected),
            "gate_out_shares_gate_in": _gate_out_camera is None,  # 1 làn chung ra/vào
            "barrier_configured": barrier_camera is not None,
            "barrier_connected": bool(barrier_camera and barrier_camera.is_connected),
        },
        "barrier": {
            "configured": zone is not None,
            "safe_to_close": zone.update(barrier_camera.read()) if (zone and barrier_camera) else False,
        },
    }


@app.get("/barrier/{barrier_id}/status", dependencies=[Depends(require_agent)])
def barrier_status(barrier_id: str) -> dict:
    """Windows hardware agent gọi liên tục khi barie đang mở, để biết lúc nào
    an toàn để tự gửi lệnh đóng qua cổng COM (xem scripts/windows_hardware_agent.py)."""
    with _safety_lock:
        zone = _safety_zones.get(barrier_id)
    if zone is None:
        return {"safe_to_close": False, "reason": "chưa cấu hình camera cho barrier này"}
    camera = _barrier_cameras.get(barrier_id)
    safe = zone.update(camera.read()) if camera else False
    return {"safe_to_close": safe}


@app.post("/alpr/detect", response_model=list[PlateReadingOut], dependencies=[Depends(require_admin)])
async def detect_plate(file: UploadFile = File(...)) -> list[PlateReadingOut]:
    """Nhận 1 ảnh (ví dụ 1 khung hình camera cổng), trả về các biển số phát hiện được.
    Dùng để test nhanh model qua HTTP, không cần script dòng lệnh."""
    data = await file.read()
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    readings = _pipeline.read(image)
    return [
        PlateReadingOut(text=r.text, confidence=r.confidence, bbox=r.detection.bbox_xyxy)
        for r in readings
    ]


def refresh_capacity(db: Session) -> None:
    """Sức chứa theo loại xe lấy từ bảng vehicle_types (admin chỉnh trên giao diện)."""
    caps = {vt.code: vt.capacity for vt in db.query(VehicleType).filter(VehicleType.is_active.is_(True)) if vt.capacity}
    _flow_counter.capacity_by_type = caps or config.get("capacity", {})


def _plate_distance(a: str, b: str) -> int:
    """Số ký tự khác nhau (Levenshtein) giữa 2 biển số, bỏ qua ký tự phân cách."""
    a, b = "".join(c for c in a.upper() if c.isalnum()), "".join(c for c in b.upper() if c.isalnum())
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


_last_scan: dict[str, tuple[float, CardScanOut]] = {}  # chống quẹt trùng: thẻ -> (thời điểm, kết quả)


def _broadcast_event(background: BackgroundTasks, **data) -> None:
    background.add_task(events.broadcast, {**data, "at": dt.datetime.utcnow().isoformat()})


def _extract_face_embedding(frame: np.ndarray, face_cfg: dict) -> list[float] | None:
    """Không bao giờ raise ra ngoài — lỗi model/khuôn mặt chỉ nên tạo cảnh báo,
    tuyệt đối không được làm hỏng luồng quẹt thẻ/mở barie chính (xem chú thích
    "face_verification" trong app/settings.py)."""
    try:
        return face_verify.extract_embedding(
            frame, model_name=face_cfg["model_name"], det_size=face_cfg["det_size"],
        )
    except Exception:
        logger.exception("Lỗi xác thực khuôn mặt (bỏ qua, không chặn giao dịch)")
        return None


def _face_verify_on_entry(session: VehicleSession, frame: np.ndarray | None, face_cfg: dict, messages: list[str]) -> None:
    if not face_cfg["enabled"] or frame is None:
        return
    embedding = _extract_face_embedding(frame, face_cfg)
    if embedding is None:
        messages.append("Không nhận diện được khuôn mặt lúc vào — bỏ qua xác thực khuôn mặt")
        return
    session.face_embedding_in = face_verify.encode_embedding(embedding)


def _face_verify_on_exit(session: VehicleSession, frame: np.ndarray | None, face_cfg: dict, messages: list[str]) -> None:
    if not face_cfg["enabled"] or frame is None or not session.face_embedding_in:
        return
    embedding = _extract_face_embedding(frame, face_cfg)
    if embedding is None:
        messages.append("Không nhận diện được khuôn mặt lúc ra — bỏ qua xác thực khuôn mặt")
        return
    cmp = face_verify.compare_embeddings(
        face_verify.decode_embedding(session.face_embedding_in), embedding, threshold=face_cfg["threshold"],
    )
    if not cmp.is_match:
        messages.append(f"Cảnh báo: khuôn mặt lúc ra không khớp lúc vào (score={cmp.score:.2f}) — kiểm tra thủ công")


@app.post("/card/scan", response_model=CardScanOut)
def card_scan(payload: CardScanIn, background: BackgroundTasks, who: User | None = Depends(user_or_agent),
              db: Session = Depends(get_db)) -> CardScanOut:
    """Quét thẻ: do bảo vệ đã đăng nhập (web) hoặc Windows hardware agent (header
    X-Agent-Key) gọi. Server tra thẻ trong DB (loại thẻ, thẻ tháng còn hạn, thẻ bị khoá),
    quyết định xe vào hay ra, chạy ALPR nếu loại thẻ bật LPR, tính phí theo biểu phí,
    ghi DB gắn với CA ĐANG MỞ, trả về barrier_id cần mở, VÀ xếp lệnh mở vào hàng đợi
    cho Windows hardware agent (dù lượt quét này do web hay chính agent gọi — xem
    `_pending_open`), rồi báo realtime cho mọi trang web đang mở qua WebSocket.

    Agent không phải người nên gắn vào ca đang mở gần nhất; chưa có bảo vệ nào
    đăng nhập (không có ca mở) thì từ chối, barie không mở."""
    if who is not None:
        work_shift = auth.open_work_shift(db, who)
    else:
        work_shift = db.query(WorkShift).filter(WorkShift.status == "open").order_by(WorkShift.started_at.desc()).first()
        if work_shift is None:
            raise HTTPException(409, "Chưa có bảo vệ nào đăng nhập/mở ca — không thể quét thẻ")

    general = app_settings.get_section(db, "general")
    now = time.monotonic()
    cached = _last_scan.get(payload.card_number)
    if cached and now - cached[0] < general["duplicate_swipe_seconds"]:
        return cached[1]

    card = db.query(Card).filter(Card.card_number == payload.card_number).first()
    if card is None:
        if not general["allow_unregistered_cards"]:
            raise HTTPException(404, "Thẻ chưa được đăng ký trong hệ thống")
        vehicle_type = payload.vehicle_type or "XeMay"
    else:
        if card.status != "active":
            raise HTTPException(403, "Thẻ đang bị khoá")
        vehicle_type = card.vehicle_type_code
    vt = db.query(VehicleType).filter(VehicleType.code == vehicle_type).first()
    if vt is not None and not vt.is_active:
        raise HTTPException(403, f"Loại thẻ {vt.display_name} đang ngừng sử dụng")

    messages: list[str] = []
    monthly = bool(vt and vt.is_monthly_pass)
    if monthly and card is not None:
        today = (dt.datetime.utcnow() + dt.timedelta(hours=config.get("timezone_offset_hours", 7))).date()
        if card.expire_date is None or card.expire_date < today:
            raise HTTPException(403, "Vé tháng đã hết hạn — cần gia hạn")
        if card.remaining_uses is not None and card.remaining_uses <= 0:
            raise HTTPException(403, "Vé đã hết số lượt")
        days_left = (card.expire_date - today).days
        if days_left <= vt.expiry_warning_days:
            messages.append(f"Vé tháng còn {days_left} ngày")

    open_session = (
        db.query(VehicleSession)
        .filter(VehicleSession.card_number == payload.card_number, VehicleSession.status == "open")
        .first()
    )
    is_entry = open_session is None
    use_lpr = (vt.lpr_in_enabled if is_entry else vt.lpr_out_enabled) if vt else True
    face_cfg = app_settings.get_section(db, "face_verification")

    reading = None
    frame = None
    if use_lpr or face_cfg["enabled"]:
        cam = _gate_camera_for(is_entry)
        frame = cam.read() if cam else None
    if use_lpr:
        readings = _pipeline.read(frame) if frame is not None else []
        reading = readings[0] if readings else None
    if reading is None:
        reading = PlateReading(
            text="", confidence=0.0,
            detection=PlateDetection(bbox_xyxy=(0, 0, 0, 0), confidence=0.0, corners=np.zeros((4, 2))),
        )
    barrier_id = (vt.barrier_in_id if is_entry else vt.barrier_out_id) if vt else "1"

    if is_entry:
        if reading.text and general["check_plate_duplication"] and db.query(VehicleSession).filter(
                VehicleSession.status == "open", VehicleSession.plate_in == reading.text).first():
            messages.append(f"Cảnh báo: biển số {reading.text} đang có trong bãi")
        session = VehicleSession(card_number=payload.card_number, vehicle_type_code=vehicle_type,
                                  plate_in=reading.text or None, plate_in_confidence=reading.confidence,
                                  status="open", work_shift_id=work_shift.id)
        _face_verify_on_entry(session, frame, face_cfg, messages)
        db.add(session)
        if card is not None and card.remaining_uses is not None:
            card.remaining_uses -= 1
        db.commit()
        _flow_counter.record_entry(vehicle_type)
        out = CardScanOut(action="entry", barrier_id=barrier_id, plate_text=reading.text,
                          plate_confidence=reading.confidence)
        _queue_open(barrier_id)
        _broadcast_event(background, type="entry", vehicle_type=vehicle_type, plate=reading.text,
                         card_number=payload.card_number)
    else:
        if use_lpr and reading.text and open_session.plate_in and \
                _plate_distance(reading.text, open_session.plate_in) > general["lpr_tolerance"]:
            messages.append(f"Biển số ra ({reading.text}) KHÁC biển số vào ({open_session.plate_in}) — kiểm tra thủ công")
        _face_verify_on_exit(open_session, frame, face_cfg, messages)
        session_manager = VehicleSessionManager(db, _flow_counter, fee_schedule=config.get("fee_schedule", {}))
        transaction = session_manager.handle_exit(open_session, reading, work_shift_id=work_shift.id,
                                                  amount_override=0 if monthly else None)
        out = CardScanOut(action="exit", barrier_id=barrier_id, plate_text=reading.text,
                          plate_confidence=reading.confidence, amount=transaction.amount)
        _queue_open(barrier_id)
        _broadcast_event(background, type="exit", vehicle_type=vehicle_type, plate=reading.text,
                         card_number=payload.card_number, amount=transaction.amount)
    out.message = "; ".join(messages) or None
    _last_scan[payload.card_number] = (now, out)
    return out


# ---- Khách lẻ không có thẻ (mở barie cho khách vào) ------------------------

class VisitorEntryIn(BaseModel):
    vehicle_type: str = "XeMay"


class VisitorEntryOut(BaseModel):
    session_id: int
    barrier_id: str
    plate_text: str
    plate_confidence: float
    message: str | None = None


def _read_gate_frame_and_plate(is_entry: bool = True) -> tuple[np.ndarray | None, PlateReading]:
    cam = _gate_camera_for(is_entry)
    frame = cam.read() if cam else None
    readings = _pipeline.read(frame) if frame is not None else []
    reading = readings[0] if readings else PlateReading(
        text="", confidence=0.0,
        detection=PlateDetection(bbox_xyxy=(0, 0, 0, 0), confidence=0.0, corners=np.zeros((4, 2))),
    )
    return frame, reading


@app.post("/visitor/entry", response_model=VisitorEntryOut)
def visitor_entry(payload: VisitorEntryIn, background: BackgroundTasks,
                  user: User = Depends(current_user), db: Session = Depends(get_db)) -> VisitorEntryOut:
    """Khách không có thẻ (vd người lạ ghé thăm cư dân) — bảo vệ bấm nút này trên
    web để mở barie cho vào ngay, không cần tạo thẻ trước. Vẫn ghi DB để tính đúng
    số xe tồn và thu phí lúc ra — đúng yêu cầu "web gửi tín hiệu mở barie cho khách"."""
    work_shift = auth.open_work_shift(db, user)
    vt = db.query(VehicleType).filter(VehicleType.code == payload.vehicle_type).first()
    face_cfg = app_settings.get_section(db, "face_verification")
    frame, reading = _read_gate_frame_and_plate()
    barrier_id = vt.barrier_in_id if vt else "1"
    messages: list[str] = []
    session = VehicleSession(card_number=None, vehicle_type_code=payload.vehicle_type,
                             plate_in=reading.text or None, plate_in_confidence=reading.confidence,
                             status="open", work_shift_id=work_shift.id)
    _face_verify_on_entry(session, frame, face_cfg, messages)
    db.add(session)
    db.commit()
    _flow_counter.record_entry(payload.vehicle_type)
    _queue_open(barrier_id)
    _broadcast_event(background, type="entry", vehicle_type=payload.vehicle_type,
                     plate=reading.text, card_number=None)
    return VisitorEntryOut(session_id=session.id, barrier_id=barrier_id,
                           plate_text=reading.text, plate_confidence=reading.confidence,
                           message="; ".join(messages) or None)


@app.get("/visitor/open")
def visitors_open(_: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    """Khách (không thẻ) còn trong bãi — để bảo vệ chọn đúng người khi cho ra."""
    rows = (db.query(VehicleSession)
           .filter(VehicleSession.card_number.is_(None), VehicleSession.status == "open")
           .order_by(VehicleSession.time_in).all())
    return [{"session_id": r.id, "vehicle_type": r.vehicle_type_code,
            "plate_in": r.plate_in, "time_in": r.time_in.isoformat()} for r in rows]


class VisitorExitOut(BaseModel):
    barrier_id: str
    plate_text: str
    amount: int
    message: str | None = None


@app.post("/visitor/{session_id}/exit", response_model=VisitorExitOut)
def visitor_exit(session_id: int, background: BackgroundTasks,
                 user: User = Depends(current_user), db: Session = Depends(get_db)) -> VisitorExitOut:
    session = db.get(VehicleSession, session_id)
    if session is None or session.status != "open" or session.card_number is not None:
        raise HTTPException(404, "Không tìm thấy khách đang trong bãi với mã này")
    work_shift = auth.open_work_shift(db, user)
    vt = db.query(VehicleType).filter(VehicleType.code == session.vehicle_type_code).first()
    face_cfg = app_settings.get_section(db, "face_verification")
    frame, reading = _read_gate_frame_and_plate(is_entry=False)
    barrier_id = vt.barrier_out_id if vt else "1"
    messages: list[str] = []
    _face_verify_on_exit(session, frame, face_cfg, messages)
    session_manager = VehicleSessionManager(db, _flow_counter, fee_schedule=config.get("fee_schedule", {}))
    transaction = session_manager.handle_exit(session, reading, work_shift_id=work_shift.id)
    _queue_open(barrier_id)
    _broadcast_event(background, type="exit", vehicle_type=session.vehicle_type_code,
                     plate=reading.text, card_number=None, amount=transaction.amount)
    return VisitorExitOut(barrier_id=barrier_id, plate_text=reading.text, amount=transaction.amount,
                          message="; ".join(messages) or None)


# ---- Hàng đợi lệnh barie cho agent + feed realtime --------------------------

@app.get("/barrier/{barrier_id}/pending-open", dependencies=[Depends(require_agent)])
def barrier_pending_open(barrier_id: str) -> dict:
    """scripts/windows_hardware_agent.py vòng lặp hỏi liên tục (không chỉ lúc tự
    nó quét thẻ) — để cũng mở được barie khi lượt quét xảy ra TỪ WEB (bảo vệ dùng
    trình duyệt), vì chỉ agent có quyền truy cập cổng COM vật lý."""
    with _pending_lock:
        pending = _pending_open.pop(barrier_id, False)
    return {"open": pending}


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket, token: str | None = Query(default=None),
                    db: Session = Depends(auth.get_db)) -> None:
    """Đẩy realtime biển số xe vào/ra cho trang web — browser không gửi được header
    tuỳ ý lúc mở WebSocket nên xác thực bằng token trên query string."""
    if auth.user_from_token(db, token) is None:
        await ws.close(code=4401)
        return
    await events.connect(ws)
    try:
        while True:
            await ws.receive_text()  # không dùng tới, chỉ để phát hiện client đóng kết nối
    except WebSocketDisconnect:
        pass
    finally:
        events.disconnect(ws)


# ---- Đăng nhập / ca làm việc ----------------------------------------------

class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
def login(payload: LoginIn, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.username == payload.username).first()
    # Luôn verify (kể cả khi user không tồn tại) để thời gian phản hồi không lộ username.
    ok = auth.verify_password(payload.password, user.password_hash if user else "scrypt$00$00")
    if not (user and ok and user.is_active):
        raise HTTPException(401, "Sai tên đăng nhập hoặc mật khẩu")
    shift_id = auth.open_work_shift(db, user).id if user.role == ROLE_GUARD else None
    return {"token": auth.create_token(db, user), "role": user.role,
            "full_name": user.full_name, "shift_id": shift_id}


@app.post("/auth/logout")
def logout(authorization: str | None = Header(default=None),
           user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Chỉ thu hồi token. Ca vẫn mở cho tới khi bấm "Kết ca" (/shift/close)."""
    auth.revoke_token(db, authorization[7:].strip())
    return {"ok": True}


@app.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"id": user.id, "username": user.username, "full_name": user.full_name, "role": user.role}


def _own_open_shift(db: Session, user: User) -> WorkShift:
    ws = db.query(WorkShift).filter(WorkShift.user_id == user.id, WorkShift.status == "open").first()
    if ws is None:
        raise HTTPException(404, "Bạn chưa có ca đang mở")
    return ws


@app.get("/shift/current")
def shift_current(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Thống kê ca hiện tại: xe vào/ra, xe tồn, tiền thu."""
    return shift_stats(db, _own_open_shift(db, user))


@app.post("/shift/close")
def shift_close(background: BackgroundTasks, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> dict:
    """Kết ca, rồi tự gửi PDF báo cáo cho quản lý qua email (nếu đã cấu hình).
    Gửi mail chạy nền: SMTP chậm/lỗi không làm treo hay làm hỏng việc kết ca."""
    ws = _own_open_shift(db, user)
    ws.status = "closed"
    ws.ended_at = dt.datetime.utcnow()
    db.commit()
    stats = shift_stats(db, ws)
    email_cfg = app_settings.get_section(db, "email")
    stats["email_queued"] = email_enabled(email_cfg)
    if stats["email_queued"]:
        background.add_task(
            send_shift_report, email_cfg,
            subject=f"[Bãi xe] Báo cáo ca #{ws.id} - {user.full_name}",
            body=(f"Nhân viên: {user.full_name}\nCa: {fmt_dt(ws.started_at)} - {fmt_dt(ws.ended_at)}\n"
                  f"Xe vào: {stats['vehicles_in']}, xe ra: {stats['vehicles_out']}, "
                  f"còn tồn: {stats['vehicles_remaining']}\nTiền thu: {fmt_money(stats['total_amount'])}\n\n"
                  "Chi tiết xem file PDF đính kèm."),
            pdf=build_shift_pdf(db, ws), filename=f"bao-cao-ca-{ws.id}.pdf")
    return stats


@app.get("/shift/{shift_id}/report.pdf")
def shift_report(shift_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    """Bảo vệ chỉ xuất được báo cáo ca CỦA MÌNH; admin xuất được mọi ca."""
    ws = db.get(WorkShift, shift_id)
    if ws is None or (user.role != ROLE_ADMIN and ws.user_id != user.id):
        raise HTTPException(404, "Không tìm thấy ca")
    return Response(build_shift_pdf(db, ws), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="bao-cao-ca-{ws.id}.pdf"'})


# ---- Quản trị (chỉ admin) --------------------------------------------------

class UserCreateIn(BaseModel):
    username: str
    password: str
    full_name: str
    role: str = ROLE_GUARD


class UserUpdateIn(BaseModel):
    password: str | None = None
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


def _user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role, "is_active": u.is_active}


@app.get("/admin/users")
def admin_users(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    return [_user_out(u) for u in db.query(User).order_by(User.id)]


@app.post("/admin/users", status_code=201)
def admin_create_user(payload: UserCreateIn, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(409, "Tên đăng nhập đã tồn tại")
    try:
        return _user_out(auth.create_user(db, payload.username, payload.password, payload.full_name, payload.role))
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.patch("/admin/users/{user_id}")
def admin_update_user(user_id: int, payload: UserUpdateIn, admin: User = Depends(require_admin),
                      db: Session = Depends(get_db)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    if user.id == admin.id and (payload.is_active is False or (payload.role and payload.role != ROLE_ADMIN)):
        raise HTTPException(400, "Không thể tự khoá hoặc hạ quyền chính mình")
    if payload.role is not None:
        if payload.role not in (ROLE_ADMIN, ROLE_GUARD):
            raise HTTPException(422, "role không hợp lệ")
        user.role = payload.role
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        if len(payload.password) < 8:
            raise HTTPException(422, "Mật khẩu phải có ít nhất 8 ký tự")
        user.password_hash = auth.hash_password(payload.password)
    if payload.password is not None or payload.is_active is False:
        db.query(AuthToken).filter(AuthToken.user_id == user.id).delete()  # buộc đăng nhập lại
    db.commit()
    return _user_out(user)


@app.get("/admin/shifts")
def admin_shifts(limit: int = 50, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(WorkShift, User).join(User, User.id == WorkShift.user_id) \
        .order_by(WorkShift.started_at.desc()).limit(min(limit, 200)).all()
    return [{**shift_stats(db, ws), "guard": u.full_name, "username": u.username} for ws, u in rows]


from app.api.admin import router as admin_router  # noqa: E402

app.include_router(admin_router)


# ---- Giao diện web ---------------------------------------------------------
# Để riêng ngoài app/ (thư mục web/ ở gốc project) cho dễ quản lý/chỉnh sửa
# độc lập với code backend — xem web/index.html.

_WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"


@app.get("/", include_in_schema=False)
def web_ui() -> FileResponse:
    return FileResponse(_WEB_DIR / "index.html")
