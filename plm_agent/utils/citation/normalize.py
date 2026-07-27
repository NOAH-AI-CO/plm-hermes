from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union, Iterable, Set
from datetime import datetime, timedelta
import re
from enum import Enum
from urllib.parse import urlparse

class SourceType(Enum):
    JOURNAL_ARTICLE = "journal_article"
    BOOK = "book"
    CONFERENCE = "conference"
    THESIS = "thesis"
    PREPRINT = "preprint"
    PATENT = "patent"
    WEBPAGE = "webpage"
    NEWS = "news"
    DATASET = "dataset"
    SOFTWARE = "software"
    MEDIA = "media"
    OTHER = "other"
    
@dataclass
class PersonName:
    family_name: str
    given_name: str = ""
    raw_name: str = ""

@dataclass
class EventInfo:
    """
    Conference / event metadata (NOT publisher metadata).
    """
    kind: str = "paper"
    name: str = ""        # conference name, e.g., "6th Digital Health Conference"
    date: str = ""        # e.g., "2024 Sep 13-15"
    location: str = ""    # e.g., "Taipei, Taiwan"
    editors: str = ""     # optional, e.g., "Chen Y, Liu R"

@dataclass
class NormalizedInput:
    source: str                          # 数据源：pubmed/crossref/...
    source_type: str                     # article-journal/book/chapter/...

    title: str = ""
    authors: List[Dict[str, str]] = field(default_factory=list)   # [{'family':..., 'given':..., 'literal':...}]
    container_title: Optional[str] = None
    container_abbrev: Optional[str] = None

    issued_year: Optional[int] = None
    issued_date: Optional[str] = None    # ISO YYYY-MM-DD

    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    article_id: Optional[str] = None     # eLocator/文章号

    publisher: Optional[str] = None
    publisher_place: Optional[str] = None
    edition: Optional[str] = None

    url: Optional[str] = None
    accessed: Optional[str] = None

    identifiers: Dict[str, str] = field(default_factory=dict)     # doi/pmid/pmcid/isbn/arxiv/...
    event: Optional[EventInfo] = None 
    extra: Dict[str, Any] = field(default_factory=dict)

def normalize_pubmed_es_doc(doc: Dict[str, Any]) -> NormalizedInput:
    st = _normalize_pubmed_source_type(doc.get("publication_type"))

    # authors: str | list[str]
    raw_authors = doc.get("author")
    author_literals: List[str] = []
    if isinstance(raw_authors, str):
        s = raw_authors.strip()
        if s:
            author_literals = [s]
    elif isinstance(raw_authors, list):
        author_literals = [_safe_str(x) for x in raw_authors if _safe_str(x)]

    authors_out: List[Dict[str, str]] = []
    for literal in author_literals:
        family, given = _normalize_pubmed_author(literal)
        authors_out.append({"family": family, "given": given, "literal": literal})

    container_abbrev = _safe_str(doc.get("journal_abbr")) or None
    container_title = _safe_str(doc.get("journal")) or None

    # issued_year
    issued_year = _try_int(doc.get("year_of_publication"))

    # issued_date: 优先 journal_pub_date，其次 pubmed_pub_date
    journal_date_raw = _safe_str(doc.get("journal_pub_date"))
    pubmed_date_raw = _safe_str(doc.get("pubmed_pub_date"))

    issued_date = None
    if journal_date_raw:
        issued_date = _normalize_iso_date(journal_date_raw[:10])
    if not issued_date and pubmed_date_raw:
        issued_date = _normalize_iso_date(pubmed_date_raw[:10])

    if issued_year is None and issued_date:
        issued_year = _try_int(issued_date[:4])

    # pagination -> pages/article_id
    pages, article_id = _normalize_pubmed_pagination(doc.get("pagination"))

    # identifiers
    identifiers: Dict[str, str] = {}
    pmid = _safe_str(doc.get("pmid"))
    if pmid:
        identifiers["pmid"] = pmid
    pmcid = _safe_str(doc.get("pmc_id"))
    if pmcid:
        identifiers["pmcid"] = pmcid
    doi = _safe_str(doc.get("doi"))
    if doi:
        identifiers["doi"] = doi

    # url
    url = _safe_str(doc.get("url")) or (f"https://doi.org/{doi}" if doi else None)

    # extra
    extra: Dict[str, Any] = {
        "language": doc.get("language"),
        "publication_type": doc.get("publication_type"),
        "journal_pub_date": doc.get("journal_pub_date"),
        "pubmed_pub_date": doc.get("pubmed_pub_date"),
        "grant_number": doc.get("grant_number"),
    }

    issn = _safe_str(doc.get("issn"))
    if issn:
        extra["issn"] = issn

    eissn = _safe_str(doc.get("essn") or doc.get("eissn") or doc.get("e_issn"))
    if eissn:
        extra["e_issn"] = eissn

    return NormalizedInput(
        source="pubmed_es",
        source_type=st.value,
        title=_safe_str(doc.get("title")),
        authors=authors_out,
        container_title=container_title,
        container_abbrev=container_abbrev,
        issued_year=issued_year,
        issued_date=issued_date,
        volume=_safe_str(doc.get("volume")) or None,
        issue=_safe_str(doc.get("issue")) or None,
        pages=pages,
        article_id=article_id,
        url=url,
        identifiers=identifiers,
        extra=extra,
    )

def _normalize_pubmed_source_type(publication_type: Union[None, str, Iterable[Any]]) -> "SourceType":
    def to_lower_set(x: Union[None, str, Iterable[Any]]) -> Set[str]:
        if x is None:
            return set()
        if isinstance(x, str):
            s = x.strip().lower()
            return {s} if s else set()
        out: Set[str] = set()
        for it in x:
            s = ("" if it is None else str(it)).strip().lower()
            if s:
                out.add(s)
        return out

    types = to_lower_set(publication_type)

    if "preprint" in types:
        return SourceType.PREPRINT
    if "newspaper article" in types or "news" in types:
        return SourceType.NEWS
    if types & {"congress", "conference", "clinical conference", "consensus development conference", "lecture"}:
        return SourceType.CONFERENCE
    if "dataset" in types:
        return SourceType.DATASET
    if types & {"video-audio media", "webcast"}:
        return SourceType.MEDIA

    return SourceType.JOURNAL_ARTICLE

def _normalize_pubmed_author(literal: str) -> Tuple[str, str]:
    """
    Parse PubMed author format: [Family Name(s)] [Given Name(s)] [Initial(s)]
    
    Examples:
        "Bénézit François F" -> ("Bénézit", "François")
        "Le Bot Audrey A" -> ("Le Bot", "Audrey")
        "Hartung Hans-Peter HP" -> ("Hartung", "Hans-Peter")
        "Barik Sandip Kumar SK" -> ("Barik", "Sandip Kumar")
    """
    UPPER_TOKEN_RE = re.compile(r"^[A-Z]{1,4}$")

    def given_initials(tokens: list[str]) -> str:
        initials: list[str] = []
        for tok in tokens:
            tok = tok.strip()
            if not tok:
                continue
            for part in tok.split("-"):
                part = part.strip()
                if part:
                    initials.append(part[0].upper())
        return "".join(initials)

    tokens = [t for t in (literal or "").strip().split() if t]
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""

    if len(tokens) == 2 and all(len(t) == 1 and t.isupper() for t in tokens):
        return "", ""
    
    last = tokens[-1]
    
    if UPPER_TOKEN_RE.match(last):
        for num_given_tokens in range(1, len(tokens) - 1):
            start_idx = len(tokens) - 1 - num_given_tokens
            given_candidates = tokens[start_idx:-1]
            
            if given_initials(given_candidates) == last:
                family_tokens = tokens[:start_idx]
                if family_tokens:
                    return " ".join(family_tokens), " ".join(given_candidates)
        
        if len(tokens) > 2:
            return tokens[0], " ".join(tokens[1:-1])
        else:
            return tokens[0], ""

    return tokens[0], " ".join(tokens[1:])

def _safe_str(x: Any) -> str:
    return ("" if x is None else str(x)).strip()

def _try_int(x: Any) -> Optional[int]:
    s = _safe_str(x)
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None

def _normalize_iso_date(s: str) -> Optional[str]:
    s = _safe_str(s)
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None

def _normalize_pubmed_pagination(pagination: Any) -> Tuple[Optional[str], Optional[str]]:
    """
    Pagination in PubMed can be pages or article_id
    """
    s = _safe_str(pagination)
    if not s:
        return None, None

    if "-" in s or "," in s:
        return s, None

    if s.isdigit():
        return None, s

    if re.match(r"^[A-Za-z][A-Za-z0-9.\-]*\d[A-Za-z0-9.\-]*$", s):
        return None, s

    return s, None

def normalize_patent(doc: Dict[str, Any]) -> NormalizedInput:
    title = _safe_str(doc.get("title"))

    inventors_raw = doc.get("inventor", "")
    inventor_list = _split_inventors(inventors_raw)

    authors_out: List[Dict[str, str]] = []
    for inv in inventor_list:
        inv = _safe_str(inv)
        if not inv:
            continue
        family, given = _normalize_patent_inventor(inv)
        authors_out.append({"family": family, "given": given, "literal": inv})

    assignee_raw = doc.get("assignee", "")
    publisher: Optional[str] = None
    if isinstance(assignee_raw, str):
        publisher = _safe_str(assignee_raw) or None
    elif isinstance(assignee_raw, list):
        assignee_list = [_safe_str(x) for x in assignee_raw if _safe_str(x)]
        if assignee_list:
            publisher = "; ".join(assignee_list)

    pub_date = _safe_str(doc.get("publication_date"))
    filing_date = _safe_str(doc.get("filing_date"))
    priority_date = _safe_str(doc.get("priority_date"))

    issued_date: Optional[str] = None
    issued_year: Optional[int] = None
    issued_date_kind: Optional[str] = None

    if pub_date:
        issued_date = _normalize_patent_date(pub_date)
        issued_date_kind = "publication_date"
    elif filing_date:
        issued_date = _normalize_patent_date(filing_date)
        issued_date_kind = "filing_date"
    elif priority_date:
        issued_date = _normalize_patent_date(priority_date)
        issued_date_kind = "priority_date"

    if issued_date:
        issued_year = _try_int(issued_date[:4])

    url = _safe_str(doc.get("patent_link") or doc.get("url")) or None

    identifiers: Dict[str, str] = {}

    patent_id = _safe_str(doc.get("patent_id"))
    if patent_id:
        identifiers["patent_id"] = patent_id

    publication_number = _safe_str(doc.get("publication_number"))
    if publication_number:
        identifiers["publication_number"] = publication_number
        identifiers["patent_number"] = publication_number

    extra: Dict[str, Any] = {
        "language": doc.get("language"),
        "publication_date": pub_date or None,
        "filing_date": filing_date or None,
        "priority_date": priority_date or None,
        "issued_date_kind": issued_date_kind,
        "assignee": publisher,
    }

    abstract = _safe_str(doc.get("snippet") or doc.get("abstract"))
    if abstract:
        extra["abstract"] = abstract

    patent_link = _safe_str(doc.get("patent_link"))
    if patent_link:
        extra["patent_link"] = patent_link

    return NormalizedInput(
        source="serpapi_patent",
        source_type=SourceType.PATENT.value,
        title=title,
        authors=authors_out,
        publisher=publisher,
        issued_year=issued_year,
        issued_date=issued_date,
        url=url,
        identifiers=identifiers,
        extra=extra,
    )

def _split_inventors(inventors_raw: Any) -> List[str]:
    if isinstance(inventors_raw, list):
        return [_safe_str(x) for x in inventors_raw if _safe_str(x)]

    s = _safe_str(inventors_raw)
    if not s:
        return []

    if ";" in s:
        return [x.strip() for x in s.split(";") if x.strip()]

    if re.search(r"\s+and\s+", s, flags=re.IGNORECASE):
        parts = re.split(r"\s+and\s+", s, flags=re.IGNORECASE)
        return [x.strip() for x in parts if x.strip()]

    if " & " in s:
        parts = [x.strip() for x in s.split(" & ") if x.strip()]
        if len(parts) > 1:
            return parts

    if s.count(',') == 1 and not s.startswith(',') and not s.endswith(','):
        return [s]

    if "," in s:
        return [x.strip() for x in s.split(",") if x.strip()]

    return [s]


def _normalize_patent_inventor(literal: str) -> Tuple[str, str]:
    """
    Conservative inventor parsing:
    - "Family, Given" -> (Family, Given)
    - Otherwise -> treat last token as family (Given ... Family)
      (Keeps literal anyway, so you can recover if needed)
    """
    s = _safe_str(literal)
    if not s:
        return "", ""

    if "," in s:
        family, given = s.split(",", 1)
        return family.strip(), given.strip()

    tokens = s.split()
    if len(tokens) == 1:
        return tokens[0], ""

    family = tokens[-1]
    given = " ".join(tokens[:-1])
    return family, given


def _normalize_patent_date(date_str: str) -> Optional[str]:
    s = _safe_str(date_str)
    if not s:
        return None

    s = re.sub(r"[^\d\-/]", "", s)

    if len(s) == 8 and s.isdigit():
        try:
            dt = datetime.strptime(s, "%Y%m%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None

    if "-" in s:
        out = _normalize_iso_date(s)
        if out:
            return out
        m = re.fullmatch(r"(\d{4})-(\d{2})", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}-01"

    # YYYY/MM/DD
    if "/" in s:
        try:
            dt = datetime.strptime(s, "%Y/%m/%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            m = re.fullmatch(r"(\d{4})/(\d{2})", s)
            if m:
                return f"{m.group(1)}-{m.group(2)}-01"

    if len(s) == 4 and s.isdigit():
        return f"{s}-01-01"

    return None

def normalize_news(doc: Dict[str, Any]) -> NormalizedInput:

    title = _safe_str(doc.get("title") or doc.get("name"))

    url = _safe_str(doc.get("link") or doc.get("url")) or None

    publisher: Optional[str] = None

    # Serper: "source"
    src = _safe_str(doc.get("source"))
    if src:
        publisher = src

    # Bing: "provider" can be list[dict] or dict
    if not publisher:
        providers = doc.get("provider")
        if isinstance(providers, dict):
            provider_name = _safe_str(providers.get("name"))
            if provider_name:
                publisher = provider_name
        elif isinstance(providers, list) and providers:
            first = providers[0]
            if isinstance(first, dict):
                provider_name = _safe_str(first.get("name"))
                if provider_name:
                    publisher = provider_name

    if not publisher and url:
        netloc = urlparse(url).netloc
        netloc = netloc[4:] if netloc.startswith("www.") else netloc
        publisher = netloc or None

    issued_date: Optional[str] = None
    issued_year: Optional[int] = None

    date_str = _safe_str(doc.get("date") or doc.get("datePublished"))
    if date_str:
        issued_date = _normalize_news_date(date_str)
        if issued_date:
            issued_year = _try_int(issued_date[:4])

    abstract = _safe_str(doc.get("snippet") or doc.get("description"))

    extra: Dict[str, Any] = {}
    if abstract:
        extra["abstract"] = abstract

    if date_str and issued_date and date_str != issued_date:
        extra["original_date"] = date_str

    image_url = _safe_str(doc.get("imageUrl") or doc.get("image_url"))
    if image_url:
        extra["image_url"] = image_url

    accessed = _today_iso()

    return NormalizedInput(
        source="news_api",
        source_type=SourceType.NEWS.value,
        title=title,
        authors=[],
        container_title=None,        
        container_abbrev=None,
        publisher=publisher,        
        issued_year=issued_year,
        issued_date=issued_date,
        url=url,
        accessed=accessed,
        identifiers={},
        extra=extra,
    )

def _today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _normalize_news_date(date_str: str) -> Optional[str]:
    s = _safe_str(date_str)
    if not s:
        return None

    # 1) ISO 8601 prefix: just take YYYY-MM-DD if present
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 2) Relative times: allow trailing text (e.g., "2 days ago · ...")
    rel = re.search(r"\b(\d+)\s+(hour|day|week|month)s?\s+ago\b", s, re.IGNORECASE)
    if rel:
        amount = int(rel.group(1))
        unit = rel.group(2).lower()
        now = datetime.now()

        if unit == "hour":
            dt = now - timedelta(hours=amount)
        elif unit == "day":
            dt = now - timedelta(days=amount)
        elif unit == "week":
            dt = now - timedelta(weeks=amount)
        elif unit == "month":
            dt = now - timedelta(days=amount * 30)  # 近似
        else:
            dt = now

        return dt.strftime("%Y-%m-%d")

    # 3) Common absolute formats
    for fmt in [
        "%B %d, %Y",   # January 15, 2024
        "%b %d, %Y",   # Jan 15, 2024
        "%d %B %Y",    # 15 January 2024
        "%d %b %Y",    # 15 Jan 2024
        "%m/%d/%Y",    # 01/15/2024
        "%d/%m/%Y",    # 15/01/2024
        "%Y/%m/%d",    # 2024/01/15
    ]:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # 4) Year-only fallback
    y = re.search(r"\b(20\d{2})\b", s)
    if y:
        return f"{y.group(1)}-01-01"

    return None

def normalize_web(doc: Dict[str, Any]) -> NormalizedInput:
    title = _safe_str(doc.get("title") or doc.get("name"))
    
    url = _safe_str(doc.get("link") or doc.get("url")) or None

    site_name: Optional[str] = None

    site_name = _safe_str(doc.get("siteName") or doc.get("site_name")) or None

    if not site_name and url:
        netloc = urlparse(url).netloc
        netloc = netloc[4:] if netloc.startswith("www.") else netloc
        site_name = netloc or None
    
    publisher = site_name
    
    issued_date: Optional[str] = None
    issued_year: Optional[int] = None

    attributes = doc.get("attributes", {})
    if isinstance(attributes, dict):
        for key in ["Date", "date", "Published", "published"]:
            date_val = _safe_str(attributes.get(key))
            if date_val:
                issued_date = _normalize_web_date(date_val)
                if issued_date:
                    issued_year = _try_int(issued_date[:4])
                    break
    
    # Bing dateLastCrawled (not publication date, but better than nothing)
    if not issued_date:
        date_crawled = _safe_str(doc.get("dateLastCrawled"))
        if date_crawled:
            issued_date = _normalize_web_date(date_crawled)
            if issued_date:
                issued_year = _try_int(issued_date[:4])
    
    # Abstract/description
    abstract = _safe_str(doc.get("snippet") or doc.get("summ") or doc.get("description"))
    
    # Extra fields
    extra: Dict[str, Any] = {}
    
    if abstract:
        extra["abstract"] = abstract
    
    # Store attributes if available
    if attributes and isinstance(attributes, dict):
        extra["attributes"] = attributes
    
    # Store site_name
    if site_name:
        extra["site_name"] = site_name
    
    # Accessed date
    accessed = _today_iso()
    
    return NormalizedInput(
        source="web_search",
        source_type=SourceType.WEBPAGE.value,
        title=title,
        authors=[],  # Web search results typically don't have structured author info
        container_title=None,
        container_abbrev=None,
        publisher=publisher,
        issued_year=issued_year,
        issued_date=issued_date,
        url=url,
        accessed=accessed,
        identifiers={},
        extra=extra,
    )

def _normalize_web_date(date_str: str) -> Optional[str]:
    """
    Normalize web page date to ISO format YYYY-MM-DD
    
    Handles various formats:
    - ISO 8601: 2024-01-15T10:30:00Z
    - Common formats: "January 15, 2024", "01/15/2024"
    """
    s = _safe_str(date_str)
    if not s:
        return None
    
    # ISO 8601 prefix
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    
    # Common date formats
    for fmt in [
        "%B %d, %Y",   # January 15, 2024
        "%b %d, %Y",   # Jan 15, 2024
        "%d %B %Y",    # 15 January 2024
        "%d %b %Y",    # 15 Jan 2024
        "%m/%d/%Y",    # 01/15/2024
        "%d/%m/%Y",    # 15/01/2024
        "%Y/%m/%d",    # 2024/01/15
        "%Y-%m-%d",    # 2024-01-15
    ]:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    # Year-only fallback
    y = re.search(r"\b(20\d{2})\b", s)
    if y:
        return f"{y.group(1)}-01-01"
    
    return None