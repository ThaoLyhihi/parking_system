"""Đọc luồng camera (RTSP/file/webcam) bằng OpenCV.

Phần mềm cũ (xem giuxe/giuxe1/Debug_MSSQL/Debug/cameras.config) dùng AForge.NET +
FFmpeg + VLC bindings để đọc RTSP, và đăng ký "nhiều camera" thực chất là cùng
một luồng RTSP hiển thị ở các mức zoom khác nhau (1x/2x/4x/8x). Ở đây dùng
OpenCV (đã có binding FFmpeg sẵn bên trong) để làm điều tương đương bằng
Python, không cần các DLL .NET cũ.

Thread riêng để đọc frame liên tục (tránh buffer RTSP bị đầy/trễ khi vòng xử
lý AI chạy chậm hơn tốc độ camera gửi khung hình) — đây là vấn đề thực tế rất
thường gặp khi đọc RTSP bằng OpenCV, không phải suy đoán.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

# Tương đương probSize="50000" trong cameras.config của phần mềm cũ: FFmpeg phân tích
# luồng ít hơn -> kết nối RTSP nhanh, ít trễ. Phải đặt TRƯỚC khi tạo VideoCapture đầu tiên;
# setdefault để người dùng vẫn ghi đè được bằng biến môi trường.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|probesize;50000|analyzeduration;0|fflags;nobuffer",
)

import cv2
import numpy as np


@dataclass
class CameraSpec:
    name: str
    source: str | int  # URL rtsp://..., đường dẫn file, hoặc index webcam (vd 0)


class CameraStream:
    """Đọc 1 luồng camera trong thread riêng, luôn giữ frame mới nhất."""

    def __init__(self, spec: CameraSpec, reconnect_delay: float = 2.0, max_fps: float = 15.0):
        self.spec = spec
        self._reconnect_delay = reconnect_delay
        # Chỉ giải mã/chuyển màu tối đa max_fps khung/giây; các khung thừa chỉ bị grab() bỏ đi
        # (vẫn phải đọc để buffer RTSP không đầy) -> giảm CPU mà vẫn luôn có khung mới nhất.
        self._min_interval = 1.0 / max_fps if max_fps > 0 else 0.0
        self._last_retrieve = 0.0
        self._seq = 0
        self._cap: cv2.VideoCapture | None = None
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> "CameraStream":
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._cap is not None:
            self._cap.release()

    def _open(self) -> bool:
        source = self.spec.source
        # Cho phép dùng chỉ số webcam (int) khi test local, URL/path (str) khi thật.
        self._cap = cv2.VideoCapture(source)
        if self._cap is not None:
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # giữ độ trễ thấp, không xếp hàng khung cũ
        return bool(self._cap and self._cap.isOpened())

    def _loop(self) -> None:
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                if not self._open():
                    time.sleep(self._reconnect_delay)
                    continue
            ok = self._cap.grab()
            frame = None
            if ok:
                now = time.monotonic()
                if now - self._last_retrieve < self._min_interval:
                    continue
                self._last_retrieve = now
                ok, frame = self._cap.retrieve()
            if not ok:
                # Mất kết nối giữa chừng (rất thường gặp với RTSP) -> fail-safe:
                # không giữ frame cũ vô hạn, để lớp gọi (ví dụ barrier safety)
                # biết là đang mất tín hiệu camera (mục 6.6 thuyết minh đề tài).
                with self._lock:
                    self._frame = None
                self._cap.release()
                self._cap = None
                time.sleep(self._reconnect_delay)
                continue
            with self._lock:
                self._frame = frame
                self._seq += 1

    @property
    def frame_seq(self) -> int:
        """Tăng mỗi khi có khung mới — để bên xử lý bỏ qua khung đã xử lý rồi."""
        return self._seq

    def read(self) -> np.ndarray | None:
        """Trả về frame mới nhất, hoặc None nếu đang mất kết nối camera."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    @property
    def is_connected(self) -> bool:
        return self._frame is not None


def crop_zoom(frame: np.ndarray, zoom: float) -> np.ndarray:
    """Crop phần giữa khung hình theo hệ số zoom, mô phỏng lại 4 "camera ảo"
    (1x/2x/4x/8x) của phần mềm cũ từ CÙNG một luồng RTSP vật lý."""
    if zoom <= 1.0:
        return frame
    h, w = frame.shape[:2]
    new_w, new_h = int(w / zoom), int(h / zoom)
    x0 = (w - new_w) // 2
    y0 = (h - new_h) // 2
    cropped = frame[y0 : y0 + new_h, x0 : x0 + new_w]
    return cv2.resize(cropped, (w, h))


def center_crop(frame: np.ndarray, zoom: float, cx: float = 0.5, cy: float = 0.5) -> np.ndarray:
    """Cắt vùng zoom quanh tâm (cx, cy) (toạ độ 0-1 trên khung gốc, 0.5/0.5 = giữa khung),
    KHÔNG resize lại và không copy (trả view). Vùng cắt luôn nằm trọn trong khung nên tâm
    sát mép sẽ tự bị đẩy vào. Dùng cho ảnh xem trực tiếp; khung gốc đưa cho AI không bị đụng tới."""
    if zoom <= 1.0:
        return frame
    h, w = frame.shape[:2]
    new_w, new_h = max(1, int(w / zoom)), max(1, int(h / zoom))
    x0 = min(max(int(cx * w) - new_w // 2, 0), w - new_w)
    y0 = min(max(int(cy * h) - new_h // 2, 0), h - new_h)
    return frame[y0 : y0 + new_h, x0 : x0 + new_w]
