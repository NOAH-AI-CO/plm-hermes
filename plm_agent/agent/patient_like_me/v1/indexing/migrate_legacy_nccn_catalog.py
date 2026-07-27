"""Bootstrap PLM NCCN candidate cards from the legacy ``guidelines`` index.

The legacy catalogue already contains NCCN metadata and title vectors, but it
uses different field names from the PLM ``plm_guidelines`` retrieval contract.
This migration copies only the candidate-selection fields; it does not invent
decision graphs or page chunks.

Run inside the PLM engine container after configuring ``api_config.ES_HOST``:

    python -m agent.patient_like_me.v1.indexing.migrate_legacy_nccn_catalog
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime

from elasticsearch import helpers

from agent.patient_like_me.v1.es.plm_index import PLM_INDEX, ensure_plm_index, get_es_client


LEGACY_INDEX = "guidelines"
NCCN_RE = re.compile(r"\bNCCN\b", re.IGNORECASE)
VERSION_RE = re.compile(r"(?:20\d{2})\s*[.\-_ ]*V\s*(\d+)", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _document_year(source: dict) -> int | None:
    value = str(source.get("publish_date") or "")
    match = YEAR_RE.search(value)
    if match:
        return int(match.group(1))
    title = " ".join(str(source.get(key) or "") for key in ("title_cn", "title_en"))
    match = YEAR_RE.search(title)
    return int(match.group(1)) if match else None


def _document_version(source: dict) -> int | None:
    title = " ".join(str(source.get(key) or "") for key in ("title_cn", "title_en"))
    match = VERSION_RE.search(title)
    return int(match.group(1)) if match else None


def _is_nccn(source: dict) -> bool:
    return NCCN_RE.search(" ".join(str(source.get(key) or "") for key in ("title_cn", "title_en", "file_name"))) is not None


def _migration_action(hit: dict) -> dict | None:
    source = hit.get("_source") or {}
    if not _is_nccn(source):
        return None
    title = str(source.get("title_cn") or source.get("title_en") or source.get("file_name") or "").strip()
    title_vector = source.get("title_cn_vector") or source.get("title_en_vector")
    if not title or not isinstance(title_vector, list) or len(title_vector) != 1024:
        return None
    doc_id = source.get("id") or hit.get("_id")
    try:
        doc_id = int(doc_id)
    except (TypeError, ValueError):
        return None
    content = str(source.get("content") or "")
    toc = str(source.get("toc") or "")
    summary = content[:3000] or toc or title
    return {
        "_op_type": "index",
        "_index": PLM_INDEX,
        "_id": str(doc_id),
        "_source": {
            "doc_id": doc_id,
            "filename": title,
            "file_path": str(source.get("file_url") or ""),
            "is_cn_content": bool(source.get("title_cn")),
            "guideline_key": title,
            "organization": "NCCN",
            "year": _document_year(source),
            "version": _document_version(source),
            "page_count": None,
            "char_count": len(content),
            "title_cn": str(source.get("title_cn") or title),
            "content": content,
            "toc": toc,
            "summary": summary,
            "title_vector": title_vector,
            "toc_vector": title_vector,
            "summary_vector": title_vector,
            "has_graph": False,
            "next_id": 1,
            "files": [],
            "pages": [],
            "nodes": [],
            "edge_rules": [],
            "conditions": [],
            "node_entry_conditions": [],
            "page_links": [],
            "page_global_rules": [],
            "care_phases": [],
            "product_scope": "yiyong",
            "paid": False,
        },
    }


def run(*, dry_run: bool = False) -> tuple[int, int]:
    client = get_es_client()
    if not client.indices.exists(index=LEGACY_INDEX):
        raise RuntimeError(f"Legacy index {LEGACY_INDEX!r} does not exist")
    ensure_plm_index()
    source_fields = [
        "id", "title_cn", "title_en", "file_name", "file_url", "publish_date",
        "content", "toc", "title_cn_vector", "title_en_vector",
    ]
    scanned = 0
    actions = []
    for hit in helpers.scan(client, index=LEGACY_INDEX, query={"query": {"match_all": {}}}, _source=source_fields, size=500):
        scanned += 1
        action = _migration_action(hit)
        if action:
            actions.append(action)
    if not dry_run and actions:
        helpers.bulk(client, actions, chunk_size=100, raise_on_error=True)
        client.indices.refresh(index=PLM_INDEX)
    return scanned, len(actions)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Count eligible NCCN records without writing")
    args = parser.parse_args()
    scanned, migrated = run(dry_run=args.dry_run)
    mode = "would migrate" if args.dry_run else "migrated"
    print(f"{mode} {migrated} NCCN records from {scanned} legacy records at {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()