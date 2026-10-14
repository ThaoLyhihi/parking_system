from __future__ import annotations

from app.barrier.hardware import BarrierHardware, LoggingHardware
from app.barrier.serial_hardware import SerialBarrierHardware


def build_barrier_hardware(cfg: dict) -> BarrierHardware:
    hw_type = cfg.get("type", "logging")
    if hw_type == "logging":
        return LoggingHardware()
    if hw_type == "serial":
        return SerialBarrierHardware(barriers=cfg.get("barriers", {}), baudrate=cfg.get("baudrate", 9600))
    raise ValueError(f"Không hỗ trợ barrier_hardware.type={hw_type!r}")
