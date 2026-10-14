"""Demo end-to-end: đọc 1 nguồn video (webcam/file/RTSP) bằng CameraStream,
chạy ALPR trên từng khung hình, hiển thị FPS + kết quả — dùng để kiểm tra khả
năng chạy thời gian thực (mục 6.5 thuyết minh) trước khi nối camera RTSP thật.

Dùng:
    python scripts/demo_pipeline.py 0                 # webcam
    python scripts/demo_pipeline.py duong/dan/video.mp4
    python scripts/demo_pipeline.py rtsp://...

Chạy headless (không có màn hình, ví dụ trên server) sẽ không mở được cửa sổ
cv2.imshow — dùng --no-display để chỉ in log ra console.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.alpr.pipeline import AlprPipeline  # noqa: E402
from app.alpr.plate_detector import PlateDetector  # noqa: E402
from app.config import config  # noqa: E402
from app.vision.camera import CameraSpec, CameraStream  # noqa: E402


def main(source: str, display: bool) -> None:
    try:
        source = int(source)
    except ValueError:
        pass

    camera = CameraStream(CameraSpec(name="demo", source=source)).start()
    detector = PlateDetector(
        model_path=config.get("alpr.model_path", "models/licenseplate/detect.onnx"),
        input_size=config.get("alpr.input_size", 896),
        conf_threshold=config.get("alpr.conf_threshold", 0.4),
        iou_threshold=config.get("alpr.iou_threshold", 0.45),
    )
    pipeline = AlprPipeline(detector)

    print("Đang chạy, nhấn Ctrl+C để dừng...")
    try:
        while True:
            start = time.time()
            frame = camera.read()
            if frame is None:
                print("Mất tín hiệu camera, đang thử kết nối lại...")
                time.sleep(1)
                continue

            readings = pipeline.read(frame)
            elapsed = time.time() - start
            print(f"FPS={1 / elapsed:.1f} | {len(readings)} biển số phát hiện được")
            for r in readings:
                print(f"  - text={r.text!r} conf={r.confidence:.2f}")

            if display:
                for r in readings:
                    x1, y1, x2, y2 = map(int, r.detection.bbox_xyxy)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.imshow("demo", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        camera.stop()
        if display:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--no-display", action="store_true")
    args = parser.parse_args()
    main(args.source, display=not args.no_display)
