from __future__ import annotations

import json
from pathlib import Path

import app_config
from app_config import load_config, migrate_legacy_memos
from app_models import MemoStore


def test_legacy_memos_are_copied_without_overwriting(monkeypatch, tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    legacy_memos = legacy / "Memos"
    target_memos = target / "Memos"
    legacy_memos.mkdir(parents=True)
    target_memos.mkdir(parents=True)
    monkeypatch.setattr(app_config, "LEGACY_NOTES_DIR", legacy)
    (legacy_memos / "old.md").write_text("legacy memo\n", encoding="utf-8")
    (target_memos / "old.md").write_text("current memo\n", encoding="utf-8")
    (legacy_memos / "new.md").write_text("new legacy memo\n", encoding="utf-8")

    migrate_legacy_memos(target)

    assert (target_memos / "old.md").read_text(encoding="utf-8") == "current memo\n"
    assert (target_memos / "new.md").read_text(encoding="utf-8") == "new legacy memo\n"


def test_load_config_keeps_default_memos_when_configured_notes_dir_is_empty(monkeypatch, tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    default_notes = app_dir / "Notes"
    custom_notes = tmp_path / "empty-notes"
    config_path = app_dir / "config.json"
    data_path = app_dir / "data.json"
    MemoStore(default_notes).save("memo-1", "saved memo")
    custom_notes.mkdir()
    app_dir.mkdir(exist_ok=True)
    config_path.write_text(json.dumps({"notes_dir": str(custom_notes), "open_memos": {"memo-1": "280x260"}}), encoding="utf-8")

    monkeypatch.setattr(app_config, "APP_DIR", app_dir)
    monkeypatch.setattr(app_config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(app_config, "DATA_PATH", data_path)
    monkeypatch.setattr(app_config, "DEFAULT_NOTES_DIR", default_notes)
    monkeypatch.setattr(app_config, "LEGACY_NOTES_DIR", tmp_path / "legacy")

    config = load_config()

    assert config["notes_dir"] == str(default_notes)
    assert MemoStore(Path(config["notes_dir"])).load("memo-1").strip() == "saved memo"
