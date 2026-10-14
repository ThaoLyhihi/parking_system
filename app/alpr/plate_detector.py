"""Chạy inference model phát hiện biển số (models/licenseplate/detect.onnx).

Đã kiểm tra trực tiếp bằng onnxruntime (không suy đoán): đây là model
**YOLOv8n-pose** (Ultralytics), KHÔNG phải model detection thường:
- input "images": [1, 3, 896, 896] float
- output "output0": [1, 17, 16464] — 17 = 4 (box cx,cy,w,h) + 1 (confidence)
  + 4 keypoint x (x, y, visibility) — 4 keypoint chính là **4 góc của biển số**,
  dùng để chỉnh phẳng ảnh biển số (perspective rectify) trước khi OCR, xem
  plate_rectify.py.
- custom_metadata: names={0: 'Bienso'}, nms=False -> model trả kết quả thô,
  phải tự làm NMS (đã cài đặt dưới đây), không gọi NMS có sẵn trong model.

Thứ tự 4 keypoint theo đúng thứ tự lúc gán nhãn khi huấn luyện model này
(không có trong metadata ONNX) — mặc định coi là
[top-left, top-right, bottom-right, bottom-left]. Cần xác minh lại bằng
scripts/test_alpr_on_image.py trên ảnh thật trước khi dùng cho production;
nếu thứ tự sai, ảnh sau rectify sẽ bị lật/xoay sai, sẽ thấy ngay khi xem ảnh
debug mà script đó lưu ra.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import onnxruntime as ort


@dataclass
class PlateDetection:
    bbox_xyxy: tuple[float, float, float, float]
    confidence: float
    corners: np.ndarray  # shape (4, 2), toạ độ (x, y) trên ảnh gốc


class PlateDetector:
    def __init__(self, model_path: str, input_size: int = 896,
                 conf_threshold: float = 0.4, iou_threshold: float = 0.45):
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._input_name = self.session.get_inputs()[0].name

    def _letterbox(self, image: np.ndarray) -> tuple[np.ndarray, float, tuple[int, int]]:
        h, w = image.shape[:2]
        scale = min(self.input_size / h, self.input_size / w)
        new_h, new_w = int(round(h * scale)), int(round(w * scale))
        resized = cv2.resize(image, (new_w, new_h))
        pad_h, pad_w = self.input_size - new_h, self.input_size - new_w
        top, left = pad_h // 2, pad_w // 2
        padded = cv2.copyMakeBorder(
            resized, top, pad_h - top, left, pad_w - left,
            cv2.BORDER_CONSTANT, value=(114, 114, 114),
        )
        return padded, scale, (left, top)

    def _preprocess(self, image: np.ndarray) -> tuple[np.ndarray, float, tuple[int, int]]:
        padded, scale, pad = self._letterbox(image)
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        chw = rgb.transpose(2, 0, 1).astype(np.float32) / 255.0
        return chw[None, ...], scale, pad

    def detect(self, image: np.ndarray) -> list[PlateDetection]:
        tensor, scale, (pad_x, pad_y) = self._preprocess(image)
        (output0,) = self.session.run(None, {self._input_name: tensor})
        preds = output0[0].transpose(1, 0)  # (16464, 17)

        boxes_cxcywh = preds[:, :4]
        scores = preds[:, 4]
        keypoints = preds[:, 5:].reshape(-1, 4, 3)  # (N, 4, [x, y, vis])

        keep = scores > self.conf_threshold
        if not np.any(keep):
            return []
        boxes_cxcywh, scores, keypoints = boxes_cxcywh[keep], scores[keep], keypoints[keep]

        # cx,cy,w,h -> x,y,w,h (góc trên-trái) để dùng với cv2.dnn.NMSBoxes
        xywh = np.column_stack([
            boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2,
            boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2,
            boxes_cxcywh[:, 2],
            boxes_cxcywh[:, 3],
        ])
        indices = cv2.dnn.NMSBoxes(
            xywh.tolist(), scores.tolist(), self.conf_threshold, self.iou_threshold
        )
        if len(indices) == 0:
            return []
        indices = np.array(indices).flatten()

        detections: list[PlateDetection] = []
        for i in indices:
            x, y, w, h = xywh[i]
            x1, y1, x2, y2 = x, y, x + w, y + h
            # Bỏ padding + chia lại theo scale để ra toạ độ trên ảnh GỐC.
            x1, x2 = (x1 - pad_x) / scale, (x2 - pad_x) / scale
            y1, y2 = (y1 - pad_y) / scale, (y2 - pad_y) / scale

            corners = keypoints[i][:, :2].copy()
            corners[:, 0] = (corners[:, 0] - pad_x) / scale
            corners[:, 1] = (corners[:, 1] - pad_y) / scale

            detections.append(
                PlateDetection(
                    bbox_xyxy=(float(x1), float(y1), float(x2), float(y2)),
                    confidence=float(scores[i]),
                    corners=corners,
                )
            )
        return detections
