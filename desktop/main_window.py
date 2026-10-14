"""Cửa sổ chính: tab Bảo vệ (mọi người dùng) + các tab quản lý (chỉ admin)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QMainWindow, QTabWidget

from desktop.admin_views import (CardsTab, OverviewTab, ReportsTab, TariffsTab, UsersTab, VehicleTypesTab)
from desktop.client import ApiClient
from desktop.guard_view import GuardView
from desktop.settings_view import SettingsTab


class MainWindow(QMainWindow):
    card_seen = Signal(str)  # phát từ thread của agent -> UI

    def __init__(self, api: ApiClient, ctl) -> None:
        super().__init__()
        self.api, self.ctl = api, ctl
        who = api.user
        self.setWindowTitle(f"Hệ thống giữ xe tự động — {who['full_name']} ({'Quản lý' if api.is_admin else 'Bảo vệ'})")
        self.resize(1360, 820)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.guard = GuardView(api)
        self.tabs.addTab(self.guard, "Bảo vệ")
        self._pages = {}
        if api.is_admin:
            for title, page in [("Tổng quan", OverviewTab(api)), ("Thẻ", CardsTab(api)), ("Loại thẻ / xe", VehicleTypesTab(api)),
                                ("Biểu phí", TariffsTab(api)), ("Tài khoản", UsersTab(api)), ("Ca và báo cáo", ReportsTab(api)),
                                ("Cài đặt", SettingsTab(api, self))]:
                self.tabs.addTab(page, title)
                self._pages[title] = page
        self.tabs.currentChanged.connect(self._tab_changed)

        self.agent_label = QLabel()
        self.statusBar().addPermanentWidget(self.agent_label)
        menu = self.menuBar().addMenu("Hệ thống")
        a = QAction("Đăng xuất", self)
        a.triggered.connect(self.logout)
        menu.addAction(a)
        b = QAction("Khởi động lại ứng dụng", self)
        b.triggered.connect(self.restart_app)
        menu.addAction(b)
        self.update_agent_label()

    def _tab_changed(self, i: int) -> None:
        page = self.tabs.widget(i)
        if hasattr(page, "reload"):
            page.reload()

    # ---- cầu nối sang controller ---------------------------------------------
    def update_agent_label(self) -> None:
        self.agent_label.setText(self.ctl.agent_status())

    def agent_status(self) -> str:
        return self.ctl.agent_status()

    def restart_agent(self) -> None:
        self.ctl.restart_agent()
        self.update_agent_label()

    def agent_open_barrier(self, barrier_id: str) -> None:
        self.ctl.agent_open_barrier(barrier_id)

    def restart_app(self) -> None:
        self.ctl.restart_app()

    def logout(self) -> None:
        self.ctl.logout()

    def shutdown(self) -> None:
        self.guard.shutdown()

    def closeEvent(self, e) -> None:
        self.ctl.quit()
        e.accept()
