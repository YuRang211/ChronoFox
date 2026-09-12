"""Immutable toolbar geometry and a painter shared by icon buttons."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

ICON_CANVAS = (26, 24)
ICON_STROKE_WIDTH = 1.35


@dataclass(frozen=True)
class IconPrimitive:
    kind: Literal["line", "circle", "rounded_rect", "path", "ellipse"]
    coords: tuple[int | float, ...]
    fill: Literal["ink", "background"] | None = None


ICONS = MappingProxyType({
    "move": tuple(IconPrimitive("circle", (x, y, 1, 1)) for x in (9, 13, 17) for y in (7, 11, 15)),
    "prev": (IconPrimitive("line", (16, 7, 10, 12)), IconPrimitive("line", (10, 12, 16, 17))),
    "next": (IconPrimitive("line", (10, 7, 16, 12)), IconPrimitive("line", (16, 12, 10, 17))),
    "close": (IconPrimitive("line", (10, 8, 17, 16)), IconPrimitive("line", (17, 8, 10, 16))),
    "menu": tuple(IconPrimitive("line", (8, y, 19, y)) for y in (8, 12, 16)),
    "today": (
        IconPrimitive("rounded_rect", (7, 7, 13, 12, 2, 2)),
        IconPrimitive("line", (7, 11, 20, 11)),
        IconPrimitive("line", (11, 5, 11, 8)),
        IconPrimitive("line", (16, 5, 16, 8)),
    ),
    "settings": tuple(
        primitive
        for y, knob_x in ((7, 11), (12, 17), (17, 13))
        for primitive in (
            IconPrimitive("line", (7, y, 21, y)),
            IconPrimitive("circle", (knob_x, y, 2, 2), "background"),
        )
    ),
    "note": (
        IconPrimitive("path", (9, 5, 18, 5, 18, 14, 14, 19, 9, 19)),
        IconPrimitive("line", (14, 19, 14, 14)),
        IconPrimitive("line", (14, 14, 18, 14)),
    ),
    "preview": (
        IconPrimitive("ellipse", (6.5, 8.0, 15.0, 8.0)),
        IconPrimitive("circle", (14, 12, 2, 2), "ink"),
    ),
    "edit": (
        IconPrimitive("line", (8, 17, 17, 8)),
        IconPrimitive("line", (15, 6, 19, 10)),
        IconPrimitive("line", (8, 17, 7, 20)),
        IconPrimitive("line", (7, 20, 10, 19)),
    ),
})


def paint_icon(painter: QPainter, kind: str, ink: QColor, background: QColor) -> None:
    """Draw at the caller's origin; unknown kinds are blank and painter state is restored."""
    painter.save()
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(ink, ICON_STROKE_WIDTH)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        for primitive in ICONS.get(kind, ()):
            painter.setBrush(ink if primitive.fill == "ink" else background if primitive.fill == "background" else Qt.NoBrush)
            coords = primitive.coords
            # Preserve Qt's integer/float overloads and separate strokes: converting
            # every primitive to a path changes edge coverage and rounded endpoints.
            if primitive.kind == "line":
                painter.drawLine(*coords)
            elif primitive.kind == "circle":
                painter.drawEllipse(QPoint(*coords[:2]), *coords[2:])
            elif primitive.kind == "rounded_rect":
                painter.drawRoundedRect(QRect(*coords[:4]), *coords[4:])
            elif primitive.kind == "ellipse":
                painter.drawEllipse(QRectF(*coords))
            elif primitive.kind == "path":
                path = QPainterPath()
                path.moveTo(*coords[:2])
                for index in range(2, len(coords), 2):
                    path.lineTo(*coords[index:index + 2])
                path.closeSubpath()
                painter.drawPath(path)
    finally:
        painter.restore()
