# -*- coding: utf-8 -*-
"""Main Window of the Colab Model Hub & Gateway.
Refactored to commercial software standards:
- All template placeholder words removed
- Clean server icon replacing avatar
- Rocket icon for one-click deployment
- Windows 10/11 native immersive dark title bar enabled
- mmproj auxiliary weight filtering and accurate VRAM estimation ('预计占用 X.XX GB / 15.00 GB')
- Right panel partitioned into '快捷接入配置' and '网关健康状态'
- Tab toolbar automatically toggles auto-scroll and clear-log buttons
- Horizontal filter capsules ('全部' / 'Qwen' / 'DeepSeek' / 'Llama' / 'Gemma') saving sidebar space
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import sys
import threading
from typing import Any

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    PlainTextEdit,
    PushButton,
    SimpleCardWidget,
    StrongBodyLabel,
    ToolButton,
    TransparentPushButton,
)

from config_manager import APP_VERSION, LOG_FILE_PATH, append_app_log, config_mgr, get_gpu_vram_limit
from hf_explorer import ModelInfo, QuantFileInfo, evaluate_vram, hf_explorer
from colab_orchestrator import colab_orchestrator
from tunnel_daemon import tunnel_daemon
from gui.auth_dialog import ColabAuthDialog
from gui.chat_widget import ChatWidget
from gui.settings_dialog import SettingsDialog
from i18n import tr
from gui.theme import (
    BG_GLASS_SUBTLE,
    BORDER_GLASS,
    BORDER_SUBTLE,
    MONO_FONT,
    STATUS_DEPLOYING,
    STATUS_ERROR,
    STATUS_OFFLINE,
    STATUS_ONLINE,
    TEXT_ICY_CYAN,
    TEXT_MUTED,
    TEXT_WHITE,
    UI_FONT,
)

ASSETS_DIR = Path(__file__).parent / "assets"


def apply_windows_dark_title_bar(window: QWidget) -> None:
    """Force Windows 10/11 native title bar to immersive dark mode."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        value = ctypes.c_int(1)
        hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
        if hr != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass


class GlassBackgroundWidget(QWidget):
    """Central container painting the authentic Windows 11 Dark aurora wallpaper with offscreen caching."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.wallpaper_pix: QPixmap | None = None
        self._cached_bg: QPixmap | None = None
        self._cached_key: tuple[int, int, float] | None = None
        wall_path = ASSETS_DIR / "wallpaper.png"
        if wall_path.exists():
            self.wallpaper_pix = QPixmap(str(wall_path))

    def _ensure_bg_cache(self) -> QPixmap:
        w, h = max(1, self.width()), max(1, self.height())
        dpr = float(self.devicePixelRatioF() or 1.0)
        key = (w, h, dpr)
        if self._cached_bg is not None and self._cached_key == key:
            return self._cached_bg

        pix = QPixmap(max(1, int(round(w * dpr))), max(1, int(round(h * dpr))))
        pix.setDevicePixelRatio(dpr)
        p = QPainter(pix)
        if self.wallpaper_pix and not self.wallpaper_pix.isNull():
            target_size = pix.size()
            scaled = self.wallpaper_pix.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            x = (w - scaled.width() / dpr) / 2.0
            y = (h - scaled.height() / dpr) / 2.0
            p.drawPixmap(int(round(x)), int(round(y)), scaled)
            p.fillRect(0, 0, w, h, QColor(7, 12, 14, 110))
        else:
            p.fillRect(0, 0, w, h, QColor(10, 15, 18))
        p.end()

        self._cached_bg = pix
        self._cached_key = key
        return pix

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._cached_key = None

    def paintEvent(self, event):
        bg = self._ensure_bg_cache()
        painter = QPainter(self)
        painter.setClipRect(event.rect())
        painter.drawPixmap(0, 0, bg)
        painter.end()


class FilterCapsuleButton(QPushButton):
    """Horizontal filter capsule pill above model list."""

    def __init__(self, text: str, is_active: bool = False, on_click=None, parent=None):
        super().__init__(text, parent)
        self.is_active = is_active
        self.setFixedHeight(26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_style()
        if on_click:
            self.clicked.connect(on_click)

    def set_active(self, active: bool):
        self.is_active = active
        self.apply_style()

    def apply_style(self):
        if self.is_active:
            self.setStyleSheet(
                "FilterCapsuleButton {"
                "  background-color: rgba(34, 150, 118, 0.40);"
                "  border: 1px solid #3BE2AF;"
                "  border-radius: 13px;"
                f"  color: {TEXT_WHITE};"
                "  font-size: 11px;"
                "  font-weight: 600;"
                "  padding: 0 6px;"
                f"  {UI_FONT}"
                "}"
            )
        else:
            self.setStyleSheet(
                "FilterCapsuleButton {"
                "  background-color: rgba(255, 255, 255, 0.04);"
                "  border: 1px solid rgba(180, 201, 207, 0.15);"
                "  border-radius: 13px;"
                f"  color: {TEXT_MUTED};"
                "  font-size: 11px;"
                "  font-weight: 500;"
                "  padding: 0 6px;"
                f"  {UI_FONT}"
                "}"
                "FilterCapsuleButton:hover {"
                "  background-color: rgba(255, 255, 255, 0.08);"
                f"  border: 1px solid rgba(180, 201, 207, 0.30);"
                f"  color: {TEXT_WHITE};"
                "}"
            )


class SearchBridge(QObject):
    results_ready = Signal(int, list)
    error_occurred = Signal(int, str)


class QuantsBridge(QObject):
    quants_ready = Signal(int, list)
    error_occurred = Signal(int, str)


class DeployBridge(QObject):
    log_emitted = Signal(str)
    status_changed = Signal(str, str)
    finished = Signal(bool, str)
    orphan_detected = Signal(list)


class EnvBridge(QObject):
    checked = Signal(dict)


class TunnelBridge(QObject):
    status_changed = Signal(str, str)
    log_emitted = Signal(str)
    alert_emitted = Signal(str, str)


class StopBridge(QObject):
    finished = Signal(bool)


class MainWindow(QMainWindow):
    """Main window of the Colab Model Hub."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{tr('app_title')} v{APP_VERSION}")
        icon_path = ASSETS_DIR / "app.ico"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1340, 840)
        self.setMinimumSize(1100, 720)

        # Force native Windows title bar to dark mode
        apply_windows_dark_title_bar(self)

        # Active data cache & concurrency guards
        self.current_models: list[ModelInfo] = []
        self.current_quants: list[QuantFileInfo] = []
        self._search_req_id: int = 0
        self._quants_req_id: int = 0
        self._is_deploying: bool = False
        self._last_status_code: str = "disconnected"
        self._last_status_desc: str = ""

        # Signal bridges
        self._search_bridge = SearchBridge()
        self._search_bridge.results_ready.connect(self.on_models_loaded)
        self._search_bridge.error_occurred.connect(self.on_search_error)

        self._quants_bridge = QuantsBridge()
        self._quants_bridge.quants_ready.connect(self.on_quants_loaded)
        self._quants_bridge.error_occurred.connect(self.on_quants_error)

        self._deploy_bridge = DeployBridge()
        self._deploy_bridge.log_emitted.connect(self.append_log)
        self._deploy_bridge.status_changed.connect(self.update_status)
        self._deploy_bridge.finished.connect(self.on_deployment_finished)
        self._deploy_bridge.orphan_detected.connect(self.on_orphan_detected)

        self._env_bridge = EnvBridge()
        self._env_bridge.checked.connect(self.on_env_checked)

        self._tunnel_bridge = TunnelBridge()
        self._tunnel_bridge.status_changed.connect(self.update_status)
        self._tunnel_bridge.log_emitted.connect(self.append_log)
        self._tunnel_bridge.alert_emitted.connect(self.on_tunnel_alert)

        self._stop_bridge = StopBridge()
        self._stop_bridge.finished.connect(self.on_stop_finished)

        self.filter_capsules: list[FilterCapsuleButton] = []

        self.setup_ui()
        self.setup_tunnel_callbacks()
        self.load_preset_models()
        self.run_env_preflight()

    def showEvent(self, event):
        super().showEvent(event)
        apply_windows_dark_title_bar(self)

    def setup_ui(self) -> None:
        self.bg_widget = GlassBackgroundWidget(self)
        self.setCentralWidget(self.bg_widget)

        root_layout = QHBoxLayout(self.bg_widget)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(16)

        # 1. Left Sidebar Navigation with Horizontal Filter Capsules
        self.sidebar_widget = self._create_sidebar()
        root_layout.addWidget(self.sidebar_widget)

        # 2. Main Right Area
        right_area = QVBoxLayout()
        right_area.setContentsMargins(0, 0, 0, 0)
        right_area.setSpacing(14)

        # Header bar (Session info, GPU hardware badge, Wide Search)
        right_area.addWidget(self._create_header_bar())

        # Main 3-column Form Card
        right_area.addWidget(self._create_main_form())

        # Bottom section: Left tabbed content (Logs & Chat) + Right split integration/health panel
        bottom_box = QHBoxLayout()
        bottom_box.setSpacing(14)

        self.tabs_card = self._create_tabs_section()
        bottom_box.addWidget(self.tabs_card, 1)

        self.source_panel = self._create_source_panel()
        bottom_box.addWidget(self.source_panel)

        right_area.addLayout(bottom_box, 1)
        root_layout.addLayout(right_area, 1)

    # ---------------- 1. Sidebar Navigation with Filter Capsules ---------------- #

    def _create_sidebar(self) -> QWidget:
        sidebar = SimpleCardWidget(self)
        sidebar.setFixedWidth(305)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(8)

        # Sidebar Title / Brand
        brand_box = QHBoxLayout()
        grid_icon = QLabel()
        grid_pix = QPixmap(str(ASSETS_DIR / "grid.svg"))
        if not grid_pix.isNull():
            grid_icon.setPixmap(
                grid_pix.scaled(
                    20,
                    20,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        brand_box.addWidget(grid_icon)

        self.brand_title = StrongBodyLabel(tr("brand_title"))
        self.brand_title.setStyleSheet(
            f"{MONO_FONT} font-size: 13px; font-weight: 700; color: {TEXT_WHITE}; letter-spacing: 0.8px;"
        )
        brand_box.addWidget(self.brand_title)
        brand_box.addStretch()
        layout.addLayout(brand_box)

        layout.addSpacing(4)

        # Horizontal Filter Capsules (全部 / Qwen / DeepSeek / Llama / Gemma)
        capsule_box = QHBoxLayout()
        capsule_box.setSpacing(4)

        def make_capsule(text: str, query: str = "", is_active=False) -> FilterCapsuleButton:
            btn = FilterCapsuleButton(
                text,
                is_active=is_active,
                on_click=lambda: self._select_capsule(btn, query),
                parent=sidebar,
            )
            self.filter_capsules.append(btn)
            capsule_box.addWidget(btn)
            return btn

        self.cap_all = make_capsule(tr("filter_all"), query="", is_active=True)
        self.cap_qwen = make_capsule("Qwen", query="qwen")
        self.cap_deepseek = make_capsule("DeepSeek", query="deepseek")
        self.cap_llama = make_capsule("Llama", query="llama")
        self.cap_gemma = make_capsule("Gemma", query="gemma")

        layout.addLayout(capsule_box)

        # Subtle separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {BORDER_SUBTLE}; margin: 4px 0;")
        layout.addWidget(sep)

        # Model Search Result List (Full height available, no truncation)
        self.model_list = ListWidget(sidebar)
        self.model_list.setMinimumHeight(420)
        self.model_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.model_list.setStyleSheet(f"{UI_FONT} font-size: 11px;")
        self.model_list.itemClicked.connect(self.on_model_selected)
        layout.addWidget(self.model_list, 1)

        # Sidebar footer controls
        foot_box = QHBoxLayout()
        self.btn_preset = PushButton(tr("btn_preset"), sidebar, FluentIcon.TAG)
        self.btn_preset.clicked.connect(self.load_preset_models)
        self.btn_sidebar_settings = ToolButton(FluentIcon.SETTING, sidebar)
        self.btn_sidebar_settings.setToolTip(tr("tip_settings"))
        self.btn_sidebar_settings.clicked.connect(self.open_settings)

        foot_box.addWidget(self.btn_preset, 1)
        foot_box.addWidget(self.btn_sidebar_settings)
        layout.addLayout(foot_box)

        return sidebar

    def _select_capsule(self, target_btn: FilterCapsuleButton, query: str):
        for btn in self.filter_capsules:
            btn.set_active(btn is target_btn)
        if not query:
            self.load_preset_models()
        else:
            self.search_hf_models(query)

    # ---------------- 2. Top Header Bar (Server Icon, Hardware Badge, Search) ---------------- #

    def _create_header_bar(self) -> QWidget:
        header = QWidget(self)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # A. Colab Session Info Capsule (Replaced female avatar with clean server icon)
        profile_card = SimpleCardWidget(header)
        p_layout = QHBoxLayout(profile_card)
        p_layout.setContentsMargins(8, 4, 14, 4)
        p_layout.setSpacing(10)

        server_icon_lbl = QLabel()
        server_icon_lbl.setFixedSize(30, 30)
        server_path = ASSETS_DIR / "server.svg"
        if server_path.exists():
            pix = QPixmap(str(server_path))
            server_icon_lbl.setPixmap(
                pix.scaled(
                    20,
                    20,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            server_icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            server_icon_lbl.setStyleSheet(
                "background-color: rgba(34, 150, 118, 0.15); border: 1px solid rgba(59, 226, 175, 0.35); border-radius: 15px;"
            )
        p_layout.addWidget(server_icon_lbl)

        user_info = QVBoxLayout()
        user_info.setSpacing(1)
        self.user_name_lbl = StrongBodyLabel(tr("session_prefix", session=config_mgr.config.colab_session))
        self.user_name_lbl.setStyleSheet(
            f"{MONO_FONT} font-size: 11px; font-weight: 600; color: {TEXT_WHITE};"
        )

        status_box = QHBoxLayout()
        status_box.setSpacing(5)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(7, 7)
        self.status_dot.setStyleSheet(f"background-color: {STATUS_OFFLINE}; border-radius: 3px;")
        self.status_text = CaptionLabel(tr("status_disconnected"))
        self.status_text.setStyleSheet(
            f"{UI_FONT} font-size: 10px; font-weight: 600; color: {TEXT_MUTED};"
        )
        status_box.addWidget(self.status_dot)
        status_box.addWidget(self.status_text)
        status_box.addStretch()

        user_info.addWidget(self.user_name_lbl)
        user_info.addLayout(status_box)
        p_layout.addLayout(user_info)

        down_arrow = QLabel()
        down_pix = QPixmap(str(ASSETS_DIR / "chevron_down.svg"))
        if not down_pix.isNull():
            down_arrow.setPixmap(
                down_pix.scaled(
                    12,
                    12,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        p_layout.addWidget(down_arrow)
        layout.addWidget(profile_card)

        # B. Hardware Badge (dynamically synced with config gpu tier)
        gpu_card = SimpleCardWidget(header)
        gpu_layout = QHBoxLayout(gpu_card)
        gpu_layout.setContentsMargins(12, 6, 12, 6)
        gpu_layout.setSpacing(8)

        gpu_dot = QLabel()
        gpu_dot.setFixedSize(8, 8)
        gpu_dot.setStyleSheet("background-color: #229676; border-radius: 4px;")
        self.gpu_text_lbl = StrongBodyLabel()
        self.gpu_text_lbl.setStyleSheet(
            f"{MONO_FONT} font-size: 11px; font-weight: 700; color: {TEXT_WHITE};"
        )
        self.gpu_vram_lbl = CaptionLabel()
        self.gpu_vram_lbl.setStyleSheet(f"{MONO_FONT} font-size: 11px; color: {TEXT_ICY_CYAN};")
        self._refresh_gpu_badge()

        gpu_layout.addWidget(gpu_dot)
        gpu_layout.addWidget(self.gpu_text_lbl)
        gpu_layout.addWidget(self.gpu_vram_lbl)
        layout.addWidget(gpu_card)

        # C. Wide Search Bar
        search_card = SimpleCardWidget(header)
        s_layout = QHBoxLayout(search_card)
        s_layout.setContentsMargins(12, 4, 12, 4)
        s_layout.setSpacing(8)

        self.btn_search_icon = QPushButton(search_card)
        self.btn_search_icon.setFixedSize(22, 22)
        self.btn_search_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search_icon.setStyleSheet(
            "background: transparent; border: none; padding: 0;"
        )
        search_pix = QPixmap(str(ASSETS_DIR / "search.svg"))
        if not search_pix.isNull():
            self.btn_search_icon.setIcon(QIcon(search_pix))
            self.btn_search_icon.setIconSize(QSize(18, 18))
        self.btn_search_icon.clicked.connect(self.search_hf_models)
        s_layout.addWidget(self.btn_search_icon)

        v_sep = QFrame()
        v_sep.setFrameShape(QFrame.Shape.VLine)
        v_sep.setStyleSheet(f"color: {BORDER_GLASS}; max-width: 1px;")
        s_layout.addWidget(v_sep)

        self.search_edit = LineEdit(search_card)
        self.search_edit.setPlaceholderText(tr("search_placeholder"))
        self.search_edit.setStyleSheet(
            f"border: none; background: transparent; font-size: 13px; color: {TEXT_WHITE};"
        )
        self.search_edit.returnPressed.connect(self.search_hf_models)
        s_layout.addWidget(self.search_edit, 1)

        # Optional Auth Badge (shown only if Google Colab OAuth token is missing)
        self.btn_auth_badge = PushButton(tr("btn_auth_needed"), header, FluentIcon.PEOPLE)
        self.btn_auth_badge.setFixedHeight(34)
        self.btn_auth_badge.setVisible(False)
        self.btn_auth_badge.clicked.connect(self.open_auth_wizard)

        layout.addWidget(search_card, 1)
        layout.addWidget(self.btn_auth_badge)
        return header

    # ---------------- 3. Main Form Panel (No Template Placeholder Residuals) ---------------- #

    def _create_main_form(self) -> QWidget:
        form_card = SimpleCardWidget(self)
        layout = QVBoxLayout(form_card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        def make_field(label_text: str, widget: QWidget) -> tuple[QVBoxLayout, CaptionLabel]:
            col = QVBoxLayout()
            col.setSpacing(4)
            lbl = CaptionLabel(label_text)
            lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-weight: 500;")
            col.addWidget(lbl)
            col.addWidget(widget)
            return col, lbl

        # 3-Column Grid Top Row
        grid_top = QHBoxLayout()
        grid_top.setSpacing(16)

        # Field 1: 模型接口别名
        self.model_alias_edit = LineEdit(form_card)
        self.model_alias_edit.setPlaceholderText(tr("ph_alias"))
        self.model_alias_edit.setFixedHeight(38)
        col_alias, self.lbl_alias = make_field(tr("lbl_alias"), self.model_alias_edit)
        grid_top.addLayout(col_alias, 1)

        # Field 2: 量化规格
        self.quant_combo = ComboBox(form_card)
        self.quant_combo.setFixedHeight(38)
        self.quant_combo.currentIndexChanged.connect(self.on_quant_changed)
        col_quant, self.lbl_quant = make_field(tr("lbl_quant"), self.quant_combo)
        grid_top.addLayout(col_quant, 1)

        # Field 3: 上下文窗口
        self.ctx_combo = ComboBox(form_card)
        self.ctx_combo.setFixedHeight(38)
        for ctx in [2048, 4096, 8192, 16384, 32768]:
            self.ctx_combo.addItem(f"{ctx} ctx", userData=ctx)
        self.ctx_combo.setCurrentIndex(1)  # 4096 default
        self.ctx_combo.currentIndexChanged.connect(self.on_context_changed)
        col_ctx, self.lbl_ctx = make_field(tr("lbl_ctx"), self.ctx_combo)
        grid_top.addLayout(col_ctx, 1)

        layout.addLayout(grid_top)

        # 3-Column Grid Bottom Row
        grid_bot = QHBoxLayout()
        grid_bot.setSpacing(16)

        # Field 4: API Base URL
        url_box = QHBoxLayout()
        url_box.setSpacing(4)
        self.url_display = LineEdit(form_card)
        self.url_display.setReadOnly(True)
        self.url_display.setText(config_mgr.config.api_base_url)
        self.url_display.setFixedHeight(38)
        self.url_display.setStyleSheet(f"{MONO_FONT} font-size: 12px;")
        self.btn_copy_url = ToolButton(FluentIcon.COPY, form_card)
        self.btn_copy_url.setFixedHeight(38)
        self.btn_copy_url.setToolTip(tr("tip_copy_url"))
        self.btn_copy_url.clicked.connect(
            lambda: self.copy_to_clipboard(self.url_display.text(), "API Base URL")
        )
        url_box.addWidget(self.url_display, 1)
        url_box.addWidget(self.btn_copy_url)
        url_container = QWidget()
        url_container.setLayout(url_box)
        col_url, self.lbl_url = make_field(tr("lbl_base_url"), url_container)
        grid_bot.addLayout(col_url, 1)

        # Field 5: API Key
        key_box = QHBoxLayout()
        key_box.setSpacing(4)
        self.key_display = LineEdit(form_card)
        self.key_display.setReadOnly(True)
        self.key_display.setEchoMode(LineEdit.EchoMode.Password)
        self.key_display.setText(config_mgr.config.api_key)
        self.key_display.setFixedHeight(38)
        self.btn_toggle_key = ToolButton(FluentIcon.VIEW, form_card)
        self.btn_toggle_key.setFixedHeight(38)
        self.btn_toggle_key.setToolTip(tr("tip_toggle_key"))
        self.btn_toggle_key.clicked.connect(self.toggle_key_visibility)
        self.btn_copy_key = ToolButton(FluentIcon.COPY, form_card)
        self.btn_copy_key.setFixedHeight(38)
        self.btn_copy_key.setToolTip(tr("tip_copy_key"))
        self.btn_copy_key.clicked.connect(
            lambda: self.copy_to_clipboard(config_mgr.config.api_key, "API Key")
        )
        key_box.addWidget(self.key_display, 1)
        key_box.addWidget(self.btn_toggle_key)
        key_box.addWidget(self.btn_copy_key)
        key_container = QWidget()
        key_container.setLayout(key_box)
        col_key, self.lbl_key = make_field(tr("lbl_api_key"), key_container)
        grid_bot.addLayout(col_key, 1)

        # Field 6: 硬件显存预估
        vram_card = QWidget()
        vram_card.setFixedHeight(38)
        vram_card.setStyleSheet(
            f"background-color: {BG_GLASS_SUBTLE}; border: 1px solid {BORDER_GLASS}; border-radius: 6px;"
        )
        v_layout = QHBoxLayout(vram_card)
        v_layout.setContentsMargins(10, 0, 10, 0)
        v_layout.setSpacing(8)

        self.vram_dot = QLabel()
        self.vram_dot.setFixedSize(8, 8)
        self.vram_dot.setStyleSheet("background-color: #71717A; border-radius: 4px;")
        self.vram_metric_lbl = CaptionLabel(tr("vram_waiting"))
        self.vram_metric_lbl.setStyleSheet(
            f"{UI_FONT} font-size: 11px; color: {TEXT_MUTED}; font-weight: 500;"
        )
        v_layout.addWidget(self.vram_dot)
        v_layout.addWidget(self.vram_metric_lbl, 1)

        col_vram, self.lbl_vram = make_field(tr("lbl_vram"), vram_card)
        grid_bot.addLayout(col_vram, 1)

        layout.addLayout(grid_bot)

        # Horizontal subtle divider line
        h_line = QFrame()
        h_line.setFrameShape(QFrame.Shape.HLine)
        h_line.setStyleSheet(f"color: {BORDER_SUBTLE}; margin: 6px 0;")
        layout.addWidget(h_line)

        # Action Buttons Row
        action_row = QHBoxLayout()
        action_row.setSpacing(12)

        # Primary Emerald Launch Button with Play Icon
        self.btn_deploy = QPushButton(tr("btn_deploy"), form_card)
        self.btn_deploy.setObjectName("btnDeploy")
        self.btn_deploy.setFixedHeight(40)
        play_svg = ASSETS_DIR / "play.svg"
        if play_svg.exists():
            self.btn_deploy.setIcon(QIcon(str(play_svg)))
            self.btn_deploy.setIconSize(QSize(16, 16))
        self.btn_deploy.clicked.connect(self.start_one_click_deploy)
        action_row.addWidget(self.btn_deploy)

        # Frosted Cancel / Stop Button
        self.btn_stop = QPushButton(tr("btn_stop"), form_card)
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.clicked.connect(self.stop_colab_service)
        action_row.addWidget(self.btn_stop)

        action_row.addStretch()

        # System Settings Shortcut
        self.btn_settings = PushButton(tr("btn_settings"), form_card, FluentIcon.SETTING)
        self.btn_settings.setFixedHeight(40)
        self.btn_settings.clicked.connect(self.open_settings)
        action_row.addWidget(self.btn_settings)

        layout.addLayout(action_row)
        return form_card

    # ---------------- 4. Bottom Tabs Section (Contextual Toolbar) ---------------- #

    def _create_tabs_section(self) -> QWidget:
        container = SimpleCardWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        # Tab Buttons Header (fixed height prevents layout reflow when toggling log controls)
        tab_header_bar = QWidget(container)
        tab_header_bar.setFixedHeight(34)
        tab_header_bar.setStyleSheet(
            f"""
            QPushButton#tabBtn {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                color: {TEXT_MUTED};
                font-size: 12px;
                padding: 0 14px;
            }}
            QPushButton#tabBtn[active="true"] {{
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(180, 201, 207, 0.22);
                color: {TEXT_WHITE};
                font-weight: 600;
            }}
            """
        )
        tab_header = QHBoxLayout(tab_header_bar)
        tab_header.setContentsMargins(0, 0, 0, 0)
        tab_header.setSpacing(8)

        self.btn_tab_incoming = QPushButton(tr("tab_logs"), tab_header_bar)
        self.btn_tab_incoming.setObjectName("tabBtn")
        self.btn_tab_incoming.setFixedHeight(32)
        self.btn_tab_incoming.setCursor(Qt.CursorShape.PointingHandCursor)

        self.btn_tab_outgoing = QPushButton(tr("tab_chat"), tab_header_bar)
        self.btn_tab_outgoing.setObjectName("tabBtn")
        self.btn_tab_outgoing.setFixedHeight(32)
        self.btn_tab_outgoing.setCursor(Qt.CursorShape.PointingHandCursor)

        # Toolbar controls: Auto-scroll, Clear log, Export log
        self.autoscroll_check = CheckBox(tr("chk_autoscroll"), tab_header_bar)
        self.autoscroll_check.setChecked(True)
        self.btn_clear_log = TransparentPushButton(tr("btn_clear_log"), tab_header_bar, FluentIcon.DELETE)
        self.btn_clear_log.clicked.connect(lambda: self.log_text.clear())
        self.btn_export_log = TransparentPushButton(tr("btn_export_log"), tab_header_bar, FluentIcon.SAVE_AS)
        self.btn_export_log.clicked.connect(self.export_logs)

        self._current_tab_name: str = ""

        self.btn_tab_incoming.clicked.connect(lambda: self.switch_tab("logs"))
        self.btn_tab_outgoing.clicked.connect(lambda: self.switch_tab("chat"))

        tab_header.addWidget(self.btn_tab_incoming)
        tab_header.addWidget(self.btn_tab_outgoing)
        tab_header.addStretch()

        tab_header.addWidget(self.autoscroll_check)
        tab_header.addWidget(self.btn_clear_log)
        tab_header.addWidget(self.btn_export_log)
        layout.addWidget(tab_header_bar)

        # Stacked Pages
        self.tab_stack = QStackedWidget(self)

        # Page 1: Logs & Mini-Table Status
        log_page = QWidget()
        lp_layout = QVBoxLayout(log_page)
        lp_layout.setContentsMargins(0, 4, 0, 0)
        lp_layout.setSpacing(6)

        strip = QWidget()
        strip.setFixedHeight(28)
        strip.setStyleSheet(
            f"background-color: rgba(18, 26, 32, 0.45); border: 1px solid {BORDER_SUBTLE}; border-radius: 4px;"
        )
        s_layout = QHBoxLayout(strip)
        s_layout.setContentsMargins(10, 0, 10, 0)
        cfg = config_mgr.config
        self.strip_port_lbl = QLabel(tr("strip_port", port=cfg.api_port, url=cfg.api_base_url))
        self.strip_port_lbl.setStyleSheet(f"{MONO_FONT} font-size: 11px; color: {TEXT_ICY_CYAN};")
        self.strip_gpu_lbl = QLabel()
        self.strip_gpu_lbl.setStyleSheet(f"{UI_FONT} font-size: 11px; color: {TEXT_MUTED};")
        self.strip_probe_lbl = QLabel(tr("strip_probe"))
        self.strip_probe_lbl.setStyleSheet(f"{UI_FONT} font-size: 11px; color: #10B981;")
        self._refresh_strip_labels()
        s_layout.addWidget(self.strip_port_lbl)
        s_layout.addStretch()
        s_layout.addWidget(self.strip_gpu_lbl)
        s_layout.addSpacing(16)
        s_layout.addWidget(self.strip_probe_lbl)
        lp_layout.addWidget(strip)

        self.log_text = PlainTextEdit(log_page)
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(3000)
        self.log_text.setStyleSheet(f"{MONO_FONT} font-size: 11px; color: {TEXT_WHITE};")
        lp_layout.addWidget(self.log_text)
        self.tab_stack.addWidget(log_page)

        # Page 2: Chat Playground
        self.chat_widget = ChatWidget(self)
        self.tab_stack.addWidget(self.chat_widget)

        layout.addWidget(self.tab_stack, 1)
        self.switch_tab("logs")
        return container

    def switch_tab(self, tab_name: str) -> None:
        if tab_name == self._current_tab_name:
            return
        self._current_tab_name = tab_name
        is_logs = tab_name == "logs"

        self.btn_tab_incoming.setProperty("active", is_logs)
        self.btn_tab_outgoing.setProperty("active", not is_logs)
        for btn in (self.btn_tab_incoming, self.btn_tab_outgoing):
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self.autoscroll_check.setVisible(is_logs)
        self.btn_clear_log.setVisible(is_logs)
        self.btn_export_log.setVisible(is_logs)
        self.tab_stack.setCurrentIndex(0 if is_logs else 1)
        if not is_logs:
            self.chat_widget.msg_input.setFocus()

    # ---------------- 5. Right Panel: 快捷接入配置 + 网关健康状态 ---------------- #

    def _create_source_panel(self) -> QWidget:
        panel = SimpleCardWidget(self)
        panel.setFixedWidth(290)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Part 1: 【快捷接入配置】
        self.access_title = CaptionLabel(tr("access_title"))
        self.access_title.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {TEXT_WHITE};")
        layout.addWidget(self.access_title)

        self.btn_curl = PushButton(tr("btn_copy_curl"), panel, FluentIcon.COMMAND_PROMPT)
        self.btn_curl.setFixedHeight(34)
        self.btn_curl.setToolTip(tr("tip_copy_curl"))
        self.btn_curl.clicked.connect(self.copy_curl_snippet)
        layout.addWidget(self.btn_curl)

        self.btn_py = PushButton(tr("btn_copy_py"), panel, FluentIcon.CODE)
        self.btn_py.setFixedHeight(34)
        self.btn_py.setToolTip(tr("tip_copy_py"))
        self.btn_py.clicked.connect(self.copy_python_snippet)
        layout.addWidget(self.btn_py)

        self.btn_client = PushButton(tr("btn_copy_client"), panel, FluentIcon.SHARE)
        self.btn_client.setFixedHeight(34)
        self.btn_client.setToolTip(tr("tip_copy_client"))
        self.btn_client.clicked.connect(self.copy_app_guide)
        layout.addWidget(self.btn_client)

        # Divider line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {BORDER_SUBTLE}; margin: 2px 0;")
        layout.addWidget(sep)

        # Part 2: 【网关健康状态】
        self.health_title = CaptionLabel(tr("health_title"))
        self.health_title.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {TEXT_WHITE};")
        layout.addWidget(self.health_title)

        health_card = QWidget(panel)
        health_card.setStyleSheet(
            f"background-color: rgba(14, 20, 26, 0.75); border: 1px solid {BORDER_GLASS}; border-radius: 6px;"
        )
        h_layout = QVBoxLayout(health_card)
        h_layout.setContentsMargins(12, 10, 12, 10)
        h_layout.setSpacing(8)

        # Row 1: Local Port
        cfg = config_mgr.config
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.health_port_dot = QLabel()
        self.health_port_dot.setFixedSize(8, 8)
        self.health_port_dot.setStyleSheet("background-color: #64748B; border-radius: 4px;")
        self.health_port_text = QLabel(tr("health_port_off", port=cfg.api_port))
        self.health_port_text.setStyleSheet(f"{UI_FONT} font-size: 11px; color: {TEXT_MUTED};")
        row1.addWidget(self.health_port_dot)
        row1.addWidget(self.health_port_text, 1)
        h_layout.addLayout(row1)

        # Row 2: Heartbeat Probe
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.health_heartbeat_dot = QLabel()
        self.health_heartbeat_dot.setFixedSize(8, 8)
        self.health_heartbeat_dot.setStyleSheet("background-color: #64748B; border-radius: 4px;")
        self.health_heartbeat_text = QLabel(tr("health_hb_off", sec=cfg.keep_alive_interval))
        self.health_heartbeat_text.setStyleSheet(f"{UI_FONT} font-size: 11px; color: {TEXT_MUTED};")
        row2.addWidget(self.health_heartbeat_dot)
        row2.addWidget(self.health_heartbeat_text, 1)
        h_layout.addLayout(row2)

        layout.addWidget(health_card)
        layout.addStretch()
        return panel

    # ---------------- Business Logic & Slots ---------------- #

    def setup_tunnel_callbacks(self) -> None:
        def on_status(code: str, desc: str):
            self._tunnel_bridge.status_changed.emit(code, desc)

        def on_log(msg: str):
            self._tunnel_bridge.log_emitted.emit(msg)

        def on_alert(title: str, text: str):
            self._tunnel_bridge.alert_emitted.emit(title, text)

        tunnel_daemon.on_status_change = on_status
        tunnel_daemon.on_log = on_log
        tunnel_daemon.on_alert = on_alert

    def load_preset_models(self) -> None:
        self.search_edit.clear()
        self.search_hf_models("")

    def _refresh_gpu_badge(self) -> None:
        gpu = str(config_mgr.config.colab_gpu or "T4").upper()
        limit = get_gpu_vram_limit(gpu)
        if gpu == "CPU" or limit <= 0:
            self.gpu_text_lbl.setText("COLAB CPU")
            self.gpu_vram_lbl.setText(tr("gpu_badge_cpu"))
        else:
            name_map = {
                "T4": "TESLA T4",
                "L4": "NVIDIA L4",
                "A100": "NVIDIA A100",
                "H100": "NVIDIA H100",
                "G4": "NVIDIA G4 (RTX 6000)",
            }
            self.gpu_text_lbl.setText(name_map.get(gpu, f"GPU {gpu}"))
            vram_str = f"{limit:g}"
            self.gpu_vram_lbl.setText(tr("gpu_badge_vram", vram=vram_str))

    def _refresh_strip_labels(self) -> None:
        cfg = config_mgr.config
        self.strip_port_lbl.setText(tr("strip_port", port=cfg.api_port, url=cfg.api_base_url))
        gpu = str(cfg.colab_gpu or "T4").upper()
        limit = get_gpu_vram_limit(gpu)
        if gpu == "CPU" or limit <= 0:
            self.strip_gpu_lbl.setText(tr("strip_runtime_cpu"))
        else:
            self.strip_gpu_lbl.setText(tr("strip_runtime_gpu", gpu=gpu, vram=f"{limit:g}"))
        self.strip_probe_lbl.setText(tr("strip_probe"))

    def run_env_preflight(self) -> None:
        def _worker():
            try:
                env = colab_orchestrator.check_environment()
                self._env_bridge.checked.emit(env)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def on_env_checked(self, env: dict) -> None:
        if not env.get("has_ssh") or not env.get("has_ssh_keygen"):
            InfoBar.warning(
                tr("warn_title"),
                tr("env_missing_ssh"),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=7000,
            )
        has_auth = bool(env.get("has_auth", True))
        self.btn_auth_badge.setVisible(not has_auth)
        if not has_auth:
            InfoBar.warning(
                tr("warn_title"),
                tr("env_missing_auth"),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=7000,
            )

    def open_auth_wizard(self) -> None:
        dlg = ColabAuthDialog(self)
        if dlg.exec():
            self.btn_auth_badge.setVisible(False)

    def search_hf_models(self, query: Any = None) -> None:
        if query is None or isinstance(query, bool):
            query = self.search_edit.text()
        q = str(query).strip()

        self._search_req_id += 1
        req_id = self._search_req_id

        self.model_list.clear()
        self.model_list.addItem(tr("list_searching") if q else tr("list_loading_preset"))
        if q:
            self.search_edit.setText(q)
            self.append_log(f"[INFO] Searching models: {q} ...\n")

        lang = config_mgr.config.language

        def _worker():
            try:
                models = hf_explorer.search_models(q, lang=lang)
                self._search_bridge.results_ready.emit(req_id, models)
            except Exception as e:
                self._search_bridge.error_occurred.emit(req_id, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def on_models_loaded(self, req_id: int, models: list[ModelInfo]) -> None:
        if req_id != self._search_req_id:
            return
        self.model_list.clear()
        self.current_models = models

        if not models:
            self.model_list.addItem(tr("list_empty"))
            self.current_quants = []
            self.quant_combo.clear()
            return

        for m in models:
            likes_str = f"{m.likes/1000:.1f}k" if m.likes >= 1000 else str(m.likes)
            downloads_str = (
                f"{m.downloads/1000:.1f}k" if m.downloads >= 1000 else str(m.downloads)
            )
            short_name = m.repo_id.split("/")[-1]
            desc_snip = m.description if len(m.description) <= 26 else m.description[:26] + "..."
            display_text = f"{short_name}\n👍 {likes_str}  📥 {downloads_str}  •  {desc_snip}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, m.repo_id)
            self.model_list.addItem(item)

        self.model_list.setCurrentRow(0)
        self.on_model_selected(self.model_list.item(0))

    def on_search_error(self, req_id: int, err: str) -> None:
        if req_id != self._search_req_id:
            return
        self.model_list.clear()
        self.model_list.addItem(tr("list_error", err=err))
        self.append_log(f"[ERROR] Search failed: {err}\n")

    def get_selected_ctx_size(self) -> int:
        data = self.ctx_combo.currentData()
        if data:
            return int(data)
        raw = self.ctx_combo.currentText().split()[0]
        try:
            return int(raw)
        except Exception:
            return 4096

    def on_context_changed(self) -> None:
        ctx = self.get_selected_ctx_size()
        cfg = config_mgr.config
        cfg.ctx_size = ctx
        idx = self.quant_combo.currentIndex()
        if 0 <= idx < len(self.current_quants):
            q = self.current_quants[idx]
            vram_est, status, status_text, badge_color = evaluate_vram(
                q.size_gb, ctx, gpu_type=cfg.colab_gpu, lang=cfg.language
            )
            q.vram_required_gb = vram_est
            q.status = status
            q.status_text = status_text
            q.badge_color = badge_color
            self.vram_dot.setStyleSheet(f"background-color: {badge_color}; border-radius: 4px;")
            self.vram_metric_lbl.setText(status_text)
            self.vram_metric_lbl.setStyleSheet(
                f"{UI_FONT} font-size: 11px; color: {badge_color}; font-weight: 600;"
            )

    def on_model_selected(self, item: QListWidgetItem) -> None:
        if not item:
            return
        repo_id = item.data(Qt.ItemDataRole.UserRole)
        if not repo_id:
            return

        self._quants_req_id += 1
        req_id = self._quants_req_id
        self.current_quants = []

        alias = repo_id.split("/")[-1].lower()
        alias = re.sub(r"(-instruct|-gguf|-chat|\.gguf)", "", alias)
        self.model_alias_edit.setText(alias)

        self.quant_combo.clear()
        self.quant_combo.addItem(tr("quant_loading"))
        self.vram_dot.setStyleSheet("background-color: #71717A; border-radius: 4px;")
        self.vram_metric_lbl.setText(tr("vram_loading"))
        self.vram_metric_lbl.setStyleSheet(f"{UI_FONT} font-size: 11px; color: {TEXT_MUTED}; font-weight: 500;")

        ctx = self.get_selected_ctx_size()
        cfg = config_mgr.config
        gpu_type = cfg.colab_gpu
        lang = cfg.language

        def _worker():
            try:
                quants = hf_explorer.get_model_quants(repo_id, ctx, gpu_type=gpu_type, lang=lang)
                self._quants_bridge.quants_ready.emit(req_id, quants)
            except Exception as e:
                self._quants_bridge.error_occurred.emit(req_id, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def on_quants_error(self, req_id: int, err: str) -> None:
        if req_id != self._quants_req_id:
            return
        self.quant_combo.clear()
        self.quant_combo.addItem(tr("quant_error"))
        self.append_log(f"[ERROR] Quant parse failed: {err}\n")

    def on_quants_loaded(self, req_id: int, quants: list[QuantFileInfo]) -> None:
        if req_id != self._quants_req_id:
            return
        self.quant_combo.clear()
        self.current_quants = quants

        if not quants:
            self.quant_combo.addItem(tr("quant_empty"))
            self.vram_dot.setStyleSheet("background-color: #EF4444; border-radius: 4px;")
            self.vram_metric_lbl.setText(tr("vram_invalid"))
            return

        for q in quants:
            self.quant_combo.addItem(f"{q.quant_type:<8} ({q.size_gb:>5.2f} GB)  {q.filename}", q)

        self.quant_combo.setCurrentIndex(0)
        self.on_quant_changed(0)

    def on_quant_changed(self, index: int) -> None:
        if index < 0 or index >= len(self.current_quants):
            return
        q = self.current_quants[index]

        self.vram_dot.setStyleSheet(f"background-color: {q.badge_color}; border-radius: 4px;")
        self.vram_metric_lbl.setText(q.status_text)
        self.vram_metric_lbl.setStyleSheet(
            f"{UI_FONT} font-size: 11px; color: {q.badge_color}; font-weight: 600;"
        )

        cfg = config_mgr.config
        selected_item = self.model_list.currentItem()
        if selected_item:
            cfg.selected_repo = selected_item.data(Qt.ItemDataRole.UserRole)
        cfg.selected_file = q.filename
        cfg.selected_model_alias = self.model_alias_edit.text().strip()

    def update_status(self, code: str, desc: str) -> None:
        self._last_status_code = code
        self._last_status_desc = desc
        cfg = config_mgr.config
        port = cfg.api_port
        hb = cfg.keep_alive_interval

        color_map = {
            "ready": STATUS_ONLINE,
            "connected": STATUS_ONLINE,
            "deploying": STATUS_DEPLOYING,
            "connecting": STATUS_DEPLOYING,
            "disconnecting": STATUS_DEPLOYING,
            "disconnected": STATUS_OFFLINE,
            "error": STATUS_ERROR,
        }
        color = color_map.get(code, STATUS_OFFLINE)
        self.status_dot.setStyleSheet(f"background-color: {color}; border-radius: 3px;")

        status_text_map = {
            "ready": tr("status_ready", port=port),
            "connected": tr("status_connected"),
            "deploying": tr("status_deploying"),
            "connecting": tr("status_connecting"),
            "disconnecting": tr("status_disconnecting"),
            "disconnected": tr("status_disconnected"),
            "error": tr("status_error"),
        }
        self.status_text.setText(status_text_map.get(code, desc.upper()))

        if code in ("ready", "connected"):
            self.user_name_lbl.setText(tr("session_prefix", session=cfg.colab_session))
            self.health_port_dot.setStyleSheet("background-color: #10B981; border-radius: 4px;")
            self.health_port_text.setText(tr("health_port_ready", port=port))
            self.health_port_text.setStyleSheet(f"{UI_FONT} font-size: 11px; color: {TEXT_WHITE};")
            self.health_heartbeat_dot.setStyleSheet("background-color: #10B981; border-radius: 4px;")
            self.health_heartbeat_text.setText(tr("health_hb_active", sec=hb))
            self.health_heartbeat_text.setStyleSheet(f"{UI_FONT} font-size: 11px; color: {TEXT_WHITE};")
        else:
            self.health_port_dot.setStyleSheet("background-color: #64748B; border-radius: 4px;")
            self.health_port_text.setText(tr("health_port_off", port=port))
            self.health_port_text.setStyleSheet(f"{UI_FONT} font-size: 11px; color: {TEXT_MUTED};")
            self.health_heartbeat_dot.setStyleSheet("background-color: #64748B; border-radius: 4px;")
            self.health_heartbeat_text.setText(tr("health_hb_off", sec=hb))
            self.health_heartbeat_text.setStyleSheet(f"{UI_FONT} font-size: 11px; color: {TEXT_MUTED};")

    def on_tunnel_alert(self, title: str, text: str) -> None:
        InfoBar.warning(
            title=title,
            content=text,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    # ---------------- One-Click Deploy & Stop ---------------- #

    def start_one_click_deploy(self) -> None:
        if self._is_deploying:
            return
        idx = self.quant_combo.currentIndex()
        if not self.current_quants or idx < 0 or idx >= len(self.current_quants):
            InfoBar.warning(tr("warn_title"), tr("warn_select_quant"), parent=self, position=InfoBarPosition.TOP)
            return

        cfg = config_mgr.config
        selected_quant = self.current_quants[idx]
        limit_gb = get_gpu_vram_limit(cfg.colab_gpu)
        if selected_quant.status == "overload" and limit_gb > 0:
            reply = QMessageBox.question(
                self,
                tr("vram_overload_title"),
                tr(
                    "vram_overload_msg",
                    size_gb=selected_quant.size_gb,
                    vram_gb=selected_quant.vram_required_gb,
                    gpu=cfg.colab_gpu,
                    limit_gb=limit_gb,
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return

        selected_item = self.model_list.currentItem()
        target_repo = selected_item.data(Qt.ItemDataRole.UserRole) if selected_item else cfg.selected_repo
        if not target_repo:
            InfoBar.warning(tr("warn_title"), tr("warn_select_repo"), parent=self, position=InfoBarPosition.TOP)
            return
        cfg.selected_repo = target_repo
        cfg.selected_file = selected_quant.filename
        cfg.selected_model_alias = self.model_alias_edit.text().strip() or "custom-model"
        cfg.ctx_size = self.get_selected_ctx_size()
        config_mgr.save()

        self._is_deploying = True
        self.btn_deploy.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.switch_tab("logs")

        def _worker():
            def log(msg: str):
                self._deploy_bridge.log_emitted.emit(msg)

            try:
                self._deploy_bridge.status_changed.emit("deploying", tr("status_deploying"))
                log("\n" + "=" * 65)
                log(f"🚀 【阶段 1/3】检查并分配 Colab 算力实例 ({cfg.colab_gpu} GPU)")
                log("=" * 65)
                if not colab_orchestrator.ensure_session(
                    cfg.colab_session, cfg.colab_gpu, high_mem=cfg.high_mem, log_callback=log
                ):
                    if colab_orchestrator.last_error_code == "412" and colab_orchestrator.last_orphan_endpoints:
                        self._deploy_bridge.orphan_detected.emit(list(colab_orchestrator.last_orphan_endpoints))
                    elif colab_orchestrator.last_error_code == "400_entitlement":
                        self._deploy_bridge.finished.emit(False, tr("err_gpu_entitlement", gpu=cfg.colab_gpu))
                        return
                    self._deploy_bridge.finished.emit(False, "无法分配 Colab 会话，请检查 Google 账号 GPU 额度或残留实例")
                    return

                self._deploy_bridge.status_changed.emit(
                    "deploying", f"llama-server: {cfg.selected_model_alias}"
                )
                log("\n" + "=" * 65)
                log(f"📦 【阶段 2/3】云端拉取模型权重并启动 llama-server (Context: {cfg.ctx_size})")
                log(f"   目标模型仓库: {target_repo}")
                log(f"   主量化文件名: {selected_quant.filename}")
                log(f"   模型接口别名: {cfg.selected_model_alias}")
                log("=" * 65)
                ok = colab_orchestrator.deploy_model(
                    session_name=cfg.colab_session,
                    repo_id=target_repo,
                    filename=selected_quant.filename,
                    model_alias=cfg.selected_model_alias,
                    api_key=cfg.api_key,
                    ctx_size=cfg.ctx_size,
                    hf_token=cfg.hf_token,
                    enable_gdrive=cfg.enable_gdrive_cache,
                    llama_cpp_tag=cfg.llama_cpp_tag,
                    log_callback=log,
                )
                if not ok:
                    self._deploy_bridge.finished.emit(False, "云端模型部署执行未成功，请检查上方详细日志")
                    return

                self._deploy_bridge.status_changed.emit("connecting", tr("status_connecting"))
                log("\n" + "=" * 65)
                log(f"🔗 【阶段 3/3】开放本地加密直连隧道与心跳守护 (127.0.0.1:{cfg.api_port})")
                log("=" * 65)
                if tunnel_daemon.start():
                    self._deploy_bridge.status_changed.emit("ready", "Ready")
                    log(f"✔ 本地直连加密隧道建立成功！端口 {cfg.api_port} 处于监听状态。")
                    log("✔ 网关健康探测通过 (status: ok)！")
                    log("=" * 65)
                    log(f"🎉 【部署全部就绪】服务已在本地 {cfg.api_port} 端口稳定就绪，已为您自动切换到【对话测试】Tab！")
                    log("=" * 65 + "\n")
                    self._deploy_bridge.finished.emit(True, tr("deploy_done_msg"))
                else:
                    self._deploy_bridge.finished.emit(False, "直连隧道建立失败，请检查 SSH 密钥或网络状态。")

            except Exception as e:
                self._deploy_bridge.log_emitted.emit(f"\n❌ 【异常中断】: {e}\n")
                self._deploy_bridge.finished.emit(False, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def on_orphan_detected(self, orphans: list[str]) -> None:
        if not orphans:
            return
        reply = QMessageBox.question(
            self,
            tr("orphan_title"),
            tr("orphan_msg", orphans=", ".join(orphans)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.append_log(f"[ACTION] 正在释放云端残留实例: {', '.join(orphans)} ...\n")
        self.btn_deploy.setEnabled(False)

        def _cleanup_and_retry():
            ok_all = True
            for ep in orphans:
                if not colab_orchestrator.unassign_orphan(ep):
                    ok_all = False
            self._deploy_bridge.log_emitted.emit(
                "[ACTION] 残留实例已释放，请点击【一键部署】重试。\n"
                if ok_all
                else "[WARN] 释放部分残留实例失败，建议在终端执行 colab sessions 检查。\n"
            )

        threading.Thread(target=_cleanup_and_retry, daemon=True).start()
        self.btn_deploy.setEnabled(True)

    def on_deployment_finished(self, success: bool, message: str) -> None:
        self._is_deploying = False
        self.btn_deploy.setEnabled(True)
        if success:
            InfoBar.success(
                title=tr("deploy_done_title"),
                content=message,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000,
            )
            self.switch_tab("chat")
        else:
            self.update_status("error", tr("deploy_fail_title"))
            self.append_log("\n" + "!" * 65)
            self.append_log(f"❌ 【{tr('deploy_fail_title')}】{message}")
            self.append_log("💡 常见排查与解决方法:")
            self.append_log("   1. 会话超时或中断: 点击【释放算力】后重新点击【一键部署】重试；")
            self.append_log("   2. 显存不足: 检查选中的模型量化规格是否超出当前 GPU 显存上限；")
            self.append_log("   3. 网络连接: 确保当前网络环境可顺畅连接 Google Colab 官方服务器。")
            self.append_log("!" * 65 + "\n")
            InfoBar.error(
                title=tr("deploy_fail_title"),
                content=message,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=6000,
            )

    def stop_colab_service(self) -> None:
        reply = QMessageBox.question(
            self,
            tr("stop_confirm_title"),
            tr("stop_confirm_msg"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.No:
            return

        self.btn_stop.setEnabled(False)
        self.btn_deploy.setEnabled(False)
        self.update_status("disconnecting", tr("status_disconnecting"))
        self.append_log("[ACTION] 正在后台断开本地隧道并释放 Colab 会话...\n")
        session_name = config_mgr.config.colab_session

        def _stop_worker():
            ok = False
            try:
                tunnel_daemon.stop()
                ok = colab_orchestrator.stop_session(session_name)
            except Exception as e:
                self._deploy_bridge.log_emitted.emit(f"[ERROR] Stop exception: {e}\n")
            self._stop_bridge.finished.emit(ok)

        threading.Thread(target=_stop_worker, daemon=True).start()

    def on_stop_finished(self, ok: bool) -> None:
        self.btn_stop.setEnabled(True)
        self.btn_deploy.setEnabled(True)
        self.update_status("disconnected", tr("status_disconnected"))
        if ok:
            self.append_log("[ACTION] Colab 资源已成功释放。\n")
            InfoBar.info(tr("stop_done_title"), tr("stop_done_msg"), parent=self, position=InfoBarPosition.TOP)
        else:
            self.append_log("[ACTION] 本地隧道已关闭（远端会话可能已离线或超时回收）。\n")
            InfoBar.info(tr("stop_done_title"), tr("stop_local_msg"), parent=self, position=InfoBarPosition.TOP)

    def append_log(self, text: str) -> None:
        if not text:
            return
        if not text.endswith("\n"):
            text += "\n"
        cleaned = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
        append_app_log(cleaned)
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(cleaned)
        if self.autoscroll_check.isChecked():
            self.log_text.setTextCursor(cursor)
            self.log_text.ensureCursorVisible()

    def export_logs(self) -> None:
        dest, _ = QFileDialog.getSaveFileName(
            self,
            tr("btn_export_log"),
            str(Path.home() / "colab_model_hub_logs.txt"),
            "Log Files (*.txt *.log)",
        )
        if not dest:
            return
        try:
            content = self.log_text.toPlainText()
            if LOG_FILE_PATH.is_file() and not content.strip():
                shutil.copy(LOG_FILE_PATH, dest)
            else:
                Path(dest).write_text(content, encoding="utf-8")
            InfoBar.success(tr("copied_title"), dest, parent=self, position=InfoBarPosition.TOP, duration=2500)
        except Exception as e:
            InfoBar.error(tr("warn_title"), str(e), parent=self, position=InfoBarPosition.TOP)

    def toggle_key_visibility(self) -> None:
        if self.key_display.echoMode() == LineEdit.EchoMode.Password:
            self.key_display.setEchoMode(LineEdit.EchoMode.Normal)
            self.btn_toggle_key.setIcon(FluentIcon.HIDE)
        else:
            self.key_display.setEchoMode(LineEdit.EchoMode.Password)
            self.btn_toggle_key.setIcon(FluentIcon.VIEW)

    def copy_to_clipboard(self, text: str, name: str) -> None:
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        InfoBar.success(tr("copied_title"), tr("copied_msg", name=name), parent=self, position=InfoBarPosition.TOP, duration=2000)

    def copy_curl_snippet(self) -> None:
        cfg = config_mgr.config
        curl_cmd = (
            f"curl -X POST {cfg.api_base_url}/chat/completions \\\n"
            f'  -H "Content-Type: application/json" \\\n'
            f'  -H "Authorization: Bearer {cfg.api_key}" \\\n'
            f"  -d '{{\n"
            f'    "model": "{self.model_alias_edit.text().strip()}",\n'
            f'    "messages": [{{"role": "user", "content": "Hello world"}}],\n'
            f'    "stream": false\n'
            f"  }}'"
        )
        self.copy_to_clipboard(curl_cmd, "cURL 请求命令")

    def copy_python_snippet(self) -> None:
        cfg = config_mgr.config
        model_name = self.model_alias_edit.text().strip()
        py_code = (
            "from openai import OpenAI\n\n"
            "client = OpenAI(\n"
            f'    base_url="{cfg.api_base_url}",\n'
            f'    api_key="{cfg.api_key}"\n'
            ")\n\n"
            "response = client.chat.completions.create(\n"
            f'    model="{model_name}",\n'
            '    messages=[{"role": "user", "content": "Hello"}],\n'
            "    stream=True\n"
            ")\n\n"
            "for chunk in response:\n"
            '    delta = chunk.choices[0].delta.content or ""\n'
            '    print(delta, end="", flush=True)\n'
        )
        self.copy_to_clipboard(py_code, "Python OpenAI SDK 代码")

    def copy_app_guide(self) -> None:
        cfg = config_mgr.config
        guide = (
            "【Cherry Studio / NextChat / Dify 接入配置说明】\n"
            f"1. 服务商规范: OpenAI API Compatible\n"
            f"2. Base URL: {cfg.api_base_url}\n"
            f"3. API Key: {cfg.api_key}\n"
            f"4. Model ID: {self.model_alias_edit.text().strip()}\n"
            f"5. 本地心跳: 客户端常驻期间保持双层心跳，防止 Colab 闲置回收。"
        )
        self.copy_to_clipboard(guide, "第三方客户端参数")

    def retranslate_ui(self) -> None:
        cfg = config_mgr.config
        self.setWindowTitle(f"{tr('app_title')} v{APP_VERSION}")
        self.brand_title.setText(tr("brand_title"))
        self.cap_all.setText(tr("filter_all"))
        self.btn_preset.setText(tr("btn_preset"))
        self.btn_sidebar_settings.setToolTip(tr("tip_settings"))
        self.user_name_lbl.setText(tr("session_prefix", session=cfg.colab_session))
        self.search_edit.setPlaceholderText(tr("search_placeholder"))
        self.btn_auth_badge.setText(tr("btn_auth_needed"))

        self.lbl_alias.setText(tr("lbl_alias"))
        self.model_alias_edit.setPlaceholderText(tr("ph_alias"))
        self.lbl_quant.setText(tr("lbl_quant"))
        self.lbl_ctx.setText(tr("lbl_ctx"))
        self.lbl_url.setText(tr("lbl_base_url"))
        self.btn_copy_url.setToolTip(tr("tip_copy_url"))
        self.lbl_key.setText(tr("lbl_api_key"))
        self.btn_toggle_key.setToolTip(tr("tip_toggle_key"))
        self.btn_copy_key.setToolTip(tr("tip_copy_key"))
        self.lbl_vram.setText(tr("lbl_vram"))
        self.btn_deploy.setText(tr("btn_deploy"))
        self.btn_stop.setText(tr("btn_stop"))
        self.btn_settings.setText(tr("btn_settings"))

        self.btn_tab_incoming.setText(tr("tab_logs"))
        self.btn_tab_outgoing.setText(tr("tab_chat"))
        self.autoscroll_check.setText(tr("chk_autoscroll"))
        self.btn_clear_log.setText(tr("btn_clear_log"))
        self.btn_export_log.setText(tr("btn_export_log"))

        self.access_title.setText(tr("access_title"))
        self.btn_curl.setText(tr("btn_copy_curl"))
        self.btn_curl.setToolTip(tr("tip_copy_curl"))
        self.btn_py.setText(tr("btn_copy_py"))
        self.btn_py.setToolTip(tr("tip_copy_py"))
        self.btn_client.setText(tr("btn_copy_client"))
        self.btn_client.setToolTip(tr("tip_copy_client"))
        self.health_title.setText(tr("health_title"))

        self._refresh_gpu_badge()
        self._refresh_strip_labels()
        self.url_display.setText(cfg.api_base_url)
        self.key_display.setText(cfg.api_key)
        self.chat_widget.retranslate_ui()
        self.update_status(self._last_status_code, self._last_status_desc)
        self.on_context_changed()

    def open_settings(self) -> None:
        prev_lang = config_mgr.config.language
        prev_gpu = config_mgr.config.colab_gpu
        dlg = SettingsDialog(self)
        if dlg.exec():
            self.retranslate_ui()
            if config_mgr.config.language != prev_lang and not self.search_edit.text().strip():
                self.load_preset_models()
            elif config_mgr.config.colab_gpu != prev_gpu:
                item = self.model_list.currentItem()
                if item:
                    self.on_model_selected(item)
            self.btn_auth_badge.setVisible(not colab_orchestrator.check_auth_non_interactive())
            self.append_log("[SETTINGS] Configuration updated.\n")

    def closeEvent(self, event) -> None:
        try:
            tunnel_daemon.stop()
        except Exception:
            pass
        event.accept()
