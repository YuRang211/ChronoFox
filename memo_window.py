from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QTextEdit, QVBoxLayout

from app_constants import APP_NAME, DEFAULT_MEMO_HEIGHT, DEFAULT_MEMO_WIDTH, SAVE_DEBOUNCE_MS
from app_theme import resolve_note_theme
from app_ui import app_font, geometry_string, parse_geometry
from app_widgets import RoundedWindow

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp

class StickyMemoWindow(RoundedWindow):
    """스티커 메모 창입니다. 내용은 Markdown 파일로 즉시 저장됩니다."""

    def __init__(self, app: FoxCalendarApp, memo_id: str, geometry: str | None = None) -> None:
        self.app = app
        self.memo_id = memo_id
        self.preview_mode = False
        colors = resolve_note_theme(app.config)
        super().__init__(colors)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(SAVE_DEBOUNCE_MS)
        self.save_timer.timeout.connect(self.save_now)
        self.setWindowTitle(f"{APP_NAME} Memo")
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(geometry or self.default_geometry(), (DEFAULT_MEMO_WIDTH, DEFAULT_MEMO_HEIGHT, 420, 120))
        self.setGeometry(x, y, width, height)
        self.build_ui()

    def default_geometry(self) -> str:
        offset = 28 * len(self.app.memo_windows)
        return f"{DEFAULT_MEMO_WIDTH}x{DEFAULT_MEMO_HEIGHT}+{420 + offset}+{120 + offset}"

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
        self.title_label.setFont(app_font(9, QFont.Bold))
        self.title_label.setStyleSheet(self.memo_title_style(c))
        self.title_label.installEventFilter(self)
        self.title_edit = QLineEdit(self.memo_title())
        self.title_edit.setAlignment(Qt.AlignCenter)
        self.title_edit.setFont(app_font(9, QFont.Bold))
        self.title_edit.setStyleSheet(self.memo_title_edit_style(c))
        self.title_edit.returnPressed.connect(self.finish_title_edit)
        self.title_edit.installEventFilter(self)
        self.title_edit.hide()
        header_layout.addWidget(self.title_label, 1)
        header_layout.addWidget(self.title_edit, 1)
        header_layout.addWidget(self.close_button)

        self.text = QTextEdit()
        self.text.setPlainText(self.app.memo_store.load(self.memo_id))
        self.text.textChanged.connect(self.queue_save)
        self.text.textChanged.connect(self.refresh_markdown_preview)
        self.text.setStyleSheet(self.note_editor_style(c))
        self.text.installEventFilter(self)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setStyleSheet(self.note_preview_style(c))
        self.preview.installEventFilter(self)
        self.preview.viewport().installEventFilter(self)

        layout.addWidget(self.header)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.preview, 1)
        if self.text.toPlainText().strip():
            self.show_preview_mode()
        else:
            self.show_edit_mode()

    def note_editor_style(self, colors: dict[str, str]) -> str:
        return (
            f"QTextEdit {{ background: {colors['memo_bg']}; color: {colors['memo_text']}; border: none; "
            f"border-bottom-left-radius: {self.radius}px; border-bottom-right-radius: {self.radius}px; padding: 10px; }}"
            + self.memo_scrollbar_style(colors)
        )

    def memo_title(self) -> str:
        return self.app.config.setdefault("memo_titles", {}).get(self.memo_id, "")

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
            f"QTextBrowser {{ background: {colors['memo_bg']}; color: {colors['memo_text']}; border: none; "
            f"border-bottom-left-radius: {self.radius}px; border-bottom-right-radius: {self.radius}px; padding: 10px; }}"
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
            self.preview.setMarkdown(self.preview_markdown())

    def show_preview_mode(self) -> None:
        self.preview_mode = True
        self.preview.setMarkdown(self.preview_markdown())
        self.text.hide()
        self.preview.show()

    def preview_markdown(self) -> str:
        """보기 모드에서 사용자가 입력한 일반 줄바꿈도 그대로 보이게 합니다."""
        lines = self.text.toPlainText().splitlines()
        return "\n".join(line + "  " if line.strip() else line for line in lines)

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
            self.title_label.setText("")
        self.title_edit.hide()
        self.title_label.show()
        self.save_now()

    def apply_note_theme(self) -> None:
        c = resolve_note_theme(self.app.config)
        self.colors.update(c)
        self.header.setStyleSheet(f"QFrame {{ background: {c['memo_bar']}; border-top-left-radius: 14px; border-top-right-radius: 14px; }}")
        self.title_label.setFont(app_font(9, QFont.Bold))
        self.title_edit.setFont(app_font(9, QFont.Bold))
        self.title_label.setStyleSheet(self.memo_title_style(c))
        self.title_edit.setStyleSheet(self.memo_title_edit_style(c))
        self.close_button.setStyleSheet(self.memo_close_style(c))
        self.text.setStyleSheet(self.note_editor_style(c))
        self.preview.setStyleSheet(self.note_preview_style(c))
        self.refresh_markdown_preview()
        self.update()

    def save_now(self) -> None:
        if self.save_timer.isActive():
            self.save_timer.stop()
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

    def queue_save(self) -> None:
        self.save_timer.start()

    def closeEvent(self, event) -> None:
        self.save_now()
        self.app.forget_open_memo(self.memo_id)
        self.app.memo_windows.pop(self.memo_id, None)
        super().closeEvent(event)

