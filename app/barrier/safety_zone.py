"""Module an toàn barie — thay thế HOÀN TOÀN cảm biến vật lý.

Bạn đã xác nhận: barie thật không có cảm biến vòng từ/quang điện nào — phần
mềm (giờ là AI) đảm nhiệm toàn bộ việc phát hiện vật cản. Vì đây là lớp an
toàn duy nhất (không có hardware fail-safe dự phòng), mục README của project
này nhắc lại khuyến nghị: nên cân nhắc lắp thêm 1 cảm biến vật lý rẻ tiền làm
lớp dự phòng độc lập trước khi để AI tự ra quyết định đóng barie không giám
sát — xem mục 6.6 thuyết minh đề tài.

Thuật toán ở đây dùng frame-differencing (phát hiện chuyển động) làm mặc định
vì rẻ, nhanh, không cần model — đúng tinh thần "Hướng đơn giản" nêu trong
thuyết minh (mục 6.3: "phát hiện chuyển động... không cần model AI"). Có thể
nâng cấp lên object detection (YOLO person/vehicle) sau khi có số liệu thực
nghiệm cho thấy cần độ chính xác cao hơn.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class SafetyZoneConfig:
    roi_polygon: list[tuple[float, float]]  # toạ độ tỉ lệ (0-1), theo (x, y)
    clear_frames_required: int = 8
    motion_threshold: int = 25


class BarrierSafetyZone:
    """Theo dõi 1 vùng ROI quanh barie, trả lời câu hỏi duy nhất mà cảm biến
    vật lý (nếu có) sẽ trả lời: "có vật cản trong vùng quét của cần barie
    ngay bây giờ không?"."""

    def __init__(self, config: SafetyZoneConfig):
        self.config = config
        self._prev_gray: np.ndarray | None = None
        self._consecutive_clear_frames = 0

    def _roi_mask(self, shape: tuple[int, int]) -> np.ndarray:
        h, w = shape
        pts = np.array(
            [[int(x * w), int(y * h)] for x, y in self.config.roi_polygon],
            dtype=np.int32,
        )
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [pts], 255)
        return mask

    def update(self, frame: np.ndarray | None) -> bool:
        """Gọi mỗi khung hình camera barie. Trả về True nếu đủ điều kiện an
        toàn để CHO PHÉP đóng barie (ROI trống liên tục đủ số khung hình cấu
        hình), False nếu còn vật cản HOẶC mất tín hiệu camera.

        Mất camera luôn trả về False (fail-safe: không cho đóng khi không
        chắc chắn) — xem mục 6.6 thuyết minh đề tài, kịch bản "camera hỏng".
        """
        if frame is None:
            self._consecutive_clear_frames = 0
            return False

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        mask = self._roi_mask(gray.shape)

        if self._prev_gray is None:
            self._prev_gray = gray
            self._consecutive_clear_frames = 0
            return False

        diff = cv2.absdiff(gray, self._prev_gray)
        diff = cv2.bitwise_and(diff, diff, mask=mask)
        self._prev_gray = gray

        motion_pixels = int(np.count_nonzero(diff > self.config.motion_threshold))
        roi_has_motion = motion_pixels > 0

        if roi_has_motion:
            self._consecutive_clear_frames = 0
            return False

        self._consecutive_clear_frames += 1
        return self._consecutive_clear_frames >= self.config.clear_frames_required
