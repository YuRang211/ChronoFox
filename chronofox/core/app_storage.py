"""임시 파일 + fsync + 원자적 rename으로 텍스트와 바이트를 안전하게 저장합니다."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """같은 볼륨의 임시 파일에 fsync까지 마친 뒤 원자적으로 교체합니다."""
    temp_path = path.with_name(f"{path.name}.tmp")
    with open(temp_path, "w", encoding=encoding, newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    temp_path.replace(path)


def write_bytes_atomic(path: Path, content: bytes) -> None:
    """바이너리와 원복 스냅샷을 바이트 변경 없이 원자 교체합니다."""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
