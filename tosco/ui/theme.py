"""Tema visual TOSCO: HUD escuro com neon ciano/magenta."""

BG = "#05070d"
PANEL = "#0a1020"
PANEL_2 = "#0e1730"
LINE = "#16304f"
CYAN = "#00e5ff"
MAGENTA = "#ff2bd6"
LIME = "#7cff4f"
AMBER = "#ffb02e"
RED = "#ff3b5c"
TEXT = "#cfe8ff"
MUTED = "#5f7a99"
FONT = "Segoe UI Variable Text, Segoe UI, sans-serif"   # texto: legível em qualquer tela
MONO = "Cascadia Mono, Consolas, monospace"            # logo, títulos HUD e registro


def rgba(hex_color, alpha):
    """'#7cff4f', 0.1 -> 'rgba(124,255,79,0.1)' (no Qt, '#rrggbbaa' seria lido como #aarrggbb)."""
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"

STATE_COLORS = {"ATIVO": LIME, "PAUSADO": AMBER, "PARADO": RED}

QSS = f"""
* {{ font-family: {FONT}; font-size: 12px; color: {TEXT}; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QToolTip {{ background: {PANEL_2}; color: {CYAN}; border: 1px solid {CYAN}; padding: 4px; }}

#sidebar {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #070c18, stop:1 #050810);
            border-right: 1px solid {LINE}; }}
#logo {{ font-family: {MONO}; color: {CYAN}; font-size: 20px; font-weight: 800; letter-spacing: 6px;
         padding: 18px 0 2px 0; }}
#logoSub {{ font-family: {MONO}; color: {MAGENTA}; font-size: 9px; letter-spacing: 4px; padding-bottom: 18px; }}
QPushButton#nav {{ text-align: left; padding: 8px 16px; border: none; border-left: 3px solid transparent;
                   background: transparent; color: #8aa3c2; font-size: 13px; letter-spacing: 0; }}
QPushButton#nav[main="true"] {{ color: {LIME}; }}
QPlainTextEdit {{ font-family: {MONO}; font-size: 11px; }}
QPushButton#nav:hover {{ color: {TEXT}; background: rgba(0,229,255,0.05); }}
QPushButton#nav:checked {{ color: {CYAN}; border-left: 3px solid {CYAN};
                           background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(0,229,255,0.18), stop:1 transparent); }}

#topbar {{ background: rgba(10,16,32,0.85); border-bottom: 1px solid {LINE}; }}
#pageTitle {{ font-family: {MONO}; color: {TEXT}; font-size: 16px; font-weight: 700; letter-spacing: 4px; }}
QLabel#h {{ font-family: {MONO}; }}
#crumb {{ color: {MUTED}; letter-spacing: 2px; font-size: 10px; }}

QFrame#card {{ background: rgba(10,16,32,0.92); border: 1px solid {LINE}; border-radius: 4px; }}
QFrame#card:hover {{ border: 1px solid #1f4a7a; }}
QFrame#cardOn {{ background: rgba(10,22,40,0.95); border: 1px solid rgba(0,229,255,0.55); border-radius: 4px; }}
QLabel#h {{ color: {CYAN}; font-size: 11px; letter-spacing: 3px; font-weight: 700; }}
QLabel#muted {{ color: {MUTED}; font-size: 11px; }}
QLabel#big {{ font-size: 26px; font-weight: 800; color: {TEXT}; }}
QLabel#glyph {{ font-size: 22px; color: {CYAN}; }}

QPushButton {{ background: {PANEL_2}; border: 1px solid {LINE}; padding: 7px 14px; border-radius: 3px;
               letter-spacing: 1px; }}
QPushButton:hover {{ border: 1px solid {CYAN}; color: {CYAN}; }}
QPushButton:pressed {{ background: rgba(0,229,255,0.15); }}
QPushButton:disabled {{ color: #34465c; border-color: #111d30; }}
QPushButton#go {{ border: 1px solid {LIME}; color: {LIME}; background: rgba(124,255,79,0.08); font-weight: 700; }}
QPushButton#go:hover {{ background: rgba(124,255,79,0.2); }}
QPushButton#warn {{ border: 1px solid {AMBER}; color: {AMBER}; background: rgba(255,176,46,0.08); font-weight: 700; }}
QPushButton#danger {{ border: 1px solid {RED}; color: {RED}; background: rgba(255,59,92,0.08); font-weight: 700; }}
QPushButton#accent {{ border: 1px solid {MAGENTA}; color: {MAGENTA}; background: rgba(255,43,214,0.08); }}
QPushButton#ghost {{ background: transparent; border: none; color: {MUTED}; padding: 2px 6px; }}
QPushButton#ghost:hover {{ color: {CYAN}; }}

QFrame#tile {{ background: #0b1324; border: 1px solid {LINE}; border-radius: 9px; }}
QFrame#tile:hover {{ border: 1px solid #2a5a8a; }}
QFrame#tile[sel="true"] {{ border: 1px solid {CYAN}; background: #0d1a30; }}
QFrame#tile[off="true"] QLabel {{ color: #6b7f99; }}
QFrame#sidepanel {{ background: #0a1222; border: 1px solid {LINE}; border-radius: 10px; }}
QLabel#navsec {{ color: #4d6585; font-size: 9px; font-weight: 700; letter-spacing: 2px; padding: 12px 18px 3px 18px; }}
QLabel#badge {{ color: {LIME}; border: 1px solid {LIME}; border-radius: 6px; padding: 0 5px; font-size: 9px; }}

QPushButton#chip {{ padding: 0 10px; border: 1px solid {LINE}; color: {MUTED}; background: transparent;
                    border-radius: 4px; font-size: 11px; letter-spacing: 0; min-height: 26px; max-height: 26px; }}
QPushButton#chip:checked {{ color: {CYAN}; border-color: {CYAN}; background: rgba(0,229,255,0.12); }}
QTableWidget QPushButton {{ padding: 2px 8px; }}
QMenu {{ background: {PANEL}; border: 1px solid {CYAN}; }}
QMenu::item:selected {{ background: rgba(0,229,255,0.2); }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit {{
    background: #060b16; border: 1px solid {LINE}; border-radius: 3px; padding: 2px 8px; min-height: 24px;
    selection-background-color: {CYAN};
    selection-color: {BG}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {CYAN}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {CYAN}; selection-background-color: rgba(0,229,255,0.25); }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {MUTED}; background: #060b16; border-radius: 2px; }}
QCheckBox::indicator:checked {{ background: {CYAN}; border: 1px solid {CYAN}; }}

QPlainTextEdit, QListWidget, QTableWidget {{ background: #04070e; border: 1px solid {LINE}; border-radius: 3px; }}
QListWidget::item {{ padding: 6px; border-bottom: 1px solid #0c1628; }}
QListWidget::item:selected {{ background: rgba(0,229,255,0.15); color: {CYAN}; }}
QHeaderView::section {{ background: {PANEL_2}; color: {CYAN}; border: none; padding: 5px; letter-spacing: 1px; }}
QTableWidget {{ gridline-color: #0c1628; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {CYAN}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}
QProgressBar {{ background: #060b16; border: 1px solid {LINE}; border-radius: 2px; height: 6px; text-align: center;
                font-size: 9px; color: transparent; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {CYAN}, stop:1 {MAGENTA}); }}
"""
