"""sahzu 专用索引: /Users/wuyifu/Downloads/all_pdfs 下的血液肿瘤/淋巴瘤类 64 份 PDF。

与通用 (public) PLM 库完全隔离:
  - product_scope='sahzu_only': ES 侧硬过滤, sahzu mode=simple 只能命中这些文档;
    PLM/biz (mode=complex) 只搜 product_scope='public' 或缺省, 双向不干扰。
  - ES 字段 paid=True 语义是"受上传解锁门禁", 组织必须在
    OrganizationGuidelineAccess 里持有对应 guideline_id 才能被检索命中。
    产品术语称"上传解锁", ES 字段名保留 paid 是历史遗留 (未做迁移)。

只建文本 + 向量, 不建决策树图谱 (has_graph=False)。
图谱由 run_graph_indexing_sahzu.py 单独针对四大组织 (NCCN/CSCO/CACA/ESMO)
的文件补齐, 其它文件保持无图谱状态。
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

_FILE = os.path.abspath(__file__)
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_FILE)))))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from agent.patient_like_me.v1.es.plm_index import (
    PLM_INDEX,
    ensure_plm_indices,
    get_es_client,
    make_doc_id,
    upgrade_plm_index_scope_fields,
)
from agent.patient_like_me.v1.indexing.index_nccn_pdfs import (
    index_single_pdf,
    parse_version,
)
from agent.patient_like_me.v1.rag.evidence import infer_organization_from_filename

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


SAHZU_PDF_DIR = "/Users/wuyifu/Downloads/all_pdfs"

# 上传解锁清单 — 唯一 source of truth。新增/删除受管指南只需要改 JSON。
# Backend 侧从同一份文件加载 (sahzu_unlock_registry.py 通过 SAHZU_UNLOCK_JSON 环境变量
# 或默认路径读取)。ES 字段仍叫 "paid" 是历史遗留 (不改是为了避免已入库文档迁移), 语义上
# 就是"是否受上传解锁门禁", 产品对外术语始终称"上传解锁"。
_UNLOCK_LIST_JSON = os.path.join(os.path.dirname(__file__), "sahzu_unlock_guidelines.json")


def _load_unlock_filenames(path: str = _UNLOCK_LIST_JSON) -> set[str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {(g.get("filename") or "").strip() for g in data.get("guidelines", []) if g.get("filename")}


_UNLOCK_FILENAMES = _load_unlock_filenames()


def is_unlock_required_by_filename(filename: str) -> bool:
    return (filename or "").strip() in _UNLOCK_FILENAMES


def _iter_pdfs(root: str):
    for name in sorted(os.listdir(root)):
        if name.lower().endswith(".pdf"):
            yield os.path.join(root, name), name


def _post_tag(client, doc_id: int, filename: str) -> dict:
    org = infer_organization_from_filename(filename) or ""
    paid = is_unlock_required_by_filename(filename)
    body = {
        "doc": {
            "product_scope": "sahzu_only",
            "paid": paid,
            "organization": org,
        }
    }
    client.update(index=PLM_INDEX, id=doc_id, body=body, refresh=False)
    return {"doc_id": doc_id, "filename": filename, "organization": org, "paid": paid}


def run(pdf_dir: str = SAHZU_PDF_DIR, workers: int = 3, chunk_embed_workers: int = 6) -> None:
    if not os.path.isdir(pdf_dir):
        raise SystemExit(f"pdf dir not found: {pdf_dir}")

    ensure_plm_indices()
    upgrade_plm_index_scope_fields()
    client = get_es_client()

    entries = list(_iter_pdfs(pdf_dir))
    logger.info("Found %d PDFs under %s", len(entries), pdf_dir)

    def _do(entry):
        path, filename = entry
        year, version = parse_version(filename)
        t0 = time.time()
        info = index_single_pdf(
            path, is_cn_content=True, year=year, version=version,
            chunk_embed_workers=chunk_embed_workers,
        )
        tag = _post_tag(client, info["id"], filename)
        return {**info, **tag, "elapsed": time.time() - t0}

    results, errors = [], []
    if workers <= 1:
        for i, entry in enumerate(entries, 1):
            try:
                r = _do(entry)
                logger.info("[%d/%d] OK %s org=%s paid=%s pages=%d chunks=%d %.1fs",
                            i, len(entries), r["filename"], r["organization"],
                            r["paid"], r["page_count"], r["chunk_count"], r["elapsed"])
                results.append(r)
            except Exception as e:
                logger.exception("[%d/%d] FAIL %s: %s", i, len(entries), entry[1], e)
                errors.append({"filename": entry[1], "error": str(e)})
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fut_to_entry = {pool.submit(_do, e): e for e in entries}
            done_i = 0
            for fut in as_completed(fut_to_entry):
                done_i += 1
                entry = fut_to_entry[fut]
                try:
                    r = fut.result()
                    logger.info("[%d/%d] OK %s org=%s paid=%s pages=%d chunks=%d %.1fs",
                                done_i, len(entries), r["filename"], r["organization"],
                                r["paid"], r["page_count"], r["chunk_count"], r["elapsed"])
                    results.append(r)
                except Exception as e:
                    logger.exception("[%d/%d] FAIL %s: %s", done_i, len(entries), entry[1], e)
                    errors.append({"filename": entry[1], "error": str(e)})

    client.indices.refresh(index=PLM_INDEX)
    logger.info("Done. ok=%d fail=%d paid=%d free=%d",
                len(results), len(errors),
                sum(1 for r in results if r.get("paid")),
                sum(1 for r in results if not r.get("paid")))
    if errors:
        for e in errors:
            logger.error("  Failed: %s — %s", e["filename"], e["error"])

    # 生成 guideline_id 回填清单 (供 Backend paid_registry 手动填回)
    paid_map = [
        {"filename": r["filename"], "doc_id": str(r["doc_id"])}
        for r in results if r.get("paid")
    ]
    logger.info("---- Paid guideline_id mapping (回填到 Backend sahzu_paid_registry.py) ----")
    for e in paid_map:
        logger.info("  %s  ->  %s", e["filename"], e["doc_id"])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dir", default=SAHZU_PDF_DIR)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--chunk-workers", type=int, default=6)
    args = p.parse_args()
    run(args.dir, workers=args.workers, chunk_embed_workers=args.chunk_workers)
