from typing import Literal, get_args

# A campaign's target_language can be any of these -- an LLM can generate in a
# new language at zero upfront cost, so this list is intentionally broader
# than the UI chrome's shipped locale set (see frontend/src/i18n/locales/).
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "hi": "Hindi",
    "pt": "Portuguese",
    "ar": "Arabic",
    "zh": "Mandarin Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "it": "Italian",
    "nl": "Dutch",
    "ru": "Russian",
    "tr": "Turkish",
    "vi": "Vietnamese",
}

TargetLanguage = Literal[
    "en", "es", "fr", "de", "hi", "pt", "ar", "zh", "ja", "ko", "it", "nl", "ru", "tr", "vi"
]

assert set(get_args(TargetLanguage)) == set(SUPPORTED_LANGUAGES)

# NewsAPI's `language` param and pytrends' `hl` param both expect specific
# codes/formats that don't always match our plain ISO 639-1 keys above.
NEWSAPI_LANGUAGE_OVERRIDES: dict[str, str] = {
    "zh": "zh",  # NewsAPI supports zh directly
}

TRENDS_HL_MAP: dict[str, str] = {
    "en": "en-US", "es": "es-ES", "fr": "fr-FR", "de": "de-DE", "hi": "hi-IN",
    "pt": "pt-BR", "ar": "ar-SA", "zh": "zh-CN", "ja": "ja-JP", "ko": "ko-KR",
    "it": "it-IT", "nl": "nl-NL", "ru": "ru-RU", "tr": "tr-TR", "vi": "vi-VN",
}


def language_name(code: str) -> str:
    return SUPPORTED_LANGUAGES.get(code, SUPPORTED_LANGUAGES["en"])


def newsapi_language(code: str) -> str:
    return NEWSAPI_LANGUAGE_OVERRIDES.get(code, code)


def trends_hl(code: str) -> str:
    return TRENDS_HL_MAP.get(code, "en-US")
