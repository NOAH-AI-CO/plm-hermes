#!/usr/bin/env python3
import argparse
import asyncio
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from openai import AsyncOpenAI


CURRENT_FILE = Path(__file__).resolve()
NOAH_AGENT_ROOT = CURRENT_FILE.parents[2]
if str(NOAH_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(NOAH_AGENT_ROOT))

from config import api_config
from agent.bp.vlm import detailed_text_map


SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif"}


def build_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_config.ALIYUN_BAILIAN_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )


def image_to_data_uri(image_path: Path) -> str:
    suffix = image_path.suffix.lower().lstrip(".")
    mime_type = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
    with image_path.open("rb") as file:
        image_b64 = base64.b64encode(file.read()).decode("utf-8")
    return f"data:image/{mime_type};base64,{image_b64}"


async def call_vlm(client: AsyncOpenAI, image_data_uri: str, detailed: int, model: str, max_retries: int = 3) -> str:
    prompt = detailed_text_map.get(detailed, "请提取这个图片的描述，返回文本。")
    for attempt in range(max_retries):
        try:
            completion = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": image_data_uri},
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
                temperature=0,
            )
            return completion.choices[0].message.content or ""
        except Exception:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise


async def process_one_image(client: AsyncOpenAI, image_path: Path, detailed: int, model: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        output_path = image_path.with_suffix(".json")
        try:
            image_data_uri = image_to_data_uri(image_path)
            content = await call_vlm(client, image_data_uri, detailed=detailed, model=model)
            payload = {
                "image": str(image_path),
                "model": model,
                "detailed": detailed,
                "result": content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"✓ {image_path.name} -> {output_path.name}")
            return True
        except Exception as exc:
            payload = {
                "image": str(image_path),
                "model": model,
                "detailed": detailed,
                "error": str(exc),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"✗ {image_path.name} -> {output_path.name} (error)")
            return False


def list_images(input_dir: Path):
    return sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXTS
    )


async def main():
    parser = argparse.ArgumentParser(description="Batch call VLM for each image and write per-image JSON results.")
    parser.add_argument(
        "--input-dir",
        default="/Users/andy/Downloads/zht-case",
        help="Directory containing images.",
    )
    parser.add_argument(
        "--detailed",
        type=int,
        default=2,
        help="Detailed level for VLM prompt (default: 2).",
    )
    parser.add_argument(
        "--model",
        default="qwen3-vl-plus",
        help="Aliyun VLM model name (default: qwen3-vl-plus).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Concurrent VLM requests (default: 5).",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        raise ValueError(f"Invalid input directory: {input_dir}")

    images = list_images(input_dir)
    if not images:
        print(f"No supported image files found in {input_dir}")
        return

    print(f"Found {len(images)} image(s) in {input_dir}")
    client = build_client()
    semaphore = asyncio.Semaphore(max(1, args.concurrency))

    tasks = [
        process_one_image(client, image_path=image, detailed=args.detailed, model=args.model, semaphore=semaphore)
        for image in images
    ]
    results = await asyncio.gather(*tasks)

    success_count = sum(1 for item in results if item)
    print(f"Done. Success: {success_count}, Failed: {len(results) - success_count}")


if __name__ == "__main__":
    asyncio.run(main())