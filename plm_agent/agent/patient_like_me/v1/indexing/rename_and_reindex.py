#!/usr/bin/env python3
"""
Rename 4 English PDFs with non-standard names to the standard naming convention,
delete their old ES index entries, and re-index with new names.

All 4 PDFs are processed in parallel.
"""
import os
import sys
import time
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

_FILE = os.path.abspath(__file__)
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_FILE)))))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)
os.chdir(_PKG_ROOT)

from agent.patient_like_me.v1.es.plm_index import (
    PLM_CHUNK_INDEX,
    PLM_INDEX,
    get_es_client,
    make_doc_id,
    ensure_plm_indices,
)
from agent.patient_like_me.v1.indexing.index_nccn_pdfs import index_single_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(_FILE))),
    "dify", "data", "25年nccn英文_副本",
)

RENAME_MAP = [
    {
        "old_name": "AML V3.2026.pdf",
        "new_name": "（2026.V3）NCCN临床实践指南：急性髓性白血病.pdf",
    },
    {
        "old_name": "B-Cell Lymphomas V3.2026.pdf",
        "new_name": "（2026.V3）NCCN临床实践指南：B细胞淋巴瘤.pdf",
    },
    {
        "old_name": "T-Cell Lymphomas V2.2026 .pdf",
        "new_name": "（2026.V2）NCCN临床实践指南：T细胞淋巴瘤.pdf",
    },
    {
        "old_name": "Hodgkin Lymphoma V1.2026.pdf",
        "new_name": "（2026.V1）NCCN临床实践指南：霍奇金淋巴瘤.pdf",
    },
]


def _delete_old_index(client, old_filename: str) -> int:
    old_doc_id = make_doc_id(old_filename)
    deleted_chunks = 0
    try:
        result = client.delete_by_query(
            index=PLM_CHUNK_INDEX,
            body={"query": {"term": {"doc_id": old_doc_id}}},
            conflicts="proceed",
            refresh=False,
        )
        deleted_chunks = result.get("deleted", 0) if isinstance(result, dict) else 0
    except Exception:
        logger.info("No chunks to delete for %s (doc_id=%s)", old_filename, old_doc_id)

    try:
        client.delete(index=PLM_INDEX, id=str(old_doc_id), refresh=False)
    except Exception:
        logger.info("No doc to delete for %s (doc_id=%s)", old_filename, old_doc_id)

    return deleted_chunks


def process_one(entry: dict) -> dict:
    old_name = entry["old_name"]
    new_name = entry["new_name"]
    old_path = os.path.join(EN_DIR, old_name)
    new_path = os.path.join(EN_DIR, new_name)

    t0 = time.time()
    client = get_es_client()

    # 1. Delete old ES entries
    deleted = _delete_old_index(client, old_name)
    logger.info("[%s] Deleted old index (chunks=%d)", old_name, deleted)

    # 2. Rename file
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
        logger.info("[%s] Renamed → %s", old_name, new_name)
    elif os.path.exists(new_path):
        logger.info("[%s] Already renamed to %s", old_name, new_name)
    else:
        raise FileNotFoundError(f"Neither {old_path} nor {new_path} exists")

    # 3. Re-index with new name
    info = index_single_pdf(new_path, is_cn_content=False)
    elapsed = time.time() - t0
    logger.info(
        "[%s] Re-indexed as %s (doc_id=%s, pages=%d, chunks=%d, %.1fs)",
        old_name, new_name, info["id"], info["page_count"], info.get("chunk_count", 0), elapsed,
    )
    return {"old": old_name, "new": new_name, "info": info, "elapsed": elapsed}


def main():
    ensure_plm_indices()

    # Verify files exist before starting
    for entry in RENAME_MAP:
        old_path = os.path.join(EN_DIR, entry["old_name"])
        new_path = os.path.join(EN_DIR, entry["new_name"])
        if not os.path.exists(old_path) and not os.path.exists(new_path):
            raise FileNotFoundError(f"Missing: {old_path}")

    logger.info("Processing %d PDFs in parallel...", len(RENAME_MAP))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(process_one, entry): entry for entry in RENAME_MAP}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                result = future.result()
                logger.info("DONE: %s → %s (%.1fs)", result["old"], result["new"], result["elapsed"])
            except Exception as e:
                logger.error("FAIL: %s — %s", entry["old_name"], e, exc_info=True)

    client = get_es_client()
    client.indices.refresh(index=PLM_INDEX)
    client.indices.refresh(index=PLM_CHUNK_INDEX)
    logger.info("All done. Indices refreshed.")


if __name__ == "__main__":
    main()
