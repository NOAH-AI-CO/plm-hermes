"""Merge all translation domains."""
from i18n.translations.tools import TRANSLATIONS as _tools, TOOL_CLASS_TO_KEY, PLANNING_TOOL_TO_KEY
from i18n.translations.ui import TRANSLATIONS as _ui
from i18n.translations.stages import TRANSLATIONS as _stages
from i18n.translations.planning import TRANSLATIONS as _planning

ALL_TRANSLATIONS: dict[str, dict[str, str]] = {
    **_tools,
    **_ui,
    **_stages,
    **_planning,
}
