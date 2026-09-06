"""Qt 기반 벽지 이미지 축소 샘플링 어댑터입니다.

이미지 디코딩만 Qt에 맡기고 좌표·휘도 판정은 core의 순수 함수에 둡니다. 큰 벽지는
긴 변 기준으로 축소해 전체 해상도 픽셀 순회를 피합니다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from chronofox.core.wallpaper_luma import WALLPAPER_SAMPLE_LONG_EDGE_PX

__all__ = ["load_wallpaper_sample"]


def load_wallpaper_sample(
    path: str, *, long_edge: int = WALLPAPER_SAMPLE_LONG_EDGE_PX
) -> tuple[tuple[int, int], list[tuple[int, int, int]]] | None:
    """벽지 이미지 파일을 열어 `(원본 크기, 축소 샘플 픽셀 목록)`을 반환합니다.

    원본 크기는 `wallpaper_luma.source_rect`의 `wallpaper_size` 인자에 그대로 쓸 수 있게
    축소 전 크기다(좌표 매핑은 항상 원본 이미지 좌표계를 기준으로 하므로). 픽셀 목록은
    축소된 이미지에서 뽑은 것이고, `wallpaper_luma.sample_stats`에 바로 넘길 수 있는
    `(r, g, b)` 튜플 시퀀스다.

    실패하면 예외를 던지지 않고 None을 반환합니다. 호출부는 None을 받으면
    `wallpaper_luma.FALLBACK_INK`/`FALLBACK_SCRIM_ENABLED`로 폴백해야 한다.
    """
    try:
        image = QImage(path)
        if image.isNull():
            return None
        natural_size = (image.width(), image.height())
        if natural_size[0] <= 0 or natural_size[1] <= 0:
            return None

        if max(natural_size) > long_edge:
            scaled = image.scaled(
                long_edge,
                long_edge,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            scaled = image
        scaled = scaled.convertToFormat(QImage.Format.Format_RGB888)

        width, height = scaled.width(), scaled.height()
        pixels: list[tuple[int, int, int]] = []
        for y in range(height):
            for x in range(width):
                color = scaled.pixelColor(x, y)
                pixels.append((color.red(), color.green(), color.blue()))
        if not pixels:
            return None
        return natural_size, pixels
    except Exception:
        return None
