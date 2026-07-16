# -*- mode: python ; coding: utf-8 -*-
"""ChronoFox PyInstaller build spec.

Reproducible onedir build config per planning/specs/release-v1.md P1-P3
(S3 packaging alpha). Committing this spec (rather than relying on ad-hoc
`pyinstaller` CLI flags) is the point: `python -m PyInstaller chronofox.spec`
must always reproduce the same build.

Build:
    python -m PyInstaller chronofox.spec

Output:
    dist/ChronoFox/ChronoFox.exe (+ _internal/ support files)
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

APP_NAME = "ChronoFox"
ENTRY_SCRIPT = "desktop_note_calendar.py"
ICON_PATH = "chronofox/assets/fox_calendar_icon.png"
VERSION_FILE = "version_info.txt"

# `holidays.country_holidays()` resolves country modules dynamically via
# importlib (see holidays/registry.py), which PyInstaller's static import
# scan cannot see. Pull in every submodule so KR (and any other country a
# user's locale maps to) is available in the frozen build (P2: bundle
# holidays for full feature parity).
hiddenimports = collect_submodules("holidays")

# holidays also ships gettext .mo translation catalogs under
# holidays/locale/**/LC_MESSAGES/*.mo (package *data*, not importable code),
# needed for `country_holidays(..., language="ko")`. collect_submodules()
# above does not pull these in — confirmed by a sandboxed smoke test that
# failed with `FileNotFoundError: No translation file found for domain: 'KR'`
# until this was added.
holidays_datas = collect_data_files("holidays")

a = Analysis(
    [ENTRY_SCRIPT],
    pathex=[],
    binaries=[],
    datas=[
        ("chronofox/assets", "chronofox/assets"),
        ("chronofox/locales", "chronofox/locales"),
        *holidays_datas,
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH,
    version=VERSION_FILE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
