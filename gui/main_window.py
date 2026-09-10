import sys
import os
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPointF, QRectF, QPropertyAnimation, QEasingCurve, QUrl, QSize
from PyQt6.QtGui import QColor, QIcon, QPixmap, QImage, QPainter, QPainterPath, QPen, QBrush, QDesktopServices
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QComboBox, QCheckBox, QGroupBox,
    QTextEdit, QFrame, QScrollArea, QGraphicsDropShadowEffect,
    QRadioButton, QButtonGroup, QSystemTrayIcon, QMenu, QApplication,
    QSizePolicy, QFileDialog
)

from gui.presets import PRESETS
from gui.backend import CoreBackend
from gui.system_proxy import SystemProxyManager
from gui.profile_manager import ProfileManager, get_cache_dir
from gui.theme import LIGHT_MINIMAL_STYLESHEET
from gui.app_finder import find_app_binary, launch_app, restart_or_launch_app
from gui.autostart import is_autostart_enabled, set_autostart
from gui.secrets import get_secrets

class ModeShim:
    """
    Drop-in compatibility adapter providing isChecked/setChecked/setEnabled
    semantics for routing modes, mapped directly to MainWindow.current_routing_mode.
    """
    def __init__(self, mode_id: int, window: 'MainWindow'):
        self.mode_id = mode_id
        self.window = window
        self._enabled = True
        self._signals: List[Any] = []

    def isChecked(self) -> bool:
        return self.window.current_routing_mode == self.mode_id

    def setChecked(self, value: bool):
        if value and self.window.current_routing_mode != self.mode_id:
            self.window._select_mode(self.mode_id)

    def isEnabled(self) -> bool:
        return self._enabled

    def setEnabled(self, value: bool):
        self._enabled = value

    def setToolTip(self, tip: str):
        pass

    @property
    def toggled(self):
        class _Signal:
            def __init__(self, shim):
                self.shim = shim
            def connect(self, slot):
                self.shim._signals.append(slot)
        return _Signal(self)

    def emit_toggled(self, checked: bool):
        for slot in self._signals:
            try:
                slot(checked)
            except Exception:
                pass

class ModeGroupShim:
    """
    Drop-in compatibility adapter for QButtonGroup.checkedId() and button().
    """
    def __init__(self, window: 'MainWindow'):
        self.window = window

    def checkedId(self) -> int:
        return self.window.current_routing_mode

    def button(self, mode_id: int):
        if mode_id == 0:
            return self.window.radio_tun
        elif mode_id == 1:
            return self.window.radio_sys_proxy
        elif mode_id == 2:
            return self.window.radio_local_only
        return None

class LogTextEdit(QTextEdit):
    """
    Dedicated log text area that consumes wheel scroll events locally,
    preventing unwanted propagation to parent scroll containers.
    """
    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()

class AnimatedLinkButton(QPushButton):
    """
    Interactive link button with animated drop shadow, hover elevation,
    smooth tactile click feedback, and external URL launcher.
    """
    def __init__(self, text: str, url: str, base_color: str, hover_color: str, pressed_color: str, icon: QIcon = None, parent=None):
        super().__init__(text, parent)
        self.url = url
        self.base_color = base_color
        self.hover_color = hover_color
        self.pressed_color = pressed_color

        if icon and not icon.isNull():
            self.setIcon(icon)
            self.setIconSize(QSize(15, 15))

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(34)
        self._update_style(self.base_color)

        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(8)
        self.shadow.setColor(QColor(0, 0, 0, 35))
        self.shadow.setOffset(0, 2)
        self.setGraphicsEffect(self.shadow)

        self.clicked.connect(self._open_url)

    def _update_style(self, bg_color: str):
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: #ffffff;
                font-size: 11px;
                font-weight: 700;
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 9px;
                padding: 4px 12px;
            }}
        """)

    def enterEvent(self, event):
        self._update_style(self.hover_color)
        self._anim_shadow(14, 3)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._update_style(self.base_color)
        self._anim_shadow(8, 2)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._update_style(self.pressed_color)
        self._anim_shadow(3, 1)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.rect().contains(event.pos()):
            self._update_style(self.hover_color)
            self._anim_shadow(14, 3)
        else:
            self._update_style(self.base_color)
            self._anim_shadow(8, 2)
        super().mouseReleaseEvent(event)

    def _anim_shadow(self, target_blur: float, target_offset: float):
        self.anim_blur = QPropertyAnimation(self.shadow, b"blurRadius")
        self.anim_blur.setDuration(130)
        self.anim_blur.setStartValue(self.shadow.blurRadius())
        self.anim_blur.setEndValue(target_blur)
        self.anim_blur.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.anim_blur.start()

        self.anim_offset = QPropertyAnimation(self.shadow, b"yOffset")
        self.anim_offset.setDuration(130)
        self.anim_offset.setStartValue(self.shadow.yOffset())
        self.anim_offset.setEndValue(target_offset)
        self.anim_offset.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.anim_offset.start()

    def _open_url(self):
        import webbrowser
        try:
            if not QDesktopServices.openUrl(QUrl(self.url)):
                webbrowser.open(self.url)
        except Exception:
            webbrowser.open(self.url)

class MainWindow(QMainWindow):
    sig_app_launch_result = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FQoF · Nexus")
        self.setFixedSize(390, 590)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setStyleSheet(LIGHT_MINIMAL_STYLESHEET)

        self.app_root = Path(sys._MEIPASS) if (getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")) else Path(__file__).parent.parent

        assets_dir = self.app_root / "assets"
        app_icon = QIcon()
        for sz in [16, 32, 48, 64, 128, 256, 512, 1024]:
            p = assets_dir / f"icon_{sz}.png" if sz != 1024 else assets_dir / "icon.png"
            if p.exists():
                app_icon.addFile(str(p))
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self.backend = CoreBackend()
        self.is_connected = False
        self._is_quitting = False
        self._tray_state = "disconnected"
        self._tray_frame_idx = 0

        self.current_socks_port = 10808
        self.current_http_port = 10809
        self.current_dns_port = 10853

        self.current_routing_mode = 0
        self.mode_controls_enabled = True

        self.radio_tun = ModeShim(0, self)
        self.radio_sys_proxy = ModeShim(1, self)
        self.radio_local_only = ModeShim(2, self)
        self.mode_group = ModeGroupShim(self)

        self.profile_mgr = ProfileManager.get_instance()
        self.remote_uuid = self.profile_mgr.get_uuid()

        _srv = get_secrets().get("server", {})
        self.remote_host = _srv.get("host", "127.0.0.1")
        self.remote_port = _srv.get("port", 443)
        self.remote_path = _srv.get("path", "/api/v1/telemetry")
        self.remote_sni = _srv.get("sni", "example.com")
        self.reality_sni = _srv.get("reality_sni", "api.weatherapi.com")
        self.reality_public_key = _srv.get("reality_public_key", "")
        self.reality_short_id = _srv.get("reality_short_id", "")
        self.pq_encryption = _srv.get("post_quantum_encryption", "")
        self.remote_user = _srv.get("user", "user")
        self.remote_pass = _srv.get("pass", "pass")
        self.tun_active = False
        self.tun_apps: List[Dict[str, Any]] = []
        self.tun_apps_enabled = True
        self._pending_apps_to_launch: List[Dict[str, Any]] = []

        self.settings_file = get_cache_dir() / "user_settings.json"
        self._user_settings = self._load_user_settings()

        self._init_ui()
        self._apply_user_settings()
        self._init_tray()
        self._connect_signals()

        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(5000)
        self._ping_timer.timeout.connect(self._on_ping_timer_tick)

        threading.Thread(target=self._sync_device_profile, daemon=True).start()

        self._try_autoload_user_proxy()

        self._ensure_sudoers_authorized()

        self.backend.start_core()

    def _sync_device_profile(self):
        try:
            data = self.profile_mgr.fetch_or_register()
            if data and data.get("uuid"):
                self.remote_uuid = data["uuid"]
                self._log(f"🔑 Профиль ПК синхронизирован с БД: {self.profile_mgr.get_hwid_short()} (UUID: {self.remote_uuid[:8]}...)")
                if hasattr(self, "btn_profile_id"):
                    disp = f"{self.remote_uuid[:8]}...{self.remote_uuid[-6:]}" if len(self.remote_uuid) > 16 else self.remote_uuid
                    self.btn_profile_id.setText(f"{disp} 📋")
                    self.btn_profile_id.setToolTip(f"Нажмите, чтобы скопировать ID:\n{self.remote_uuid}")
        except Exception as e:
            self._log(f"⚠️ Ошибка синхронизации профиля: {e}")

    def _init_ui(self):
        central = QWidget()
        central.setObjectName("central_widget")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        top_header = QHBoxLayout()
        top_header.setSpacing(8)

        logo_file = self.app_root / "assets" / "logo_header.png"
        if logo_file.exists():
            lbl_logo = QLabel()
            pix = QPixmap(str(logo_file)).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            lbl_logo.setPixmap(pix)
            lbl_logo.setFixedSize(22, 22)
            top_header.addWidget(lbl_logo)

        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        self.brand_title = QLabel("FQoF NEXUS")
        self.brand_title.setStyleSheet("font-size: 13px; font-weight: 800; letter-spacing: 1.2px; color: #09090b;")
        brand_sub = QLabel("STEALTH PROXY")
        brand_sub.setStyleSheet("font-size: 8.5px; font-weight: 700; letter-spacing: 1.5px; color: #71717a;")
        brand_box.addWidget(self.brand_title)
        brand_box.addWidget(brand_sub)
        top_header.addLayout(brand_box)
        top_header.addStretch()

        self.lbl_header_badge = QLabel("v1.1.5")
        self.lbl_header_badge.setStyleSheet("""
            background-color: #f1f5f9;
            color: #475569;
            border: 1px solid #e2e8f0;
            border-radius: 9px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: 700;
        """)
        top_header.addWidget(self.lbl_header_badge)
        main_layout.addLayout(top_header)

        navbar = self._create_navbar()
        main_layout.addWidget(navbar)

        self.stack = QStackedWidget(self)
        self.page_dashboard = self._build_dashboard_page()
        self.page_apps = self._build_apps_page()
        self.page_settings = self._build_settings_page()

        self.stack.addWidget(self.page_dashboard)
        self.stack.addWidget(self.page_apps)
        self.stack.addWidget(self.page_settings)
        self.stack.setCurrentIndex(0)

        main_layout.addWidget(self.stack, 1)

    def _create_navbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("navbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        self.nav_tabs: List[QPushButton] = []
        tabs_data = [
            ("🛡️ Главная", 0),
            ("🎯 Приложения", 1),
            ("⚙️ Настройки", 2),
        ]

        for text, idx in tabs_data:
            btn = QPushButton(text)
            btn.setProperty("class", "nav_tab")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=idx: self._switch_tab(i))
            self.nav_tabs.append(btn)
            layout.addWidget(btn)

        self._update_navbar_active(0)
        return bar

    def _switch_tab(self, index: int):
        self.stack.setCurrentIndex(index)
        self._update_navbar_active(index)

    def _update_navbar_active(self, active_index: int):
        for i, btn in enumerate(self.nav_tabs):
            is_active = (i == active_index)
            btn.setProperty("active", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _setup_light_combobox(self, combo: QComboBox):
        from PyQt6.QtWidgets import QListView
        from PyQt6.QtGui import QPalette, QColor

        view = QListView(combo)
        view.setObjectName("combo_popup_view")
        pal = view.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#0f172a"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#0f172a"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#f1f5f9"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#09090b"))
        view.setPalette(pal)
        view.setStyleSheet("""
            QListView {
                background-color: #ffffff;
                background: #ffffff;
                color: #0f172a;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }
            QListView::item {
                background-color: #ffffff;
                color: #0f172a;
                min-height: 28px;
                padding: 5px 10px;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
            }
            QListView::item:hover, QListView::item:selected {
                background-color: #f1f5f9;
                color: #09090b;
            }
        """)
        combo.setView(view)

    def _build_dashboard_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("dashboard_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)

        center_box = QVBoxLayout()
        center_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_box.setSpacing(9)

        self.status_pill = QLabel("● fuqoff?")
        self.status_pill.setObjectName("status_pill")
        self.status_pill.setProperty("class", "status_pill")
        self.status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_pill.setStyleSheet("""
            background-color: #ffffff;
            color: #64748b;
            border: 1.5px solid #e2e8f0;
            padding: 4px 16px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 11px;
        """)
        self.status_pill.setMinimumWidth(180)
        center_box.addWidget(self.status_pill, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_main = QPushButton("ПОДКЛЮЧИТЬСЯ")
        self.btn_main.setObjectName("btn_main_connect")
        self.btn_main.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_main.setFixedSize(230, 52)
        self.btn_main.clicked.connect(self._toggle_connection)

        btn_shadow = QGraphicsDropShadowEffect(self.btn_main)
        btn_shadow.setBlurRadius(18)
        btn_shadow.setColor(QColor(0, 0, 0, 45))
        btn_shadow.setOffset(0, 4)
        self.btn_main.setGraphicsEffect(btn_shadow)
        center_box.addWidget(self.btn_main, alignment=Qt.AlignmentFlag.AlignCenter)

        preset_row = QHBoxLayout()
        preset_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preset_row.setSpacing(6)

        lbl_pres_prefix = QLabel("Маскировка:")
        lbl_pres_prefix.setStyleSheet("font-size: 10px; font-weight: 700; color: #64748b; letter-spacing: 0.5px;")
        preset_row.addWidget(lbl_pres_prefix)

        self.combo_dashboard_preset = QComboBox()
        self.combo_dashboard_preset.setObjectName("combo_dashboard_preset")
        self.combo_dashboard_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_dashboard_preset.setToolTip("Выберите профиль маскировки трафика перед ТСПУ")
        self.combo_dashboard_preset.setFixedWidth(138)
        for key, p in PRESETS.items():
            self.combo_dashboard_preset.addItem(p["name"], key)
        self._setup_light_combobox(self.combo_dashboard_preset)
        self.combo_dashboard_preset.currentIndexChanged.connect(self._on_dashboard_preset_changed)
        preset_row.addWidget(self.combo_dashboard_preset)

        center_box.addLayout(preset_row)

        layout.addLayout(center_box)
        layout.addSpacing(2)

        mode_section = self._create_mode_segmented_control()
        layout.addWidget(mode_section)

        self.proxy_info_card = self._create_local_proxy_card()
        self.proxy_info_card.setVisible(False)
        layout.addWidget(self.proxy_info_card)

        layout.addStretch(1)

        metrics_card = self._create_metrics_card()
        layout.addWidget(metrics_card)
        layout.addSpacing(6)

        links_box = QHBoxLayout()
        links_box.setSpacing(8)

        tg_icon_path = self.app_root / "assets" / "telegram.png"
        tg_icon = QIcon(str(tg_icon_path)) if tg_icon_path.exists() else QIcon()

        _links = get_secrets().get("links", {})
        self.btn_telegram = AnimatedLinkButton(
            " Telegram",
            _links.get("telegram", "https://t.me/"),
            base_color="#229ED9",
            hover_color="#2baee5",
            pressed_color="#1a80b3",
            icon=tg_icon
        )

        self.btn_website = AnimatedLinkButton(
            "🤮 Сайт",
            _links.get("website", "https://example.com"),
            base_color="#1e293b",
            hover_color="#334155",
            pressed_color="#0f172a"
        )

        links_box.addWidget(self.btn_telegram)
        links_box.addWidget(self.btn_website)
        layout.addLayout(links_box)

        return page

    def _create_mode_segmented_control(self) -> QWidget:
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 2, 0, 2)
        vbox.setSpacing(5)

        lbl_hdr = QLabel("РЕЖИМ МАРШРУТИЗАЦИИ:")
        lbl_hdr.setStyleSheet("border: none; background: transparent; font-size: 9px; font-weight: 800; color: #64748b; letter-spacing: 0.8px;")
        vbox.addWidget(lbl_hdr)

        bar = QFrame()
        bar.setObjectName("mode_segmented_bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(3)

        self.mode_buttons: List[QPushButton] = []
        modes = [
            ("🛡️ TUN", 0, "100% сетевого трафика компьютера через туннель"),
            ("🌐 Системный", 1, "Системный прокси Windows для браузеров и служб"),
            ("🔌 Локальный", 2, "Локальные SOCKS5 и HTTP порты"),
        ]

        for text, mode_id, tip in modes:
            btn = QPushButton(text)
            btn.setProperty("class", "mode_segment")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda checked=False, m=mode_id: self._select_mode(m))
            self.mode_buttons.append(btn)
            layout.addWidget(btn)

        vbox.addWidget(bar)

        self.lbl_mode_desc = QLabel("100% сетевого трафика компьютера направляется через туннель")
        self.lbl_mode_desc.setStyleSheet("color: #64748b; font-size: 9.5px; font-weight: 500; padding-left: 2px;")
        vbox.addWidget(self.lbl_mode_desc)

        self._update_mode_segments()
        return container

    def _select_mode(self, mode_id: int):
        if not self.mode_controls_enabled:
            return
        self.current_routing_mode = mode_id
        self._update_mode_segments()
        self._on_mode_toggled()
        self._save_user_settings()

    def _update_mode_segments(self):
        descriptions = {
            0: "100% сетевого трафика компьютера направляется через туннель",
            1: "Системный прокси Windows (браузеры и системные службы)",
            2: "SOCKS5 и HTTP порты для ручной настройки программ"
        }
        for i, btn in enumerate(self.mode_buttons):
            is_active = (i == self.current_routing_mode)
            btn.setProperty("active", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if hasattr(self, "lbl_mode_desc"):
            self.lbl_mode_desc.setText(descriptions.get(self.current_routing_mode, ""))

    def _create_local_proxy_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("class", "card")
        p_layout = QVBoxLayout(card)
        p_layout.setSpacing(4)
        p_layout.setContentsMargins(10, 8, 10, 8)

        row_socks = QHBoxLayout()
        lbl_socks = QLabel("SOCKS5: 127.0.0.1:10808")
        lbl_socks.setStyleSheet("font-family: Consolas, monospace; font-size: 10px; font-weight: 700; color: #0f172a;")
        row_socks.addWidget(lbl_socks)
        row_socks.addStretch()
        self.btn_copy_socks = QPushButton("📋 Копировать")
        self.btn_copy_socks.setProperty("class", "copy_btn")
        self.btn_copy_socks.clicked.connect(lambda: self._copy_to_clipboard("127.0.0.1:10808", self.btn_copy_socks))
        row_socks.addWidget(self.btn_copy_socks)
        p_layout.addLayout(row_socks)

        row_http = QHBoxLayout()
        lbl_http = QLabel("HTTP:   127.0.0.1:10809")
        lbl_http.setStyleSheet("font-family: Consolas, monospace; font-size: 10px; font-weight: 700; color: #0f172a;")
        row_http.addWidget(lbl_http)
        row_http.addStretch()
        self.btn_copy_http = QPushButton("📋 Копировать")
        self.btn_copy_http.setProperty("class", "copy_btn")
        self.btn_copy_http.clicked.connect(lambda: self._copy_to_clipboard("http://127.0.0.1:10809", self.btn_copy_http))
        row_http.addWidget(self.btn_copy_http)
        p_layout.addLayout(row_http)

        self.btn_tg_proxy = QPushButton("✈️ Подключить Telegram к SOCKS5")
        self.btn_tg_proxy.setProperty("class", "secondary_btn")
        self.btn_tg_proxy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tg_proxy.clicked.connect(self._open_telegram_proxy)
        p_layout.addWidget(self.btn_tg_proxy)

        return card

    def _create_metrics_card(self) -> QFrame:
        frame = QFrame()
        frame.setProperty("class", "card")
        m_layout = QHBoxLayout(frame)
        m_layout.setSpacing(2)
        m_layout.setContentsMargins(6, 6, 6, 6)

        self.stat_down = self._create_mini_stat("Вход", "0.0 KB/s")
        self.stat_up = self._create_mini_stat("Исход", "0.0 KB/s")
        self.stat_ping = self._create_mini_stat("Пинг", "-- ms")
        self.stat_dns = self._create_mini_stat("DNS", "Amnezia")

        m_layout.addLayout(self.stat_down["layout"])
        m_layout.addLayout(self.stat_up["layout"])
        m_layout.addLayout(self.stat_ping["layout"])
        m_layout.addLayout(self.stat_dns["layout"])

        return frame

    def _create_mini_stat(self, title: str, value: str):
        vl = QVBoxLayout()
        vl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vl.setSpacing(1)
        vl.setContentsMargins(0, 0, 0, 0)
        lbl_t = QLabel(title)
        lbl_t.setStyleSheet("border: none; background: transparent; font-size: 9px; font-weight: 700; color: #64748b; text-transform: uppercase;")
        lbl_v = QLabel(value)
        lbl_v.setStyleSheet("border: none; background: transparent; font-size: 11px; font-weight: 800; color: #09090b;")
        vl.addWidget(lbl_t, alignment=Qt.AlignmentFlag.AlignCenter)
        vl.addWidget(lbl_v, alignment=Qt.AlignmentFlag.AlignCenter)
        return {"layout": vl, "val": lbl_v}

    def _build_apps_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("apps_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        info_card = QFrame()
        info_card.setProperty("class", "card")
        ic_layout = QVBoxLayout(info_card)
        ic_layout.setContentsMargins(10, 8, 10, 8)
        ic_layout.setSpacing(3)

        lbl_title = QLabel("🎯 Маршрутизация приложений")
        lbl_title.setStyleSheet("font-size: 11px; font-weight: 700; color: #09090b;")
        lbl_sub = QLabel("Выбранные программы и игры направляются через изолированный TUN туннель.")
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet("font-size: 9.5px; color: #64748b;")
        ic_layout.addWidget(lbl_title)
        ic_layout.addWidget(lbl_sub)
        layout.addWidget(info_card)

        chips_box = QHBoxLayout()
        chips_box.setSpacing(4)
        lbl_quick = QLabel("Быстро:")
        lbl_quick.setStyleSheet("color: #64748b; font-size: 10px; font-weight: 700;")
        chips_box.addWidget(lbl_quick)

        for name, exe in [("Discord", "discord.exe"), ("Telegram", "telegram.exe"), ("Steam", "steam.exe"), ("CS2", "cs2.exe")]:
            btn_chip = QPushButton(f"+ {name}")
            btn_chip.setProperty("class", "chip_btn")
            btn_chip.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_chip.clicked.connect(lambda checked=False, n=name, e=exe: self._add_tun_app(n, e))
            chips_box.addWidget(btn_chip)
        chips_box.addStretch()
        layout.addLayout(chips_box)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.apps_scroll_content = QWidget()
        self.apps_scroll_content.setStyleSheet("background: transparent;")
        self.tun_apps_list_layout = QVBoxLayout(self.apps_scroll_content)
        self.tun_apps_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tun_apps_list_layout.setSpacing(4)
        self.tun_apps_list_layout.setContentsMargins(0, 0, 4, 0)

        scroll.setWidget(self.apps_scroll_content)
        layout.addWidget(scroll, 1)

        actions_box = QVBoxLayout()
        actions_box.setSpacing(4)

        self.btn_launch_tun_apps = QPushButton("🚀 Запустить выбранные в TUN")
        self.btn_launch_tun_apps.setProperty("class", "secondary_btn")
        self.btn_launch_tun_apps.setFixedHeight(30)
        self.btn_launch_tun_apps.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_launch_tun_apps.clicked.connect(self._launch_selected_tun_apps)
        actions_box.addWidget(self.btn_launch_tun_apps)

        btn_add_custom = QPushButton("➕ Добавить другой исполняемый файл (.exe)...")
        btn_add_custom.setProperty("class", "chip_btn")
        btn_add_custom.setFixedHeight(24)
        btn_add_custom.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_custom.clicked.connect(self._browse_and_add_tun_app)
        actions_box.addWidget(btn_add_custom)

        layout.addLayout(actions_box)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settings_page")
        main_l = QVBoxLayout(page)
        main_l.setContentsMargins(0, 4, 0, 0)
        main_l.setSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        l = QVBoxLayout(content)
        l.setSpacing(8)
        l.setContentsMargins(0, 0, 4, 14)

        card_profile = QFrame()
        card_profile.setProperty("class", "card")
        cp_layout = QVBoxLayout(card_profile)
        cp_layout.setContentsMargins(10, 8, 10, 8)
        cp_layout.setSpacing(5)

        cp_header = QLabel("🔑 Профиль и Устройство")
        cp_header.setStyleSheet("font-size: 11px; font-weight: 700; color: #09090b;")
        cp_layout.addWidget(cp_header)

        hwid_row = QHBoxLayout()
        lbl_hwid_t = QLabel("HWID ПК:")
        lbl_hwid_t.setStyleSheet("color: #64748b; font-size: 10px; font-weight: 600;")
        lbl_hwid_v = QLabel(self.profile_mgr.get_hwid_short())
        lbl_hwid_v.setToolTip(f"Полный аппаратный ID: {self.profile_mgr.hwid}")
        lbl_hwid_v.setStyleSheet("color: #09090b; font-size: 10px; font-family: Consolas, monospace; font-weight: 600;")
        hwid_row.addWidget(lbl_hwid_t)
        hwid_row.addWidget(lbl_hwid_v)
        hwid_row.addStretch()
        btn_copy_hwid = QPushButton("📋")
        btn_copy_hwid.setProperty("class", "copy_btn")
        btn_copy_hwid.setToolTip("Скопировать полный HWID")
        btn_copy_hwid.clicked.connect(lambda: self._copy_to_clipboard(self.profile_mgr.hwid, btn_copy_hwid))
        hwid_row.addWidget(btn_copy_hwid)
        cp_layout.addLayout(hwid_row)

        uuid_row = QHBoxLayout()
        uuid_row.setSpacing(6)
        lbl_uuid_t = QLabel("ID профиля:")
        lbl_uuid_t.setStyleSheet("color: #64748b; font-size: 10px; font-weight: 600;")
        uuid_row.addWidget(lbl_uuid_t)

        disp_uuid = f"{self.remote_uuid[:8]}...{self.remote_uuid[-6:]}" if len(self.remote_uuid) > 16 else self.remote_uuid
        self.btn_profile_id = QPushButton(f"{disp_uuid} 📋")
        self.btn_profile_id.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_profile_id.setToolTip(f"Нажмите, чтобы скопировать ID:\n{self.remote_uuid}")
        self.btn_profile_id.setProperty("class", "chip_btn")
        self.btn_profile_id.clicked.connect(self._copy_profile_id)
        uuid_row.addWidget(self.btn_profile_id)
        uuid_row.addStretch()
        cp_layout.addLayout(uuid_row)

        lbl_hwid_info = QLabel("🟢 Синхронизирован с сервером")
        lbl_hwid_info.setStyleSheet("color: #10b981; font-size: 9.5px; font-weight: 600;")
        cp_layout.addWidget(lbl_hwid_info)
        l.addWidget(card_profile)

        card_preset = QFrame()
        card_preset.setProperty("class", "card")
        pre_layout = QVBoxLayout(card_preset)
        pre_layout.setContentsMargins(10, 8, 10, 8)
        pre_layout.setSpacing(5)

        pre_header = QLabel("🕶️ Маскировка ТСПУ")
        pre_header.setStyleSheet("font-size: 11px; font-weight: 700; color: #09090b;")
        pre_layout.addWidget(pre_header)

        self.preset_combo = QComboBox()
        for key, p in PRESETS.items():
            self.preset_combo.addItem(p["name"], key)
        ghost_idx = self.preset_combo.findData("stealth_ghost")
        if ghost_idx >= 0:
            self.preset_combo.setCurrentIndex(ghost_idx)
        self._setup_light_combobox(self.preset_combo)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        pre_layout.addWidget(self.preset_combo)

        default_preset = PRESETS.get("stealth_ghost", next(iter(PRESETS.values())))
        self.preset_desc_label = QLabel(default_preset["description"])
        self.preset_desc_label.setWordWrap(True)
        self.preset_desc_label.setStyleSheet("color: #64748b; font-size: 9.5px; margin-top: 1px;")
        pre_layout.addWidget(self.preset_desc_label)
        l.addWidget(card_preset)

        card_system = QFrame()
        card_system.setProperty("class", "card")
        sys_layout = QVBoxLayout(card_system)
        sys_layout.setContentsMargins(10, 8, 10, 8)
        sys_layout.setSpacing(5)

        sys_header = QLabel("⚙️ Системные параметры")
        sys_header.setStyleSheet("font-size: 11px; font-weight: 700; color: #09090b;")
        sys_layout.addWidget(sys_header)

        self.check_autostart = QCheckBox()
        self.check_autostart.setChecked(is_autostart_enabled())
        tile_autostart = self._create_setting_tile(
            "Автозапуск с Windows",
            "Запуск FQoF Nexus в фоновом режиме при входе в систему",
            self.check_autostart
        )
        sys_layout.addWidget(tile_autostart)

        self.check_auto_amnezia_dns = QCheckBox()
        self.check_auto_amnezia_dns.setChecked(True)
        tile_dns = self._create_setting_tile(
            "Защита от DNS-Leak",
            "Шифрование DNS-запросов через защищенный Amnezia DNS",
            self.check_auto_amnezia_dns
        )
        sys_layout.addWidget(tile_dns)

        self.check_ru_bypass = QCheckBox()
        self.check_ru_bypass.setChecked(True)
        tile_ru = self._create_setting_tile(
            "РФ сайты напрямую (ru-bypass)",
            "Госуслуги, банки, Кинопоиск и VK в обход VPN",
            self.check_ru_bypass
        )
        sys_layout.addWidget(tile_ru)
        l.addWidget(card_system)

        card_logs = QFrame()
        card_logs.setProperty("class", "card")
        logs_layout = QVBoxLayout(card_logs)
        logs_layout.setContentsMargins(10, 8, 10, 8)
        logs_layout.setSpacing(5)

        logs_hdr_box = QHBoxLayout()
        lbl_logs = QLabel("📋 Журнал событий")
        lbl_logs.setStyleSheet("font-size: 11px; font-weight: 700; color: #09090b;")
        logs_hdr_box.addWidget(lbl_logs)
        logs_hdr_box.addStretch()

        self.btn_copy_logs = QPushButton("📋 Копировать")
        self.btn_copy_logs.setProperty("class", "copy_btn")
        self.btn_copy_logs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_logs.clicked.connect(self._copy_all_logs)
        logs_hdr_box.addWidget(self.btn_copy_logs)

        btn_clear_logs = QPushButton("🗑️ Очистить")
        btn_clear_logs.setProperty("class", "copy_btn")
        btn_clear_logs.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear_logs.clicked.connect(lambda: self.log_view.clear())
        logs_hdr_box.addWidget(btn_clear_logs)
        logs_layout.addLayout(logs_hdr_box)

        self.log_view = LogTextEdit()
        self.log_view.setObjectName("log_view")
        self.log_view.setFixedHeight(85)
        self.log_view.setReadOnly(True)
        logs_layout.addWidget(self.log_view)
        l.addWidget(card_logs)

        scroll.setWidget(content)
        main_l.addWidget(scroll, 1)
        return page

    def _create_setting_tile(self, title: str, subtitle: str, checkbox: QCheckBox) -> QFrame:
        tile = QFrame()
        tile.setProperty("class", "setting_tile")
        layout = QHBoxLayout(tile)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(8)

        text_vbox = QVBoxLayout()
        text_vbox.setSpacing(1)
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 11px; font-weight: 700; color: #09090b;")
        lbl_sub = QLabel(subtitle)
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet("font-size: 9.5px; color: #64748b;")
        text_vbox.addWidget(lbl_title)
        text_vbox.addWidget(lbl_sub)

        layout.addLayout(text_vbox, 1)
        layout.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        tile.setCursor(Qt.CursorShape.PointingHandCursor)
        tile.mousePressEvent = lambda e: checkbox.toggle() if checkbox.isEnabled() else None
        return tile

    def _init_tray(self):
        self._tray_anim_timer = QTimer(self)
        self._tray_anim_timer.setInterval(50)
        self._tray_anim_timer.timeout.connect(self._on_tray_anim_tick)

        tray_logo_path = self.app_root / "assets" / "logo_tray.png"
        if tray_logo_path.exists():
            self._tray_base_img = QImage(str(tray_logo_path))
        else:
            self._tray_base_img = None

        self._pregenerate_tray_frames()

        self.tray_icon = QSystemTrayIcon(self)
        self._set_tray_state("disconnected")
        self.tray_icon.setToolTip("FQoF · Nexus")

        tray_menu = QMenu()
        self.tray_title_action = tray_menu.addAction("● FQoF · Nexus")
        self.tray_title_action.setEnabled(False)
        tray_menu.addSeparator()

        self.tray_toggle_action = tray_menu.addAction("Подключиться")
        self.tray_toggle_action.triggered.connect(self._toggle_connection)

        action_restore = tray_menu.addAction("Развернуть окно")
        action_restore.triggered.connect(self._restore_from_tray)

        tray_menu.addSeparator()
        action_quit = tray_menu.addAction("Выход")
        action_quit.triggered.connect(self._force_quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _pregenerate_tray_frames(self):
        self._tray_frames_connecting = [self._draw_tray_icon("connecting", angle=i * 10) for i in range(36)]
        self._tray_frames_disconnecting = [self._draw_tray_icon("disconnecting", angle=-i * 10) for i in range(36)]
        self._tray_frame_idx = 0

    def _draw_tray_icon(self, state: str = "disconnected", angle: float = 0.0) -> QIcon:
        size = 32
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        if getattr(self, "_tray_base_img", None) and not self._tray_base_img.isNull():
            painter.drawImage(QRectF(1, 1, 30, 30), self._tray_base_img)
        else:
            painter.setBrush(QColor(24, 24, 27))
            painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
            painter.drawRoundedRect(QRectF(1, 1, 30, 30), 6.5, 6.5)

        cx, cy = 24.5, 24.5
        badge_r = 4.2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(9, 9, 11, 235))
        painter.drawEllipse(QPointF(cx, cy), badge_r + 1.2, badge_r + 1.2)

        if state == "connected":
            painter.setBrush(QColor("#10b981"))
            painter.drawEllipse(QPointF(cx, cy), badge_r, badge_r)
            painter.setBrush(QColor("#a7f3d0"))
            painter.drawEllipse(QPointF(cx - 1.0, cy - 1.0), 1.4, 1.4)
        elif state in ("connecting", "disconnecting"):
            color_base = QColor("#06b6d4") if state == "connecting" else QColor("#f59e0b")
            painter.setBrush(color_base)
            painter.drawEllipse(QPointF(cx, cy), badge_r, badge_r)
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(angle)
            pen = QPen(QColor("#ffffff"), 1.2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(-badge_r - 0.5, -badge_r - 0.5, (badge_r + 0.5) * 2, (badge_r + 0.5) * 2), 0, 16 * 120)
            painter.restore()
        elif state == "disconnected":
            painter.setBrush(QColor("#71717a"))
            painter.drawEllipse(QPointF(cx, cy), badge_r, badge_r)
        else:
            painter.setBrush(QColor("#ef4444"))
            painter.drawEllipse(QPointF(cx, cy), badge_r, badge_r)

        painter.end()
        return QIcon(pix)

    def _set_tray_state(self, state: str):
        self._tray_state = state
        if state in ("connecting", "disconnecting"):
            if not self._tray_anim_timer.isActive():
                self._tray_frame_idx = 0
                self._tray_anim_timer.start()
        else:
            self._tray_anim_timer.stop()
            self.tray_icon.setIcon(self._draw_tray_icon(state))

    def _on_tray_anim_tick(self):
        if self._tray_state == "connecting":
            frames = self._tray_frames_connecting
        elif self._tray_state == "disconnecting":
            frames = self._tray_frames_disconnecting
        else:
            self._tray_anim_timer.stop()
            return

        self._tray_frame_idx = (self._tray_frame_idx + 1) % len(frames)
        self.tray_icon.setIcon(frames[self._tray_frame_idx])

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible():
                self.hide()
            else:
                self._restore_from_tray()

    def _restore_from_tray(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event):
        if self._is_quitting:
            event.accept()
        else:
            event.ignore()
            self.hide()
            if self.tray_icon.isVisible():
                self.tray_icon.showMessage(
                    "FQoF · Nexus",
                    "Приложение свернуто в трей и продолжает защищать трафик",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )

    def _force_quit(self):
        self._is_quitting = True
        if self.is_connected:
            self._toggle_connection()
        self.backend.shutdown()
        QApplication.quit()

    def _connect_signals(self):
        self.backend.sig_ready.connect(self._on_backend_ready)
        self.backend.sig_started.connect(self._on_backend_started)
        self.backend.sig_stopped.connect(self._on_backend_stopped)
        self.backend.sig_stats.connect(self._on_backend_stats)
        self.backend.sig_log.connect(self._on_backend_log)
        self.backend.sig_error.connect(self._on_backend_error)
        self.backend.sig_ping.connect(self._on_backend_ping)
        self.sig_app_launch_result.connect(self._on_app_launch_result)

    def _refresh_tun_apps_ui(self):
        if not hasattr(self, "tun_apps_list_layout"):
            return

        while self.tun_apps_list_layout.count():
            item = self.tun_apps_list_layout.takeAt(0)
            if item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()

        if not self.tun_apps:
            lbl_empty = QLabel("Список пуст. Добавьте игру или программу кнопками выше.")
            lbl_empty.setStyleSheet("color: #94a3b8; font-size: 10px; font-style: italic; padding: 6px;")
            self.tun_apps_list_layout.addWidget(lbl_empty)
            self._update_tun_status_badge()
            self._update_launch_btn_label()
            return

        for app in self.tun_apps:
            card = QFrame()
            card.setProperty("class", "app_card")
            row = QHBoxLayout(card)
            row.setContentsMargins(8, 4, 8, 4)
            row.setSpacing(6)

            chk = QCheckBox(app["name"])
            chk.setChecked(app.get("enabled", True))
            p_display = app.get("path") or "Авто-определение"
            chk.setToolTip(f"Исполняемый файл: {app['exe']}\nПуть: {p_display}")
            chk.setStyleSheet("font-size: 11px; font-weight: 600; color: #0f172a;")
            chk.stateChanged.connect(lambda state, e=app["exe"]: self._toggle_tun_app(e, state == 2))
            row.addWidget(chk, 1)

            btn_launch = QPushButton("🚀 Старт")
            btn_launch.setToolTip(f"Запустить {app['name']} в защищенном TUN")
            btn_launch.setProperty("class", "chip_btn")
            btn_launch.setFixedHeight(22)
            btn_launch.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_launch.clicked.connect(lambda checked=False, a=app: self._launch_app_in_tun(a))
            row.addWidget(btn_launch)

            btn_del = QPushButton("✕")
            btn_del.setToolTip(f"Удалить {app['name']} из списка")
            btn_del.setProperty("class", "chip_btn")
            btn_del.setStyleSheet("font-size: 10px; font-weight: bold; color: #64748b; padding: 0px;")
            btn_del.setFixedSize(22, 22)
            btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_del.clicked.connect(lambda checked=False, e=app["exe"]: self._remove_tun_app(e))
            row.addWidget(btn_del)

            self.tun_apps_list_layout.addWidget(card)

        self._update_tun_status_badge()
        self._update_launch_btn_label()

    def _add_tun_app(self, name: str, exe: str, path: str = "") -> dict:
        exe_clean = exe.lower().strip()
        if not path or not os.path.isfile(path):
            path = find_app_binary(exe_clean) or find_app_binary(name) or ""

        for a in self.tun_apps:
            if a["exe"].lower() == exe_clean:
                a["enabled"] = True
                if path:
                    a["path"] = path
                self._save_user_settings()
                self._refresh_tun_apps_ui()
                self._sync_tun_backend()
                return a
        new_app = {
            "name": name,
            "exe": exe_clean,
            "path": path,
            "enabled": True
        }
        self.tun_apps.append(new_app)
        self._save_user_settings()
        self._refresh_tun_apps_ui()
        self._sync_tun_backend()
        self._log(f"🎯 В TUN добавлено приложение: {name} ({exe_clean})")
        return new_app

    def _remove_tun_app(self, exe: str):
        exe_clean = exe.lower().strip()
        self.tun_apps = [a for a in self.tun_apps if a["exe"].lower() != exe_clean]
        self._save_user_settings()
        self._refresh_tun_apps_ui()
        self._sync_tun_backend()
        self._log(f"🗑️ Из TUN удалено: {exe_clean}")

    def _toggle_tun_app(self, exe: str, state: bool):
        exe_clean = exe.lower().strip()
        for a in self.tun_apps:
            if a["exe"].lower() == exe_clean:
                a["enabled"] = state
                break
        self._save_user_settings()
        self._sync_tun_backend()
        self._update_tun_status_badge()
        self._update_launch_btn_label()

    def _sync_tun_backend(self):
        if not self.is_connected:
            return
        is_full_tun = (self.current_routing_mode == 0)
        enabled_apps = [a["exe"].lower() for a in getattr(self, "tun_apps", []) if a.get("enabled", True)]
        self.backend.update_tun_apps(enabled_apps, full_mode=is_full_tun)

    def _update_tun_status_badge(self):
        pass

    def _update_launch_btn_label(self):
        if not hasattr(self, "btn_launch_tun_apps"):
            return
        enabled_apps = [a for a in getattr(self, "tun_apps", []) if a.get("enabled", True)]
        if not enabled_apps:
            self.btn_launch_tun_apps.setText("🚀 Запустить в TUN")
            self.btn_launch_tun_apps.setEnabled(False)
        elif len(enabled_apps) == 1:
            self.btn_launch_tun_apps.setText(f"🚀 Запустить {enabled_apps[0]['name']} в TUN")
            self.btn_launch_tun_apps.setEnabled(True)
        else:
            self.btn_launch_tun_apps.setText(f"🚀 Запустить в TUN ({len(enabled_apps)})")
            self.btn_launch_tun_apps.setEnabled(True)

    def _browse_and_add_tun_app(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите исполняемый файл приложения или игры",
            "C:\\",
            "Исполняемые файлы (*.exe)"
        )
        if not file_path:
            return
        exe_name = os.path.basename(file_path)
        name = os.path.splitext(exe_name)[0]
        self._add_tun_app(name, exe_name, file_path)

    def _launch_selected_tun_apps(self):
        enabled_apps = [a for a in getattr(self, "tun_apps", []) if a.get("enabled", True)]
        if not enabled_apps:
            self._log("⚠️ В списке TUN нет активных приложений. Отметьте галочкой приложение выше.")
            return
        for app in enabled_apps:
            self._launch_app_in_tun(app)

    def _launch_app_in_tun(self, app_info: dict):
        exe_name = app_info.get("exe", "")
        exe_path = app_info.get("path", "")
        app_name = app_info.get("name", exe_name)

        app_info["enabled"] = True
        self._save_user_settings()
        self._refresh_tun_apps_ui()

        if not exe_path or not os.path.isfile(exe_path):
            detected = find_app_binary(exe_name) or find_app_binary(app_name)
            if detected and os.path.isfile(detected):
                exe_path = detected
                app_info["path"] = exe_path
                self._save_user_settings()

        if not exe_path or not os.path.isfile(exe_path):
            chosen, _ = QFileDialog.getOpenFileName(
                self,
                f"Укажите путь к файлу {app_name} ({exe_name})",
                "C:\\",
                "Исполняемые файлы (*.exe)"
            )
            if not chosen:
                self._log(f"⚠️ Запуск отменен: путь к {exe_name} не найден")
                return
            exe_path = chosen
            app_info["path"] = exe_path
            self._save_user_settings()

        if not self.is_connected:
            self._log(f"🚀 [TUN] Включение туннеля для запуска {app_name}...")
            if not hasattr(self, "_pending_apps_to_launch"):
                self._pending_apps_to_launch = []
            self._pending_apps_to_launch.append(app_info)
            self._start_connection()
            return

        self._sync_tun_backend()
        self._execute_app_process(app_name, exe_path, exe_name)

    def _execute_app_process(self, app_name: str, exe_path: str, exe_name: str):
        try:
            restarted = restart_or_launch_app(app_name, exe_path)
            if restarted:
                self._log(f"🔄 [TUN] {app_name} перезапущен для работы в изолированном туннеле!")
            else:
                self._log(f"🚀 [TUN] {app_name} успешно запущен в изолированном туннеле!")
        except Exception as e:
            self._log(f"❌ Ошибка запуска {app_name}: {e}")

    def _on_app_launch_result(self, success: bool, message: str):
        if success:
            self._log(f"✅ {message}")
        else:
            self._log(f"❌ {message}")

    def _set_mode_controls_enabled(self, enabled: bool):
        self.mode_controls_enabled = enabled
        for btn in getattr(self, "mode_buttons", []):
            btn.setEnabled(enabled)

        if hasattr(self, "combo_dashboard_preset"):
            self.combo_dashboard_preset.setEnabled(enabled)
            tip = "" if enabled else "Отключитесь от VPN для изменения маскировки"
            self.combo_dashboard_preset.setToolTip(tip)
        if hasattr(self, "preset_combo"):
            self.preset_combo.setEnabled(enabled)
            tip = "" if enabled else "Отключитесь от VPN для изменения маскировки"
            self.preset_combo.setToolTip(tip)
        if hasattr(self, "check_auto_amnezia_dns"):
            self.check_auto_amnezia_dns.setEnabled(enabled)
        if hasattr(self, "check_ru_bypass"):
            self.check_ru_bypass.setEnabled(enabled)

    def _load_user_settings(self) -> dict:
        defaults = {
            "routing_mode": 0,
            "preset_key": "stealth_ghost",
            "auto_amnezia_dns": True,
            "ru_bypass": True,
            "tun_apps_enabled": True,
            "tun_apps": []
        }
        if hasattr(self, "settings_file") and self.settings_file.exists():
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        defaults.update(data)
            except Exception:
                pass

        for app in defaults.get("tun_apps", []):
            if not app.get("path") or not os.path.isfile(app["path"]):
                found = find_app_binary(app.get("exe") or app.get("name", ""))
                if found:
                    app["path"] = found

        return defaults

    def _save_user_settings(self):
        if not hasattr(self, "settings_file"):
            return
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            preset_key = self.combo_dashboard_preset.currentData() if hasattr(self, "combo_dashboard_preset") else (self.preset_combo.currentData() if hasattr(self, "preset_combo") else "stealth_ghost")
            settings = {
                "routing_mode": self.current_routing_mode,
                "preset_key": preset_key or "stealth_ghost",
                "auto_amnezia_dns": self.check_auto_amnezia_dns.isChecked() if hasattr(self, "check_auto_amnezia_dns") else True,
                "ru_bypass": self.check_ru_bypass.isChecked() if hasattr(self, "check_ru_bypass") else True,
                "autostart": self.check_autostart.isChecked() if hasattr(self, "check_autostart") else False,
                "tun_apps": getattr(self, "tun_apps", [])
            }
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _apply_user_settings(self):
        s = getattr(self, "_user_settings", {})
        self.current_routing_mode = s.get("routing_mode", 0)
        self._update_mode_segments()
        self._on_mode_toggled()

        preset_key = s.get("preset_key", "stealth_ghost")
        if hasattr(self, "preset_combo"):
            idx = self.preset_combo.findData(preset_key)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
        if hasattr(self, "combo_dashboard_preset"):
            idx_dash = self.combo_dashboard_preset.findData(preset_key)
            if idx_dash >= 0:
                self.combo_dashboard_preset.setCurrentIndex(idx_dash)
        self._update_preset_desc(preset_key)

        self.check_auto_amnezia_dns.setChecked(s.get("auto_amnezia_dns", True))

        if hasattr(self, "check_ru_bypass"):
            self.check_ru_bypass.setChecked(s.get("ru_bypass", True))

        if hasattr(self, "check_autostart"):
            is_enabled = is_autostart_enabled()
            saved_autostart = s.get("autostart", None)
            if saved_autostart is not None and saved_autostart != is_enabled:
                set_autostart(saved_autostart, minimized=True)
                is_enabled = saved_autostart
            self.check_autostart.setChecked(is_enabled)
            self.check_autostart.toggled.connect(self._on_autostart_toggled)

        self.tun_apps = s.get("tun_apps", [])
        self._refresh_tun_apps_ui()

        self.check_auto_amnezia_dns.toggled.connect(lambda _val: self._save_user_settings())
        if hasattr(self, "check_ru_bypass"):
            self.check_ru_bypass.toggled.connect(lambda _val: self._save_user_settings())

    def _on_autostart_toggled(self, checked: bool):
        ok, msg = set_autostart(checked, minimized=True)
        self._log(f"🚀 {msg}")
        self._save_user_settings()

    def _on_mode_toggled(self):
        is_local = (self.current_routing_mode == 2)
        if hasattr(self, "proxy_info_card"):
            self.proxy_info_card.setVisible(is_local)
        self._update_tun_status_badge()

    def _copy_profile_id(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.remote_uuid)
        disp = f"{self.remote_uuid[:8]}...{self.remote_uuid[-6:]}" if len(self.remote_uuid) > 16 else self.remote_uuid
        self.btn_profile_id.setText("✅ Скопировано!")
        QTimer.singleShot(1400, lambda: self.btn_profile_id.setText(f"{disp} 📋"))

    def _copy_to_clipboard(self, text: str, btn: QPushButton):
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        old_text = btn.text()
        if old_text == "📋":
            btn.setText("✅")
            btn.setToolTip("Скопировано в буфер!")
        else:
            btn.setText("✅ Скопировано!")
        QTimer.singleShot(1400, lambda: btn.setText(old_text))

    def _copy_all_logs(self):
        text = self.log_view.toPlainText()
        if not text:
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        old_text = self.btn_copy_logs.text()
        self.btn_copy_logs.setText("✅ Скопировано!")
        QTimer.singleShot(1400, lambda: self.btn_copy_logs.setText(old_text))

    def _on_dashboard_preset_changed(self, index: int):
        if not self.combo_dashboard_preset.isEnabled():
            return
        key = self.combo_dashboard_preset.currentData()
        if hasattr(self, "preset_combo") and self.preset_combo.currentData() != key:
            idx = self.preset_combo.findData(key)
            if idx >= 0:
                self.preset_combo.blockSignals(True)
                self.preset_combo.setCurrentIndex(idx)
                self.preset_combo.blockSignals(False)
        self._update_preset_desc(key)
        self._save_user_settings()

    def _on_preset_changed(self, index: int):
        if not self.preset_combo.isEnabled():
            return
        key = self.preset_combo.currentData()
        if hasattr(self, "combo_dashboard_preset") and self.combo_dashboard_preset.currentData() != key:
            idx = self.combo_dashboard_preset.findData(key)
            if idx >= 0:
                self.combo_dashboard_preset.blockSignals(True)
                self.combo_dashboard_preset.setCurrentIndex(idx)
                self.combo_dashboard_preset.blockSignals(False)
        self._update_preset_desc(key)
        self._save_user_settings()

    def _update_preset_desc(self, key: str):
        preset = PRESETS.get(key)
        if not preset:
            return
        if hasattr(self, "preset_desc_label"):
            self.preset_desc_label.setText(preset["description"])

    def _toggle_connection(self):
        if self.is_connected:
            self.btn_main.setEnabled(False)
            self.btn_main.setText("ОТКЛЮЧЕНИЕ...")
            self._set_mode_controls_enabled(False)
            self._set_tray_state("disconnecting")
            self.tray_icon.setToolTip("FQoF · Nexus: Отключение...")
            self.tray_toggle_action.setText("Отключение...")
            self._log("⏹ Отключение туннеля...")
            if self.current_routing_mode == 1:
                if self.check_auto_amnezia_dns.isChecked():
                    SystemProxyManager.disable_dns()
                SystemProxyManager.disable_proxy()
            self.backend.stop_proxy()
        else:
            self._start_connection()

    def _start_connection(self):
        self._set_mode_controls_enabled(False)
        self._set_tray_state("connecting")
        self.tray_icon.setToolTip("FQoF · Nexus: Подключение...")
        self.tray_toggle_action.setText("Отключить")
        key = self.combo_dashboard_preset.currentData() if hasattr(self, "combo_dashboard_preset") else (self.preset_combo.currentData() if hasattr(self, "preset_combo") else "stealth_ghost")
        preset = PRESETS.get(key, {})
        preset_cfg = preset.get("config", {})
        base_mode = preset_cfg.get("mode", "vless_reality")
        preset_remote = preset_cfg.get("remote_proxy", {})

        is_full_tun = (self.current_routing_mode == 0)
        enabled_apps = [a["exe"].lower() for a in getattr(self, "tun_apps", []) if a.get("enabled", True)]
        is_per_app_tun = (not is_full_tun and len(enabled_apps) > 0)
        tun_active_needed = is_full_tun or is_per_app_tun

        device_name = "FQoF" if os.name == "nt" else "tun0"

        host = preset_remote.get("host") or self.remote_host
        port = preset_remote.get("port") or self.remote_port
        sni = preset_remote.get("sni") or self.remote_sni

        config = {
            "mode": base_mode,
            "bind_host": "127.0.0.1",
            "socks_port": self.current_socks_port,
            "http_port": self.current_http_port,
            "remote_proxy": {
                "host": host,
                "port": port,
                "username": self.remote_user,
                "password": self.remote_pass,
                "uuid": self.remote_uuid or preset_remote.get("uuid") or get_secrets().get("server", {}).get("uuid", "00000000-0000-0000-0000-000000000000"),
                "path": preset_remote.get("path") or self.remote_path,
                "sni": sni,
                "reality_public_key": preset_remote.get("reality_public_key") or self.reality_public_key,
                "reality_short_id": preset_remote.get("reality_short_id") or self.reality_short_id,
                "post_quantum_encryption": preset_remote.get("post_quantum_encryption") or self.pq_encryption,
                "skip_cert_verify": False
            },
            "dpi": preset_cfg.get("dpi", {
                "enabled": True,
                "strategy": "ghost_dual_split",
                "split_delay_ms": 3,
                "fake_sni": None,
                "http_host_case_toggle": True
            }),
            "dns": {
                "enabled": self.check_auto_amnezia_dns.isChecked(),
                "local_port": self.current_dns_port,
                "remote_host": "172.29.172.254",
                "remote_port": 53
            },
            "tun": {
                "enabled": tun_active_needed,
                "full_mode": is_full_tun,
                "apps": enabled_apps if not is_full_tun else [],
                "device": device_name,
                "mtu": 1500
            },
            "ru_bypass": self.check_ru_bypass.isChecked() if hasattr(self, "check_ru_bypass") else True
        }

        self.btn_main.setEnabled(False)
        self.btn_main.setText("ПОДКЛЮЧЕНИЕ...")

        mode_names = {0: "TUN", 1: "Системный прокси", 2: "Локальный прокси"}
        mode_desc = mode_names.get(self.current_routing_mode, "TUN")
        if is_per_app_tun:
            apps_sample = ", ".join(enabled_apps[:3])
            mode_desc += f" + TUN [{apps_sample}]"
        self._log(f"🚀 Запуск {base_mode} [{mode_desc}]...")
        self.backend.start_proxy(config)

    def _open_telegram_proxy(self):
        url = QUrl(f"tg://socks?server=127.0.0.1&port={self.current_socks_port}")
        QDesktopServices.openUrl(url)
        self._log(f"✈️ Отправлен запрос подключения Telegram к SOCKS5 127.0.0.1:{self.current_socks_port}")

    def _ensure_sudoers_authorized(self):
        if os.name == "nt":
            return
        helper_symlink = Path("/usr/local/bin/stealthproxy_tun_helper")
        helper_script = Path(__file__).parent.parent / "bin" / "tun_helper.sh"
        try:
            if helper_symlink.exists():
                res = subprocess.run(["sudo", "-n", str(helper_symlink), "status"], capture_output=True, text=True)
                if res.returncode == 0:
                    return
            res = subprocess.run(["sudo", "-n", str(helper_script), "status"], capture_output=True, text=True)
            if res.returncode == 0:
                return
        except Exception:
            pass

        setup_script = Path(__file__).parent.parent / "scripts" / "setup_tun_sudoers.sh"
        if setup_script.exists():
            threading.Thread(target=lambda: subprocess.run(["bash", str(setup_script)], capture_output=True), daemon=True).start()

    def _try_autoload_user_proxy(self):
        proxy_path = Path(os.path.expanduser("~/PROXY"))
        if not proxy_path.exists():
            return
        try:
            content = proxy_path.read_text(encoding="utf-8", errors="ignore")
            host_m = re.search(r"Host\s*\|\s*([^\s\n]+)", content, re.IGNORECASE)
            port_m = re.search(r"Port\s*\|\s*(\d+)", content, re.IGNORECASE)
            uuid_m = re.search(r"UUID\s*\|\s*([a-f0-9\-]+)", content, re.IGNORECASE)
            path_m = re.search(r"Path\s*\|\s*([^\s\n]+)", content, re.IGNORECASE)
            sni_m = re.search(r"TLS SNI\s*\|\s*([^\s\n]+)", content, re.IGNORECASE)

            if host_m:
                self.remote_host = host_m.group(1).strip()
            if port_m:
                self.remote_port = int(port_m.group(1).strip())
            if uuid_m:
                self.remote_uuid = uuid_m.group(1).strip()
            if path_m:
                self.remote_path = path_m.group(1).strip()
            if sni_m:
                self.remote_sni = sni_m.group(1).strip()
        except Exception:
            pass

    def _on_backend_ready(self):
        self._log("✅ Ядро готово.")

    def _on_backend_started(self, socks_port: int, http_port: int, dns_port: object, mode: str, tun_active: bool = False):
        self.is_connected = True
        self.tun_active = tun_active
        self._set_mode_controls_enabled(False)
        self.btn_main.setEnabled(True)
        self.btn_main.setText("ОТКЛЮЧИТЬ")
        self.btn_main.setObjectName("btn_main_disconnect")
        self.btn_main.style().unpolish(self.btn_main)
        self.btn_main.style().polish(self.btn_main)

        if self.current_routing_mode == 1:
            ru_bp = self.check_ru_bypass.isChecked() if hasattr(self, "check_ru_bypass") else True
            ok, msg = SystemProxyManager.enable_proxy(socks_port, http_port, ru_bypass=ru_bp)
            self._log(f"🌐 {msg}")
            if self.check_auto_amnezia_dns.isChecked() and dns_port:
                ok, msg = SystemProxyManager.enable_dns(int(dns_port))
                self._log(f"🔒 {msg}")

        if self.current_routing_mode == 0:
            pill_text = "● Подключено (TUN)"
            self.stat_dns["val"].setText("TUN DNS")
        elif self.current_routing_mode == 1:
            pill_text = "● Подключено (Системный)"
            self.stat_dns["val"].setText("Amnezia")
        else:
            pill_text = "● Подключено (Локальный)"
            self.stat_dns["val"].setText("SOCKS5")
            self.proxy_info_card.setVisible(True)

        self.status_pill.setText(pill_text)
        self.status_pill.setStyleSheet("""
            background-color: #ecfdf5;
            color: #059669;
            padding: 4px 16px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 11px;
            border: 1.5px solid #a7f3d0;
        """)

        self._set_tray_state("connected")
        self.tray_icon.setToolTip(f"FQoF · Nexus: {pill_text}")
        self.tray_title_action.setText(f"● {pill_text}")
        self.tray_toggle_action.setText("Отключить")

        self._update_tun_status_badge()

        if hasattr(self, "_pending_apps_to_launch") and self._pending_apps_to_launch:
            pending = list(self._pending_apps_to_launch)
            self._pending_apps_to_launch.clear()
            QTimer.singleShot(350, lambda: [self._execute_app_process(a["name"], a["path"], a["exe"]) for a in pending])

        self._ping_timer.start()
        self.backend.test_ping(self.remote_host, self.remote_port)

    def _on_ping_timer_tick(self):
        if self.is_connected:
            self.backend.test_ping(self.remote_host, self.remote_port)

    def _on_backend_stopped(self):
        self._ping_timer.stop()
        self.is_connected = False
        self.tun_active = False
        if hasattr(self, "_pending_apps_to_launch"):
            self._pending_apps_to_launch.clear()
        self._set_mode_controls_enabled(True)
        self.btn_main.setEnabled(True)
        self.btn_main.setText("ПОДКЛЮЧИТЬСЯ")
        self.btn_main.setObjectName("btn_main_connect")
        self.btn_main.style().unpolish(self.btn_main)
        self.btn_main.style().polish(self.btn_main)

        self.status_pill.setText("● fuqoff?")
        self.status_pill.setStyleSheet("""
            background-color: #ffffff;
            color: #64748b;
            border: 1.5px solid #e2e8f0;
            padding: 4px 16px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 11px;
        """)

        self.stat_down["val"].setText("0.0 KB/s")
        self.stat_up["val"].setText("0.0 KB/s")
        self.stat_ping["val"].setText("-- ms")

        self._set_tray_state("disconnected")
        self.tray_icon.setToolTip("FQoF · Nexus")
        self.tray_title_action.setText("● FQoF · Nexus")
        self.tray_toggle_action.setText("Подключиться")

        self._update_tun_status_badge()

    def _on_backend_stats(self, data: dict):
        d_raw = float(data.get("download_speed") or data.get("download_rate") or 0.0)
        u_raw = float(data.get("upload_speed") or data.get("upload_rate") or 0.0)

        d_kb = d_raw / 1024.0
        u_kb = u_raw / 1024.0

        if d_kb >= 1024.0 * 1024.0:
            self.stat_down["val"].setText(f"{d_kb / (1024.0 * 1024.0):.2f} GB/s")
        elif d_kb >= 1024.0:
            self.stat_down["val"].setText(f"{d_kb / 1024.0:.1f} MB/s")
        else:
            self.stat_down["val"].setText(f"{d_kb:.1f} KB/s")

        if u_kb >= 1024.0 * 1024.0:
            self.stat_up["val"].setText(f"{u_kb / (1024.0 * 1024.0):.2f} GB/s")
        elif u_kb >= 1024.0:
            self.stat_up["val"].setText(f"{u_kb / 1024.0:.1f} MB/s")
        else:
            self.stat_up["val"].setText(f"{u_kb:.1f} KB/s")

    def _on_backend_log(self, level: str, message: str):
        self._log(f"[{level.upper()}] {message}")

    def _on_backend_error(self, message: str):
        self._ping_timer.stop()
        self._log(f"❌ {message}")
        self.is_connected = False
        self.tun_active = False
        self._set_mode_controls_enabled(True)
        self.btn_main.setEnabled(True)
        self.btn_main.setText("ПОДКЛЮЧИТЬСЯ")
        self.btn_main.setObjectName("btn_main_connect")
        self.btn_main.style().unpolish(self.btn_main)
        self.btn_main.style().polish(self.btn_main)

        self.status_pill.setText("● Ошибка подключения")
        self.status_pill.setStyleSheet("""
            background-color: #fef2f2;
            color: #dc2626;
            padding: 4px 16px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 11px;
            border: 1.5px solid #fecaca;
        """)
        self._set_tray_state("error")
        self.tray_icon.setToolTip("FQoF · Nexus: Ошибка подключения")
        self.tray_title_action.setText("● FQoF · Nexus (Ошибка)")
        self.tray_toggle_action.setText("Подключиться")
        self._update_tun_status_badge()

    def _on_backend_ping(self, latency_ms: object, error: object):
        if latency_ms is not None:
            self.stat_ping["val"].setText(f"{latency_ms} ms")
        else:
            self.stat_ping["val"].setText("ERR")

    def _log(self, text: str):
        if hasattr(self, "log_view"):
            self.log_view.append(text)
