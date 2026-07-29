"""허브(R4-1)의 빈 골격 섹션(Today/설정) 믹스인.

두 섹션 모두 아직 실제 콘텐츠가 없다 — 실이식은 각각 R4-5(Today)/R4-4(설정)에서
진행한다. 이 믹스인은 제목 + "곧 채워집니다" 자리표시자만 그리는 공용 골격을 제공해,
두 섹션이 사이드바에서 열리고 닫히는 경로(show_section, 지연 생성)를 지금 확정한다.

R4-3a: 알람 섹션은 `alarms_section.AlarmsSectionMixin`으로 실이식되어 더 이상 이
자리표시자를 쓰지 않는다(PLACEHOLDER_TITLES에서 제거).

REQUIRED attributes/메서드 (DetailScheduleWindow 코어가 제공):
- `self.colors`(dict), `self.section`(str)
- `self.tr(key, fallback, **kwargs)` (TrMixin)
- `self.icon_only_button(icon, handler)`, `self.close()` (layout.py DetailLayoutMixin)
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from chronofox.ui.app_ui import app_font

# kind -> (제목 번역 키, 제목 기본값). show_section()의 kind 어휘와 동일하다(H-D8).
PLACEHOLDER_TITLES: dict[str, tuple[str, str]] = {
    "today": ("detail.nav.today", "Today"),
    "settings": ("detail.nav.settings", "설정"),
}


class HubPlaceholderMixin:
    """Today/설정 빈 골격 섹션의 상단바·본문을 담당합니다."""

    def build_placeholder_top_bar(self) -> QHBoxLayout:
        """빈 골격 섹션의 상단 바(제목 + 닫기)를 구성합니다."""
        c = self.colors
        self.view_buttons = {}
        title_key, title_fallback = PLACEHOLDER_TITLES.get(self.section, ("detail.nav.today", "Today"))
        bar = QHBoxLayout()
        bar.setSpacing(12)
        title = QLabel(self.tr(title_key, title_fallback))
        title.setFont(app_font(15, QFont.Bold))
        title.setStyleSheet(f"color: {c['text']};")
        close_button = self.icon_only_button("close", self.close)
        bar.addWidget(title)
        bar.addStretch()
        bar.addWidget(close_button)
        return bar

    def build_placeholder_view(self) -> QWidget:
        """빈 골격 섹션의 본문("곧 채워집니다" 안내)을 구성합니다.

        지연 생성(H-D12) 검증용으로 `self.placeholder_view`에 자신을 남긴다 — build_ui()가
        매 재빌드마다 이 속성을 pop하므로, 현재 표시 중인 섹션이 아니면 존재하지 않는다.
        """
        c = self.colors
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        empty = QLabel(self.tr("detail.section.placeholder", "곧 채워집니다."))
        empty.setAlignment(Qt.AlignCenter)
        empty.setFont(app_font(11))
        empty.setStyleSheet(f"color: {c['muted2']};")
        layout.addWidget(empty)
        layout.addStretch()
        self.placeholder_view = container
        return container
