"""Chạy trong tiến trình riêng bởi tests/test_desktop.py (app.* đọc DATABASE_URL lúc import nên không dùng chung với pytest)."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.getcwd())
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PARKING_DATA_DIR"] = tempfile.mkdtemp()

from desktop import bootstrap  # noqa: E402

bootstrap.prepare_environment()
from PySide6.QtWidgets import QApplication  # noqa: E402

from desktop.client import ApiClient  # noqa: E402
from desktop.main_window import MainWindow  # noqa: E402
from desktop.widgets import STYLE  # noqa: E402

app = QApplication([])
app.setStyleSheet(STYLE)
srv = bootstrap.EmbeddedServer()
srv.start()
t = time.time()
while not srv.wait_ready(0.3):
    assert not srv.error and time.time() - t < 120, srv.error
assert bootstrap.needs_first_admin()
bootstrap.create_first_admin("admin", "matkhau123", "Quản lý")
assert not bootstrap.needs_first_admin()
api = ApiClient(srv.base_url)
api.login("admin", "matkhau123")
assert api.is_admin
api.post("/admin/cards", {"card_number": "T1", "vehicle_type_code": "XeMay"})


class Ctl:
    def agent_status(self): return "test"
    def restart_agent(self): pass
    def agent_open_barrier(self, b): pass
    def restart_app(self): pass
    def logout(self): pass
    def quit(self): pass


win = MainWindow(api, Ctl())
win.show()


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


pump(0.5)
win.guard.card_input.setText("T1")
win.guard.scan_card()
assert win.guard.result_title.text() == "XE VÀO", win.guard.result_title.text()
win.guard.card_input.setText("KHONG-CO")
win.guard.scan_card()
assert "TỪ CHỐI" in win.guard.result_title.text()
for i in range(win.tabs.count()):  # mỗi tab nạp được dữ liệu mà không văng lỗi
    win.tabs.setCurrentIndex(i)
    pump(0.3)
assert win.tabs.count() == 8
cards = win._pages["Thẻ"].table
assert cards.rowCount() == 1 and cards.item(0, 0).text() == "T1"
win.guard.shutdown()
srv.stop()
print("DESKTOP_SMOKE_OK")
