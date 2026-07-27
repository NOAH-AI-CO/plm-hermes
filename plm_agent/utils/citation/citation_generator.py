"""
Citation generator for WebSearchLink objects
Converts WebSearchLink to Vancouver format (txt and bib)
"""

from typing import Dict, Any
from agent.explore.schema import WebSearchLink, SearchType
from utils.citation.normalize import (
    NormalizedInput,
    normalize_pubmed_es_doc,
    normalize_patent,
    normalize_news,
    normalize_web,
)
from utils.citation.vancouver import format_vancouver
from utils.citation.export import export_bibtex


def generate_citation(link: WebSearchLink) -> Dict[str, str]:
    """
    Generate Vancouver citation (txt and bib) for a WebSearchLink
    
    Args:
        link: WebSearchLink object with search result data
        
    Returns:
        Dict with "txt" and "bib" keys containing formatted citations
        Returns empty dict if citation cannot be generated
    """
    try:
        # Convert WebSearchLink to appropriate input format based on SearchType
        normalized = _websearchlink_to_normalized(link)
        
        if normalized is None:
            return {}
        
        # Generate txt format (Vancouver style)
        txt = format_vancouver(normalized)
        
        # Generate bib format (BibTeX)
        bib = export_bibtex([normalized]).strip()
        
        return {
            "txt": txt,
            "bib": bib
        }
    except Exception as e:
        # Log error but don't crash
        import logging
        logging.warning(f"Failed to generate citation for {link.url}: {e}")
        return {}


def _websearchlink_to_normalized(link: WebSearchLink) -> NormalizedInput:
    """
    Convert WebSearchLink to NormalizedInput based on SearchType
    """
    search_type = link.type
    
    if search_type == SearchType.PUBMED:
        return _convert_pubmed(link)
    elif search_type == SearchType.PATENT:
        return _convert_patent(link)
    elif search_type == SearchType.NEWS:
        return _convert_news(link)
    elif search_type == SearchType.WEB:
        return _convert_web(link)
    else:
        # For other types, treat as web page
        return _convert_web(link)


def _convert_pubmed(link: WebSearchLink) -> NormalizedInput:
    """Convert PubMed WebSearchLink to NormalizedInput"""
    doc = {
        "title": link.title,
        "abstract": link.summ,
        "pmid": link.pubmed_id,
        "pmc_id": link.pmcid,
        "doi": link.doi,
        "author": [a.strip() for a in link.author.split(",")] if link.author else [],
        "journal": link.full_journal_name,
        "journal_abbr": link.full_journal_name,  # Fallback
        "issn": link.issn,
        "essn": link.essn,
        "pubmed_pub_date": link.pub_date,
        "url": link.url,
    }
    
    # Parse volume, issue, pagination from summ if available
    # This is a simplified approach - may need enhancement
    if link.summ:
        import re
        # Try to extract year
        year_match = re.search(r'\b(19|20)\d{2}\b', link.summ)
        if year_match:
            doc["year_of_publication"] = year_match.group(0)
        
        # Try to extract volume/issue/pages pattern like "2024;15(3):123-456"
        vol_match = re.search(r';(\d+)\((\d+)\):([0-9\-]+)', link.summ)
        if vol_match:
            doc["volume"] = vol_match.group(1)
            doc["issue"] = vol_match.group(2)
            doc["pagination"] = vol_match.group(3)
    
    return normalize_pubmed_es_doc(doc)


def _convert_patent(link: WebSearchLink) -> NormalizedInput:
    """Convert Patent WebSearchLink to NormalizedInput"""
    doc = {
        "title": link.title,
        "snippet": link.summ,
        "patent_link": link.url,
        "patent_id": link.patent_id,
    }
    
    # Try to extract structured data from summ
    # Patent data is often concatenated in summ field
    if link.summ:
        import re
        
        # Extract inventor
        inv_match = re.search(r'inventor:\s*([^,]+)', link.summ, re.IGNORECASE)
        if inv_match:
            doc["inventor"] = inv_match.group(1).strip()
        
        # Extract assignee
        ass_match = re.search(r'assignee:\s*([^,]+)', link.summ, re.IGNORECASE)
        if ass_match:
            doc["assignee"] = ass_match.group(1).strip()
        
        # Extract publication_date
        pub_match = re.search(r'publication_date:\s*([^,]+)', link.summ, re.IGNORECASE)
        if pub_match:
            doc["publication_date"] = pub_match.group(1).strip()
        
        # Extract filing_date
        fil_match = re.search(r'filing_date:\s*([^,]+)', link.summ, re.IGNORECASE)
        if fil_match:
            doc["filing_date"] = fil_match.group(1).strip()
        
        # Extract publication_number
        num_match = re.search(r'publication_number:\s*([^,]+)', link.summ, re.IGNORECASE)
        if num_match:
            doc["publication_number"] = num_match.group(1).strip()
        
        # Extract language
        lang_match = re.search(r'language:\s*([^,]+)', link.summ, re.IGNORECASE)
        if lang_match:
            doc["language"] = lang_match.group(1).strip()
    
    return normalize_patent(doc)


def _convert_news(link: WebSearchLink) -> NormalizedInput:
    """Convert News WebSearchLink to NormalizedInput"""
    doc = {
        "title": link.title,
        "link": link.url,
        "snippet": link.summ,
        "source": link.site_name,
    }
    
    # Try to extract date from summ
    if link.pub_date:
        doc["date"] = link.pub_date
    elif link.summ:
        import re
        # Look for date patterns in summ
        date_match = re.search(r'date:\s*([^,]+)', link.summ, re.IGNORECASE)
        if date_match:
            doc["date"] = date_match.group(1).strip()
    
    return normalize_news(doc)


def _convert_web(link: WebSearchLink) -> NormalizedInput:
    """Convert Web WebSearchLink to NormalizedInput"""
    doc = {
        "title": link.title,
        "link": link.url,
        "snippet": link.summ,
        "site_name": link.site_name,
    }
    
    return normalize_web(doc)

