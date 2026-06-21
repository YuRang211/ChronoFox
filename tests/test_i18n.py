from __future__ import annotations

import json
from pathlib import Path

from app_i18n import DEFAULT_LANGUAGE, normalize_language, translate

LOCALES_DIR = Path(__file__).resolve().parents[1] / "locales"


def load_locale(name: str) -> dict[str, str]:
    raw = json.loads((LOCALES_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return {str(key): str(value) for key, value in raw.items()}


def test_locale_keys_match() -> None:
    korean = load_locale("ko")
    english = load_locale("en")

    assert set(korean) == set(english)


def test_language_normalization_falls_back_to_default() -> None:
    assert normalize_language("missing") == DEFAULT_LANGUAGE
    assert normalize_language(None) == DEFAULT_LANGUAGE


def test_translate_falls_back_to_korean_text() -> None:
    korean = load_locale("ko")
    first_key = next(iter(korean))

    assert translate("missing", first_key) == korean[first_key]
