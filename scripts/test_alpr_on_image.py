"""Chạy thử model detect.onnx trên 1 ảnh thật — đúng khuyến nghị "Bước 1" trong
QUY_TRINH_LAM_LAI_PHAN_MEM.md (mục 6, việc #5): kiểm tra model trước khi tin
tưởng dùng cho production.

Dùng:
    python scripts/test_alpr_on_image.py duong/dan/anh.jpg

Lưu ảnh debug `*_debug.jpg` vẽ box + 4 góc biển số để bạn tự mắt kiểm tra xem
model có nhận diện đúng không, và để KIỂM TRA xem giả định thứ tự 4 góc
(top-left, top-right, bottom-right, bottom-left) trong plate_detector.py có
đúng không — nếu ảnh rectify (`*_rectified_N.jpg`) bị lật/xoay sai, cần sửa
lại thứ tự đó.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.alpr.plate_detector import PlateDetector  # noqa: E402
from app.alpr.plate_rectify import rectify_plate, split_lines_if_needed  # noqa: E402
from app.config import config  # noqa: E402


def main(image_path: str) -> None:
    image = cv2.imread(image_path)
    if image is None:
        raise SystemExit(f"Không đọc được ảnh: {image_path}")

    detector = PlateDetector(
        model_path=config.get("alpr.model_path", "models/licenseplate/detect.onnx"),
        input_size=config.get("alpr.input_size", 896),
        conf_threshold=config.get("alpr.conf_threshold", 0.4),
        iou_threshold=config.get("alpr.iou_threshold", 0.45),
    )
    detections = detector.detect(image)
    print(f"Phát hiện {len(detections)} biển số.")

    debug = image.copy()
    stem = Path(image_path).stem
    out_dir = Path(image_path).resolve().parent

    for idx, det in enumerate(detections):
        x1, y1, x2, y2 = map(int, det.bbox_xyxy)
        cv2.rectangle(debug, (x1, y1), (x2, y2), (0, 255, 0), 2)
        for px, py in det.corners.astype(int):
            cv2.circle(debug, (px, py), 4, (0, 0, 255), -1)
        print(f"  #{idx}: conf={det.confidence:.3f} bbox={det.bbox_xyxy} corners={det.corners.tolist()}")

        rectified = rectify_plate(image, det.corners)
        cv2.imwrite(str(out_dir / f"{stem}_rectified_{idx}.jpg"), rectified)
        for li, line in enumerate(split_lines_if_needed(rectified)):
            cv2.imwrite(str(out_dir / f"{stem}_rectified_{idx}_line{li}.jpg"), line)

    debug_path = out_dir / f"{stem}_debug.jpg"
    cv2.imwrite(str(debug_path), debug)
    print(f"Đã lưu: {debug_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
