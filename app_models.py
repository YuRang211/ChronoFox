from __future__ import annotations

from pathlib import Path


class MemoStore:
    """메모 내용을 앱 데이터 폴더의 Markdown 파일로 저장하고 불러옵니다."""

    def __init__(self, notes_dir: Path) -> None:
        self.memo_dir = notes_dir / "Memos"
        self.memo_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, memo_id: str) -> Path:
        base = self.memo_dir.resolve(strict=False)
        path = (self.memo_dir / f"{memo_id}.md").resolve(strict=False)
        if path.parent != base:
            raise ValueError("Invalid memo id")
        return path

    def load(self, memo_id: str) -> str:
        try:
            path = self.path_for(memo_id)
        except ValueError:
            return ""
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def save(self, memo_id: str, text: str) -> None:
        self.path_for(memo_id).write_text(text.rstrip() + "\n", encoding="utf-8")

    def memo_ids(self) -> list[str]:
        return sorted(path.stem for path in self.memo_dir.glob("*.md") if path.is_file())

    def delete(self, memo_id: str) -> None:
        try:
            path = self.path_for(memo_id)
        except ValueError:
            return
        if path.exists():
            path.unlink()

    def exists(self, memo_id: str) -> bool:
        try:
            return self.path_for(memo_id).exists()
        except ValueError:
            return False

    def has_content(self, memo_id: str) -> bool:
        return bool(self.load(memo_id).strip())
