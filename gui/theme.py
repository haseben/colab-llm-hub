# -*- coding: utf-8 -*-
"""Figma Glassmorphism Dark Theme Tokens and Stylesheet.
Faithfully restored from Figma Community 'Glassmorphism Components' (Dark Frame):
- Authentic Windows 11 dark aurora background rendering
- Frosted glass cards (rgba tints with fine reflective borders)
- Figma form input styles, signature icy-cyan text (#B4C9CF) and emerald action buttons
"""

from __future__ import annotations

from qfluentwidgets import Theme, setTheme, setThemeColor

# ----------------- Palette Tokens ----------------- #
BG_CANVAS = "#070C0E"
BG_GLASS_CARD = "rgba(12, 18, 22, 0.72)"
BG_GLASS_SUBTLE = "rgba(18, 26, 32, 0.55)"
BG_GLASS_INPUT = "rgba(18, 26, 32, 0.65)"
BG_GLASS_INPUT_FOCUS = "rgba(22, 32, 40, 0.90)"

# Reflective Borders (Figma 0.5px / 1px soft icy edges)
BORDER_GLASS = "rgba(180, 201, 207, 0.20)"
BORDER_GLASS_HOVER = "rgba(180, 201, 207, 0.45)"
BORDER_GLASS_FOCUS = "#3BE2AF"
BORDER_SUBTLE = "rgba(180, 201, 207, 0.10)"

# Typography Colors
TEXT_WHITE = "#FFFFFF"
TEXT_ICY_CYAN = "#B4C9CF"       # Figma primary interactive / body tint
TEXT_MUTED = "#8E9BAE"          # Figma form label tint
TEXT_PLACEHOLDER = "rgba(142, 155, 174, 0.50)"

# Accents & Glass Buttons
ACCENT_CYAN = "#00F2FE"
ACCENT_EMERALD = "#229676"
ACCENT_EMERALD_BORDER = "#3BE2AF"

# Runtime Status Tokens
STATUS_ONLINE = "#10B981"
STATUS_DEPLOYING = "#F59E0B"
STATUS_OFFLINE = "#64748B"
STATUS_ERROR = "#EF4444"

# Monospace font stack for metrics, ports, IDs, and logs
MONO_FONT = "font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace;"
UI_FONT = "font-family: 'Segoe UI', 'Microsoft YaHei UI', -apple-system, sans-serif;"

# ----------------- Global Stylesheet ----------------- #
BASE_STYLESHEET = f"""
QMainWindow {{
    background-color: {BG_CANVAS};
    color: {TEXT_WHITE};
    {UI_FONT}
}}

QWidget#centralWidget {{
    background: transparent;
}}

/* Frosted Glass Card Containers */
.SimpleCardWidget, QWidget#glassPanel, QWidget.glassCard {{
    background-color: {BG_GLASS_CARD};
    border: 1px solid {BORDER_GLASS};
    border-radius: 10px;
}}

/* Form Input Controls (Opaque fill avoids cascading parent wallpaper repaints on every keystroke) */
LineEdit {{
    background-color: #10171D;
    border: 1px solid {BORDER_GLASS};
    border-radius: 6px;
    color: {TEXT_WHITE};
    padding: 6px 12px;
    selection-background-color: rgba(34, 150, 118, 0.5);
    font-size: 13px;
    {UI_FONT}
}}

LineEdit:hover {{
    border: 1px solid {BORDER_GLASS_HOVER};
}}

LineEdit:focus {{
    border: 1px solid {BORDER_GLASS_FOCUS};
    background-color: #141E26;
}}

ComboBox {{
    background-color: {BG_GLASS_INPUT};
    border: 1px solid {BORDER_GLASS};
    border-radius: 6px;
    color: {TEXT_WHITE};
    padding: 6px 12px;
    font-size: 13px;
    {UI_FONT}
}}

ComboBox:hover {{
    border: 1px solid {BORDER_GLASS_HOVER};
}}

ComboBox:focus {{
    border: 1px solid {BORDER_GLASS_FOCUS};
}}

/* Figma Emerald Glass Button (Primary Action - Search / Deploy) */
QPushButton#btnDeploy, PrimaryPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1E7E65, stop:1 #176551);
    border: 1px solid {ACCENT_EMERALD_BORDER};
    border-radius: 6px;
    color: {TEXT_WHITE};
    font-weight: 600;
    font-size: 13px;
    padding: 8px 22px;
    {UI_FONT}
}}

QPushButton#btnDeploy:hover, PrimaryPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #259B7D, stop:1 #1C7B63);
    border: 1px solid #58EDB7;
}}

QPushButton#btnDeploy:pressed, PrimaryPushButton:pressed {{
    background: #145947;
}}

/* Figma Frosted Secondary PushButtons (Cancel / Preset) */
PushButton, QPushButton#btnSecondary {{
    background-color: {BG_GLASS_SUBTLE};
    border: 1px solid {BORDER_GLASS};
    border-radius: 6px;
    color: {TEXT_ICY_CYAN};
    font-weight: 500;
    font-size: 13px;
    padding: 7px 16px;
    {UI_FONT}
}}

PushButton:hover, QPushButton#btnSecondary:hover {{
    background-color: rgba(35, 48, 58, 0.85);
    border: 1px solid {BORDER_GLASS_HOVER};
    color: {TEXT_WHITE};
}}

PushButton:pressed, QPushButton#btnSecondary:pressed {{
    background-color: rgba(14, 20, 24, 0.95);
}}

/* Cancel / Stop Button */
QPushButton#btnStop {{
    background-color: transparent;
    border: 1px solid {BORDER_GLASS};
    border-radius: 6px;
    color: {TEXT_ICY_CYAN};
    font-weight: 500;
    font-size: 13px;
    padding: 8px 20px;
    {UI_FONT}
}}

QPushButton#btnStop:hover {{
    background-color: rgba(239, 68, 68, 0.25);
    border: 1px solid rgba(239, 68, 68, 0.65);
    color: #FFFFFF;
}}

QPushButton#btnStop:pressed {{
    background-color: rgba(185, 28, 28, 0.55);
}}

/* Frosted Glass Tool Buttons */
ToolButton {{
    background-color: {BG_GLASS_SUBTLE};
    border: 1px solid {BORDER_GLASS};
    border-radius: 6px;
    color: {TEXT_ICY_CYAN};
}}

ToolButton:hover {{
    background-color: rgba(35, 48, 58, 0.80);
    border: 1px solid {BORDER_GLASS_HOVER};
    color: {TEXT_WHITE};
}}

/* Frosted List Widget */
QListWidget {{
    background-color: transparent;
    border: none;
    outline: none;
}}

QListWidget::item {{
    background-color: rgba(255, 255, 255, 0.02);
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 6px;
    margin-bottom: 6px;
    padding: 8px 10px;
}}

QListWidget::item:hover {{
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid {BORDER_GLASS_HOVER};
}}

QListWidget::item:selected {{
    background-color: rgba(34, 150, 118, 0.22);
    border: 1px solid {ACCENT_EMERALD_BORDER};
}}

/* Terminal Logs & PlainTextEdit (Opaque dark fill avoids parent repaint propagation on streaming) */
PlainTextEdit, QTextEdit {{
    background-color: #080D11;
    border: 1px solid {BORDER_GLASS};
    border-radius: 6px;
    color: #E2E8F0;
    selection-background-color: rgba(34, 150, 118, 0.50);
}}

/* CheckBox styling */
CheckBox {{
    color: {TEXT_ICY_CYAN};
    font-size: 12px;
}}

/* ScrollBars */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: rgba(180, 201, 207, 0.25);
    min-height: 24px;
    border-radius: 3px;
}}

QScrollBar::handle:vertical:hover {{
    background: rgba(180, 201, 207, 0.50);
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


def setup_theme(app=None) -> None:
    """Configure dark theme and apply Figma glassmorphism palette."""
    setTheme(Theme.DARK)
    setThemeColor("#229676")  # Figma Emerald accent
    if app:
        current_ss = app.styleSheet() or ""
        app.setStyleSheet(current_ss + "\n" + BASE_STYLESHEET)
