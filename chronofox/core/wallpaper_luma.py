"""P-3a 벽지 밝기 판정 순수 로직 + 벽지 취득 (W-D3/W-D4, `planning/PROJECT.md` §12-G).

이머시브 프리셋(`immersive`, P-3b에서 UI에 연결)의 "적응형 잉크"가 쓸 판정 엔진이다.
이 모듈은 Qt import 0(`todo_logic`/`holiday_country` 선례와 동일한 규약) — 화면 없이
pytest만으로 좌표 매핑·휘도·히스테리시스를 검증하기 위해서다.

두 계층으로 나뉜다:

1. **순수 판정** — `source_rect`(맞춤 방식별 좌표 매핑), `relative_luminance`(WCAG 상대
   휘도), `sample_stats`(평균·분산), `decide_ink`(히스테리시스가 있는 임계 판정). 전부
   결정적이고 OS·Qt에 의존하지 않는다.
2. **벽지 취득** — `detect_wallpaper()`가 `SPI_GETDESKWALLPAPER`(ctypes)와 레지스트리
   (`HKCU\\Control Panel\\Desktop`의 `WallpaperStyle`/`TileWallpaper`, 벽지가 없으면
   `HKCU\\Control Panel\\Colors\\Background`)를 읽는다. 실제 OS 호출(`_win32_*` 접두사
   함수)은 전부 개별적으로 예외를 삼키고(`holiday_country.detect_country_windows` 선례),
   `detect_wallpaper()` 자체도 한 번 더 감싸 이중 안전(W-D9)을 둔다. 테스트는 이 OS 호출
   함수들을 절대 실행하지 않는다 — `detect_wallpaper()`의 키워드 인자로 항상 가짜 콜백을
   주입한다.

**타일(tile) 방식의 반환 규약**: 타일은 화면 전체에 이미지가 반복되므로 위젯이 덮은 영역이
이미지 안의 단일 사각형으로 환원되지 않는다(위젯이 타일 경계를 넘나들 수 있음). 이 모듈은
`widget_rect`를 무시하고 **원본 이미지 전체(대표 타일 1장)를 표본 소스로 반환**한다 — 타일
패턴 자체가 반복 단위이므로 그 전체의 평균 밝기가 화면 어디를 봐도 통계적으로 대표성을
가지며, 위젯이 정확히 몇 개의 타일에 걸치는지 계산하는 것보다 훨씬 단순하고 안정적이다
(벽지가 바뀌지 않는 한 표본이 고정되어 히스테리시스와도 잘 맞는다).

**이미지 밖(레터박스) 처리**: `fit`처럼 화면보다 이미지가 작게 그려지는 방식에서 위젯이
그 여백에 걸치면, 대응하는 이미지 좌표도 이미지 경계 밖(음수 또는 이미지 크기 초과)이
된다. `source_rect`는 이 경우 이미지 경계와의 교집합으로 잘라내며, 교집합이 없으면
`(0.0, 0.0, 0.0, 0.0)`(면적 0)을 반환한다 — 호출부는 면적 0을 "이 위젯 영역은 표본을
얻을 수 없다"는 신호로 다뤄야 한다(예: 이전 판정 유지 또는 W-D9 기본값).

이미지 디코딩(Qt `QImage`)은 이 모듈의 일이 아니다 — `chronofox/ui/wallpaper_sampling.py`
(Qt 의존)가 얇은 어댑터로 픽셀을 뽑아 이 모듈의 `sample_stats`에 넘긴다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from statistics import pvariance
from typing import NamedTuple

__all__ = [
    "WALLPAPER_STYLES",
    "INK_LIGHT",
    "INK_DARK",
    "INK_THRESHOLD",
    "INK_HYSTERESIS",
    "WALLPAPER_SAMPLE_LONG_EDGE_PX",
    "SCRIM_VARIANCE_THRESHOLD",
    "FALLBACK_INK",
    "FALLBACK_SCRIM_ENABLED",
    "SampleStats",
    "WallpaperSample",
    "source_rect",
    "relative_luminance",
    "sample_stats",
    "decide_ink",
    "should_show_scrim",
    "scaled_size_for",
    "crop_scaled_pixels",
    "resolve_wallpaper_style",
    "detect_wallpaper",
]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수 (W-D5/W-D10)
# ---------------------------------------------------------------------------

#: Windows 벽지 맞춤 방식 6종. "tile"은 반복이라 별도 취급(모듈 docstring 참고).
WALLPAPER_STYLES = ("center", "tile", "stretch", "fit", "fill", "span")

INK_LIGHT = "light"  # 밝은 잉크 — 어두운 벽지 위에 쓴다
INK_DARK = "dark"  # 어두운 잉크 — 밝은 벽지 위에 쓴다

INK_THRESHOLD = 0.5  # W-D5
INK_HYSTERESIS = 0.06  # W-D5

WALLPAPER_SAMPLE_LONG_EDGE_PX = 256  # W-D10: 축소 샘플링 긴 변 기준

# W-D9: 벽지 취득이 실패하면 이 값으로 고정한다("밝은 잉크 + 스크림").
FALLBACK_INK = INK_LIGHT
FALLBACK_SCRIM_ENABLED = True

# W-D8: 표본 분산(모집단 분산, sample_stats 반환값)이 이 값을 넘으면 "혼합 밝기 벽지"로
# 보고 스크림 후보로 삼는다. 실측 근거가 없는(이 개발 기기에 벽지 이미지가 없다 —
# P-3a 알려진 한계 ①) 상황에서 손으로 고른 값이다: half/half 최고 대비(순백/순검
# 절반씩)의 모집단 분산은 0.25(sample_stats 테스트로 검증됨), 완만하게 섞인 두 영역
# (상대 휘도 0.3/0.7 절반씩, 여전히 육안으로 뚜렷이 밝기가 갈리는 벽지)은 0.04, 사진
# 벽지의 자연스러운 질감·그라데이션(하늘/그림자 등)은 대략 0.005~0.015 범위로
# 추정된다. 그 사이인 0.025를 임계로 잡아 "부드러운 사진 질감"은 스크림을 켜지 않고
# "뚜렷이 갈리는 두 영역"부터 켜지게 했다. 실기기에서 실제 벽지로 재보정이 필요하면
# 이 상수만 바꾸면 된다(호출부는 상수를 직접 참조하지 않고 should_show_scrim의
# 기본값으로만 쓴다).
SCRIM_VARIANCE_THRESHOLD = 0.025


# ---------------------------------------------------------------------------
# 좌표 매핑 (W-D3-①)
# ---------------------------------------------------------------------------


def _display_rect_for_style(
    wallpaper_size: tuple[float, float],
    screen_size: tuple[float, float],
    style: str,
) -> tuple[float, float, float, float]:
    """벽지 이미지가 화면 좌표계에서 실제로 그려지는 사각형을 계산합니다.

    "tile"은 반복이라 이 함수의 대상이 아니다(`source_rect`가 별도로 처리한다).
    이미지·화면 크기가 0 이하이면 면적 0 사각형을 반환한다.
    """
    img_w, img_h = wallpaper_size
    scr_w, scr_h = screen_size
    if img_w <= 0 or img_h <= 0 or scr_w <= 0 or scr_h <= 0:
        return (0.0, 0.0, 0.0, 0.0)

    if style == "center":
        w, h = float(img_w), float(img_h)
    elif style == "stretch":
        w, h = float(scr_w), float(scr_h)
    elif style == "fit":
        # 이미지 전체가 보이도록 종횡비를 유지한 채 화면 안에 들어가는 최대 크기
        # (더 짧은 쪽 배율을 쓴다) — 남는 축은 레터박스 여백이 된다.
        scale = min(scr_w / img_w, scr_h / img_h)
        w, h = img_w * scale, img_h * scale
    elif style in ("fill", "span"):
        # 화면을 완전히 덮도록 종횡비를 유지한 채 확대하는 최소 크기(더 큰 쪽 배율) —
        # 남는 축은 화면 밖으로 넘쳐 잘린다. span은 caller가 screen_size에 가상 데스크톱
        # 전체 크기를 넘긴다고 전제하면 fill과 수식이 동일하다(모듈 docstring 참고 없음,
        # 호출부 책임 — 이 함수는 두 스타일을 구분하지 않는다).
        scale = max(scr_w / img_w, scr_h / img_h)
        w, h = img_w * scale, img_h * scale
    else:
        raise ValueError(f"unsupported wallpaper style: {style!r}")

    x = (scr_w - w) / 2.0
    y = (scr_h - h) / 2.0
    return (x, y, w, h)


def source_rect(
    wallpaper_size: tuple[float, float],
    screen_size: tuple[float, float],
    style: str,
    widget_rect: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """위젯이 덮은 화면 영역이 벽지 이미지의 어느 사각형에 대응하는지 계산합니다.

    좌표계: `wallpaper_size`/`screen_size`는 (너비, 높이) 픽셀. `widget_rect`는
    (x, y, width, height) — 화면 좌상단(0, 0) 기준. 반환값도 같은 형태의 사각형이며
    벽지 이미지 좌상단(0, 0) 기준이다.

    - center/stretch/fit/fill/span: 화면 위 표시 사각형(`_display_rect_for_style`)을
      구한 뒤, widget_rect를 그 사각형 기준 상대 좌표로 바꿔 이미지 크기로 선형 스케일한다.
      이미지 경계를 벗어나는 부분(레터박스 여백에 걸친 경우 등)은 잘라내고, 교집합이
      없으면 면적 0 사각형을 반환한다(모듈 docstring 참고).
    - tile: widget_rect를 무시하고 이미지 전체 `(0, 0, img_w, img_h)`를 반환한다(대표
      타일 1장 규약).
    """
    img_w, img_h = wallpaper_size
    if style == "tile":
        return (0.0, 0.0, float(img_w), float(img_h))

    display_x, display_y, display_w, display_h = _display_rect_for_style(
        wallpaper_size, screen_size, style
    )
    if display_w <= 0 or display_h <= 0:
        return (0.0, 0.0, 0.0, 0.0)

    scale_x = img_w / display_w
    scale_y = img_h / display_h

    wx, wy, ww, wh = widget_rect
    rel_x = wx - display_x
    rel_y = wy - display_y
    img_x = rel_x * scale_x
    img_y = rel_y * scale_y
    img_w_out = ww * scale_x
    img_h_out = wh * scale_y

    x0 = max(0.0, img_x)
    y0 = max(0.0, img_y)
    x1 = min(float(img_w), img_x + img_w_out)
    y1 = min(float(img_h), img_y + img_h_out)
    if x1 <= x0 or y1 <= y0:
        return (0.0, 0.0, 0.0, 0.0)
    return (x0, y0, x1 - x0, y1 - y0)


# ---------------------------------------------------------------------------
# 휘도·통계·잉크 판정 (W-D3-②~④, W-D5)
# ---------------------------------------------------------------------------


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    """WCAG 2.x 상대 휘도. `rgb`는 0-255 범위 sRGB 3튜플(정수 또는 float).

    sRGB 감마를 역보정(linearize)한 뒤 0.2126/0.7152/0.0722로 가중합한다. 근사식이
    아니다 — 참고값: 흰색(255,255,255)=1.0, 검정(0,0,0)=0.0, 중간회색(128,128,128)
    ≈0.2159(테스트에서 재검증).
    """

    def _linearize(channel: float) -> float:
        c = channel / 255.0
        if c <= 0.03928:
            return c / 12.92
        return ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b)


class SampleStats(NamedTuple):
    """`sample_stats`의 반환값: 평균 상대 휘도와 그 모집단 분산."""

    mean_luma: float
    variance: float


def sample_stats(pixels: Sequence[tuple[float, float, float]]) -> SampleStats:
    """픽셀 시퀀스의 평균 상대 휘도와 분산을 계산합니다(W-D8 혼합 밝기 판정용).

    각 픽셀의 `relative_luminance`를 구한 뒤 모집단 평균·분산(`statistics.pvariance`)을
    반환한다 — 이미 축소 샘플링된 전체 픽셀 집합을 다루므로 표본 분산이 아니라 모집단
    분산이 맞다. 빈 시퀀스는 `SampleStats(0.0, 0.0)`을 반환한다(발생하면 안 되는 입력이지만
    예외로 판정 파이프라인을 죽이지 않는다).
    """
    if not pixels:
        return SampleStats(0.0, 0.0)
    lumas = [relative_luminance(p) for p in pixels]
    mean = sum(lumas) / len(lumas)
    variance = pvariance(lumas, mean) if len(lumas) > 1 else 0.0
    return SampleStats(mean, variance)


def decide_ink(
    mean_luma: float,
    *,
    previous: str | None = None,
    threshold: float = INK_THRESHOLD,
    hysteresis: float = INK_HYSTERESIS,
) -> str:
    """평균 휘도로 잉크(`INK_LIGHT`/`INK_DARK`)를 판정합니다(W-D5).

    기본 판정: `mean_luma > threshold`면 배경이 밝다는 뜻이므로 `INK_DARK`, 아니면
    `INK_DARK`(밝은 벽지)/`INK_LIGHT`(어두운 벽지) — 즉 밝으면 어두운 잉크, 어두우면
    밝은 잉크.

    히스테리시스: `previous`가 `INK_LIGHT`/`INK_DARK` 중 하나로 주어지고 `mean_luma`가
    `[threshold - hysteresis, threshold + hysteresis]` 데드밴드 안에 있으면 `previous`를
    그대로 반환한다 — 임계값 근처를 오가는 입력(벽지 슬라이드쇼 등)에서 잉크가 매번
    뒤집히는 것을 막는다. `previous`가 없으면(최초 판정) 데드밴드 없이 순수 임계 비교만
    쓴다.
    """
    if previous in (INK_LIGHT, INK_DARK) and (threshold - hysteresis) <= mean_luma <= (threshold + hysteresis):
        return previous
    return INK_DARK if mean_luma > threshold else INK_LIGHT


def should_show_scrim(
    variance: float,
    *,
    user_enabled: bool,
    threshold: float = SCRIM_VARIANCE_THRESHOLD,
) -> bool:
    """W-D8: 혼합 밝기 스크림을 실제로 켤지 판정합니다.

    기본은 OFF다 — `user_enabled`가 False(설정 기본값)면 분산이 얼마든 항상 False를
    반환한다("순수 v1"). 사용자가 설정에서 켰을 때만 표본 분산이 `threshold`를 넘는
    "혼합 밝기" 벽지에서 자동으로 스크림이 나타난다."""
    return bool(user_enabled) and variance > threshold


# ---------------------------------------------------------------------------
# 축소 샘플 크롭 (P-3b 오케스트레이션 보조) — source_rect가 원본 이미지 좌표계로 계산한
# 표본 사각형을, ui/wallpaper_sampling.load_wallpaper_sample이 이미 축소해 둔 픽셀
# 목록의 좌표계로 다시 스케일해 위젯이 실제로 덮은 부분만 골라낸다. Qt 의존 없이
# 순수하게 좌표 변환만 하므로 core/에 둔다(W-D3와 같은 계층).
# ---------------------------------------------------------------------------


def scaled_size_for(natural_size: tuple[int, int], long_edge: int) -> tuple[int, int]:
    """`ui.wallpaper_sampling.load_wallpaper_sample`이 QImage.scaled(KeepAspectRatio)로
    만드는 축소 크기를 원본 크기만으로 근사 재계산합니다(Qt 없이).

    최종 픽셀 1~2px 차이가 나더라도(반올림 방식 차이) 이 크기는 밝기 통계용 크롭 범위
    계산에만 쓰이므로 결과에 실질적 영향이 없다."""
    w, h = natural_size
    if w <= 0 or h <= 0:
        return (0, 0)
    if max(w, h) <= long_edge:
        return (int(w), int(h))
    scale = long_edge / max(w, h)
    return (max(1, round(w * scale)), max(1, round(h * scale)))


def crop_scaled_pixels(
    natural_size: tuple[int, int],
    scaled_size: tuple[int, int],
    pixels: Sequence[tuple[float, float, float]],
    crop_rect: tuple[float, float, float, float],
) -> list[tuple[float, float, float]]:
    """축소 샘플(`scaled_size`/`pixels`, 행 우선 평탄 목록)에서 원본 좌표계의
    `crop_rect`(`source_rect()`의 결과, `natural_size` 기준)에 대응하는 부분만 골라냅니다.

    `pixels`는 `scaled_size`와 같은 종횡비로 축소된 이미지의 행 우선(row-major) 픽셀
    목록이어야 합니다(`ui/wallpaper_sampling.load_wallpaper_sample`의 반환 형태). 결과가
    비면(면적 0, 범위 밖, 잘못된 입력) 빈 리스트를 반환합니다 — 호출부는 이 경우 축소
    이미지 전체를 대체로 써야 합니다."""
    nat_w, nat_h = natural_size
    scl_w, scl_h = scaled_size
    if nat_w <= 0 or nat_h <= 0 or scl_w <= 0 or scl_h <= 0:
        return []
    cx, cy, cw, ch = crop_rect
    if cw <= 0 or ch <= 0:
        return []
    scale_x = scl_w / nat_w
    scale_y = scl_h / nat_h
    x0 = max(0, int(cx * scale_x))
    y0 = max(0, int(cy * scale_y))
    x1 = min(scl_w, int((cx + cw) * scale_x) + 1)
    y1 = min(scl_h, int((cy + ch) * scale_y) + 1)
    if x1 <= x0 or y1 <= y0:
        return []
    expected_len = scl_w * scl_h
    if len(pixels) < expected_len:
        return []
    result: list[tuple[float, float, float]] = []
    for y in range(y0, y1):
        row_start = y * scl_w
        result.extend(pixels[row_start + x0 : row_start + x1])
    return result


# ---------------------------------------------------------------------------
# 벽지 취득 (W-D4/W-D9) — 실제 OS 접근과 순수 해석을 분리한다.
# ---------------------------------------------------------------------------

_SPI_GETDESKWALLPAPER = 0x0073
_MAX_PATH = 260

# 레지스트리 WallpaperStyle 코드 -> 맞춤 방식 문자열(실측/공식 문서 기준).
# TileWallpaper==1이면 이 매핑과 무관하게 "tile"이 우선한다(resolve_wallpaper_style).
_STYLE_CODE_TO_NAME: dict[int, str] = {
    0: "center",
    2: "stretch",
    6: "fit",
    10: "fill",
    22: "span",
}


def _win32_get_wallpaper_path() -> str | None:
    """`SystemParametersInfoW(SPI_GETDESKWALLPAPER, ...)`로 벽지 이미지 경로를 읽습니다.

    실패(호출 실패·빈 값)하면 None. 예외는 여기서 삼킨다 — 상위 `detect_wallpaper()`가
    한 번 더 감싸므로 이중 안전이지만, 이 함수 자체도 단독 호출에서 안전해야 한다
    (`holiday_country.detect_country_windows` 선례와 동일한 원칙).
    """
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(_MAX_PATH)
        ok = ctypes.windll.user32.SystemParametersInfoW(_SPI_GETDESKWALLPAPER, _MAX_PATH, buf, 0)
        if not ok:
            return None
        path = buf.value.strip()
        return path or None
    except Exception:
        _log.exception("SPI_GETDESKWALLPAPER failed")
        return None


def _win32_get_wallpaper_style_registry() -> tuple[int | None, int | None]:
    """`HKCU\\Control Panel\\Desktop`의 `WallpaperStyle`/`TileWallpaper`를 읽습니다.

    값이 없거나(키 없음) 정수로 해석할 수 없으면 `(None, None)`."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
            style_raw, _ = winreg.QueryValueEx(key, "WallpaperStyle")
            tile_raw, _ = winreg.QueryValueEx(key, "TileWallpaper")
        return int(style_raw), int(tile_raw)
    except Exception:
        _log.exception("WallpaperStyle/TileWallpaper registry read failed")
        return None, None


def _win32_get_background_color_registry() -> tuple[int, int, int] | None:
    """`HKCU\\Control Panel\\Colors\\Background`("R G B" 공백 구분 문자열)를 읽습니다.

    벽지가 없을 때(단색 배경) Windows가 쓰는 값이다. 실패하면 None."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Colors") as key:
            raw, _ = winreg.QueryValueEx(key, "Background")
        parts = str(raw).split()
        r, g, b = (int(p) for p in parts[:3])
        return (r, g, b)
    except Exception:
        _log.exception("Background color registry read failed")
        return None


def resolve_wallpaper_style(style_code: int | None, tile_code: int | None) -> str:
    """레지스트리 정수 코드를 `WALLPAPER_STYLES` 문자열로 해석합니다(순수 함수).

    `tile_code == 1`이면 `style_code`와 무관하게 `"tile"`을 반환한다 — Windows는 타일
    설정 시 `WallpaperStyle`을 보통 0(center)으로 남겨 두므로 타일이 우선한다. 모르는
    `style_code`(또는 None)는 Windows 10/11 기본값인 `"fill"`로 폴백한다.
    """
    if tile_code == 1:
        return "tile"
    return _STYLE_CODE_TO_NAME.get(style_code, "fill")


@dataclass(frozen=True)
class WallpaperSample:
    """`detect_wallpaper()`의 반환값.

    `kind`: "image"(벽지 이미지가 있음) / "solid"(단색 배경) / "unknown"(취득 실패,
    W-D9 기본값 적용 대상). `path`는 kind=="image"일 때만 의미 있고, `solid_rgb`는
    kind=="solid"일 때만 의미 있다. `style`은 kind=="image"일 때 `WALLPAPER_STYLES` 중
    하나이고, 그 외에는 임의값(사용하지 않음)이다.
    """

    kind: str
    path: str | None
    style: str
    solid_rgb: tuple[int, int, int] | None


_UNKNOWN_WALLPAPER_SAMPLE = WallpaperSample(kind="unknown", path=None, style="fill", solid_rgb=None)


def detect_wallpaper(
    *,
    get_wallpaper_path: Callable[[], str | None] = _win32_get_wallpaper_path,
    get_wallpaper_style_registry: Callable[[], tuple[int | None, int | None]] = _win32_get_wallpaper_style_registry,
    get_background_color_registry: Callable[[], tuple[int, int, int] | None] = _win32_get_background_color_registry,
) -> WallpaperSample:
    """현재 Windows 벽지 설정을 읽어 `WallpaperSample`로 돌려줍니다(W-D4/W-D9).

    화면 캡처를 쓰지 않는다 — 핀 모드 창이 최하단이라 캡처하면 자기 자신이나 다른 창이
    찍히기 때문이다(W-D4). 세 OS 접근 함수는 전부 키워드 인자로 주입 가능하다 — 테스트는
    항상 가짜 콜백을 넘겨 실제 ctypes/레지스트리를 절대 건드리지 않는다.

    순서: ① `get_wallpaper_path()`가 경로를 주면 스타일 레지스트리를 읽어 `"image"` 표본을
    만든다. ② 경로가 없으면 `get_background_color_registry()`로 단색 배경을 시도한다.
    ③ 그것도 없으면(또는 과정 중 어떤 예외든 발생하면) `"unknown"`을 반환한다 — 호출부는
    이 경우 `FALLBACK_INK`/`FALLBACK_SCRIM_ENABLED`를 그대로 쓰면 된다. 이 함수 자체는
    어떤 예외도 밖으로 던지지 않는다.
    """
    try:
        path = get_wallpaper_path()
        if path:
            style_code, tile_code = get_wallpaper_style_registry()
            style = resolve_wallpaper_style(style_code, tile_code)
            return WallpaperSample(kind="image", path=path, style=style, solid_rgb=None)

        color = get_background_color_registry()
        if color:
            return WallpaperSample(kind="solid", path=None, style="fill", solid_rgb=color)

        return _UNKNOWN_WALLPAPER_SAMPLE
    except Exception:
        _log.exception("wallpaper acquisition failed — falling back to W-D9 default")
        return _UNKNOWN_WALLPAPER_SAMPLE
