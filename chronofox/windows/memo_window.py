"""바탕화면에 떠 있는 낱장 메모(스티키 메모) 창 StickyMemoWindow를 구현하는 모듈."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QCursor, QFont, QFontMetricsF, QImageReader, QTextCursor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QTextEdit, QVBoxLayout

from chronofox.core.app_constants import APP_NAME, DEFAULT_MEMO_HEIGHT, DEFAULT_MEMO_WIDTH, SAVE_DEBOUNCE_MS
from chronofox.ui.app_i18n import TrMixin
from chronofox.ui.app_styles import fancy_scrollbar_style
from chronofox.ui.app_theme import resolve_note_theme
from chronofox.ui.app_ui import app_font, geometry_string, parse_geometry
from chronofox.ui.app_widgets import RoundedWindow

if TYPE_CHECKING:
    from chronofox.windows.desktop_note_calendar import FoxCalendarApp

class StickyMemoWindow(TrMixin, RoundedWindow):
    """스티커 메모 창입니다. 내용은 Markdown 파일로 즉시 저장됩니다."""

    def __init__(self, app: FoxCalendarApp, memo_id: str, geometry: str | None = None) -> None:
        self.app = app
        self.memo_id = memo_id
        self.preview_mode = False
        self._discard_on_close = False
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
        """메모 창의 기본 위치/크기를 반환합니다."""
        offset = 28 * len(self.app.memo_windows)
        return f"{DEFAULT_MEMO_WIDTH}x{DEFAULT_MEMO_HEIGHT}+{420 + offset}+{120 + offset}"

    def build_ui(self) -> None:
        """창/페이지의 위젯 레이아웃을 구성합니다."""
        c = resolve_note_theme(self.app.store)
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
        self.title_label.setToolTip(self.tr("memo.title.tooltip", "더블클릭해 제목 수정"))
        self.title_label.setCursor(QCursor(Qt.PointingHandCursor))
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
        self.text.viewport().installEventFilter(self)
        self.preview = QTextBrowser()
        self.preview.setAcceptDrops(True)
        self.preview.setOpenExternalLinks(False)
        self.preview.setStyleSheet(self.note_preview_style(c))
        self.preview.setCursor(QCursor(Qt.PointingHandCursor))
        self.preview.setToolTip(self.tr("memo.preview.tooltip", "클릭해 편집"))
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
        """메모 편집기 QSS 스타일 문자열을 만듭니다."""
        return (
            f"QTextEdit {{ background: {colors['memo_bg']}; color: {colors['memo_text']}; border: none; "
            f"border-bottom-left-radius: {self.radius}px; border-bottom-right-radius: {self.radius}px; padding: 10px; }}"
            + self.memo_scrollbar_style(colors)
        )

    def memo_title(self) -> str:
        """메모 창에 표시할 제목 문자열을 반환합니다."""
        return self.app.store.get("memo_titles", {}).get(self.memo_id, "")

    def clean_title(self) -> str:
        """제목 문자열에서 불필요한 공백/기호를 정리합니다."""
        title = self.title_edit.text().strip()
        return title if title and title != "제목 없음" else ""

    def memo_title_style(self, colors: dict[str, str]) -> str:
        """메모 제목 라벨 QSS 스타일 문자열을 만듭니다."""
        return f"QLabel {{ color: {colors['memo_text']}; background: transparent; }}"

    def memo_title_edit_style(self, colors: dict[str, str]) -> str:
        """메모 제목 편집창 QSS 스타일 문자열을 만듭니다."""
        return (
            f"QLineEdit {{ color: {colors['memo_text']}; background: {colors['memo_hover']}; border: none; "
            "border-radius: 5px; padding: 2px 6px; font-weight: 700; }}"
        )

    def note_preview_style(self, colors: dict[str, str]) -> str:
        """메모 미리보기(Markdown 렌더링) QSS 스타일 문자열을 만듭니다."""
        return (
            f"QTextBrowser {{ background: {colors['memo_bg']}; color: {colors['memo_text']}; border: none; "
            f"border-bottom-left-radius: {self.radius}px; border-bottom-right-radius: {self.radius}px; padding: 10px; }}"
            f"QTextBrowser a {{ color: {colors['accent']}; }}"
            + self.memo_scrollbar_style(colors)
        )

    def memo_scrollbar_style(self, colors: dict[str, str]) -> str:
        """메모 창 스크롤바 QSS 스타일 문자열을 만듭니다."""
        return (
            fancy_scrollbar_style(
                colors["memo_scroll_track"], colors["memo_scroll_handle"], colors["memo_scroll_handle_hover"], colors["memo_scroll_handle"]
            )
            + f"QScrollBar:horizontal {{ background: {colors['memo_scroll_track']}; height: 12px; margin: 0 13px 0 13px; }}"
            f"QScrollBar::handle:horizontal {{ background: {colors['memo_scroll_handle']}; min-width: 28px; border-radius: 5px; margin: 3px 1px; }}"
            f"QScrollBar::handle:horizontal:hover {{ background: {colors['memo_scroll_handle_hover']}; }}"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; height: 0; background: transparent; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }"
        )

    def refresh_markdown_preview(self) -> None:
        """Markdown 미리보기를 현재 내용으로 다시 렌더링합니다."""
        if self.preview_mode:
            self.render_preview()

    def show_preview_mode(self) -> None:
        """메모를 미리보기 모드로 전환합니다."""
        self.preview_mode = True
        self.render_preview()
        self.text.hide()
        self.preview.show()

    def render_preview(self) -> None:
        """보기 모드 줄 간격을 수정 모드와 맞추기 위해 마크다운 단락 마진을 제거합니다."""
        StickyMemoWindow.update_tab_stops(self)
        self.preview.setMarkdown(self.preview_markdown())
        document = self.preview.document()
        metrics = QFontMetricsF(document.defaultFont())
        indent_width = metrics.horizontalAdvance("99. ")
        block = document.firstBlock()
        while block.isValid():
            text_list = block.textList()
            if text_list is not None:
                indent_width = max(indent_width, metrics.horizontalAdvance(text_list.itemText(block) + " "))
            cursor = QTextCursor(block)
            block_format = block.blockFormat()
            block_format.setTopMargin(0)
            block_format.setBottomMargin(0)
            cursor.setBlockFormat(block_format)
            block = block.next()

        # Qt의 기본 40px 대신 번호가 들어갈 폭만 확보하고 중첩/이어쓰기 단계는 유지한다.
        document.setIndentWidth(indent_width)

        StickyMemoWindow.fit_preview_images(self)

    def update_tab_stops(self) -> None:
        """편집·보기의 Tab 폭을 각 현재 글꼴의 공백 네 칸에 맞춘다."""
        for widget in (self.text, self.preview):
            widget.setTabStopDistance(QFontMetricsF(widget.font()).horizontalAdvance("    "))

    def fit_preview_images(self) -> None:
        """외부 이미지의 원본 비율을 유지하며 메모 폭에 맞춥니다."""
        document = self.preview.document()
        available = max(1, self.preview.viewport().width() - 28)
        block = document.firstBlock()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.charFormat().isImageFormat():
                    image_format = fragment.charFormat().toImageFormat()
                    url = QUrl(image_format.name())
                    if url.isLocalFile():
                        size = QImageReader(url.toLocalFile()).size()
                        if size.isValid():
                            width = min(size.width(), available)
                            image_format.setWidth(width)
                            image_format.setHeight(size.height() * width / size.width())
                            cursor = QTextCursor(document)
                            cursor.setPosition(fragment.position())
                            cursor.setPosition(fragment.position() + fragment.length(), QTextCursor.KeepAnchor)
                            cursor.setCharFormat(image_format)
                iterator += 1
            block = block.next()

    def dropped_image_urls(self, mime) -> list[QUrl]:
        """실제 로컬 이미지 파일만 받으며 파일을 복사하거나 이동하지 않습니다."""
        images = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_file() and QImageReader(str(path)).canRead():
                images.append(QUrl.fromLocalFile(str(path.resolve())))
        return images

    def insert_image_references(self, urls: list[QUrl], position=None) -> None:
        cursor = self.text.cursorForPosition(position) if position is not None else self.text.textCursor()
        if position is None:
            cursor.movePosition(QTextCursor.End)
        alt = self.tr("memo.image.alt", "이미지")
        references = "\n\n".join(f"![{alt}](<{url.toString(QUrl.FullyEncoded)}>)" for url in urls)
        cursor.beginEditBlock()
        cursor.insertText(f"\n\n{references}\n\n")
        cursor.endEditBlock()
        self.text.setTextCursor(cursor)
        self.show_preview_mode()

    def preview_markdown(self) -> str:
        """일반 줄바꿈을 보존하되 목록·코드의 Markdown 문단 경계는 유지한다."""
        lines = self.text.toPlainText().splitlines()
        following = [""] * len(lines)
        next_line = ""
        for index in range(len(lines) - 1, -1, -1):
            following[index] = next_line
            if lines[index].strip():
                next_line = lines[index]
        rendered = []
        fence = ""
        list_indent = None
        list_columns = []
        in_indented_code = False
        can_continue = False
        preserve_list_block = False
        in_quote = False
        previous = ""
        for index, line in enumerate(lines):
            expanded = line.expandtabs(4)
            indent = len(expanded) - len(expanded.lstrip(" "))
            marker = re.match(r"^\s*(`{3,}|~{3,})(.*)$", expanded)
            if fence:
                rendered.append(line)
                if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                    fence = ""
                continue
            if line.strip():
                while list_columns and indent < list_columns[-1]:
                    list_columns.pop()
            content_column = list_columns[-1] if list_columns else 0
            starts_paragraph = index == 0 or not lines[index - 1].strip()
            if line.strip() and indent >= content_column + 4 and (starts_paragraph or in_indented_code):
                # Indented code can contain list/fence markers; classify its container first.
                rendered.append(line)
                in_indented_code = True
                can_continue = False
                previous = line
                continue
            if line.strip():
                in_indented_code = False
            if marker:
                fence = marker[1]
                rendered.append(line)
                can_continue = False
                preserve_list_block = False
                continue
            # Quote containers keep their original Markdown, including nested lists/code.
            if re.match(r"^ {0,3}>", expanded):
                rendered.append(line)
                in_quote = True
                previous = line
                can_continue = False
                continue
            item = re.match(r"^(\s*)(?:[-+*]|\d+[.)])(?:[ \t]+|$)", expanded)
            if not line.strip():
                can_continue = False
                preserve_list_block = False
                in_quote = False
                next_text = following[index].expandtabs(4)
                next_indent = len(next_text) - len(next_text.lstrip(" \t"))
                next_item = re.match(r"^\s*(?:[-+*]|\d+[.)])(?:[ \t]+|$)", next_text)
                continues_list = list_indent is not None and next_text and (next_item or next_indent >= list_indent)
                continues_code = previous.startswith(("    ", "\t")) and next_text.startswith(("    ", "\t"))
                if continues_list or continues_code:
                    rendered.append("")
                else:
                    list_indent = None
                    list_columns.clear()
                    in_indented_code = False
                    # 실제 문단 경계 사이에 빈 줄을 두어 앞 목록의 항목으로 흡수되지 않게 한다.
                    rendered.extend(("", "\u00a0", ""))
                continue
            previous = line
            next_text = lines[index + 1].expandtabs(4) if index + 1 < len(lines) else ""
            setext_next = next_text.startswith(" " * content_column) and re.match(
                r"^ {0,3}(?:=+|-+)[ \t]*$", next_text[content_column:],
            )
            contained_start = list_indent is not None and indent >= list_indent and (
                setext_next or re.match(
                    r"(?:#{1,6}(?:\s|$)|(?:\*\s*){3,}$|(?:-\s*){3,}$|(?:_\s*){3,}$|=+[ \t]*$"
                    r"|\[[^\]]+\]:|<(?:/?[A-Za-z][\w-]*(?=[ \t/>]|$)|!--))",
                    expanded.lstrip(" "),
                )
            )
            if item and not contained_start:
                preserve_list_block = False
            if contained_start or (preserve_list_block and list_indent is not None and indent >= list_indent):
                # A separator before a block marker makes Qt parse it as literal text.
                # Preserve this block's remaining lines until a paragraph/list boundary.
                preserve_list_block = True
                can_continue = False
                rendered.append(line)
                continue
            interrupt = re.match(r"^ {0,3}(?:#{1,6}(?:\s|$)|(?:\*\s*){3,}$|(?:-\s*){3,}$|(?:_\s*){3,}$)", expanded)
            if interrupt and (list_indent is None or indent < list_indent):
                list_indent = None
                list_columns.clear()
                in_quote = False
                rendered.append(line)
                can_continue = False
                continue
            if list_indent is not None and not item and indent < list_indent and not in_quote:
                # 메모의 일반 줄은 Markdown의 암묵적 목록 이어쓰기로 합치지 않는다.
                rendered.append("")
                list_indent = None
                list_columns.clear()
            if item:
                # Keep the outer list's content column when entering a nested item.
                list_indent = min(list_indent, item.end()) if list_indent is not None else item.end()
                while list_columns and indent < list_columns[-1]:
                    list_columns.pop()
                list_columns.append(item.end())
            if list_indent is not None and not item and not in_indented_code and can_continue:
                # Qt turns Markdown hard breaks into extra bullets; a Unicode line separator
                # keeps the continuation on a new visual line inside the same list item.
                leading = len(line) - len(line.lstrip(" \t"))
                rendered[-1] = rendered[-1].rstrip(" ")
                rendered.append(line[:leading] + "\u2028" + line[leading:])
            elif list_indent is not None or in_quote or in_indented_code:
                rendered.append(line)
            else:
                rendered.append(line + "  ")
            can_continue = not in_indented_code
        return "\n".join(rendered)

    def show_edit_mode(self) -> None:
        """메모를 편집 모드로 전환합니다."""
        self.preview_mode = False
        self.update_tab_stops()
        self.preview.hide()
        self.text.show()
        self.text.setFocus()

    def eventFilter(self, watched, event) -> bool:
        if hasattr(self, "preview") and watched in (self.text, self.text.viewport(), self.preview, self.preview.viewport()):
            if event.type() in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop) and event.mimeData().hasUrls():
                images = self.dropped_image_urls(event.mimeData())
                if images:
                    event.setDropAction(Qt.CopyAction)
                    event.accept()
                    if event.type() == QEvent.Drop:
                        position = event.position().toPoint() if watched in (self.text, self.text.viewport()) else None
                        self.insert_image_references(images, position)
                else:
                    event.ignore()
                return True
            if watched is self.preview.viewport() and event.type() == QEvent.Resize:
                self.fit_preview_images()
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
        """메모 창 닫기 버튼 QSS 스타일 문자열을 만듭니다."""
        return (
            f"QPushButton {{ color: {colors['memo_text']}; background: transparent; border: none; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {colors['memo_hover']}; border-radius: 5px; }}"
        )

    def start_title_edit(self) -> None:
        """메모 제목 편집을 시작합니다."""
        current = self.clean_title() or self.memo_title()
        self.title_edit.setText("" if current == "제목 없음" else current)
        self.title_label.hide()
        self.title_edit.show()
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def finish_title_edit(self) -> None:
        """메모 제목 편집을 마치고 저장합니다."""
        title = self.clean_title()
        titles = self.app.store.get("memo_titles", {})
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
        """메모 창들에 현재 테마를 다시 적용합니다."""
        c = resolve_note_theme(self.app.store)
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
        """디바운스를 건너뛰고 즉시 저장합니다."""
        if self.save_timer.isActive():
            self.save_timer.stop()
        if getattr(self.app, "skip_exit_flush", False):
            return
        text = self.text.toPlainText()
        title = self.clean_title()
        titles = self.app.store.get("memo_titles", {})
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
        """짧은 디바운스 후 저장되도록 예약합니다."""
        if getattr(self.app, "skip_exit_flush", False):
            self.save_timer.stop()
            return
        self.save_timer.start()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if hasattr(self, "save_timer"):
            self.queue_save()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "save_timer"):
            self.queue_save()

    def closeEvent(self, event) -> None:
        if self._discard_on_close or getattr(self.app, "skip_exit_flush", False):
            self.save_timer.stop()
            self.app.memo_windows.pop(self.memo_id, None)
            super().closeEvent(event)
            self.app.store.notify("memo_windows")
            return
        self.save_now()
        # QApplication.quit()도 closeEvent를 보내므로 앱 종료는 사용자의 메모 닫기와 구분한다.
        if not getattr(self.app, "force_quit", False):
            self.app.forget_open_memo(self.memo_id)
        self.app.memo_windows.pop(self.memo_id, None)
        super().closeEvent(event)
        self.app.store.notify("memo_windows")

    def discard_and_close(self) -> None:
        """삭제 흐름에서 대기 중 저장을 버리고 창을 닫습니다."""
        self._discard_on_close = True
        self.close()

