from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget

from app_constants import APP_NAME, DEFAULT_SEARCH_GEOMETRY, SEARCH_DEBOUNCE_MS
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
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self.search_timer.timeout.connect(self.refresh_current_results)
        width, height, x, y = parse_geometry(app.config.get("search_geometry", DEFAULT_SEARCH_GEOMETRY), (520, 420, 320, 160))
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
        self.title_label = QLabel("검색")
        self.title_label.setFont(app_font(15, QFont.Bold))
        self.close_button = QPushButton("x")
        self.close_button.setFixedSize(24, 24)
        self.close_button.clicked.connect(self.close)
        self.close_button.setStyleSheet(self.button_style())
        header.addWidget(self.title_label)
        header.addStretch()
        header.addWidget(self.close_button)

        self.query = QLineEdit()
        self.query.setPlaceholderText("일정, 메모 검색")
        self.query.textChanged.connect(self.queue_refresh_results)
        self.query.returnPressed.connect(self.refresh_current_results)
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

        titles = self.app.config.setdefault("memo_titles", {})
        for memo_id in self.app.memo_store.memo_ids():
            content = self.app.memo_store.load(memo_id)
            title = titles.get(memo_id, "").strip()
            haystack = f"{title}\n{content}".lower()
            if text not in haystack:
                continue
            target = title or "제목 없는 메모"
            preview = self.preview_text(content) or target
            self.add_result("메모", target, preview, ("memo", memo_id))
            count += 1

        if count == 0:
            self.add_empty_message("검색 결과가 없습니다.")

    def queue_refresh_results(self, _query: str) -> None:
        self.search_timer.start()

    def refresh_current_results(self) -> None:
        if self.search_timer.isActive():
            self.search_timer.stop()
        self.refresh_results(self.query.text())

    def preview_text(self, content: str) -> str:
        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
        return first_line

    def add_result(self, kind: str, target: str, preview: str, data: tuple[str, str]) -> None:
        item = QListWidgetItem()
        item.setData(Qt.UserRole, data)
        item.setSizeHint(QSize(0, 52))
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
            elif kind == "memo":
                QTimer.singleShot(0, lambda memo_id=value: self.open_memo_result(memo_id))
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

    def open_memo_result(self, memo_id: str) -> None:
        try:
            self.app.open_memo(memo_id)
            self.close()
        except Exception as exc:
            self.opening_result = False
            QMessageBox.warning(self, APP_NAME, f"검색 결과를 여는 중 문제가 발생했습니다.\n{exc}")

    def apply_theme(self) -> None:
        self.colors.update(self.app.dialog_colors())
        self.refresh_theme_styles()
        self.refresh_font_styles()
        self.update()

    def refresh_theme_styles(self) -> None:
        self.setStyleSheet(f"QLabel {{ color: {self.colors['text']}; }}")
        if hasattr(self, "close_button"):
            self.close_button.setStyleSheet(self.button_style())
        if hasattr(self, "query"):
            self.query.setStyleSheet(self.input_style())
        if hasattr(self, "results"):
            self.results.setStyleSheet(self.results_style())
            for index in range(self.results.count()):
                item = self.results.item(index)
                widget = self.results.itemWidget(item)
                if isinstance(widget, SearchResultWidget):
                    widget.colors = self.colors
                    widget.update()

    def refresh_font_styles(self) -> None:
        if hasattr(self, "title_label"):
            self.title_label.setFont(app_font(15, QFont.Bold))
        if hasattr(self, "query"):
            self.query.setFont(app_font())
        if hasattr(self, "results"):
            self.results.setFont(app_font())
            for index in range(self.results.count()):
                item = self.results.item(index)
                widget = self.results.itemWidget(item)
                if isinstance(widget, SearchResultWidget):
                    widget.update()

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

        badge_width = max(42, metrics.horizontalAdvance(self.kind) + 18)
        badge_rect = QRect(x, self.height() // 2 - 12, badge_width, 24)
        badge_color = QColor(c["accent"])
        badge_color.setAlpha(42)
        painter.setPen(Qt.NoPen)
        painter.setBrush(badge_color)
        painter.drawRoundedRect(badge_rect, 8, 8)
        painter.setPen(QColor(c["text"]))
        painter.drawText(badge_rect, Qt.AlignCenter, self.kind)
        x += badge_width + 12

        painter.setPen(QColor(c["text"]))
        target_width = min(150, max(70, self.width() // 3))
        painter.drawText(QRect(x, 0, target_width, self.height()), Qt.AlignVCenter | Qt.AlignLeft, metrics.elidedText(self.target, Qt.ElideRight, target_width))
        x += target_width + 10

        painter.setPen(QColor(c["muted"]))
        painter.drawText(x, y, "|")
        x += metrics.horizontalAdvance("|") + 10

        painter.setFont(app_font(9))
        painter.setPen(QColor(c["text"]))
        available = max(20, self.width() - x - 12)
        painter.drawText(x, y, painter.fontMetrics().elidedText(self.preview, Qt.ElideRight, available))

