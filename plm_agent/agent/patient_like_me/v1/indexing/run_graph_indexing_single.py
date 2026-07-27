"""单 PDF 图谱构建 — 用于跟主进程并行跑加速。

用法:
    python -m agent.patient_like_me.v1.indexing.run_graph_indexing_single <pdf_filename_keyword>

例:
    python -m agent.patient_like_me.v1.indexing.run_graph_indexing_single 降低乳腺癌风险
"""
import os, sys, asyncio, time
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

import agent.patient_like_me.v1.indexing.run_graph_indexing as rgi
rgi.SKIP_STAGE1 = False
rgi.SKIP_STAGE15 = False
rgi.STAGE1_CONCURRENCY = 8
rgi.STAGE2_CONCURRENCY = 3

PDF_DIR = "/Users/wuyifu/NoahAgent/noah_agent/agent/patient_like_me/dify/data/25年nccn英文_副本"


async def main():
    if len(sys.argv) < 2:
        print("用法: ... run_graph_indexing_single <pdf_filename_keyword>")
        sys.exit(1)
    keyword = sys.argv[1]
    candidates = [p for p in Path(PDF_DIR).glob("*.pdf") if keyword in p.name]
    if not candidates:
        print(f"找不到包含 '{keyword}' 的 PDF")
        sys.exit(1)
    if len(candidates) > 1:
        print(f"找到多个 PDF, 用第一个: {candidates[0].name}")
    pdf = str(candidates[0])
    print(f"=== 单 PDF 跑测: {Path(pdf).name} (并发=4/2) ===")
    t0 = time.time()
    try:
        await rgi.run_one_pdf(pdf)
        print(f"\n✅ 完成, 耗时 {(time.time()-t0)/60:.1f} min")
    except Exception as e:
        print(f"\n❌ 失败: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
