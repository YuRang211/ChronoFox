"""이머시브 프리셋의 벽지 판독과 적응형 잉크 갱신을 조정합니다.

벽지·창 위치·크기·화면 변경 이벤트만 단발 타이머로 디바운스하며 폴링하지 않습니다.
휘도 판정과 이미지 디코딩은 각각 core와 UI 어댑터에 위임합니다.
"""

from __future__ import annotations

import ctypes.wintypes as wintypes
import logging
from collections.abc import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, QTimer

from chronofox.core.wallpaper_luma import (
    FALLBACK_INK,
    FALLBACK_SCRIM_ENABLED,
    WALLPAPER_SAMPLE_LONG_EDGE_PX,
    WallpaperSample,
    crop_scaled_pixels,
    decide_ink,
    detect_wallpaper,
    relative_luminance,
    sample_stats,
    scaled_size_for,
    should_show_scrim,
    source_rect,
)
from chronofox.ui.app_styles import normalized_calendar_style
from chronofox.ui.app_theme import resolve_immersive_ink
from chronofox.ui.wallpaper_sampling import load_wallpaper_sample

logger = logging.getLogger(__name__)

WM_SETTINGCHANGE = 0x001A
_RECALC_DEBOUNCE_MS = 200

LoadSampleFn = Callable[[str], tuple[tuple[int, int], list[tuple[int, int, int]]] | None]


class _SettingChangeFilter(QAbstractNativeEventFilter):
    """벽지 변경을 포함한 WM_SETTINGCHANGE를 감지합니다.

    `windows/global_hotkey.py`의 `_HotkeyNativeFilter`와 같은 패턴 — 특정 창 핸들에
    바인딩하지 않고 앱 전역 네이티브 이벤트 필터로 수신해야 창 재생성(핀 모드 등)과
    무관하게 항상 잡힌다."""

    def __init__(self, owner: ImmersiveInkController) -> None:
        super().__init__()
        self._owner = owner

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt 오버라이드 시그니처
        try:
            msg = wintypes.MSG.from_address(int(message))
        except Exception:  # pragma: no cover - 플랫폼별 message 표현 차이 방어
            return False, 0
        if msg.message == WM_SETTINGCHANGE:
            self._owner.request_recalc("wallpaper_setting_change")
        return False, 0


class ImmersiveInkController(QObject):
    """이머시브 프리셋의 적응형 잉크 상태를 소유하고 재계산을 오케스트레이션한다.

    ``app``는 FoxCalendarApp — ``store``/``cell_style``/``geometry()``/``screen()``만
    duck-typing으로 쓴다. 벽지 취득(``detect_wallpaper_fn``)과 이미지 샘플링
        (``load_sample_fn``)은 테스트에서 주입해 실제 OS와 이미지 디코더 접근을 피할 수 있습니다."""

    def __init__(
        self,
        app,
        *,
        detect_wallpaper_fn: Callable[..., WallpaperSample] = detect_wallpaper,
        load_sample_fn: LoadSampleFn = load_wallpaper_sample,
        install_native_filter: bool = True,
    ) -> None:
        super().__init__(app)
        self.app = app
        self._detect_wallpaper = detect_wallpaper_fn
        self._load_sample = load_sample_fn
        self.ink_kind: str = FALLBACK_INK
        self.last_variance: float = 0.0
        self._computed_once = False
        self._last_failed = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self.recompute)
        self._filter: _SettingChangeFilter | None = None
        if install_native_filter:
            self._filter = _SettingChangeFilter(self)
            qt_app = QCoreApplication.instance()
            if qt_app is not None:
                qt_app.installNativeEventFilter(self._filter)

    # 트리거

    def is_active_style(self) -> bool:
        """현재 프리셋이 이머시브인지 반환합니다."""
        return normalized_calendar_style(self.app.store) == "immersive"

    def request_recalc(self, _reason: str) -> None:
        """벽지 변경·화면 변경 트리거. 이벤트가 겹쳐 들어올 수 있으므로 디바운스
        타이머를 (재)시작만 한다 — 즉시 계산하지 않는다."""
        if not self.is_active_style():
            return
        self._debounce.start(_RECALC_DEBOUNCE_MS)

    def request_recalc_debounced(self, _reason: str) -> None:
        """창 이동/리사이즈 트리거 — 짧은 시간에 여러 번 연속 발화하므로 매번 타이머를
        재시작해 마지막 이벤트로부터 일정 시간 뒤 단 한 번만 재계산한다(폴링이 아니다:
        이 메서드가 호출되지 않으면 타이머는 절대 시작되지 않는다)."""
        if not self.is_active_style():
            return
        self._debounce.start(_RECALC_DEBOUNCE_MS)

    def ensure_computed_once(self) -> None:
        """첫 표시 뒤 아직 계산하지 않았을 때만 한 번 계산합니다."""
        if not self.is_active_style() or self._computed_once:
            return
        self.recompute()

    # 계산

    def recompute(self) -> None:
        """벽지를 다시 읽고 판정한 잉크를 현재 셀 스타일에 반영합니다."""
        if not self.is_active_style():
            return
        self._computed_once = True
        mean_luma, variance, failed = self._sample_wallpaper()
        self._last_failed = failed
        if failed:
            # 실패 시 이전 히스테리시스 상태를 버리고 결정적인 기본 잉크로 돌아간다.
            self.ink_kind = FALLBACK_INK
            self.last_variance = 0.0
        else:
            self.ink_kind = decide_ink(mean_luma, previous=self.ink_kind)
            self.last_variance = variance
        self._apply()

    def reapply_if_computed(self) -> None:
        """build_ui()가 `calendar_cell_style()`로 cell_style dict를 새로 만들 때마다
        (프리셋 전환·테마 재적용) 호출한다 — 새 dict는 항상 FALLBACK_INK 기본값에서
        시작하므로, 이미 한 번 계산해 둔 값이 있으면 즉시 덮어써 재계산 없이 최신
        판정을 유지한다(벽지를 다시 읽지 않는다 — 값만 재적용). 이머시브가 아닌
        프리셋으로 build_ui()가 불렸을 때는 그 프리셋의 cell_style을 이머시브 잉크로
        오염시키면 안 되므로 아무 것도 하지 않습니다."""
        if self._computed_once and self.is_active_style():
            self._apply()

    def apply_scrim_setting(self) -> None:
        """구버전 호출 호환: 벽지를 다시 읽지 않고 자동 스크림 판정을 재적용합니다."""
        self._apply()

    def _sample_wallpaper(self) -> tuple[float, float, bool]:
        """반환: (평균 상대 휘도, 분산, 취득/디코딩 실패 여부)."""
        sample = self._safe_detect_wallpaper()
        if sample.kind == "image" and sample.path:
            loaded = self._load_sample(sample.path)
            if loaded is None:
                return 0.0, 0.0, True
            natural_size, pixels = loaded
            pixels_to_use = pixels
            widget_rect = self._widget_rect()
            screen_size = self._screen_size()
            if widget_rect is not None and screen_size is not None:
                try:
                    crop = source_rect(natural_size, screen_size, sample.style, widget_rect)
                    # load_wallpaper_sample()은 원본을 WALLPAPER_SAMPLE_LONG_EDGE_PX로
                    # 축소한다 — 여기서도 같은 기준으로 축소 크기를 재계산해야
                    # crop_scaled_pixels의 좌표 스케일이 실제 pixels 목록과 맞는다.
                    scaled_size = scaled_size_for(natural_size, WALLPAPER_SAMPLE_LONG_EDGE_PX)
                    cropped = crop_scaled_pixels(natural_size, scaled_size, pixels, crop)
                    if cropped:
                        pixels_to_use = cropped
                except Exception:
                    logger.exception("immersive ink: crop failed, falling back to whole sample")
            mean, variance = sample_stats(pixels_to_use)
            return mean, variance, False
        if sample.kind == "solid" and sample.solid_rgb:
            return relative_luminance(sample.solid_rgb), 0.0, False
        return 0.0, 0.0, True

    def _apply(self) -> None:
        ink_tokens = resolve_immersive_ink(self.ink_kind)
        scrim_active = (
            FALLBACK_SCRIM_ENABLED if self._last_failed else should_show_scrim(self.last_variance, user_enabled=True)
        )
        cell_style = getattr(self.app, "cell_style", None)
        if isinstance(cell_style, dict):
            cell_style.update(ink_tokens)
            cell_style["scrim_active"] = scrim_active
        on_applied = getattr(self.app, "on_immersive_ink_applied", None)
        if callable(on_applied):
            on_applied()

    def _safe_detect_wallpaper(self) -> WallpaperSample:
        try:
            return self._detect_wallpaper()
        except Exception:
            logger.exception("immersive ink: wallpaper detection failed")
            return WallpaperSample(kind="unknown", path=None, style="fill", solid_rgb=None)

    def _widget_rect(self) -> tuple[float, float, float, float] | None:
        try:
            geo = self.app.geometry()
            return (float(geo.x()), float(geo.y()), float(geo.width()), float(geo.height()))
        except Exception:
            return None

    def _screen_size(self) -> tuple[float, float] | None:
        try:
            screen = self.app.screen()
            if screen is None:
                return None
            geo = screen.geometry()
            return (float(geo.width()), float(geo.height()))
        except Exception:
            return None
