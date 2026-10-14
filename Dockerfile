FROM python:3.12-slim

# libglib2.0-0: opencv-python-headless vẫn cần ở runtime dù là bản "headless"
# (một số codec/video backend liên kết tới nó). gcc + linux-libc-dev: cần để
# build evdev từ source (không có wheel sẵn cho python-slim image) — evdev
# cần header "linux/input.h" lấy từ linux-libc-dev, không phải header của
# đúng kernel đang chạy (image Docker build độc lập với kernel host).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    build-essential \
    linux-libc-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# insightface (xác thực khuôn mặt, tuỳ chọn) khai "Requires: opencv-python" (bản GUI) —
# cài --no-deps để không đè mất "opencv-python-headless" đã cài trên (xem chú thích
# trong requirements.txt); các dependency còn lại của nó đã cài qua requirements.txt.
RUN pip install --no-cache-dir --no-deps insightface==2.1

COPY app/ app/
COPY web/ web/
COPY models/ models/
COPY config/config.example.yaml config/config.example.yaml
RUN mkdir -p /app/data

# config/config.yaml (thông tin thật: RTSP, COM port, API key...) KHÔNG copy vào image —
# phải mount từ ngoài vào lúc chạy container (xem docker-compose.yml), để không bake
# thông tin nhạy cảm của bãi xe thật vào image có thể bị chia sẻ nhầm.

EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
