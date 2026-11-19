"""Shared Qt stylesheet.

Kept in one module so contributors can restyle the whole app without touching
widget code. The palette is intentionally light and high-contrast.
"""

STYLESHEET = """
QWidget {
    font-size: 13px;
}
QMainWindow, QDialog {
    background: #f7f8fa;
}
QGroupBox {
    border: 1px solid #d8dee9;
    border-radius: 8px;
    margin-top: 10px;
    padding: 10px 8px 8px 8px;
    background: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #344054;
    font-weight: 600;
}
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    border: 1px solid #d0d5dd;
    border-radius: 6px;
    padding: 5px 7px;
    background: #ffffff;
    selection-background-color: #d1e9ff;
}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #4a90e2;
}
QPushButton {
    border: 1px solid #d0d5dd;
    border-radius: 6px;
    padding: 6px 14px;
    background: #ffffff;
}
QPushButton:hover {
    background: #f2f4f7;
}
QPushButton:disabled {
    color: #98a2b3;
    background: #f2f4f7;
}
QPushButton#primaryButton {
    background: #1570ef;
    border-color: #1570ef;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background: #175cd3;
}
QPushButton#primaryButton[stopping="true"] {
    background: #d92d20;
    border-color: #d92d20;
}
QPushButton#dangerButton {
    color: #b42318;
    border-color: #fda29b;
}
QTabWidget::pane {
    border: 1px solid #d8dee9;
    border-radius: 8px;
    background: #ffffff;
}
QTabBar::tab {
    padding: 8px 16px;
    margin-right: 2px;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    color: #475467;
}
QTabBar::tab:selected {
    background: #ffffff;
    border-color: #d8dee9;
    border-bottom-color: #ffffff;
    color: #101828;
    font-weight: 600;
}
QTextBrowser {
    border: 1px solid #d8dee9;
    border-radius: 6px;
    background: #ffffff;
}
QListWidget {
    border: 1px solid #d8dee9;
    border-radius: 6px;
    background: #ffffff;
}
QListWidget::item {
    padding: 3px 2px;
}
QListWidget::indicator, QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #98a2b3;
    border-radius: 3px;
    background: #ffffff;
}
QListWidget::indicator:checked, QCheckBox::indicator:checked {
    background: #1570ef;
    border-color: #1570ef;
}
QListWidget::indicator:hover, QCheckBox::indicator:hover {
    border-color: #1570ef;
}
QStatusBar {
    background: #f2f4f7;
    color: #475467;
}
"""
