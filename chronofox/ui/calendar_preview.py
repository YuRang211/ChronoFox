"""Non-activating design previews; hovering never constructs or mutates a calendar."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from chronofox.core.app_constants import CALENDAR_PREVIEW_DIR
from chronofox.ui.app_styles import CALENDAR_STYLE_KEYS
from chronofox.ui.app_theme import THEMES
from chronofox.ui.app_ui import app_font
from chronofox.ui.app_widgets import ArrowComboBox


class CalendarPreview(QFrame):
    def __init__(self, parent, translate: Callable) -> None:
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setObjectName("calendarPreview")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.translate = translate
        self.preview_style = ""
        self.preview_theme = ""
        self.preview_language = ""
        self._image = QPixmap()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        header = QHBoxLayout()
        self.title = QLabel()
        self.title.setFont(app_font(10))
        self.caption = QLabel()
        self.caption.setFont(app_font(8))
        header.addWidget(self.title, 1)
        header.addWidget(self.caption)
        layout.addLayout(header)
        self.image = QLabel()
        self.image.setObjectName("calendarPreviewImage")
        self.image.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.image)
        self.note = QLabel()
        self.note.setFont(app_font(8))
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

    def show_design(self, style: str, title: str, theme: str, language: str, width: int) -> None:
        self.preview_style, self.preview_theme, self.preview_language = style, theme, language
        colors = THEMES[theme]
        self.setStyleSheet(
            f"QFrame#calendarPreview {{ background: {colors['panel']}; "
            f"border: 1px solid {colors['border']}; border-radius: 8px; }}"
            f"QFrame#calendarPreview QLabel {{ background: transparent; border: none; color: {colors['text']}; }}"
        )
        for label in (self.caption, self.note):
            label.setStyleSheet(f"color: {colors['muted']};")
        self.title.setText(title)
        self.caption.setText(self.translate("settings.theme.preview.title", "미리보기"))
        self.note.setText(self.translate("settings.theme.preview.sample", "예시 일정 · 클릭하면 적용됩니다"))
        # Synthetic captures avoid personal data reads and rebuilding the real window.
        self._image = QPixmap(str(CALENDAR_PREVIEW_DIR / f"{style}-{theme}-{language}.png"))
        self.setFixedWidth(width)
        if self._image.isNull():
            self.image.clear()
            self.image.setText(self.translate("settings.theme.preview.unavailable", "미리보기를 불러올 수 없습니다"))
        else:
            self.image.setPixmap(self._image.scaledToWidth(width - 24, Qt.SmoothTransformation))
        self.adjustSize()


class CalendarStyleComboBox(ArrowComboBox):
    """Keep native selection semantics; only highlighted rows preview."""

    def __init__(self, colors: dict[str, str], context: Callable, translate: Callable) -> None:
        super().__init__(colors)
        self._context = context
        self._preview_index = -1
        self._popup_open = False
        self.preview_window = CalendarPreview(self, translate)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(250)
        self._preview_timer.timeout.connect(self._show_preview)
        self.highlighted.connect(self._queue_preview)
        self.view().setMouseTracking(True)
        self.view().viewport().setMouseTracking(True)
        self.view().viewport().installEventFilter(self)

    def showPopup(self) -> None:
        self._popup_open = True
        super().showPopup()
        self.view().window().installEventFilter(self)
        self._queue_preview(self.currentIndex())

    def hidePopup(self) -> None:
        self._close_preview()
        super().hidePopup()

    def hideEvent(self, event) -> None:
        self._close_preview()
        super().hideEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Hide and watched is self.view().window():
            self._close_preview()
        elif event.type() == QEvent.Leave and watched is self.view().viewport():
            self._preview_timer.stop()
        return super().eventFilter(watched, event)

    def _close_preview(self) -> None:
        self._popup_open = False
        self._preview_timer.stop()
        self.preview_window.hide()

    def _queue_preview(self, index: int) -> None:
        if self._popup_open and 0 <= index < self.count():
            self._preview_index = index
            self._preview_timer.start()

    def _show_preview(self) -> None:
        if not self._popup_open or not self.isVisible() or not self.view().isVisible():
            return
        style = self.itemData(self._preview_index)
        if style not in CALENDAR_STYLE_KEYS:
            return
        theme, language = self._context()
        theme = theme if theme in THEMES else "dark"
        language = language if language in ("ko", "en") else "ko"
        bounds = self.view().window().frameGeometry()
        screen = self.view().screen().availableGeometry()
        width = min(444, screen.width() - 16)
        self.preview_window.show_design(style, self.itemText(self._preview_index), theme, language, width)
        popup = self.preview_window
        # Prefer the side with room, then clamp to this screen's available area.
        x = bounds.right() + 9
        if x + popup.width() > screen.right() + 1:
            x = bounds.left() - popup.width() - 8
        x = max(screen.left() + 4, min(x, screen.right() - popup.width() - 3))
        y = max(screen.top() + 4, min(bounds.top(), screen.bottom() - popup.height() - 3))
        popup.move(QPoint(x, y))
        popup.show()
