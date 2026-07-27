# -*- coding: utf-8 -*-
"""
Format PubMed records (list[dict]) into Vancouver style references.

Vancouver style rules implemented here:
- Authors: list up to 6 authors; if >6, list first 6 then 'et al.'
- Author format: Surname Initials (no periods in initials), authors separated by ', '
- Title: keep as-is, end with a period.
- Journal: prefer Medline abbreviation (journal_abbr), fallback to full journal.
- Year;volume(issue):pages.
- Pages: use numeric range like 101-108; if an article number (e.g., 'e12345' / 'ltad030'),
  render as ':e12345' (no pages).
- DOI (optional): append 'doi:10.xxxx/xxxxx.' if present.

Input example (each record dict may contain keys):
  'author' (List[str]), 'title', 'journal_abbr', 'journal', 'journal_pub_date', 'year_of_publication',
  'volume', 'issue', 'pagination', 'doi', 'pmid', etc.
"""

from typing import List, Dict, Optional, Tuple
import re

def _safe_get(d: Dict, *keys, default: Optional[str] = None) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default

def _extract_year(rec: Dict) -> Optional[str]:
    # Prefer journal_pub_date like '2024-09-28'; fallback to year_of_publication
    jp = rec.get("journal_pub_date")
    if isinstance(jp, str) and jp:
        m = re.search(r"\b(\d{4})\b", jp)
        if m:
            return m.group(1)
    yp = rec.get("year_of_publication")
    if isinstance(yp, str) and re.fullmatch(r"\d{4}", yp):
        return yp
    return None

def _normalize_author(name: str) -> Optional[str]:
    """
    Convert variants like 'Presley Carolyn J CJ' -> 'Presley CJ'
    Rules:
      - First token is taken as surname.
      - If last token looks like initials (all caps, ≤3 chars), ignore it (it's duplicate from ES)
      - Extract initials from middle tokens only.
      - No dots between initials (Vancouver).
    
    Examples:
      - 'Hirsch Pierre P' -> 'Hirsch P' (ignore last 'P')
      - 'Marie Jean Pierre JP' -> 'Marie JP' (ignore last 'JP')
      - 'Abbi Kamal K S KK' -> 'Abbi KS' (ignore last 'KK')
    """
    if not isinstance(name, str):
        return None
    parts = [p for p in name.replace(",", " ").split() if p]
    if not parts:
        return None
    
    surname = parts[0]
    middle_parts = parts[1:]
    
    # 如果最后一个部分看起来像首字母缩写（全大写且≤3个字符），就忽略它
    if middle_parts and len(middle_parts[-1]) <= 3 and middle_parts[-1].isupper():
        middle_parts = middle_parts[:-1]
    
    # 从剩余的中间部分提取首字母
    initials = "".join(ch[0] for p in middle_parts for ch in [p] if ch and ch[0].isalpha())
    return f"{surname} {initials}".strip()

def _format_authors_vancouver(auth_list: List[str]) -> str:
    if not auth_list:
        return ""
    normed = [_normalize_author(a) for a in auth_list if a]
    normed = [a for a in normed if a]
    if not normed:
        return ""
    if len(normed) > 6:
        normed = normed[:6] + ["et al."]
    return ", ".join(normed)

def _split_pagination(pagination: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Return (pages, article_id)
    - Pages if numeric or range like '101-108' or '1176-1178'
    - Otherwise treat as article_id (e.g., 'e12345', 'ltad030')
    """
    if not isinstance(pagination, str) or not pagination.strip():
        return None, None
    s = pagination.strip()
    if re.fullmatch(r"\d+(-\d+)?", s):
        return s, None
    return None, s  # non-numeric -> article number/id

def vancouver_format_one(rec: Dict) -> str:
    authors = _format_authors_vancouver(rec.get("author") or [])
    title = (_safe_get(rec, "title", default="") or "").rstrip(".")
    journal = _safe_get(rec, "journal_abbr", "journal", default="") or ""
    year = _extract_year(rec) or ""
    volume = _safe_get(rec, "volume", default="") or ""
    issue = _safe_get(rec, "issue", default="") or ""
    pagination = rec.get("pagination")
    pages, article_id = _split_pagination(pagination)
    doi = _safe_get(rec, "doi", default="") or ""

    # Authors. Title. Journal. Year;volume(issue):pages/article.
    segs: List[str] = []

    if authors:
        segs.append(f"{authors}.")
    if title:
        segs.append(f"{title}.")
    if journal:
        segs.append(f"{journal}.")
    # Year;volume(issue):pages/article
    yi = ""
    if year:
        yi += year
    if volume:
        yi += f";{volume}" if yi else volume
    if issue:
        yi += f"({issue})"
    
    # 只有当有 pages 或 article_id 时才添加年份/卷号信息和冒号
    if pages or article_id:
        if yi:
            yi += ":"
            segs.append(yi)
        # pages or article number
        if pages:
            segs.append(f"{pages}.")
        elif article_id:
            # Vancouver with article number: Year;vol(issue):e12345.
            segs.append(f"{article_id}.")
    elif yi:
        # 如果有年份/卷号但没有页码，直接添加（不加冒号）
        segs.append(f"{yi}.")

    # DOI
    if doi:
        doi_clean = doi.strip().rstrip(".")
        segs.append(f"doi:{doi_clean}.")

    # Join and tidy spaces
    out = " ".join(segs)
    out = re.sub(r"\s+\.", ".", out).strip()
    return out

def vancouver_format_list(records: List[Dict]) -> List[str]:
    out = []
    for rec in records:
        try:
            out.append(vancouver_format_one(rec))
        except Exception as e:
            out.append(f"[format error] {e}")
    return out


# ---------- Name helpers for Bib/RIS ----------
def _split_name_for_bib(name: str) -> Optional[Tuple[str, str]]:
    """
    将任意输入粗略拆成 (surname, given).
    规则：第一个 token 视为姓，其余视为名；名用空格拼接（或保留原始大写首字母）。
    """
    if not isinstance(name, str):
        return None
    parts = [p for p in name.replace(",", " ").split() if p]
    if not parts:
        return None
    surname = parts[0]
    given_parts = parts[1:]
    given = " ".join(given_parts)
    return surname, given

def _format_bibtex_authors(auth_list: List[str]) -> str:
    """
    BibTeX 作者串： 'Surname, Given and Surname, Given ...'
    """
    out = []
    for a in (auth_list or []):
        sp = _split_name_for_bib(a)
        if not sp:
            continue
        s, g = sp
        if g:
            out.append(f"{s}, {g}")
        else:
            out.append(s)
    return " and ".join(out)

def _make_bibtex_key(rec: Dict, idx: int = 1) -> str:
    """
    生成简易 BibTeX key：FirstAuthorSurnameYYYY[abbrtitle]
    提示：真实项目中建议做去重与冲突处理，这里给一个稳妥的默认。
    """
    year = _extract_year(rec) or "n.d."
    authors = rec.get("author") or []
    first = authors[0] if authors else "Anon"
    sp = _split_name_for_bib(first) or ("Anon", "")
    surname = re.sub(r"[^A-Za-z0-9]+", "", sp[0])
    title = _safe_get(rec, "title", default="") or ""
    abbr = re.sub(r"[^A-Za-z0-9]+", "", title.lower())[:8]
    key = f"{surname}{year}{abbr}"
    if not key:
        key = f"ref{idx}"
    return key

# ---------- BibTeX ----------
def bibtex_entry(rec: Dict, idx: int = 1) -> str:
    """
    生成单条 BibTeX 条目（@article）。
    兼容字段：author/title/journal_abbr/journal/year/volume/issue/pagination/doi/pmid
    """
    entry_type = "article"
    key = _make_bibtex_key(rec, idx)

    authors = _format_bibtex_authors(rec.get("author") or [])
    title = (_safe_get(rec, "title", default="") or "").rstrip(".")
    journal = _safe_get(rec, "journal_abbr", "journal", default="") or ""
    year = _extract_year(rec) or ""
    volume = _safe_get(rec, "volume", default="") or ""
    number = _safe_get(rec, "issue", default="") or ""
    pages, article_id = _split_pagination(rec.get("pagination"))
    doi = _safe_get(rec, "doi", default="") or ""
    pmid = _safe_get(rec, "pmid", default="") or ""

    fields = []
    if authors: fields.append(("author", authors))
    if title: fields.append(("title", title))
    if journal: fields.append(("journal", journal))
    if year: fields.append(("year", year))
    if volume: fields.append(("volume", volume))
    if number: fields.append(("number", number))
    if pages: fields.append(("pages", pages))
    elif article_id: fields.append(("pages", article_id))  # 一些样式会接受 article number 放 pages
    if doi: fields.append(("doi", doi))
    if pmid: fields.append(("pmid", pmid))

    # 统一转义花括号等：这里只简单处理 title 的花括号保护（可按需扩展）
    def _esc(s: str) -> str:
        return s.replace("{", "\\{").replace("}", "\\}")

    body = ",\n  ".join([f"{k} = {{{_esc(v)}}}" for k, v in fields if v])
    return f"@{entry_type}{{{key},\n  {body}\n}}"

def bibtex_export(records: List[Dict]) -> str:
    return "\n\n".join(bibtex_entry(r, i+1) for i, r in enumerate(records))

# ---------- RIS ----------
def ris_entry(rec: Dict) -> str:
    """
    生成单条 RIS（期刊文章类型：TY 取 JOUR）。
    字段映射：AU, TI, T2(期刊), PY, VL, IS, SP, EP, DO, ID(PMID)
    """
    authors = rec.get("author") or []
    title = (_safe_get(rec, "title", default="") or "").rstrip(".")
    journal = _safe_get(rec, "journal_abbr", "journal", default="") or ""
    year = _extract_year(rec) or ""
    volume = _safe_get(rec, "volume", default="") or ""
    issue = _safe_get(rec, "issue", default="") or ""
    pages, article_id = _split_pagination(rec.get("pagination"))
    doi = _safe_get(rec, "doi", default="") or ""
    pmid = _safe_get(rec, "pmid", default="") or ""

    lines = []
    lines.append("TY  - JOUR")
    for a in authors:
        sp = _split_name_for_bib(a)
        if sp:
            s, g = sp
            # RIS 作者格式常见写法：'Surname, Given'
            lines.append(f"AU  - {s}, {g}" if g else f"AU  - {s}")
    if title: lines.append(f"TI  - {title}")
    if journal: lines.append(f"T2  - {journal}")
    if year: lines.append(f"PY  - {year}")
    if volume: lines.append(f"VL  - {volume}")
    if issue: lines.append(f"IS  - {issue}")
    if pages:
        # 页码如 101-108 → SP, EP
        if "-" in pages:
            sp, ep = pages.split("-", 1)
            lines.append(f"SP  - {sp}")
            lines.append(f"EP  - {ep}")
        else:
            lines.append(f"SP  - {pages}")
    elif article_id:
        # 若为 article number，一些 RIS 消费方会把它放在 SP 或 EP；这里放在 SP
        lines.append(f"SP  - {article_id}")
    if doi: lines.append(f"DO  - {doi}")
    if pmid: lines.append(f"ID  - {pmid}")
    lines.append("ER  - ")
    return "\n".join(lines)

def ris_export(records: List[Dict]) -> str:
    return "\n\n".join(ris_entry(r) for r in records)

# ---------- CSL-JSON ----------
def csljson_one(rec: Dict) -> Dict:
    """
    生成单条 CSL-JSON（适配 Zotero/CSL）
    https://citationstyles.org/
    """
    authors = []
    for a in (rec.get("author") or []):
        sp = _split_name_for_bib(a)
        if not sp:
            continue
        s, g = sp
        authors.append({"family": s, "given": g})

    title = (_safe_get(rec, "title", default="") or "").rstrip(".")
    journal = _safe_get(rec, "journal_abbr", "journal", default="")
    year = _extract_year(rec)
    volume = _safe_get(rec, "volume", default="")
    issue = _safe_get(rec, "issue", default="")
    pages, article_id = _split_pagination(rec.get("pagination"))
    doi = _safe_get(rec, "doi", default="")
    pmid = _safe_get(rec, "pmid", default="")

    # note: CSL-JSON 推荐把 article number 放在 'page' 或 'article-number'
    page_field = pages or None
    article_number = article_id or None

    item = {
        "type": "article-journal",
        "title": title or None,
        "author": authors or None,
        "container-title": journal or None,
        "issued": {"date-parts": [[int(year)]]} if year and year.isdigit() else None,
        "volume": volume or None,
        "issue": issue or None,
        "page": page_field,
        "article-number": article_number,
        "DOI": (doi or None),
        "PMID": (pmid or None),
    }
    # 清理空字段
    return {k: v for k, v in item.items() if v}

def csljson_export(records: List[Dict]) -> List[Dict]:
    return [csljson_one(r) for r in records]

# ----------------------------
# Example usage:
# records = [...]  # your list of dicts from PubMed
# refs = vancouver_format_list(records)
# for i, r in enumerate(refs, 1):
#     print(f"[{i}] {r}")