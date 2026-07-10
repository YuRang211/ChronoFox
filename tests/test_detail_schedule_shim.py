"""S3P2(M4) 재수출 shim 검증.

detail_schedule_window.py는 detail_schedule/ 패키지로 분할됐다(D7). 이 테스트는 기존
`from detail_schedule_window import DetailScheduleWindow` 호출부가 패키지 직접 import와
동일한 클래스를 가리키는지 확인한다 — 창을 실제로 띄우지 않으므로 fast lane에 남긴다.
"""

from __future__ import annotations


def test_shim_reexports_same_class_as_package() -> None:
    from detail_schedule import DetailScheduleWindow as PackageDetailScheduleWindow
    from detail_schedule_window import DetailScheduleWindow as ShimDetailScheduleWindow

    assert ShimDetailScheduleWindow is PackageDetailScheduleWindow


def test_shim_reexports_palette_helpers() -> None:
    from detail_schedule.palette import DESIGN_DARK as PackageDesignDark
    from detail_schedule.palette import DESIGN_LIGHT as PackageDesignLight
    from detail_schedule.palette import design_palette as package_design_palette
    from detail_schedule_window import DESIGN_DARK, DESIGN_LIGHT, design_palette

    assert DESIGN_DARK is PackageDesignDark
    assert DESIGN_LIGHT is PackageDesignLight
    assert design_palette is package_design_palette
