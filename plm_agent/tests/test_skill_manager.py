# -*- coding: utf-8 -*-
"""Tests for the SkillManager and image OCR skill integration."""

import pytest

from tools.sandbox.skill_manager import (
    SkillManager,
    extract_filenames_from_text,
)
from tools.sandbox.executor_prompt import build_sandbox_prompt


@pytest.fixture
def manager():
    return SkillManager()


class TestSkillDiscovery:
    def test_discover_includes_image(self, manager):
        skills = manager.discover()
        assert "image" in skills
        assert skills["image"].name == "image"
        assert "pytesseract" in skills["image"].body

    def test_discover_includes_all_expected_skills(self, manager):
        skills = manager.discover()
        for name in ("pdf", "docx", "xlsx", "pptx", "image"):
            assert name in skills, f"Skill '{name}' not discovered"


class TestExtensionMatching:
    @pytest.mark.parametrize("filename", [
        "scan.jpg", "photo.jpeg", "screenshot.png",
        "document.tiff", "scan.tif", "old.bmp",
        "modern.webp", "anim.gif", "photo.heic",
    ])
    def test_image_extensions_match(self, manager, filename):
        result = manager.match_skills("process this", filenames=[filename])
        names = [s.name for s in result]
        assert "image" in names

    def test_pdf_does_not_match_image(self, manager):
        result = manager.match_skills("process this", filenames=["doc.pdf"])
        names = [s.name for s in result]
        assert "image" not in names
        assert "pdf" in names


class TestKeywordMatching:
    @pytest.mark.parametrize("task", [
        "OCR this document",
        "use tesseract to extract text",
        "perform text recognition on the file",
        "do image ocr on this scan",
        "convert image to text",
    ])
    def test_ocr_keywords_match(self, manager, task):
        result = manager.match_skills(task)
        names = [s.name for s in result]
        assert "image" in names

    def test_no_false_positive_on_bare_image_word(self, manager):
        """'create a bar chart image' should NOT trigger image skill."""
        result = manager.match_skills("create a bar chart image")
        names = [s.name for s in result]
        assert "image" not in names


class TestFilenameExtraction:
    def test_extract_jpg_from_chinese_text(self):
        filenames = extract_filenames_from_text("请OCR receipt.jpg 中的文字")
        assert "receipt.jpg" in filenames

    def test_extract_png(self):
        filenames = extract_filenames_from_text("analyze screenshot.png")
        assert "screenshot.png" in filenames

    def test_extract_multiple_image_files(self):
        text = "process scan1.jpg and scan2.tiff together"
        filenames = extract_filenames_from_text(text)
        assert "scan1.jpg" in filenames
        assert "scan2.tiff" in filenames

    def test_no_match_on_non_image(self):
        filenames = extract_filenames_from_text("just some text without files")
        assert len(filenames) == 0


class TestBuildSandboxPrompt:
    def test_prompt_contains_pytesseract_when_image_matched(self, manager):
        matched = manager.match_skills("process", filenames=["scan.jpg"])
        prompt = build_sandbox_prompt(matched_skills=matched)
        assert "pytesseract" in prompt
        assert "Activated Skills" in prompt

    def test_brief_contains_image_ocr(self):
        prompt = build_sandbox_prompt(matched_skills=None)
        assert "Image/OCR" in prompt
        assert "pytesseract" in prompt
