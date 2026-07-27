"""4 case 召回的 11 个 PDF 图谱构建——重试 + 慢速版。

行为:
- 跳过已建好图谱的 PDF(has_graph=True)
- 每个 PDF 失败时自动重试最多 3 次,每次等待 60 秒
- Stage 1/2 并发降到 4 / 2,避免再次 429
- 每 PDF 之间间隔 20 秒,让 ES 喘息
"""
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_NOAH_AGENT_ROOT = _SCRIPT_DIR.parents[3]

_gcp_key = _NOAH_AGENT_ROOT / "gcp_claude.json"
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_gcp_key)
os.environ["GOOGLE_CLOUD_PROJECT"] = "noah-ai-claude"
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")

if str(_NOAH_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_NOAH_AGENT_ROOT))

from config import api_config as _ac
_ac.VERTEX_PROJECT_ID = "noah-ai-claude"

import asyncio, time
from elasticsearch import Elasticsearch

PDF_DIR = "/Users/wuyifu/NoahAgent/noah_agent/agent/patient_like_me/dify/data/25年nccn英文_副本"
PDFS_ALL = [
    f"{PDF_DIR}/（2025.V1）NCCN临床实践指南：乳腺癌.pdf",
    f"{PDF_DIR}/（2025.V1）NCCN临床实践指南：降低乳腺癌风险.pdf",
    f"{PDF_DIR}/（2025.V3）NCCN临床实践指南：非小细胞肺癌.pdf",
    f"{PDF_DIR}/（2025.V1）NCCN临床实践指南：肺癌筛查.pdf",
    f"{PDF_DIR}/（2025.V1）NCCN临床实践指南：姑息治疗.pdf",
    f"{PDF_DIR}/（2025.V1）NCCN临床实践指南：前列腺癌.pdf",
    f"{PDF_DIR}/（2025.V1）NCCN临床实践指南：心理痛苦的处理.pdf",
    f"{PDF_DIR}/（2025.V1）NCCN临床实践指南：癌症相关疲劳.pdf",
    f"{PDF_DIR}/（2025.V1）NCCN临床实践指南：成人癌痛.pdf",
    f"{PDF_DIR}/（2025.V1）NCCN临床实践指南：结肠癌.pdf",
    f"{PDF_DIR}/（2025.V1）NCCN临床实践指南：直肠癌.pdf",
]


def already_built(filename: str) -> bool:
    """Check ES if this PDF already has has_graph=True."""
    es = Elasticsearch("http://localhost:6002", basic_auth=("elastic", "elasticnoah"))
    try:
        r = es.search(index="plm_guidelines",
                      body={"query": {"bool": {"must": [
                          {"term": {"filename": filename}},
                          {"term": {"has_graph": True}},
                      ]}}, "size": 1})
        return len(r["hits"]["hits"]) > 0
    except Exception as e:
        print(f"  [warn] ES 检查异常: {e}")
        return False


import agent.patient_like_me.v1.indexing.run_graph_indexing as rgi
rgi.SKIP_STAGE1 = False
rgi.SKIP_STAGE15 = False
# ES 容器升到 6GB / heap 4GB 后,circuit breaker 触发概率大幅降低,
# 恢复原默认高并发 8/3
rgi.STAGE1_CONCURRENCY = 8
rgi.STAGE2_CONCURRENCY = 3

MAX_RETRY = 5
SLEEP_BETWEEN_RETRY = 60
SLEEP_BETWEEN_PDF = 10


async def run_one_with_retry(pdf: str, idx: int, total: int) -> bool:
    fn = Path(pdf).name
    for attempt in range(1, MAX_RETRY + 1):
        # 每次 attempt 都重检 has_graph,防止上次失败前其实已经写完
        if already_built(fn):
            print(f"\n[{idx}/{total}] ⏭  {fn} 已有图谱(检测于 attempt {attempt} 之前), 跳过")
            return True
        print(f"\n{'#'*80}")
        print(f"# [{idx}/{total}] {fn}   attempt {attempt}/{MAX_RETRY}")
        print(f"{'#'*80}")
        try:
            await rgi.run_one_pdf(pdf)
            return True
        except Exception as e:
            print(f"\n[ERROR] {fn} attempt {attempt} 失败: {e}")
            if attempt < MAX_RETRY:
                print(f"  等 {SLEEP_BETWEEN_RETRY}s 后重试...")
                await asyncio.sleep(SLEEP_BETWEEN_RETRY)
    return False


async def main():
    total_start = time.time()
    n_ok = n_fail = 0
    failed = []
    for i, pdf in enumerate(PDFS_ALL, 1):
        ok = await run_one_with_retry(pdf, i, len(PDFS_ALL))
        if ok:
            n_ok += 1
        else:
            n_fail += 1
            failed.append(Path(pdf).name)
        # 每 PDF 后等一下,让 ES 喘息
        if i < len(PDFS_ALL):
            await asyncio.sleep(SLEEP_BETWEEN_PDF)

    print(f"\n{'='*80}")
    print(f"全部处理完成: ok={n_ok}, fail={n_fail}, 总耗时 {(time.time()-total_start)/60:.1f} min")
    if failed:
        print(f"失败 PDF:")
        for f in failed:
            print(f"  ❌ {f}")


if __name__ == "__main__":
    asyncio.run(main())
