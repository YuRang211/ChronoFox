"""마우스 드래그로 창 가장자리를 잡아 크기를 조절하는 공용 ResizeHandle 위젯."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QWidget


class CornerResizeHandle(QWidget):
    """논리 좌표로 반대편 모서리를 고정하며 크기를 바꾸는 투명 입력 영역."""

    def __init__(self, corner: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.corner = corner
        self.start: QPoint | None = None
        self.origin = QRect()
        self.setFixedSize(18, 18)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setCursor(Qt.SizeFDiagCursor if corner in ('top_left', 'bottom_right') else Qt.SizeBDiagCursor)

    def cancel_drag(self) -> None:
        self.start = None
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()

    def paintEvent(self, _event) -> None:
        # Windows layered 창은 alpha=0 픽셀의 마우스 입력을 뒤 창으로 통과시킨다.
        # 이머시브에서도 잡히도록 육안으로 보이지 않는 입력 표면만 남긴다.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))

    def hideEvent(self, event) -> None:
        self.cancel_drag()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self.parentWidget().drag_locked():
            return
        self.start = event.globalPosition().toPoint()
        self.origin = self.parentWidget().geometry()
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        parent = self.parentWidget()
        if parent.drag_locked():
            self.cancel_drag()
            return
        if self.start is None or not event.buttons() & Qt.LeftButton:
            return
        delta = event.globalPosition().toPoint() - self.start
        left = self.corner.endswith('left')
        top = self.corner.startswith('top')
        width = max(parent.minimumWidth(), self.origin.width() + (-delta.x() if left else delta.x()))
        height = max(parent.minimumHeight(), self.origin.height() + (-delta.y() if top else delta.y()))
        width = min(parent.maximumWidth(), max(1, width))
        height = min(parent.maximumHeight(), max(1, height))
        x = self.origin.x() + self.origin.width() - width if left else self.origin.x()
        y = self.origin.y() + self.origin.height() - height if top else self.origin.y()
        parent.setGeometry(x, y, width, height)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self.cancel_drag()
        event.accept()


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
        # 핀 모드는 위치뿐 아니라 크기도 고정해야 바탕화면 배치가 유지된다.
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
