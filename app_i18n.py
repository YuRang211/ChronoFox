from __future__ import annotations

import json
from pathlib import Path

DEFAULT_LANGUAGE = "ko"
SUPPORTED_LANGUAGES: dict[str, str] = {
    "ko": "한국어",
    "en": "English",
}
LOCALES_DIR = Path(__file__).resolve().parent / "locales"

_TRANSLATION_CACHE: dict[str, dict[str, str]] = {}


def normalize_language(value: object) -> str:
    code = str(value or DEFAULT_LANGUAGE).lower()
    return code if code in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def load_language(language: object) -> dict[str, str]:
    code = normalize_language(language)
    if code in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[code]
    path = LOCALES_DIR / f"{code}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    translations = {str(key): str(value) for key, value in raw.items()}
    _TRANSLATION_CACHE[code] = translations
    return translations


def translate(language: object, key: str, fallback: str = "") -> str:
    translations = load_language(language)
    if key in translations:
        return translations[key]
    if normalize_language(language) != DEFAULT_LANGUAGE:
        return load_language(DEFAULT_LANGUAGE).get(key, fallback or key)
    return fallback or key
