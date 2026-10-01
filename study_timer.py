#!/usr/bin/env python3
"""
StudyFlow — Minimalist Study Timer & Session Tracker
Dark contrast, distraction-free, zero flashy animations.
Robust QLocalServer single-instance & toggle IPC.
"""

import sys
import os
import sqlite3
import csv
from datetime import datetime, timedelta
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSystemTrayIcon, QMenu, QAction,
    QTabWidget, QComboBox, QFrame, QScrollArea, QDesktopWidget,
    QStackedWidget, QDialog, QLineEdit, QFileDialog, QMessageBox,
    QGridLayout, QSizePolicy, QColorDialog
)
from PyQt5.QtCore import (
    Qt, QTimer, QPoint, QSize, pyqtSignal, QObject, QRect
)
from PyQt5.QtGui import (
    QIcon, QFont, QColor, QPainter, QPen, QBrush, QPixmap
)
from PyQt5.QtNetwork import QLocalServer, QLocalSocket


# ─── Constants & Cross-Platform Database Path ─────────────────────────────────

APP_NAME = "StudyFlow"
VERSION = "1.0.0"

def _get_default_data_dir() -> Path:
    """Return platform-appropriate data directory for StudyFlow."""
    legacy = Path.home() / ".local" / "share" / "studyflow"
    if legacy.exists():
        return legacy
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "StudyFlow"
        return Path.home() / "AppData" / "Roaming" / "StudyFlow"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "StudyFlow"
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            return Path(xdg_data) / "studyflow"
        return legacy

DB_DIR = _get_default_data_dir()
DB_PATH = DB_DIR / "sessions.db"
SOCKET_NAME = "studyflow_ipc_socket"

# Default subjects seeded on fresh installs
DEFAULT_SUBJECT_DATA = [
    ("Physics",   "#EF4444", 0),  # Coral Red
    ("Chemistry", "#10B981", 1),  # Emerald Green
    ("Maths",     "#38BDF8", 2),  # Sky Blue
    ("English",   "#F59E0B", 3),  # Amber Gold
    ("Computer",  "#A855F7", 4),  # Vivid Purple
    ("Mixed",     "#EC4899", 5),  # Pink Rose
]

DEFAULT_SUBJECTS = [d[0] for d in DEFAULT_SUBJECT_DATA]
SUBJECTS = DEFAULT_SUBJECTS
DEFAULT_SUBJECT_COLOR = "#A1A1AA"
SUBJECT_COLORS = {d[0]: d[1] for d in DEFAULT_SUBJECT_DATA}

PRESET_COLORS = [
    "#EF4444",  # Coral Red
    "#F97316",  # Orange
    "#F59E0B",  # Amber Gold
    "#10B981",  # Emerald Green
    "#14B8A6",  # Teal
    "#06B6D4",  # Cyan
    "#38BDF8",  # Sky Blue
    "#6366F1",  # Indigo
    "#8B5CF6",  # Violet
    "#A855F7",  # Purple
    "#EC4899",  # Pink
    "#A1A1AA",  # Slate Zinc
]


# ─── Minimalist Dark Theme Colors ─────────────────────────────────────────────

COLORS = {
    "bg_window":       "#09090B",   # Obsidian dark
    "bg_panel":        "#121215",   # Dark panel
    "bg_card":         "#18181B",   # Flat card background
    "bg_hover":        "#27272A",   # Hover fill
    "border":          "#27272A",   # Subtle border
    "border_light":    "#3F3F46",   # Highlight border
    "text_primary":    "#FAFAFA",   # Crisp white
    "text_secondary":  "#A1A1AA",   # Soft zinc
    "text_dim":        "#52525B",   # Dim grey
    "accent":          "#E4E4E7",   # Clean neutral highlight
    "danger":          "#DC2626",   # Flat muted red
    "success":         "#16A34A",   # Flat muted green
}


# ─── Database ─────────────────────────────────────────────────────────────────

class Database:
    def __init__(self):
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL,
                date TEXT NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                color TEXT NOT NULL,
                sort_order INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()
        self._seed_default_subjects()

    def _seed_default_subjects(self):
        try:
            cursor = self.conn.execute("SELECT COUNT(*) FROM subjects")
            if cursor.fetchone()[0] == 0:
                for name, color, order in DEFAULT_SUBJECT_DATA:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO subjects (name, color, sort_order) VALUES (?, ?, ?)",
                        (name, color, order)
                    )
                # Auto-migrate distinct subjects from existing sessions table if any
                existing = self.conn.execute("SELECT DISTINCT subject FROM sessions").fetchall()
                order = len(DEFAULT_SUBJECT_DATA)
                for (s_name,) in existing:
                    if s_name and s_name not in [d[0] for d in DEFAULT_SUBJECT_DATA]:
                        c = PRESET_COLORS[order % len(PRESET_COLORS)]
                        self.conn.execute(
                            "INSERT OR IGNORE INTO subjects (name, color, sort_order) VALUES (?, ?, ?)",
                            (s_name, c, order)
                        )
                        order += 1
                self.conn.commit()
        except Exception:
            pass

    def get_setting(self, key, default=None):
        try:
            cursor = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default
        except Exception:
            return default

    def set_setting(self, key, value):
        try:
            self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
            self.conn.commit()
        except Exception:
            pass

    def save_session(self, subject, start_time, end_time, duration_seconds):
        date_str = start_time.strftime("%Y-%m-%d")
        self.conn.execute("""
            INSERT INTO sessions (subject, start_time, end_time, duration_seconds, date)
            VALUES (?, ?, ?, ?, ?)
        """, (subject, start_time.isoformat(), end_time.isoformat(),
              duration_seconds, date_str))
        self.conn.commit()

    def get_sessions(self, period="overall"):
        now = datetime.now()
        if period == "session":
            cursor = self.conn.execute(
                "SELECT * FROM sessions ORDER BY id DESC LIMIT 1"
            )
        elif period == "today":
            date_str = now.strftime("%Y-%m-%d")
            cursor = self.conn.execute(
                "SELECT * FROM sessions WHERE date = ?", (date_str,)
            )
        elif period == "3days":
            cutoff = (now - timedelta(days=3)).strftime("%Y-%m-%d")
            cursor = self.conn.execute(
                "SELECT * FROM sessions WHERE date >= ?", (cutoff,)
            )
        elif period == "week":
            cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")
            cursor = self.conn.execute(
                "SELECT * FROM sessions WHERE date >= ?", (cutoff,)
            )
        elif period == "month":
            cutoff = (now - timedelta(days=30)).strftime("%Y-%m-%d")
            cursor = self.conn.execute(
                "SELECT * FROM sessions WHERE date >= ?", (cutoff,)
            )
        else:
            cursor = self.conn.execute("SELECT * FROM sessions")

        rows = cursor.fetchall()
        return [{
            "id": r[0],
            "subject": r[1],
            "start_time": r[2],
            "end_time": r[3],
            "duration_seconds": r[4],
            "date": r[5]
        } for r in rows]

    def get_all_sessions(self):
        cursor = self.conn.execute("SELECT * FROM sessions ORDER BY id DESC")
        return [{
            "id": r[0],
            "subject": r[1],
            "start_time": r[2],
            "end_time": r[3],
            "duration_seconds": r[4],
            "date": r[5]
        } for r in cursor.fetchall()]

    def get_subjects(self):
        try:
            cursor = self.conn.execute("SELECT name, color FROM subjects ORDER BY sort_order ASC, id ASC")
            rows = cursor.fetchall()
            if rows:
                return [{"name": r[0], "color": r[1]} for r in rows]
        except Exception:
            pass
        return [{"name": d[0], "color": d[1]} for d in DEFAULT_SUBJECT_DATA]

    def get_subject_names(self):
        return [s["name"] for s in self.get_subjects()]

    def get_subject_colors(self):
        return {s["name"]: s["color"] for s in self.get_subjects()}

    def add_subject(self, name, color):
        name = name.strip()
        if not name:
            return False, "Subject name cannot be empty."
        try:
            max_order_row = self.conn.execute("SELECT MAX(sort_order) FROM subjects").fetchone()
            order = (max_order_row[0] or 0) + 1
            self.conn.execute(
                "INSERT INTO subjects (name, color, sort_order) VALUES (?, ?, ?)",
                (name, color, order)
            )
            self.conn.commit()
            return True, ""
        except sqlite3.IntegrityError:
            return False, f"A subject named '{name}' already exists."
        except Exception as e:
            return False, str(e)

    def update_subject(self, old_name, new_name, new_color):
        new_name = new_name.strip()
        if not new_name:
            return False, "Subject name cannot be empty."
        try:
            if old_name != new_name:
                existing = self.conn.execute(
                    "SELECT COUNT(*) FROM subjects WHERE name = ? AND name != ?",
                    (new_name, old_name)
                ).fetchone()[0]
                if existing > 0:
                    return False, f"A subject named '{new_name}' already exists."

            self.conn.execute(
                "UPDATE subjects SET name = ?, color = ? WHERE name = ?",
                (new_name, new_color, old_name)
            )
            if old_name != new_name:
                self.conn.execute(
                    "UPDATE sessions SET subject = ? WHERE subject = ?",
                    (new_name, old_name)
                )
            self.conn.commit()
            return True, ""
        except Exception as e:
            return False, str(e)

    def delete_subject(self, name):
        try:
            count = self.conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
            if count <= 1:
                return False, "You must keep at least one subject."
            self.conn.execute("DELETE FROM subjects WHERE name = ?", (name,))
            self.conn.commit()
            return True, ""
        except Exception as e:
            return False, str(e)

    def export_sessions_csv(self, file_path):
        cursor = self.conn.execute(
            "SELECT id, subject, start_time, end_time, duration_seconds, date FROM sessions ORDER BY id ASC"
        )
        rows = cursor.fetchall()
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Subject", "Start Time", "End Time", "Duration (Seconds)", "Duration (Formatted)", "Date"])
            for r in rows:
                writer.writerow([r[0], r[1], r[2], r[3], r[4], format_duration(r[4]), r[5]])
        return len(rows)

    def clear_all_sessions(self):
        self.conn.execute("DELETE FROM sessions")
        self.conn.commit()

    def reset_to_defaults(self):
        self.conn.execute("DELETE FROM subjects")
        self.conn.execute("DELETE FROM settings")
        self.conn.commit()
        self._seed_default_subjects()

    def close(self):
        self.conn.close()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def format_duration(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def make_color_dot_pixmap(color_hex, size=10):
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(color_hex)))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return pix


def create_tray_icon(active=False):
    pixmap = QPixmap(22, 22)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    if active:
        painter.setBrush(QBrush(QColor("#22C55E")))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(5, 5, 12, 12)
    else:
        painter.setBrush(QBrush(QColor("#52525B")))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(5, 5, 12, 12)

    painter.end()
    return QIcon(pixmap)


# ─── Minimalist Stylesheet ────────────────────────────────────────────────────

STYLESHEET = f"""
QMainWindow {{
    background-color: transparent;
}}

#CentralWidget {{
    background-color: {COLORS['bg_window']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
}}

QWidget {{
    color: {COLORS['text_primary']};
    font-family: 'Inter', 'SF Pro Text', -apple-system, sans-serif;
    font-size: 13px;
}}

QLabel {{
    background: transparent;
    border: none;
}}

QTabWidget::pane {{
    border: none;
    background-color: transparent;
    margin-top: 0px;
}}

QTabBar {{
    background: transparent;
    border: none;
    qproperty-drawBase: 0;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {COLORS['text_secondary']};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 7px 10px;
    margin-right: 2px;
    font-weight: 500;
    font-size: 12px;
}}

QTabBar::tab:selected {{
    color: {COLORS['text_primary']};
    border-bottom: 2px solid {COLORS['text_primary']};
    font-weight: 600;
}}

QTabBar::tab:hover {{
    color: {COLORS['text_primary']};
}}

QComboBox {{
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    padding: 5px 10px;
    background-color: {COLORS['bg_card']};
    color: {COLORS['text_primary']};
    font-size: 12px;
    min-width: 120px;
}}

QComboBox:hover {{
    border-color: {COLORS['border_light']};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {COLORS['text_secondary']};
    margin-right: 4px;
}}

QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_card']};
    border: 1px solid {COLORS['border']};
    color: {COLORS['text_primary']};
    selection-background-color: {COLORS['bg_hover']};
    selection-color: {COLORS['text_primary']};
    padding: 4px;
}}

QScrollArea {{
    border: none;
    background-color: transparent;
}}

QScrollBar:vertical {{
    background-color: transparent;
    width: 5px;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background-color: {COLORS['border']};
    min-height: 20px;
    border-radius: 2px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['border_light']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""


# ─── Minimal Timer Display Widget ─────────────────────────────────────────────

class MinimalTimerWidget(QWidget):
    """Timer display with clean typography and pause notice."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.elapsed_seconds = 0
        self.is_running = False
        self.is_paused = False
        self.pause_remaining = 0
        self.subject = "Mixed"
        self.setFixedHeight(130)

    def set_time(self, seconds):
        self.elapsed_seconds = seconds
        self.update()

    def set_running(self, running):
        self.is_running = running
        if not running:
            self.is_paused = False
            self.pause_remaining = 0
        self.update()

    def set_paused(self, paused, remaining=0):
        self.is_paused = paused
        self.pause_remaining = remaining
        self.update()

    def set_subject(self, subject):
        self.subject = subject
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()

        hours = self.elapsed_seconds // 3600
        minutes = (self.elapsed_seconds % 3600) // 60
        seconds = self.elapsed_seconds % 60
        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        # 1. Main Time Digits
        time_color = QColor(COLORS["text_dim"]) if not self.is_running else (
            QColor(COLORS["danger"]) if self.is_paused else QColor(COLORS["text_primary"])
        )
        painter.setPen(time_color)
        font = QFont("Inter", 38, QFont.Bold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        painter.setFont(font)
        painter.drawText(QRect(0, 8, rect.width(), 48), Qt.AlignCenter, time_str)

        # 2. Status / Subject Badge
        if self.is_paused:
            status_text = f"PAUSED ({self.pause_remaining // 60}:{self.pause_remaining % 60:02d} left)"
            badge_color = QColor(COLORS["danger"])
        elif self.is_running:
            status_text = self.subject.upper()
            badge_color = QColor(COLORS["text_secondary"])
        else:
            status_text = f"READY — {self.subject.upper()}"
            badge_color = QColor(COLORS["text_dim"])

        painter.setPen(badge_color)
        status_font = QFont("Inter", 10, QFont.Bold)
        status_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        painter.setFont(status_font)
        painter.drawText(QRect(0, 60, rect.width(), 20), Qt.AlignCenter, status_text)

        # 3. Anti-procrastination pause notice
        if self.is_paused:
            p_m = self.pause_remaining // 60
            p_s = self.pause_remaining % 60
            if self.pause_remaining <= 30:
                painter.setPen(QColor(COLORS["danger"]))
                banner = f"⚠ WARNING: Break ending in {p_s}s!"
            else:
                painter.setPen(QColor(COLORS["text_dim"]))
                banner = f"Break timer active: {p_m}:{p_s:02d} remaining"
            b_font = QFont("Inter", 10)
            painter.setFont(b_font)
            painter.drawText(QRect(0, 84, rect.width(), 20), Qt.AlignCenter, banner)
        elif self.is_running:
            painter.setPen(QColor(COLORS["text_dim"]))
            b_font = QFont("Inter", 10)
            painter.setFont(b_font)
            painter.drawText(QRect(0, 84, rect.width(), 20), Qt.AlignCenter, "Focus lock active")

        painter.end()


# ─── Minimal Subject Tag Button ──────────────────────────────────────────────

class SubjectTag(QPushButton):
    """Minimalist flat subject tag button with colored dot indicator."""

    def __init__(self, subject, color="#A1A1AA", parent=None):
        super().__init__(parent)
        self.subject = subject
        self.color = color
        self.is_selected = False
        self.setText(f" {subject}")
        self.setIcon(QIcon(make_color_dot_pixmap(self.color, 10)))
        self.setIconSize(QSize(10, 10))
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._update_style()

    def set_selected(self, selected):
        self.is_selected = selected
        self._update_style()

    def _update_style(self):
        if self.is_selected:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['text_primary']};
                    border: 1px solid {COLORS['text_primary']};
                    border-radius: 4px;
                    color: {COLORS['bg_window']};
                    font-weight: 700;
                    font-size: 11px;
                    padding: 0 6px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_card']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 4px;
                    color: {COLORS['text_secondary']};
                    font-weight: 500;
                    font-size: 11px;
                    padding: 0 6px;
                }}
                QPushButton:hover {{
                    border-color: {COLORS['border_light']};
                    background-color: {COLORS['bg_hover']};
                    color: {COLORS['text_primary']};
                }}
            """)


# ─── Period Selector (Today / 3 Days / Week / Month / All) ────────────────────

class PeriodSelector(QFrame):
    """Segmented pill bar for period filtering."""

    period_changed = pyqtSignal(str)

    PERIODS = [
        ("today",  "Today"),
        ("3days",  "3 Days"),
        ("week",   "Week"),
        ("month",  "Month"),
        ("all",    "All"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_period = "today"
        self.buttons = {}
        self._setup_ui()

    def _setup_ui(self):
        self.setObjectName("PeriodSelector")
        self.setStyleSheet(f"""
            QFrame#PeriodSelector {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        for key, label in self.PERIODS:
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(26)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda checked, k=key: self._on_select(k))
            self.buttons[key] = btn
            layout.addWidget(btn)

        self._update_styles()

    def _on_select(self, key):
        if self.current_period != key:
            self.current_period = key
            self._update_styles()
            self.period_changed.emit(key)

    def _update_styles(self):
        for key, btn in self.buttons.items():
            if key == self.current_period:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {COLORS['text_primary']};
                        border: none;
                        border-radius: 3px;
                        color: {COLORS['bg_window']};
                        font-weight: 700;
                        font-size: 11px;
                        padding: 0 4px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        border: none;
                        border-radius: 3px;
                        color: {COLORS['text_secondary']};
                        font-weight: 500;
                        font-size: 11px;
                        padding: 0 4px;
                    }}
                    QPushButton:hover {{
                        background-color: {COLORS['bg_hover']};
                        color: {COLORS['text_primary']};
                    }}
                """)

    def get_period(self):
        return self.current_period


# ─── Minimal Bar Chart Widget ─────────────────────────────────────────────────

class BarChartWidget(QWidget):
    """Clean multi-colored bar chart with percentages and background tracks."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = {}
        self.colors = {}
        self.setMinimumHeight(60)

    def set_data(self, data, colors=None):
        self.data = data
        self.colors = colors or {}
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if not self.data or sum(self.data.values()) == 0:
            painter.setPen(QColor(COLORS["text_dim"]))
            font = QFont("Inter", 11)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, "No study sessions recorded in this period.")
            painter.end()
            return

        total_time = sum(self.data.values())
        max_val = max(self.data.values()) if self.data else 1
        bar_height = 8
        row_height = 26

        left_label_width = 72
        bar_x = 78
        right_stat_width = 96
        bar_gap = 8
        available_bar_width = max(30, self.width() - bar_x - right_stat_width - bar_gap)

        y = 2
        for subject, seconds in sorted(self.data.items(), key=lambda x: -x[1]):
            color_hex = self.colors.get(subject, DEFAULT_SUBJECT_COLOR)
            display_name = subject[:9] + "…" if len(subject) > 10 else subject
            percent = int((seconds / total_time) * 100) if total_time > 0 else 0

            # 1. Subject colored dot indicator
            dot_x = 2
            dot_y = y + row_height // 2
            painter.setBrush(QBrush(QColor(color_hex)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPoint(dot_x, dot_y), 3, 3)

            # 2. Subject name text
            painter.setPen(QColor(COLORS["text_primary"]))
            font = QFont("Inter", 11, QFont.Medium)
            painter.setFont(font)
            painter.drawText(QRect(10, y, left_label_width - 10, row_height),
                             Qt.AlignLeft | Qt.AlignVCenter, display_name)

            # 3. Background track
            track_rect = QRect(bar_x, y + (row_height - bar_height) // 2, available_bar_width, bar_height)
            painter.setBrush(QBrush(QColor(COLORS["bg_card"])))
            painter.setPen(QPen(QColor(COLORS["border"]), 1))
            painter.drawRoundedRect(track_rect, 2, 2)

            # 4. Filled colored progress bar
            bar_width = max(int((seconds / max_val) * available_bar_width), 4)
            bar_rect = QRect(bar_x, y + (row_height - bar_height) // 2, bar_width, bar_height)
            painter.setBrush(QBrush(QColor(color_hex)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bar_rect, 2, 2)

            # 5. Right-side duration & percentage
            stat_x = bar_x + available_bar_width + bar_gap
            painter.setPen(QColor(COLORS["text_primary"]))
            font_stat = QFont("Inter", 10, QFont.DemiBold)
            painter.setFont(font_stat)
            dur_str = format_duration(seconds)
            pct_str = f"({percent}%)"
            full_stat = f"{dur_str} {pct_str}"
            painter.drawText(QRect(stat_x, y, right_stat_width, row_height),
                             Qt.AlignRight | Qt.AlignVCenter, full_stat)

            y += row_height

        self.setFixedHeight(y + 8)
        painter.end()


# ─── Weekly Comparison Widget ─────────────────────────────────────────────────

class WeeklyComparisonWidget(QFrame):
    """Compares today's study time against 7-day average."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WeeklyCard")
        self.setStyleSheet(f"""
            QFrame#WeeklyCard {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)

        left = QVBoxLayout()
        left.setSpacing(2)
        lbl = QLabel("TODAY VS 7-DAY AVG")
        lbl.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        left.addWidget(lbl)
        self.val_label = QLabel("0m  /  0m avg")
        self.val_label.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: 600;")
        left.addWidget(self.val_label)
        layout.addLayout(left)

        layout.addStretch()

        self.badge = QLabel("—")
        self.badge.setStyleSheet(f"""
            color: {COLORS['text_dim']};
            font-size: 11px;
            font-weight: 700;
            background-color: {COLORS['bg_panel']};
            border: 1px solid {COLORS['border']};
            border-radius: 3px;
            padding: 2px 8px;
        """)
        layout.addWidget(self.badge)

    def set_data(self, today_sec, avg_sec):
        t_str = format_duration(today_sec)
        a_str = format_duration(avg_sec)
        self.val_label.setText(f"{t_str}  /  {a_str} avg")

        if avg_sec == 0 and today_sec == 0:
            self.badge.setText("No data")
            self.badge.setStyleSheet(f"color: {COLORS['text_dim']}; background: {COLORS['bg_panel']}; border: 1px solid {COLORS['border']}; border-radius: 3px; padding: 2px 8px; font-size: 11px; font-weight: 700;")
        elif avg_sec == 0 and today_sec > 0:
            self.badge.setText("First day")
            self.badge.setStyleSheet(f"color: {COLORS['success']}; background: #052e16; border: 1px solid #166534; border-radius: 3px; padding: 2px 8px; font-size: 11px; font-weight: 700;")
        else:
            diff = today_sec - avg_sec
            pct = int(abs(diff) / avg_sec * 100)
            if diff >= 0:
                self.badge.setText(f"+{pct}%")
                self.badge.setStyleSheet(f"color: {COLORS['success']}; background: #052e16; border: 1px solid #166534; border-radius: 3px; padding: 2px 8px; font-size: 11px; font-weight: 700;")
            else:
                self.badge.setText(f"-{pct}%")
                self.badge.setStyleSheet(f"color: {COLORS['danger']}; background: #450a0a; border: 1px solid #991b1b; border-radius: 3px; padding: 2px 8px; font-size: 11px; font-weight: 700;")


# ─── Session Summary Card ─────────────────────────────────────────────────────

class SessionSummaryCard(QFrame):
    """Displays typical session duration (median) and session count."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SummaryCard")
        self.setStyleSheet(f"""
            QFrame#SummaryCard {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)

        # Left: Typical session length
        left = QVBoxLayout()
        left.setSpacing(2)
        lbl1 = QLabel("TYPICAL SESSION (MEDIAN)")
        lbl1.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        left.addWidget(lbl1)
        self.typical_lbl = QLabel("—")
        self.typical_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 14px; font-weight: 700;")
        left.addWidget(self.typical_lbl)
        layout.addLayout(left)

        layout.addStretch()

        # Right: Total sessions in period
        right = QVBoxLayout()
        right.setSpacing(2)
        lbl2 = QLabel("SESSIONS LOGGED")
        lbl2.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        lbl2.setAlignment(Qt.AlignRight)
        right.addWidget(lbl2)
        self.count_lbl = QLabel("0")
        self.count_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 14px; font-weight: 700;")
        self.count_lbl.setAlignment(Qt.AlignRight)
        right.addWidget(self.count_lbl)
        layout.addLayout(right)

    def set_data(self, sessions):
        session_count = len(sessions)
        self.count_lbl.setText(str(session_count))

        if session_count == 0:
            self.typical_lbl.setText("—")
            return

        durations = [s["duration_seconds"] for s in sessions if s["duration_seconds"] > 0]
        if not durations:
            self.typical_lbl.setText("—")
            return

        sorted_durations = sorted(durations)
        mid = session_count // 2
        if session_count % 2 == 1:
            typical_time = sorted_durations[mid]
        else:
            typical_time = (sorted_durations[mid - 1] + sorted_durations[mid]) // 2

        self.typical_lbl.setText(format_duration(typical_time))


# ─── Pomodoro Timer Display Widget ────────────────────────────────────────────

class PomodoroTimerWidget(QWidget):
    """Pomodoro display with large numbers, cycle dots, and phase badges."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.time_remaining = 25 * 60
        self.phase = "FOCUS"
        self.current_round = 1
        self.total_rounds = 4
        self.is_running = False
        self.is_paused = False
        self.subject = "Mixed"
        self.setFixedHeight(140)

    def set_state(self, remaining, phase, current_round, total_rounds, running, paused, subject):
        self.time_remaining = remaining
        self.phase = phase
        self.current_round = current_round
        self.total_rounds = total_rounds
        self.is_running = running
        self.is_paused = paused
        self.subject = subject
        self.update()

    def set_subject(self, subject):
        self.subject = subject
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()

        mins = self.time_remaining // 60
        secs = self.time_remaining % 60
        time_str = f"{mins:02d}:{secs:02d}"

        # 1. Main Time Digits
        if self.phase == "FOCUS":
            time_color = QColor(COLORS["danger"]) if self.is_paused else QColor(COLORS["text_primary"])
        elif self.phase == "SHORT_BREAK":
            time_color = QColor(COLORS["success"])
        else:
            time_color = QColor("#38BDF8")  # Sky Blue for Long Break

        painter.setPen(time_color)
        font = QFont("Inter", 38, QFont.Bold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        painter.setFont(font)
        painter.drawText(QRect(0, 8, rect.width(), 48), Qt.AlignCenter, time_str)

        # 2. Status badge / Phase text
        status_font = QFont("Inter", 10, QFont.Bold)
        status_font.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        painter.setFont(status_font)

        if self.is_paused:
            status_text = f"PAUSED — {self.phase}"
            painter.setPen(QColor(COLORS["danger"]))
        elif self.is_running:
            if self.phase == "FOCUS":
                status_text = f"FOCUSING ON {self.subject.upper()}"
                painter.setPen(QColor(COLORS["text_secondary"]))
            elif self.phase == "SHORT_BREAK":
                status_text = "SHORT BREAK"
                painter.setPen(QColor(COLORS["success"]))
            else:
                status_text = "LONG BREAK"
                painter.setPen(QColor("#38BDF8"))
        else:
            status_text = f"READY — {self.phase} ({self.subject.upper()})"
            painter.setPen(QColor(COLORS["text_dim"]))

        painter.drawText(QRect(0, 60, rect.width(), 20), Qt.AlignCenter, status_text)

        # 3. Round indicator dots
        dot_radius = 4
        dot_spacing = 14
        total_width = self.total_rounds * (dot_radius * 2) + (self.total_rounds - 1) * dot_spacing
        start_x = (rect.width() - total_width) // 2
        y_pos = 92

        for i in range(self.total_rounds):
            x = start_x + i * (dot_radius * 2 + dot_spacing) + dot_radius
            if i + 1 < self.current_round:
                painter.setBrush(QBrush(QColor(COLORS["success"])))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPoint(x, y_pos), dot_radius, dot_radius)
            elif i + 1 == self.current_round:
                painter.setBrush(QBrush(time_color))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPoint(x, y_pos), dot_radius + 1, dot_radius + 1)
            else:
                painter.setBrush(QBrush(QColor(COLORS["border"])))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPoint(x, y_pos), dot_radius, dot_radius)

        cycle_font = QFont("Inter", 10)
        painter.setFont(cycle_font)
        painter.setPen(QColor(COLORS["text_dim"]))
        cycle_str = f"Round {self.current_round} of {self.total_rounds}"
        painter.drawText(QRect(0, 108, rect.width(), 20), Qt.AlignCenter, cycle_str)

        painter.end()


# ─── Stepper Row for Settings ─────────────────────────────────────────────────

class StepperRow(QFrame):
    """Minimalist stepper control with [-] [value unit] [+] buttons."""

    value_changed = pyqtSignal(int)

    def __init__(self, title, initial_value, min_val, max_val, unit="min", step=1, parent=None):
        super().__init__(parent)
        self.value = initial_value
        self.min_val = min_val
        self.max_val = max_val
        self.unit = unit
        self.step = step
        self._setup_ui(title)

    def _setup_ui(self, title):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: 500; font-size: 12px;")
        layout.addWidget(title_lbl)

        layout.addStretch()

        btn_style = f"""
            QPushButton {{
                background-color: {COLORS['bg_panel']};
                border: 1px solid {COLORS['border']};
                border-radius: 3px;
                color: {COLORS['text_primary']};
                font-weight: 700;
                font-size: 14px;
                min-width: 28px;
                max-width: 28px;
                min-height: 26px;
                max-height: 26px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['bg_hover']};
                border-color: {COLORS['border_light']};
            }}
            QPushButton:pressed {{
                background-color: {COLORS['border']};
            }}
        """

        self.minus_btn = QPushButton("−")
        self.minus_btn.setCursor(Qt.PointingHandCursor)
        self.minus_btn.setStyleSheet(btn_style)
        self.minus_btn.clicked.connect(self._decrement)
        layout.addWidget(self.minus_btn)

        self.val_lbl = QLabel(f"{self.value} {self.unit}")
        self.val_lbl.setFixedWidth(65)
        self.val_lbl.setAlignment(Qt.AlignCenter)
        self.val_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: 700; font-size: 12px;")
        layout.addWidget(self.val_lbl)

        self.plus_btn = QPushButton("+")
        self.plus_btn.setCursor(Qt.PointingHandCursor)
        self.plus_btn.setStyleSheet(btn_style)
        self.plus_btn.clicked.connect(self._increment)
        layout.addWidget(self.plus_btn)

    def _decrement(self):
        if self.value - self.step >= self.min_val:
            self.value -= self.step
            self.val_lbl.setText(f"{self.value} {self.unit}")
            self.value_changed.emit(self.value)

    def _increment(self):
        if self.value + self.step <= self.max_val:
            self.value += self.step
            self.val_lbl.setText(f"{self.value} {self.unit}")
            self.value_changed.emit(self.value)


# ─── Toggle Row (ON / OFF Switch) ─────────────────────────────────────────────

class ToggleRow(QFrame):
    """Clean iOS/macOS-style ON/OFF pill switch card."""

    toggled = pyqtSignal(bool)

    def __init__(self, title, subtitle, initial_state=True, parent=None):
        super().__init__(parent)
        self.state = initial_state
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: 500; font-size: 12px;")
        text_layout.addWidget(title_lbl)

        if subtitle:
            sub_lbl = QLabel(subtitle)
            sub_lbl.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px;")
            text_layout.addWidget(sub_lbl)
        layout.addLayout(text_layout)

        layout.addStretch()

        self.btn = QPushButton("ON" if self.state else "OFF")
        self.btn.setFixedSize(46, 26)
        self.btn.setCursor(Qt.PointingHandCursor)
        self._update_btn_style()
        self.btn.clicked.connect(self._toggle)
        layout.addWidget(self.btn)

    def _toggle(self):
        self.state = not self.state
        self.btn.setText("ON" if self.state else "OFF")
        self._update_btn_style()
        self.toggled.emit(self.state)

    def _update_btn_style(self):
        if self.state:
            self.btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['text_primary']};
                    border: 1px solid {COLORS['text_primary']};
                    border-radius: 13px;
                    color: {COLORS['bg_window']};
                    font-weight: 700;
                    font-size: 10px;
                }}
            """)
        else:
            self.btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_panel']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 13px;
                    color: {COLORS['text_dim']};
                    font-weight: 600;
                    font-size: 10px;
                }}
            """)


# ─── Subject Row for Settings ─────────────────────────────────────────────────

class SubjectRow(QFrame):
    """Row in settings subjects list with color dot, name, and edit/delete actions."""

    edited = pyqtSignal(str)
    deleted = pyqtSignal(str)

    def __init__(self, name, color, can_delete=True, parent=None):
        super().__init__(parent)
        self.name = name
        self.color = color
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
            }}
            QFrame:hover {{
                border-color: {COLORS['border_light']};
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(8)

        dot_btn = QPushButton()
        dot_btn.setFixedSize(16, 16)
        dot_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.2);
            }}
            QPushButton:hover {{
                border: 1px solid white;
            }}
        """)
        dot_btn.setCursor(Qt.PointingHandCursor)
        dot_btn.setToolTip("Click to edit subject")
        dot_btn.clicked.connect(lambda: self.edited.emit(name))
        layout.addWidget(dot_btn)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: 600; font-size: 12px;")
        layout.addWidget(name_lbl)

        layout.addStretch()

        edit_btn = QPushButton("✎")
        edit_btn.setFixedSize(24, 24)
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {COLORS['text_secondary']};
                font-size: 13px;
            }}
            QPushButton:hover {{
                color: {COLORS['text_primary']};
            }}
        """)
        edit_btn.setToolTip("Edit subject")
        edit_btn.clicked.connect(lambda: self.edited.emit(name))
        layout.addWidget(edit_btn)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(24, 24)
        del_btn.setCursor(Qt.PointingHandCursor if can_delete else Qt.ArrowCursor)
        del_btn.setEnabled(can_delete)
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {COLORS['danger'] if can_delete else COLORS['text_dim']};
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                color: {'#EF4444' if can_delete else COLORS['text_dim']};
            }}
        """)
        del_btn.setToolTip("Delete subject" if can_delete else "Cannot delete the only subject")
        if can_delete:
            del_btn.clicked.connect(lambda: self.deleted.emit(name))
        layout.addWidget(del_btn)


# ─── Subject Edit / Add Dialog ────────────────────────────────────────────────

class SubjectEditDialog(QDialog):
    """Clean dark-theme modal dialog to add or edit a subject."""

    def __init__(self, parent=None, title="Add Subject", current_name="", current_color="#38BDF8"):
        super().__init__(parent)
        self.selected_color = current_color
        self.setWindowTitle(title)
        self.setFixedSize(320, 260)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._setup_ui(title, current_name)

    def _setup_ui(self, title, current_name):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_window']};
                border: 1px solid {COLORS['border_light']};
                border-radius: 6px;
            }}
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(18, 16, 18, 16)
        c_layout.setSpacing(12)

        t_lbl = QLabel(title.upper())
        t_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: 700; font-size: 13px; letter-spacing: 1px;")
        c_layout.addWidget(t_lbl)

        self.name_input = QLineEdit(current_name)
        self.name_input.setPlaceholderText("Subject name (e.g. Biology, Coding...)")
        self.name_input.setFixedHeight(34)
        self.name_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                color: {COLORS['text_primary']};
                padding: 0 10px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border-color: {COLORS['accent']};
            }}
        """)
        c_layout.addWidget(self.name_input)

        color_lbl = QLabel("PICK A COLOR")
        color_lbl.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        c_layout.addWidget(color_lbl)

        swatch_layout = QGridLayout()
        swatch_layout.setSpacing(8)
        self.swatch_buttons = []
        for idx, hex_col in enumerate(PRESET_COLORS):
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda ch, c=hex_col: self._pick_color(c))
            self.swatch_buttons.append((btn, hex_col))
            row = idx // 6
            col = idx % 6
            swatch_layout.addWidget(btn, row, col)
        c_layout.addLayout(swatch_layout)

        custom_row = QHBoxLayout()
        self.preview_badge = QLabel("  ● Preview  ")
        self.preview_badge.setFixedHeight(24)
        custom_row.addWidget(self.preview_badge)

        custom_row.addStretch()

        custom_btn = QPushButton("Custom...")
        custom_btn.setFixedHeight(24)
        custom_btn.setCursor(Qt.PointingHandCursor)
        custom_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 3px;
                color: {COLORS['text_secondary']};
                font-size: 11px;
                padding: 0 8px;
            }}
            QPushButton:hover {{
                color: {COLORS['text_primary']};
                border-color: {COLORS['border_light']};
            }}
        """)
        custom_btn.clicked.connect(self._open_custom_color_dialog)
        custom_row.addWidget(custom_btn)
        c_layout.addLayout(custom_row)

        self._refresh_swatches()

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                color: {COLORS['text_secondary']};
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                color: {COLORS['text_primary']};
            }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setFixedHeight(32)
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['text_primary']};
                border: 1px solid {COLORS['text_primary']};
                border-radius: 4px;
                color: {COLORS['bg_window']};
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: #E4E4E7;
            }}
        """)
        save_btn.clicked.connect(self.accept)
        btn_layout.addWidget(save_btn)

        c_layout.addLayout(btn_layout)
        layout.addWidget(card)

    def _pick_color(self, hex_color):
        self.selected_color = hex_color
        self._refresh_swatches()

    def _open_custom_color_dialog(self):
        col = QColorDialog.getColor(QColor(self.selected_color), self, "Select Custom Color")
        if col.isValid():
            self._pick_color(col.name())

    def _refresh_swatches(self):
        for btn, hex_col in self.swatch_buttons:
            is_active = (hex_col.lower() == self.selected_color.lower())
            border = "2px solid white" if is_active else "1px solid rgba(255,255,255,0.15)"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {hex_col};
                    border-radius: 11px;
                    border: {border};
                }}
            """)
        self.preview_badge.setStyleSheet(f"""
            background-color: {COLORS['bg_card']};
            border: 1px solid {COLORS['border']};
            border-radius: 3px;
            color: {self.selected_color};
            font-size: 11px;
            font-weight: bold;
        """)

    def get_data(self):
        return self.name_input.text().strip(), self.selected_color


# ─── Timer Tab Widget ────────────────────────────────────────────────────────

class TimerTab(QWidget):
    """Main minimalist timer interface with dynamic subject tags."""

    session_saved = pyqtSignal()
    started = pyqtSignal()
    notification_requested = pyqtSignal(str, str)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.is_running = False
        self.is_paused = False
        self.elapsed_seconds = 0
        self.pause_seconds_left = 0
        self.pause_cooldown = 0
        self.start_time = None
        self.selected_subject = self._get_initial_subject()
        self._setup_ui()
        self._setup_timer()

    def _get_initial_subject(self):
        names = self.db.get_subject_names()
        return names[0] if names else "General"

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        self.timer_widget = MinimalTimerWidget()
        layout.addWidget(self.timer_widget)

        tags_label = QLabel("SELECT SUBJECT")
        tags_label.setAlignment(Qt.AlignCenter)
        tags_label.setStyleSheet(f"""
            color: {COLORS['text_dim']};
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1.5px;
            margin-top: 1px;
        """)
        layout.addWidget(tags_label)

        # Dynamic scrollable subject tags container
        self.tags_scroll = QScrollArea()
        self.tags_scroll.setWidgetResizable(True)
        self.tags_scroll.setFixedHeight(72)
        self.tags_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tags_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tags_scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS['border_light']};
                border-radius: 2px;
            }}
        """)

        self.tags_container = QWidget()
        self.tags_container.setStyleSheet("background: transparent;")
        self.tags_grid = QGridLayout(self.tags_container)
        self.tags_grid.setContentsMargins(0, 0, 0, 0)
        self.tags_grid.setSpacing(6)
        self.tags_scroll.setWidget(self.tags_container)
        layout.addWidget(self.tags_scroll)

        self.tag_buttons = {}
        self._populate_subject_tags()

        # Action & Pause buttons row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.pause_button = QPushButton("⏸ PAUSE")
        self.pause_button.setFixedHeight(44)
        self.pause_button.setCursor(Qt.ArrowCursor)
        self.pause_button.setEnabled(False)
        self._set_pause_btn_style("disabled")
        self.pause_button.setToolTip("Start studying to enable pause")
        self.pause_button.clicked.connect(self._toggle_pause)
        btn_layout.addWidget(self.pause_button)

        self.action_button = QPushButton("START STUDYING")
        self.action_button.setCursor(Qt.PointingHandCursor)
        self.action_button.setFixedHeight(44)
        self._set_start_button_style()
        self.action_button.clicked.connect(self._toggle_timer)
        btn_layout.addWidget(self.action_button)

        layout.addLayout(btn_layout)

        hint = QLabel("Super + Z to toggle window")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(hint)

        layout.addStretch()

    def _populate_subject_tags(self):
        while self.tags_grid.count():
            item = self.tags_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.tag_buttons = {}

        subjects = self.db.get_subjects()
        if not subjects:
            subjects = [{"name": "General", "color": "#A1A1AA"}]

        names = [s["name"] for s in subjects]
        if self.selected_subject not in names:
            self.selected_subject = names[0]

        cols = 3
        for idx, s_info in enumerate(subjects):
            name = s_info["name"]
            color = s_info["color"]
            btn = SubjectTag(name, color)
            btn.clicked.connect(lambda checked, s=name: self._select_subject(s))
            self.tag_buttons[name] = btn
            row = idx // cols
            col = idx % cols
            self.tags_grid.addWidget(btn, row, col)

        if self.selected_subject in self.tag_buttons:
            self.tag_buttons[self.selected_subject].set_selected(True)
        self.timer_widget.set_subject(self.selected_subject)

    def reload_subjects(self):
        self._populate_subject_tags()

    def reload_settings(self):
        pass

    def _setup_timer(self):
        self.tick_timer = QTimer(self)
        self.tick_timer.setInterval(1000)
        self.tick_timer.timeout.connect(self._tick)

    def _set_start_button_style(self):
        self.action_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['text_primary']};
                border: 1px solid {COLORS['text_primary']};
                border-radius: 4px;
                color: {COLORS['bg_window']};
                font-weight: 700;
                font-size: 13px;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background-color: #E4E4E7;
            }}
        """)

    def _set_stop_button_style(self):
        self.action_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['danger']};
                border: 1px solid {COLORS['danger']};
                border-radius: 4px;
                color: white;
                font-weight: 700;
                font-size: 13px;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background-color: #B91C1C;
            }}
        """)

    def _set_pause_btn_style(self, state):
        if state == "disabled":
            self.pause_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_card']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 4px;
                    color: {COLORS['text_dim']};
                    font-weight: 700;
                    font-size: 12px;
                    letter-spacing: 0.5px;
                }}
            """)
        elif state == "ready":
            self.pause_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_card']};
                    border: 1px solid {COLORS['border_light']};
                    border-radius: 4px;
                    color: {COLORS['text_primary']};
                    font-weight: 700;
                    font-size: 12px;
                    letter-spacing: 0.5px;
                }}
                QPushButton:hover {{
                    background-color: {COLORS['bg_hover']};
                }}
            """)
        elif state == "paused":
            self.pause_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['danger']};
                    border: 1px solid {COLORS['danger']};
                    border-radius: 4px;
                    color: white;
                    font-weight: 700;
                    font-size: 11px;
                    letter-spacing: 0.5px;
                }}
                QPushButton:hover {{
                    background-color: #B91C1C;
                }}
            """)
        elif state == "cooldown":
            self.pause_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_panel']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 4px;
                    color: {COLORS['text_dim']};
                    font-weight: 600;
                    font-size: 11px;
                    letter-spacing: 0.5px;
                }}
            """)

    def _select_subject(self, subject):
        if self.is_running:
            return
        self.selected_subject = subject
        for s, btn in self.tag_buttons.items():
            btn.set_selected(s == subject)
        self.timer_widget.set_subject(subject)

    def _toggle_timer(self):
        if self.is_running:
            self._stop_timer()
        else:
            self._start_timer()

    def _start_timer(self):
        self.started.emit()
        self.is_running = True
        self.is_paused = False
        self.pause_seconds_left = 0
        self.pause_cooldown = 0
        self.elapsed_seconds = 0
        self.start_time = datetime.now()
        self.timer_widget.set_running(True)
        self.tick_timer.start()

        self.action_button.setText("STOP & SAVE")
        self._set_stop_button_style()

        p_limit = int(self.db.get_setting("max_pause_minutes", 3))
        self.pause_button.setEnabled(True)
        self.pause_button.setCursor(Qt.PointingHandCursor)
        self.pause_button.setText("⏸ PAUSE")
        self._set_pause_btn_style("ready")
        self.pause_button.setToolTip(f"Pause timer (max {p_limit} minutes)")

        for btn in self.tag_buttons.values():
            btn.setEnabled(False)

    def _toggle_pause(self):
        if not self.is_running:
            return
        if self.is_paused:
            self._resume_timer(manual=True)
        else:
            if self.pause_cooldown > 0:
                return
            self._pause_timer()

    def _pause_timer(self):
        self.is_paused = True
        max_pause_sec = int(self.db.get_setting("max_pause_minutes", 3)) * 60
        self.pause_seconds_left = max_pause_sec
        self.timer_widget.set_paused(True, self.pause_seconds_left)

        m = self.pause_seconds_left // 60
        s = self.pause_seconds_left % 60
        self.pause_button.setText(f"▶ RESUME ({m}:{s:02d})")
        self._set_pause_btn_style("paused")
        self.pause_button.setToolTip("Click to resume studying before pause limit expires")

    def _resume_timer(self, manual=False):
        self.is_paused = False
        self.pause_seconds_left = 0
        self.timer_widget.set_paused(False)

        cd_sec = int(self.db.get_setting("pause_cooldown_minutes", 3)) * 60
        self.pause_cooldown = cd_sec
        self.pause_button.setEnabled(False)
        self.pause_button.setCursor(Qt.ArrowCursor)

        cd_m = self.pause_cooldown // 60
        cd_s = self.pause_cooldown % 60
        self.pause_button.setText(f"⏳ CD ({cd_m}:{cd_s:02d})")
        self._set_pause_btn_style("cooldown")
        self.pause_button.setToolTip(f"Pause on cooldown ({cd_m}m {cd_s:02d}s remaining)")

        if not manual:
            p_limit = int(self.db.get_setting("max_pause_minutes", 3))
            self.notification_requested.emit(
                "Pause Limit Reached",
                f"Your {p_limit}-minute pause has ended. Study session resumed!"
            )

    def _stop_timer(self):
        self.tick_timer.stop()
        self.is_running = False
        self.is_paused = False
        self.pause_seconds_left = 0
        self.pause_cooldown = 0
        self.timer_widget.set_running(False)

        end_time = datetime.now()
        min_sec = int(self.db.get_setting("min_session_seconds", 10))
        if self.elapsed_seconds >= min_sec:
            self.db.save_session(
                self.selected_subject,
                self.start_time or datetime.now(),
                end_time,
                self.elapsed_seconds
            )
            self.session_saved.emit()

        self.elapsed_seconds = 0
        self.timer_widget.set_time(0)

        self.action_button.setText("START STUDYING")
        self._set_start_button_style()

        self.pause_button.setEnabled(False)
        self.pause_button.setCursor(Qt.ArrowCursor)
        self.pause_button.setText("⏸ PAUSE")
        self._set_pause_btn_style("disabled")
        self.pause_button.setToolTip("Start studying to enable pause")

        for btn in self.tag_buttons.values():
            btn.setEnabled(True)

    def _tick(self):
        if self.is_paused:
            self.pause_seconds_left -= 1
            if self.pause_seconds_left <= 0:
                self._resume_timer(manual=False)
            else:
                self.timer_widget.set_paused(True, self.pause_seconds_left)
                m = self.pause_seconds_left // 60
                s = self.pause_seconds_left % 60
                self.pause_button.setText(f"▶ RESUME ({m}:{s:02d})")
        else:
            self.elapsed_seconds += 1
            self.timer_widget.set_time(self.elapsed_seconds)

            if self.pause_cooldown > 0:
                self.pause_cooldown -= 1
                if self.pause_cooldown > 0:
                    cd_m = self.pause_cooldown // 60
                    cd_s = self.pause_cooldown % 60
                    self.pause_button.setText(f"⏳ CD ({cd_m}:{cd_s:02d})")
                    self.pause_button.setToolTip(f"Pause on cooldown ({cd_m}m {cd_s:02d}s remaining)")
                else:
                    self.pause_button.setEnabled(True)
                    self.pause_button.setCursor(Qt.PointingHandCursor)
                    self.pause_button.setText("⏸ PAUSE")
                    self._set_pause_btn_style("ready")
                    p_limit = int(self.db.get_setting("max_pause_minutes", 3))
                    self.pause_button.setToolTip(f"Pause timer (max {p_limit} minutes)")

    def get_is_running(self):
        return self.is_running

    def get_pause_time_remaining_str(self):
        if not self.is_paused:
            return ""
        m = self.pause_seconds_left // 60
        s = self.pause_seconds_left % 60
        return f"{m}:{s:02d}"


# ─── Pomodoro Tab Widget ──────────────────────────────────────────────────────

class PomodoroTab(QWidget):
    """Pomodoro timer with cycle tracking and dynamic subjects."""

    session_saved = pyqtSignal()
    started = pyqtSignal()
    notification_requested = pyqtSignal(str, str)
    settings_requested = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.task_time = int(self.db.get_setting("pomo_task_time", 25))
        self.break_time = int(self.db.get_setting("pomo_break_time", 5))
        self.long_break_time = int(self.db.get_setting("pomo_long_break_time", 15))
        self.sessions_until_long = int(self.db.get_setting("pomo_sessions_until_long", 4))

        self.time_remaining = self.task_time * 60
        self.phase = "FOCUS"
        self.current_round = 1
        self.is_running = False
        self.is_paused = False
        self.focus_start_time = None
        self.focus_seconds_completed = 0
        self.selected_subject = self._get_initial_subject()

        self._setup_ui()
        self._setup_timer()

    def _get_initial_subject(self):
        names = self.db.get_subject_names()
        return names[0] if names else "General"

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.timer_page = QWidget()
        layout = QVBoxLayout(self.timer_page)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.pomo_widget = PomodoroTimerWidget()
        layout.addWidget(self.pomo_widget)

        tags_label = QLabel("SELECT SUBJECT")
        tags_label.setAlignment(Qt.AlignCenter)
        tags_label.setStyleSheet(f"""
            color: {COLORS['text_dim']};
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1.5px;
            margin-top: 1px;
        """)
        layout.addWidget(tags_label)

        # Dynamic scrollable subject tags
        self.tags_scroll = QScrollArea()
        self.tags_scroll.setWidgetResizable(True)
        self.tags_scroll.setFixedHeight(72)
        self.tags_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tags_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tags_scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS['border_light']};
                border-radius: 2px;
            }}
        """)

        self.tags_container = QWidget()
        self.tags_container.setStyleSheet("background: transparent;")
        self.tags_grid = QGridLayout(self.tags_container)
        self.tags_grid.setContentsMargins(0, 0, 0, 0)
        self.tags_grid.setSpacing(6)
        self.tags_scroll.setWidget(self.tags_container)
        layout.addWidget(self.tags_scroll)

        self.tag_buttons = {}
        self._populate_subject_tags()

        # Main Action Button
        self.action_btn = QPushButton("START FOCUS")
        self.action_btn.setCursor(Qt.PointingHandCursor)
        self.action_btn.setFixedHeight(42)
        self._set_primary_btn_style()
        self.action_btn.clicked.connect(self._toggle_timer)
        layout.addWidget(self.action_btn)

        # Secondary Control Buttons Row
        sec_layout = QHBoxLayout()
        sec_layout.setSpacing(8)

        self.skip_btn = QPushButton("Skip Phase ⏭")
        self.skip_btn.setCursor(Qt.PointingHandCursor)
        self.skip_btn.setFixedHeight(30)
        self._set_sec_btn_style(self.skip_btn)
        self.skip_btn.clicked.connect(self._skip_phase)
        sec_layout.addWidget(self.skip_btn)

        self.reset_btn = QPushButton("Reset ↺")
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.setFixedHeight(30)
        self._set_sec_btn_style(self.reset_btn)
        self.reset_btn.clicked.connect(self._reset_timer)
        sec_layout.addWidget(self.reset_btn)

        self.settings_btn = QPushButton("⚙ Settings")
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setFixedHeight(30)
        self._set_sec_btn_style(self.settings_btn)
        self.settings_btn.clicked.connect(lambda: self.settings_requested.emit())
        sec_layout.addWidget(self.settings_btn)

        layout.addLayout(sec_layout)
        layout.addStretch()

        main_layout.addWidget(self.timer_page)

    def _populate_subject_tags(self):
        while self.tags_grid.count():
            item = self.tags_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.tag_buttons = {}

        subjects = self.db.get_subjects()
        if not subjects:
            subjects = [{"name": "General", "color": "#A1A1AA"}]

        names = [s["name"] for s in subjects]
        if self.selected_subject not in names:
            self.selected_subject = names[0]

        cols = 3
        for idx, s_info in enumerate(subjects):
            name = s_info["name"]
            color = s_info["color"]
            btn = SubjectTag(name, color)
            btn.clicked.connect(lambda checked, s=name: self._select_subject(s))
            self.tag_buttons[name] = btn
            row = idx // cols
            col = idx % cols
            self.tags_grid.addWidget(btn, row, col)

        if self.selected_subject in self.tag_buttons:
            self.tag_buttons[self.selected_subject].set_selected(True)
        self.pomo_widget.set_subject(self.selected_subject)

    def reload_subjects(self):
        self._populate_subject_tags()

    def reload_settings(self):
        self.task_time = int(self.db.get_setting("pomo_task_time", 25))
        self.break_time = int(self.db.get_setting("pomo_break_time", 5))
        self.long_break_time = int(self.db.get_setting("pomo_long_break_time", 15))
        self.sessions_until_long = int(self.db.get_setting("pomo_sessions_until_long", 4))
        if not self.is_running:
            if self.phase == "FOCUS":
                self.time_remaining = self.task_time * 60
            elif self.phase == "SHORT_BREAK":
                self.time_remaining = self.break_time * 60
            else:
                self.time_remaining = self.long_break_time * 60
            self._update_widget_state()

    def _setup_timer(self):
        self.tick_timer = QTimer(self)
        self.tick_timer.setInterval(1000)
        self.tick_timer.timeout.connect(self._tick)

    def _set_primary_btn_style(self):
        self.action_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['text_primary']};
                border: 1px solid {COLORS['text_primary']};
                border-radius: 4px;
                color: {COLORS['bg_window']};
                font-weight: 700;
                font-size: 13px;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background-color: #E4E4E7;
            }}
        """)

    def _set_paused_btn_style(self):
        self.action_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['danger']};
                border: 1px solid {COLORS['danger']};
                border-radius: 4px;
                color: white;
                font-weight: 700;
                font-size: 13px;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background-color: #B91C1C;
            }}
        """)

    def _set_sec_btn_style(self, btn):
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                color: {COLORS['text_secondary']};
                font-weight: 500;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['bg_hover']};
                border-color: {COLORS['border_light']};
                color: {COLORS['text_primary']};
            }}
        """)

    def _select_subject(self, subject):
        if self.is_running:
            return
        self.selected_subject = subject
        for s, btn in self.tag_buttons.items():
            btn.set_selected(s == subject)
        self.pomo_widget.set_subject(subject)

    def _toggle_timer(self):
        if not self.is_running:
            self._start_timer()
        elif self.is_paused:
            self._resume_timer()
        else:
            self._pause_timer()

    def _start_timer(self):
        self.started.emit()
        self.is_running = True
        self.is_paused = False
        if self.phase == "FOCUS" and self.focus_start_time is None:
            self.focus_start_time = datetime.now()
        self.tick_timer.start()

        for btn in self.tag_buttons.values():
            btn.setEnabled(False)

        self._update_button_label()
        self._update_widget_state()

    def _pause_timer(self):
        self.is_paused = True
        self._update_button_label()
        self._update_widget_state()

    def _resume_timer(self):
        self.is_paused = False
        self._update_button_label()
        self._update_widget_state()

    def _stop_timer(self, save_if_focus=False):
        self.tick_timer.stop()
        if self.is_running and self.phase == "FOCUS" and save_if_focus:
            min_sec = int(self.db.get_setting("min_session_seconds", 10))
            if self.focus_seconds_completed >= min_sec:
                self.db.save_session(
                    self.selected_subject,
                    self.focus_start_time or datetime.now(),
                    datetime.now(),
                    self.focus_seconds_completed
                )
                self.session_saved.emit()

        self.is_running = False
        self.is_paused = False
        self.focus_start_time = None
        self.focus_seconds_completed = 0
        for btn in self.tag_buttons.values():
            btn.setEnabled(True)
        self._update_button_label()
        self._update_widget_state()

    def _reset_timer(self):
        self._stop_timer(save_if_focus=True)
        if self.phase == "FOCUS":
            self.time_remaining = self.task_time * 60
        elif self.phase == "SHORT_BREAK":
            self.time_remaining = self.break_time * 60
        else:
            self.time_remaining = self.long_break_time * 60
        self._update_widget_state()

    def _skip_phase(self):
        min_sec = int(self.db.get_setting("min_session_seconds", 10))
        if self.phase == "FOCUS" and self.focus_seconds_completed >= min_sec:
            self.db.save_session(
                self.selected_subject,
                self.focus_start_time or datetime.now(),
                datetime.now(),
                self.focus_seconds_completed
            )
            self.session_saved.emit()
        self._advance_phase(from_skip=True)

    def _advance_phase(self, from_skip=False):
        self.tick_timer.stop()
        self.is_running = False
        self.is_paused = False
        self.focus_start_time = None
        self.focus_seconds_completed = 0

        for btn in self.tag_buttons.values():
            btn.setEnabled(True)

        if self.phase == "FOCUS":
            if self.current_round >= self.sessions_until_long:
                self.phase = "LONG_BREAK"
                self.time_remaining = self.long_break_time * 60
                self.current_round = 1
                if not from_skip:
                    self.notification_requested.emit(
                        "Long Break Time!",
                        f"Great work! You completed all {self.sessions_until_long} focus rounds. Enjoy your {self.long_break_time}m break!"
                    )
            else:
                self.phase = "SHORT_BREAK"
                self.time_remaining = self.break_time * 60
                self.current_round += 1
                if not from_skip:
                    self.notification_requested.emit(
                        "Short Break Time!",
                        f"Focus session complete ({self.selected_subject}). Take a {self.break_time}m break!"
                    )
        else:
            self.phase = "FOCUS"
            self.time_remaining = self.task_time * 60
            if not from_skip:
                self.notification_requested.emit(
                    "Break Over!",
                    f"Ready to focus on {self.selected_subject}? Round {self.current_round} starts now!"
                )

        self._update_button_label()
        self._update_widget_state()

    def _tick(self):
        if not self.is_running or self.is_paused:
            return

        self.time_remaining -= 1
        if self.phase == "FOCUS":
            self.focus_seconds_completed += 1

        if self.time_remaining <= 0:
            if self.phase == "FOCUS":
                self.db.save_session(
                    self.selected_subject,
                    self.focus_start_time or datetime.now(),
                    datetime.now(),
                    self.focus_seconds_completed
                )
                self.session_saved.emit()
            self._advance_phase(from_skip=False)
        else:
            self._update_widget_state()

    def _update_widget_state(self):
        self.pomo_widget.set_state(
            self.time_remaining,
            self.phase,
            self.current_round,
            self.sessions_until_long,
            self.is_running,
            self.is_paused,
            self.selected_subject
        )

    def _update_button_label(self):
        if not self.is_running:
            lbl = "START FOCUS" if self.phase == "FOCUS" else "START BREAK"
            self.action_btn.setText(lbl)
            self._set_primary_btn_style()
        elif self.is_paused:
            self.action_btn.setText("RESUME ▶")
            self._set_paused_btn_style()
        else:
            self.action_btn.setText("PAUSE ⏸")
            self._set_primary_btn_style()

    def get_is_running(self):
        return self.is_running

    def get_phase_display(self):
        return self.phase

    def get_time_remaining_str(self):
        mins = self.time_remaining // 60
        secs = self.time_remaining % 60
        return f"{mins:02d}:{secs:02d}"


# ─── Statistics Tab Widget ────────────────────────────────────────────────────

class StatsTab(QWidget):
    """Statistics view with period filters, weekly comparison, and history."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._setup_ui()
        self._refresh_stats()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # 1. Period Selector (Segmented control)
        self.period_selector = PeriodSelector()
        self.period_selector.period_changed.connect(lambda p: self._refresh_stats())
        layout.addWidget(self.period_selector)

        # 2. Scroll Area for stats content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        c_layout = QVBoxLayout(content)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(12)

        # 3. Weekly comparison card
        self.weekly_card = WeeklyComparisonWidget()
        c_layout.addWidget(self.weekly_card)

        # 4. Typical session median card
        self.summary_card = SessionSummaryCard()
        c_layout.addWidget(self.summary_card)

        # 5. Subject Breakdown Header
        bd_header = QLabel("SUBJECT BREAKDOWN")
        bd_header.setStyleSheet(f"""
            color: {COLORS['text_dim']};
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1.5px;
            margin-top: 4px;
        """)
        c_layout.addWidget(bd_header)

        # 6. Bar Chart Widget
        self.chart = BarChartWidget()
        c_layout.addWidget(self.chart)

        # 7. Recent Sessions Section Header
        recent_header = QLabel("RECENT SESSIONS")
        recent_header.setStyleSheet(f"""
            color: {COLORS['text_dim']};
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1.5px;
            margin-top: 4px;
        """)
        c_layout.addWidget(recent_header)

        # 8. Recent Sessions Container
        self.recent_container = QVBoxLayout()
        self.recent_container.setSpacing(4)
        c_layout.addLayout(self.recent_container)

        c_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def _refresh_stats(self):
        period = self.period_selector.get_period()
        sessions = self.db.get_sessions(period)

        # 1. Update Weekly Comparison
        today_sessions = self.db.get_sessions("today")
        today_sec = sum(s["duration_seconds"] for s in today_sessions)
        week_sessions = self.db.get_sessions("week")
        week_sec = sum(s["duration_seconds"] for s in week_sessions)
        avg_sec = week_sec // 7
        self.weekly_card.set_data(today_sec, avg_sec)

        # 2. Update Summary Card (median calculation)
        self.summary_card.set_data(sessions)

        # 3. Update Subject Breakdown Bar Chart
        subject_data = {}
        for s in sessions:
            subj = s["subject"]
            subject_data[subj] = subject_data.get(subj, 0) + s["duration_seconds"]

        colors = self.db.get_subject_colors()
        self.chart.set_data(subject_data, colors=colors)

        # 4. Update Recent Sessions List
        while self.recent_container.count():
            item = self.recent_container.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not sessions:
            empty_lbl = QLabel("No study sessions logged for this period.")
            empty_lbl.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px; padding: 8px 0;")
            empty_lbl.setAlignment(Qt.AlignCenter)
            self.recent_container.addWidget(empty_lbl)
        else:
            colors = self.db.get_subject_colors()
            for session in reversed(sessions[-8:]):
                row = self._create_session_row(session, colors)
                self.recent_container.addWidget(row)

    def _create_session_row(self, session, colors=None):
        row = QFrame()
        row.setObjectName("SessionRow")
        row.setStyleSheet(f"""
            QFrame#SessionRow {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
            }}
            QFrame#SessionRow:hover {{
                border-color: {COLORS['border_light']};
                background-color: {COLORS['bg_hover']};
            }}
        """)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 6, 10, 6)
        row_layout.setSpacing(6)

        subj = session["subject"]
        color_hex = (colors or {}).get(subj, DEFAULT_SUBJECT_COLOR)
        dur = session["duration_seconds"]

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {color_hex}; font-size: 10px;")
        row_layout.addWidget(dot)

        subj_label = QLabel(subj)
        subj_label.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: 500; font-size: 12px;")
        row_layout.addWidget(subj_label)

        if dur < 300:
            tag = QLabel("short")
            tag.setStyleSheet(f"""
                color: {COLORS['text_dim']};
                font-size: 9px;
                font-weight: 600;
                background-color: {COLORS['bg_panel']};
                padding: 1px 4px;
                border-radius: 2px;
            """)
            row_layout.addWidget(tag)

        row_layout.addStretch()

        dur_label = QLabel(format_duration(dur))
        dur_label.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: 600; font-size: 12px;")
        row_layout.addWidget(dur_label)

        try:
            dt = datetime.fromisoformat(session["start_time"])
            time_str = dt.strftime("%b %d, %H:%M")
        except Exception:
            time_str = session["date"]

        time_label = QLabel(time_str)
        time_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        row_layout.addWidget(time_label)

        return row


# ─── Settings Tab Widget ──────────────────────────────────────────────────────

class SettingsTab(QWidget):
    """Comprehensive settings view: Subjects CRUD, timers, behavior, and data."""

    subjects_changed = pyqtSignal()
    always_on_top_changed = pyqtSignal(bool)
    settings_changed = pyqtSignal(str, object)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS['border_light']};
                border-radius: 2px;
            }}
        """)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(4, 2, 4, 16)
        c_layout.setSpacing(14)

        # ── 1. Subjects Section ──
        c_layout.addWidget(self._create_section_header("SUBJECTS & COLORS", "Customize subjects, tags, and color badges"))

        self.subjects_container = QVBoxLayout()
        self.subjects_container.setSpacing(5)
        c_layout.addLayout(self.subjects_container)
        self._refresh_subjects_list()

        add_subj_btn = QPushButton("+ Add New Subject")
        add_subj_btn.setFixedHeight(32)
        add_subj_btn.setCursor(Qt.PointingHandCursor)
        add_subj_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_card']};
                border: 1px dashed {COLORS['border_light']};
                border-radius: 4px;
                color: {COLORS['text_primary']};
                font-weight: 600;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['bg_hover']};
                border-color: {COLORS['accent']};
            }}
        """)
        add_subj_btn.clicked.connect(self._add_subject_dialog)
        c_layout.addWidget(add_subj_btn)

        # ── 2. Timer & Breaks ──
        c_layout.addWidget(self._create_section_header("TIMER & BREAK LIMITS", "Anti-procrastination pause limits"))

        p_limit = int(self.db.get_setting("max_pause_minutes", 3))
        self.pause_stepper = StepperRow("Max Pause Duration", p_limit, 1, 30, "min", 1)
        self.pause_stepper.value_changed.connect(lambda v: self._save_setting("max_pause_minutes", v))
        c_layout.addWidget(self.pause_stepper)

        p_cd = int(self.db.get_setting("pause_cooldown_minutes", 3))
        self.cd_stepper = StepperRow("Pause Cooldown", p_cd, 1, 30, "min", 1)
        self.cd_stepper.value_changed.connect(lambda v: self._save_setting("pause_cooldown_minutes", v))
        c_layout.addWidget(self.cd_stepper)

        min_sec = int(self.db.get_setting("min_session_seconds", 10))
        self.min_stepper = StepperRow("Discard Sessions Under", min_sec, 0, 120, "sec", 5)
        self.min_stepper.value_changed.connect(lambda v: self._save_setting("min_session_seconds", v))
        c_layout.addWidget(self.min_stepper)

        # ── 3. Pomodoro Intervals ──
        c_layout.addWidget(self._create_section_header("POMODORO INTERVALS", "Custom work and rest durations"))

        task_t = int(self.db.get_setting("pomo_task_time", 25))
        self.pomo_task_s = StepperRow("Focus Time", task_t, 1, 120, "min", 1)
        self.pomo_task_s.value_changed.connect(lambda v: self._save_setting("pomo_task_time", v))
        c_layout.addWidget(self.pomo_task_s)

        break_t = int(self.db.get_setting("pomo_break_time", 5))
        self.pomo_break_s = StepperRow("Short Break Time", break_t, 1, 30, "min", 1)
        self.pomo_break_s.value_changed.connect(lambda v: self._save_setting("pomo_break_time", v))
        c_layout.addWidget(self.pomo_break_s)

        lbreak_t = int(self.db.get_setting("pomo_long_break_time", 15))
        self.pomo_lbreak_s = StepperRow("Long Break Time", lbreak_t, 1, 60, "min", 1)
        self.pomo_lbreak_s.value_changed.connect(lambda v: self._save_setting("pomo_long_break_time", v))
        c_layout.addWidget(self.pomo_lbreak_s)

        rounds_t = int(self.db.get_setting("pomo_sessions_until_long", 4))
        self.pomo_rounds_s = StepperRow("Rounds to Long Break", rounds_t, 1, 10, "rounds", 1)
        self.pomo_rounds_s.value_changed.connect(lambda v: self._save_setting("pomo_sessions_until_long", v))
        c_layout.addWidget(self.pomo_rounds_s)

        # ── 4. Preferences ──
        c_layout.addWidget(self._create_section_header("WINDOW & BEHAVIOR", "Display and alert preferences"))

        is_top = bool(int(self.db.get_setting("always_on_top", 1)))
        self.top_toggle = ToggleRow("Always on Top", "Float HUD above other open windows", is_top)
        self.top_toggle.toggled.connect(self._on_top_toggled)
        c_layout.addWidget(self.top_toggle)

        is_notif = bool(int(self.db.get_setting("notifications_enabled", 1)))
        self.notif_toggle = ToggleRow("Desktop Notifications", "Show alerts on break/session finish", is_notif)
        self.notif_toggle.toggled.connect(lambda st: self._save_setting("notifications_enabled", 1 if st else 0))
        c_layout.addWidget(self.notif_toggle)

        is_sound = bool(int(self.db.get_setting("sound_enabled", 1)))
        self.sound_toggle = ToggleRow("Sound Alert", "Play system bell on timer completion", is_sound)
        self.sound_toggle.toggled.connect(lambda st: self._save_setting("sound_enabled", 1 if st else 0))
        c_layout.addWidget(self.sound_toggle)

        # ── 5. Data & Export ──
        c_layout.addWidget(self._create_section_header("DATA MANAGEMENT", "Export or manage your study history"))

        export_btn = QPushButton("📥 Export Sessions to CSV")
        export_btn.setFixedHeight(34)
        export_btn.setCursor(Qt.PointingHandCursor)
        export_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                color: {COLORS['text_primary']};
                font-weight: 600;
                font-size: 11px;
            }}
            QPushButton:hover {{
                border-color: {COLORS['border_light']};
                background-color: {COLORS['bg_hover']};
            }}
        """)
        export_btn.clicked.connect(self._export_csv)
        c_layout.addWidget(export_btn)

        reset_btn = QPushButton("↺ Reset Subjects & Settings to Defaults")
        reset_btn.setFixedHeight(30)
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                color: {COLORS['danger']};
                font-weight: 500;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #2D1515;
                border-color: {COLORS['danger']};
            }}
        """)
        reset_btn.clicked.connect(self._reset_defaults)
        c_layout.addWidget(reset_btn)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def _create_section_header(self, title, subtitle):
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 4, 0, 0)
        l.setSpacing(1)

        t_lbl = QLabel(title)
        t_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: 700; font-size: 11px; letter-spacing: 1px;")
        l.addWidget(t_lbl)

        s_lbl = QLabel(subtitle)
        s_lbl.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px;")
        l.addWidget(s_lbl)
        return w

    def _save_setting(self, key, value):
        self.db.set_setting(key, value)
        self.settings_changed.emit(key, value)

    def _refresh_subjects_list(self):
        while self.subjects_container.count():
            item = self.subjects_container.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        subjects = self.db.get_subjects()
        can_delete = len(subjects) > 1
        for s in subjects:
            row = SubjectRow(s["name"], s["color"], can_delete=can_delete)
            row.edited.connect(self._edit_subject_dialog)
            row.deleted.connect(self._delete_subject)
            self.subjects_container.addWidget(row)

    def _add_subject_dialog(self):
        dlg = SubjectEditDialog(self, title="Add Subject")
        if dlg.exec_() == QDialog.Accepted:
            name, color = dlg.get_data()
            if name:
                ok, err = self.db.add_subject(name, color)
                if ok:
                    self._refresh_subjects_list()
                    self.subjects_changed.emit()
                else:
                    QMessageBox.warning(self, "Could not add subject", err)

    def _edit_subject_dialog(self, name):
        colors = self.db.get_subject_colors()
        current_color = colors.get(name, "#38BDF8")
        dlg = SubjectEditDialog(self, title="Edit Subject", current_name=name, current_color=current_color)
        if dlg.exec_() == QDialog.Accepted:
            new_name, new_color = dlg.get_data()
            if new_name:
                ok, err = self.db.update_subject(name, new_name, new_color)
                if ok:
                    self._refresh_subjects_list()
                    self.subjects_changed.emit()
                else:
                    QMessageBox.warning(self, "Could not update subject", err)

    def _delete_subject(self, name):
        reply = QMessageBox.question(
            self,
            "Delete Subject",
            f"Are you sure you want to delete '{name}'?\nPast sessions with this subject will remain in your history.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            ok, err = self.db.delete_subject(name)
            if ok:
                self._refresh_subjects_list()
                self.subjects_changed.emit()
            else:
                QMessageBox.warning(self, "Could not delete subject", err)

    def _on_top_toggled(self, state):
        self.db.set_setting("always_on_top", 1 if state else 0)
        self.always_on_top_changed.emit(state)

    def _export_csv(self):
        default_filename = f"studyflow_sessions_{datetime.now().strftime('%Y%m%d')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export StudyFlow Sessions", default_filename, "CSV Files (*.csv)")
        if path:
            count = self.db.export_sessions_csv(path)
            QMessageBox.information(self, "Export Successful", f"Successfully exported {count} study sessions to:\n{path}")

    def _reset_defaults(self):
        reply = QMessageBox.warning(
            self,
            "Reset Settings",
            "Reset all subjects, colors, and timer durations to defaults?\n(Your saved study sessions will NOT be deleted).",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.db.reset_to_defaults()
            self._refresh_subjects_list()
            self.subjects_changed.emit()

            self.pause_stepper.value = 3
            self.pause_stepper.val_lbl.setText("3 min")
            self.cd_stepper.value = 3
            self.cd_stepper.val_lbl.setText("3 min")
            self.min_stepper.value = 10
            self.min_stepper.val_lbl.setText("10 sec")
            self.pomo_task_s.value = 25
            self.pomo_task_s.val_lbl.setText("25 min")
            self.pomo_break_s.value = 5
            self.pomo_break_s.val_lbl.setText("5 min")
            self.pomo_lbreak_s.value = 15
            self.pomo_lbreak_s.val_lbl.setText("15 min")
            self.pomo_rounds_s.value = 4
            self.pomo_rounds_s.val_lbl.setText("4 rounds")
            QMessageBox.information(self, "Reset Complete", "Settings and subjects have been reset to defaults.")


# ─── Main Window ──────────────────────────────────────────────────────────────

class StudyFlowWindow(QMainWindow):
    """Main window with clean minimalist design and 4 tabs."""

    def __init__(self, db):
        super().__init__()
        self.db = db
        self._setup_window()
        self._setup_tray()
        self._setup_tabs()

    def _setup_window(self):
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(create_tray_icon(active=False))
        self.setFixedSize(400, 540)

        always_on_top = bool(int(self.db.get_setting("always_on_top", 1)))
        flags = Qt.FramelessWindowHint | Qt.Tool
        if always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(STYLESHEET)

        screen = QDesktopWidget().screenGeometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(6)

        title_bar = QFrame()
        title_bar.setObjectName("TitleBar")
        title_bar.setFixedHeight(30)
        title_bar.setStyleSheet(f"""
            QFrame#TitleBar {{
                background-color: transparent;
                border-bottom: 1px solid {COLORS['border']};
            }}
        """)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(6, 0, 4, 0)

        title_text = QLabel(APP_NAME)
        title_text.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: 700; font-size: 13px;")
        title_layout.addWidget(title_text)

        title_layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {COLORS['text_dim']};
                font-size: 12px;
            }}
            QPushButton:hover {{
                color: {COLORS['text_primary']};
            }}
        """)
        close_btn.clicked.connect(self._hide_to_tray)
        title_layout.addWidget(close_btn)

        self.main_layout.addWidget(title_bar)

        self._drag_pos = None
        title_bar.mousePressEvent = self._title_mouse_press
        title_bar.mouseMoveEvent = self._title_mouse_move

    def _title_mouse_press(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.pos()

    def _title_mouse_move(self, event):
        if self._drag_pos and event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(create_tray_icon(active=False))
        self.tray_icon.setToolTip(f"{APP_NAME} — Ready")

        tray_menu = QMenu()
        tray_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 4px;
            }}
            QMenu::item {{
                color: {COLORS['text_primary']};
                padding: 6px 16px;
            }}
            QMenu::item:selected {{
                background-color: {COLORS['bg_hover']};
            }}
        """)

        show_action = QAction("Show StudyFlow", self)
        show_action.triggered.connect(self._toggle_visibility)
        tray_menu.addAction(show_action)

        tray_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()

    def _setup_tabs(self):
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        # Tab 1: Regular Timer
        self.timer_tab = TimerTab(self.db)
        self.timer_tab.session_saved.connect(self._on_session_saved)
        self.timer_tab.notification_requested.connect(self._show_notification)
        self.tabs.addTab(self.timer_tab, "Timer")

        # Tab 2: Pomodoro Timer
        self.pomodoro_tab = PomodoroTab(self.db)
        self.pomodoro_tab.session_saved.connect(self._on_session_saved)
        self.pomodoro_tab.notification_requested.connect(self._show_notification)
        self.pomodoro_tab.settings_requested.connect(lambda: self.tabs.setCurrentIndex(3))
        self.tabs.addTab(self.pomodoro_tab, "Pomodoro")

        # Tab 3: Statistics
        self.stats_tab = StatsTab(self.db)
        self.tabs.addTab(self.stats_tab, "Stats")

        # Tab 4: Settings
        self.settings_tab = SettingsTab(self.db)
        self.settings_tab.subjects_changed.connect(self._on_subjects_changed)
        self.settings_tab.always_on_top_changed.connect(self._on_always_on_top_changed)
        self.settings_tab.settings_changed.connect(self._on_settings_changed)
        self.tabs.addTab(self.settings_tab, "Settings")

        # Cross-timer coordination
        self.timer_tab.started.connect(self._on_timer_started)
        self.pomodoro_tab.started.connect(self._on_pomodoro_started)

        self.main_layout.addWidget(self.tabs)

        self._tray_update_timer = QTimer(self)
        self._tray_update_timer.setInterval(1000)
        self._tray_update_timer.timeout.connect(self._update_tray_state)
        self._tray_update_timer.start()

    def _on_subjects_changed(self):
        self.timer_tab.reload_subjects()
        self.pomodoro_tab.reload_subjects()
        self.stats_tab._refresh_stats()

    def _on_settings_changed(self, key, val):
        self.timer_tab.reload_settings()
        self.pomodoro_tab.reload_settings()

    def _on_always_on_top_changed(self, enabled):
        was_visible = self.isVisible()
        flags = Qt.FramelessWindowHint | Qt.Tool
        if enabled:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if was_visible:
            self.show()

    def _on_timer_started(self):
        if self.pomodoro_tab.get_is_running():
            self.pomodoro_tab._stop_timer(save_if_focus=True)

    def _on_pomodoro_started(self):
        if self.timer_tab.get_is_running():
            self.timer_tab._stop_timer()

    def _toggle_visibility(self):
        if self.isVisible():
            self._hide_to_tray()
        else:
            self._show_window()

    def _show_window(self):
        screen = QDesktopWidget().screenGeometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        self.show()
        self.activateWindow()
        self.raise_()

    def _hide_to_tray(self):
        self.hide()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_visibility()

    def _show_notification(self, title, message):
        if bool(int(self.db.get_setting("notifications_enabled", 1))):
            self.tray_icon.showMessage(
                f"{APP_NAME} — {title}",
                message,
                QSystemTrayIcon.Information,
                4000
            )
        if bool(int(self.db.get_setting("sound_enabled", 1))):
            QApplication.beep()

    def _on_session_saved(self):
        self.stats_tab._refresh_stats()
        if bool(int(self.db.get_setting("notifications_enabled", 1))):
            self.tray_icon.showMessage(
                APP_NAME,
                "Session saved!",
                QSystemTrayIcon.Information,
                2000
            )
        if bool(int(self.db.get_setting("sound_enabled", 1))):
            QApplication.beep()

    def _update_tray_state(self):
        timer_running = self.timer_tab.get_is_running()
        pomo_running = self.pomodoro_tab.get_is_running()
        is_running = timer_running or pomo_running
        self.tray_icon.setIcon(create_tray_icon(active=is_running))

        if timer_running:
            if getattr(self.timer_tab, 'is_paused', False):
                rem = self.timer_tab.get_pause_time_remaining_str()
                subject = self.timer_tab.selected_subject
                self.tray_icon.setToolTip(
                    f"{APP_NAME} — {subject} (Paused {rem})"
                )
            else:
                elapsed = self.timer_tab.elapsed_seconds
                subject = self.timer_tab.selected_subject
                self.tray_icon.setToolTip(
                    f"{APP_NAME} — {subject} ({format_duration(elapsed)})"
                )
        elif pomo_running:
            rem = self.pomodoro_tab.get_time_remaining_str()
            phase = self.pomodoro_tab.get_phase_display()
            subj = self.pomodoro_tab.selected_subject
            self.tray_icon.setToolTip(
                f"{APP_NAME} — [{phase}] {subj} ({rem})"
            )
        else:
            self.tray_icon.setToolTip(f"{APP_NAME} — Ready")

    def _quit_app(self):
        if self.timer_tab.is_running:
            self.timer_tab._stop_timer()
        if self.pomodoro_tab.is_running:
            self.pomodoro_tab._stop_timer(save_if_focus=True)
        self.db.close()
        QApplication.quit()

    def closeEvent(self, event):
        event.ignore()
        self._hide_to_tray()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._hide_to_tray()
        super().keyPressEvent(event)


# ─── Native QLocalServer IPC for Toggle & Single Instance ──────────────────────

class LocalServerManager(QObject):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.server = QLocalServer(self)
        QLocalServer.removeServer(SOCKET_NAME)
        if self.server.listen(SOCKET_NAME):
            self.server.newConnection.connect(self._on_connection)

    def _on_connection(self):
        socket = self.server.nextPendingConnection()
        if socket:
            socket.readyRead.connect(lambda: self._handle_read(socket))

    def _handle_read(self, socket):
        msg = socket.readAll().data().decode("utf-8", errors="ignore")
        if "toggle" in msg:
            self.window._toggle_visibility()
        socket.disconnectFromServer()


def notify_running_instance(timeout_ms=500):
    socket = QLocalSocket()
    socket.connectToServer(SOCKET_NAME)
    if socket.waitForConnected(timeout_ms):
        socket.write(b"toggle\n")
        socket.waitForBytesWritten(timeout_ms)
        socket.disconnectFromServer()
        return True
    return False


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(f"{APP_NAME} v{VERSION} — Minimalist Study Timer & Session Tracker")
        print("\nUsage:")
        print("  python study_timer.py [options]")
        print("  python main.py [options]\n")
        print("Options:")
        print("  -h, --help       Show this help message and exit")
        print("  -v, --version    Show version number and exit")
        print("  -t, --toggle     Toggle window visibility if running, or launch")
        print("  -m, --minimized  Start minimized to system tray (e.g. for autostart)")
        print("      --tray       Alias for --minimized")
        sys.exit(0)

    if "-v" in args or "--version" in args:
        print(f"{APP_NAME} v{VERSION}")
        sys.exit(0)

    # Windows taskbar grouping fix
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("studyflow.timer.app.1")
        except Exception:
            pass

    # Check if another instance is already running
    if notify_running_instance(500):
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    db = Database()
    window = StudyFlowWindow(db)
    ipc = LocalServerManager(window, app)

    if "-m" not in args and "--minimized" not in args and "--tray" not in args:
        window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
