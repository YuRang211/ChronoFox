"""locales/*.json을 읽어 언어 코드로 문자열을 번역하는 i18n 코어와, 창/다이얼로그가 공유하는 TrMixin."""

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
    """언어를 정규화합니다."""
    code = str(value or DEFAULT_LANGUAGE).lower()
    return code if code in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def load_language(language: object) -> dict[str, str]:
    """locales/{언어}.json을 읽어 캐시된 번역 dict를 반환합니다."""
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
    """언어 코드와 키로 번역 문자열을 찾고, 없으면 기본 언어나 fallback을 사용합니다."""
    translations = load_language(language)
    if key in translations:
        return translations[key]
    if normalize_language(language) != DEFAULT_LANGUAGE:
        return load_language(DEFAULT_LANGUAGE).get(key, fallback or key)
    return fallback or key


class TrMixin:
    """Shared tr() implementation for windows/dialogs (F3 spec D5).

    Subclasses may override `_tr_language()` if their language lookup path
    differs from the default `self.app.store` / `self.app.config` / `self.config`
    fallback chain.
    """

    def _tr_language(self) -> str:
        holder = getattr(self, "app", None) or self
        store = getattr(holder, "store", None)
        if store is not None:
            return store.get("language", "ko")
        config = getattr(holder, "config", {})
        return config.get("language", "ko")

    def tr(self, key: str, fallback: str = "", **format_values) -> str:
        """현재 언어로 키를 번역하고, 전달된 값으로 {placeholder}를 채웁니다."""
        text = translate(self._tr_language(), key, fallback)
        if not format_values:
            return text
        try:
            return text.format(**format_values)
        except (KeyError, IndexError, ValueError):
            return fallback or key
