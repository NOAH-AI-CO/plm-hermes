from typing import List, Dict, Optional
from utils.citation.normalize import NormalizedInput, EventInfo, SourceType
from utils.citation.normalize import _safe_str

def format_vancouver(n: "NormalizedInput") -> str:
    if n.source_type == SourceType.JOURNAL_ARTICLE.value:
        return format_journal_article_vancouver(n)
    elif n.source_type == SourceType.CONFERENCE.value:
        return format_conference_vancouver(n)
    elif n.source_type == SourceType.BOOK.value:
        return format_book_vancouver(n)
    elif n.source_type == SourceType.THESIS.value:
        return format_thesis_vancouver(n)
    elif n.source_type == SourceType.PREPRINT.value:
        return format_preprint_vancouver(n)
    elif n.source_type == SourceType.NEWS.value:
        return format_news_vancouver(n)
    elif n.source_type == SourceType.MEDIA.value:
        return format_media_vancouver(n)
    elif n.source_type == SourceType.WEBPAGE.value:
        return format_webpage_vancouver(n)
    elif n.source_type == SourceType.DATASET.value:
        return format_dataset_vancouver(n)
    elif n.source_type == SourceType.PATENT.value:
        return format_patent_vancouver(n)
    elif n.source_type == SourceType.OTHER.value:
        return format_other_vancouver(n)
    else:
        return ""



# Journal Article
def format_journal_article_vancouver(n: "NormalizedInput") -> str:
    return _render_vancouver_journal_like(n) if _journal_like(n) else _render_vancouver_internet_like(n)

# Conference
def format_conference_vancouver(n, *, max_authors: int = 6) -> str:
    ev = _get_event_or_none(n)

    if ev is None:
        if _journal_like(n):
            return format_journal_article_vancouver(n, max_authors=max_authors)
        return _format_vancouver_conference_paper(n, ev=None, max_authors=max_authors)

    kind = _safe_str(getattr(ev, "kind", "")).lower() or "paper"
    if kind == "proceedings":
        return _format_vancouver_conference_proceedings(n, ev)
    return _format_vancouver_conference_paper(n, ev, max_authors=max_authors)

def _format_vancouver_conference_proceedings(n, ev: Optional["EventInfo"]) -> str:
    resp = _format_authors(getattr(n, "authors", []) or [], max_authors=0)  # editors/org: don't truncate

    # Proceedings title: prefer container_title; fallback to title
    proc_title = _safe_str(getattr(n, "container_title", None) or getattr(n, "title", None)).rstrip(".")

    conf_name = _safe_str(getattr(ev, "name", "")) if ev else ""
    conf_date = _safe_str(getattr(ev, "date", "")) if ev else ""
    conf_loc  = _safe_str(getattr(ev, "location", "")) if ev else ""

    place = _safe_str(getattr(n, "publisher_place", None))
    publisher = _safe_str(getattr(n, "publisher", None))
    year = _year(n)

    url = _safe_str(getattr(n, "url", None))
    doi = _get_id(n, "doi")

    chunks: List[str] = []
    if resp:
        chunks.append(f"{resp}.")
    if proc_title:
        chunks.append(f"{proc_title}.")

    conf_bits = [x for x in [conf_name, conf_date, conf_loc] if x]
    if conf_bits:
        chunks.append("Proceedings of " + "; ".join(conf_bits) + ".")

    # Place: Publisher; Year.
    if place and publisher:
        if year:
            chunks.append(f"{place}: {publisher}; {year}.")
        else:
            chunks.append(f"{place}: {publisher}.")
    elif publisher and year:
        chunks.append(f"{publisher}; {year}.")
    elif year:
        chunks.append(f"{year}.")

    if url:
        chunks.append(f"Available from: {url}.")
    if doi:
        chunks.append(f"doi:{doi}.")

    return _collapse_spaces(" ".join(chunks))


def _format_vancouver_conference_paper(n, ev: Optional["EventInfo"], *, max_authors: int = 6) -> str:
    authors = _format_authors(getattr(n, "authors", []) or [], max_authors=max_authors)
    paper_title = _safe_str(getattr(n, "title", None)).rstrip(".")

    # proceedings title SHOULD be container_title for papers
    proc_title = _safe_str(getattr(n, "container_title", None)).rstrip(".")

    editors = _safe_str(getattr(ev, "editors", "")) if ev else ""
    conf_name = _safe_str(getattr(ev, "name", "")) if ev else ""
    conf_date = _safe_str(getattr(ev, "date", "")) if ev else ""
    conf_loc  = _safe_str(getattr(ev, "location", "")) if ev else ""

    place = _safe_str(getattr(n, "publisher_place", None))
    publisher = _safe_str(getattr(n, "publisher", None))
    year = _year(n)

    pages = _safe_str(getattr(n, "pages", None))
    url = _safe_str(getattr(n, "url", None))
    doi = _get_id(n, "doi")

    chunks: List[str] = []
    if authors:
        chunks.append(f"{authors}.")
    if paper_title:
        chunks.append(f"{paper_title}.")

    # In: Editors. Proceedings title.
    in_bits: List[str] = []
    if editors:
        in_bits.append(f"{editors}, editors")
    if proc_title:
        in_bits.append(proc_title)
    if in_bits:
        chunks.append("In: " + ". ".join(in_bits) + ".")

    # ConfName; Date; Location.
    conf_bits = [x for x in [conf_name, conf_date, conf_loc] if x]
    if conf_bits:
        chunks.append("; ".join(conf_bits) + ".")

    # Place: Publisher; Year.
    if place and publisher:
        if year:
            chunks.append(f"{place}: {publisher}; {year}.")
        else:
            chunks.append(f"{place}: {publisher}.")
    elif publisher and year:
        chunks.append(f"{publisher}; {year}.")
    elif year:
        chunks.append(f"{year}.")

    if pages:
        chunks.append(f"p. {pages}.")
    if url:
        chunks.append(f"Available from: {url}.")
    if doi:
        chunks.append(f"doi:{doi}.")

    return _collapse_spaces(" ".join(chunks))


# Preprint
def format_preprint_vancouver(n: "NormalizedInput") -> str:
    if _journal_like(n):
        return _render_vancouver_journal_like(n)

    return _render_vancouver_internet_like(n, bracket_label="Preprint")

# News
def format_news_vancouver(n: "NormalizedInput") -> str:
    if _journal_like(n):
        return _render_vancouver_journal_like(n)
    return _render_vancouver_internet_like(n, bracket_label="News")

# Media
def format_media_vancouver(n: "NormalizedInput") -> str:
    if _journal_like(n):
        return _render_vancouver_journal_like(n)
    return _render_vancouver_internet_like(n, bracket_label="Media", title_suffix=" [Media]")

# Webpage
def format_webpage_vancouver(n: "NormalizedInput") -> str:
    return _render_vancouver_internet_like(n, bracket_label="Internet")

# Dataset
def format_dataset_vancouver(n: "NormalizedInput") -> str:
    return _render_vancouver_internet_like(n, bracket_label="Dataset", title_suffix=" [Dataset]")

# Thesis
def format_thesis_vancouver(n: "NormalizedInput") -> str:
    authors = _format_authors(n.authors, max_authors=0)
    title = _safe_str(n.title).rstrip(".")
    year = _year(n)

    place = _safe_str(n.publisher_place)       
    university = _safe_str(n.publisher)      
    url = _safe_str(n.url)

    chunks = []
    if authors: chunks.append(f"{authors}.")
    if title: chunks.append(f"{title} [dissertation].")
    if place and university:
        if year:
            chunks.append(f"{place}: {university}; {year}.")
        else:
            chunks.append(f"{place}: {university}.")
    elif university:
        chunks.append(f"{university}.")
        if year:
            chunks.append(f"{year}.")
    elif year:
        chunks.append(f"{year}.")
    if url:
        chunks.append(f"Available from: {url}.")
    return _collapse_spaces(" ".join(chunks))

# Book
def format_book_vancouver(n: NormalizedInput) -> str:
    authors = _format_authors(n.authors, max_authors=0)
    title = _safe_str(n.title).rstrip(".")
    edition = _safe_str(n.edition)
    place = _safe_str(n.publisher_place)
    publisher = _safe_str(n.publisher)
    year = _year(n)
    url = _safe_str(n.url)
    doi = _get_id(n, "doi")

    chunks = []
    if authors: chunks.append(f"{authors}.")
    if title: chunks.append(f"{title}.")
    if edition: chunks.append(f"{edition}.")
    # 出版信息块
    if place and publisher:
        if year:
            chunks.append(f"{place}: {publisher}; {year}.")
        else:
            chunks.append(f"{place}: {publisher}.")
    elif publisher and year:
        chunks.append(f"{publisher}; {year}.")
    elif year:
        chunks.append(f"{year}.")
    if url:
        chunks.append(f"Available from: {url}.")
    if doi:
        chunks.append(f"doi:{doi}.")
    return _collapse_spaces(" ".join(chunks))

# Patent
def format_patent_vancouver(n: NormalizedInput) -> str:
    inventors = _format_authors(n.authors, max_authors=0)
    title = _safe_str(n.title).rstrip(".")

    country = _safe_str((n.extra or {}).get("patent_country")) or _safe_str((n.identifiers or {}).get("patent_country"))
    number = _safe_str((n.identifiers or {}).get("patent_number")) or _safe_str((n.identifiers or {}).get("patent"))
    assignee = _safe_str((n.extra or {}).get("assignee"))

    date = _safe_str(n.issued_date) or _year(n)

    url = _safe_str(n.url)

    chunks = []
    if inventors:
        chunks.append(f"{inventors}, inventor(s);")
    if assignee:
        chunks.append(f"{assignee}.")
    if title:
        chunks.append(f"{title}.")
    if country and number:
        chunks.append(f"{country} patent {number}.")
    elif number:
        chunks.append(f"Patent {number}.")
    if date:
        chunks.append(f"{date}.")
    if url:
        chunks.append(f"Available from: {url}.")
    return _collapse_spaces(" ".join(chunks))

# Other
def format_other_vancouver(n: NormalizedInput) -> str:
    authors = _format_authors(n.authors)
    title = _safe_str(n.title).rstrip(".")
    container = _safe_str(n.container_abbrev or n.container_title)
    year = _year(n)
    doi = _get_id(n, "doi")
    url = _safe_str(n.url)

    chunks = []
    if authors: chunks.append(f"{authors}.")
    if title: chunks.append(f"{title}.")
    if container: chunks.append(f"{container}.")
    if year: chunks.append(f"{year}.")
    if doi:
        chunks.append(f"doi:{doi}.")
    if url:
        chunks.append(f"Available from: {url}.")
    return _collapse_spaces(" ".join(chunks))

def _collapse_spaces(s: str) -> str:
    return " ".join((s or "").split())

def _get_id(n: "NormalizedInput", key: str) -> str:
    return (n.identifiers or {}).get(key, "") or ""

def _year(n: "NormalizedInput") -> str:
    if n.issued_year:
        return str(n.issued_year)
    if n.issued_date:
        return (n.issued_date or "")[:4]
    return ""

def _journal_like(n: "NormalizedInput") -> bool:
    has_container = bool((n.container_abbrev or n.container_title))
    has_locator = bool(n.volume or n.issue or n.pages or n.article_id)
    has_doi = bool(_get_id(n, "doi"))
    return has_container and (has_locator or has_doi)

def _format_authors(authors: List[Dict[str, str]], max_authors: int = 6) -> str:
    """
    Vancouver: Surname Initials, Surname Initials, ...; 超过 max_authors → et al.
    authors: [{'family':..., 'given':..., 'literal':...}]
    """
    if not authors:
        return ""

    def initials(given: str) -> str:
        """Extract initials from given name(s)."""
        given = (given or "").strip()
        if not given:
            return ""
        
        out = []
        for tok in given.replace(".", " ").split():
            if tok:
                # Handle hyphenated names like "Hans-Peter" -> "HP"
                for part in tok.split("-"):
                    if part:
                        out.append(part[0].upper())
        return "".join(out)

    parts = []
    for a in authors:
        family = (a.get("family") or "").strip()
        given = (a.get("given") or "").strip()
        literal = (a.get("literal") or "").strip()
        
        # Prefer family/given, fallback to literal
        if family:
            ini = initials(given)
            parts.append(f"{family} {ini}".strip())
        elif literal:
            # No family, use literal as-is
            parts.append(literal)

    if not parts:
        return ""

    if max_authors and len(parts) > max_authors:
        return ", ".join(parts[:max_authors]) + ", et al"
    return ", ".join(parts)

def _format_tail(n: "NormalizedInput") -> str:
    """
    Year;Volume(Issue):Pages OR Year;Volume:ArticleId（eLocator）
    """
    year = _year(n)
    vol = (n.volume or "").strip()
    iss = (n.issue or "").strip()
    loc = (n.pages or "").strip() or (n.article_id or "").strip()

    if not year:
        return ""

    vol_issue = ""
    if vol and iss:
        vol_issue = f"{vol}({iss})"
    elif vol:
        vol_issue = vol

    if vol_issue and loc:
        return f"{year};{vol_issue}:{loc}"
    if vol_issue:
        return f"{year};{vol_issue}"
    return year

def _render_vancouver_journal_like(n: "NormalizedInput") -> str:
    authors = _format_authors(n.authors)
    title = (n.title or "").strip().rstrip(".")
    journal = (n.container_abbrev or n.container_title or "").strip()
    tail = _format_tail(n)
    doi = _get_id(n, "doi")

    chunks = []
    if authors: chunks.append(f"{authors}.")
    if title: chunks.append(f"{title}.")
    if journal: chunks.append(f"{journal}.")
    if tail: chunks.append(f"{tail}.")
    out = " ".join(chunks).strip()

    if doi:
        out = out.rstrip(".") + f". doi:{doi}."
    return _collapse_spaces(out)

def _render_vancouver_internet_like(
    n: "NormalizedInput",
    *,
    bracket_label: str = "Internet",  
    title_suffix: str = "",          
) -> str:
    authors = _format_authors(n.authors)
    title = (n.title or "").strip().rstrip(".")
    container = (n.container_title or n.container_abbrev or "").strip()
    year = _year(n)
    url = (n.url or "").strip()
    cited = (n.accessed or "").strip()
    doi = _get_id(n, "doi")

    chunks = []
    if authors: chunks.append(f"{authors}.")
    if title:
        chunks.append(f"{title}{title_suffix}.")
    elif title_suffix:
        chunks.append(f"{title_suffix.strip()}.")  

    # Vancouver Internet
    if container:
        chunks.append(f"{container} [{bracket_label}].")
    else:
        chunks.append(f"[{bracket_label}].")

    # 年份与引用日期
    if year and cited:
        chunks.append(f"{year} [cited {cited}].")
    elif year:
        chunks.append(f"{year}.")
    elif cited:
        chunks.append(f"[cited {cited}].")

    if url:
        chunks.append(f"Available from: {url}.")
    if doi:
        chunks.append(f"doi:{doi}.")
    return _collapse_spaces(" ".join(chunks))

def _get_event_or_none(n: "NormalizedInput") -> Optional["EventInfo"]:
    return getattr(n, "event", None)