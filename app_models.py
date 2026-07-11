"""메모(Markdown) 파일 저장소인 MemoStore를 정의하는 모듈. 경로 탈출(디렉터리 트래버설)을 막는다."""

from __future__ import annotations

from pathlib import Path

from app_storage import write_text_atomic


class MemoStore:
    """메모 내용을 앱 데이터 폴더의 Markdown 파일로 저장하고 불러옵니다."""

    def __init__(self, notes_dir: Path) -> None:
        self.memo_dir = notes_dir / "Memos"
        self.memo_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, memo_id: str) -> Path:
        """메모 id를 실제 파일 경로로 변환합니다. 메모 폴더를 벗어나는 id는 거부합니다(경로 탈출 방지)."""
        base = self.memo_dir.resolve(strict=False)
        path = (self.memo_dir / f"{memo_id}.md").resolve(strict=False)
        if path.parent != base:
            raise ValueError("Invalid memo id")
        return path

    def load(self, memo_id: str) -> str:
        """메모 id에 해당하는 Markdown 내용을 읽어 반환합니다(없으면 빈 문자열)."""
        try:
            path = self.path_for(memo_id)
        except ValueError:
            return ""
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def save(self, memo_id: str, text: str) -> None:
        """저장 중 앱이 종료되어도 기존 메모 파일이 깨지지 않도록 원자적으로 씁니다."""
        path = self.path_for(memo_id)
        write_text_atomic(path, text.rstrip() + "\n")

    def memo_ids(self) -> list[str]:
        """저장된 모든 메모의 id 목록을 반환합니다."""
        return sorted(path.stem for path in self.memo_dir.glob("*.md") if path.is_file())

    def delete(self, memo_id: str) -> None:
        """메모 id에 해당하는 파일을 삭제합니다."""
        try:
            path = self.path_for(memo_id)
        except ValueError:
            return
        if path.exists():
            path.unlink()

    def exists(self, memo_id: str) -> bool:
        """메모 id에 해당하는 파일이 존재하는지 반환합니다."""
        try:
            return self.path_for(memo_id).exists()
        except ValueError:
            return False

    def has_content(self, memo_id: str) -> bool:
        """content 존재 여부를 반환합니다."""
        return bool(self.load(memo_id).strip())
