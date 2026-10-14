# PyInstaller spec — ứng dụng desktop all-in-one (desktop/main.py). Build: scripts\build_desktop_exe.bat (Windows)
# hoặc `pyinstaller parking_desktop.spec --noconfirm --clean`. Kết quả: dist/ParkingAI/ParkingAI.exe (onedir).
from PyInstaller.utils.hooks import collect_submodules

hidden = (collect_submodules("uvicorn") + collect_submodules("insightface") + collect_submodules("skimage") + collect_submodules("app") + collect_submodules("desktop")
          + ["websockets.sync.client", "serial.tools.list_ports", "keyboard._winkeyboard",
             "serial.tools.list_ports_windows", "sqlalchemy.dialects.sqlite"])

a = Analysis(
    ["desktop/main.py"],
    pathex=["."],
    datas=[
        ("models/licenseplate/detect.onnx", "models/licenseplate"),
        ("models/insightface", "models/insightface"),  # model khuôn mặt buffalo_s (det + recognition) -> chạy offline
        ("config/config.example.yaml", "config"),
        ("app/assets/fonts", "app/assets/fonts"),
    ],
    hiddenimports=hidden,
    excludes=["evdev", "psycopg2", "torch", "tkinter", "matplotlib", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ParkingAI", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="ParkingAI")
