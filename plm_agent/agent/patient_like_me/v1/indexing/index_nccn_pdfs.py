"""
Index NCCN PDF guidelines into the unified plm_guidelines ES index.

Handles version deduplication: when multiple versions of the same guideline
exist (e.g. V1, V2, V3), only the latest version is indexed.
CN and EN variants are treated as separate entries (both kept at latest version).

Uses pdf_utils.pdf_to_pages_clean() for header/footer-free text extraction.
Each PDF gets text + embedding vectors (Path 1) and placeholder graph fields (Path 2).
Graph data is populated separately by the guidance parsing pipeline.
"""

import os
import re
import sys
import time
import logging
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

_FILE = os.path.abspath(__file__)
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_FILE)))))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from agent.patient_like_me.v1.indexing.pdf_utils import pdf_to_pages_clean, build_section_titles
from elasticsearch import helpers

from agent.patient_like_me.v1.es.plm_index import (
    PLM_CHUNK_INDEX,
    PLM_INDEX,
    ensure_plm_indices,
    get_es_client,
    make_doc_id,
)
from agent.iit.utils.guidelines.embedding import get_embedding

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_DATA_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(_FILE))),
    "dify", "data",
)
CN_DIR = os.path.join(_DATA_ROOT, "25nccn中文_副本")
EN_DIR = os.path.join(_DATA_ROOT, "25年nccn英文_副本")

_VERSION_RE = re.compile(r"[（(](\d{4})\.V(\d+)[）)]")
_VERSION_EN_RE = re.compile(r"\s+V(\d+)\.(\d{4})\s*$")
_LANG_SUFFIX_RE = re.compile(r"\s*(中文版|中文|zh)\s*$")
_NCCN_PREFIX_RE = re.compile(r"^\s*NCCN临床实践指南[：:]\s*")
_GUIDELINE_KEY_ALIASES = {
    "castleman病": "卡斯尔曼病",
    "卡斯尔曼病": "卡斯尔曼病",
    "小儿中枢神经系统癌症": "儿童中枢神经系统肿瘤",
    "儿童中枢神经系统肿瘤": "儿童中枢神经系统肿瘤",
    "华氏巨球蛋白血症淋巴浆细胞淋巴瘤": "巨球蛋白血症/淋巴浆细胞性淋巴瘤",
    "巨球蛋白血症/淋巴浆细胞性淋巴瘤": "巨球蛋白血症/淋巴浆细胞性淋巴瘤",
    "aml": "急性髓性白血病",
    "acutemyeloidleukemia": "急性髓性白血病",
    "b-celllymphomas": "B细胞淋巴瘤",
    "hodgkinlymphoma": "霍奇金淋巴瘤",
    "t-celllymphomas": "T细胞淋巴瘤",
}
_GRAPH_FIELDS = [
    "has_graph",
    "guideline_name",
    "organization",
    "description",
    "next_id",
    "files",
    "pages",
    "nodes",
    "edge_rules",
    "conditions",
    "node_entry_conditions",
    "page_links",
    "page_global_rules",
    "care_phases",
]


def _env_int(name: str, default: int, minimum: int = 1, maximum: int = 64) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r, using default %d", name, raw, default)
        return default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float = 0.0, maximum: float = 10.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r, using default %.3f", name, raw, default)
        return default
    return max(minimum, min(maximum, value))


_EMBED_TOTAL_CONCURRENCY = _env_int("PLM_EMBED_TOTAL_CONCURRENCY", default=10, minimum=1, maximum=64)
_EMBED_SEMAPHORE = threading.BoundedSemaphore(_EMBED_TOTAL_CONCURRENCY)
_EMBED_MIN_INTERVAL = _env_float("PLM_EMBED_MIN_INTERVAL", default=0.08, minimum=0.0, maximum=2.0)
_EMBED_START_LOCK = threading.Lock()
_EMBED_LAST_START = 0.0


def _pace_embedding_start() -> None:
    if _EMBED_MIN_INTERVAL <= 0:
        return
    global _EMBED_LAST_START
    with _EMBED_START_LOCK:
        now = time.monotonic()
        wait_for = _EMBED_LAST_START + _EMBED_MIN_INTERVAL - now
        if wait_for > 0:
            time.sleep(wait_for)
            now = time.monotonic()
        _EMBED_LAST_START = now


def parse_version(filename: str) -> tuple[int | None, int | None]:
    """Extract (year, version_number) from filename.

    Supports both '（2025.V2）' → (2025, 2) and 'AML V3.2026' → (2026, 3).
    """
    m = _VERSION_RE.search(filename)
    if m:
        return int(m.group(1)), int(m.group(2))
    stem = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE).strip()
    m2 = _VERSION_EN_RE.search(stem)
    if m2:
        return int(m2.group(2)), int(m2.group(1))
    return None, None


def extract_guideline_key(filename: str) -> str:
    """Normalize filename to a guideline identity key (disease name only).

    Strips version tag, language suffixes, file extension.
    Used for grouping the same guideline across versions.
    """
    name = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE).strip()
    name = _VERSION_RE.sub("", name)
    name = _VERSION_EN_RE.sub("", name)
    name = _LANG_SUFFIX_RE.sub("", name)
    name = _NCCN_PREFIX_RE.sub("", name)
    name = re.sub(r"\s+", "", name)
    name = name.replace("／", "/")
    return _GUIDELINE_KEY_ALIASES.get(name.lower(), _GUIDELINE_KEY_ALIASES.get(name, name)).strip()


def _existing_graph_fields(client, doc_id: int) -> dict:
    try:
        existing = client.options(ignore_status=[404]).get(index=PLM_INDEX, id=doc_id)
    except Exception:
        return {}
    if not existing or not existing.get("found"):
        return {}
    source = existing.get("_source", {}) or {}
    if not source.get("has_graph"):
        return {}
    return {field: source[field] for field in _GRAPH_FIELDS if field in source}


def deduplicate_pdfs(
    pdf_entries: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Deduplicate PDFs by guideline name + language, keeping latest version.

    Args:
        pdf_entries: list of {"filename", "path", "is_cn", "year", "version", "key"}

    Returns:
        (kept, skipped) — both are lists of pdf_entry dicts.
    """
    groups: dict[tuple[str, bool], list[dict]] = defaultdict(list)
    for entry in pdf_entries:
        group_key = (entry["key"], entry["is_cn"])
        groups[group_key].append(entry)

    kept = []
    skipped = []
    for (gname, is_cn), entries in sorted(groups.items()):
        entries.sort(key=lambda e: (e["year"] or 0, e["version"] or 0), reverse=True)
        kept.append(entries[0])
        for old in entries[1:]:
            skipped.append(old)

    return kept, skipped


def _safe_embedding(text: str, max_chars: int = 0):
    if not text or not text.strip():
        return None
    with _EMBED_SEMAPHORE:
        _pace_embedding_start()
        return get_embedding(text if max_chars <= 0 else text[:max_chars])


def _embed_chunk_action_vectors(actions: list[dict], max_workers: int, label: str) -> None:
    if not actions:
        return

    def embed_one(action: dict) -> tuple[dict, list[float] | None]:
        text = action.get("_source", {}).get("text") or ""
        return action, _safe_embedding(text)

    if max_workers <= 1:
        for action in actions:
            _action, vector = embed_one(action)
            if vector is not None:
                _action["_source"]["text_vector"] = vector
        return

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(embed_one, action) for action in actions]
        for future in as_completed(futures):
            action, vector = future.result()
            if vector is not None:
                action["_source"]["text_vector"] = vector
            done += 1
            if done % 100 == 0 or done == len(actions):
                logger.info("Embedded chunks for %s: %d/%d", label, done, len(actions))


def _build_text_pages(pages: list[str], section_map: dict[int, str]) -> list[dict]:
    return [
        {
            "page": idx,
            "section_title": section_map.get(idx, ""),
            "text": text or "",
        }
        for idx, text in enumerate(pages, 1)
    ]


def _split_page_chunks(page_text: str, max_chars: int = 2400, overlap_chars: int = 260) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", (page_text or "").strip())
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            start = 0
            while start < len(paragraph):
                end = min(len(paragraph), start + max_chars)
                chunks.append(paragraph[start:end].strip())
                if end >= len(paragraph):
                    break
                start = max(end - overlap_chars, start + 1)
            continue
        proposed = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(proposed) <= max_chars:
            current = proposed
            continue
        if current:
            chunks.append(current.strip())
        tail = current[-overlap_chars:] if current and overlap_chars > 0 else ""
        current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
    if current:
        chunks.append(current.strip())
    return chunks


def _build_chunk_actions(
    *,
    doc_id: int,
    filename: str,
    file_path: str,
    guideline_key: str,
    is_cn_content: bool,
    year: int | None,
    version: int | None,
    pages: list[str],
    section_map: dict[int, str],
    embed_chunks: bool,
    chunk_embed_workers: int = 1,
) -> list[dict]:
    actions = []
    for idx, text in enumerate(pages, 1):
        clean_text = (text or "").strip()
        if not clean_text:
            continue
        section_title = section_map.get(idx, "")
        page_chunks = _split_page_chunks(clean_text)
        for part_index, chunk_text in enumerate(page_chunks, 1):
            chunk_id = f"{doc_id}:{idx}:{part_index}"
            chunk_doc = {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "filename": filename,
                "filename_text": filename,
                "file_path": file_path,
                "guideline_key": guideline_key,
                "is_cn_content": is_cn_content,
                "year": year,
                "version": version,
                "page_start": idx,
                "page_end": idx,
                "section_title": section_title,
                "text": chunk_text,
            }
            actions.append({
                "_op_type": "index",
                "_index": PLM_CHUNK_INDEX,
                "_id": chunk_id,
                "_source": chunk_doc,
            })
    if embed_chunks:
        _embed_chunk_action_vectors(actions, max_workers=chunk_embed_workers, label=filename)
    return actions


def index_single_pdf(
    pdf_path: str,
    is_cn_content: bool = True,
    year: int | None = None,
    version: int | None = None,
    index_chunks: bool = True,
    embed_chunks: bool = True,
    chunk_embed_workers: int | None = None,
    pages_override: list[str] | None = None,
    doc_id_override: int | None = None,
) -> dict:
    """Extract clean text from a single PDF and index into unified plm_guidelines.

    pages_override: 若提供, 直接用这份逐页文本 (如 OCR / 非 NCCN 通用抽取的结果),
    跳过内部的 NCCN 专用 pdf_to_pages_clean。
    doc_id_override: 若提供, 用它作为 doc_id (用于给不同 product_scope 的同名文件做
    命名空间隔离, 避免 md5(filename) 撞车覆盖其它 scope 的文档)。

    Returns a summary dict with id, filename, page_count, char_count, year, version.
    """
    ensure_plm_indices()
    if chunk_embed_workers is None:
        chunk_embed_workers = _env_int("PLM_CHUNK_EMBED_WORKERS", default=8, minimum=1, maximum=64)

    filename = os.path.basename(pdf_path)
    doc_id = doc_id_override if doc_id_override is not None else make_doc_id(filename)

    if year is None or version is None:
        year, version = parse_version(filename)

    pages = pages_override if pages_override is not None else pdf_to_pages_clean(pdf_path)
    section_map = build_section_titles(pdf_path)
    full_text = "\n\n".join(p for p in pages if p.strip())
    toc_text = pages[0] if pages else ""
    summary_text = "\n\n".join(pages[:3]) if len(pages) >= 3 else full_text
    guideline_key = extract_guideline_key(filename)

    title_vec = _safe_embedding(filename)
    toc_vec = _safe_embedding(toc_text)
    summary_vec = _safe_embedding(summary_text)

    doc = {
        "doc_id": doc_id,
        "filename": filename,
        "file_path": os.path.abspath(pdf_path),
        "is_cn_content": is_cn_content,
        "guideline_key": guideline_key,
        "year": year,
        "version": version,
        "page_count": len(pages),
        "char_count": len(full_text),

        "title_cn": filename,
        "content": full_text,
        "toc": toc_text,
        "summary": summary_text,
        "text_pages": _build_text_pages(pages, section_map),
        "title_vector": title_vec,
        "toc_vector": toc_vec,
        "summary_vector": summary_vec,

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
    }
    client = get_es_client()
    graph_fields = _existing_graph_fields(client, doc_id)
    if graph_fields:
        doc.update(graph_fields)
    client.index(index=PLM_INDEX, id=doc_id, document=doc, refresh=False)

    chunk_count = 0
    if index_chunks:
        try:
            client.delete_by_query(
                index=PLM_CHUNK_INDEX,
                body={"query": {"term": {"doc_id": doc_id}}},
                conflicts="proceed",
                refresh=False,
            )
        except Exception:
            logger.info("No previous chunks to delete for doc_id=%s", doc_id)
        actions = _build_chunk_actions(
            doc_id=doc_id,
            filename=filename,
            file_path=os.path.abspath(pdf_path),
            guideline_key=guideline_key,
            is_cn_content=is_cn_content,
            year=year,
            version=version,
            pages=pages,
            section_map=section_map,
            embed_chunks=embed_chunks,
            chunk_embed_workers=chunk_embed_workers,
        )
        if actions:
            helpers.bulk(client.options(request_timeout=120), actions, refresh=False)
            chunk_count = len(actions)

    return {
        "id": doc_id,
        "filename": filename,
        "page_count": len(pages),
        "char_count": len(full_text),
        "chunk_count": chunk_count,
        "year": year,
        "version": version,
    }


def _cleanup_stale_pdf_docs(kept_entries: list[dict]) -> None:
    """Remove older PDF docs/chunks from the managed PDF folders.

    This keeps ES aligned with the version-deduped file set without touching
    unrelated guideline docs that may have been created by graph tooling.
    """
    keep_doc_ids = [make_doc_id(entry["filename"]) for entry in kept_entries]
    if not keep_doc_ids:
        return

    client = get_es_client()
    data_root = os.path.abspath(_DATA_ROOT)
    stale_query = {
        "bool": {
            "filter": [{"prefix": {"file_path": data_root}}],
            "must_not": [{"terms": {"doc_id": keep_doc_ids}}],
        }
    }
    for index in [PLM_CHUNK_INDEX, PLM_INDEX]:
        try:
            result = client.delete_by_query(
                index=index,
                body={"query": stale_query},
                conflicts="proceed",
                refresh=False,
                ignore_unavailable=True,
            )
            deleted = result.get("deleted", 0) if isinstance(result, dict) else 0
            if deleted:
                logger.info("Cleaned %d stale records from %s", deleted, index)
        except Exception:
            logger.exception("Failed to clean stale records from %s", index)


def _collect_pdfs(en_dir: str) -> list[dict]:
    """Scan EN directory and collect all PDF entries with parsed metadata."""
    entries = []
    if not os.path.isdir(en_dir):
        logger.warning("Directory not found, skipping: %s", en_dir)
        return entries
    for f in sorted(os.listdir(en_dir)):
        if not f.lower().endswith(".pdf"):
            continue
        year, ver = parse_version(f)
        entries.append({
            "filename": f,
            "path": os.path.join(en_dir, f),
            "is_cn": False,
            "year": year,
            "version": ver,
            "key": extract_guideline_key(f),
        })
    return entries


def run(
    en_dir: str = EN_DIR,
    pdf_workers: int | None = None,
    chunk_embed_workers: int | None = None,
):
    ensure_plm_indices()
    if pdf_workers is None:
        pdf_workers = _env_int("PLM_PDF_INDEX_WORKERS", default=4, minimum=1, maximum=16)
    if chunk_embed_workers is None:
        chunk_embed_workers = _env_int("PLM_CHUNK_EMBED_WORKERS", default=8, minimum=1, maximum=64)

    all_entries = _collect_pdfs(en_dir)
    kept, skipped = deduplicate_pdfs(all_entries)
    _cleanup_stale_pdf_docs(kept)

    logger.info(
        "Version dedup: %d total → %d kept, %d skipped (older/duplicate)",
        len(all_entries), len(kept), len(skipped),
    )
    logger.info(
        "Index concurrency: pdf_workers=%d, chunk_embed_workers=%d, embed_total_concurrency=%d, embed_min_interval=%.3fs",
        pdf_workers, chunk_embed_workers, _EMBED_TOTAL_CONCURRENCY, _EMBED_MIN_INTERVAL,
    )
    for s in skipped:
        logger.info(
            "  SKIP  V%s %s — superseded by newer version",
            s["version"] or "?", s["filename"],
        )

    results = []
    errors = []

    def _index_entry(i: int, entry: dict) -> tuple[int, dict, dict, float]:
        t0 = time.time()
        info = index_single_pdf(
            entry["path"],
            is_cn_content=entry["is_cn"],
            year=entry["year"],
            version=entry["version"],
            chunk_embed_workers=chunk_embed_workers,
        )
        return i, entry, info, time.time() - t0

    def _record_success(i: int, entry: dict, info: dict, elapsed: float) -> None:
        lang = "CN" if entry["is_cn"] else "EN"
        logger.info(
            "[%d/%d] OK  %s V%s  %s  (pages=%d, chunks=%d, chars=%d, %.1fs)",
            i, len(kept), lang, entry["version"] or "?", entry["filename"],
            info["page_count"], info.get("chunk_count", 0), info["char_count"], elapsed,
        )
        results.append(info)

    if pdf_workers <= 1:
        for i, entry in enumerate(kept, 1):
            try:
                _record_success(*_index_entry(i, entry))
            except Exception as e:
                logger.error("[%d/%d] FAIL %s: %s", i, len(kept), entry["filename"], e)
                errors.append({"filename": entry["filename"], "error": str(e)})
    else:
        with ThreadPoolExecutor(max_workers=pdf_workers) as pool:
            future_to_entry = {
                pool.submit(_index_entry, i, entry): (i, entry)
                for i, entry in enumerate(kept, 1)
            }
            for future in as_completed(future_to_entry):
                i, entry = future_to_entry[future]
                try:
                    _record_success(*future.result())
                except Exception as e:
                    logger.error("[%d/%d] FAIL %s: %s", i, len(kept), entry["filename"], e)
                    errors.append({"filename": entry["filename"], "error": str(e)})

    get_es_client().indices.refresh(index=PLM_INDEX)
    get_es_client().indices.refresh(index=PLM_CHUNK_INDEX)

    logger.info("Done. Indexed %d PDFs, %d errors.", len(results), len(errors))
    if errors:
        for err in errors:
            logger.error("  Failed: %s — %s", err["filename"], err["error"])

    return results, errors


if __name__ == "__main__":
    run()
