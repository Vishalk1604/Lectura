ACCENT = "#4f46e5"
ACCENT_DARK = "#4338ca"
RED = "#e5484d"

QSS = f"""
QWidget {{
    font-family: "Segoe UI", sans-serif;
    font-size: 10pt;
    color: #1f2330;
}}
QMainWindow, QDialog {{ background: #f5f6fa; }}
QFrame#card {{
    background: #ffffff;
    border: 1px solid #e3e5ee;
    border-radius: 10px;
}}
QLabel#h1 {{ font-size: 15pt; font-weight: 600; }}
QLabel#muted {{ color: #6b7085; }}
QLabel#status {{ font-size: 11pt; font-weight: 600; }}
QPushButton {{
    background: #ffffff;
    border: 1px solid #d5d8e3;
    border-radius: 7px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background: #f0f1f8; }}
QPushButton:pressed {{ background: #e5e7f2; }}
QPushButton:disabled {{ color: #a9adbd; background: #f6f7fa; border-color: #e6e8ef; }}
QPushButton#primary {{
    background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {ACCENT_DARK}; }}
QPushButton#primary:disabled {{ background: #b9b6f3; border-color: #b9b6f3; }}
QPushButton#danger {{
    background: {RED}; color: white; border: 1px solid {RED}; font-weight: 600;
}}
QPushButton#danger:hover {{ background: #d13f44; }}
QPushButton#danger:disabled {{ background: #f1b3b5; border-color: #f1b3b5; }}
QComboBox, QLineEdit {{
    background: #ffffff;
    border: 1px solid #d5d8e3;
    border-radius: 7px;
    padding: 6px 8px;
}}
QComboBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QCheckBox {{ spacing: 8px; }}
QSlider::groove:horizontal {{ height: 6px; background: #e3e5ee; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: white; border: 2px solid {ACCENT}; width: 14px; margin: -6px 0; border-radius: 9px;
}}
QListWidget {{
    background: #ffffff; border: 1px solid #e3e5ee; border-radius: 10px; padding: 8px;
}}
QListWidget::item {{ border-radius: 8px; padding: 6px; margin: 4px; }}
QListWidget::item:selected {{ background: #e6e5fb; color: #1f2330; }}
QProgressBar {{ border: 1px solid #d5d8e3; border-radius: 6px; text-align: center; height: 16px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
"""
