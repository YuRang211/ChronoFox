"""임시 파일 + fsync + 원자적 rename으로 텍스트와 바이트를 안전하게 저장합니다."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """같은 볼륨의 임시 파일에 fsync까지 마친 뒤 원자적으로 교체합니다."""
    temp_path = path.with_name(f"{path.name}.tmp")
    with open(temp_path, "w", encoding=encoding, newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    _replace_with_retry(temp_path, path)


def _replace_with_retry(source: Path, target: Path, attempts: int = 5, delay: float = 0.05) -> None:
    """Windows에서 백신·인덱서가 대상 파일을 잠깐 잡고 있을 때 생기는 교체 실패를 짧게 재시도합니다."""
    for attempt in range(attempts):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay * (attempt + 1))


def write_bytes_atomic(path: Path, content: bytes) -> None:
    """바이너리와 원복 스냅샷을 바이트 변경 없이 원자 교체합니다."""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
