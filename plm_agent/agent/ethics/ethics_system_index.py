from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import os
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

from agent.ethics.policy_service import (
    index_system_policy_records,
)
from utils.docs.parsing import convert_document

# 按需填写两个目录（支持递归扫描）
DEFAULT_CHINA_POLICY_PATH = "/Users/ivylyx/Code/NoahAgent/我国伦理审查相关法规汇总20260324周吉银"
DEFAULT_GLOBAL_POLICY_PATH = "/Users/ivylyx/Code/NoahAgent/国际伦理审查相关指南汇总20260324周吉银"

_SUPPORTED_EXTENSIONS: set[str] = {".pdf", ".doc", ".docx"}
_PDF_CHUNK_PAGES: int = 30
_DOC_CONVERT_TIMEOUT_SECONDS: int = 180


def _iter_policy_files(root_path: str) -> list[Path]:
    root = Path(str(root_path or "").strip())
    if not root.exists() or not root.is_dir():
        return []
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # 跳过 Office 临时锁文件，例如 .~xxx.docx
        if path.name.startswith(".~"):
            continue
        if path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            continue
        files.append(path)
    files.sort(key=lambda p: str(p).lower())
    return files


def _build_doc_id(path: Path, region: str) -> str:
    # 以 region + 文件名 生成稳定 id，重复执行同名文档会覆盖更新
    raw = f"{region}:{path.name.strip().lower()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _pdf_to_text_chunked(file_bytes: bytes, chunk_pages: int = _PDF_CHUNK_PAGES) -> str:
    if chunk_pages <= 0:
        raise ValueError("chunk_pages must be positive")
    pypdf = importlib.import_module("pypdf")

    stream = BytesIO(file_bytes)
    pdf_reader = pypdf.PdfReader(stream)
    total_pages = len(pdf_reader.pages)
    if total_pages == 0:
        return ""
    text_parts: list[str] = []
    for start_page in range(0, total_pages, chunk_pages):
        end_page = min(start_page + chunk_pages, total_pages)
        chunk_text_parts: list[str] = []
        for page_index in range(start_page, end_page):
            chunk_text_parts.append(pdf_reader.pages[page_index].extract_text() or "")
        chunk_text = "".join(chunk_text_parts).strip()
        if chunk_text:
            text_parts.append(chunk_text)
    return "\n\n".join(text_parts).strip()


def _convert_doc_bytes_to_docx_bytes(file_bytes: bytes, file_name: str) -> bytes:
    if not file_bytes:
        raise ValueError("doc file bytes are empty")
    source_name = os.path.basename(file_name or "document.doc")
    if not source_name.lower().endswith(".doc"):
        source_name = f"{os.path.splitext(source_name)[0]}.doc"
    source_stem = os.path.splitext(source_name)[0]
    with tempfile.TemporaryDirectory(prefix="ethics_system_doc_convert_") as temp_dir:
        source_path = os.path.join(temp_dir, source_name)
        with open(source_path, "wb") as file_obj:
            file_obj.write(file_bytes)

        office_binary = shutil.which("soffice") or shutil.which("libreoffice")
        if not office_binary:
            raise ValueError("soffice/libreoffice is required for .doc conversion")

        convert_cmd = [
            office_binary,
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            temp_dir,
            source_path,
        ]
        try:
            subprocess.run(
                convert_cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=_DOC_CONVERT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise ValueError("doc to docx conversion timeout") from error
        except subprocess.CalledProcessError as error:
            stderr_text = (error.stderr or b"").decode("utf-8", errors="ignore").strip()
            raise ValueError(f"doc to docx conversion failed: {stderr_text or error}") from error

        target_path = os.path.join(temp_dir, f"{source_stem}.docx")
        if not os.path.exists(target_path):
            candidates = [name for name in os.listdir(temp_dir) if name.lower().endswith(".docx")]
            if not candidates:
                raise ValueError("doc to docx conversion produced no output")
            target_path = os.path.join(temp_dir, candidates[0])

        with open(target_path, "rb") as file_obj:
            converted_bytes = file_obj.read()
        if not converted_bytes:
            raise ValueError("converted docx is empty")
        return converted_bytes


async def _index_single_file(path: Path, *, region: str, index_name: str) -> dict[str, Any]:
    try:
        file_bytes = path.read_bytes()
        if path.suffix.lower() == ".pdf":
            content_text = _pdf_to_text_chunked(file_bytes=file_bytes, chunk_pages=_PDF_CHUNK_PAGES)
        elif path.suffix.lower() == ".doc":
            converted_docx_bytes = _convert_doc_bytes_to_docx_bytes(file_bytes=file_bytes, file_name=path.name)
            converted_name = f"{path.stem}.docx"
            content_text = convert_document(converted_name, converted_docx_bytes)
        else:
            content_text = convert_document(path.name, file_bytes)
        content_text = (content_text or "").strip()
        if not content_text:
            raise ValueError("parsed content is empty")
        doc_id = _build_doc_id(path, region)
        # 用去后缀文件名作为索引 title，降低扩展名噪音对 BM25 的影响。
        normalized_title = path.stem.strip() or path.name
        record = {
            "doc_id": doc_id,
            "title": normalized_title,
            "content": content_text,
            "region": region,
        }
        return {"ok": True, "file": str(path), "doc_id": doc_id, "record": record}
    except Exception as e:
        return {"ok": False, "file": str(path), "error": str(e)}


async def index_system_policy_dirs(*, china_policy_path: str, global_policy_path: str) -> dict[str, Any]:
    china_files = _iter_policy_files(china_policy_path)
    global_files = _iter_policy_files(global_policy_path)
    tasks: list[asyncio.Task] = []

    for path in china_files:
        tasks.append(
            asyncio.create_task(
                _index_single_file(
                    path,
                    region="china",
                    index_name="china_index",
                )
            )
        )
    for path in global_files:
        tasks.append(
            asyncio.create_task(
                _index_single_file(
                    path,
                    region="global",
                    index_name="global_index",
                )
            )
        )

    if not tasks:
        return {
            "indexed": [],
            "failed": [],
            "china_files": len(china_files),
            "global_files": len(global_files),
            "message": "no files found to index",
        }

    results = await asyncio.gather(*tasks)
    parsed_ok = [r for r in results if r.get("ok")]
    parse_failed = [r for r in results if not r.get("ok")]
    records = [r.get("record") for r in parsed_ok if isinstance(r.get("record"), dict)]
    index_result = await index_system_policy_records(records)
    indexed_ids = set(index_result.get("indexed") or [])
    index_errors = index_result.get("errors") or {}
    final_indexed = [r for r in parsed_ok if str(r.get("doc_id") or "") in indexed_ids]
    index_failed = [
        {"ok": False, "file": r.get("file"), "doc_id": r.get("doc_id"), "error": index_errors.get(str(r.get("doc_id") or ""), "index failed")}
        for r in parsed_ok
        if str(r.get("doc_id") or "") not in indexed_ids
    ]
    failed = parse_failed + index_failed
    return {
        "indexed": final_indexed,
        "failed": failed,
        "index_skipped": index_result.get("skipped") or [],
        "index_errors": index_errors,
        "china_files": len(china_files),
        "global_files": len(global_files),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index ethics system policy documents into Elasticsearch.")
    parser.add_argument(
        "--china-policy-path",
        default=DEFAULT_CHINA_POLICY_PATH,
        help="Path to China policy directory",
    )
    parser.add_argument(
        "--global-policy-path",
        default=DEFAULT_GLOBAL_POLICY_PATH,
        help="Path to global policy directory",
    )
    args = parser.parse_args()
    result = asyncio.run(
        index_system_policy_dirs(
            china_policy_path=str(args.china_policy_path),
            global_policy_path=str(args.global_policy_path),
        )
    )
    print(result)