# -*- coding: utf-8 -*-
"""
Local CLI command router for NSFC V3 agents.

Intercepts shell commands matching LOCAL_CLI_COMMANDS and executes them
in-process (no subprocess, no file I/O). All other commands are forwarded
to the sandbox via the injected executor callable.
"""

import json
import logging
from typing import Awaitable, Callable

from agent.nsfc.nsfc_query_database import (
    keyword_search_nsfc,
    vector_search_pubmed,
    rank_pubmed_records_with_if,
)
from utils.pubmed_opt.pubmed_search import PubMedSearch
from tools.explore.attachment_tools import AttachmentDownload

logger = logging.getLogger(__name__)

LOCAL_CLI_COMMANDS = frozenset({
    "nsfc-search",
    "literature-pool",
    "pubmed-search",
    "attachment-download",
})


def is_local_cli(command: str) -> bool:
    """Check if a shell command starts with a local CLI command name."""
    first_token = command.strip().split()[0] if command.strip() else ""
    return first_token in LOCAL_CLI_COMMANDS


def parse_command(raw: str) -> tuple[str, dict]:
    """Parse 'command-name \'{"key": "value"}\'' into (name, args_dict).

    Returns (name, {}) on parse failure.
    """
    raw = raw.strip()
    parts = raw.split(None, 1)
    name = parts[0] if parts else ""
    if len(parts) < 2:
        return name, {}

    arg_str = parts[1].strip()
    # Strip surrounding single quotes
    if arg_str.startswith("'") and arg_str.endswith("'"):
        arg_str = arg_str[1:-1]
    # Strip surrounding double quotes (sometimes LLMs use them)
    elif arg_str.startswith('"') and arg_str.endswith('"'):
        arg_str = arg_str[1:-1]
        # Unescape inner quotes
        arg_str = arg_str.replace('\\"', '"')

    try:
        args = json.loads(arg_str)
        if not isinstance(args, dict):
            return name, {}
        return name, args
    except (json.JSONDecodeError, ValueError):
        return name, {}


async def execute_local_cli(command: str) -> str:
    """Execute a local CLI command and return text output."""
    name, args = parse_command(command)
    if not name or name not in LOCAL_CLI_COMMANDS:
        return f"Error: Unknown local CLI command '{name}'"

    try:
        if name == "nsfc-search":
            return await _handle_nsfc_search(args)
        elif name == "literature-pool":
            return await _handle_literature_pool(args)
        elif name == "pubmed-search":
            return await _handle_pubmed_search(args)
        elif name == "attachment-download":
            return await _handle_attachment_download(args)
        else:
            return f"Error: Unhandled command '{name}'"
    except Exception as e:
        logger.error(f"[LocalCLI] Command '{name}' failed: {e}")
        return f"Error executing {name}: {str(e)}"


async def route_shell_commands(
    commands: list[str],
    sandbox_execute: Callable[[str], Awaitable[dict]],
) -> str:
    """Route each command: local CLI -> local execution, others -> sandbox.

    Args:
        commands: List of shell command strings.
        sandbox_execute: Callable that executes a command in the sandbox.
            Signature: async (cmd: str) -> dict with keys stdout, stderr, exit_code.

    Returns concatenated output from all commands.
    """
    output_parts = []
    for cmd in commands:
        if is_local_cli(cmd):
            logger.info(f"[LocalCLI] Routing locally: {cmd[:200]}")
            result = await execute_local_cli(cmd)
            output_parts.append(result)
        else:
            logger.info(f"[LocalCLI] Routing to sandbox: {cmd[:200]}")
            result = await sandbox_execute(cmd)
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            exit_code = result.get("exit_code", -1)
            parts = []
            if stdout:
                parts.append(stdout)
            if stderr:
                parts.append(f"STDERR: {stderr}")
            if exit_code != 0:
                parts.append(f"Exit code: {exit_code}")
            output_parts.append("\n".join(parts) if parts else "(no output)")

    return "\n".join(output_parts) if output_parts else "(no output)"


# ============================================================
# CLI Handlers
# ============================================================

async def _handle_nsfc_search(args: dict) -> str:
    """nsfc-search: keyword search NSFC projects."""
    keywords = args.get("keywords", [])
    if not keywords:
        return "Error: 'keywords' is required.\nUsage: nsfc-search '{\"keywords\": [\"cancer\", \"immunotherapy\"]}'"

    start_year = args.get("start_year", 2020)
    top_k = args.get("top_k", 50)

    logger.info(f"[LocalCLI:nsfc-search] keywords={keywords}, start_year={start_year}, top_k={top_k}")

    records = keyword_search_nsfc(keywords=keywords, start_year=start_year, top_k=top_k)

    if not records:
        return f"No NSFC projects found for keywords: {keywords}"

    lines = [f"Found {len(records)} NSFC projects:\n"]
    for i, rec in enumerate(records, 1):
        name = rec.get("projectName", "")
        pi = rec.get("projectAdmin", "")
        unit = rec.get("dependUnit", "")
        kws = rec.get("keywordList", [])
        start = str(rec.get("researchTimeStart", ""))[:10]
        end = str(rec.get("researchTimeEnd", ""))[:10]
        ratify = rec.get("ratifyNo", "")
        ptype = rec.get("type", "")
        code = rec.get("code", "")
        abstract = (rec.get("projectAbstractC", "") or "")[:500]
        conclusion = (rec.get("conclusionAbstract", "") or "")[:300]
        score = rec.get("_score")

        lines.append(f"[{i}] {name}")
        lines.append(f"    PI: {pi} | Unit: {unit}")
        lines.append(f"    Keywords: {', '.join(kws) if kws else 'N/A'}")
        lines.append(f"    Period: {start} ~ {end} | No: {ratify}")
        if ptype or code:
            lines.append(f"    Type: {ptype} | Code: {code}")
        if score is not None:
            lines.append(f"    Score: {score}")
        if abstract:
            lines.append(f"    Abstract: {abstract}")
        if conclusion:
            lines.append(f"    Conclusion: {conclusion}")
        lines.append("")

    return "\n".join(lines)


async def _handle_literature_pool(args: dict) -> str:
    """literature-pool: vector search PubMed + rank by IF."""
    keywords = args.get("keywords", [])
    if not keywords:
        return "Error: 'keywords' is required.\nUsage: literature-pool '{\"keywords\": [\"EGFR\", \"lung cancer\"]}'"

    years = args.get("years", [2021, 2022, 2023, 2024, 2025])
    max_papers = args.get("max_papers", 40)

    logger.info(f"[LocalCLI:literature-pool] keywords={keywords}, years={years}, max_papers={max_papers}")

    records = vector_search_pubmed(
        inputs=keywords,
        search_years=years,
        top_k=max(max_papers * 3, 120),
    )

    if records:
        ranked = rank_pubmed_records_with_if(records, max_papers=max_papers)
    else:
        ranked = []

    if not ranked:
        return f"No PubMed articles found for keywords: {keywords}"

    snippets = []
    for idx, rec in enumerate(ranked, start=1):
        authors = rec.get("author", "") or rec.get("authors", "")
        if isinstance(authors, list):
            author_names = []
            for a in authors[:3]:
                if isinstance(a, dict):
                    name = a.get("name") or a.get("full_name") or a.get("last_name") or ""
                else:
                    name = str(a)
                if name.strip():
                    author_names.append(name.strip())
            authors_str = ", ".join(author_names)
            if len(rec.get("authors", [])) > 3:
                authors_str += " et al"
        else:
            authors_str = str(authors)

        title = rec.get("title", "Untitled")
        journal = rec.get("journal", "") or rec.get("fulljournalname", "")
        year = str(rec.get("year_of_publication", "") or rec.get("pubdate", ""))[:4]
        pmid = rec.get("pmid", "")
        doi = rec.get("doi", "")
        abstract = (rec.get("abstract", "") or "")[:300]
        jif = rec.get("jif_value", 0)

        snippet = f"[{idx}] {authors_str}. {title}. {journal}. {year}."
        if pmid:
            snippet += f" PMID: {pmid}."
        if doi:
            snippet += f" doi: {doi}."
        if jif:
            snippet += f" (IF: {jif:.1f})"
        if abstract:
            snippet += f"\n    Abstract: {abstract}"

        snippets.append(snippet)

    return f"Literature pool: {len(snippets)} papers\n\n" + "\n\n".join(snippets)


async def _handle_pubmed_search(args: dict) -> str:
    """pubmed-search: hybrid search PubMed articles."""
    query = args.get("pubmed_query", "")
    if not query:
        return "Error: 'pubmed_query' is required.\nUsage: pubmed-search '{\"pubmed_query\": \"EGFR lung cancer\"}'"

    years = args.get("years", [])

    logger.info(f"[LocalCLI:pubmed-search] query={query}, years={years}")

    searcher = PubMedSearch()
    results = await searcher.hybrid_search(query=query, years=years)

    if not results:
        return f"No PubMed articles found for query: {query}"

    lines = [f"Found {len(results)} PubMed articles:\n"]
    for i, rec in enumerate(results, 1):
        title = rec.get("title", "Untitled")
        pmid = rec.get("pmid", "")
        abstract = (rec.get("abstract", "") or "")[:400]
        journal = rec.get("journal", "") or rec.get("fulljournalname", "")
        year = str(rec.get("year_of_publication", "") or rec.get("pubdate", ""))[:4]
        authors = rec.get("author", "") or rec.get("authors", "")
        if isinstance(authors, list):
            authors = ", ".join(str(a.get("name", a) if isinstance(a, dict) else a) for a in authors[:3])
            if len(rec.get("authors", [])) > 3:
                authors += " et al"

        lines.append(f"[{i}] {title}")
        lines.append(f"    Authors: {authors}")
        lines.append(f"    Journal: {journal} ({year}) | PMID: {pmid}")
        if abstract:
            lines.append(f"    Abstract: {abstract}")
        lines.append("")

    return "\n".join(lines)


async def _handle_attachment_download(args: dict) -> str:
    """attachment-download: download and parse attachments."""
    urls = args.get("urls", [])
    if not urls:
        return "Error: 'urls' is required.\nUsage: attachment-download '{\"urls\": [\"https://...\"]}'"

    logger.info(f"[LocalCLI:attachment-download] Downloading {len(urls)} attachments")

    tool = AttachmentDownload()
    results = []
    async for chunk in tool.run(
        urls=urls,
        explanation="CLI download",
        _context=type("Ctx", (), {"id": "", "call_id": ""})(),
    ):
        if hasattr(chunk, "result"):
            results = chunk.result if isinstance(chunk.result, list) else [chunk.result]

    if not results:
        return "No attachments downloaded."

    lines = [f"Downloaded {len(results)} attachment(s):\n"]
    for r in results:
        if not isinstance(r, dict):
            continue
        success = r.get("success", False)
        fname = r.get("filename", "unknown")
        if success:
            lines.append(f"  {fname} (type: {r.get('type', 'unknown')})")
            if r.get("blob_path"):
                lines.append(f"    blob_path: {r['blob_path']}")
            preview = r.get("text_preview", "")
            if preview:
                lines.append(f"    Preview: {preview[:500]}")
            desc = r.get("data_description", "")
            if desc:
                lines.append(f"    Description: {desc}")
        else:
            lines.append(f"  {fname} - FAILED: {r.get('error', 'unknown error')}")
        lines.append("")

    return "\n".join(lines)
