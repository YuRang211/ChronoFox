from __future__ import annotations

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QToolButton

from app_ui import app_font
from PySide6.QtGui import QFont


ALARM_ICON_SVG = """<svg width="22" height="20" viewBox="0 0 22 20" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M10.65 19.65C9.4 19.65 8.22917 19.4125 7.1375 18.9375C6.04583 18.4625 5.09583 17.8208 4.2875 17.0125C3.47917 16.2042 2.8375 15.2542 2.3625 14.1625C1.8875 13.0708 1.65 11.9 1.65 10.65C1.65 9.4 1.8875 8.22917 2.3625 7.1375C2.8375 6.04583 3.47917 5.09583 4.2875 4.2875C5.09583 3.47917 6.04583 2.8375 7.1375 2.3625C8.22917 1.8875 9.4 1.65 10.65 1.65C11.9 1.65 13.0708 1.8875 14.1625 2.3625C15.2542 2.8375 16.2042 3.47917 17.0125 4.2875C17.8208 5.09583 18.4625 6.04583 18.9375 7.1375C19.4125 8.22917 19.65 9.4 19.65 10.65C19.65 11.9 19.4125 13.0708 18.9375 14.1625C18.4625 15.2542 17.8208 16.2042 17.0125 17.0125C16.2042 17.8208 15.2542 18.4625 14.1625 18.9375C13.0708 19.4125 11.9 19.65 10.65 19.65ZM13.45 14.85L14.85 13.45L11.65 10.25V5.65H9.65V11.05L13.45 14.85ZM4.25 0L5.65 1.4L1.4 5.65L0 4.25L4.25 0ZM17.05 0L21.3 4.25L19.9 5.65L15.65 1.4L17.05 0ZM10.65 17.65C12.6 17.65 14.2542 16.9708 15.6125 15.6125C16.9708 14.2542 17.65 12.6 17.65 10.65C17.65 8.7 16.9708 7.04583 15.6125 5.6875C14.2542 4.32917 12.6 3.65 10.65 3.65C8.7 3.65 7.04583 4.32917 5.6875 5.6875C4.32917 7.04583 3.65 8.7 3.65 10.65C3.65 12.6 4.32917 14.2542 5.6875 15.6125C7.04583 16.9708 8.7 17.65 10.65 17.65Z" fill="{color}"/>
</svg>"""


STOPWATCH_ICON_SVG = """<svg width="18" height="21" viewBox="0 0 18 21" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M6 2V0H12V2H6ZM8 13H10V7H8V13ZM9 21C7.76667 21 6.60417 20.7625 5.5125 20.2875C4.42083 19.8125 3.46667 19.1667 2.65 18.35C1.83333 17.5333 1.1875 16.5792 0.7125 15.4875C0.2375 14.3958 0 13.2333 0 12C0 10.7667 0.2375 9.60417 0.7125 8.5125C1.1875 7.42083 1.83333 6.46667 2.65 5.65C3.46667 4.83333 4.42083 4.1875 5.5125 3.7125C6.60417 3.2375 7.76667 3 9 3C10.0333 3 11.025 3.16667 11.975 3.5C12.925 3.83333 13.8167 4.31667 14.65 4.95L16.05 3.55L17.45 4.95L16.05 6.35C16.6833 7.18333 17.1667 8.075 17.5 9.025C17.8333 9.975 18 10.9667 18 12C18 13.2333 17.7625 14.3958 17.2875 15.4875C16.8125 16.5792 16.1667 17.5333 15.35 18.35C14.5333 19.1667 13.5792 19.8125 12.4875 20.2875C11.3958 20.7625 10.2333 21 9 21ZM9 19C10.9333 19 12.5833 18.3167 13.95 16.95C15.3167 15.5833 16 13.9333 16 12C16 10.0667 15.3167 8.41667 13.95 7.05C12.5833 5.68333 10.9333 5 9 5C7.06667 5 5.41667 5.68333 4.05 7.05C2.68333 8.41667 2 10.0667 2 12C2 13.9333 2.68333 15.5833 4.05 16.95C5.41667 18.3167 7.06667 19 9 19Z" fill="{color}"/>
</svg>"""


HOURGLASS_ICON_SVG = """<svg width="16" height="20" viewBox="0 0 16 20" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M4 18H12V15C12 13.9 11.6083 12.9583 10.825 12.175C10.0417 11.3917 9.1 11 8 11C6.9 11 5.95833 11.3917 5.175 12.175C4.39167 12.9583 4 13.9 4 15V18ZM8 9C9.1 9 10.0417 8.60833 10.825 7.825C11.6083 7.04167 12 6.1 12 5V2H4V5C4 6.1 4.39167 7.04167 5.175 7.825C5.95833 8.60833 6.9 9 8 9ZM0 20V18H2V15C2 13.9833 2.2375 13.0292 2.7125 12.1375C3.1875 11.2458 3.85 10.5333 4.7 10C3.85 9.46667 3.1875 8.75417 2.7125 7.8625C2.2375 6.97083 2 6.01667 2 5V2H0V0H16V2H14V5C14 6.01667 13.7625 6.97083 13.2875 7.8625C12.8125 8.75417 12.15 9.46667 11.3 10C12.15 10.5333 12.8125 11.2458 13.2875 12.1375C13.7625 13.0292 14 13.9833 14 15V18H16V20H0Z" fill="{color}"/>
</svg>"""


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
            svg = STOPWATCH_ICON_SVG.format(color=color.name())
            renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            renderer.render(painter, QRectF(5, 3, 18, 21))
        elif self.icon_name == "hourglass":
            svg = HOURGLASS_ICON_SVG.format(color=color.name())
            renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            renderer.render(painter, QRectF(6, 4, 16, 20))
        elif self.icon_name == "alarm":
            svg = ALARM_ICON_SVG.format(color=color.name())
            renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            renderer.render(painter, QRectF(3, 4, 22, 20))
        painter.end()
        return QIcon(pixmap)
