from __future__ import annotations

import calendar
import json
import shutil
import sys
import winreg
from datetime import date, datetime
from pathlib import Path

try:
    import holidays as holiday_lib
except ImportError:
    holiday_lib = None

try:
    from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
    from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPen
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QCheckBox,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMenu,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizeGrip,
        QSlider,
        QSpinBox,
        QSystemTrayIcon,
        QTabWidget,
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
LEGACY_NOTES_DIR = Path.home() / "Documents" / "DesktopNotes"
DEFAULT_NOTES_DIR = APP_DIR / "Notes"
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

HOLIDAY_NAME_REPLACEMENTS = {
    "부처님오신날 대체 휴일": "대체공휴일",
    "신정연휴": "신정",
    "기독탄신일": "성탄절",
    " 대체 휴일": " 대체공휴일",
}

THEMES = {
    "dark": {
        "bg": "#101416",
        "panel": "#171d20",
        "panel2": "#20292d",
        "border": "#2e3a40",
        "text": "#e8f0f2",
        "muted": "#95a5aa",
        "accent": "#77c7d4",
        "grid": "#1d383e",
        "weekday": "#183238",
        "cell": "#132428",
        "other": "#172125",
        "other_text": "#62777d",
        "saturday": "#8fb8d8",
        "sunday": "#d9969c",
        "today_bg": "#203235",
        "today_text": "#c7f1d4",
        "today_border": "#c7f1d4",
        "selected_bg": "#1f4952",
        "selected_text": "#effdff",
        "selected_border": "#77c7d4",
        "holiday": "#ff9fa8",
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
        "grid": "#a9dce1",
        "weekday": "#9adce2",
        "cell": "#eafafb",
        "other": "#cfe3e6",
        "other_text": "#6f8b90",
        "saturday": "#3477aa",
        "sunday": "#b94e5a",
        "today_bg": "#fff6d6",
        "today_text": "#5d4a13",
        "today_border": "#d2ad3f",
        "selected_bg": "#d2f2ee",
        "selected_text": "#14383d",
        "selected_border": "#4aa8b2",
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
        "memo_scroll_track": "#eef5f7",
        "memo_scroll_handle": "#a9bdc4",
        "memo_scroll_handle_hover": "#7f98a0",
    },
    "default": {
        "memo_bg": "#fff7b8",
        "memo_bar": "#f5dc65",
        "memo_text": "#24210e",
        "memo_hover": "#ead157",
        "memo_scroll_track": "#f7e99a",
        "memo_scroll_handle": "#c7ac36",
        "memo_scroll_handle_hover": "#9d821d",
    },
    "dark": {
        "memo_bg": "#1d1f21",
        "memo_bar": "#2c2c2c",
        "memo_text": "#f2f2f2",
        "memo_hover": "#3a3a3a",
        "memo_scroll_track": "#151719",
        "memo_scroll_handle": "#3b3f42",
        "memo_scroll_handle_hover": "#c8d0d4",
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


def migrate_legacy_memos(target_notes_dir: Path) -> None:
    """기존 Documents\\DesktopNotes 메모를 앱 데이터 폴더로 보존 복사합니다."""
    old_memo_dir = LEGACY_NOTES_DIR / "Memos"
    new_memo_dir = target_notes_dir / "Memos"
    if not old_memo_dir.exists() or old_memo_dir == new_memo_dir:
        return
    new_memo_dir.mkdir(parents=True, exist_ok=True)
    for old_path in old_memo_dir.glob("*.md"):
        new_path = new_memo_dir / old_path.name
        if not new_path.exists():
            shutil.copy2(old_path, new_path)


def prettify_holiday_name(name: str) -> str:
    """외부 휴일 데이터의 표현을 달력에 어울리는 짧은 한국어 이름으로 정리합니다."""
    for source, replacement in HOLIDAY_NAME_REPLACEMENTS.items():
        name = name.replace(source, replacement)
    return name


def load_config() -> dict:
    """설정 파일을 읽고, 없는 값은 기본값으로 채운 뒤 다시 저장합니다."""
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
        "memo_titles": {},
        "schedules": {},
        "recurring_tasks": {"daily": [], "weekly": [], "monthly": [], "yearly": []},
        "theme_mode": "system",
        "note_theme": "default",
        "holiday_enabled": True,
        "calendar_opacity": 56,
    }
    for key, value in defaults.items():
        data.setdefault(key, value)
    if Path(data.get("notes_dir", "")) == LEGACY_NOTES_DIR:
        data["notes_dir"] = str(DEFAULT_NOTES_DIR)
    migrate_legacy_memos(Path(data["notes_dir"]))
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def save_config(config: dict) -> None:
    """창 위치, 일정, 설정값 같은 앱 상태를 config.json에 저장합니다."""
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
    """메모 내용을 앱 데이터 폴더의 Markdown 파일로 저장하고 불러옵니다."""

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

    def delete(self, memo_id: str) -> None:
        path = self.path_for(memo_id)
        if path.exists():
            path.unlink()

    def exists(self, memo_id: str) -> bool:
        return self.path_for(memo_id).exists()

    def has_content(self, memo_id: str) -> bool:
        return bool(self.load(memo_id).strip())


class RoundedWindow(QWidget):
    """둥근 모서리와 드래그 이동을 공통으로 제공하는 기본 창입니다."""

    def __init__(self, colors: dict[str, str], radius: int = 14) -> None:
        super().__init__()
        self.colors = colors
        self.radius = radius
        self.drag_start: QPoint | None = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
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
    """이미지 파일 없이 QPainter로 그리는 작은 아이콘 버튼입니다."""

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
        elif self.kind == "menu":
            for y in (8, 12, 16):
                painter.drawLine(8, y, 19, y)
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
    """달력의 날짜 한 칸을 직접 그리는 위젯입니다."""

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
        painter.setPen(QPen(QColor(colors["grid"]), 0.45))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        if self.state == "selected":
            painter.setPen(QPen(QColor(colors["selected_border"]), 1.7))
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))
        elif self.state == "today":
            painter.setPen(QPen(QColor(colors["today_border"]), 1.5))
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

        date_color = fg
        if self.state != "other":
            if self.day.weekday() == 5:
                date_color = colors["saturday"]
            elif self.day.weekday() == 6:
                date_color = colors["sunday"]
            if self.state == "holiday":
                date_color = colors["holiday"]

        painter.setPen(QColor(date_color))
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
        painter.setPen(QColor(fg))
        for line in self.lines:
            painter.drawText(8, y, metrics.elidedText(line, Qt.ElideRight, available))
            y += 16


class ScheduleWindow(RoundedWindow):
    """선택한 날짜의 일정 텍스트를 편집하는 창입니다."""

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
    """스티커 메모 창입니다. 내용은 Markdown 파일로 즉시 저장됩니다."""

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
        self.close_button = QPushButton("x")
        self.close_button.setFixedSize(24, 24)
        self.close_button.clicked.connect(self.close)
        self.close_button.setStyleSheet(self.memo_close_style(c))
        header_layout.addSpacing(24)
        self.title_label = QLabel(self.memo_title())
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
        self.title_label.setStyleSheet(self.memo_title_style(c))
        self.title_label.installEventFilter(self)
        self.title_edit = QLineEdit(self.memo_title())
        self.title_edit.setAlignment(Qt.AlignCenter)
        self.title_edit.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
        self.title_edit.setStyleSheet(self.memo_title_edit_style(c))
        self.title_edit.returnPressed.connect(self.finish_title_edit)
        self.title_edit.installEventFilter(self)
        self.title_edit.hide()
        header_layout.addWidget(self.title_label, 1)
        header_layout.addWidget(self.title_edit, 1)
        header_layout.addWidget(self.close_button)

        self.text = QTextEdit()
        self.text.setPlainText(self.app.memo_store.load(self.memo_id))
        self.text.textChanged.connect(self.save_now)
        self.text.textChanged.connect(self.refresh_markdown_preview)
        self.text.setStyleSheet(self.note_editor_style(c))
        self.text.installEventFilter(self)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setStyleSheet(self.note_preview_style(c))
        self.preview.installEventFilter(self)
        self.preview.viewport().installEventFilter(self)
        grip = QSizeGrip(self)
        grip.setFixedSize(12, 12)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 8, 8)
        bottom.addStretch()
        bottom.addWidget(grip)

        layout.addWidget(self.header)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.preview, 1)
        layout.addLayout(bottom)
        if self.text.toPlainText().strip():
            self.show_preview_mode()
        else:
            self.show_edit_mode()

    def note_editor_style(self, colors: dict[str, str]) -> str:
        return (
            f"QTextEdit {{ background: {colors['memo_bg']}; color: {colors['memo_text']}; border: none; padding: 10px; }}"
            + self.memo_scrollbar_style(colors)
        )

    def memo_title(self) -> str:
        return self.app.config.setdefault("memo_titles", {}).get(self.memo_id, "제목 없음")

    def clean_title(self) -> str:
        title = self.title_edit.text().strip()
        return title if title and title != "제목 없음" else ""

    def memo_title_style(self, colors: dict[str, str]) -> str:
        return f"QLabel {{ color: {colors['memo_text']}; background: transparent; }}"

    def memo_title_edit_style(self, colors: dict[str, str]) -> str:
        return (
            f"QLineEdit {{ color: {colors['memo_text']}; background: {colors['memo_hover']}; border: none; "
            "border-radius: 5px; padding: 2px 6px; font-weight: 700; }}"
        )

    def note_preview_style(self, colors: dict[str, str]) -> str:
        return (
            f"QTextBrowser {{ background: {colors['memo_bg']}; color: {colors['memo_text']}; border: none; padding: 10px; }}"
            f"QTextBrowser a {{ color: {colors['accent']}; }}"
            + self.memo_scrollbar_style(colors)
        )

    def memo_scrollbar_style(self, colors: dict[str, str]) -> str:
        return (
            f"QScrollBar:vertical {{ background: {colors['memo_scroll_track']}; width: 12px; margin: 13px 0 13px 0; }}"
            f"QScrollBar::handle:vertical {{ background: {colors['memo_scroll_handle']}; min-height: 28px; border-radius: 5px; margin: 1px 3px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {colors['memo_scroll_handle_hover']}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ background: {colors['memo_scroll_track']}; height: 13px; subcontrol-origin: margin; }}"
            f"QScrollBar::sub-line:vertical {{ subcontrol-position: top; }}"
            f"QScrollBar::add-line:vertical {{ subcontrol-position: bottom; }}"
            f"QScrollBar::up-arrow:vertical {{ border-left: 4px solid transparent; border-right: 4px solid transparent; border-bottom: 5px solid {colors['memo_scroll_handle']}; width: 0; height: 0; }}"
            f"QScrollBar::down-arrow:vertical {{ border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid {colors['memo_scroll_handle']}; width: 0; height: 0; }}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
            f"QScrollBar:horizontal {{ background: {colors['memo_scroll_track']}; height: 12px; margin: 0 13px 0 13px; }}"
            f"QScrollBar::handle:horizontal {{ background: {colors['memo_scroll_handle']}; min-width: 28px; border-radius: 5px; margin: 3px 1px; }}"
            f"QScrollBar::handle:horizontal:hover {{ background: {colors['memo_scroll_handle_hover']}; }}"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; height: 0; background: transparent; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }"
        )

    def refresh_markdown_preview(self) -> None:
        if self.preview_mode:
            self.preview.setMarkdown(self.text.toPlainText())

    def show_preview_mode(self) -> None:
        self.preview_mode = True
        self.preview.setMarkdown(self.text.toPlainText())
        self.text.hide()
        self.preview.show()

    def show_edit_mode(self) -> None:
        self.preview_mode = False
        self.preview.hide()
        self.text.show()
        self.text.setFocus()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.title_label and event.type() == QEvent.MouseButtonDblClick:
            self.start_title_edit()
            return True
        if watched is self.title_edit and event.type() == QEvent.FocusOut:
            self.finish_title_edit()
            return False
        if hasattr(self, "preview") and watched in (self.preview, self.preview.viewport()) and event.type() == QEvent.MouseButtonPress:
            self.show_edit_mode()
            return True
        if hasattr(self, "text") and watched is self.text and event.type() == QEvent.FocusOut and self.text.toPlainText().strip():
            self.show_preview_mode()
        return super().eventFilter(watched, event)

    def memo_close_style(self, colors: dict[str, str]) -> str:
        return (
            f"QPushButton {{ color: {colors['memo_text']}; background: transparent; border: none; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {colors['memo_hover']}; border-radius: 5px; }}"
        )

    def start_title_edit(self) -> None:
        current = self.clean_title() or self.memo_title()
        self.title_edit.setText("" if current == "제목 없음" else current)
        self.title_label.hide()
        self.title_edit.show()
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def finish_title_edit(self) -> None:
        title = self.clean_title()
        titles = self.app.config.setdefault("memo_titles", {})
        if title:
            titles[self.memo_id] = title
            self.title_label.setText(title)
        else:
            titles.pop(self.memo_id, None)
            self.title_label.setText("제목 없음")
        self.title_edit.hide()
        self.title_label.show()
        self.save_now()

    def apply_note_theme(self) -> None:
        c = resolve_note_theme(self.app.config)
        self.colors.update(c)
        self.header.setStyleSheet(f"QFrame {{ background: {c['memo_bar']}; border-top-left-radius: 14px; border-top-right-radius: 14px; }}")
        self.title_label.setStyleSheet(self.memo_title_style(c))
        self.title_edit.setStyleSheet(self.memo_title_edit_style(c))
        self.close_button.setStyleSheet(self.memo_close_style(c))
        self.text.setStyleSheet(self.note_editor_style(c))
        self.preview.setStyleSheet(self.note_preview_style(c))
        self.refresh_markdown_preview()
        self.update()

    def save_now(self) -> None:
        text = self.text.toPlainText()
        title = self.clean_title()
        titles = self.app.config.setdefault("memo_titles", {})
        if title:
            titles[self.memo_id] = title
        elif self.memo_id in titles:
            titles.pop(self.memo_id, None)
        if text.strip() or title:
            self.app.memo_store.save(self.memo_id, text)
            self.app.remember_open_memo(self.memo_id, geometry_string(self))
        else:
            self.app.memo_store.delete(self.memo_id)
            self.app.forget_open_memo(self.memo_id)

    def closeEvent(self, event) -> None:
        self.save_now()
        self.app.forget_open_memo(self.memo_id)
        self.app.memo_windows.pop(self.memo_id, None)
        super().closeEvent(event)


class SearchWindow(RoundedWindow):
    """일정과 메모 파일을 한 번에 찾는 검색창입니다."""

    def __init__(self, app: "FoxCalendarApp") -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.setWindowTitle(f"{APP_NAME} 검색")
        self.setWindowIcon(app.icon)
        self.opening_result = False
        width, height, x, y = parse_geometry(app.config.get("search_geometry", "520x420"), (520, 420, 320, 160))
        self.setGeometry(x, y, width, height)
        self.build_ui()

    def build_ui(self) -> None:
        c = self.colors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("검색")
        title.setFont(QFont("Malgun Gothic", 15, QFont.Bold))
        close = QPushButton("x")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        close.setStyleSheet(self.button_style())
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close)

        self.query = QLineEdit()
        self.query.setPlaceholderText("일정 검색")
        self.query.textChanged.connect(self.refresh_results)
        self.query.setStyleSheet(self.input_style())

        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(self.open_result)
        self.results.setStyleSheet(self.results_style())

        layout.addLayout(header)
        layout.addWidget(self.query)
        layout.addWidget(self.results, 1)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        self.query.setFocus()
        self.refresh_results("")

    def input_style(self) -> str:
        c = self.colors
        return (
            f"QLineEdit {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 9px; padding: 9px 11px; }}"
            f"QLineEdit:focus {{ border-color: {c['accent']}; }}"
        )

    def results_style(self) -> str:
        c = self.colors
        return (
            f"QListWidget {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 10px; padding: 6px; outline: none; }}"
            f"QListWidget::item {{ padding: 8px; border-radius: 7px; }}"
            f"QListWidget::item:selected, QListWidget::item:hover {{ background: {c['panel2']}; }}"
        )

    def button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ color: {c['muted']}; background: transparent; border: none; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['panel']}; color: {c['text']}; border-radius: 5px; }}"
        )

    def refresh_results(self, query: str) -> None:
        text = query.strip().lower()
        self.results.clear()
        if not text:
            self.add_empty_message("검색어를 입력해 주세요.")
            return

        count = 0
        for day_text, schedule in sorted(self.app.config.setdefault("schedules", {}).items()):
            try:
                day = date.fromisoformat(day_text)
            except ValueError:
                continue
            if text in schedule.lower() or text in day_text or text in day.strftime("%Y.%m.%d"):
                preview = self.preview_text(schedule)
                self.add_result("일정", day.strftime("%Y.%m.%d"), preview, ("schedule", day.isoformat()))
                count += 1

        if count == 0:
            self.add_empty_message("검색 결과가 없습니다.")

    def preview_text(self, content: str) -> str:
        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
        return first_line

    def add_result(self, kind: str, target: str, preview: str, data: tuple[str, str]) -> None:
        item = QListWidgetItem()
        item.setData(Qt.UserRole, data)
        item.setSizeHint(QSize(0, 46))
        self.results.addItem(item)
        self.results.setItemWidget(item, SearchResultWidget(kind, target, preview, self.colors))

    def add_empty_message(self, message: str) -> None:
        item = QListWidgetItem(message)
        item.setFlags(Qt.NoItemFlags)
        self.results.addItem(item)

    def open_result(self, item: QListWidgetItem) -> None:
        if self.opening_result:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        self.opening_result = True
        try:
            kind, value = data
            if kind == "schedule":
                day = date.fromisoformat(value)
                QTimer.singleShot(0, lambda d=day: self.open_schedule_result(d))
        except Exception as exc:
            self.opening_result = False
            QMessageBox.warning(self, APP_NAME, f"검색 결과를 여는 중 문제가 발생했습니다.\n{exc}")

    def open_schedule_result(self, day: date) -> None:
        try:
            self.app.select_date(day)
            self.app.open_schedule(day)
            self.close()
        except Exception as exc:
            self.opening_result = False
            QMessageBox.warning(self, APP_NAME, f"검색 결과를 여는 중 문제가 발생했습니다.\n{exc}")

    def closeEvent(self, event) -> None:
        self.app.config["search_geometry"] = geometry_string(self)
        self.app.save()
        self.app.search_window = None
        super().closeEvent(event)


class SearchResultWidget(QWidget):
    """검색 결과 한 줄을 창 폭에 맞춰 직접 그립니다."""

    def __init__(self, kind: str, target: str, preview: str, colors: dict[str, str]) -> None:
        super().__init__()
        self.kind = kind
        self.target = target
        self.preview = preview
        self.colors = colors

    def paintEvent(self, _event) -> None:
        c = self.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(c["panel2"]))

        painter.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
        metrics = painter.fontMetrics()
        x = 12
        y = self.height() // 2 + metrics.ascent() // 2 - 2

        painter.setPen(QColor(c["text"]))
        painter.drawText(x, y, self.kind)
        x += metrics.horizontalAdvance(self.kind) + 10

        painter.setPen(QColor(c["muted"]))
        painter.drawText(x, y, "|")
        x += metrics.horizontalAdvance("|") + 10

        painter.setPen(QColor(c["text"]))
        painter.drawText(x, y, self.target)
        x += metrics.horizontalAdvance(self.target) + 10

        painter.setPen(QColor(c["muted"]))
        painter.drawText(x, y, "|")
        x += metrics.horizontalAdvance("|") + 10

        painter.setFont(QFont("Malgun Gothic", 9))
        painter.setPen(QColor(c["text"]))
        available = max(20, self.width() - x - 12)
        painter.drawText(x, y, painter.fontMetrics().elidedText(self.preview, Qt.ElideRight, available))


class ClockWindow(RoundedWindow):
    """현재 시각, 스톱워치, 타이머를 제공하는 작은 도구 창입니다."""

    def __init__(self, app: "FoxCalendarApp") -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.stopwatch_seconds = 0
        self.timer_remaining = 0
        self.timer_running = False
        self.stopwatch_running = False
        self.tick = QTimer(self)
        self.tick.setInterval(1000)
        self.tick.timeout.connect(self.on_tick)
        self.tick.start()
        self.setWindowTitle(f"{APP_NAME} 시계")
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(app.config.get("clock_geometry", "380x340"), (380, 340, 360, 180))
        self.setGeometry(x, y, width, height)
        self.build_ui()

    def build_ui(self) -> None:
        c = self.colors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)
        layout.addLayout(self.header("시계"))

        tabs = QTabWidget()
        tabs.setStyleSheet(self.tab_style())
        tabs.addTab(self.clock_tab(), "현재")
        tabs.addTab(self.stopwatch_tab(), "스톱워치")
        tabs.addTab(self.timer_tab(), "타이머")
        layout.addWidget(tabs, 1)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")

    def header(self, title_text: str) -> QHBoxLayout:
        header = QHBoxLayout()
        title = QLabel(title_text)
        title.setFont(QFont("Malgun Gothic", 15, QFont.Bold))
        close = QPushButton("x")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        close.setStyleSheet(self.button_style())
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close)
        return header

    def clock_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)
        self.current_time = QLabel("")
        self.current_time.setAlignment(Qt.AlignCenter)
        self.current_time.setFont(QFont("Malgun Gothic", 28, QFont.Bold))
        self.current_date = QLabel("")
        self.current_date.setAlignment(Qt.AlignCenter)
        self.current_date.setFont(QFont("Malgun Gothic", 11))
        layout.addWidget(self.current_time)
        layout.addWidget(self.current_date)
        self.refresh_clock()
        return widget

    def stopwatch_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)
        self.stopwatch_label = QLabel(self.format_seconds(0))
        self.stopwatch_label.setAlignment(Qt.AlignCenter)
        self.stopwatch_label.setFont(QFont("Malgun Gothic", 26, QFont.Bold))
        controls = QHBoxLayout()
        start = QPushButton("시작")
        pause = QPushButton("정지")
        reset = QPushButton("초기화")
        start.clicked.connect(self.start_stopwatch)
        pause.clicked.connect(self.pause_stopwatch)
        reset.clicked.connect(self.reset_stopwatch)
        for button in (start, pause, reset):
            button.setStyleSheet(self.button_style())
            controls.addWidget(button)
        layout.addWidget(self.stopwatch_label)
        layout.addLayout(controls)
        return widget

    def timer_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)
        inputs = QHBoxLayout()
        self.timer_minutes = QSpinBox()
        self.timer_seconds = QSpinBox()
        self.timer_minutes.setRange(0, 999)
        self.timer_seconds.setRange(0, 59)
        self.timer_minutes.setSuffix(" 분")
        self.timer_seconds.setSuffix(" 초")
        for spin in (self.timer_minutes, self.timer_seconds):
            spin.setStyleSheet(self.input_style())
            inputs.addWidget(spin)
        self.timer_label = QLabel(self.format_seconds(0))
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setFont(QFont("Malgun Gothic", 26, QFont.Bold))
        controls = QHBoxLayout()
        start = QPushButton("시작")
        pause = QPushButton("정지")
        reset = QPushButton("초기화")
        start.clicked.connect(self.start_timer)
        pause.clicked.connect(self.pause_timer)
        reset.clicked.connect(self.reset_timer)
        for button in (start, pause, reset):
            button.setStyleSheet(self.button_style())
            controls.addWidget(button)
        layout.addLayout(inputs)
        layout.addWidget(self.timer_label)
        layout.addLayout(controls)
        return widget

    def on_tick(self) -> None:
        self.refresh_clock()
        if self.stopwatch_running:
            self.stopwatch_seconds += 1
            self.stopwatch_label.setText(self.format_seconds(self.stopwatch_seconds))
        if self.timer_running and self.timer_remaining > 0:
            self.timer_remaining -= 1
            self.timer_label.setText(self.format_seconds(self.timer_remaining))
            if self.timer_remaining == 0:
                self.timer_running = False
                self.raise_()
                QMessageBox.information(self, APP_NAME, "타이머가 끝났습니다.")

    def refresh_clock(self) -> None:
        now = datetime.now()
        self.current_time.setText(now.strftime("%H:%M:%S"))
        self.current_date.setText(now.strftime("%Y.%m.%d"))

    def start_stopwatch(self) -> None:
        self.stopwatch_running = True

    def pause_stopwatch(self) -> None:
        self.stopwatch_running = False

    def reset_stopwatch(self) -> None:
        self.stopwatch_running = False
        self.stopwatch_seconds = 0
        self.stopwatch_label.setText(self.format_seconds(0))

    def start_timer(self) -> None:
        if self.timer_remaining <= 0:
            self.timer_remaining = self.timer_minutes.value() * 60 + self.timer_seconds.value()
        self.timer_label.setText(self.format_seconds(self.timer_remaining))
        self.timer_running = self.timer_remaining > 0

    def pause_timer(self) -> None:
        self.timer_running = False

    def reset_timer(self) -> None:
        self.timer_running = False
        self.timer_remaining = self.timer_minutes.value() * 60 + self.timer_seconds.value()
        self.timer_label.setText(self.format_seconds(self.timer_remaining))

    def format_seconds(self, total: int) -> str:
        hours = total // 3600
        minutes = (total % 3600) // 60
        seconds = total % 60
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def tab_style(self) -> str:
        c = self.colors
        return (
            f"QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 9px; background: {c['panel']}; }}"
            f"QTabBar::tab {{ color: {c['muted']}; padding: 7px 12px; }}"
            f"QTabBar::tab:selected {{ color: {c['text']}; background: {c['panel2']}; border-radius: 7px; }}"
        )

    def input_style(self) -> str:
        c = self.colors
        return f"QSpinBox {{ background: {c['panel2']}; color: {c['text']}; border: none; border-radius: 7px; padding: 6px 8px; }}"

    def button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 7px; padding: 7px 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def closeEvent(self, event) -> None:
        self.app.config["clock_geometry"] = geometry_string(self)
        self.app.save()
        self.app.clock_window = None
        super().closeEvent(event)


class RepeatWindow(RoundedWindow):
    """반복되는 할 일의 완료 횟수와 경과 시간을 관리합니다."""

    PERIODS = [("daily", "매일"), ("weekly", "매주"), ("monthly", "매월"), ("yearly", "매년")]

    def __init__(self, app: "FoxCalendarApp") -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.add_window: AddRepeatTaskWindow | None = None
        self.period_keys = self.current_period_keys()
        self.setWindowTitle(f"{APP_NAME} 반복")
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(app.config.get("repeat_geometry", "480x460"), (480, 460, 340, 160))
        self.setGeometry(x, y, width, height)
        self.build_ui()

    def build_ui(self) -> None:
        c = self.colors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)
        layout.addLayout(self.header())

        top_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색")
        self.search_input.setStyleSheet(self.input_style())
        self.search_input.textChanged.connect(self.refresh_all)
        add = QPushButton("+")
        add.setFixedSize(38, 34)
        add.clicked.connect(self.open_add_task)
        add.setStyleSheet(self.plus_button_style())
        top_row.addWidget(self.search_input, 1)
        top_row.addWidget(add)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(self.list_style())
        layout.addLayout(top_row)
        layout.addWidget(self.list_widget, 1)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        self.refresh_all()
        self.reset_check_timer = QTimer(self)
        self.reset_check_timer.setInterval(60000)
        self.reset_check_timer.timeout.connect(self.refresh_if_period_changed)
        self.reset_check_timer.start()

    def header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        title = QLabel("반복")
        title.setFont(QFont("Malgun Gothic", 15, QFont.Bold))
        close = QPushButton("x")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        close.setStyleSheet(self.button_style())
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close)
        return header

    def current_key(self, period: str) -> str:
        today = date.today()
        if period == "daily":
            return today.isoformat()
        if period == "weekly":
            year, week, _weekday = today.isocalendar()
            return f"{year}-W{week:02}"
        if period == "monthly":
            return today.strftime("%Y-%m")
        return today.strftime("%Y")

    def current_period_keys(self) -> dict[str, str]:
        return {period: self.current_key(period) for period, _label in self.PERIODS}

    def refresh_if_period_changed(self) -> None:
        current = self.current_period_keys()
        if current != self.period_keys:
            self.period_keys = current
            self.refresh_all()

    def tasks(self, period: str) -> list[dict]:
        tasks = self.app.config.setdefault("recurring_tasks", {}).setdefault(period, [])
        return tasks

    def normalize_task(self, task: dict) -> dict:
        task.setdefault("id", datetime.now().strftime("%Y%m%d%H%M%S%f"))
        task.setdefault("text", "")
        task.setdefault("done", "")
        task.setdefault("created", date.today().isoformat())
        task.setdefault("done_count", 0)
        task.setdefault("counted_keys", [])
        return task

    def period_label(self, period: str) -> str:
        return dict(self.PERIODS).get(period, period)

    def all_tasks(self) -> list[tuple[str, dict]]:
        rows: list[tuple[str, dict]] = []
        for period, _label in self.PERIODS:
            for task in self.tasks(period):
                rows.append((period, task))
        return rows

    def open_add_task(self) -> None:
        if self.add_window and self.add_window.isVisible():
            self.add_window.raise_()
            self.add_window.activateWindow()
            return
        self.add_window = AddRepeatTaskWindow(self)
        self.add_window.show()

    def open_edit_task(self, period: str, task: dict) -> None:
        if self.add_window and self.add_window.isVisible():
            self.add_window.close()
        self.add_window = AddRepeatTaskWindow(self, period, task)
        self.add_window.show()

    def add_task(self, period: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.tasks(period).append(
            {
                "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
                "text": text,
                "done": "",
                "created": date.today().isoformat(),
                "done_count": 0,
                "counted_keys": [],
            }
        )
        self.app.save()
        self.refresh_all()

    def update_task(self, old_period: str, task: dict, new_period: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.normalize_task(task)
        task["text"] = text
        if old_period != new_period:
            self.tasks(old_period)[:] = [item for item in self.tasks(old_period) if item.get("id") != task.get("id")]
            self.tasks(new_period).append(task)
        self.app.save()
        self.refresh_all()

    def refresh_all(self) -> None:
        self.list_widget.clear()
        query = self.search_input.text().strip().lower()
        changed = False
        for period, task in self.all_tasks():
            before = dict(task)
            self.normalize_task(task)
            changed = changed or task != before
            text = task.get("text", "")
            if query and query not in text.lower() and query not in self.period_label(period):
                continue
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 58))
            self.list_widget.addItem(item)
            row = RepeatTaskRow(self, period, task)
            self.list_widget.setItemWidget(item, row)
        if changed:
            self.app.save()

    def set_done(self, period: str, task: dict, checked: bool) -> None:
        task = self.normalize_task(task)
        current = self.current_key(period)
        counted = task.setdefault("counted_keys", [])
        if checked:
            if current not in counted:
                task["done_count"] = int(task.get("done_count", 0)) + 1
                counted.append(current)
            task["done"] = current
        else:
            if task.get("done") == current and current in counted:
                task["done_count"] = max(0, int(task.get("done_count", 0)) - 1)
                counted.remove(current)
            task["done"] = ""
        self.app.save()
        self.refresh_all()

    def elapsed_text(self, period: str, task: dict) -> str:
        try:
            created = date.fromisoformat(task.get("created", ""))
        except ValueError:
            created = date.today()
        today = date.today()
        days = max(0, (today - created).days)
        if period == "daily":
            value, unit = days, "일"
        elif period == "weekly":
            value, unit = days // 7, "주"
        elif period == "monthly":
            value = max(0, (today.year - created.year) * 12 + today.month - created.month)
            unit = "개월"
        else:
            value, unit = max(0, today.year - created.year), "년"
        return f"{value}{unit} 지남"

    def list_style(self) -> str:
        c = self.colors
        return (
            f"QListWidget {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 9px; padding: 6px; outline: none; }}"
            f"QListWidget::item:selected {{ background: {c['panel2']}; border-radius: 6px; }}"
        )

    def checkbox_style(self) -> str:
        c = self.colors
        return f"QCheckBox {{ color: {c['text']}; spacing: 8px; padding: 7px; }}"

    def input_style(self) -> str:
        c = self.colors
        return (
            f"QLineEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 8px; }}"
        )

    def plus_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 10px; font-size: 20px; font-weight: 700; padding-bottom: 2px; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def edit_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['muted']}; border: none; "
            "border-radius: 9px; font-size: 11px; font-weight: 700; padding: 4px 8px; }}"
            f"QPushButton:hover {{ background: {c['border']}; color: {c['text']}; }}"
        )

    def button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 7px; padding: 7px 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def closeEvent(self, event) -> None:
        self.app.config["repeat_geometry"] = geometry_string(self)
        self.app.save()
        self.app.repeat_window = None
        super().closeEvent(event)


class RepeatTaskRow(QWidget):
    """반복 할 일 한 줄입니다."""

    def __init__(self, window: RepeatWindow, period: str, task: dict) -> None:
        super().__init__()
        self.window = window
        self.period = period
        self.task = task
        self.build_ui()

    def build_ui(self) -> None:
        c = self.window.colors
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        check = QCheckBox()
        check.setChecked(self.task.get("done") == self.window.current_key(self.period))
        check.setStyleSheet(self.window.checkbox_style())
        check.toggled.connect(lambda checked: self.window.set_done(self.period, self.task, checked))

        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(1)
        title = QLabel(self.task.get("text", ""))
        title.setStyleSheet(f"QLabel {{ color: {c['text']}; background: transparent; font-weight: 600; }}")
        meta = QLabel(f"{self.window.elapsed_text(self.period, self.task)} · {int(self.task.get('done_count', 0))}회 완료")
        meta.setStyleSheet(f"QLabel {{ color: {c['muted']}; background: transparent; font-size: 11px; }}")
        texts.addWidget(title)
        texts.addWidget(meta)

        badge = QLabel(self.window.period_label(self.period))
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedWidth(44)
        badge.setStyleSheet(
            f"QLabel {{ color: {c['muted']}; background: {c['panel2']}; border-radius: 8px; padding: 4px 6px; }}"
        )

        edit = QPushButton("수정")
        edit.setFixedSize(42, 28)
        edit.setStyleSheet(self.window.edit_button_style())
        edit.clicked.connect(lambda: self.window.open_edit_task(self.period, self.task))

        layout.addWidget(check)
        layout.addLayout(texts, 1)
        layout.addWidget(badge)
        layout.addWidget(edit)


class AddRepeatTaskWindow(RoundedWindow):
    """반복 할 일을 추가하거나 수정하는 작은 설정창입니다."""

    def __init__(self, repeat_window: RepeatWindow, edit_period: str | None = None, edit_task: dict | None = None) -> None:
        super().__init__(repeat_window.app.dialog_colors())
        self.repeat_window = repeat_window
        self.edit_period = edit_period
        self.edit_task = edit_task
        self.setWindowTitle(f"{APP_NAME} 반복 {'수정' if edit_task else '추가'}")
        self.setWindowIcon(repeat_window.app.icon)
        anchor = repeat_window.geometry()
        self.setGeometry(anchor.x() + 36, anchor.y() + 72, 320, 180)
        self.build_ui()

    def build_ui(self) -> None:
        c = self.colors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("할 일 수정" if self.edit_task else "할 일 추가")
        title.setFont(QFont("Malgun Gothic", 13, QFont.Bold))
        close = QPushButton("x")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        close.setStyleSheet(self.repeat_window.button_style())
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("할 일 입력")
        if self.edit_task:
            self.text_input.setText(self.edit_task.get("text", ""))
        self.text_input.setStyleSheet(self.repeat_window.input_style())
        self.text_input.returnPressed.connect(self.add_task)

        self.period_combo = QComboBox()
        for key, label in RepeatWindow.PERIODS:
            self.period_combo.addItem(label, key)
        if self.edit_period:
            index = self.period_combo.findData(self.edit_period)
            self.period_combo.setCurrentIndex(max(0, index))
        self.period_combo.setStyleSheet(self.combo_style())

        apply = QPushButton("저장" if self.edit_task else "+")
        apply.setFixedHeight(34)
        apply.clicked.connect(self.add_task)
        apply.setStyleSheet(self.repeat_window.plus_button_style() if not self.edit_task else self.repeat_window.button_style())

        layout.addLayout(header)
        layout.addWidget(self.text_input)
        layout.addWidget(self.period_combo)
        layout.addWidget(apply)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        self.text_input.setFocus()

    def combo_style(self) -> str:
        c = self.colors
        return (
            f"QComboBox {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def add_task(self) -> None:
        if self.edit_task and self.edit_period:
            self.repeat_window.update_task(
                self.edit_period,
                self.edit_task,
                self.period_combo.currentData(),
                self.text_input.text(),
            )
        else:
            self.repeat_window.add_task(self.period_combo.currentData(), self.text_input.text())
        self.close()

    def closeEvent(self, event) -> None:
        self.repeat_window.add_window = None
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
    """테마, 투명도, 자동실행 같은 사용자 설정을 바꾸는 창입니다."""

    def __init__(self, app: "FoxCalendarApp") -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.setWindowTitle(f"{APP_NAME} 설정")
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(app.config.get("settings_geometry", "620x520"), (620, 520, 260, 130))
        self.setGeometry(x, y, width, height)
        self.build_ui()

    def build_ui(self) -> None:
        """설정창의 각 설정 카드와 입력 컨트롤을 구성합니다."""
        c = self.colors
        existing = self.layout()
        if existing is None:
            layout = QVBoxLayout(self)
        else:
            clear_layout(existing)
            layout = existing
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
            + self.scrollbar_style()
        )
        scroll.viewport().setStyleSheet(f"background: {c['bg']};")
        content = QWidget()
        content.setStyleSheet(f"background: {c['bg']};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 12, 0)
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
            "border-radius: 7px; padding: 6px 28px 6px 10px; }}"
            f"QComboBox:hover, QSpinBox:hover {{ background: {c['border']}; }}"
            f"QComboBox::drop-down {{ border: none; width: 28px; subcontrol-origin: padding; subcontrol-position: top right; }}"
            f"QComboBox::down-arrow {{ image: none; width: 0; height: 0; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid {c['muted']}; margin-top: 2px; margin-right: 9px; }}"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def scrollbar_style(self) -> str:
        c = self.colors
        return (
            f"QScrollBar:vertical {{ background: {c['panel']}; width: 12px; margin: 13px 0 13px 0; }}"
            f"QScrollBar::handle:vertical {{ background: {c['border']}; min-height: 28px; border-radius: 5px; margin: 1px 3px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ background: {c['panel']}; height: 13px; subcontrol-origin: margin; }}"
            f"QScrollBar::sub-line:vertical {{ subcontrol-position: top; }}"
            f"QScrollBar::add-line:vertical {{ subcontrol-position: bottom; }}"
            f"QScrollBar::up-arrow:vertical {{ border-left: 4px solid transparent; border-right: 4px solid transparent; border-bottom: 5px solid {c['border']}; width: 0; height: 0; }}"
            f"QScrollBar::down-arrow:vertical {{ border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid {c['border']}; width: 0; height: 0; }}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
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
        self.app.apply_theme()
        self.colors = self.app.dialog_colors()
        self.build_ui()
        self.update()

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
    """달력, 트레이 아이콘, 일정, 메모창을 관리하는 메인 앱입니다."""

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
        self.search_window: SearchWindow | None = None
        self.clock_window: ClockWindow | None = None
        self.repeat_window: RepeatWindow | None = None
        self.holiday_cache: dict[int, dict[date, str]] = {}
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
        """메인 달력의 헤더, 요일줄, 날짜칸을 구성합니다."""
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
        menu_button = IconButton("menu", c)
        self.header_buttons = []
        prev_button.clicked.connect(self.previous_month)
        next_button.clicked.connect(self.next_month)
        menu_button.clicked.connect(self.open_header_menu)

        self.icon_buttons = [prev_button, next_button, menu_button]
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
        right.addWidget(menu_button)
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
            label.setProperty("weekday_col", col)
            label.setAlignment(Qt.AlignCenter)
            label.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
            label.setFixedHeight(20)
            weekday_color = c["text"]
            if col == 0:
                weekday_color = c["sunday"]
            elif col == 6:
                weekday_color = c["saturday"]
            label.setStyleSheet(
                f"background: {c['weekday']}; color: {weekday_color};"
                f"border: 0.5px solid {c['grid']};"
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

    def open_header_menu(self) -> None:
        c = self.colors
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 7px; padding: 5px; }}"
            f"QMenu::item {{ padding: 7px 28px 7px 12px; border-radius: 5px; }}"
            f"QMenu::item:selected {{ background: {c['panel2']}; }}"
            f"QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 4px; }}"
        )
        today_action = menu.addAction("오늘로 이동")
        search_action = menu.addAction("검색")
        clock_action = menu.addAction("시계")
        repeat_action = menu.addAction("반복")
        menu.addSeparator()
        memo_action = menu.addAction("새 메모")
        recall_memos_action = menu.addAction("숨은 메모 불러오기")
        settings_action = menu.addAction("설정")
        menu.addSeparator()
        hide_action = menu.addAction("숨기기")

        today_action.triggered.connect(self.go_to_today)
        search_action.triggered.connect(self.open_search)
        clock_action.triggered.connect(self.open_clock)
        repeat_action.triggered.connect(self.open_repeat)
        memo_action.triggered.connect(self.create_memo)
        recall_memos_action.triggered.connect(self.recall_hidden_memos)
        settings_action.triggered.connect(self.open_settings)
        hide_action.triggered.connect(self.close)

        sender = self.sender()
        if isinstance(sender, QWidget):
            menu.exec(sender.mapToGlobal(QPoint(0, sender.height() + 2)))

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
        self.raise_memos_above_calendar()

    def raise_memos_above_calendar(self) -> None:
        """달력이 다시 활성화되어도 열린 메모가 달력 뒤로 숨지 않게 합니다."""
        for window in list(self.memo_windows.values()):
            if window.isVisible():
                window.raise_()

    def event(self, event) -> bool:
        if event.type() == QEvent.WindowActivate:
            self.raise_memos_above_calendar()
        return super().event(event)

    def quit_from_tray(self) -> None:
        self.force_quit = True
        self.persist_open_memos()
        self.save()
        QApplication.quit()

    def header_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ color: {c['text']}; background: transparent; border: none; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['panel2']}; border-radius: 5px; }}"
        )

    def render_calendar(self) -> None:
        """현재 보이는 월의 날짜, 일정, 공휴일을 날짜칸에 반영합니다."""
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
        return self.holidays_for_year(day.year).get(day, "")

    def holidays_for_year(self, year: int) -> dict[date, str]:
        """API 키 없이 한국 공휴일을 계산하고 연도별로 캐시합니다."""
        if year in self.holiday_cache:
            return self.holiday_cache[year]

        holidays_by_date: dict[date, str] = {}
        if holiday_lib is not None:
            try:
                kr_holidays = holiday_lib.country_holidays("KR", years=[year], language="ko", observed=True)
                holidays_by_date = {
                    holiday_day: prettify_holiday_name(str(name))
                    for holiday_day, name in kr_holidays.items()
                    if isinstance(holiday_day, date)
                }
            except Exception:
                holidays_by_date = {}

        if not holidays_by_date:
            holidays_by_date = {
                date(year, month, day): name
                for (month, day), name in FIXED_KOREAN_HOLIDAYS.items()
            }

        self.holiday_cache[year] = holidays_by_date
        return holidays_by_date

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

    def go_to_today(self) -> None:
        self.go_to_date(date.today())

    def go_to_date(self, day: date) -> None:
        self.select_date(day)
        self.show_calendar()

    def select_date(self, day: date) -> None:
        self.selected_day = day
        self.visible_month = day.replace(day=1)
        self.render_calendar()

    def open_schedule_near(self, day: date) -> None:
        self.selected_day = day
        self.render_calendar()
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
        self.open_schedule(day, geometry)

    def open_schedule(self, day: date, geometry: str | None = None) -> None:
        key = day.isoformat()
        if key in self.schedule_windows and self.schedule_windows[key].isVisible():
            self.schedule_windows[key].raise_()
            self.schedule_windows[key].activateWindow()
            return
        if geometry is None:
            width, height = 430, 360
            anchor = self.geometry()
            screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
            available = screen.availableGeometry()
            x = min(max(available.left(), anchor.x() + 32), available.right() - width)
            y = min(max(available.top(), anchor.y() + 64), available.bottom() - height)
            geometry = f"{width}x{height}+{x}+{y}"
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

    def open_search(self) -> None:
        if self.search_window and self.search_window.isVisible():
            self.search_window.raise_()
            self.search_window.activateWindow()
            return
        self.search_window = SearchWindow(self)
        self.search_window.show()

    def open_clock(self) -> None:
        if self.clock_window and self.clock_window.isVisible():
            self.clock_window.raise_()
            self.clock_window.activateWindow()
            return
        self.clock_window = ClockWindow(self)
        self.clock_window.show()

    def open_repeat(self) -> None:
        if self.repeat_window and self.repeat_window.isVisible():
            self.repeat_window.raise_()
            self.repeat_window.activateWindow()
            return
        self.repeat_window = RepeatWindow(self)
        self.repeat_window.show()

    def reopen_settings(self) -> None:
        if self.settings_window:
            self.settings_window.close()
        self.open_settings()

    def create_memo(self) -> None:
        memo_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        self.open_memo(memo_id)

    def open_memo(self, memo_id: str, geometry: str | None = None) -> None:
        if memo_id in self.memo_windows and self.memo_windows[memo_id].isVisible():
            self.memo_windows[memo_id].raise_()
            return
        window = StickyMemoWindow(self, memo_id, geometry)
        self.memo_windows[memo_id] = window
        if self.memo_has_content(memo_id):
            self.remember_open_memo(memo_id, geometry_string(window))
        window.show()
        window.raise_()

    def restore_open_memos(self) -> None:
        """복원 목록에 남아 있고 내용이 있는 메모창만 다시 엽니다."""
        for memo_id, geometry in list(self.config.get("open_memos", {}).items()):
            if self.memo_has_content(memo_id):
                self.open_memo(memo_id, geometry)
            else:
                self.forget_open_memo(memo_id)

    def memo_has_content(self, memo_id: str) -> bool:
        return self.memo_store.has_content(memo_id) or bool(self.config.setdefault("memo_titles", {}).get(memo_id, "").strip())

    def remember_open_memo(self, memo_id: str, geometry: str) -> None:
        self.config.setdefault("open_memos", {})[memo_id] = geometry
        self.save()

    def forget_open_memo(self, memo_id: str) -> None:
        self.config.setdefault("open_memos", {}).pop(memo_id, None)
        self.save()

    def persist_open_memos(self) -> None:
        """종료 직전에 열린 메모의 내용과 위치를 한 번 더 저장합니다."""
        for memo_id, window in list(self.memo_windows.items()):
            if window.isVisible():
                window.save_now()
        self.save()

    def recall_hidden_memos(self) -> None:
        """복원 대상 메모를 달력 근처로 다시 모아 화면 밖 메모를 회수합니다."""
        active_ids = [
            memo_id
            for memo_id in self.config.get("open_memos", {})
            if self.memo_has_content(memo_id)
        ]
        if not active_ids:
            return

        anchor = self.geometry()
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        base_x = min(max(available.left() + 12, anchor.x() + 24), available.right() - 280)
        base_y = min(max(available.top() + 12, anchor.y() + 54), available.bottom() - 260)

        for index, memo_id in enumerate(active_ids):
            window = self.memo_windows.get(memo_id)
            if window is None or not window.isVisible():
                self.open_memo(memo_id, self.config["open_memos"].get(memo_id))
                window = self.memo_windows.get(memo_id)
            if window is None:
                continue

            offset = index * 28
            x = min(base_x + offset, available.right() - window.width())
            y = min(base_y + offset, available.bottom() - window.height())
            window.move(max(available.left(), x), max(available.top(), y))
            window.show()
            window.raise_()
            window.activateWindow()
            self.remember_open_memo(memo_id, geometry_string(window))

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
            col = int(label.property("weekday_col") or -1)
            weekday_color = c["text"]
            if col == 0:
                weekday_color = c["sunday"]
            elif col == 6:
                weekday_color = c["saturday"]
            label.setStyleSheet(
                f"background: {c['weekday']}; color: {weekday_color};"
                f"border: 0.5px solid {c['grid']};"
            )
        for cell in self.day_cells:
            cell.update()

    def closeEvent(self, event) -> None:
        self.persist_open_memos()
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
    app.aboutToQuit.connect(window.persist_open_memos)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
