"""Cài đặt chỉnh được từ giao diện admin. Giá trị trong DB (bảng settings) ghi đè
config.yaml; chưa có thì dùng config.yaml; chưa có nữa thì dùng default dưới đây.

SCHEMA mô tả từng mục để giao diện tự vẽ form (không phải viết HTML cho từng mục).
`restart: True` = cần khởi động lại AI service (hoặc hardware agent) mới có hiệu lực."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import config
from app.db.models import Setting

# type: int | float | bool | text | secret | list (nhập cách nhau dấu phẩy) | json | select
SCHEMA: dict[str, dict] = {
    "general": {
        "title": "Chung",
        "fields": [
            {"key": "allow_unregistered_cards", "label": "Cho phép thẻ chưa đăng ký (coi là thẻ lượt xe máy)", "type": "bool", "default": False},
            {"key": "duplicate_swipe_seconds", "label": "Bỏ qua quẹt trùng cùng thẻ trong (giây)", "type": "int", "default": 3},
            {"key": "lpr_tolerance", "label": "Số ký tự biển số được phép lệch khi đối chiếu vào/ra", "type": "int", "default": 0},
            {"key": "check_plate_duplication", "label": "Cảnh báo trùng biển số đang trong bãi", "type": "bool", "default": True},
        ],
    },
    "alpr": {
        "title": "Nhận diện biển số",
        "fields": [
            {"key": "conf_threshold", "label": "Ngưỡng tin cậy", "type": "float", "default": 0.4, "restart": True},
            {"key": "iou_threshold", "label": "Ngưỡng IoU (NMS)", "type": "float", "default": 0.45, "restart": True},
            {"key": "input_size", "label": "Kích thước input model", "type": "int", "default": 896, "restart": True},
        ],
    },
    "cameras": {
        "title": "Camera",
        "note": "Hỗ trợ 1 đến 4 camera — để trống camera nào không có, hệ thống vẫn chạy được "
                "với các camera còn lại (chỉ mất đúng chức năng gắn với camera còn thiếu, vd "
                "thiếu camera toàn cảnh thì không đếm được chỗ trống theo từng ô). Nếu bãi chỉ "
                "có 1 lối ra/vào chung, chỉ cần điền 'Camera cổng vào' và để trống 'Camera cổng "
                "ra' — hệ thống tự dùng lại camera cổng vào cho lượt xe ra. Dù dùng 1 hay nhiều "
                "camera, HỆ THỐNG CHỈ CẦN 1 ĐẦU ĐỌC THẺ DUY NHẤT cho cả quét vào và quét ra — "
                "server tự nhận biết vào/ra dựa trên thẻ đó hiện có đang mở phiên gửi xe hay "
                "không, không cần đầu đọc riêng cho mỗi chiều (xem mục 'Đầu đọc thẻ' bên dưới).",
        "fields": [
            {"key": "gate_in_source", "label": "Camera cổng vào (RTSP/đường dẫn/số webcam)", "type": "text", "default": "", "restart": True},
            {"key": "gate_out_source", "label": "Camera cổng ra (để trống = dùng chung camera cổng vào)", "type": "text", "default": "", "restart": True},
            {"key": "overview_source", "label": "Camera toàn cảnh (tuỳ chọn — đếm chỗ trống theo ô)", "type": "text", "default": "", "restart": True},
            {"key": "barrier_source", "label": "Camera barie (tuỳ chọn — lớp an toàn barie)", "type": "text", "default": "", "restart": True},
        ],
    },
    "barrier_safety": {
        "title": "An toàn barie",
        "fields": [
            {"key": "clear_frames_required", "label": "Số khung hình trống liên tiếp mới đóng barie", "type": "int", "default": 8, "restart": True},
            {"key": "motion_threshold", "label": "Ngưỡng chuyển động (0-255)", "type": "int", "default": 25, "restart": True},
            {"key": "roi_polygon", "label": "Vùng kiểm tra (ROI, JSON toạ độ 0-1)", "type": "json", "default": [[0.1, 0.5], [0.9, 0.5], [0.9, 1.0], [0.1, 1.0]], "restart": True},
        ],
    },
    "barrier_hardware": {
        "title": "Barie (COM/TCP)",
        "fields": [
            {"key": "type", "label": "Chế độ", "type": "select", "options": ["logging", "serial"], "default": "logging", "restart": True},
            {"key": "baudrate", "label": "Baudrate", "type": "int", "default": 9600, "restart": True},
            {"key": "barriers", "label": "Danh sách barie (JSON: id → port, open_command, close_command)", "type": "json", "default": {}, "restart": True},
        ],
    },
    "card_reader": {
        "title": "Đầu đọc thẻ",
        "note": "'windows_keyboard'/'usb_hid_linux' cho đầu đọc USB kiểu gõ ra như bàn phím. "
                "'serial' cho đầu đọc cắm qua cổng COM/RS232 (đúng kiểu phần mềm cũ dùng, cổng "
                "COM7...) — điền thêm 'Cổng COM' và 'Baudrate' bên dưới nếu chọn loại này.",
        "fields": [
            {"key": "type", "label": "Loại đầu đọc", "type": "select", "options": ["windows_keyboard", "usb_hid_linux", "serial", "simulated"], "default": "windows_keyboard", "restart": True},
            {"key": "device_name_contains", "label": "Tên thiết bị chứa (chỉ dùng cho usb_hid_linux)", "type": "text", "default": "RFID", "restart": True},
            {"key": "port", "label": "Cổng COM (chỉ dùng cho loại 'serial', vd COM7)", "type": "text", "default": "", "restart": True},
            {"key": "baudrate", "label": "Baudrate (chỉ dùng cho loại 'serial')", "type": "int", "default": 9600, "restart": True},
        ],
    },
    "face_verification": {
        "title": "Xác thực khuôn mặt (tuỳ chọn)",
        "note": "Đối chiếu khuôn mặt người quẹt thẻ lúc vào/ra, CHỈ để cảnh báo thêm cho bảo vệ "
                "(không chặn mở barie) — tương tự cảnh báo lệch biển số. TẮT theo mặc định. Model "
                "nhận diện khuôn mặt (buffalo_s) đã đi kèm sẵn trong phần mềm nên chạy hoàn toàn "
                "OFFLINE, không cần Internet.",
        "fields": [
            {"key": "enabled", "label": "Bật xác thực khuôn mặt", "type": "bool", "default": False, "restart": True},
            {"key": "model_name", "label": "Model InsightFace", "type": "text", "default": "buffalo_s", "restart": True},
            {"key": "threshold", "label": "Ngưỡng cosine similarity (0.35-0.55 theo khuyến nghị)", "type": "float", "default": 0.45},
            {"key": "det_size", "label": "Kích thước detector (px, vuông)", "type": "int", "default": 320, "restart": True},
        ],
    },
    "hardware_agent": {
        "title": "Hardware agent",
        "fields": [
            {"key": "poll_interval_seconds", "label": "Chu kỳ hỏi trạng thái barie (giây)", "type": "float", "default": 0.5, "restart": True},
        ],
    },
    "auth": {
        "title": "Đăng nhập",
        "fields": [
            {"key": "token_ttl_hours", "label": "Thời hạn phiên đăng nhập (giờ)", "type": "int", "default": 12, "restart": True},
        ],
    },
    "email": {
        "title": "Email báo cáo ca",
        "fields": [
            {"key": "enabled", "label": "Tự gửi báo cáo khi kết ca", "type": "bool", "default": False},
            {"key": "smtp_host", "label": "SMTP host", "type": "text", "default": ""},
            {"key": "smtp_port", "label": "SMTP port", "type": "int", "default": 587},
            {"key": "security", "label": "Bảo mật", "type": "select", "options": ["starttls", "ssl", "none"], "default": "starttls"},
            {"key": "username", "label": "Tài khoản SMTP", "type": "text", "default": ""},
            {"key": "password", "label": "Mật khẩu SMTP (để trống = giữ nguyên)", "type": "secret", "default": ""},
            {"key": "from", "label": "Địa chỉ gửi", "type": "text", "default": ""},
            {"key": "recipients", "label": "Người nhận (cách nhau dấu phẩy)", "type": "list", "default": []},
        ],
    },
}


def _stored(db: Session, section: str) -> dict:
    row = db.get(Setting, section)
    return json.loads(row.value_json) if row else {}


def get_section(db: Session, section: str) -> dict[str, Any]:
    """Giá trị hiệu lực của 1 mục: default < config.yaml < DB."""
    out: dict[str, Any] = {}
    stored = _stored(db, section)
    yaml_section = config.get(section, {}) or {}
    for f in SCHEMA[section]["fields"]:
        k = f["key"]
        # cameras trong yaml có dạng cameras.gate_in.source, khác tên khoá trong form
        if section == "cameras":
            yaml_val = config.get(f"cameras.{k.removesuffix('_source')}.source")
        else:
            yaml_val = yaml_section.get(k) if isinstance(yaml_section, dict) else None
        out[k] = stored[k] if k in stored else (yaml_val if yaml_val is not None else f["default"])
    return out


def get_value(db: Session, section: str, key: str) -> Any:
    return get_section(db, section)[key]


def coerce(field: dict, value: Any) -> Any:
    t = field["type"]
    if t == "int":
        return int(value)
    if t == "float":
        return float(value)
    if t == "bool":
        return bool(value)
    if t == "list":
        return [x.strip() for x in value.split(",") if x.strip()] if isinstance(value, str) else list(value)
    if t == "json":
        return json.loads(value) if isinstance(value, str) else value
    if t == "select":
        if value not in field["options"]:
            raise ValueError(f"{field['key']}: giá trị phải thuộc {field['options']}")
        return value
    return str(value)


def save_section(db: Session, section: str, values: dict[str, Any]) -> dict:
    fields = {f["key"]: f for f in SCHEMA[section]["fields"]}
    stored = _stored(db, section)
    for k, v in values.items():
        if k not in fields:
            raise ValueError(f"Khoá không hợp lệ: {k}")
        if fields[k]["type"] == "secret" and v in ("", None):
            continue  # để trống = giữ mật khẩu cũ
        stored[k] = coerce(fields[k], v)
    row = db.get(Setting, section)
    if row is None:
        db.add(Setting(section=section, value_json=json.dumps(stored, ensure_ascii=False)))
    else:
        row.value_json = json.dumps(stored, ensure_ascii=False)
    db.commit()
    return get_section(db, section)


def public_section(db: Session, section: str) -> dict:
    """Dạng trả về cho giao diện: ẩn giá trị secret."""
    vals = get_section(db, section)
    for f in SCHEMA[section]["fields"]:
        if f["type"] == "secret":
            vals[f["key"]] = ""
    return vals
