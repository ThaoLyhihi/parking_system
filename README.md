# Parking AI System (viết lại từ đầu bằng Python)

Phần mềm mới cho đề tài NCKH, xây dựng lại từ đầu bằng Python (không có mã nguồn gốc của
phần mềm cũ — xem [../QUY_TRINH_LAM_LAI_PHAN_MEM.md](../QUY_TRINH_LAM_LAI_PHAN_MEM.md)),
dựa trên 3 module AI trong [../THUYET_MINH_DE_TAI.md](../THUYET_MINH_DE_TAI.md):

1. **ALPR** (`app/alpr/`) — dùng lại model có sẵn `models/licenseplate/detect.onnx`/`detect.pt`
   (đã xác minh: YOLOv8n-pose, phát hiện 4 góc biển số để chỉnh phẳng trước khi OCR).
2. **Đếm chỗ trống** (`app/occupancy/`) — Hướng B (đếm luồng vào/ra) đã cài đặt đầy đủ;
   Hướng A (per-slot) mới là interface, chưa có dữ liệu để huấn luyện.
3. **An toàn barie** (`app/barrier/`) — **thay thế hoàn toàn** cảm biến vật lý (đã xác nhận
   barie thật không có cảm biến vòng từ/quang điện nào) bằng phát hiện chuyển động trong
   vùng ROI qua camera.

**Trang web** (`web/index.html`) đã hoàn chỉnh từ đăng nhập tới quản lý: bảo vệ quét thẻ/cho
khách không thẻ vào (tự xếp lệnh mở barie cho `scripts/windows_hardware_agent.py`), xem biển
số vào/ra **thời gian thực** qua WebSocket (`/ws/events`); quản lý xem tình trạng bãi xe, quản
lý tài khoản/ca trực, thẻ lượt/vé tháng (gia hạn, lịch sử đóng tiền), loại xe & biểu phí,
doanh thu vé tháng, và cài đặt phần mềm — toàn bộ qua `/admin/*` (xem `app/api/admin.py`).

## Vì sao viết lại từ đầu bằng Python (không sửa phần mềm .NET cũ)

Không có mã nguồn gốc (C#/.NET) của phần mềm cũ, chỉ có bản build đã compile — không thể
sửa/tích hợp trực tiếp. Một số thứ "rất tốt" từ phần mềm cũ mà bạn muốn giữ lại được tái
tạo bằng thư viện Python tương đương:

| Phần mềm cũ (.NET) | Tương đương trong project này |
|---|---|
| AForge.Video.DirectShow + FFmpeg + VLC bindings đọc RTSP | `app/vision/camera.py` — OpenCV `VideoCapture` (có FFmpeg built-in), đọc trong thread riêng để không bị nghẽn buffer RTSP |
| 1 luồng RTSP hiển thị thành "4 camera ảo" theo zoom (1x/2x/4x/8x) | `crop_zoom()` trong `app/vision/camera.py` |
| SDK SimpleLPR (thương mại, không tối ưu cho biển 2 dòng VN) | `app/alpr/` — model `detect.onnx` tự huấn luyện (kiến trúc YOLOv8-pose, nhận diện 4 góc biển số) |
| Class `BarrierController` (`OpenBarrierById`/`CloseBarrierById`) | `app/barrier/controller.py` — cùng tên khái niệm, thêm điều kiện an toàn mà bản cũ không có |
| Đầu đọc thẻ qua cổng **COM** (`coms.config`: `COM7`) | **Đổi sang USB** theo yêu cầu — `app/card_reader/usb_hid_reader.py` (đầu đọc dạng USB HID keyboard-wedge) |
| Barie qua COM/TCP, lệnh đóng/mở định nghĩa trong `<Barriers>` của `app.config.xml` | **Giữ nguyên cổng COM + định dạng lệnh**, chỉ đổi người quyết định thời điểm gửi — `app/barrier/serial_hardware.py` (AI gọi, không phải thẻ từ) |
| Logo công ty, hotline (`get_logo_cty`, `get_hotline`, `<e k="COMPANY" v="TAM TOAN THANG CORP" />`), API bên thứ 3 dùng số điện thoại làm key (`tienichcongcong.vn`) | **Đã loại bỏ hoàn toàn** — project này không có bất kỳ branding/liên hệ nào của công ty cung cấp phần mềm cũ |

## Phần cứng: những gì đã đổi theo yêu cầu mới

- **Camera: hỗ trợ 1 đến 4 camera, mỗi camera đều tuỳ chọn** (mục `cameras` trong trang Cài đặt
  admin hoặc `config.yaml`): `gate_in` (cổng vào), `gate_out` (cổng ra — để trống thì tự dùng
  lại `gate_in` cho lượt xe ra, đúng cho bãi 1 làn chung ra/vào), `overview` (toàn cảnh, đếm chỗ
  trống theo ô), `barrier` (an toàn barie). Thiếu camera nào thì chỉ mất đúng chức năng gắn với
  nó, phần còn lại vẫn chạy — xem `app/api/main.py` (`_gate_camera_for()`) và
  `test_gate_camera_fallback_supports_1_to_4_cameras` (đã test qua `pytest`).
  - Đã sửa 1 lỗi phát hiện được khi làm phần này: trước đây `_startup()` đọc camera thẳng từ
    `config.yaml` (`config.get(...)`), nên **sửa camera trên trang Cài đặt admin rồi khởi động
    lại KHÔNG có tác dụng gì** — đã sửa lại đọc qua `app_settings.get_section()` (gộp đúng thứ
    tự ưu tiên: DB admin đã lưu > config.yaml > mặc định). Đã test thật qua server chạy thật:
    lưu cấu hình camera qua API admin, khởi động lại, xác nhận `/status/overview` phản ánh
    đúng cấu hình mới lưu.
- **1 đầu đọc thẻ dùng chung cho cả quét vào và quét ra** (không cần đầu đọc riêng theo chiều/
  làn) — server tự biết là vào hay ra dựa trên thẻ đó có phiên gửi xe đang mở hay không
  (`card_scan()`), không phụ thuộc camera/làn nào đọc được. Đã ghi rõ thành 1 đoạn giải thích
  (`note`) ngay trong mục "Camera" của trang Cài đặt admin, không chỉ nằm trong code — đã test
  qua `pytest` xác nhận API `/admin/settings` trả đúng đoạn giải thích này.
- **Đầu đọc thẻ: hỗ trợ cả USB và COM** (chọn qua mục "Đầu đọc thẻ" trong Cài đặt admin, hoặc
  `card_reader.type` trong `config.yaml`):
  - `windows_keyboard`/`usb_hid_linux`: đầu đọc USB kiểu HID keyboard-wedge (gõ ra như bàn phím)
    — mặc định, loại phổ biến/giá rẻ nhất.
  - `serial`: đầu đọc qua cổng **COM/RS232** — đúng kiểu phần cứng phần mềm cũ dùng (`coms.config`:
    `COM7`), dùng lại khi bạn có sẵn đầu đọc loại này. Xem `app/card_reader/serial_reader.py` —
    giả định giao thức ASCII kết thúc bằng `\r`/`\n`, **chưa xác minh với phần cứng thật**.
  - Nếu đầu đọc thật dùng giao thức khác (HID riêng không gõ ra bàn phím, hoặc serial có khung
    byte riêng), cần viết thêm 1 class khác implement `CardReader`
    (xem `app/card_reader/interface.py`).
- **Barie: vẫn dùng cổng COM** (hoặc TCP cho 1 số barie, đúng như phần mềm cũ), gửi đúng định
  dạng lệnh `openCommand`/`closeCommand` lấy từ `app.config.xml` gốc — xem
  `app/barrier/serial_hardware.py` và `config/config.example.yaml` (mục `barrier_hardware`).
  **Khác biệt duy nhất**: trước đây thẻ từ quyết định khi nào gửi lệnh, giờ AI
  (`BarrierSafetyZone` + `BarrierController.try_close_barrier()`) quyết định — đúng yêu cầu
  "AI chịu trách nhiệm gửi tín hiệu đóng mở".
  - ⚠️ 2 điểm chưa xác minh được bằng phần cứng thật, xem cảnh báo chi tiết trong
    `serial_hardware.py`: cách hiểu ký hiệu `<02>` trong lệnh của barie id=2, và lệnh
    `openCommand` khác định dạng của barie id=1.

## Tự chỉnh cấu hình theo máy/bãi xe thật — "cửa sổ" Cài đặt + công cụ dò cổng COM

Toàn bộ cấu hình phần cứng (camera, đầu đọc thẻ, barie...) đều chỉnh được **ngay trên web**,
không cần sửa file tay: đăng nhập bằng tài khoản **admin** → tab cuối cùng **"Cài đặt"** trên
trang quản lý. Mỗi mục (Camera, Đầu đọc thẻ, Barie...) tự hiện đúng các trường cần điền, kèm
giải thích ngắn ngay trong trang — đây chính là "cửa sổ" để tự setting theo tình hình thực tế
của bạn, không cần tôi chỉnh giùm mỗi lần đổi phần cứng.

**Vấn đề thực tế khi tự chỉnh**: với đầu đọc thẻ/barie qua cổng COM, bạn cần biết đúng tên cổng
(`COM3`, `COM7`...) trên MÁY WINDOWS THẬT trước khi điền vào — không thể đoán. Dùng:
```
scripts\list_com_ports.bat
```
Chạy file này **trên máy Windows** (không chạy trong Docker) — nó liệt kê toàn bộ cổng COM
đang có kèm tên thiết bị (vd `COM7 - USB-SERIAL CH340`), để bạn biết đúng cổng nào điền vào
mục "Đầu đọc thẻ" (loại `serial`) hoặc "Barie (COM/TCP)" trong trang Cài đặt.

⚠️ Đã test được dòng lệnh Python bên trong file này chạy đúng cú pháp (không lỗi) trên Linux —
chạy ra danh sách cổng serial giả của Linux (`/dev/ttyS0`...), không phải cổng COM Windows thật.
**Chưa chạy thử được chính file `.bat` này trên Windows** (môi trường phát triển là Linux).

## Database: PostgreSQL gói chung qua Docker (không cần cài SQL Server/PostgreSQL riêng)

`docker compose up` tự chạy luôn 1 container PostgreSQL (service `db`) — máy triển khai chỉ
cần cài Docker, không cần cài thêm CSDL nào. Local dev không dùng Docker thì mặc định dùng
SQLite (`config.example.yaml`), không cần cài gì. Xem `app/db/base.py`: biến môi trường
`DATABASE_URL` (đặt tự động trong `docker-compose.yml`) được ưu tiên hơn `config.yaml`.

## Triển khai trên Windows — kiến trúc 2 phần, vì sao phải tách

Docker Desktop trên Windows chạy container Linux qua WSL2. Camera là **luồng mạng (RTSP)**
nên container gọi ra ngoài qua mạng LAN vẫn được bình thường, dù chạy trên Windows — không
vấn đề. Nhưng **đầu đọc thẻ USB và cổng COM điều khiển barie là thiết bị cục bộ của máy
Windows**, không xuyên vào container Linux một cách đơn giản/đáng tin cậy được. Vì vậy:

```
┌─────────────────────────────┐        HTTP         ┌──────────────────────────────┐
│   Windows (ngoài Docker)     │ ───────────────────▶│   Docker (Linux qua WSL2)     │
│  scripts/windows_hardware_   │  POST /card/scan     │  app/api/main.py              │
│  agent.py                    │  GET /barrier/{id}/  │  - ALPR, đếm chỗ trống         │
│  - đọc đầu đọc thẻ USB        │       status         │  - BarrierSafetyZone (camera   │
│    (thư viện `keyboard`)      │◀─────────────────── │    barie, qua RTSP mạng LAN)  │
│  - gửi lệnh mở/đóng qua COM   │                      │  - PostgreSQL (service "db")  │
│    (thư viện `pyserial`)      │                      │                                │
└─────────────────────────────┘                      └──────────────────────────────┘
```

Cài trên Windows (chạy từ mã nguồn — cần Python):
```powershell
pip install -r requirements-windows-agent.txt
python scripts\windows_hardware_agent.py
```

**Hoặc đóng gói sẵn thành 1 file `.exe`** để mang sang máy khác chạy, KHÔNG cần cài Python:
```
scripts\build_agent_exe.bat
```
Double-click (hoặc chạy trong `cmd`) file này **trên chính máy Windows** (PyInstaller không
build chéo được — chạy trên Linux chỉ ra file chạy được trên Linux). File này tự tạo
`.venv`, cài `keyboard`/`pyserial`/`requests`/`PyYAML`/`pyinstaller`, rồi đóng gói
`scripts/windows_hardware_agent.py` bằng PyInstaller. Kết quả nằm trong thư mục `dist\`:
- `dist\parking_hardware_agent.exe`
- `dist\config\config.example.yaml` (copy sẵn, đổi tên thành `config.yaml` rồi sửa lại cho
  đúng bãi xe/đầu đọc thẻ/barie thật trước khi chạy — xem mục `card_reader`/`barrier_hardware`).

**Mang sang máy khác**: copy nguyên thư mục `dist\`, không chỉ file `.exe` — file cấu hình
`config\config.yaml` phải nằm CẠNH file `.exe` (cùng cấp), vì `app/config.py` tìm thư mục
`config\` ngay cạnh vị trí file `.exe` đang chạy khi đã đóng gói (không phải cạnh mã nguồn).

⚠️ Đã build & chạy thử thành công **trên Linux** bằng đúng lệnh PyInstaller trong file `.bat`
(để kiểm tra logic đóng gói/import không lỗi) — file chạy ra khởi động đúng, đọc đúng
`config.yaml` cạnh nó, xử lý mất kết nối AI service không crash. **Chưa build/chạy thử được
trên Windows thật** vì môi trường phát triển là Linux — PyInstaller không cho build chéo
sang Windows, nên lần build thật đầu tiên trên Windows có thể lộ ra lỗi riêng của Windows mà
lần test trên Linux không thấy được (vd thiếu hidden-import nào đó chỉ xảy ra trên Windows).

Agent gọi `POST /card/scan` khi có người quẹt thẻ (server quyết định vào/ra, chạy ALPR, ghi
DB, trả về `barrier_id` cần mở) rồi agent tự gửi lệnh mở qua COM; sau đó agent hỏi lặp lại
`GET /barrier/{id}/status` tới khi `safe_to_close=true` (do `BarrierSafetyZone` phía Docker
quyết định từ camera barie) rồi mới tự gửi lệnh đóng — đúng yêu cầu "AI chịu trách nhiệm gửi
tín hiệu đóng mở", chỉ có *đường truyền lệnh vật lý cuối* là qua agent cục bộ vì giới hạn hệ
điều hành, không phải do thẻ từ quyết định nữa.

⚠️ **Chưa test được với Windows/phần cứng thật** — môi trường phát triển là Linux, không có
máy Windows + đầu đọc thẻ + barie thật để thử. Đã test được: toàn bộ phần server (card_scan,
barrier/status) qua `pytest`, và `keyboard`/`pyserial` import/cài đặt được không lỗi.

## Hoạt động khi mất Internet (WAN) — chỉ web/email bị ảnh hưởng

**Phạm vi đã xác nhận với bạn**: hệ thống chịu được **mất kết nối Internet/WAN** (modem/đường
truyền nhà mạng đứt), miễn AI service (Docker) + agent Windows + camera vẫn cùng một mạng LAN
nội bộ. Không bao gồm trường hợp hạ tầng LAN/Docker nội bộ tự hỏng (vd Docker Desktop/WSL2 lỗi)
— phạm vi đó cần một thiết kế dự phòng cục bộ khác, chưa làm.

**Vì sao đã đáp ứng được, không phải tình cờ đúng** — đã rà soát bằng `grep` toàn bộ `app/`,
`web/`, `scripts/`, `config/` tìm `http://`/`https://`: chỉ có 2 chỗ, cả hai đều là
`http://localhost:8000` (mặc định của `hardware_agent.api_base_url`) — không có API/CDN/font
ngoài nào được gọi ở bất kỳ đâu khác:
- **Agent ↔ AI service**: qua `localhost`/IP LAN (xem cảnh báo mới thêm trong
  `config.example.yaml`) — không đi qua Internet nên mất WAN không ảnh hưởng.
- **Camera (RTSP)**: phải dùng IP LAN (vd `192.168.x.x`), không dùng hostname DDNS/domain công
  khai — đã ghi rõ cảnh báo này trong `config.example.yaml` vì DDNS vẫn cần Internet để phân
  giải DNS dù camera là camera tại chỗ.
- **Đầu đọc thẻ USB, barie qua COM**: phần cứng cục bộ 100%, không qua mạng.
- **CSDL**: PostgreSQL chạy trong Docker trên cùng máy — không qua Internet.
- **Model ALPR (ONNX)**: chạy suy luận cục bộ, không gọi API AI nào ở ngoài.
- **`web/index.html`**: toàn bộ CSS/JS viết tay, nhúng thẳng trong file — không tải font/thư
  viện từ CDN nào, nên trang vẫn hiển thị/hoạt động đầy đủ khi mở trong LAN lúc mất Internet.
- **Email báo cáo ca**: là tính năng **DUY NHẤT** thật sự cần Internet (gửi SMTP) — đã tắt mặc
  định (`email.enabled: false`), và khi bật, lỗi gửi mail **không** làm hỏng việc kết ca
  (`send_shift_report()` bắt mọi exception, chạy nền qua `BackgroundTasks`, chỉ ghi log) — đã
  test qua `test_close_shift_sends_email`.
- Đã thử nghiệm thật: tắt hẳn AI service (giả lập mất kết nối hoàn toàn) rồi chạy
  `windows_hardware_agent.py` — agent tự log cảnh báo và **không crash**, chạy lặp vô hạn chờ
  kết nối lại (xem lịch sử phát triển); đây là test khắc nghiệt hơn cả yêu cầu thực tế (chỉ mất
  Internet, không mất luôn kết nối nội bộ tới AI service).

**Lưu ý khi triển khai thật**: `docker compose build`/`pull` ảnh Postgres + ảnh tự build cần
Internet **một lần đầu**; sau đó `docker compose up` dùng image đã có sẵn trong máy, không cần
Internet nữa (Docker không tự pull lại trừ khi bạn chủ động `--pull always` hoặc xoá image).

## Cấu trúc

```
parking_system/
  app/
    config.py            # load config/config.yaml
    db/models.py          # schema mới, tương đương nghiệp vụ với CSDL cũ (xem docstring từng class)
    vision/camera.py       # đọc RTSP/webcam/file, threaded
    alpr/
      plate_detector.py    # chạy detect.onnx (YOLOv8-pose), tự NMS
      plate_rectify.py     # chỉnh phẳng + tách 2 dòng biển xe máy
      ocr.py                # INTERFACE — chưa cắm OCR thật (xem mục 6.2 thuyết minh)
      pipeline.py           # ghép detect + rectify + ocr
    occupancy/
      flow_counter.py      # Hướng B — đã cài đặt đầy đủ
      slot_classifier.py   # Hướng A — interface, chưa triển khai (cần dataset)
    barrier/
      safety_zone.py       # phát hiện chuyển động trong ROI (cảm biến = camera)
      controller.py         # state machine mở/đóng barie
    core/
      fee.py                 # tính phí theo giờ
      session_manager.py    # luồng xe vào/ra, ghi DB
    api/main.py            # FastAPI — AI Inference Service (mục 6.3 thuyết minh)
                           # + /card/scan, /barrier/{id}/status cho Windows agent
    card_reader/            # interface + usb_hid_reader (Linux/evdev) + windows_keyboard_reader + giả lập
    barrier/hardware.py      # BarrierHardware/LoggingHardware — KHÔNG import cv2 (để .exe nhẹ, xem build_agent_exe.bat)
    barrier/serial_hardware.py  # gửi lệnh đóng/mở thật qua COM/TCP (giữ nguyên giao thức cũ)
  web/index.html           # Giao diện web (đăng nhập, quét thẻ, tình trạng bãi xe, quản trị) — để RIÊNG
                           # ngoài app/ cho dễ quản lý; app/api/main.py chỉ phục vụ nó qua route "/"
  models/licenseplate/     # detect.onnx + detect.pt (copy từ giuxe/giuxe1/model/licenseplate/)
  config/config.example.yaml
  requirements.txt              # cho Docker/Linux (AI service)
  requirements-windows-agent.txt  # cho Windows (chỉ agent: keyboard, pyserial, requests)
  scripts/
    test_alpr_on_image.py  # chạy thử model trên 1 ảnh thật — LÀM TRƯỚC KHI DÙNG CHO PRODUCTION
    demo_pipeline.py       # chạy pipeline trên webcam/file/RTSP, in FPS + kết quả
    demo_card_to_barrier.py  # demo đầy đủ: quẹt thẻ -> ghi DB -> mở barie (đã test chạy qua)
    windows_hardware_agent.py  # chạy TRÊN WINDOWS — xem mục "Triển khai trên Windows"
    build_agent_exe.bat     # đóng gói windows_hardware_agent.py thành .exe — chạy TRÊN WINDOWS
    list_com_ports.bat      # dò tên cổng COM thật trên máy — chạy TRÊN WINDOWS
  tests/test_smoke.py      # 4 test, bao gồm /card/scan — đã chạy qua (xem mục Chạy thử)
  Dockerfile, docker-compose.yml   # app + PostgreSQL — đã build & chạy thử thành công
```

## Chạy thử

```bash
cd parking_system
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config/config.example.yaml config/config.yaml   # rồi sửa theo bãi xe thật

pytest tests/ -v                                   # smoke test (đã chạy qua, 3/3 pass)

# Quan trọng nhất — làm NGAY khi có ảnh biển số thật:
python scripts/test_alpr_on_image.py duong/dan/anh_bien_so.jpg
# Kiểm tra file *_rectified_*.jpg — nếu ảnh biển số bị lật/xoay sai, cần sửa
# lại thứ tự 4 góc trong app/alpr/plate_detector.py (xem docstring ở đó).

uvicorn app.api.main:app --reload                   # chạy AI Inference Service
# POST /alpr/detect (multipart file) để test qua HTTP, GET /occupancy xem tồn xe

python scripts/demo_card_to_barrier.py              # demo quẹt thẻ (giả lập) -> DB -> mở barie
```

## Chạy bằng Docker (đã build & test thật — app + PostgreSQL, không chỉ viết Dockerfile suông)

```bash
cp config/config.example.yaml config/config.yaml   # sửa theo bãi xe thật trước khi chạy
docker compose build
docker compose up -d        # tự chạy cả PostgreSQL (service "db") + AI service
curl http://localhost:8000/health
curl http://localhost:8000/occupancy
curl -X POST http://localhost:8000/card/scan -H "Content-Type: application/json" -d "{\"card_number\":\"123\"}"
```

Đã test thật toàn bộ luồng trên (health, occupancy, card/scan vào + ra, barrier/status) qua
`docker compose up` với PostgreSQL thật — không phải SQLite giả lập.

- `config/config.yaml` được mount từ ngoài vào (không bake vào image) — tránh lưu nhầm
  thông tin nhạy cảm (RTSP, lệnh barie) vào image có thể bị chia sẻ. Dữ liệu PostgreSQL lưu
  trong Docker volume `parking-db`, không mất khi `docker compose down` (chỉ mất khi thêm `-v`).
- Lưu ý khi build: `evdev` (dùng cho đầu đọc thẻ USB trên Linux) cần biên dịch từ source trong
  image `python:3.12-slim` (không có wheel sẵn) — Dockerfile đã cài `build-essential` +
  `linux-libc-dev` cho việc này; đừng xoá 2 package đó nếu sửa Dockerfile.
- **Không có `devices:`/USB/COM nào trong `docker-compose.yml`** — theo thiết kế, vì mục tiêu
  triển khai là Windows (xem mục "Triển khai trên Windows" ở trên): phần cứng cục bộ chạy
  bằng `scripts/windows_hardware_agent.py` ngoài Docker, không qua container.

## Việc CHƯA làm — rất quan trọng, đừng báo cáo nhầm là đã xong

- **OCR đọc ký tự biển số**: chỉ có interface (`app/alpr/ocr.py`), chưa cắm model thật.
  Đây đúng là nội dung nghiên cứu còn mở trong thuyết minh đề tài (mục 6.2) — cần khảo
  sát dataset rồi mới quyết định huấn luyện CRNN riêng hay dùng EasyOCR/PaddleOCR.
- **Hướng A (đếm chỗ trống theo ô)**: chỉ có interface (`app/occupancy/slot_classifier.py`),
  cần dataset ảnh toàn cảnh + nhãn occupied/empty theo ô.
- **Thứ tự 4 góc biển số** (`plate_detector.py`) là giả định, chưa xác minh bằng ảnh thật.
- **Đầu đọc thẻ USB và barie qua COM/TCP đã viết code thật** (`app/card_reader/`,
  `app/barrier/serial_hardware.py`) và test được luồng logic đầy đủ bằng giả lập
  (`demo_card_to_barrier.py`, và endpoint `/card/scan` qua `pytest`), nhưng **chưa test với
  phần cứng/Windows thật** — không có máy Windows + đầu đọc thẻ/relay/barie thật trong môi
  trường phát triển này (Linux). Cần test lại khi triển khai thật, đặc biệt 2 điểm chưa
  chắc chắn nêu trong `serial_hardware.py`.
- Camera RTSP trong `config.example.yaml` là placeholder — **không dùng lại** địa chỉ IP
  trong file cũ `giuxe/giuxe1/Debug_MSSQL/Debug/cameras.config` (đã public, xem mục 3
  trong QUY_TRINH_LAM_LAI_PHAN_MEM.md).
- **Trang web đã test bằng `pytest` (TestClient) và client Python thật** (HTTP + WebSocket
  qua `websockets`, xem lịch sử phát triển) — gọi đúng API, nhận đúng sự kiện realtime.
  **Chưa mở thử bằng trình duyệt thật** (môi trường phát triển không có GUI) — trước khi
  dùng thật, mở `http://localhost:8000` bằng Chrome/Edge và thử đủ luồng: đăng nhập, quét
  thẻ, "Khách vào"/"Cho ra", xem feed realtime tự cập nhật, các tab quản lý.
- `docker-compose.yml` giờ **bắt buộc** file `.env` (không có trong git) khai báo
  `PARKING_ADMIN_PASSWORD` và `AGENT_API_KEY` trước khi `docker compose build/up` chạy được
  — xem thông báo lỗi khi thiếu, nó tự nói rõ cần đặt biến nào.
