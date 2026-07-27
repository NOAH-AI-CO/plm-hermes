import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[4]   # NoahServer/
_noah_agent_root = Path(__file__).resolve().parents[2]  # noah_agent/
sys.path.insert(0, str(_noah_agent_root))

# Config files (api.json, setting_test.json) are read relative to CWD.
import os as _os
_os.chdir(_repo_root)

# Many LLM client classes are instantiated at module-import time and read
# arbitrary keys from api_config.  Patch __missing__ so any absent key returns
# "stub" rather than raising, allowing the import chain to complete.
import config as _cfg  # noqa: E402 — must come after chdir

_cfg.api_config.__class__.__missing__ = lambda self, key: "stub"

# Several infrastructure modules create live connections (DB, Elasticsearch,
# Redis) at module-import time using config values unavailable in the test
# environment.  Stub them all out before the deep import chain fires.
from unittest.mock import MagicMock as _MagicMock, patch as _patch
import sys as _sys

# Patch connection-validating constructors at the library level so any
# module-level client instantiation succeeds without real credentials.
import elasticsearch as _es
_es.Elasticsearch = _MagicMock(return_value=_MagicMock())

try:
    from azure.storage.blob import BlobServiceClient as _BSC
    _BSC.from_connection_string = _MagicMock(return_value=_MagicMock())
except ImportError:
    pass

try:
    from azure.data.tables import TableServiceClient as _TSC
    _TSC.from_connection_string = _MagicMock(return_value=_MagicMock())
except ImportError:
    pass

# tiktoken in this environment doesn't recognise "gpt-4o"; patch before the
# class body that calls encoding_for_model runs.
import tiktoken as _tiktoken
_tiktoken.encoding_for_model = _MagicMock(return_value=_MagicMock())

for _mod in (
    "utils.sql_client",
    "agent.knowledge.es",
    "utils.redis_client",
    "utils.celery_client",
    "utils.azure.blob_client",
    "utils.utils.attachment",
):
    _sys.modules.setdefault(_mod, _MagicMock())

from agent.simple_research_rec.research_recommendation import stream_research_rec  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

QUERY = "阿米卡星治疗药物监测（TDM）"
SAMPLE_MD = Path(__file__).parent / "test_outputs" / "research_rec_20260525_145247.md"

OUTPUT_DIR = Path(__file__).parent / "test_outputs"


async def test_structurize_from_sample():
    """Test _structurize_report directly using the existing sample MD output."""
    from agent.simple_research_rec.research_recommendation import _structurize_report
    from google import genai
    from google.genai.types import HttpOptions

    if not SAMPLE_MD.exists():
        print(f"Sample file not found: {SAMPLE_MD}")
        return

    report_text = SAMPLE_MD.read_text(encoding="utf-8")
    print(f"Loaded sample report ({len(report_text)} chars) from {SAMPLE_MD.name}")
    print("Calling _structurize_report ...")

    client = genai.Client(http_options=HttpOptions(api_version="v1"))
    report_json = await _structurize_report(client, report_text)

    if report_json is None:
        print("_structurize_report returned None — check logs.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_file = SAMPLE_MD.with_suffix(".json")
    json_file.write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON saved: {json_file}")

    print("\nJSON summary:")
    print(f"  overview            : {len(report_json.get('overview', ''))} chars")
    print(f"  key_findings        : {len(report_json.get('key_findings', []))} items")
    print(f"  research_directions : {len(report_json.get('research_directions', []))} items")
    print(f"  references          : {len(report_json.get('references', []))} items")


async def main():
    print("=" * 60)
    print("Step 1: Test _structurize_report on existing sample MD")
    print("=" * 60)
    await test_structurize_from_sample()

    print()
    print("=" * 60)
    print("Step 2: Full pipeline test (requires live API credentials)")
    print("=" * 60)
    print(f"Running research recommendation for query: {QUERY!r}")

    report_text: str = ""
    report_json: dict | None = None
    full_event: dict | None = None

    async for event in stream_research_rec(QUERY):
        status = event["status"]

        if status == "processing":
            print(f"[processing] {event['content']}")

        elif status == "streaming":
            # Overwrite the line so we can watch progress without flooding terminal
            content = event["content"]
            lines = content.split("\n")
            preview = lines[-1] if lines[-1].strip() else (lines[-2] if len(lines) > 1 else "")
            print(f"\r[streaming]  {len(content):>6} chars  …{preview[-60:]!r}", end="", flush=True)
            report_text = content

        elif status == "done":
            print()  # newline after streaming progress
            report_text = event.get("content") or report_text
            report_json = event.get("json")
            full_event = event
            print("=" * 60)
            print("[done] Report complete.")

        elif status == "error":
            print(f"\n[error] {event['content']}")
            return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    md_file = OUTPUT_DIR / f"research_rec_{timestamp}.md"
    md_file.write_text(report_text, encoding="utf-8")
    print(f"Markdown saved : {md_file}")

    if full_event is not None:
        event_file = OUTPUT_DIR / f"research_rec_{timestamp}_event.json"
        event_file.write_text(json.dumps(full_event, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Full event saved: {event_file}")

    if report_json is not None:
        json_file = OUTPUT_DIR / f"research_rec_{timestamp}.json"
        json_file.write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON saved     : {json_file}")

        # Quick validation: print top-level keys and counts
        print("\nJSON summary:")
        print(f"  overview            : {len(report_json.get('overview', ''))} chars")
        print(f"  key_findings        : {len(report_json.get('key_findings', []))} items")
        print(f"  research_directions : {len(report_json.get('research_directions', []))} items")
        print(f"  references          : {len(report_json.get('references', []))} items")
    else:
        print("JSON structurization returned None — check logs for details.")


if __name__ == "__main__":
    asyncio.run(main())
