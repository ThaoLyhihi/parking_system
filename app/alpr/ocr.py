"""Nhận diện ký tự (OCR) trên ảnh dòng biển số đã cắt.

QUAN TRỌNG: huấn luyện/chọn OCR cho biển số Việt Nam (đặc biệt biển 2 dòng xe
máy) là một nội dung nghiên cứu CHƯA hoàn thành trong thuyết minh đề tài (mục
6.2: "khảo sát dataset công khai... quyết định có cần thu thập dataset riêng
cho biển 2 dòng"). Vì vậy module này chỉ định nghĩa INTERFACE để các bước sau
(detector, rectify, session_manager) có chỗ cắm vào, chứ không giả vờ đã có
OCR hoạt động — tránh báo cáo sai một việc chưa thực sự làm.

Cách cắm OCR thật khi có kết quả khảo sát mục 6.2:
- Nếu dùng EasyOCR/PaddleOCR có sẵn: viết 1 class kế thừa `PlateOCR`, gọi thư
  viện tương ứng trong `read_line()`.
- Nếu tự huấn luyện CRNN riêng cho ký tự biển số VN: load model trong
  `__init__`, decode trong `read_line()`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class PlateOCR(ABC):
    @abstractmethod
    def read_line(self, line_image: np.ndarray) -> tuple[str, float]:
        """Trả về (text, confidence) cho một dòng biển số đã cắt."""
        raise NotImplementedError


class NotImplementedOCR(PlateOCR):
    """Dùng tạm khi chưa cắm OCR thật — để toàn bộ pipeline (detect + rectify)
    vẫn chạy được và test được (xem scripts/test_alpr_on_image.py), chỉ phần
    đọc ký tự trả về rỗng thay vì crash, có log rõ ràng để không nhầm là đã
    hoạt động."""

    def read_line(self, line_image: np.ndarray) -> tuple[str, float]:
        return "", 0.0
