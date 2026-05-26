from __future__ import annotations

import calendar
import json
import sys
import winreg
from datetime import date, datetime
from pathlib import Path

try:
    from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
    from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPen
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMenu,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizeGrip,
        QSlider,
        QSpinBox,
        QSystemTrayIcon,
        QTextBrowser,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:
    raise SystemExit(
        "PySide6가 설치되어 있지 않습니다.\n"
        "터미널에서 아래 명령을 먼저 실행해 주세요:\n\n"
        "python -m pip install PySide6"
    ) from exc


APP_NAME = "Fox Calendar"
APP_DIR = Path.home() / ".desktop_note_calendar"
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_NOTES_DIR = Path.home() / "Documents" / "DesktopNotes"
APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "fox_calendar_icon.png"
STARTUP_PATH = (
    Path.home()
    / "AppData"
    / "Roaming"
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "Startup"
    / "FoxCalendar.bat"
)

FIXED_KOREAN_HOLIDAYS = {
    (1, 1): "신정",
    (3, 1): "삼일절",
    (5, 5): "어린이날",
    (6, 6): "현충일",
    (8, 15): "광복절",
    (10, 3): "개천절",
    (10, 9): "한글날",
    (12, 25): "성탄절",
}

THEMES = {
    "dark": {
        "bg": "#151515",
        "panel": "#222222",
        "panel2": "#2c2c2c",
        "border": "#3a3a3a",
        "text": "#f2f2f2",
        "muted": "#a8a8a8",
        "accent": "#4aa3ff",
        "grid": "#56c4d0",
        "weekday": "#235d68",
        "cell": "#172b31",
        "other": "#263136",
        "other_text": "#7d969d",
        "today_bg": "#6b6530",
        "today_text": "#fff08a",
        "selected_bg": "#386a4d",
        "selected_text": "#b8ffca",
        "holiday": "#ffb7bd",
        "memo_bg": "#fff7b8",
        "memo_bar": "#f5dc65",
        "memo_text": "#24210e",
    },
    "light": {
        "bg": "#edf4f6",
        "panel": "#ffffff",
        "panel2": "#dce8eb",
        "border": "#b9ced5",
        "text": "#122a31",
        "muted": "#5c737a",
        "accent": "#2f8fe8",
        "grid": "#40adbb",
        "weekday": "#9adce2",
        "cell": "#eafafb",
        "other": "#cfe3e6",
        "other_text": "#6f8b90",
        "today_bg": "#fff2a8",
        "today_text": "#3c3410",
        "selected_bg": "#b9f4c9",
        "selected_text": "#12381f",
        "holiday": "#b12633",
        "memo_bg": "#fff7b8",
        "memo_bar": "#f5dc65",
        "memo_text": "#24210e",
    },
}

THEME_FALLBACK = dict(THEMES["dark"])

NOTE_THEMES = {
    "light": {
        "memo_bg": "#ffffff",
        "memo_bar": "#dce8eb",
        "memo_text": "#122a31",
        "memo_hover": "#c9dce1",
    },
    "default": {
        "memo_bg": "#fff7b8",
        "memo_bar": "#f5dc65",
        "memo_text": "#24210e",
        "memo_hover": "#ead157",
    },
    "dark": {
        "memo_bg": "#1d1f21",
        "memo_bar": "#2c2c2c",
        "memo_text": "#f2f2f2",
        "memo_hover": "#3a3a3a",
    },
}


def windows_prefers_dark() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
    except OSError:
        return True


def load_config() -> dict:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}

    defaults = {
        "notes_dir": str(DEFAULT_NOTES_DIR),
        "calendar_geometry": "760x520+180+40",
        "settings_geometry": "620x520",
        "open_memos": {},
        "schedules": {},
        "theme_mode": "system",
        "note_theme": "default",
        "holiday_enabled": True,
        "calendar_opacity": 56,
    }
    for key, value in defaults.items():
        data.setdefault(key, value)
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def save_config(config: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_theme(config: dict) -> dict[str, str]:
    mode = config.get("theme_mode", "system")
    if mode == "system":
        mode = "dark" if windows_prefers_dark() else "light"
    colors = dict(THEME_FALLBACK)
    colors.update(THEMES.get(mode, {}))
    return colors


def resolve_note_theme(config: dict) -> dict[str, str]:
    colors = resolve_theme(config)
    colors.update(NOTE_THEMES.get(config.get("note_theme", "default"), NOTE_THEMES["default"]))
    colors["bg"] = colors["memo_bg"]
    return colors


def parse_geometry(geometry: str, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    try:
        size, x_text, y_text = geometry.split("+")
        width_text, height_text = size.split("x")
        return int(width_text), int(height_text), int(x_text), int(y_text)
    except ValueError:
        return fallback


def geometry_string(widget: QWidget) -> str:
    return f"{widget.width()}x{widget.height()}+{widget.x()}+{widget.y()}"


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        child_layout = item.layout()
        child_widget = item.widget()
        if child_layout is not None:
            clear_layout(child_layout)
        if child_widget is not None:
            child_widget.deleteLater()


class MemoStore:
    def __init__(self, notes_dir: Path) -> None:
        self.memo_dir = notes_dir / "Memos"
        self.memo_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, memo_id: str) -> Path:
        return self.memo_dir / f"{memo_id}.md"

    def load(self, memo_id: str) -> str:
        path = self.path_for(memo_id)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def save(self, memo_id: str, text: str) -> None:
        self.path_for(memo_id).write_text(text.rstrip() + "\n", encoding="utf-8")


class RoundedWindow(QWidget):
    def __init__(self, colors: dict[str, str], radius: int = 14) -> None:
        super().__init__()
        self.colors = colors
        self.radius = radius
        self.drag_start: QPoint | None = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)
        painter.fillPath(path, QColor(self.colors["bg"]))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self.drag_start is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_start)

    def mouseReleaseEvent(self, _event) -> None:
        self.drag_start = None


class IconButton(QPushButton):
    def __init__(self, kind: str, colors: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.colors = colors
        self.setFixedSize(26, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.refresh_style()

    def refresh_style(self) -> None:
        self.setStyleSheet(
            "QPushButton { border: none; background: transparent; }"
            f"QPushButton:hover {{ background: {self.colors['panel2']}; border-radius: 5px; }}"
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self.colors["text"])
        pen = QPen(color, 1.35)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        if self.kind == "move":
            for x in (9, 13, 17):
                for y in (7, 11, 15):
                    painter.drawEllipse(QPoint(x, y), 1, 1)
        elif self.kind == "prev":
            painter.drawLine(16, 7, 10, 12)
            painter.drawLine(10, 12, 16, 17)
        elif self.kind == "next":
            painter.drawLine(10, 7, 16, 12)
            painter.drawLine(16, 12, 10, 17)
        elif self.kind == "close":
            painter.drawLine(10, 8, 17, 16)
            painter.drawLine(17, 8, 10, 16)
        elif self.kind == "settings":
            for y, knob_x in ((7, 11), (12, 17), (17, 13)):
                painter.drawLine(7, y, 21, y)
                painter.setBrush(QColor(self.colors["bg"]))
                painter.drawEllipse(QPoint(knob_x, y), 2, 2)
                painter.setBrush(Qt.NoBrush)
        elif self.kind == "note":
            path = QPainterPath()
            path.moveTo(9, 5)
            path.lineTo(18, 5)
            path.lineTo(18, 14)
            path.lineTo(14, 19)
            path.lineTo(9, 19)
            path.closeSubpath()
            painter.drawPath(path)
            painter.drawLine(14, 19, 14, 14)
            painter.drawLine(14, 14, 18, 14)
        elif self.kind == "preview":
            eye = QRectF(6.5, 8.0, 15.0, 8.0)
            painter.drawEllipse(eye)
            painter.setBrush(color)
            painter.drawEllipse(QPoint(14, 12), 2, 2)
        elif self.kind == "edit":
            painter.drawLine(8, 17, 17, 8)
            painter.drawLine(15, 6, 19, 10)
            painter.drawLine(8, 17, 7, 20)
            painter.drawLine(7, 20, 10, 19)


class DayCell(QWidget):
    clicked = Signal(date)

    def __init__(self, colors: dict[str, str]) -> None:
        super().__init__()
        self.colors = colors
        self.day = date.today()
        self.lines: list[str] = []
        self.holiday = ""
        self.state = "normal"
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(54)

    def set_data(self, day: date, lines: list[str], state: str, holiday: str = "") -> None:
        self.day = day
        self.lines = lines[:2]
        self.holiday = holiday
        self.state = state
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.day)

    def paintEvent(self, _event) -> None:
        colors = self.colors
        bg = colors["cell"]
        fg = colors["text"]
        if self.state == "other":
            bg, fg = colors["other"], colors["other_text"]
        elif self.state == "today":
            bg, fg = colors["today_bg"], colors["today_text"]
        elif self.state == "selected":
            bg, fg = colors["selected_bg"], colors["selected_text"]
        elif self.state == "holiday":
            bg, fg = colors["cell"], colors["holiday"]

        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(bg))
        painter.setPen(QColor(colors["grid"]))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        painter.setPen(QColor(fg))
        painter.setFont(QFont("Malgun Gothic", 9))
        painter.drawText(8, 18, str(self.day.day))

        if self.holiday:
            holiday_color = colors["other_text"] if self.state == "other" else colors["holiday"]
            painter.setPen(QColor(holiday_color))
            metrics = painter.fontMetrics()
            holiday_rect = QRect(30, 4, max(10, self.width() - 38), 18)
            painter.drawText(
                holiday_rect,
                Qt.AlignRight | Qt.AlignVCenter,
                metrics.elidedText(self.holiday, Qt.ElideRight, holiday_rect.width()),
            )

        metrics = painter.fontMetrics()
        y = 36
        available = max(10, self.width() - 14)
        for line in self.lines:
            painter.drawText(8, y, metrics.elidedText(line, Qt.ElideRight, available))
            y += 16


class ScheduleWindow(RoundedWindow):
    def __init__(self, app: "FoxCalendarApp", schedule_day: date, geometry: str | None = None) -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.schedule_day = schedule_day
        self.setWindowTitle(f"{APP_NAME} {self.schedule_day:%Y.%m.%d}")
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(geometry or "430x360+260+160", (430, 360, 260, 160))
        self.setGeometry(x, y, width, height)
        self.build_ui()

    def build_ui(self) -> None:
        colors = self.colors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(f"{self.schedule_day:%Y.%m.%d}")
        title.setFont(QFont("Malgun Gothic", 15, QFont.Bold))
        close = QPushButton("x")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        close.setStyleSheet(self.button_style())
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close)

        self.text = QTextEdit()
        self.text.setPlainText(self.app.get_schedule(self.schedule_day))
        self.text.textChanged.connect(self.save_now)
        self.text.setStyleSheet(
            f"QTextEdit {{ background: {colors['panel']}; color: {colors['text']}; "
            f"border: 1px solid {colors['border']}; border-radius: 10px; padding: 10px; }}"
        )

        footer = QHBoxLayout()
        self.status = QLabel("")
        save_button = QPushButton("저장")
        save_button.clicked.connect(self.save_now)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.close)
        for button in (save_button, close_button):
            button.setStyleSheet(self.button_style())
        footer.addWidget(self.status)
        footer.addStretch()
        footer.addWidget(save_button)
        footer.addWidget(close_button)

        layout.addLayout(header)
        layout.addWidget(self.text, 1)
        layout.addLayout(footer)
        self.setStyleSheet(f"QLabel {{ color: {colors['text']}; }}")
        self.text.setFocus()

    def button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 6px; padding: 6px 14px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def save_now(self) -> None:
        self.app.set_schedule(self.schedule_day, self.text.toPlainText())
        self.status.setText("저장됨")

    def closeEvent(self, event) -> None:
        self.save_now()
        self.app.schedule_windows.pop(self.schedule_day.isoformat(), None)
        super().closeEvent(event)


class StickyMemoWindow(RoundedWindow):
    def __init__(self, app: "FoxCalendarApp", memo_id: str, geometry: str | None = None) -> None:
        self.app = app
        self.memo_id = memo_id
        self.preview_mode = False
        colors = resolve_note_theme(app.config)
        super().__init__(colors)
        self.setWindowTitle(f"{APP_NAME} Memo")
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(geometry or self.default_geometry(), (280, 260, 420, 120))
        self.setGeometry(x, y, width, height)
        self.build_ui()

    def default_geometry(self) -> str:
        offset = 28 * len(self.app.memo_windows)
        return f"280x260+{420 + offset}+{120 + offset}"

    def build_ui(self) -> None:
        c = resolve_note_theme(self.app.config)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QFrame()
        self.header.setStyleSheet(f"QFrame {{ background: {c['memo_bar']}; border-top-left-radius: 14px; border-top-right-radius: 14px; }}")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(8, 5, 8, 5)
        self.move_button = IconButton("move", {"text": c["memo_text"], "bg": c["memo_bar"], "panel2": c["memo_hover"]})
        self.preview_button = IconButton("preview", {"text": c["memo_text"], "bg": c["memo_bar"], "panel2": c["memo_hover"]})
        self.preview_button.setToolTip("미리보기")
        self.preview_button.clicked.connect(self.toggle_markdown_preview)
        self.close_button = QPushButton("x")
        self.close_button.setFixedSize(24, 24)
        self.close_button.clicked.connect(self.close)
        self.close_button.setStyleSheet(self.memo_close_style(c))
        header_layout.addWidget(self.move_button)
        header_layout.addStretch()
        header_layout.addWidget(self.preview_button)
        header_layout.addWidget(self.close_button)

        self.text = QTextEdit()
        self.text.setPlainText(self.app.memo_store.load(self.memo_id))
        self.text.textChanged.connect(self.save_now)
        self.text.textChanged.connect(self.refresh_markdown_preview)
        self.text.setStyleSheet(self.note_editor_style(c))
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setStyleSheet(self.note_preview_style(c))
        self.preview.hide()
        grip = QSizeGrip(self)
        grip.setFixedSize(16, 16)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(grip)

        layout.addWidget(self.header)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.preview, 1)
        layout.addLayout(bottom)

    def note_editor_style(self, colors: dict[str, str]) -> str:
        return f"QTextEdit {{ background: {colors['memo_bg']}; color: {colors['memo_text']}; border: none; padding: 10px; }}"

    def note_preview_style(self, colors: dict[str, str]) -> str:
        return (
            f"QTextBrowser {{ background: {colors['memo_bg']}; color: {colors['memo_text']}; border: none; padding: 10px; }}"
            f"QTextBrowser a {{ color: {colors['accent']}; }}"
        )

    def refresh_markdown_preview(self) -> None:
        if self.preview_mode:
            self.preview.setMarkdown(self.text.toPlainText())

    def toggle_markdown_preview(self) -> None:
        self.preview_mode = not self.preview_mode
        if self.preview_mode:
            self.preview.setMarkdown(self.text.toPlainText())
            self.text.hide()
            self.preview.show()
            self.preview_button.kind = "edit"
            self.preview_button.setToolTip("편집")
        else:
            self.preview.hide()
            self.text.show()
            self.text.setFocus()
            self.preview_button.kind = "preview"
            self.preview_button.setToolTip("미리보기")
        self.preview_button.update()

    def memo_close_style(self, colors: dict[str, str]) -> str:
        return (
            f"QPushButton {{ color: {colors['memo_text']}; background: transparent; border: none; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {colors['memo_hover']}; border-radius: 5px; }}"
        )

    def apply_note_theme(self) -> None:
        c = resolve_note_theme(self.app.config)
        self.colors.update(c)
        self.header.setStyleSheet(f"QFrame {{ background: {c['memo_bar']}; border-top-left-radius: 14px; border-top-right-radius: 14px; }}")
        self.move_button.colors.update({"text": c["memo_text"], "bg": c["memo_bar"], "panel2": c["memo_hover"]})
        self.move_button.refresh_style()
        self.move_button.update()
        self.preview_button.colors.update({"text": c["memo_text"], "bg": c["memo_bar"], "panel2": c["memo_hover"]})
        self.preview_button.refresh_style()
        self.preview_button.update()
        self.close_button.setStyleSheet(self.memo_close_style(c))
        self.text.setStyleSheet(self.note_editor_style(c))
        self.preview.setStyleSheet(self.note_preview_style(c))
        self.refresh_markdown_preview()
        self.update()

    def save_now(self) -> None:
        self.app.memo_store.save(self.memo_id, self.text.toPlainText())
        self.app.remember_open_memo(self.memo_id, geometry_string(self))

    def closeEvent(self, event) -> None:
        self.save_now()
        self.app.forget_open_memo(self.memo_id)
        super().closeEvent(event)


class Switch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked: bool, colors: dict[str, str]) -> None:
        super().__init__()
        self.checked = checked
        self.colors = colors
        self.setFixedSize(42, 24)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.checked = not self.checked
            self.toggled.emit(self.checked)
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = QColor(self.colors["accent"] if self.checked else self.colors["panel2"])
        painter.setBrush(track)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 12, 12)
        painter.setBrush(QColor("white" if self.checked else self.colors["muted"]))
        x = 22 if self.checked else 4
        painter.drawEllipse(QRect(x, 5, 14, 14))


class ThemeButton(QPushButton):
    def __init__(self, mode: str, label: str, colors: dict[str, str]) -> None:
        super().__init__()
        self.mode = mode
        self.label = label
        self.colors = colors
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self.setFixedWidth({"light": 108, "dark": 96, "system": 84}[mode])
        self.setStyleSheet("QPushButton { border: none; background: transparent; }")

    def paintEvent(self, _event) -> None:
        c = self.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 2, -1, -2)

        if self.isChecked() or self.underMouse():
            painter.setPen(QPen(QColor(c["border"]), 1 if self.isChecked() else 0))
            painter.setBrush(QColor(c["panel2"]))
            painter.drawRoundedRect(rect, 10, 10)

        icon_color = QColor(c["text"] if self.isChecked() else c["muted"])
        text_color = QColor(c["text"] if self.isChecked() else c["muted"])
        self.draw_icon(painter, icon_color)

        painter.setPen(text_color)
        painter.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
        painter.drawText(QRect(31, 0, self.width() - 34, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.label)

    def draw_icon(self, painter: QPainter, color: QColor) -> None:
        pen = QPen(color, 1.15)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        if self.mode == "light":
            center = QPoint(16, 15)
            painter.drawEllipse(center, 3, 3)
            for x1, y1, x2, y2 in (
                (16, 6, 16, 8),
                (16, 22, 16, 24),
                (7, 15, 9, 15),
                (23, 15, 25, 15),
                (10, 9, 12, 11),
                (20, 19, 22, 21),
                (10, 21, 12, 19),
                (20, 11, 22, 9),
            ):
                painter.drawLine(x1, y1, x2, y2)
        elif self.mode == "dark":
            moon = QPainterPath()
            moon.addEllipse(QRectF(10.5, 8.0, 11.0, 14.0))
            cut = QPainterPath()
            cut.addEllipse(QRectF(15.0, 6.5, 10.5, 15.0))
            painter.fillPath(moon.subtracted(cut), color)
        elif self.mode == "system":
            painter.drawRoundedRect(QRect(9, 10, 15, 10), 2, 2)
            painter.drawLine(12, 20, 21, 20)
            painter.drawLine(16, 20, 16, 23)
            painter.drawLine(13, 23, 19, 23)


class SettingsWindow(RoundedWindow):
    def __init__(self, app: "FoxCalendarApp") -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.setWindowTitle(f"{APP_NAME} 설정")
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(app.config.get("settings_geometry", "620x520"), (620, 520, 260, 130))
        self.setGeometry(x, y, width, height)
        self.build_ui()

    def build_ui(self) -> None:
        c = self.colors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("설정")
        title.setFont(QFont("Malgun Gothic", 15, QFont.Bold))
        close = QPushButton("x")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        close.setStyleSheet(self.button_style())
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {c['bg']}; border: none; }}"
            f"QScrollArea > QWidget > QWidget {{ background: {c['bg']}; }}"
        )
        scroll.viewport().setStyleSheet(f"background: {c['bg']};")
        content = QWidget()
        content.setStyleSheet(f"background: {c['bg']};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        content_layout.addWidget(self.section("화면"))
        content_layout.addWidget(self.setting_card("테마", "Fox Calendar의 색상 모드를 선택합니다", self.theme_selector()))
        content_layout.addWidget(self.setting_card("노트 테마", "메모 창의 색상 모드를 선택합니다", self.note_theme_combo()))
        content_layout.addWidget(self.setting_card("투명도", "달력이 바탕화면에 보이는 정도를 조절합니다", self.opacity_control()))
        content_layout.addWidget(self.section("실행"))
        startup_switch = Switch(STARTUP_PATH.exists(), c)
        startup_switch.toggled.connect(lambda enabled: self.app.set_startup(enabled, show_message=False))
        content_layout.addWidget(self.setting_card("Windows 시작 시 자동 실행", "컴퓨터를 켤 때 Fox Calendar를 자동으로 엽니다", startup_switch))
        content_layout.addWidget(self.section("달력"))
        holiday_switch = Switch(self.app.config.get("holiday_enabled", True), c)
        holiday_switch.toggled.connect(self.toggle_holidays)
        content_layout.addWidget(self.setting_card("공휴일 표시", "주요 고정 공휴일은 자동으로 달력에 표시됩니다", holiday_switch))
        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")

    def section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont("Malgun Gothic", 11, QFont.Bold))
        return label

    def setting_card(self, title: str, desc: str, control: QWidget) -> QFrame:
        c = self.colors
        card = QFrame()
        card.setObjectName("settingCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#settingCard {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 9px; }}"
            "QFrame#settingCard QLabel { border: none; background: transparent; }"
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        texts = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
        desc_label = QLabel(desc)
        desc_label.setStyleSheet(f"color: {c['muted']};")
        texts.addWidget(title_label)
        texts.addWidget(desc_label)
        layout.addLayout(texts, 1)
        layout.addWidget(control)
        return card

    def theme_selector(self) -> QWidget:
        c = self.colors
        current = self.app.config.get("theme_mode", "system")
        widget = QWidget()
        widget.setObjectName("themeSelector")
        widget.setAttribute(Qt.WA_StyledBackground, True)
        widget.setStyleSheet("QWidget#themeSelector { background: transparent; border: none; }")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        options = [
            ("light", "라이트 모드"),
            ("dark", "다크 모드"),
            ("system", "시스템"),
        ]
        for mode, label in options:
            button = ThemeButton(mode, label, c)
            button.setChecked(mode == current)
            button.clicked.connect(lambda _checked=False, selected=mode: self.set_theme(selected))
            layout.addWidget(button)
        widget.setFixedWidth(292)
        return widget

    def note_theme_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.addItem("라이트", "light")
        combo.addItem("기본", "default")
        combo.addItem("다크", "dark")
        index = combo.findData(self.app.config.get("note_theme", "default"))
        combo.setCurrentIndex(max(0, index))
        combo.currentIndexChanged.connect(lambda _i: self.set_note_theme(combo.currentData()))
        combo.setStyleSheet(self.input_style())
        combo.setFixedWidth(140)
        return combo

    def opacity_control(self) -> QWidget:
        c = self.colors
        widget = QWidget()
        widget.setObjectName("opacityControl")
        widget.setAttribute(Qt.WA_StyledBackground, True)
        widget.setStyleSheet(f"QWidget#opacityControl {{ background: {c['panel']}; border: none; }}")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(20, 100)
        slider.setValue(self.app.config.get("calendar_opacity", 56))
        spin = QSpinBox()
        spin.setRange(20, 100)
        spin.setButtonSymbols(QSpinBox.NoButtons)
        spin.setValue(slider.value())
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(self.app.set_calendar_opacity)
        slider.setStyleSheet(
            "QSlider { background: transparent; border: none; }"
            f"QSlider::groove:horizontal {{ height: 3px; background: {c['panel2']}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}"
            "QSlider::handle:horizontal { background: white; border: 1px solid #6f858c; width: 18px; height: 18px; margin: -8px 0; border-radius: 9px; }"
        )
        spin.setStyleSheet(self.input_style())
        layout.addWidget(slider)
        layout.addWidget(spin)
        widget.setFixedWidth(220)
        return widget

    def input_style(self) -> str:
        c = self.colors
        return (
            f"QComboBox, QSpinBox {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 7px; padding: 6px 10px; }}"
            f"QComboBox:hover, QSpinBox:hover {{ background: {c['border']}; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid {c['muted']}; margin-right: 8px; }}"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ color: {c['muted']}; background: transparent; border: none; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['panel']}; color: {c['text']}; border-radius: 5px; }}"
        )

    def set_theme(self, mode: str) -> None:
        if self.app.config.get("theme_mode", "system") == mode:
            return
        self.app.config["theme_mode"] = mode
        self.app.config["settings_geometry"] = geometry_string(self)
        self.app.save()
        app = self.app
        app.apply_theme()
        self.close()
        app.open_settings()

    def set_note_theme(self, mode: str) -> None:
        if self.app.config.get("note_theme", "default") == mode:
            return
        self.app.config["note_theme"] = mode
        self.app.save()
        self.app.apply_note_theme()

    def toggle_holidays(self, enabled: bool) -> None:
        self.app.config["holiday_enabled"] = enabled
        self.app.save()
        self.app.render_calendar()

    def closeEvent(self, event) -> None:
        self.app.config["settings_geometry"] = geometry_string(self)
        self.app.save()
        self.app.settings_window = None
        super().closeEvent(event)


class FoxCalendarApp(RoundedWindow):
    def __init__(self) -> None:
        self.config = load_config()
        self.colors = resolve_theme(self.config)
        super().__init__(self.colors)
        self.icon = QIcon(str(APP_ICON_PATH)) if APP_ICON_PATH.exists() else QIcon()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self.icon)
        self.memo_store = MemoStore(Path(self.config["notes_dir"]))
        self.visible_month = date.today().replace(day=1)
        self.selected_day = date.today()
        self.day_cells: list[DayCell] = []
        self.memo_windows: dict[str, StickyMemoWindow] = {}
        self.schedule_windows: dict[str, ScheduleWindow] = {}
        self.settings_window: SettingsWindow | None = None
        self.force_quit = False
        width, height, x, y = parse_geometry(self.config.get("calendar_geometry", "760x520+180+40"), (760, 520, 180, 40))
        self.setGeometry(x, y, width, height)
        self.setMinimumSize(520, 360)
        self.setWindowOpacity(self.config.get("calendar_opacity", 56) / 100)
        self.build_ui()
        self.setup_tray()
        self.render_calendar()
        self.restore_open_memos()

    def save(self) -> None:
        self.config["calendar_geometry"] = geometry_string(self)
        save_config(self.config)

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def build_ui(self) -> None:
        c = self.colors
        existing = self.layout()
        if existing is None:
            layout = QVBoxLayout(self)
        else:
            clear_layout(existing)
            layout = existing
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)

        header = QGridLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setColumnStretch(0, 1)
        header.setColumnStretch(1, 1)
        header.setColumnStretch(2, 1)
        prev_button = IconButton("prev", c)
        next_button = IconButton("next", c)
        close_button = IconButton("close", c)
        self.header_buttons = []
        prev_button.clicked.connect(self.previous_month)
        next_button.clicked.connect(self.next_month)
        close_button.clicked.connect(self.close)

        note = IconButton("note", c)
        settings = IconButton("settings", c)
        self.icon_buttons = [prev_button, next_button, close_button, note, settings]
        note.clicked.connect(self.create_memo)
        settings.clicked.connect(self.open_settings)
        self.month_label = QLabel("")
        self.month_label.setAlignment(Qt.AlignCenter)
        self.month_label.setFont(QFont("Malgun Gothic", 12, QFont.Bold))

        left = QHBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(prev_button)
        left.addStretch()
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.addStretch()
        right.addWidget(note)
        right.addWidget(settings)
        right.addWidget(close_button)
        right.addWidget(next_button)
        header.addLayout(left, 0, 0)
        header.addWidget(self.month_label, 0, 1)
        header.addLayout(right, 0, 2)
        layout.addLayout(header)

        self.grid = QGridLayout()
        self.grid.setSpacing(0)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.weekday_labels = []
        for col, text in enumerate(["일", "월", "화", "수", "목", "금", "토"]):
            label = QLabel(text)
            label.setAlignment(Qt.AlignCenter)
            label.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
            label.setFixedHeight(20)
            label.setStyleSheet(
                f"background: {c['weekday']}; color: {c['text']};"
                f"border: 1px solid {c['grid']};"
            )
            self.weekday_labels.append(label)
            self.grid.addWidget(label, 0, col)

        for row in range(6):
            for col in range(7):
                cell = DayCell(c)
                cell.clicked.connect(self.open_schedule_near)
                self.day_cells.append(cell)
                self.grid.addWidget(cell, row + 1, col)
        layout.addLayout(self.grid, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(QSizeGrip(self))
        layout.addLayout(bottom)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")

    def setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip(APP_NAME)

        menu = QMenu()
        show_action = QAction("Fox Calendar 열기", self)
        memo_action = QAction("새 메모", self)
        settings_action = QAction("설정", self)
        quit_action = QAction("종료", self)

        show_action.triggered.connect(self.show_calendar)
        memo_action.triggered.connect(self.create_memo)
        settings_action.triggered.connect(self.open_settings)
        quit_action.triggered.connect(self.quit_from_tray)

        menu.addAction(show_action)
        menu.addAction(memo_action)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.handle_tray_activated)
        self.tray.show()

    def handle_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and self.isActiveWindow():
                self.hide()
            else:
                self.show_calendar()

    def show_calendar(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def quit_from_tray(self) -> None:
        self.force_quit = True
        self.save()
        QApplication.quit()

    def header_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ color: {c['text']}; background: transparent; border: none; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['panel2']}; border-radius: 5px; }}"
        )

    def render_calendar(self) -> None:
        self.month_label.setText(f"{self.visible_month.year}년 {self.visible_month.month}월")
        weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(self.visible_month.year, self.visible_month.month)
        days = [day for week in weeks for day in week]
        for index, cell in enumerate(self.day_cells):
            if index >= len(days):
                cell.hide()
                continue
            cell.show()
            day = days[index]
            lines: list[str] = []
            holiday = self.get_holiday(day)
            schedule = self.get_schedule(day).strip()
            if schedule:
                lines.extend(line.strip() for line in schedule.splitlines() if line.strip())
            state = "normal"
            if day.month != self.visible_month.month:
                state = "other"
            elif day == self.selected_day:
                state = "selected"
            elif day == date.today():
                state = "today"
            elif holiday:
                state = "holiday"
            cell.set_data(day, lines, state, holiday)

    def get_holiday(self, day: date) -> str:
        if not self.config.get("holiday_enabled", True):
            return ""
        return FIXED_KOREAN_HOLIDAYS.get((day.month, day.day), "")

    def get_schedule(self, day: date) -> str:
        return self.config.setdefault("schedules", {}).get(day.isoformat(), "")

    def set_schedule(self, day: date, text: str) -> None:
        schedules = self.config.setdefault("schedules", {})
        clean = text.rstrip()
        if clean:
            schedules[day.isoformat()] = clean
        else:
            schedules.pop(day.isoformat(), None)
        self.save()
        self.render_calendar()

    def previous_month(self) -> None:
        year = self.visible_month.year
        month = self.visible_month.month - 1
        if month == 0:
            year -= 1
            month = 12
        self.visible_month = date(year, month, 1)
        self.render_calendar()

    def next_month(self) -> None:
        year = self.visible_month.year
        month = self.visible_month.month + 1
        if month == 13:
            year += 1
            month = 1
        self.visible_month = date(year, month, 1)
        self.render_calendar()

    def open_schedule_near(self, day: date) -> None:
        self.selected_day = day
        self.render_calendar()
        key = day.isoformat()
        if key in self.schedule_windows and self.schedule_windows[key].isVisible():
            self.schedule_windows[key].raise_()
            self.schedule_windows[key].activateWindow()
            return
        width, height = 430, 360
        sender = self.sender()
        if isinstance(sender, QWidget):
            point = sender.mapToGlobal(QPoint(12, 28))
            screen = QApplication.primaryScreen().availableGeometry()
            x = min(max(screen.left(), point.x()), screen.right() - width)
            y = min(max(screen.top(), point.y()), screen.bottom() - height)
            geometry = f"{width}x{height}+{x}+{y}"
        else:
            geometry = None
        window = ScheduleWindow(self, day, geometry)
        self.schedule_windows[key] = window
        window.show()

    def open_settings(self) -> None:
        if self.settings_window and self.settings_window.isVisible():
            self.settings_window.raise_()
            self.settings_window.activateWindow()
            return
        self.settings_window = SettingsWindow(self)
        self.settings_window.show()

    def reopen_settings(self) -> None:
        if self.settings_window:
            self.settings_window.close()
        self.open_settings()

    def create_memo(self) -> None:
        memo_id = datetime.now().strftime("%Y%m%d%H%M%S")
        self.open_memo(memo_id)

    def open_memo(self, memo_id: str, geometry: str | None = None) -> None:
        if memo_id in self.memo_windows and self.memo_windows[memo_id].isVisible():
            self.memo_windows[memo_id].raise_()
            return
        window = StickyMemoWindow(self, memo_id, geometry)
        self.memo_windows[memo_id] = window
        self.remember_open_memo(memo_id, geometry_string(window))
        window.show()

    def restore_open_memos(self) -> None:
        for memo_id, geometry in list(self.config.get("open_memos", {}).items()):
            self.open_memo(memo_id, geometry)

    def remember_open_memo(self, memo_id: str, geometry: str) -> None:
        self.config.setdefault("open_memos", {})[memo_id] = geometry
        self.save()

    def forget_open_memo(self, memo_id: str) -> None:
        self.config.setdefault("open_memos", {}).pop(memo_id, None)
        self.save()

    def set_calendar_opacity(self, value: int) -> None:
        value = max(20, min(100, int(value)))
        self.config["calendar_opacity"] = value
        self.setWindowOpacity(value / 100)
        self.save()

    def set_startup(self, enabled: bool, show_message: bool = True) -> None:
        if enabled:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            launcher = pythonw if pythonw.exists() else Path(sys.executable)
            STARTUP_PATH.parent.mkdir(parents=True, exist_ok=True)
            STARTUP_PATH.write_text(
                f'@echo off\nstart "" "{launcher}" "{Path(__file__).resolve()}"\n',
                encoding="utf-8",
            )
        elif STARTUP_PATH.exists():
            STARTUP_PATH.unlink()
        if show_message:
            QMessageBox.information(self, APP_NAME, "자동 실행 설정을 변경했습니다.")

    def apply_theme(self) -> "FoxCalendarApp":
        self.save()
        new_colors = resolve_theme(self.config)
        self.colors.update(new_colors)
        self.refresh_theme_styles()
        self.render_calendar()
        self.update()
        return self

    def apply_note_theme(self) -> None:
        for window in list(self.memo_windows.values()):
            if window.isVisible():
                window.apply_note_theme()

    def refresh_theme_styles(self) -> None:
        c = self.colors
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        if hasattr(self, "month_label"):
            self.month_label.setStyleSheet(f"color: {c['text']};")
        for button in getattr(self, "header_buttons", []):
            button.setStyleSheet(self.header_button_style())
        for button in getattr(self, "icon_buttons", []):
            button.refresh_style()
            button.update()
        for label in getattr(self, "weekday_labels", []):
            label.setStyleSheet(
                f"background: {c['weekday']}; color: {c['text']};"
                f"border: 1px solid {c['grid']};"
            )
        for cell in self.day_cells:
            cell.update()

    def closeEvent(self, event) -> None:
        self.save()
        if self.force_quit:
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    window = FoxCalendarApp()
    app.main_window = window  # type: ignore[attr-defined]
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
