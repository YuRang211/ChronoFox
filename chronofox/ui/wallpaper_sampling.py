"""P-3a 벽지 이미지 축소 샘플링 어댑터 (Qt 의존).

`chronofox/core/wallpaper_luma.py`는 좌표 매핑·휘도·잉크 판정을 Qt 없이 순수 함수로
제공하지만, 실제 벽지 이미지 파일을 열고 픽셀을 읽는 일은 이미지 디코더가 필요하다.
그 디코더가 Qt `QImage`이므로 이 얇은 어댑터는 core/의 Qt-free 규약을 지키기 위해
`ui/`에 둔다 — `core/` 안에서 Qt import는 금지지만(`todo_logic`/`holiday_country` 선례),
이 파일은 애초에 `core/`가 다루지 않기로 한 "이미지 디코딩" 그 자체를 담당한다.

W-D10: 원본을 그대로 읽지 않고 긴 변 `WALLPAPER_SAMPLE_LONG_EDGE_PX`(256)px로 축소한 뒤
픽셀을 뽑는다 — 4K 벽지를 매번 풀 해상도로 읽지 않기 위해서다.
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

    실패(경로 없음·파일 없음·포맷 불가 등)하면 예외를 던지지 않고 None을 반환한다 —
    W-D9와 같은 실패-안전 정신을 어댑터 경계에도 적용한다. 호출부는 None을 받으면
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
