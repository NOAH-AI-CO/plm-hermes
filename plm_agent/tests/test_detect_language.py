"""Tests for i18n.languages.detect_language (P2 heuristic detection)."""

import pytest
from i18n.languages import detect_language


class TestDetectLanguageChinese:
    """Chinese text detection."""

    def test_pure_chinese(self):
        assert detect_language("帮我查一下最新的临床试验数据") == "zh-CN"

    def test_chinese_with_english_terms(self):
        """Mixed Chinese/English common in medical domain."""
        assert detect_language("帮我查一下EGFR inhibitors的最新临床试验") == "zh-CN"

    def test_short_chinese_with_english(self):
        assert detect_language("介绍一下EGFR") == "zh-CN"

    def test_chinese_drug_question(self):
        assert detect_language("依鲁替尼的作用机制是什么？") == "zh-CN"

    def test_chinese_report_request(self):
        assert detect_language("给我出个关于KRAS抑制剂的研究报告") == "zh-CN"


class TestDetectLanguageEnglish:
    """English text detection."""

    def test_pure_english(self):
        assert detect_language("What is the mechanism of action of erenumab?") == "en-US"

    def test_english_medical(self):
        assert detect_language("Compare EGFR inhibitors for NSCLC treatment") == "en-US"

    def test_short_english(self):
        assert detect_language("EGFR") == "en-US"

    def test_english_with_few_cjk(self):
        """English text with a Chinese drug name — short text with CJK ratio > 0.3 detects as Chinese."""
        # "What is 依鲁替尼?" → CJK=4, Latin=6, ratio=40% → zh-CN
        # This is acceptable: short mixed text tends toward Chinese user in this domain.
        assert detect_language("What is 依鲁替尼?") == "zh-CN"
        # Longer English text with same Chinese name → ratio drops below 0.3 → en-US
        assert detect_language("What is the clinical profile of 依鲁替尼?") == "en-US"

    def test_english_long_with_chinese_name(self):
        assert detect_language("Please provide a comprehensive analysis of 恩沙替尼 clinical trial results") == "en-US"


class TestDetectLanguageJapanese:
    """Japanese text detection (Kana presence)."""

    def test_japanese_with_kana(self):
        assert detect_language("EGFRについて教えてください") == "ja-JP"

    def test_pure_hiragana(self):
        assert detect_language("おはようございます") == "ja-JP"

    def test_katakana(self):
        assert detect_language("エルロチニブの副作用") == "ja-JP"


class TestDetectLanguageKorean:
    """Korean text detection (Hangul presence)."""

    def test_korean(self):
        assert detect_language("EGFR 억제제에 대해 알려주세요") == "ko-KR"

    def test_pure_hangul(self):
        assert detect_language("안녕하세요") == "ko-KR"


class TestDetectLanguageArabic:
    """Arabic text detection."""

    def test_arabic(self):
        assert detect_language("ما هي آلية عمل إيرينوماب؟") == "ar-SA"


class TestDetectLanguageLatinFamily:
    """Latin-script languages distinguished via langdetect."""

    def test_french(self):
        assert detect_language("Recherchez les essais cliniques sur les inhibiteurs de l'EGFR") == "fr-FR"

    def test_german(self):
        assert detect_language("Suchen Sie nach klinischen Studien zu EGFR-Inhibitoren") == "de-DE"

    def test_spanish(self):
        assert detect_language("Buscar ensayos clínicos sobre inhibidores de EGFR") == "es-ES"

    def test_portuguese(self):
        assert detect_language("Quais são os efeitos colaterais dos inibidores de EGFR no tratamento oncológico") == "pt-BR"

    def test_english_not_misdetected(self):
        """English should remain en-US and not be misclassified as another Latin language."""
        assert detect_language("Find all clinical trials for EGFR inhibitors in NSCLC") == "en-US"


class TestDetectLanguageEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_string(self):
        assert detect_language("") == "en-US"

    def test_whitespace_only(self):
        assert detect_language("   ") == "en-US"

    def test_numbers_only(self):
        assert detect_language("12345") == "en-US"

    def test_symbols_only(self):
        assert detect_language("!@#$%") == "en-US"

    def test_cjk_at_threshold(self):
        """CJK ratio right at the 0.3 boundary."""
        # 3 CJK + 7 Latin = ratio 0.3 → should be Chinese
        assert detect_language("帮我查abcdefg") == "zh-CN"

    def test_cjk_below_threshold(self):
        """CJK ratio below 0.3 → English."""
        # 2 CJK + 8 Latin = ratio 0.2 → English
        assert detect_language("帮我abcdefgh") == "en-US"

    def test_mixed_cjk_heavy(self):
        """Heavy CJK with some English abbreviations."""
        assert detect_language("请帮我分析一下这个药物的临床数据EGFR") == "zh-CN"
