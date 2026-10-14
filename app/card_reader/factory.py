from __future__ import annotations

from app.card_reader.interface import CardReader
from app.card_reader.simulated_reader import SimulatedCardReader


def build_card_reader(cfg: dict) -> CardReader:
    """`usb_hid_linux` và `windows_keyboard` import module riêng ở trong hàm
    (không import ở đầu file) vì mỗi module chỉ cài được/chạy được đúng 1 OS
    (evdev: Linux, keyboard: chủ yếu dùng cho Windows) — tránh để lỗi import
    module sai OS làm hỏng toàn bộ service (ví dụ chạy AI service trong Docker
    Linux thì không cần, không nên import `keyboard`)."""
    reader_type = cfg.get("type", "simulated")
    if reader_type == "usb_hid_linux":
        from app.card_reader.usb_hid_reader import UsbHidCardReader
        return UsbHidCardReader(
            device_path=cfg.get("device_path"),
            device_name_contains=cfg.get("device_name_contains"),
        )
    if reader_type == "windows_keyboard":
        from app.card_reader.windows_keyboard_reader import WindowsKeyboardCardReader
        return WindowsKeyboardCardReader()
    if reader_type == "serial":
        from app.card_reader.serial_reader import SerialCardReader
        port = cfg.get("port")
        if not port:
            raise ValueError("card_reader.type='serial' cần có card_reader.port (vd 'COM7')")
        return SerialCardReader(port=port, baudrate=cfg.get("baudrate", 9600))
    if reader_type == "simulated":
        return SimulatedCardReader()
    raise ValueError(f"Không hỗ trợ card_reader.type={reader_type!r}")
