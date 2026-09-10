LIGHT_MINIMAL_STYLESHEET = """
QMainWindow {
    background-color: #f8fafc;
}

QWidget {
    color: #0f172a;
    font-family: 'Segoe UI Variable Text', 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Ubuntu', sans-serif;
    font-size: 11px;
}

/* -------------------------------------------------------------
   TOP NAVIGATION BAR & SEGMENTED TABS
   ------------------------------------------------------------- */
QFrame#navbar {
    background-color: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 11px;
    padding: 3px;
}

QPushButton.nav_tab {
    background-color: transparent;
    color: #64748b;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 600;
}

QPushButton.nav_tab:hover {
    color: #0f172a;
    background-color: rgba(255, 255, 255, 0.55);
}

QPushButton.nav_tab[active="true"] {
    background-color: #ffffff;
    color: #09090b;
    font-weight: 700;
    border: 1px solid rgba(0, 0, 0, 0.06);
}

/* -------------------------------------------------------------
   ROUTING MODE SEGMENTED CONTROL (DASHBOARD)
   ------------------------------------------------------------- */
QFrame#mode_segmented_bar {
    background-color: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 3px;
}

QPushButton.mode_segment {
    background-color: transparent;
    color: #64748b;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 6px 6px;
    font-size: 10.5px;
    font-weight: 600;
}

QPushButton.mode_segment:hover {
    color: #0f172a;
    background-color: rgba(255, 255, 255, 0.55);
}

QPushButton.mode_segment[active="true"] {
    background-color: #ffffff;
    color: #09090b;
    font-weight: 700;
    border: 1px solid rgba(0, 0, 0, 0.06);
}

/* -------------------------------------------------------------
   MAIN HERO CONNECT BUTTON
   ------------------------------------------------------------- */
QPushButton#btn_main_connect {
    background-color: #09090b;
    color: #ffffff;
    border: 2px solid #27272a;
    border-radius: 26px;
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 1.2px;
    padding: 13px 28px;
}

QPushButton#btn_main_connect:hover {
    background-color: #18181b;
    border: 2px solid #52525b;
}

QPushButton#btn_main_connect:pressed {
    background-color: #27272a;
    border: 2px solid #71717a;
}

QPushButton#btn_main_disconnect {
    background-color: #09090b;
    color: #ffffff;
    border: 2.5px solid #ef4444;
    border-radius: 26px;
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 1.2px;
    padding: 13px 28px;
}

QPushButton#btn_main_disconnect:hover {
    background-color: #18181b;
    border: 2.5px solid #f87171;
}

QPushButton#btn_main_disconnect:pressed {
    background-color: #27272a;
    border: 2.5px solid #dc2626;
}

/* -------------------------------------------------------------
   CARD CONTAINERS & TILES
   ------------------------------------------------------------- */
QFrame.card {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 13px;
}

QFrame.card:hover {
    border-color: #cbd5e1;
}

QFrame.setting_tile {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 11px;
    padding: 8px 10px;
}

QFrame.setting_tile:hover {
    border-color: #cbd5e1;
    background-color: #fafbfc;
}

QFrame.app_card {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 6px 10px;
}

QFrame.app_card:hover {
    border-color: #cbd5e1;
}

/* -------------------------------------------------------------
   SECONDARY & ACTION BUTTONS
   ------------------------------------------------------------- */
QPushButton.secondary_btn {
    background-color: #ffffff;
    color: #1e293b;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 5px 12px;
    font-weight: 600;
    font-size: 11px;
}

QPushButton.secondary_btn:hover {
    background-color: #f1f5f9;
    border-color: #cbd5e1;
    color: #0f172a;
}

QPushButton.secondary_btn:pressed {
    background-color: #e2e8f0;
}

QPushButton.chip_btn {
    background-color: #f1f5f9;
    color: #334155;
    border: 1px solid #e2e8f0;
    border-radius: 7px;
    padding: 3px 8px;
    font-size: 10px;
    font-weight: 600;
}

QPushButton.chip_btn:hover {
    background-color: #e2e8f0;
    color: #0f172a;
    border-color: #cbd5e1;
}

QPushButton.copy_btn {
    background-color: #f1f5f9;
    color: #1e293b;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 2px 7px;
    font-size: 10px;
    font-weight: 700;
}

QPushButton.copy_btn:hover {
    background-color: #e2e8f0;
    border-color: #cbd5e1;
    color: #0f172a;
}

QPushButton.copy_btn:pressed {
    background-color: #09090b;
    color: #ffffff;
}

/* -------------------------------------------------------------
   PRESET CHIP & STATUS BADGES
   ------------------------------------------------------------- */
QPushButton#btn_preset_chip {
    background-color: #ffffff;
    color: #334155;
    border: 1px solid #e2e8f0;
    border-radius: 11px;
    padding: 4px 12px;
    font-size: 10.5px;
    font-weight: 600;
}

QPushButton#btn_preset_chip:hover {
    background-color: #f8fafc;
    border-color: #cbd5e1;
    color: #0f172a;
}

QLabel.status_pill {
    padding: 4px 12px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
}

/* -------------------------------------------------------------
   FORM INPUTS & COMBOBOX
   ------------------------------------------------------------- */
QLineEdit, QSpinBox, QComboBox {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 6px 10px;
    color: #0f172a;
    font-size: 11px;
    font-weight: 500;
}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1.5px solid #09090b;
}

QComboBox#combo_dashboard_preset {
    background-color: #ffffff;
    color: #1e293b;
    border: 1px solid #e2e8f0;
    border-radius: 13px;
    padding: 3px 6px 3px 10px;
    font-size: 11px;
    font-weight: 700;
}

QComboBox#combo_dashboard_preset:hover {
    background-color: #f8fafc;
    border-color: #cbd5e1;
    color: #09090b;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border: none;
    background: transparent;
}

QComboBox::down-arrow {
    image: none;
    border-left: 3.5px solid transparent;
    border-right: 3.5px solid transparent;
    border-top: 4.5px solid #64748b;
    width: 0px;
    height: 0px;
    margin-right: 6px;
}

QComboBox::down-arrow:hover {
    border-top-color: #09090b;
}

/* Force pure white background on all combobox popups and containers */
QComboBox QAbstractItemView,
QComboBox QListView,
QListView {
    background-color: #ffffff !important;
    background: #ffffff !important;
    color: #0f172a !important;
    border: 1px solid #e2e8f0;
    border-radius: 9px;
    padding: 4px;
    outline: none;
    selection-background-color: #f1f5f9;
    selection-color: #09090b;
}

QComboBox QAbstractItemView::viewport,
QComboBox QListView::viewport,
QListView::viewport {
    background-color: #ffffff !important;
    background: #ffffff !important;
    color: #0f172a !important;
}

QComboBox QAbstractItemView::item,
QComboBox QListView::item,
QListView::item {
    background-color: #ffffff;
    color: #0f172a;
    min-height: 28px;
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
}

QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected,
QComboBox QListView::item:hover,
QComboBox QListView::item:selected,
QListView::item:hover,
QListView::item:selected {
    background-color: #f1f5f9 !important;
    color: #09090b !important;
}

QFrame#combo_popup_view,
QComboBoxPrivateContainer {
    background-color: #ffffff;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 9px;
}

/* -------------------------------------------------------------
   CHECKBOXES & TOGGLES
   ------------------------------------------------------------- */
QCheckBox {
    spacing: 8px;
    color: #0f172a;
    font-size: 11px;
    font-weight: 500;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1.5px solid #cbd5e1;
    background-color: #ffffff;
}

QCheckBox::indicator:hover {
    border-color: #94a3b8;
}

QCheckBox::indicator:checked {
    background-color: #09090b;
    border: 1.5px solid #09090b;
    image: url(assets/check.png);
}

QCheckBox:disabled {
    color: #94a3b8;
}

QCheckBox::indicator:disabled {
    background-color: #f1f5f9;
    border: 1px solid #e2e8f0;
}

/* -------------------------------------------------------------
   LOG VIEWER & TERMINAL STYLE
   ------------------------------------------------------------- */
QTextEdit#log_view {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 9px;
    color: #334155;
    font-family: 'Consolas', 'Cascadia Code', monospace;
    font-size: 10px;
    padding: 6px 8px;
}

/* -------------------------------------------------------------
   SCROLLBARS
   ------------------------------------------------------------- */
QScrollBar:vertical {
    background: transparent;
    width: 5px;
    margin: 0px;
    border-radius: 2px;
}

QScrollBar::handle:vertical {
    background: #cbd5e1;
    min-height: 24px;
    border-radius: 2px;
}

QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    height: 0px;
}

/* -------------------------------------------------------------
   TOOLTIPS
   ------------------------------------------------------------- */
QToolTip {
    background-color: #09090b;
    color: #ffffff;
    border: 1px solid #27272a;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 10px;
}
"""
