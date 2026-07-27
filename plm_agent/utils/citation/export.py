from enum import Enum
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import hashlib
import re

from utils.citation.normalize import NormalizedInput, SourceType
from utils.citation.vancouver import format_vancouver
from utils.citation.normalize import _safe_str

class ExportFormat(Enum):
    TXT = "txt"
    BIBTEX = "bib"
    RIS = "ris"
    CSL_JSON = "csl-json"
    RTF = "rtf"
    DOCX = "docx" 

class CitationStyle(Enum):
    VANCOUVER = "vancouver"
    # APA = "apa" ...

@dataclass
class ExportOptions:
    style: Optional[CitationStyle] = CitationStyle.VANCOUVER  # TXT/RTF/DOCX
    numbered: bool = True                # [1] [2] ...
    start_index: int = 1
    line_break: str = "\n"


def export_txt(citations: List[NormalizedInput], *, opts: ExportOptions) -> str:
    if not opts.style:
        raise ValueError("TXT export requires a citation style (e.g. Vancouver).")

    lines = []
    for i, n in enumerate(citations, start=opts.start_index):
        if opts.style == CitationStyle.VANCOUVER:
            s = format_vancouver(n)
        else:
            raise NotImplementedError(f"Style not implemented: {opts.style}")

        if opts.numbered:
            lines.append(f"{i}. {s}")
        else:
            lines.append(s)

    return opts.line_break.join(lines) + opts.line_break

def export_bibtex(citations: List[NormalizedInput]) -> str:
    out = []
    for n in citations:
        et = _bibtex_entry_type(n)
        key = make_citekey(n)

        fields: Dict[str, str] = {}
        title = _safe_str(n.title)
        if title: fields["title"] = title

        authors = _bibtex_author_list(n.authors)
        if authors: fields["author"] = authors

        year = str(n.issued_year) if n.issued_year else _safe_str(n.issued_date)[:4]
        if year: fields["year"] = year

        doi = _safe_str((n.identifiers or {}).get("doi"))
        if doi: fields["doi"] = doi

        if n.url: fields["url"] = n.url

        # journal/booktitle
        if et == "article":
            j = _safe_str(n.container_title or n.container_abbrev)
            if j: fields["journal"] = j
            if n.volume: fields["volume"] = n.volume
            if n.issue: fields["number"] = n.issue
            if n.pages: fields["pages"] = n.pages
            if n.article_id and not n.pages:
                fields["eid"] = n.article_id
        elif et == "inproceedings":
            bt = _safe_str(n.container_title)
            if bt: fields["booktitle"] = bt
            if n.pages: fields["pages"] = n.pages
            if n.publisher: fields["publisher"] = n.publisher
            if n.publisher_place: fields["address"] = n.publisher_place
        elif et in ("book", "phdthesis"):
            if n.publisher: fields["publisher"] = n.publisher
            if n.publisher_place: fields["address"] = n.publisher_place
            if n.edition: fields["edition"] = n.edition

        # patent specifics (store as note/howpublished)
        if _safe_str(n.source_type) == SourceType.PATENT.value:
            pn = _safe_str((n.identifiers or {}).get("patent_number"))
            if pn:
                fields["howpublished"] = f"Patent {pn}"
            assignee = _safe_str((n.extra or {}).get("assignee"))
            if assignee:
                fields["note"] = f"Assignee: {assignee}"

        # render
        lines = [f"@{et}{{{key},"]
        for k, v in fields.items():
            lines.append(f"  {k} = {{{_bibtex_escape(v)}}},")
        lines.append("}")
        out.append("\n".join(lines))

    return "\n\n".join(out) + "\n"


def _bibtex_author_list(authors: List[Dict[str, str]]) -> str:
    # "Family, Given and Family, Given"
    out = []
    for a in authors or []:
        family = _safe_str(a.get("family"))
        given = _safe_str(a.get("given"))
        lit = _safe_str(a.get("literal"))
        if family:
            out.append(f"{family}, {given}".strip().rstrip(","))
        elif lit:
            out.append(lit)
    return " and ".join(out)

def _slug(s: str) -> str:
    s = re.sub(r"\s+", " ", _safe_str(s)).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

def make_citekey(n: NormalizedInput) -> str:
    doi = _safe_str((n.identifiers or {}).get("doi"))
    if doi:
        return "doi" + _slug(doi)[:40]
    pmid = _safe_str((n.identifiers or {}).get("pmid"))
    if pmid:
        return f"pmid{pmid}"
    pn = _safe_str((n.identifiers or {}).get("patent_number"))
    if pn:
        return "pat" + _slug(pn)[:40]

    family = _safe_str(n.authors[0].get("family")) if n.authors else "anon"
    year = str(n.issued_year) if n.issued_year else "n.d."
    title = _safe_str(n.title)
    h = hashlib.sha1(title.encode("utf-8")).hexdigest()[:6] if title else "xxxxxx"
    return f"{_slug(family)}{year}{h}"

def _bibtex_entry_type(n: NormalizedInput) -> str:
    st = _safe_str(n.source_type)
    if st == SourceType.JOURNAL_ARTICLE.value:
        return "article"
    if st == SourceType.BOOK.value:
        return "book"
    if st == SourceType.CONFERENCE.value:
        return "inproceedings"
    if st == SourceType.THESIS.value:
        return "phdthesis"
    if st in (SourceType.WEBPAGE.value, SourceType.DATASET.value, SourceType.SOFTWARE.value, SourceType.MEDIA.value, SourceType.NEWS.value):
        return "misc"
    if st == SourceType.PATENT.value:
        return "misc"  # bibtex classic
    return "misc"

def _bibtex_escape(s: str) -> str:
    # 够用的最小转义：防止 {} 破坏结构
    s = _safe_str(s)
    s = s.replace("{", "\\{").replace("}", "\\}")
    return s
