# -*- coding: utf-8 -*-
"""
Tests for AttachmentDetector

Run with: python -m utils.web_search.test_attachment_detector
"""

import logging
from utils.web_search.attachment_detector import AttachmentDetector, AttachmentType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_detect_direct_pdf_links():
    """Test detection of direct PDF links"""
    detector = AttachmentDetector()

    content = """
    Here are some documents:
    - [Annual Report 2024](https://example.com/reports/annual-2024.pdf)
    - [Q1 Results](https://example.com/docs/q1-results.xlsx)
    - [Data Export](https://example.com/data/export.csv)
    - [User Guide](https://example.com/docs/guide.docx)
    """

    result = detector.detect(content, "https://example.com/page")

    print(f"\n=== Test: Direct PDF Links ===")
    print(f"Direct attachments found: {len(result.direct)}")
    for att in result.direct:
        print(f"  - {att.filename} ({att.type.value}): {att.url}")

    assert len(result.direct) == 4, f"Expected 4 attachments, got {len(result.direct)}"

    types = {att.type for att in result.direct}
    assert AttachmentType.PDF in types
    assert AttachmentType.EXCEL in types
    assert AttachmentType.CSV in types
    assert AttachmentType.WORD in types

    print("[PASS] Direct PDF links detection")


def test_detect_html_href_links():
    """Test detection of HTML href links"""
    detector = AttachmentDetector()

    content = """
    <a href="/files/report.pdf">Download Report</a>
    <a href="https://cdn.example.com/data.xlsx">Excel Data</a>
    <a href="document.csv">CSV File</a>
    """

    result = detector.detect(content, "https://example.com/page")

    print(f"\n=== Test: HTML href Links ===")
    print(f"Direct attachments found: {len(result.direct)}")
    for att in result.direct:
        print(f"  - {att.filename}: {att.url}")

    assert len(result.direct) == 3, f"Expected 3 attachments, got {len(result.direct)}"
    print("[PASS] HTML href links detection")


def test_detect_relative_urls():
    """Test handling of relative URLs"""
    detector = AttachmentDetector()

    content = """
    [Report](/downloads/report.pdf)
    [Data](../data/file.xlsx)
    """

    result = detector.detect(content, "https://example.com/page/index.html")

    print(f"\n=== Test: Relative URLs ===")
    for att in result.direct:
        print(f"  - {att.filename}: {att.url}")

    assert len(result.direct) == 2
    assert "https://example.com/downloads/report.pdf" in [a.url for a in result.direct]
    print("[PASS] Relative URLs handling")


def test_detect_attachment_pages():
    """Test detection of pages that may contain attachments"""
    detector = AttachmentDetector()

    content = """
    - [Downloads Center](https://example.com/downloads)
    - [Annual Report Archive](https://example.com/investor-relations)
    - [SEC Filings](https://example.com/sec-filings)
    - [About Us](https://example.com/about)
    """

    result = detector.detect(content, "https://example.com")

    print(f"\n=== Test: Attachment Pages ===")
    print(f"Attachment pages found: {len(result.pages)}")
    for page in result.pages:
        print(f"  - {page.url} (hint: {page.hint}, confidence: {page.confidence})")

    assert len(result.pages) >= 2, f"Expected at least 2 pages, got {len(result.pages)}"
    print("[PASS] Attachment pages detection")


def test_exclude_patterns():
    """Test exclusion of non-attachment links"""
    detector = AttachmentDetector()

    content = """
    [JavaScript](javascript:void(0))
    [Email](mailto:test@example.com)
    [Phone](tel:+1234567890)
    [Anchor](#section)
    [Image](https://example.com/image.jpg)
    [Real PDF](https://example.com/real.pdf)
    """

    result = detector.detect(content, "https://example.com")

    print(f"\n=== Test: Exclude Patterns ===")
    print(f"Attachments found: {len(result.direct)}")

    assert len(result.direct) == 1
    assert result.direct[0].filename == "real.pdf"
    print("[PASS] Exclude patterns")


def test_duplicate_urls():
    """Test deduplication of URLs"""
    detector = AttachmentDetector()

    content = """
    [Report 1](https://example.com/report.pdf)
    [Report 2](https://example.com/report.pdf)
    <a href="https://example.com/report.pdf">Report 3</a>
    """

    result = detector.detect(content, "https://example.com")

    print(f"\n=== Test: Duplicate URLs ===")
    print(f"Attachments found: {len(result.direct)}")

    assert len(result.direct) == 1, f"Expected 1 attachment (deduplicated), got {len(result.direct)}"
    print("[PASS] Duplicate URL deduplication")


def test_url_with_query_params():
    """Test detection of URLs with query parameters"""
    detector = AttachmentDetector()

    content = """
    [Report](https://example.com/report.pdf?token=abc123&download=true)
    [Data](https://cdn.example.com/data.xlsx?v=2)
    """

    result = detector.detect(content, "https://example.com")

    print(f"\n=== Test: URLs with Query Params ===")
    for att in result.direct:
        print(f"  - {att.filename}: {att.url}")

    assert len(result.direct) == 2
    print("[PASS] URLs with query parameters")


def test_empty_content():
    """Test handling of empty content"""
    detector = AttachmentDetector()

    result = detector.detect("", "https://example.com")

    print(f"\n=== Test: Empty Content ===")
    assert len(result.direct) == 0
    assert len(result.pages) == 0
    print("[PASS] Empty content handling")


def test_chinese_keywords():
    """Test detection with Chinese keywords"""
    detector = AttachmentDetector()

    content = """
    - [下载中心](https://example.com/download-center)
    - [年报下载](https://example.com/annual-report)
    - [财报](https://example.com/financial)
    - [公司介绍](https://example.com/about)
    """

    result = detector.detect(content, "https://example.com")

    print(f"\n=== Test: Chinese Keywords ===")
    print(f"Attachment pages found: {len(result.pages)}")
    for page in result.pages:
        print(f"  - {page.url} (hint: {page.hint})")

    assert len(result.pages) >= 2
    print("[PASS] Chinese keywords detection")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("AttachmentDetector Tests")
    print("=" * 60)

    tests = [
        test_detect_direct_pdf_links,
        test_detect_html_href_links,
        test_detect_relative_urls,
        test_detect_attachment_pages,
        test_exclude_patterns,
        test_duplicate_urls,
        test_url_with_query_params,
        test_empty_content,
        test_chinese_keywords,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] {test.__name__}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
