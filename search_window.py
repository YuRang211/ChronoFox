from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget

from app_constants import APP_NAME
from app_ui import app_font, clear_layout, geometry_string, parse_geometry
from app_widgets import RoundedWindow

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp

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
        current_query = self.query.text() if hasattr(self, "query") else ""
        existing = self.layout()
        if existing is None:
            layout = QVBoxLayout(self)
        else:
            clear_layout(existing)
            layout = existing
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("검색")
        title.setFont(app_font(15, QFont.Bold))
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
        self.query.setText(current_query)
        self.refresh_results(current_query)

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
        for day_text, schedule in sorted(self.app.data.setdefault("schedules", {}).items()):
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

    def apply_theme(self) -> None:
        self.colors.update(self.app.dialog_colors())
        self.build_ui()
        self.update()

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

        painter.setFont(app_font(9, QFont.Bold))
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

        painter.setFont(app_font(9))
        painter.setPen(QColor(c["text"]))
        available = max(20, self.width() - x - 12)
        painter.drawText(x, y, painter.fontMetrics().elidedText(self.preview, Qt.ElideRight, available))

