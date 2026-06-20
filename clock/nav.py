from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QToolButton

from app_ui import app_font
from PySide6.QtGui import QFont

class ClockNavButton(QToolButton):
    """Bottom navigation item styled after the exported clock widget."""

    def __init__(self, icon: str, label: str, colors: dict[str, str]) -> None:
        super().__init__()
        self.icon_name = icon
        self.label = label
        self.colors = colors
        self.active = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(62)
        self.setText(label)
        self.setIconSize(QSize(26, 26))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setFont(app_font(9, QFont.Medium))
        self.refresh_style()

    def set_active(self, active: bool) -> None:
        if self.active == active:
            return
        self.active = active
        self.refresh_style()

    def refresh_style(self) -> None:
        c = self.colors
        fg = c["accent"] if self.active else c["muted"]
        self.setIcon(self.nav_icon(fg))
        active_bg = c.get("accent_soft", c["panel2"]) if self.active else "transparent"
        self.setStyleSheet(
            f"QToolButton {{ background: {active_bg}; color: {fg}; border: none; border-radius: 16px; "
            "padding: 5px 3px; font-weight: 600; }}"
            f"QToolButton:hover {{ background: {c['panel2']}; color: {c['accent']}; }}"
        )

    def nav_icon(self, color_text: str) -> QIcon:
        pixmap = QPixmap(28, 28)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(color_text)
        pen = QPen(color, 2.1)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        cx, cy = 14, 14
        if self.icon_name == "clock":
            painter.drawEllipse(QRect(cx - 8, cy - 8, 16, 16))
            painter.drawLine(cx, cy, cx, cy - 5)
            painter.drawLine(cx, cy, cx + 4, cy + 3)
        elif self.icon_name == "timer":
            painter.drawEllipse(QRect(cx - 8, cy - 5, 16, 16))
            painter.drawLine(cx - 4, cy - 11, cx + 4, cy - 11)
            painter.drawLine(cx, cy - 11, cx, cy - 7)
            painter.drawLine(cx + 6, cy - 8, cx + 9, cy - 11)
            painter.drawLine(cx, cy + 3, cx, cy - 3)
            painter.drawLine(cx, cy + 3, cx + 4, cy + 1)
        elif self.icon_name == "hourglass":
            path = QPainterPath()
            path.moveTo(cx - 7, cy - 10)
            path.lineTo(cx + 7, cy - 10)
            path.lineTo(cx + 2, cy)
            path.lineTo(cx + 7, cy + 10)
            path.lineTo(cx - 7, cy + 10)
            path.lineTo(cx - 2, cy)
            path.closeSubpath()
            painter.drawPath(path)
            painter.drawLine(cx - 4, cy - 5, cx + 4, cy - 5)
            painter.drawLine(cx - 4, cy + 6, cx + 4, cy + 6)
        elif self.icon_name == "alarm":
            painter.drawEllipse(QRect(cx - 8, cy - 5, 16, 16))
            painter.drawLine(cx, cy + 3, cx, cy - 2)
            painter.drawLine(cx, cy + 3, cx + 4, cy + 2)
            painter.drawArc(QRect(cx - 13, cy - 12, 9, 9), 35 * 16, 120 * 16)
            painter.drawArc(QRect(cx + 4, cy - 12, 9, 9), 25 * 16, 120 * 16)
            painter.drawLine(cx - 5, cy + 12, cx - 8, cy + 15)
            painter.drawLine(cx + 5, cy + 12, cx + 8, cy + 15)
        painter.end()
        return QIcon(pixmap)
