"""일정과 메모를 함께 검색해 결과를 보여주는 SearchWindow(디바운스 검색 포함)를 구현하는 모듈."""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QVBoxLayout, QWidget

from chronofox.core.app_constants import APP_NAME, DEFAULT_SEARCH_GEOMETRY, SEARCH_DEBOUNCE_MS
from chronofox.ui.app_i18n import TrMixin
from chronofox.ui.app_ui import app_font, clear_layout, geometry_string, parse_geometry
from chronofox.ui.app_widgets import IconButton, RoundedWindow

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp

class SearchWindow(TrMixin, RoundedWindow):
    """일정과 메모 파일을 한 번에 찾는 검색창입니다."""

    def __init__(self, app: FoxCalendarApp) -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.setWindowTitle(self.window_title_text())
        self.setWindowIcon(app.icon)
        self.opening_result = False
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self.search_timer.timeout.connect(self.refresh_current_results)
        width, height, x, y = parse_geometry(app.config.get("search_geometry", DEFAULT_SEARCH_GEOMETRY), (520, 420, 320, 160))
        self.setGeometry(x, y, width, height)
        self.build_ui()

    def window_title_text(self) -> str:
        """현재 언어에 맞는 창 제목 문자열을 반환합니다."""
        return self.tr("search.window.title", "{app} 검색", app=self.tr("app.name", APP_NAME))

    def build_ui(self) -> None:
        """창/페이지의 위젯 레이아웃을 구성합니다."""
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
        self.title_label = QLabel(self.tr("search.title", "검색"))
        self.title_label.setFont(app_font(15, QFont.Bold))
        self.close_button = IconButton("close", self.colors)
        self.close_button.setFixedSize(26, 24)
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.title_label)
        header.addStretch()
        header.addWidget(self.close_button)

        self.query = QLineEdit()
        self.query.setPlaceholderText(self.tr("search.placeholder", "일정, 메모 검색"))
        self.query.textChanged.connect(self.queue_refresh_results)
        self.query.returnPressed.connect(self.refresh_current_results)
        self.query.setStyleSheet(self.input_style())

        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(self.open_result)
        self.results.itemActivated.connect(self.open_result)
        self.results.setStyleSheet(self.results_style())

        self.hint_label = QLabel(self.tr("search.hint", "Enter 또는 더블클릭으로 열기"))
        self.hint_label.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")

        layout.addLayout(header)
        layout.addWidget(self.query)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.hint_label)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        self.query.setFocus()
        self.query.setText(current_query)
        self.refresh_results(current_query)

    def input_style(self) -> str:
        """입력창 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QLineEdit {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 9px; padding: 9px 11px; }}"
            f"QLineEdit:focus {{ border-color: {c['accent']}; }}"
        )

    def results_style(self) -> str:
        """검색 결과 목록 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QListWidget {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 10px; padding: 6px; outline: none; }}"
            f"QListWidget::item {{ padding: 8px; border-radius: 7px; }}"
            f"QListWidget::item:selected, QListWidget::item:hover {{ background: {c['panel2']}; }}"
        )

    def button_style(self) -> str:
        """버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QPushButton {{ color: {c['muted']}; background: transparent; border: none; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['panel']}; color: {c['text']}; border-radius: 5px; }}"
        )

    def refresh_results(self, query: str) -> None:
        """results를 새로 고칩니다."""
        text = query.strip().lower()
        self.results.clear()
        if not text:
            self.add_empty_message(self.tr("search.empty.prompt", "검색어를 입력해 주세요."))
            return

        count = 0
        for day_text, schedule in sorted(self.app.store.schedules().items()):
            try:
                day = date.fromisoformat(day_text)
            except ValueError:
                continue
            if text in schedule.lower() or text in day_text or text in day.strftime("%Y.%m.%d"):
                preview = self.preview_text(schedule)
                self.add_result(self.tr("search.kind.schedule", "일정"), day.strftime("%Y.%m.%d"), preview, ("schedule", day.isoformat()))
                count += 1

        titles = self.app.store.get("memo_titles", {})
        for memo_id in self.app.memo_store.memo_ids():
            content = self.app.memo_store.load(memo_id)
            title = titles.get(memo_id, "").strip()
            haystack = f"{title}\n{content}".lower()
            if text not in haystack:
                continue
            target = title or self.tr("search.memo.untitled", "제목 없는 메모")
            preview = self.preview_text(content) or target
            self.add_result(self.tr("search.kind.memo", "메모"), target, preview, ("memo", memo_id))
            count += 1

        if count == 0:
            self.add_empty_message(self.tr("search.empty.none", "검색 결과가 없습니다."))

    def queue_refresh_results(self, _query: str) -> None:
        """검색 결과 갱신을 짧은 디바운스 후 예약합니다."""
        self.search_timer.start()

    def refresh_current_results(self) -> None:
        """현재 검색어로 검색 결과를 다시 계산합니다."""
        if self.search_timer.isActive():
            self.search_timer.stop()
        self.refresh_results(self.query.text())

    def preview_text(self, content: str) -> str:
        """검색 결과에 보여줄 미리보기 문자열을 만듭니다."""
        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
        return first_line

    def add_result(self, kind: str, target: str, preview: str, data: tuple[str, str]) -> None:
        """검색 결과 목록에 한 항목을 추가합니다."""
        item = QListWidgetItem()
        item.setData(Qt.UserRole, data)
        item.setSizeHint(QSize(0, 52))
        self.results.addItem(item)
        self.results.setItemWidget(item, SearchResultWidget(kind, target, preview, self.colors))

    def add_empty_message(self, message: str) -> None:
        """검색 결과가 없을 때 표시할 안내 문구를 추가합니다."""
        item = QListWidgetItem(message)
        item.setFlags(Qt.NoItemFlags)
        self.results.addItem(item)

    def open_result(self, item: QListWidgetItem) -> None:
        """선택한 검색 결과 항목을 엽니다."""
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
            logging.getLogger(__name__).exception("failed to dispatch search result")
            self.opening_result = False
            QMessageBox.warning(self, self.tr("app.name", APP_NAME), self.tr("search.error.open", "검색 결과를 여는 중 문제가 발생했습니다.\n{error}", error=str(exc)))

    def open_schedule_result(self, day: date) -> None:
        """검색 결과에서 일정 항목을 엽니다."""
        try:
            self.app.select_date(day)
            self.app.open_schedule(day)
            self.close()
        except Exception as exc:
            logging.getLogger(__name__).exception("failed to open schedule search result")
            self.opening_result = False
            QMessageBox.warning(self, self.tr("app.name", APP_NAME), self.tr("search.error.open", "검색 결과를 여는 중 문제가 발생했습니다.\n{error}", error=str(exc)))

    def open_memo_result(self, memo_id: str) -> None:
        """검색 결과에서 메모 항목을 엽니다."""
        try:
            self.app.open_memo(memo_id)
            self.close()
        except Exception as exc:
            logging.getLogger(__name__).exception("failed to open memo search result")
            self.opening_result = False
            QMessageBox.warning(self, self.tr("app.name", APP_NAME), self.tr("search.error.open", "검색 결과를 여는 중 문제가 발생했습니다.\n{error}", error=str(exc)))

    def apply_theme(self) -> None:
        """현재 테마 색상을 위젯 스타일에 다시 적용합니다."""
        self.colors.update(self.app.dialog_colors())
        self.refresh_theme_styles()
        self.refresh_font_styles()
        self.update()

    def apply_language(self) -> None:
        """현재 언어 설정에 맞춰 화면 텍스트를 다시 그립니다."""
        self.setWindowTitle(self.window_title_text())
        self.build_ui()
        self.update()

    def refresh_theme_styles(self) -> None:
        """테마가 바뀐 뒤 스타일시트를 다시 적용합니다."""
        self.setStyleSheet(f"QLabel {{ color: {self.colors['text']}; }}")
        if hasattr(self, "close_button"):
            self.close_button.refresh_style()
            self.close_button.update()
        if hasattr(self, "query"):
            self.query.setStyleSheet(self.input_style())
        if hasattr(self, "hint_label"):
            self.hint_label.setStyleSheet(f"color: {self.colors['muted']}; font-size: 11px;")
        if hasattr(self, "results"):
            self.results.setStyleSheet(self.results_style())
            for index in range(self.results.count()):
                item = self.results.item(index)
                widget = self.results.itemWidget(item)
                if isinstance(widget, SearchResultWidget):
                    widget.colors = self.colors
                    widget.update()

    def refresh_font_styles(self) -> None:
        """폰트가 바뀐 뒤 스타일시트를 다시 적용합니다."""
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
        self.app.store.set("search_geometry", geometry_string(self), notify_topic=None)
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

