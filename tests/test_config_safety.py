from __future__ import annotations

import json
from pathlib import Path

import app_config
from app_config import load_config, load_data, load_json_object


def _patch_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    app_dir = tmp_path / "app"
    default_notes = app_dir / "Notes"
    config_path = app_dir / "config.json"
    data_path = app_dir / "data.json"
    monkeypatch.setattr(app_config, "APP_DIR", app_dir)
    monkeypatch.setattr(app_config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(app_config, "DATA_PATH", data_path)
    monkeypatch.setattr(app_config, "DEFAULT_NOTES_DIR", default_notes)
    monkeypatch.setattr(app_config, "LEGACY_NOTES_DIR", tmp_path / "legacy")
    return config_path, data_path


def test_load_json_object_returns_empty_dict_when_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    assert load_json_object(missing) == {}


def test_load_json_object_recovers_from_non_object_root(tmp_path: Path) -> None:
    list_path = tmp_path / "list.json"
    list_path.write_text(json.dumps([1, 2]), encoding="utf-8")
    assert load_json_object(list_path) == {}

    string_path = tmp_path / "string.json"
    string_path.write_text(json.dumps("hello"), encoding="utf-8")
    assert load_json_object(string_path) == {}

    number_path = tmp_path / "number.json"
    number_path.write_text(json.dumps(42), encoding="utf-8")
    assert load_json_object(number_path) == {}


def test_load_json_object_recovers_from_broken_json(tmp_path: Path) -> None:
    broken_path = tmp_path / "broken.json"
    broken_path.write_text("{not valid json", encoding="utf-8")
    assert load_json_object(broken_path) == {}


def test_load_json_object_preserves_valid_dict(tmp_path: Path) -> None:
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps({"a": 1, "b": "two"}), encoding="utf-8")
    assert load_json_object(dict_path) == {"a": 1, "b": "two"}


def test_load_config_recovers_when_config_json_root_is_a_list(monkeypatch, tmp_path: Path) -> None:
    config_path, _data_path = _patch_paths(monkeypatch, tmp_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps([1, 2]), encoding="utf-8")

    config = load_config()

    assert isinstance(config, dict)
    assert config["theme_mode"] == "system"
    assert config["notes_dir"] == str(app_config.DEFAULT_NOTES_DIR)


def test_load_data_recovers_when_data_json_root_is_a_string(monkeypatch, tmp_path: Path) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps("hello"), encoding="utf-8")

    data = load_data({})

    assert isinstance(data, dict)
    assert data["schedules"] == {}
    assert data["plans"] == []
    assert data["recurring_tasks"] == {"daily": [], "weekly": [], "monthly": [], "yearly": []}
    assert data["alarms"] == []


def test_load_config_preserves_values_from_valid_dict_json(monkeypatch, tmp_path: Path) -> None:
    config_path, _data_path = _patch_paths(monkeypatch, tmp_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"theme_mode": "dark", "language": "en"}), encoding="utf-8")

    config = load_config()

    assert config["theme_mode"] == "dark"
    assert config["language"] == "en"


def test_load_data_preserves_values_from_valid_dict_json(monkeypatch, tmp_path: Path) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps({"schedules": {"2026-07-04": "memo"}, "plans": [{"id": "1"}]}), encoding="utf-8")

    data = load_data({})

    assert data["schedules"] == {"2026-07-04": "memo"}
    assert data["plans"] == [{"id": "1"}]
