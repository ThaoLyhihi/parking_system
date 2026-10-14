"""Chỉnh phẳng (perspective rectify) ảnh biển số từ 4 điểm góc do PlateDetector trả về,
rồi tách dòng cho biển số xe máy 2 dòng — xem mục 6.2 thuyết minh đề tài về đặc thù
biển 1 dòng (ô tô) / 2 dòng (xe máy) của Việt Nam.
"""
from __future__ import annotations

import cv2
import numpy as np

# Biển 2 dòng thường có tỉ lệ dài/rộng ~1.0-1.8; biển 1 dòng ~3.5-5.
# Ngưỡng này là ước lượng ban đầu, CẦN hiệu chỉnh lại bằng dữ liệu thật thu thập
# được (mục 6.2 thuyết minh) trước khi dùng cho production.
TWO_LINE_ASPECT_RATIO_THRESHOLD = 2.2


def rectify_plate(image: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """corners: 4 điểm (x, y) theo thứ tự [top-left, top-right, bottom-right, bottom-left]
    (xem ghi chú về thứ tự keypoint trong plate_detector.py).
    Trả về ảnh biển số đã chỉnh phẳng thành hình chữ nhật.
    """
    tl, tr, br, bl = corners
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    width, height = max(width, 1), max(height, 1)

    dst = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(corners.astype(np.float32), dst)
    return cv2.warpPerspective(image, matrix, (width, height))


def split_lines_if_needed(rectified: np.ndarray) -> list[np.ndarray]:
    """Nếu ảnh biển số sau rectify có tỉ lệ dài/rộng nhỏ (gần vuông) -> coi là
    biển 2 dòng của xe máy, cắt làm 2 nửa trên/dưới để OCR riêng từng dòng.
    Biển 1 dòng (ô tô) trả về nguyên ảnh."""
    h, w = rectified.shape[:2]
    aspect_ratio = w / h if h else 0
    if aspect_ratio >= TWO_LINE_ASPECT_RATIO_THRESHOLD:
        return [rectified]
    mid = h // 2
    return [rectified[:mid, :], rectified[mid:, :]]
