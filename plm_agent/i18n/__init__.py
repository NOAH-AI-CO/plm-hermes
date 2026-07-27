"""
NoahAgent internationalization module.

Usage:
    from i18n import translate, tool_name, processing_stages

    label = translate("ui.think", language)
    name = tool_name("MedicalSearch", language)
    stages = processing_stages(language)
"""

from i18n.languages import (
    ENGLISH, CHINESE, JAPANESE, ARABIC,
    KOREAN, FRENCH, GERMAN, SPANISH, PORTUGUESE,
    DEFAULT, DEFAULT_CODE, LANGUAGE_MAP,
    resolve as resolve_language,
    normalize as normalize_language,
    detect_language,
)
from i18n.translations import ALL_TRANSLATIONS, TOOL_CLASS_TO_KEY, PLANNING_TOOL_TO_KEY


def translate(key: str, language: str, **kwargs) -> str:
    """
    Look up a translated string.

    Args:
        key: Translation key, e.g. "ui.think", "tool.medical_search"
        language: Full language name (e.g. "English", "Simplified Chinese")
        **kwargs: Template parameters (e.g. symbol, date_from)

    Returns:
        Translated string. Falls back to English if language is missing.

    Raises:
        KeyError: if key does not exist (catch typos early).
    """
    entry = ALL_TRANSLATIONS[key]
    text = entry[language] if language in entry else entry[DEFAULT]
    if kwargs:
        text = text.format(**kwargs)
    return text


def tool_name(class_name: str, language: str) -> str:
    """Tool class name -> translated display name. Unknown tools fall back to Web Search."""
    key = TOOL_CLASS_TO_KEY.get(class_name, "tool.web_search")
    return translate(key, language)


def planning_tool_name(tool: str, language: str) -> str:
    """Planning tool name (e.g. 'Medical-Search') → translated display name."""
    key = PLANNING_TOOL_TO_KEY.get(tool)
    if not key:
        return tool
    return translate(key, language)


def _build_reverse_tool_map() -> dict[str, str]:
    """Build a reverse lookup: translated name → English planning tool name.

    Covers all languages so that any translated tool name can be mapped back
    to its canonical English identifier (e.g. "의학 검색" → "Medical-Search").
    """
    reverse: dict[str, str] = {}
    for tool_id, key in PLANNING_TOOL_TO_KEY.items():
        entry = ALL_TRANSLATIONS.get(key, {})
        for lang_name, translated in entry.items():
            if translated != tool_id:
                reverse[translated] = tool_id
    return reverse


_REVERSE_TOOL_MAP: dict[str, str] = _build_reverse_tool_map()


def normalize_planning_tool_name(tool: str) -> str:
    """Map a possibly-translated tool name back to its English identifier.

    If *tool* is already a valid English planning tool name, return as-is.
    Otherwise try the reverse translation lookup. Falls back to the original
    string if no match is found.
    """
    if tool in PLANNING_TOOL_TO_KEY:
        return tool
    return _REVERSE_TOOL_MAP.get(tool, tool)


def planning_tool_names_table(language: str) -> str:
    """Generate tool name translation table for injection into planning prompts.

    Returns empty string for English (no translation needed).
    """
    if language == ENGLISH:
        return ""
    lines = []
    for tool_id, key in PLANNING_TOOL_TO_KEY.items():
        translated = translate(key, language)
        lines.append(f"- {tool_id} = {translated}")
    return "\n".join(lines)


def processing_stages(language: str) -> list[str]:
    """Return the 4 progress-bar stage labels."""
    return [
        translate("stage.analyzing", language),
        translate("stage.searching", language),
        translate("stage.answering", language),
        translate("stage.finished", language),
    ]
