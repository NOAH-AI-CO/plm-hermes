#!/usr/bin/env python3
"""
前置 MinerU OCR：调用 MinerU /file_parse 接口，获取 middle.json 等结果，供 ocr_translate 等流程使用。

用法示例:
    from agent.translation.mineru_ocr import call_mineru_parse

    result = call_mineru_parse("/path/to/doc.pdf", return_middle_json=True)
    # 或传入内存中的 PDF 字节
    result = call_mineru_parse("doc.pdf", data=pdf_bytes, return_middle_json=True)
"""
import json
import logging
import os
import socket
import time
from io import BytesIO
from typing import Any, List, Optional

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)


class _TCPKeepAliveAdapter(HTTPAdapter):
    """HTTPAdapter that enables TCP keepalive on every connection."""

    def init_poolmanager(self, *args, **kwargs):
        opts = [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
        ]
        if hasattr(socket, "TCP_KEEPIDLE"):      # Linux
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60))
        elif hasattr(socket, "TCP_KEEPALIVE"):   # macOS
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, 60))
        if hasattr(socket, "TCP_KEEPINTVL"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 30))
        if hasattr(socket, "TCP_KEEPCNT"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5))
        kwargs.setdefault("socket_options", opts)
        super().init_poolmanager(*args, **kwargs)


_session = requests.Session()
_session.mount("http://", _TCPKeepAliveAdapter())
_session.mount("https://", _TCPKeepAliveAdapter())

# 与 pp.call_mineru 保持一致，可改为环境变量
DEFAULT_MINERU_PARSE_URL = os.environ.get(
    "MINERU_FILE_PARSE_URL", "http://136.110.229.215/file_parse"
)
RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}

# 按扩展名选 MIME，支持 PDF 与常见图片（接口支持）
def _mime_for_path(path: str) -> str:
    ext = os.path.splitext(path.split('?')[0])[1].lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext in (".gif", ".bmp", ".webp"):
        return f"image/{ext[1:]}"
    return "application/octet-stream"


def call_mineru_parse(
    pdf_path: str,
    data: Optional[bytes] = None,
    *,
    output_dir: str = "./output",
    lang_list: Optional[List[str]] = None,
    backend: str = "pipeline",
    parse_method: str = "auto",
    formula_enable: bool = False,
    table_enable: bool = False,
    server_url: Optional[str] = None,
    return_md: bool = True,
    return_middle_json: bool = True,
    return_model_output: bool = False,
    return_content_list: bool = False,
    return_images: bool = True,
    response_format_zip: bool = False,
    start_page_id: int = 0,
    end_page_id: int = 99999,
    url: Optional[str] = None,
    timeout: tuple = (180, 1200),
    **kwargs: Any,
) -> dict:
    """
    调用 MinerU /file_parse 接口做 PDF 解析（前置 OCR），返回结果中含 middle 信息时供 ocr_translate 使用。

    :param pdf_path: 文件路径（支持 .pdf、.jpg/.jpeg、.png 等；当 data 为 None 时从该路径读取）；当 data 不为 None 时仅用于生成文件名与 MIME。
    :param data: 可选，已读入内存的文件字节（PDF 或图片）。若提供则不再从 pdf_path 读文件（此时 pdf_path 仅作文件名）。
    :param output_dir: 服务端输出目录说明（部分实现会忽略）。
    :param lang_list: 语言列表，如 ["ch"]、["ch","en"]。
    :param backend: 解析后端，如 pipeline / hybrid-auto-engine / vlm-auto-engine 等。
    :param parse_method: auto / txt / ocr。
    :param formula_enable: 是否解析公式。
    :param table_enable: 是否解析表格。
    :param server_url: vlm/hybrid 的 http-client 后端时使用的 openai 兼容服务地址。
    :param return_md: 是否返回 markdown。
    :param return_middle_json: 必须为 True 时才能拿到 middle 结构供 ocr_translate 使用。
    :param return_model_output: 是否返回模型原始输出 JSON。
    :param return_content_list: 是否返回 content list。
    :param return_images: 是否返回提取的图片。默认 True（OCR PDF 时常用）。
    :param response_format_zip: 是否以 ZIP 形式返回。
    :param start_page_id: 起始页（从 0 开始）。
    :param end_page_id: 结束页。
    :param url: 覆盖默认的 /file_parse 完整 URL。
    :param timeout: (connect_timeout, read_timeout)。
    :param kwargs: 其余表单项会一并提交（用于兼容未来参数）。
    :return: 接口 JSON 响应；若 response_format_zip=True 则返回内容由接口约定（可能是二进制）。
    """
    print(f"Calling MinerU OCR... (PDF Path: {pdf_path})")
    if lang_list is None:
        lang_list = ["ch"]

    request_url = url or DEFAULT_MINERU_PARSE_URL
    pdf_name = os.path.basename(pdf_path.split('?')[0]) or os.path.basename(pdf_path)

    # 构建 form data（与 /file_parse 的 Form 参数一致）
    form_data: List[tuple] = [
        ("output_dir", output_dir),
        ("backend", backend),
        ("parse_method", parse_method),
        ("formula_enable", "true" if formula_enable else "false"),
        ("table_enable", "true" if table_enable else "false"),
        ("return_md", "true" if return_md else "false"),
        ("return_middle_json", "true" if return_middle_json else "false"),
        ("return_model_output", "true" if return_model_output else "false"),
        ("return_content_list", "true" if return_content_list else "false"),
        ("return_images", "true" if return_images else "false"),
        ("response_format_zip", "true" if response_format_zip else "false"),
        ("start_page_id", str(start_page_id)),
        ("end_page_id", str(end_page_id)),
    ]
    for lang in lang_list:
        form_data.append(("lang_list", lang))
    if server_url is not None:
        form_data.append(("server_url", server_url))
    for k, v in kwargs.items():
        if v is None:
            continue
        if isinstance(v, bool):
            form_data.append((k, "true" if v else "false"))
        elif isinstance(v, (list, tuple)):
            for item in v:
                form_data.append((k, str(item)))
        else:
            form_data.append((k, str(v)))

    mime = _mime_for_path(pdf_path)

    max_retries = 3
    response = None
    raw_content = b""
    for attempt in range(max_retries):
        try:
            if data is not None:
                files = {"files": (pdf_name, BytesIO(data), mime)}
                response = _session.post(
                    request_url,
                    files=files,
                    data=form_data,
                    timeout=timeout,
                    stream=True,
                )
            else:
                with open(pdf_path, "rb") as f:
                    files = {"files": (pdf_name, f, mime)}
                    response = _session.post(
                        request_url,
                        files=files,
                        data=form_data,
                        timeout=timeout,
                        stream=True,
                    )

            if response.status_code in RETRYABLE_HTTP_STATUS_CODES:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "MinerU HTTP %s on attempt %d/%d, retrying in %ds",
                        response.status_code,
                        attempt + 1,
                        max_retries,
                        wait,
                    )
                    time.sleep(wait)
                    continue
            response.raise_for_status()

            # Read chunked/large response incrementally to avoid connection-reset errors
            raw_content = b"".join(response.iter_content(chunk_size=65536))
            break
        except requests.exceptions.ChunkedEncodingError as exc:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(
                    "MinerU ChunkedEncodingError on attempt %d/%d, retrying in %ds: %s",
                    attempt + 1, max_retries, wait, exc,
                )
                time.sleep(wait)
            else:
                raise
        except requests.exceptions.RequestException as exc:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(
                    "MinerU request failed on attempt %d/%d, retrying in %ds: %s",
                    attempt + 1,
                    max_retries,
                    wait,
                    exc,
                )
                time.sleep(wait)
            else:
                raise
    else:
        raise RuntimeError("MinerU request failed after retries")

    if response_format_zip:
        return {"content": raw_content, "headers": dict(response.headers)}

    return json.loads(raw_content)


def call_mineru_and_get_middle(
    pdf_path: str,
    data: Optional[bytes] = None,
    **parse_kwargs: Any,
) -> Optional[dict]:
    """
    调用 MinerU 解析，仅返回 middle 字典（不落盘），供 ocr_translate 等流程在内存中使用。

    :param pdf_path: 文件路径（支持 .pdf、.jpg/.jpeg、.png 等）；data 不为 None 时仅作文件名。
    :param data: 可选，已读入的文件字节。
    :param parse_kwargs: 传给 call_mineru_parse 的其余参数。
    :return: middle 字典；若响应中无 middle 则返回 None。
    """
    middle, images = call_mineru_and_get_middle_and_images(
        pdf_path, data=data, return_images=True, **parse_kwargs
    )
    logger.info("Images returned: %s", "Yes" if images else "No")
    
    return middle


def call_mineru_and_get_middle_and_images(
    pdf_path: str,
    data: Optional[bytes] = None,
    return_images: bool = True,
    **parse_kwargs: Any,
) -> tuple[Optional[dict], Optional[dict]]:
    """
    调用 MinerU 解析，返回 middle 字典与裁切好的图片（供 ocr_translate 做图片 OCR 注释用，无需再从 PDF 裁切）。

    :param pdf_path: 文件路径（支持 .pdf、.jpg/.jpeg、.png 等）；data 不为 None 时仅作文件名。
    :param data: 可选，已读入的文件字节。
    :param return_images: 是否请求 MinerU 返回裁切图片（默认 True，便于翻译流程中直接用图做 OCR）。
    :param parse_kwargs: 传给 call_mineru_parse 的其余参数。
    :return: (middle 字典, images 字典)。images 为 None 或 { "文件名.jpg": "data:image/jpeg;base64,..." }。
    """
    parse_kwargs.setdefault("return_middle_json", True)
    parse_kwargs["return_images"] = return_images
    result = call_mineru_parse(pdf_path, data=data, **parse_kwargs)
    if not isinstance(result, dict):
        return None, None

    # 兼容新旧两种返回结构：
    # - 旧：顶层直接包含 results/middle_json
    # - 新：顶层包装 task_id/status/result，真实数据在 result 内
    result_root = result.get("result") if isinstance(result.get("result"), dict) else result
    middle = result.get("middle_json") or result.get("middle")
    if middle is None and isinstance(result_root, dict):
        middle = result_root.get("middle_json") or result_root.get("middle")
    images = None
    if isinstance(result_root, dict) and "results" in result_root:
        results = result_root["results"]
        pdf_basename = os.path.basename(pdf_path)
        name_no_ext = os.path.splitext(pdf_basename)[0]
        file_result = results.get(name_no_ext) or results.get(pdf_basename)
        if file_result is None and results:
            file_result = next(iter(results.values()), None)
        if isinstance(file_result, dict):
            raw = file_result.get("middle_json") or file_result.get("middle")
            if raw is not None:
                middle = json.loads(raw) if isinstance(raw, str) else raw
            if return_images and "images" in file_result:
                images = file_result["images"]
    if images is None and return_images:
        images = result.get("images")
        if images is None and isinstance(result_root, dict):
            images = result_root.get("images")
    if middle is None:
        # Log the actual response structure to help diagnose why middle is missing
        top_keys = list(result.keys()) if isinstance(result, dict) else repr(result)
        results_summary = None
        if isinstance(result, dict) and "results" in result:
            raw_results = result["results"]
            if isinstance(raw_results, dict):
                results_summary = {
                    k: list(v.keys()) if isinstance(v, dict) else repr(v)
                    for k, v in list(raw_results.items())[:3]
                }
            else:
                results_summary = repr(raw_results)[:500]
        error_info = result.get("error") or result.get("message") or result.get("detail") if isinstance(result, dict) else None
        logger.error(
            "MinerU did not return middle data for %s. "
            "Top-level keys: %s | error/message: %s | results structure: %s",
            pdf_path,
            top_keys,
            error_info,
            results_summary,
        )
        return None, images
    if isinstance(middle, str):
        middle = json.loads(middle)
    return middle, images


def run_mineru_and_save_middle(
    pdf_path: str,
    out_dir: Optional[str] = None,
    data: Optional[bytes] = None,
    **parse_kwargs: Any,
) -> dict:
    """
    调用 MinerU 解析并将结果中的 middle 信息按 ocr_translate 可用的方式落盘（若响应里包含）。

    :param pdf_path: PDF 路径或仅文件名（当 data 不为 None 时）。
    :param out_dir: 保存 middle 等结果的目录；默认使用与 pdf 同目录下的 mineru_out/<basename>。
    :param data: 可选，PDF 字节。
    :param parse_kwargs: 传给 call_mineru_parse 的其余参数（return_middle_json 默认 True）。
    :return: MinerU 接口返回的 JSON。
    """
    parse_kwargs.setdefault("return_middle_json", True)
    result = call_mineru_parse(pdf_path, data=data, **parse_kwargs)

    if not out_dir:
        base = os.path.splitext(os.path.basename(pdf_path))[0]
        out_dir = os.path.join(os.path.dirname(os.path.abspath(pdf_path)), "mineru_out", base)
    os.makedirs(out_dir, exist_ok=True)

    # 兼容新旧层级:
    # - 旧: results -> <文件名(无.pdf)> -> middle_json
    # - 新: result -> results -> <文件名(无.pdf)> -> middle_json
    if isinstance(result, dict):
        result_root = (
            result.get("result") if isinstance(result.get("result"), dict) else result
        )
        middle = result.get("middle_json") or result.get("middle")
        if middle is None and isinstance(result_root, dict):
            middle = result_root.get("middle_json") or result_root.get("middle")
        if middle is None and isinstance(result_root, dict) and "results" in result_root:
            results = result_root["results"]
            pdf_basename = os.path.basename(pdf_path)
            name_no_ext = os.path.splitext(pdf_basename)[0]
            # 兼容 key 为 "test_5" 或 "test_5.pdf"
            file_result = results.get(name_no_ext) or results.get(pdf_basename)
            if file_result is None and results:
                file_result = next(iter(results.values()), None)
            if isinstance(file_result, dict):
                raw = file_result.get("middle_json") or file_result.get("middle")
                if raw is not None:
                    middle = json.loads(raw) if isinstance(raw, str) else raw
        if middle is not None:
            if isinstance(middle, str):
                middle = json.loads(middle)
            middle_path = os.path.join(out_dir, "middle.json")
            with open(middle_path, "w", encoding="utf-8") as f:
                json.dump(middle, f, ensure_ascii=False, indent=2)
            logger.info("Wrote middle.json to %s", middle_path)
        if isinstance(result_root, dict) and "results" in result_root:
            with open(os.path.join(out_dir, "mineru_response.json"), "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            logger.info("Wrote full mineru_response.json to %s", out_dir)

    return result


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path or not os.path.isfile(path):
        print("Usage: python -m agent.translation.mineru_ocr <path_to.pdf>")
        sys.exit(1)
    r = call_mineru_parse(path, return_middle_json=True)
    print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])
