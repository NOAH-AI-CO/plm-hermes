"""恢复刚删掉的 3 个 PDF 的 plm_guidelines doc 元信息(含 vectors)。

chunks 还在(没动 plm_guideline_chunks),只需重建 doc 元信息。
不重建图谱(那是另外的 run_graph_indexing 流程)。
"""
import os, sys
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

from agent.patient_like_me.v1.indexing.index_nccn_pdfs import index_single_pdf

PDF_DIR = "/Users/wuyifu/NoahAgent/noah_agent/agent/patient_like_me/dify/data/25年nccn英文_副本"
TARGETS = [
    f"{PDF_DIR}/（2025.V1）NCCN临床实践指南：乳腺癌.pdf",
    f"{PDF_DIR}/（2025.V1）NCCN临床实践指南：降低乳腺癌风险.pdf",
    f"{PDF_DIR}/（2025.V1）NCCN临床实践指南：姑息治疗.pdf",
]

if __name__ == "__main__":
    for p in TARGETS:
        print(f"\n=== {Path(p).name} ===")
        info = index_single_pdf(p, is_cn_content=False, index_chunks=False)
        print(f"  ok: {info}")
    print("\n全部完成")
