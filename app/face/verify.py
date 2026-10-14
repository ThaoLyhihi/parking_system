"""Xác thực khuôn mặt 1:1 dựa trên InsightFace (buffalo_s), tách từ SDK vendor
(giuxe/giuxe1/model/face-recognition-main/fr_sdk) thành 2 bước extract/compare
riêng — để lưu embedding lúc xe VÀO một lần rồi so khớp lúc xe RA, không cần
giữ/đọc lại ảnh vào. Chỉ dùng khi cài đặt "face_verification.enabled" = true
(xem app/settings.py) — tắt theo mặc định. Model nằm sẵn trong models/insightface
nên chạy offline; thiếu thư mục đó thì insightface mới tự tải về ~/.insightface.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

_APP_CACHE: dict[tuple[str, tuple[str, ...], int], Any] = {}


def _bundled_root(model_name: str) -> str | None:
    """Thư mục models/insightface đi kèm dự án/bản đóng gói (chứa models/<tên>/*.onnx) -> chạy OFFLINE hoàn toàn,
    không phải tải từ Internet. Không có thì trả None để insightface dùng ~/.insightface (tự tải lần đầu)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    root = base / "models" / "insightface"
    return str(root) if any((root / "models" / model_name).glob("*.onnx")) else None


def _get_face_app(model_name: str, providers: Sequence[str] | None, det_size: int):
    from insightface.app import FaceAnalysis

    providers = tuple(providers) if providers else ("CPUExecutionProvider",)
    key = (model_name, providers, det_size)
    if key not in _APP_CACHE:
        kwargs: dict[str, Any] = {}
        root = _bundled_root(model_name)
        if root:
            kwargs["root"] = root
        # Chỉ cần phát hiện + nhúng khuôn mặt (embedding); bỏ landmark 3D (143MB) và giới tính/tuổi.
        app = FaceAnalysis(name=model_name, providers=list(providers),
                           allowed_modules=["detection", "recognition"], **kwargs)
        app.prepare(ctx_id=0, det_size=(det_size, det_size))
        _APP_CACHE[key] = app
    return _APP_CACHE[key]


def _largest_face(app, image_bgr: np.ndarray):
    faces = app.get(image_bgr)
    if not faces:
        return None
    return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))


def extract_embedding(
    image_bgr: np.ndarray,
    *,
    model_name: str = "buffalo_s",
    det_size: int = 320,
    providers: Sequence[str] | None = None,
) -> list[float] | None:
    """Trả về embedding (512 số thực) của khuôn mặt lớn nhất trong ảnh, hoặc
    None nếu không phát hiện được khuôn mặt (không raise — gọi ở nơi không
    được chặn luồng quẹt thẻ chính, xem app/api/main.py)."""
    app = _get_face_app(model_name, providers, det_size)
    face = _largest_face(app, image_bgr)
    if face is None:
        return None
    return [float(x) for x in np.asarray(face.embedding, dtype=np.float32)]


def encode_embedding(embedding: Sequence[float]) -> str:
    return json.dumps([round(float(x), 6) for x in embedding])


def decode_embedding(data: str) -> list[float]:
    return json.loads(data)


@dataclass
class FaceCompareResult:
    is_match: bool
    score: float
    threshold: float


def compare_embeddings(a: Sequence[float], b: Sequence[float], threshold: float = 0.45) -> FaceCompareResult:
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    score = float(np.dot(va, vb) / ((np.linalg.norm(va) * np.linalg.norm(vb)) + 1e-12))
    return FaceCompareResult(is_match=score >= threshold, score=score, threshold=threshold)
