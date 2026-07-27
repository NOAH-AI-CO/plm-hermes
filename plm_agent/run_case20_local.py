#!/usr/bin/env python3
"""One-off driver: run case 20 (test2 dataset) for local-vs-test-env timing comparison."""
import asyncio
import os
import re
import sys
import time
from pathlib import Path

_NOAH_AGENT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_NOAH_AGENT_ROOT))

_gcp_key = _NOAH_AGENT_ROOT / "gcp_key.json"
if _gcp_key.exists() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_gcp_key)
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "noahai-440408")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")

CASE_FILE = _NOAH_AGENT_ROOT / "agent/patient_like_me/v1/test/batch_results_test2/case_20.txt"


def extract_question() -> str:
    text = CASE_FILE.read_text(encoding="utf-8")
    m = re.search(r"=== QUESTION ===\n(.*?)\n=== ", text, re.DOTALL)
    if not m:
        raise RuntimeError("QUESTION block not found")
    return m.group(1).strip()


async def main():
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    question = extract_question()
    print(f"Question chars: {len(question)}")

    from agent.patient_like_me.v1.rag.workflow import run_plm_workflow

    t0 = time.time()
    result = await run_plm_workflow(question, task_id="case20_local_compare")
    elapsed = time.time() - t0

    print(f"\nWall clock elapsed: {elapsed:.2f}s")
    print(f"Output length: {len(result.get('output', ''))}")


if __name__ == "__main__":
    asyncio.run(main())
