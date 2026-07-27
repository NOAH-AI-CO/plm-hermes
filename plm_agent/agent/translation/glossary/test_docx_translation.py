#!/usr/bin/env python3
"""
Translate 部署架构SEER.docx to English using agent.translation.txt_translate.
"""
import asyncio
import sys
import time
from pathlib import Path

# Allow running directly or as part of the noah_agent package
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from agent.translation.txt_translate import translate_text_file

INPUT_DOCX = Path("/Users/andy/Downloads/部署架构SEER.docx")
OUTPUT_DIR = Path("/Users/andy/Downloads")

TARGET_LANGUAGE = "English"


async def main():
    if not INPUT_DOCX.is_file():
        print(f"ERROR: Input file not found: {INPUT_DOCX}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Translating: {INPUT_DOCX}")
    print(f"Target language: {TARGET_LANGUAGE}")
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"{'='*60}")

    t0 = time.perf_counter()
    md_path, docx_path, _ = await translate_text_file(
        origin_path=str(INPUT_DOCX),
        target_language=TARGET_LANGUAGE,
        output_dir=str(OUTPUT_DIR),
    )
    elapsed = time.perf_counter() - t0

    print(f"\nDone in {elapsed:.1f}s")
    print(f"  MD   : {md_path}")
    print(f"  DOCX : {docx_path}")


if __name__ == "__main__":
    asyncio.run(main())
