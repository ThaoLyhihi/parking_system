"""Load cấu hình YAML cho toàn bộ hệ thống.

Dùng config.yaml nếu có (copy từ config/config.example.yaml và sửa theo bãi xe thật),
nếu không thì fallback sang config.example.yaml để vẫn chạy được ở môi trường dev/demo.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

# PyInstaller (đóng gói .exe cho scripts/windows_hardware_agent.py, xem
# scripts/build_agent_exe.py): __file__ lúc đó chỉ trong thư mục tạm giải nén
# (sys._MEIPASS), không phải cạnh file .exe thật — phải dùng sys.executable để
# tìm đúng thư mục "config/" mà người dùng đặt cạnh file .exe khi triển khai.
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys.executable).resolve().parent
else:
    _BASE_DIR = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _BASE_DIR / "config"


def _resolve_config_path() -> Path:
    real = _CONFIG_DIR / "config.yaml"
    if real.exists():
        return real
    example = _CONFIG_DIR / "config.example.yaml"
    if not example.exists() and getattr(sys, "frozen", False):
        # Bản đóng gói onedir: config.example.yaml được PyInstaller gói kèm trong thư mục bundle.
        return Path(getattr(sys, "_MEIPASS", _BASE_DIR)) / "config" / "config.example.yaml"
    return example


class Config:
    """Wrapper mỏng quanh dict đã load, truy cập qua dot-path: cfg.get("cameras.gate.source")."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or _resolve_config_path()
        with open(path, "r", encoding="utf-8") as f:
            return cls(yaml.safe_load(f))

    def get(self, dot_path: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dot_path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def raw(self) -> dict[str, Any]:
        return self._data


config = Config.load()
