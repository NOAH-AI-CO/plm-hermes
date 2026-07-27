"""sahzu 决策树图谱构建 — 只处理 NCCN / CSCO / CACA / ESMO 的文件。

用法:
    cd noah_agent
    python -m agent.patient_like_me.v1.indexing.run_graph_indexing_sahzu \
        [--dir /Users/wuyifu/Downloads/all_pdfs] [--only NCCN,ESMO]

流程复用 run_graph_indexing.run_one_pdf, 会跑 Stage 1 → 1.5 → 2 → 2.5, 结果直接写入
plm_guidelines 里对应 doc_id 的图谱字段。
"""
import argparse
import asyncio
import os
import re
import sys
import time
from pathlib import Path


_SCRIPT_DIR = Path(__file__).resolve().parent
_NOAH_AGENT_ROOT = _SCRIPT_DIR.parents[3]

# Vertex / GCP 凭据: 与 single 版本一致
_gcp_key = _NOAH_AGENT_ROOT / "gcp_claude.json"
if _gcp_key.exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_gcp_key)
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "noah-ai-claude")
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


SAHZU_PDF_DIR = "/Users/wuyifu/Downloads/all_pdfs"

_ORG_PATTERNS = [
    (re.compile(r"NCCN", re.IGNORECASE), "NCCN"),
    (re.compile(r"CSCO|中国临床肿瘤学会", re.IGNORECASE), "CSCO"),
    (re.compile(r"ESMO", re.IGNORECASE), "ESMO"),
    (re.compile(r"CACA|中国抗癌协会", re.IGNORECASE), "CACA"),
]


def infer_orgs(filename: str) -> list[str]:
    out = []
    for p, o in _ORG_PATTERNS:
        if p.search(filename or "") and o not in out:
            out.append(o)
    return out


def collect_targets(pdf_dir: str, only: set[str] | None = None) -> list[Path]:
    targets: list[Path] = []
    for entry in sorted(Path(pdf_dir).iterdir()):
        if not entry.is_file() or entry.suffix.lower() != ".pdf":
            continue
        orgs = infer_orgs(entry.name)
        if not orgs:
            continue
        if only and not (set(orgs) & only):
            continue
        targets.append(entry)
    return targets


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=SAHZU_PDF_DIR)
    ap.add_argument("--only", default="",
                    help="逗号分隔的组织白名单, 空 = NCCN+CSCO+CACA+ESMO 全部")
    ap.add_argument("--start", type=int, default=0, help="从第 N 份开始 (断点续跑)")
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少份, 0=不限")
    args = ap.parse_args()

    only = {s.strip().upper() for s in args.only.split(",") if s.strip()} or None
    targets = collect_targets(args.dir, only=only)
    if args.start:
        targets = targets[args.start:]
    if args.limit:
        targets = targets[:args.limit]

    print(f"待处理 {len(targets)} 份 (only={only or 'ALL 4-org'}):")
    for i, p in enumerate(targets, 1):
        print(f"  [{i}] {p.name}  orgs={infer_orgs(p.name)}")

    total_start = time.time()
    ok, fail = 0, 0
    fails: list[tuple[str, str]] = []
    for i, pdf in enumerate(targets, 1):
        print(f"\n{'#'*80}\n# [{i}/{len(targets)}] {pdf.name}\n{'#'*80}")
        t0 = time.time()
        try:
            await rgi.run_one_pdf(str(pdf))
            ok += 1
            print(f"[{i}/{len(targets)}] OK, 用时 {(time.time()-t0)/60:.1f} min")
        except Exception as e:
            fail += 1
            fails.append((pdf.name, f"{type(e).__name__}: {e}"))
            print(f"[{i}/{len(targets)}] FAIL: {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()

    print(f"\n{'='*80}\n全部完成, ok={ok} fail={fail}, 总耗时 {(time.time()-total_start)/60:.1f} min")
    if fails:
        print("失败清单:")
        for name, err in fails:
            print(f"  - {name} — {err}")


if __name__ == "__main__":
    asyncio.run(main())
