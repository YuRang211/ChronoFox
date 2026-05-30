from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QComboBox, QPushButton, QWidget

from app_ui import app_font

class RoundedWindow(QWidget):
    """둥근 모서리와 드래그 이동을 공통으로 제공하는 기본 창입니다."""

    def __init__(self, colors: dict[str, str], radius: int = 14) -> None:
        super().__init__()
        self.colors = colors
        self.radius = radius
        self.drag_start: QPoint | None = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)
        painter.fillPath(path, QColor(self.colors["bg"]))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.grabMouse()

    def mouseMoveEvent(self, event) -> None:
        if self.drag_start is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_start)

    def mouseReleaseEvent(self, _event) -> None:
        if self.drag_start is not None:
            self.drag_start = None
            self.releaseMouse()

class IconButton(QPushButton):
    """이미지 파일 없이 QPainter로 그리는 작은 아이콘 버튼입니다."""

    def __init__(self, kind: str, colors: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.colors = colors
        self.setFixedSize(26, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.refresh_style()

    def refresh_style(self) -> None:
        self.setStyleSheet(
            "QPushButton { border: none; background: transparent; }"
            f"QPushButton:hover {{ background: {self.colors['panel2']}; border-radius: 5px; }}"
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self.colors["text"])
        pen = QPen(color, 1.35)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.translate((self.width() - 26) / 2, (self.height() - 24) / 2)

        if self.kind == "move":
            for x in (9, 13, 17):
                for y in (7, 11, 15):
                    painter.drawEllipse(QPoint(x, y), 1, 1)
        elif self.kind == "prev":
            painter.drawLine(16, 7, 10, 12)
            painter.drawLine(10, 12, 16, 17)
        elif self.kind == "next":
            painter.drawLine(10, 7, 16, 12)
            painter.drawLine(16, 12, 10, 17)
        elif self.kind == "close":
            painter.drawLine(10, 8, 17, 16)
            painter.drawLine(17, 8, 10, 16)
        elif self.kind == "menu":
            for y in (8, 12, 16):
                painter.drawLine(8, y, 19, y)
        elif self.kind == "today":
            painter.drawRoundedRect(QRect(8, 6, 12, 12), 2, 2)
            painter.drawLine(8, 10, 20, 10)
            painter.setBrush(color)
            painter.drawEllipse(QPoint(14, 14), 2, 2)
            painter.setBrush(Qt.NoBrush)
        elif self.kind == "settings":
            for y, knob_x in ((7, 11), (12, 17), (17, 13)):
                painter.drawLine(7, y, 21, y)
                painter.setBrush(QColor(self.colors["bg"]))
                painter.drawEllipse(QPoint(knob_x, y), 2, 2)
                painter.setBrush(Qt.NoBrush)
        elif self.kind == "note":
            path = QPainterPath()
            path.moveTo(9, 5)
            path.lineTo(18, 5)
            path.lineTo(18, 14)
            path.lineTo(14, 19)
            path.lineTo(9, 19)
            path.closeSubpath()
            painter.drawPath(path)
            painter.drawLine(14, 19, 14, 14)
            painter.drawLine(14, 14, 18, 14)
        elif self.kind == "preview":
            eye = QRectF(6.5, 8.0, 15.0, 8.0)
            painter.drawEllipse(eye)
            painter.setBrush(color)
            painter.drawEllipse(QPoint(14, 12), 2, 2)
        elif self.kind == "edit":
            painter.drawLine(8, 17, 17, 8)
            painter.drawLine(15, 6, 19, 10)
            painter.drawLine(8, 17, 7, 20)
            painter.drawLine(7, 20, 10, 19)

class ArrowComboBox(QComboBox):
    """Qt 스타일시트 대신 직접 아래 화살표를 그리는 콤보박스입니다."""

    def __init__(self, colors: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.colors = colors

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(self.colors["muted"]))
        painter.setFont(app_font(8, QFont.Bold))
        painter.drawText(QRect(self.width() - 28, 0, 20, self.height()), Qt.AlignCenter, "▼")

class Switch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked: bool, colors: dict[str, str]) -> None:
        super().__init__()
        self.checked = checked
        self.colors = colors
        self.setFixedSize(42, 24)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.checked = not self.checked
            self.toggled.emit(self.checked)
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = QColor(self.colors["accent"] if self.checked else self.colors["panel2"])
        painter.setBrush(track)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 12, 12)
        painter.setBrush(QColor("white" if self.checked else self.colors["muted"]))
        x = 22 if self.checked else 4
        painter.drawEllipse(QRect(x, 5, 14, 14))

class ThemeButton(QPushButton):
    def __init__(self, mode: str, label: str, colors: dict[str, str]) -> None:
        super().__init__()
        self.mode = mode
        self.label = label
        self.colors = colors
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self.setFixedWidth({"light": 108, "dark": 96, "system": 84}[mode])
        self.setStyleSheet("QPushButton { border: none; background: transparent; }")

    def paintEvent(self, _event) -> None:
        c = self.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 2, -1, -2)

        if self.isChecked() or self.underMouse():
            painter.setPen(QPen(QColor(c["border"]), 1 if self.isChecked() else 0))
            painter.setBrush(QColor(c["panel2"]))
            painter.drawRoundedRect(rect, 10, 10)

        icon_color = QColor(c["text"] if self.isChecked() else c["muted"])
        text_color = QColor(c["text"] if self.isChecked() else c["muted"])
        self.draw_icon(painter, icon_color)

        painter.setPen(text_color)
        painter.setFont(app_font(9, QFont.Bold))
        painter.drawText(QRect(31, 0, self.width() - 34, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.label)

    def draw_icon(self, painter: QPainter, color: QColor) -> None:
        pen = QPen(color, 1.15)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        if self.mode == "light":
            center = QPoint(16, 15)
            painter.drawEllipse(center, 3, 3)
            for x1, y1, x2, y2 in (
                (16, 6, 16, 8),
                (16, 22, 16, 24),
                (7, 15, 9, 15),
                (23, 15, 25, 15),
                (10, 9, 12, 11),
                (20, 19, 22, 21),
                (10, 21, 12, 19),
                (20, 11, 22, 9),
            ):
                painter.drawLine(x1, y1, x2, y2)
        elif self.mode == "dark":
            moon = QPainterPath()
            moon.addEllipse(QRectF(10.5, 8.0, 11.0, 14.0))
            cut = QPainterPath()
            cut.addEllipse(QRectF(15.0, 6.5, 10.5, 15.0))
            painter.fillPath(moon.subtracted(cut), color)
        elif self.mode == "system":
            painter.drawRoundedRect(QRect(9, 10, 15, 10), 2, 2)
            painter.drawLine(12, 20, 21, 20)
            painter.drawLine(16, 20, 16, 23)
            painter.drawLine(13, 23, 19, 23)

