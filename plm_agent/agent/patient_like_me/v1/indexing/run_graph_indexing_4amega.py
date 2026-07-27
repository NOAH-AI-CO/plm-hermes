"""4 case 召回的 11 个 NCCN PDF 全量图谱构建(Stage 1+1.5+2+2.5)。

直接复用 run_graph_indexing.run_one_pdf,但 SKIP_* 全部关掉,从 0 建。
"""
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
# indexing(SCRIPT_DIR) → v1(p0) → patient_like_me(p1) → agent(p2) → noah_agent(p3)
_NOAH_AGENT_ROOT = _SCRIPT_DIR.parents[3]

# 改用 gcp_claude.json 这个 key,原 gcp_key.json (vertex-ai-api@noahai-440408)
# 在 Stage 1 大量调用 gemini-3.1-pro-preview 时会被持续 403 限流(quota 耗尽),
# gcp_claude.json (noah-ai-claude project) 实测正常。
_gcp_key = _NOAH_AGENT_ROOT / "gcp_claude.json"
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_gcp_key)
os.environ["GOOGLE_CLOUD_PROJECT"] = "noah-ai-claude"
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")

if str(_NOAH_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_NOAH_AGENT_ROOT))

# 覆盖 api_config 里的 project id, 让 LLM wrapper 用 noah-ai-claude 项目
# (默认值 noahai-440408 的 SA 在 gemini-3.1-pro-preview 上限流严重)
from config import api_config as _ac
_ac.VERTEX_PROJECT_ID = "noah-ai-claude"

import asyncio, time

# 4 case 召回的 11 个 PDF(已确认全部缺图谱)
PDF_DIR = "/Users/wuyifu/NoahAgent/noah_agent/agent/patient_like_me/dify/data/25年nccn英文_副本"
PDFS = [
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


# Monkey-patch run_graph_indexing 的配置:
# - SKIP_* 都关,从 0 构建
# - 切到 noah-ai-claude project 后并发恢复原默认值
import agent.patient_like_me.v1.indexing.run_graph_indexing as rgi
rgi.SKIP_STAGE1 = False
rgi.SKIP_STAGE15 = False
rgi.STAGE1_CONCURRENCY = 8
rgi.STAGE2_CONCURRENCY = 3
rgi.PDFS = PDFS


async def main():
    total_start = time.time()
    n_ok = n_fail = 0
    for i, pdf in enumerate(PDFS, 1):
        print(f"\n{'#'*80}")
        print(f"# [{i}/{len(PDFS)}] {Path(pdf).name}")
        print(f"# elapsed so far: {(time.time()-total_start)/60:.1f} min")
        print(f"{'#'*80}")
        try:
            await rgi.run_one_pdf(pdf)
            n_ok += 1
        except Exception as e:
            n_fail += 1
            print(f"\n[ERROR] {Path(pdf).name} 失败: {e}")
            import traceback; traceback.print_exc()
    print(f"\n{'='*80}")
    print(f"全部完成: ok={n_ok}, fail={n_fail}, 总耗时 {(time.time()-total_start)/60:.1f} min")


if __name__ == "__main__":
    asyncio.run(main())
