#!/usr/bin/env python3
"""
Test script: translate to_translate.pdf with use_glossary=True and use_glossary=False,
writing to two separate output files for manual comparison.
"""
import asyncio
import sys
import time
from pathlib import Path

# Allow running directly or as part of the noah_agent package
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from agent.translation.ocr_translate import translate_file

INPUT_PDF = Path(__file__).parent / "to_translate.pdf"
OUTPUT_WITH_GLOSSARY = Path(__file__).parent / "to_translate_with_glossary.pdf"
OUTPUT_WITHOUT_GLOSSARY = Path(__file__).parent / "to_translate_without_glossary.pdf"

TARGET_LANGUAGE = "English"


async def run_translation(use_glossary: bool) -> tuple[str, float]:
    label = "with glossary" if use_glossary else "without glossary"
    output_path = str(OUTPUT_WITH_GLOSSARY if use_glossary else OUTPUT_WITHOUT_GLOSSARY)
    print(f"\n{'='*60}")
    print(f"Starting translation {label} ...")
    print(f"  Input : {INPUT_PDF}")
    print(f"  Output: {output_path}")
    print(f"{'='*60}")

    t0 = time.perf_counter()
    result = await translate_file(
        origin_path=str(INPUT_PDF),
        target_language=TARGET_LANGUAGE,
        output_path=output_path,
        use_glossary=use_glossary,
    )
    elapsed = time.perf_counter() - t0
    print(f"\nDone ({label}): {result}  [{elapsed:.1f}s]")
    return result, elapsed


async def main():
    if not INPUT_PDF.is_file():
        print(f"ERROR: Input file not found: {INPUT_PDF}")
        sys.exit(1)

    # Run sequentially so logs from each run don't interleave
    result_with, t_with = await run_translation(use_glossary=True)
    # result_without, t_without = await run_translation(use_glossary=False)

    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    print(f"  With glossary   : {result_with}  ({t_with:.1f}s)")
    # print(f"  Without glossary: {result_without}  ({t_without:.1f}s)")
    print("\nOpen both PDFs to compare translation quality.")


if __name__ == "__main__":
    asyncio.run(main())
