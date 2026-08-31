"""Detail-schedule 창의 "보관" 섹션 믹스인.

REQUIRED attributes/메서드 (DetailScheduleWindow 코어가 제공):
- `self.app`(FoxCalendarApp, `.store`/`.memo_store`/`open_memo`/`create_memo` 보관), `self.colors`(dict)
- `self.section`(str), `self.archive_box`(QVBoxLayout, build_archive_view가 생성)
- `self.tr(key, fallback, **kwargs)` (TrMixin)
- `self.build_ui()`, `self.icon_only_button(icon, handler)`, `self.scroll_style()`, `self.close()`
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget

from chronofox.core.app_constants import APP_NAME
from chronofox.ui.app_ui import app_font, clear_layout

from .widgets import ElidedLabel, stroke_icon


class ArchiveSectionMixin:
    """보관 목록 상단바/본문/행/열기/생성과 준비 중 안내를 담당합니다."""

    def show_archive_view(self) -> None:
        """호환 위임: 기존 호출부가 그대로 동작하도록 show_section("archive")를 부른다."""
        self.show_section("archive")

    def saved_memos(self) -> list[tuple[str, str, str]]:
        """저장된 메모를 (id, 제목, 미리보기)로 최신순 반환합니다."""
        rows: list[tuple[str, str, str]] = []
        titles = self.app.store.get("memo_titles", {})
        for memo_id in self.app.memo_store.memo_ids():
            content = self.app.memo_store.load(memo_id)
            title = str(titles.get(memo_id, "")).strip()
            preview = next((line.strip() for line in content.splitlines() if line.strip()), "")
            if not title and not preview:
                continue
            rows.append((memo_id, title, preview))
        rows.sort(key=lambda row: row[0], reverse=True)
        return rows

    def build_archive_top_bar(self) -> QHBoxLayout:
        """보관함 화면 상단 바를 구성합니다."""
        c = self.colors
        self.view_buttons = {}
        bar = QHBoxLayout()
        bar.setSpacing(12)
        title = QLabel(self.tr("detail.archive.title", "보관"))
        title.setFont(app_font(15, QFont.Bold))
        title.setStyleSheet(f"color: {c['text']};")
        self.archive_badge = QLabel("")
        self.archive_badge.setFont(app_font(7, QFont.Bold))
        self.archive_badge.setStyleSheet(
            f"QLabel {{ background: {c['panel2']}; color: {c['muted']}; border-radius: 5px; padding: 2px 7px; }}"
        )
        new_memo = QPushButton(self.tr("detail.archive.new", "새 메모"))
        new_memo.setCursor(Qt.PointingHandCursor)
        new_memo.setFixedHeight(32)
        new_memo.clicked.connect(self.create_archive_memo)
        new_memo.setStyleSheet(
            f"QPushButton {{ background: {c['pill']}; color: {c['pill_text']}; border: none; "
            "border-radius: 9px; padding: 0 16px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['accent']}; color: #ffffff; }}"
        )
        # AUDIT-B D6: 무기능 벨 아이콘(DETAIL2 목업 잔재) 제거 — layout.py 상단 바와 통일.
        close_button = self.icon_only_button("close", self.close)
        bar.addWidget(title)
        bar.addSpacing(6)
        bar.addWidget(self.archive_badge)
        bar.addStretch()
        bar.addWidget(new_memo)
        bar.addWidget(close_button)
        return bar

    def build_archive_view(self) -> QWidget:
        """보관함 목록 화면을 구성합니다."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(self.scroll_style())
        inner = QWidget()
        self.archive_box = QVBoxLayout(inner)
        self.archive_box.setContentsMargins(2, 2, 12, 2)
        self.archive_box.setSpacing(8)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        self.refresh_archive_view()
        return container

    def refresh_archive_view(self) -> None:
        """보관함 목록을 현재 데이터로 다시 그립니다."""
        if self.section != "archive" or not hasattr(self, "archive_box"):
            return
        clear_layout(self.archive_box)
        rows = self.saved_memos()
        if hasattr(self, "archive_badge"):
            self.archive_badge.setText(self.tr("detail.archive.count", "{count}개", count=len(rows)))
        if not rows:
            empty = QLabel(self.tr("detail.archive.empty", "저장된 메모가 없습니다."))
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {self.colors['muted2']}; padding: 10px 4px;")
            self.archive_box.addWidget(empty)
            self.archive_box.addStretch()
            return
        for memo_id, title, preview in rows:
            self.archive_box.addWidget(self.make_archive_row(memo_id, title, preview))
        self.archive_box.addStretch()

    def make_archive_row(self, memo_id: str, title: str, preview: str) -> QFrame:
        """보관함 목록의 한 줄 위젯을 만듭니다."""
        c = self.colors
        row = QFrame()
        row.setObjectName("archiveRow")
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet(
            f"QFrame#archiveRow {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px; }}"
            f"QFrame#archiveRow:hover {{ border: 1px solid {c['accent']}; }}"
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(13, 10, 12, 10)
        layout.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(stroke_icon("archive", c["muted"], 16))
        icon.setFixedWidth(20)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        title_label = ElidedLabel(title or self.tr("detail.archive.untitled", "제목 없는 메모"))
        title_label.setObjectName("archiveMemoTitle")
        title_label.setFont(app_font(11, QFont.Bold))
        title_label.setStyleSheet(f"color: {c['text_soft']}; background: transparent;")
        preview_label = ElidedLabel(preview or self.tr("detail.archive.no_preview", "내용 없음"))
        preview_label.setObjectName("archiveMemoPreview")
        preview_label.setFont(app_font(8))
        preview_label.setStyleSheet(f"color: {c['muted2']}; background: transparent;")
        texts.addWidget(title_label)
        texts.addWidget(preview_label)
        delete_button = QPushButton()
        delete_button.setObjectName("archiveMemoDeleteButton")
        delete_button.setIcon(QIcon(stroke_icon("trash", c["muted"], 16)))
        delete_button.setFixedSize(30, 30)
        delete_button.setCursor(Qt.PointingHandCursor)
        delete_button.setToolTip(self.tr("detail.archive.delete", "메모 삭제"))
        delete_button.setStyleSheet(
            f"QPushButton#archiveMemoDeleteButton {{ background: transparent; border: none; border-radius: 7px; }}"
            f"QPushButton#archiveMemoDeleteButton:hover {{ background: {c['panel2']}; }}"
        )
        delete_button.clicked.connect(lambda _checked=False, mid=memo_id: self.delete_archived_memo(mid))
        layout.addWidget(icon)
        layout.addLayout(texts, 1)
        layout.addWidget(delete_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        row.mousePressEvent = lambda _event, mid=memo_id: self.open_archived_memo(mid)  # type: ignore[assignment]
        return row

    def open_archived_memo(self, memo_id: str) -> None:
        """보관된 항목에 연결된 메모를 엽니다."""
        opener = getattr(self.app, "open_memo", None)
        if opener is not None:
            opener(memo_id)

    def create_archive_memo(self) -> None:
        """보관 항목에 연결할 새 메모를 만듭니다."""
        creator = getattr(self.app, "create_memo", None)
        if creator is not None:
            creator()

    def delete_archived_memo(self, memo_id: str) -> None:
        """확인 후 메모 파일과 복원 메타데이터를 함께 삭제합니다."""
        answer = QMessageBox.question(
            self,
            APP_NAME,
            self.tr("detail.archive.delete.confirm", "이 메모를 삭제할까요? 삭제한 메모는 복구할 수 없습니다."),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        deleter = getattr(self.app, "delete_memo", None)
        if deleter is None:
            return
        deleter(memo_id)
        self.refresh_archive_view()
