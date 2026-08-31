"""Windows 로그인 자동실행 명령과 HKCU Run 등록을 관리한다."""

from __future__ import annotations

import subprocess
import winreg
from pathlib import Path
from typing import Any

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "ChronoFox"


def build_startup_command(
    *,
    executable: Path,
    entrypoint: Path,
    frozen: bool,
    pythonw_exists: bool,
) -> str:
    """Windows 명령줄 인용 규칙에 맞춘 직접 실행 명령을 반환한다."""
    if frozen:
        arguments = [str(executable)]
    else:
        pythonw = executable.with_name("pythonw.exe")
        launcher = pythonw if pythonw_exists else executable
        arguments = [str(launcher), str(entrypoint)]
    return subprocess.list2cmdline(arguments)


def set_startup_registration(
    enabled: bool,
    command: str | None,
    *,
    legacy_paths: tuple[Path, ...],
    registry: Any = None,
) -> None:
    """사용자 동의 상태를 HKCU Run에 기록하고 구버전 배치 파일을 정리한다."""
    registry = winreg if registry is None else registry
    if enabled:
        if not command:
            raise ValueError("startup command is required when enabling registration")
        with registry.CreateKeyEx(
            registry.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            registry.KEY_SET_VALUE,
        ) as key:
            registry.SetValueEx(key, RUN_VALUE_NAME, 0, registry.REG_SZ, command)
    else:
        try:
            with registry.OpenKey(
                registry.HKEY_CURRENT_USER,
                RUN_KEY,
                0,
                registry.KEY_SET_VALUE,
            ) as key:
                registry.DeleteValue(key, RUN_VALUE_NAME)
        except FileNotFoundError:
            pass

    # 등록 쓰기가 실패하면 기존 동작 가능한 파일을 보존해야 하므로 성공 뒤에만 지운다.
    for path in legacy_paths:
        path.unlink(missing_ok=True)


def startup_registration_enabled(
    *,
    legacy_paths: tuple[Path, ...],
    registry: Any = None,
) -> bool:
    """HKCU Run 값 또는 마이그레이션 전 배치 파일이 존재하는지 반환한다."""
    registry = winreg if registry is None else registry
    try:
        with registry.OpenKey(
            registry.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            registry.KEY_QUERY_VALUE,
        ) as key:
            value, _value_type = registry.QueryValueEx(key, RUN_VALUE_NAME)
            if str(value).strip():
                return True
    except OSError:
        pass
    return any(path.exists() for path in legacy_paths)
