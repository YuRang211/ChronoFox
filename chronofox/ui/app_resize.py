"""마우스 드래그로 창 가장자리를 잡아 크기를 조절하는 공용 ResizeHandle 위젯."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QWidget


class ResizeHandle(QWidget):
    """Small bottom-right resize affordance that stays aligned above child widgets."""

    def __init__(self, colors: dict[str, str], parent: QWidget) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setFixedSize(18, 18)
        self.setCursor(Qt.SizeFDiagCursor)

    def mousePressEvent(self, event) -> None:
        parent = self.parent()
        if event.button() != Qt.LeftButton or not hasattr(parent, "begin_resize"):
            return
        # P-D1: 핀 모드 중인 메인 창은 리사이즈도 막는다(RoundedWindow.drag_locked
        # 훅 — 다른 창은 기본 False라 이 가드가 실질적으로 아무것도 바꾸지 않는다).
        if getattr(parent, "drag_locked", lambda: False)():
            return
        parent.begin_resize(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        parent = self.parent()
        if event.buttons() & Qt.LeftButton and hasattr(parent, "update_resize"):
            parent.update_resize(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, _event) -> None:
        parent = self.parent()
        if hasattr(parent, "end_resize"):
            parent.end_resize()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self.colors.get("muted", "#64748B"))
        color.setAlpha(135)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        step = 4
        for row in range(3):
            for col in range(2 - row, 3):
                painter.drawEllipse(QPoint(6 + col * step, 6 + row * step), 1.1, 1.1)
