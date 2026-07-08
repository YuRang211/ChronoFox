from __future__ import annotations

import os
from pathlib import Path


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """같은 볼륨의 임시 파일에 fsync까지 마친 뒤 원자적으로 교체합니다."""
    temp_path = path.with_name(f"{path.name}.tmp")
    with open(temp_path, "w", encoding=encoding, newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    temp_path.replace(path)
