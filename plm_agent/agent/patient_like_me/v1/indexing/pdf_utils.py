"""
PDF text extraction utilities with header/footer removal for NCCN guidelines.

NCCN PDFs use a standardized landscape (792x612) template with fixed-position
headers (watermark, title bar, nav links) and footers (category note, page code,
copyright). These occupy the top 11.5% and bottom 8.5% of each page.
"""
import re
from io import BytesIO

try:
    import pymupdf
except ModuleNotFoundError:  # PyMuPDF exposed this module as fitz in older installs.
    import fitz as pymupdf

_HEADER_Y_THRESHOLD = 70
_FOOTER_Y_THRESHOLD = 560

_HEADER_PATTERNS = [
    re.compile(r"^NCCN\s*授权医脉通"),
    re.compile(r"NCCN Guidelines Version"),
    re.compile(r"NCCN Guidelines Index"),
    re.compile(r"^National\s+Comprehensive\s+Cancer\s+Network"),
]

_FOOTER_PATTERNS = [
    re.compile(r"Version\s+\d+\.\d{4}.*©.*National Comprehensive Cancer Network"),
    re.compile(r"^Note:\s+All recommendations are category 2A"),
]


def _is_noise_block(block: dict) -> bool:
    bbox = block.get("bbox") or (0, 0, 0, 0)
    y0, y1 = bbox[1], bbox[3]
    if y1 <= _HEADER_Y_THRESHOLD or y0 >= _FOOTER_Y_THRESHOLD:
        return True
    text = ""
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            text += span.get("text", "")
    text = text.strip()
    if not text:
        return True
    for pat in _HEADER_PATTERNS + _FOOTER_PATTERNS:
        if pat.search(text):
            return True
    return False


def extract_page_text_clean(pdf_path: str, page_index: int) -> str:
    """Extract text from a single PDF page with header/footer removal."""
    doc = pymupdf.open(pdf_path)
    try:
        page = doc[page_index]
        raw = page.get_text("dict")
        blocks = raw.get("blocks") or []
        parts = []
        for block in blocks:
            if _is_noise_block(block):
                continue
            for line in block.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                if line_text.strip():
                    parts.append(line_text)
        return "\n".join(parts)
    finally:
        doc.close()


def pdf_to_pages_clean(pdf_path: str) -> list[str]:
    """Extract per-page clean text from a PDF, removing NCCN headers/footers."""
    doc = pymupdf.open(pdf_path)
    try:
        pages = []
        for i in range(len(doc)):
            pages.append(extract_page_text_clean(pdf_path, i))
        return pages
    finally:
        doc.close()


def page_count(pdf_path: str) -> int:
    doc = pymupdf.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


_BOOKMARK_CODE_RE = re.compile(
    r"\(([A-Z]{2,}-[A-Z0-9]+(?:\s+\d+\s+OF\s+\d+)?)\)\s*$"
)


def build_section_titles(pdf_path: str) -> dict[int, str]:
    """Build 1-based page -> section_title from PDF bookmarks.

    Pages between bookmarks inherit the most recent entry.
    Pages before the first bookmark or after the last get "Discussion".
    """
    doc = pymupdf.open(pdf_path)
    try:
        toc = doc.get_toc()
        n_pages = len(doc)
    finally:
        doc.close()

    if not toc:
        return {}

    entries: list[tuple[int, int, str, str]] = []
    for level, title, page in toc:
        if page < 1:
            continue
        m = _BOOKMARK_CODE_RE.search(title)
        code = m.group(1) if m else ""
        clean = _BOOKMARK_CODE_RE.sub("", title).strip()
        clean = re.sub(r"^[A-Z]+:\s*", "", clean).strip()
        entries.append((page, level, code, clean))

    if not entries:
        return {}

    entries.sort(key=lambda e: (e[0], -e[1]))

    best: dict[int, tuple[str, str]] = {}
    for page, _level, code, clean in entries:
        if code or page not in best:
            best[page] = (code, clean)

    sorted_pages = sorted(best.keys())
    result: dict[int, str] = {}
    for pg in range(1, n_pages + 1):
        parent = None
        for bp in sorted_pages:
            if bp <= pg:
                parent = best[bp]
            else:
                break
        if parent:
            code, title = parent
            result[pg] = f"{code} | {title}" if code and title else (code or title)
        else:
            result[pg] = "Discussion"

    return result
