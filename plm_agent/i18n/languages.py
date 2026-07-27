"""Language constants and short-code mapping."""

from langdetect import detect as _langdetect, LangDetectException

# Full language names (used for prompt injection and translation lookup)
ENGLISH = "English"
CHINESE = "Simplified Chinese"
JAPANESE = "Japanese"
ARABIC = "Arabic"
KOREAN = "Korean"
FRENCH = "French"
GERMAN = "German"
SPANISH = "Spanish"
PORTUGUESE = "Portuguese"

# BCP-47 codes (canonical format, language lowercase + region uppercase)
LANGUAGE_MAP: dict[str, str] = {
    "en-US": ENGLISH,
    "zh-CN": CHINESE,
    "ja-JP": JAPANESE,
    "ar-SA": ARABIC,
    "ko-KR": KOREAN,
    "fr-FR": FRENCH,
    "de-DE": GERMAN,
    "es-ES": SPANISH,
    "pt-BR": PORTUGUESE,
}

# Legacy short codes → BCP-47
_LEGACY_TO_BCP47: dict[str, str] = {
    "en": "en-US",
    "cn": "zh-CN",
    "jp": "ja-JP",
    "arsa": "ar-SA",
    "ko": "ko-KR",
    "fr": "fr-FR",
    "de": "de-DE",
    "es": "es-ES",
    "pt": "pt-BR",
    # Common variants
    "zh": "zh-CN",
    "ja": "ja-JP",
    "ar": "ar-SA",
    "chinese": "zh-CN",
}

# Default language
DEFAULT = ENGLISH
DEFAULT_CODE = "en-US"

# Internal: lowercase → canonical mixed-case (for case-insensitive lookup)
_LOWER_LOOKUP: dict[str, str] = {k.lower(): k for k in LANGUAGE_MAP}


def normalize(code: str) -> str:
    """Normalize any language code to standard BCP-47 mixed-case format.

    Examples:
        normalize("cn")    → "zh-CN"
        normalize("zh-CN") → "zh-CN"
        normalize("zh-cn") → "zh-CN"
        normalize("EN-US") → "en-US"
        normalize("")       → "en-US"
    """
    c = code.strip().lower()
    if not c:
        return DEFAULT_CODE
    if c in _LOWER_LOOKUP:
        return _LOWER_LOOKUP[c]
    if c in _LEGACY_TO_BCP47:
        return _LEGACY_TO_BCP47[c]
    return DEFAULT_CODE


def resolve(code: str) -> str:
    """Short code to full language name. Unknown codes fall back to English."""
    return LANGUAGE_MAP.get(normalize(code), DEFAULT)


# ---------------------------------------------------------------------------
# Language detection from text (P2 heuristic)
# ---------------------------------------------------------------------------

def _classify_char(ch: str) -> str:
    """Classify a single character into a script category."""
    cp = ord(ch)
    # CJK Unified Ideographs & extensions
    if (0x4E00 <= cp <= 0x9FFF
            or 0x3400 <= cp <= 0x4DBF
            or 0x20000 <= cp <= 0x2A6DF
            or 0xF900 <= cp <= 0xFAFF):
        return "cjk"
    # Hiragana
    if 0x3040 <= cp <= 0x309F:
        return "kana"
    # Katakana
    if 0x30A0 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF:
        return "kana"
    # Hangul Syllables & Jamo
    if (0xAC00 <= cp <= 0xD7AF
            or 0x1100 <= cp <= 0x11FF
            or 0x3130 <= cp <= 0x318F):
        return "hangul"
    # Arabic
    if 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F or 0x08A0 <= cp <= 0x08FF:
        return "arabic"
    # Basic Latin letters
    if (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A):
        return "latin"
    # Extended Latin (accented characters for European languages)
    if 0x00C0 <= cp <= 0x024F:
        return "latin"
    return "other"


# CJK-to-Latin ratio threshold for Chinese detection.
# 0.3 works well for mixed medical text like "帮我查一下EGFR inhibitors的临床试验"
_CJK_RATIO_THRESHOLD = 0.3

# langdetect short code → project BCP-47
_LANGDETECT_TO_BCP47: dict[str, str] = {
    "en": "en-US",
    "zh-cn": "zh-CN",
    "zh-tw": "zh-CN",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "ar": "ar-SA",
    "fr": "fr-FR",
    "de": "de-DE",
    "es": "es-ES",
    "pt": "pt-BR",
}


def detect_language(text: str) -> str:
    """Detect response language from user prompt text using character script analysis.

    Priority rules:
    - Kana (Hiragana/Katakana) present → Japanese
    - Hangul present → Korean
    - Arabic script present → Arabic
    - CJK / (CJK + Latin) >= 0.3 → Chinese
    - Otherwise → English (default)

    Returns BCP-47 code (e.g., "zh-CN", "en-US").
    """
    if not text or text.isspace():
        return DEFAULT_CODE

    cjk = latin = 0
    for ch in text:
        cat = _classify_char(ch)
        if cat == "kana":
            return "ja-JP"
        if cat == "hangul":
            return "ko-KR"
        if cat == "arabic":
            return "ar-SA"
        if cat == "cjk":
            cjk += 1
        elif cat == "latin":
            latin += 1

    # CJK vs Latin ratio
    total = cjk + latin
    if total > 0 and cjk / total >= _CJK_RATIO_THRESHOLD:
        return "zh-CN"

    # Layer 2: Latin-dominant text → langdetect for fr/de/es/pt distinction
    # langdetect is unreliable on very short text; require minimum Latin chars
    if latin < 20:
        return DEFAULT_CODE
    try:
        code = _langdetect(text).lower()
        return _LANGDETECT_TO_BCP47.get(code, DEFAULT_CODE)
    except LangDetectException:
        return DEFAULT_CODE
