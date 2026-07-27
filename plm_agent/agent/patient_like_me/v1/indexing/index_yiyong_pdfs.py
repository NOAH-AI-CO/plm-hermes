"""yiyong (医用) 指南库入库: NCCN/CSCO/CACA/ESMO 每个指南的最新版。

与 sahzu_only / public 并列的第三类 product_scope='yiyong', ES 侧硬隔离。
- 文本版 (NCCN 横版 → 现有裁剪; CSCO/ESMO 竖版 → 通用抽取)。
- 扫描件 (CACA) → qwen3-vl-plus 逐页 OCR。
- 每个指南把抽取/OCR 文本按页存一份 md 留档 + 作为再入库缓存。
只建文本+向量, 不建决策树图谱 (has_graph=False)。

用法:
    cd noah_agent
    python -m agent.patient_like_me.v1.indexing.index_yiyong_pdfs            # 本地 ES
    python -m agent.patient_like_me.v1.indexing.index_yiyong_pdfs --limit 3  # 先试跑 3 个
"""
import argparse
import logging
import os
import re
import sys
import time
from collections import defaultdict
from hashlib import md5
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import pymupdf
except ModuleNotFoundError:
    import fitz as pymupdf

_FILE = os.path.abspath(__file__)
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_FILE)))))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from agent.patient_like_me.v1.es.plm_index import (
    PLM_INDEX,
    ensure_plm_indices,
    get_es_client,
    upgrade_plm_index_scope_fields,
)
from agent.patient_like_me.v1.indexing.index_nccn_pdfs import index_single_pdf, parse_version
from agent.patient_like_me.v1.indexing.pdf_utils import pdf_to_pages_clean
from agent.patient_like_me.v1.indexing.ocr_vlm import is_scanned_pdf, ocr_pdf_pages
from agent.patient_like_me.v1.rag.evidence import infer_organization_from_filename

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_HOME = os.path.expanduser("~")
SOURCE_DIRS = [
    os.path.join(_HOME, "Downloads/caca/raw/pdf"),
    os.path.join(_HOME, "Downloads/csco/raw/pdf"),
    os.path.join(_HOME, "Downloads/downloads_nccn_esmo/nccn/noah-data-cooperation"),
    os.path.join(_HOME, "Downloads/downloads_nccn_esmo/esmo/noah-data-cooperation"),
    os.path.join(_HOME, "Downloads/最新版_多版本指南"),
]
EXCLUDE_DIR_PARTS = ("_duplicates", "_excluded")
MD_ROOT = os.path.join(_HOME, "Downloads/yiyong_guideline_md")

_YV_PREFIX = re.compile(r"^（(\d{4})\.V(\d+)）")
_MULTI_SUFFIX = re.compile(r"\((\d)\)$")


def _identity_key(filename: str) -> str:
    """去掉 （年.V数） 前缀、(数) 后缀、.pdf, 作为跨版本指南身份 (机构串:病名)。"""
    name = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
    name = _YV_PREFIX.sub("", name)
    name = _MULTI_SUFFIX.sub("", name).strip()
    return name


def _collect_latest() -> list[dict]:
    """扫描所有源目录, 每个指南身份只留 (年,版本) 最新的一份。"""
    seen_paths: set[str] = set()
    groups: dict[str, list[dict]] = defaultdict(list)
    for root_dir in SOURCE_DIRS:
        if not os.path.isdir(root_dir):
            logger.warning("源目录不存在, 跳过: %s", root_dir)
            continue
        for root, _dirs, files in os.walk(root_dir):
            if any(part in root for part in EXCLUDE_DIR_PARTS):
                continue
            for f in files:
                if not f.lower().endswith(".pdf"):
                    continue
                m = _YV_PREFIX.match(f)
                if not m:
                    continue  # 只收已规范化 （年.V数） 的文件
                path = os.path.join(root, f)
                rp = os.path.realpath(path)
                if rp in seen_paths:
                    continue
                seen_paths.add(rp)
                year, version = int(m.group(1)), int(m.group(2))
                groups[_identity_key(f)].append(
                    {"filename": f, "path": path, "year": year, "version": version}
                )
    latest = []
    for key, entries in groups.items():
        entries.sort(key=lambda e: (e["year"], e["version"]), reverse=True)
        latest.append(entries[0])
    latest.sort(key=lambda e: e["filename"])
    return latest


def _generic_pages(pdf_path: str) -> list[str]:
    """竖版文字型 PDF 的通用逐页抽取 (不做 NCCN 横版裁剪)。"""
    doc = pymupdf.open(pdf_path)
    try:
        return [(doc[i].get_text() or "").strip() for i in range(len(doc))]
    finally:
        doc.close()


def _md_path(filename: str, org: str) -> str:
    safe = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
    return os.path.join(MD_ROOT, org or "OTHER", safe + ".md")


def _load_md_cache(md_file: str) -> list[str] | None:
    if not os.path.exists(md_file):
        return None
    with open(md_file, "r", encoding="utf-8") as f:
        content = f.read()
    parts = re.split(r"\n<!-- PAGE (\d+) -->\n", content)
    # parts = [preamble, '1', page1, '2', page2, ...]
    pages = [parts[i] for i in range(2, len(parts), 2)]
    return pages or None


def _save_md(md_file: str, filename: str, org: str, method: str, pages: list[str]) -> None:
    os.makedirs(os.path.dirname(md_file), exist_ok=True)
    lines = [f"# {filename}", "", f"- organization: {org}", f"- extract_method: {method}",
             f"- pages: {len(pages)}", ""]
    body = "\n".join(f"\n<!-- PAGE {i} -->\n{p}" for i, p in enumerate(pages, 1))
    with open(md_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + body)


def _extract_pages(entry: dict, org: str, ocr_workers: int) -> tuple[list[str], str]:
    """返回 (逐页文本, 方法)。优先 md 缓存。"""
    md_file = _md_path(entry["filename"], org)
    cached = _load_md_cache(md_file)
    if cached is not None:
        return cached, "cache"
    path = entry["path"]
    if is_scanned_pdf(path):
        pages = ocr_pdf_pages(path, workers=ocr_workers)
        method = "ocr"
    elif org == "NCCN":
        pages = pdf_to_pages_clean(path)
        method = "nccn_clean"
    else:
        pages = _generic_pages(path)
        method = "generic"
    _save_md(md_file, entry["filename"], org, method, pages)
    return pages, method


# yiyong 用独立命名空间 doc_id, 避免和 sahzu/public 的同名 NCCN 文件 (md5(filename)) 撞车覆盖。
def yiyong_doc_id(filename: str) -> int:
    return int(md5(("yiyong|" + filename).encode("utf-8")).hexdigest()[:15], 16)


def _index_one(entry: dict, client, chunk_embed_workers: int, ocr_workers: int) -> dict:
    filename = entry["filename"]
    org = infer_organization_from_filename(filename) or ""
    pages, method = _extract_pages(entry, org, ocr_workers)
    info = index_single_pdf(
        entry["path"],
        is_cn_content=True,
        year=entry["year"],
        version=entry["version"],
        chunk_embed_workers=chunk_embed_workers,
        pages_override=pages,
        doc_id_override=yiyong_doc_id(filename),
    )
    client.update(
        index=PLM_INDEX,
        id=info["id"],
        body={"doc": {"product_scope": "yiyong", "paid": False, "organization": org}},
        refresh=False,
    )
    return {**info, "organization": org, "method": method}


def run(workers: int = 2, chunk_embed_workers: int = 6, ocr_workers: int = 6, limit: int = 0) -> None:
    ensure_plm_indices()
    upgrade_plm_index_scope_fields()
    client = get_es_client()

    entries = _collect_latest()
    if limit:
        entries = entries[:limit]
    by_org = defaultdict(int)
    for e in entries:
        by_org[infer_organization_from_filename(e["filename"]) or "OTHER"] += 1
    logger.info("待入库 %d 个 (最新版), 机构分布: %s", len(entries), dict(by_org))

    results, errors = [], []

    def _do(entry):
        t0 = time.time()
        r = _index_one(entry, client, chunk_embed_workers, ocr_workers)
        return {**r, "elapsed": time.time() - t0}

    if workers <= 1:
        for i, entry in enumerate(entries, 1):
            try:
                r = _do(entry)
                logger.info("[%d/%d] OK %s org=%s method=%s pages=%d chunks=%d %.0fs",
                            i, len(entries), r["filename"], r["organization"], r["method"],
                            r["page_count"], r["chunk_count"], r["elapsed"])
                results.append(r)
            except Exception as e:
                logger.exception("[%d/%d] FAIL %s: %s", i, len(entries), entry["filename"], e)
                errors.append({"filename": entry["filename"], "error": str(e)})
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fut_map = {pool.submit(_do, e): e for e in entries}
            done = 0
            for fut in as_completed(fut_map):
                done += 1
                entry = fut_map[fut]
                try:
                    r = fut.result()
                    logger.info("[%d/%d] OK %s org=%s method=%s pages=%d chunks=%d %.0fs",
                                done, len(entries), r["filename"], r["organization"], r["method"],
                                r["page_count"], r["chunk_count"], r["elapsed"])
                    results.append(r)
                except Exception as e:
                    logger.exception("[%d/%d] FAIL %s: %s", done, len(entries), entry["filename"], e)
                    errors.append({"filename": entry["filename"], "error": str(e)})

    client.indices.refresh(index=PLM_INDEX)
    ok_by_org = defaultdict(int)
    for r in results:
        ok_by_org[r["organization"] or "OTHER"] += 1
    logger.info("完成. ok=%d fail=%d, 机构: %s", len(results), len(errors), dict(ok_by_org))
    for e in errors:
        logger.error("  Failed: %s — %s", e["filename"], e["error"])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=2, help="PDF 级并发")
    p.add_argument("--chunk-workers", type=int, default=6, help="chunk embedding 并发")
    p.add_argument("--ocr-workers", type=int, default=6, help="单 PDF 内 OCR 页并发")
    p.add_argument("--limit", type=int, default=0, help="只处理前 N 个 (试跑)")
    args = p.parse_args()
    run(workers=args.workers, chunk_embed_workers=args.chunk_workers,
        ocr_workers=args.ocr_workers, limit=args.limit)
