from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ThemePalette:
    name: str
    background: str
    panel: str
    card: str
    accent: str
    accent_alt: str
    text: str
    muted: str
    border: str
    success: str
    danger: str


THEMES: dict[str, ThemePalette] = {
    "Neon Cyan": ThemePalette("Neon Cyan", "#070B14", "#0B1220", "#101A2B", "#00E5FF", "#7C4DFF", "#F5FAFF", "#8CA0B8", "#1D3550", "#00E6A8", "#FF4D6D"),
    "Cyber Purple": ThemePalette("Cyber Purple", "#090711", "#120D20", "#1A1230", "#B14CFF", "#00E5FF", "#FBF7FF", "#AA9BBD", "#35264E", "#5CFFB0", "#FF5277"),
    "Emerald Grid": ThemePalette("Emerald Grid", "#06110D", "#0A1A14", "#0E241B", "#00F5A0", "#00D9F5", "#F2FFF9", "#8CB5A4", "#204536", "#55FFB3", "#FF5D73"),
    "Solar Red": ThemePalette("Solar Red", "#120709", "#1D0B0F", "#291016", "#FF365D", "#FF9D00", "#FFF7F8", "#C29AA3", "#4C202A", "#58F2A5", "#FF365D"),
    "Midnight Blue": ThemePalette("Midnight Blue", "#07101B", "#0D1826", "#122236", "#3182FF", "#38D9FF", "#F5F9FF", "#91A4BA", "#203956", "#40DFA3", "#FF607A"),
}


@dataclass
class UISettings:
    theme: str = "Neon Cyan"
    compact_mode: bool = False
    animations: bool = True


class UISettingsStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> UISettings:
        if not self.path.exists():
            return UISettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return UISettings()
        theme = str(data.get("theme") or "Neon Cyan")
        if theme not in THEMES:
            theme = "Neon Cyan"
        return UISettings(
            theme=theme,
            compact_mode=bool(data.get("compact_mode", False)),
            animations=bool(data.get("animations", True)),
        )

    def save(self, settings: UISettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.path)


def build_stylesheet(theme_name: str) -> str:
    p = THEMES.get(theme_name, THEMES["Neon Cyan"])
    return f"""
    QMainWindow, QWidget {{ background: {p.background}; color: {p.text}; }}
    QFrame#sidebar {{ background: {p.panel}; border-right: 1px solid {p.border}; }}
    QLabel#logo {{ color: {p.accent}; font-size: 22px; font-weight: 900; letter-spacing: 2px; }}
    QLabel#titulo_pagina {{ color: {p.text}; font-size: 28px; font-weight: 800; }}
    QLabel#section_title {{ color: {p.accent}; font-size: 17px; font-weight: 800; }}
    QLabel#metric_value {{ color: {p.accent}; font-size: 27px; font-weight: 900; }}
    QLabel#metric_label {{ color: {p.muted}; font-size: 12px; }}
    QFrame#metric_card, QFrame#card_status {{ background: {p.card}; border: 1px solid {p.border}; border-radius: 14px; }}
    QFrame#metric_card:hover {{ border: 1px solid {p.accent}; }}
    QPushButton {{ background: {p.card}; color: {p.text}; border: 1px solid {p.border}; border-radius: 10px; padding: 10px 14px; font-weight: 700; }}
    QPushButton:hover {{ border-color: {p.accent}; color: {p.accent}; }}
    QPushButton:disabled {{ color: {p.muted}; border-color: {p.border}; }}
    QPushButton#btn_nav {{ text-align: left; padding: 13px 16px; background: transparent; border: 0; color: {p.muted}; }}
    QPushButton#btn_nav:hover {{ background: {p.card}; color: {p.text}; }}
    QPushButton#btn_nav:checked {{ background: {p.accent}; color: #071018; border: 0; }}
    QPushButton#btn_primario, QPushButton#btn_destaque {{ background: {p.accent}; color: #071018; border: 0; padding: 12px 18px; }}
    QPushButton#btn_primario:hover, QPushButton#btn_destaque:hover {{ background: {p.accent_alt}; color: #071018; }}
    QPushButton#btn_success {{ background: {p.success}; color: #06100C; border: 0; }}
    QLineEdit, QTextEdit, QComboBox, QTableWidget {{ background: {p.card}; color: {p.text}; border: 1px solid {p.border}; border-radius: 9px; padding: 9px; selection-background-color: {p.accent}; selection-color: #071018; }}
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{ border: 1px solid {p.accent}; }}
    QComboBox QAbstractItemView {{ background: {p.card}; color: {p.text}; selection-background-color: {p.accent}; selection-color: #071018; }}
    QHeaderView::section {{ background: {p.panel}; color: {p.muted}; padding: 8px; border: 0; border-bottom: 1px solid {p.border}; }}
    QTableWidget {{ gridline-color: {p.border}; }}
    QProgressBar {{ border: 1px solid {p.border}; border-radius: 7px; background: {p.card}; text-align: center; }}
    QProgressBar::chunk {{ background: {p.accent}; border-radius: 6px; }}
    QCheckBox {{ color: {p.text}; spacing: 8px; }}
    QToolTip {{ background: {p.card}; color: {p.text}; border: 1px solid {p.accent}; }}
    """
