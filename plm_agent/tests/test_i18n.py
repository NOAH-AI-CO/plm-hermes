"""Unit tests for the i18n module."""
import pytest
from i18n import translate, tool_name, processing_stages, resolve_language, normalize_language
from i18n.languages import (
    ENGLISH, CHINESE, JAPANESE, ARABIC,
    KOREAN, FRENCH, GERMAN, SPANISH, PORTUGUESE,
    DEFAULT, DEFAULT_CODE, LANGUAGE_MAP, normalize,
)
from i18n.translations import ALL_TRANSLATIONS, TOOL_CLASS_TO_KEY

ALL_LANGUAGES = [ENGLISH, CHINESE, JAPANESE, ARABIC, KOREAN, FRENCH, GERMAN, SPANISH, PORTUGUESE]


class TestLanguages:
    def test_resolve_known_codes(self):
        assert resolve_language("zh-CN") == CHINESE
        assert resolve_language("ja-JP") == JAPANESE
        assert resolve_language("ar-SA") == ARABIC
        assert resolve_language("en-US") == ENGLISH
        assert resolve_language("ko-KR") == KOREAN
        assert resolve_language("fr-FR") == FRENCH
        assert resolve_language("de-DE") == GERMAN
        assert resolve_language("es-ES") == SPANISH
        assert resolve_language("pt-BR") == PORTUGUESE

    def test_resolve_legacy_codes(self):
        assert resolve_language("cn") == CHINESE
        assert resolve_language("jp") == JAPANESE
        assert resolve_language("arsa") == ARABIC
        assert resolve_language("en") == ENGLISH
        assert resolve_language("ko") == KOREAN
        assert resolve_language("fr") == FRENCH
        assert resolve_language("de") == GERMAN
        assert resolve_language("es") == SPANISH
        assert resolve_language("pt") == PORTUGUESE

    def test_resolve_case_insensitive(self):
        assert resolve_language("ZH-CN") == CHINESE
        assert resolve_language("Ja-JP") == JAPANESE
        assert resolve_language("KO-KR") == KOREAN
        assert resolve_language("FR-FR") == FRENCH

    def test_resolve_unknown_falls_back_to_english(self):
        assert resolve_language("") == DEFAULT
        assert resolve_language("xyz") == DEFAULT


class TestNormalize:
    def test_bcp47_passthrough(self):
        assert normalize("en-US") == "en-US"
        assert normalize("zh-CN") == "zh-CN"
        assert normalize("ja-JP") == "ja-JP"
        assert normalize("ar-SA") == "ar-SA"
        assert normalize("ko-KR") == "ko-KR"

    def test_legacy_to_bcp47(self):
        assert normalize("cn") == "zh-CN"
        assert normalize("en") == "en-US"
        assert normalize("jp") == "ja-JP"
        assert normalize("arsa") == "ar-SA"
        assert normalize("ko") == "ko-KR"
        assert normalize("fr") == "fr-FR"
        assert normalize("de") == "de-DE"
        assert normalize("es") == "es-ES"
        assert normalize("pt") == "pt-BR"

    def test_case_insensitive(self):
        assert normalize("CN") == "zh-CN"
        assert normalize("EN") == "en-US"
        assert normalize("zh-cn") == "zh-CN"
        assert normalize("EN-US") == "en-US"

    def test_common_variants(self):
        assert normalize("zh") == "zh-CN"
        assert normalize("ja") == "ja-JP"
        assert normalize("ar") == "ar-SA"
        assert normalize("chinese") == "zh-CN"

    def test_empty_returns_default(self):
        assert normalize("") == DEFAULT_CODE
        assert normalize("  ") == DEFAULT_CODE

    def test_unknown_returns_default(self):
        assert normalize("xyz") == DEFAULT_CODE

    def test_normalize_language_alias(self):
        assert normalize_language("cn") == "zh-CN"


class TestTranslate:
    def test_basic_lookup(self):
        assert translate("ui.think", ENGLISH) == "Think..."
        assert translate("ui.think", CHINESE) == "思考..."
        assert translate("ui.think", JAPANESE) == "考え…"
        assert translate("ui.think", ARABIC) == "أفكر..."
        assert translate("ui.think", KOREAN) == "생각 중..."
        assert translate("ui.think", FRENCH) == "Réflexion..."
        assert translate("ui.think", GERMAN) == "Denke nach..."
        assert translate("ui.think", SPANISH) == "Pensando..."
        assert translate("ui.think", PORTUGUESE) == "Pensando..."

    def test_empty_string_not_treated_as_falsy(self):
        """Empty string values should be returned as-is, not trigger English fallback."""
        from i18n.translations import ALL_TRANSLATIONS
        # Temporarily inject an empty-string entry to verify the fix
        ALL_TRANSLATIONS["_test.empty"] = {ENGLISH: "fallback", CHINESE: ""}
        try:
            assert translate("_test.empty", CHINESE) == ""
        finally:
            del ALL_TRANSLATIONS["_test.empty"]

    def test_fallback_to_english(self):
        # If a language is missing for a key, should fall back to English
        assert translate("ui.think", "Klingon") == "Think..."

    def test_template_parameters(self):
        result = translate("query.get_stock_prices", CHINESE, symbol="AAPL", date_from="2024-01", date_to="2024-12")
        assert "AAPL" in result
        assert "2024-01" in result
        assert "2024-12" in result

    def test_unknown_key_raises(self):
        with pytest.raises(KeyError):
            translate("nonexistent.key", ENGLISH)


class TestToolName:
    def test_known_tools(self):
        assert tool_name("MedicalSearch", ENGLISH) == "Health Search"
        assert tool_name("MedicalSearch", CHINESE) == "医学检索"
        assert tool_name("AgentRunSandbox", JAPANESE) == "サンドボックスでコード実行"

    def test_unknown_tool_falls_back_to_web_search(self):
        assert tool_name("NonExistentTool", ENGLISH) == "Web Search"
        assert tool_name("NonExistentTool", CHINESE) == "网络搜索"

    def test_all_tool_class_keys_exist_in_translations(self):
        for class_name, key in TOOL_CLASS_TO_KEY.items():
            assert key in ALL_TRANSLATIONS, f"Key {key} for tool {class_name} not in translations"

    def test_v2_specific_tools(self):
        assert tool_name("WebpageReader", CHINESE) == "阅读网页"
        assert tool_name("DatastoreFinished", ENGLISH) == "Data Filtering"
        assert tool_name("CatalystEventsDatabaseQuery", JAPANESE) == "データベースクエリ"

    def test_rewrite_tools(self):
        assert tool_name("Confirming", CHINESE) == "问题澄清"
        assert tool_name("Clarification", JAPANESE) == "問題の明確化"
        assert tool_name("RewrittenUserPrompt", ENGLISH) == "Rewritten Question"
        assert tool_name("Attachment", CHINESE) == "阅读附件"


class TestProcessingStages:
    def test_returns_four_stages(self):
        for lang in ALL_LANGUAGES:
            stages = processing_stages(lang)
            assert len(stages) == 4, f"Expected 4 stages for {lang}, got {len(stages)}"

    def test_english_stages(self):
        assert processing_stages(ENGLISH) == ["Analyzing", "Searching", "Answering", "Finished"]

    def test_chinese_stages(self):
        assert processing_stages(CHINESE) == ["分析问题", "网络搜索", "整理答案", "完成"]


class TestAllTranslationsHaveEnglish:
    def test_every_key_has_english(self):
        for key, entry in ALL_TRANSLATIONS.items():
            assert ENGLISH in entry, f"Key {key} is missing English translation"


class TestAllTranslationsHaveAllLanguages:
    def test_every_key_has_all_languages(self):
        missing = []
        for key, entry in ALL_TRANSLATIONS.items():
            for lang in ALL_LANGUAGES:
                if lang not in entry:
                    missing.append(f"{key} missing {lang}")
        assert not missing, f"Missing translations:\n" + "\n".join(missing)


class TestNewUIKeys:
    """Cover the 4 keys added for mindsearch_agent_v3 migration."""

    def test_reading_attachment(self):
        assert translate("ui.reading_attachment", ENGLISH) == "Reading attachment"
        assert translate("ui.reading_attachment", CHINESE) == "正在阅读附件"

    def test_attachment_read(self):
        assert translate("ui.attachment_read", ENGLISH) == "Attachment read"
        assert translate("ui.attachment_read", CHINESE) == "附件已读取"

    def test_answering(self):
        assert translate("ui.answering", ENGLISH) == "Answering..."
        assert translate("ui.answering", CHINESE) == "回答中..."

    def test_model_completed(self):
        assert translate("ui.model_completed", ENGLISH) == "Model processing completed"
        assert translate("ui.model_completed", CHINESE) == "模型处理完成"


class TestFixedTranslations:
    def test_search_finished_arabic_is_not_language_name(self):
        result = translate("ui.search_finished", ARABIC)
        assert result == "انتهى البحث"
        assert result != "العربية"

    def test_company_info_differs_from_press_releases(self):
        info_en = translate("tool.company_info", ENGLISH)
        press_en = translate("tool.press_releases", ENGLISH)
        assert info_en != press_en

    def test_query_keys_have_arabic(self):
        keys = [
            "query.get_financial_statements",
            "query.get_china_financial_statements",
            "query.get_company_info",
            "query.get_press_releases",
            "query.search_stock_symbol",
        ]
        for key in keys:
            assert ARABIC in ALL_TRANSLATIONS[key], f"{key} missing Arabic"


class TestBackwardCompatibility:
    def test_constants_module(self):
        from agent.explore.constants import ENGLISH as C_EN, CHINESE as C_CN
        from agent.explore.constants import EN, CN, JP, ARSA, KO, FR, DE, ES, PT
        assert C_EN == ENGLISH
        assert C_CN == CHINESE
        assert EN == "en-US"
        assert CN == "zh-CN"
        assert JP == "ja-JP"
        assert ARSA == "ar-SA"
        assert KO == "ko-KR"
        assert FR == "fr-FR"
        assert DE == "de-DE"
        assert ES == "es-ES"
        assert PT == "pt-BR"
