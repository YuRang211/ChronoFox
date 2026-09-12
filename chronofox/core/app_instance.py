"""같은 데이터 폴더를 사용하는 앱의 동시 실행을 차단한다."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile

RESTART_WAIT_ARGUMENT = "--wait-for-instance"
RESTART_WAIT_MS = 10_000


def acquire_instance_lock(data_dir: Path, *, wait_ms: int = 0) -> QLockFile | None:
    """획득한 잠금 또는 중복 실행이면 None을 반환하고, 잠금 I/O 실패는 보고한다.

    호출자는 앱 종료 저장까지 반환 객체를 유지한 뒤 unlock해야 한다.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / "instance.lock"
    if lock_path.is_dir():
        raise IsADirectoryError("Application lock path is a directory")
    lock = QLockFile(str(lock_path))
    # 상주 앱은 실행 시간이 길다는 이유로 잠금을 만료시키면 안 된다.
    # 비정상 종료의 잔여 파일은 Qt의 PID/프로세스 생존 검사로 복구한다.
    lock.setStaleLockTime(0)
    if lock.tryLock(wait_ms):
        return lock
    if lock.error() == QLockFile.LockFailedError:
        return None
    raise OSError(f"Unable to acquire application lock: {lock.error().name}")
