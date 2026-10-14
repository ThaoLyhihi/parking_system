"""Smoke test ứng dụng desktop: server nhúng + giao diện PySide6 (offscreen) + quét thẻ + nạp mọi tab."""
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

ROOT = Path(__file__).resolve().parent.parent


def test_desktop_app_smoke():
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "desktop_smoke_script.py")], cwd=ROOT,
                       capture_output=True, text=True, timeout=240)
    assert "DESKTOP_SMOKE_OK" in r.stdout, r.stdout[-2000:] + r.stderr[-3000:]
