import asyncio
from io import BytesIO
from pathlib import Path
from typing import List, Dict, Any, Optional

import pypdf

from docling.document_converter import DocumentConverter
from docling_core.types.io import DocumentStream

_converter = None

def _get_converter() -> DocumentConverter:
    global _converter
    if _converter is None:
        _converter = DocumentConverter()
    return _converter

try:
    from docling_core.types.doc import PictureItem, TableItem
    _HAS_PICTURE_ITEM = True
except ImportError:
    PictureItem = type(None)  # noqa: F811
    TableItem = type(None)
    _HAS_PICTURE_ITEM = False

def pdf_to_text(pdf_stream) -> Optional[str]:
    text = ""
    try:
        pdf_stream.seek(0)
        pdf_reader = pypdf.PdfReader(pdf_stream)

        for page in pdf_reader.pages:
            text += page.extract_text() or ""
    except Exception as e:
        print(f"[pdf_to_text] Error reading PDF: {e}")
        return None

    return text or None


# 扫描件 PDF 的 OCR 回退阈值：pypdf 抽到的字符数低于此值视为"扫描件 / 无文本层"。
# 不写 0 是因为有些 PDF 会带几个空白页码、装饰字符等，但实际正文是图。
_SCANNED_PDF_TEXT_THRESHOLD = 50
_OCR_MAX_PAGES = 30  # 限制 OCR 页数，避免 100 页扫描件爆炸


def _pdf_pages_to_images(file_bytes: bytes) -> list[bytes]:
    """逐页渲染 PDF 为 PNG bytes 列表。失败时返回空列表。"""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        print("[pdf_ocr_fallback] pypdfium2 not installed; cannot render scanned PDF for OCR")
        return []

    images: list[bytes] = []
    try:
        pdf = pdfium.PdfDocument(file_bytes)
        n_pages = min(len(pdf), _OCR_MAX_PAGES)
        for i in range(n_pages):
            page = pdf[i]
            # scale=2 → 渲染密度约 144 DPI，平衡 OCR 准确度与体积
            bitmap = page.render(scale=2)
            pil_img = bitmap.to_pil()
            buf = BytesIO()
            pil_img.save(buf, format="PNG")
            images.append(buf.getvalue())
    except Exception as e:
        print(f"[pdf_ocr_fallback] PDF render failed: {e}")
        return []

    return images


def _pdf_ocr_fallback(file_bytes: bytes) -> Optional[str]:
    """扫描件 PDF 兜底：渲染每页 → Qwen-VL OCR → 拼接文本。

    convert_document 通常在 ``asyncio.to_thread`` 包装的工作线程里被调用，
    工作线程没有运行中的事件循环，所以 ``asyncio.run`` 是安全的。
    """
    images = _pdf_pages_to_images(file_bytes)
    if not images:
        return None

    try:
        from agent.translation.llm_translate import qwen_vl_extract_batch
        texts = asyncio.run(qwen_vl_extract_batch(images, batch_size=8))
    except RuntimeError as e:
        # 如果调用方没把 convert_document 放到 to_thread 里（直接在事件循环里同步调用），
        # asyncio.run 会抛 "asyncio.run() cannot be called from a running event loop"。
        # 这种用法不应出现在生产路径，但兜底降级为返回 None（让 docling 接力）。
        print(f"[pdf_ocr_fallback] cannot run OCR from running event loop: {e}")
        return None
    except Exception as e:
        print(f"[pdf_ocr_fallback] OCR failed: {e}")
        return None

    joined = "\n\n".join(t.strip() for t in texts if t and t.strip())
    return joined or None


def convert_document(name: str, file_bytes: bytes) -> str:
    stream = BytesIO(file_bytes)
    lower_name = name.lower()

    if lower_name.endswith(".pdf"):
        text = pdf_to_text(stream)
        if text and len(text.strip()) >= _SCANNED_PDF_TEXT_THRESHOLD:
            return text

        # pypdf 抽到的文本极少或为空：极可能是扫描件，回退到 OCR。
        # 注意 docling 也能解析 PDF 但对扫描件支持弱，所以 OCR 优先于 docling。
        ocr_text = _pdf_ocr_fallback(file_bytes)
        if ocr_text:
            return ocr_text

        # 最后兜底：让 docling 尝试一次（可能拿到一些目录页等）
        stream.seek(0)

    if lower_name.endswith(".txt") or lower_name.endswith(".md"):
        stream.seek(0)
        return stream.read().decode("utf-8", errors="ignore")

    stream.seek(0)
    source = DocumentStream(name=name, stream=stream)
    result = _get_converter().convert(source)
    md = result.document.export_to_markdown()
    return md or "empty"


def parse_document_with_images(
    name: str,
    file_bytes: bytes,
    *,
    image_output_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    解析 doc/docx，按文档顺序返回「文本片段 + 图片」列表，便于后续对图片翻译并回嵌。

    仅支持 .doc、.docx。.txt / .md 返回单一段 text；.pdf 暂不支持（请用现有 convert_document 或 PDF 专用流程）。

    返回格式：列表，每项为
      - {"type": "text", "content": "段落或标题等文本"}
      - {"type": "image", "content": <bytes 或临时文件路径>, "index": 0-based 序号}
    若某张图从 docling 取不到（如 DOCX 未生成 picture image），则该项为
      {"type": "image", "content": None, "index": i, "error": "说明"}
    """
    stream = BytesIO(file_bytes)
    lower_name = name.lower()

    if lower_name.endswith(".txt") or lower_name.endswith(".md"):
        stream.seek(0)
        text = stream.read().decode("utf-8", errors="ignore")
        return [{"type": "text", "content": text or ""}]

    if lower_name.endswith(".pdf"):
        raise ValueError("parse_document_with_images 暂不支持 PDF，请用 convert_document 或 PDF 翻译流程")

    if not (lower_name.endswith(".doc") or lower_name.endswith(".docx")):
        raise ValueError(f"parse_document_with_images 仅支持 .doc/.docx，当前为 {name}")

    stream.seek(0)
    source = DocumentStream(name=name, stream=stream)
    result = _get_converter().convert(source)
    doc = result.document

    segments: List[Dict[str, Any]] = []
    image_index = 0
    image_output_path = Path(image_output_dir) if image_output_dir else None

    for element, _level in doc.iterate_items():
        if not _HAS_PICTURE_ITEM:
            break
        if isinstance(element, PictureItem):
            try:
                img = element.get_image(doc)
                if img is not None:
                    buf = BytesIO()
                    img.save(buf, format="PNG")
                    raw_bytes = buf.getvalue()
                    seg = {"type": "image", "content": raw_bytes, "index": image_index}
                    if image_output_path is not None:
                        out_path = image_output_path / f"image_{image_index}.png"
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        out_path.write_bytes(raw_bytes)
                        seg["path"] = str(out_path)
                    segments.append(seg)
                    image_index += 1
                else:
                    segments.append({"type": "image", "content": None, "index": image_index, "error": "get_image 返回 None"})
                    image_index += 1
            except Exception as e:
                segments.append({"type": "image", "content": None, "index": image_index, "error": str(e)})
                image_index += 1
            continue
        if isinstance(element, TableItem):
            export_md = getattr(element, "export_to_markdown", None)
            if callable(export_md):
                try:
                    table_md = export_md()
                    segments.append({"type": "text", "content": table_md or ""})
                except Exception:
                    segments.append({"type": "text", "content": "[表格]"})
            else:
                segments.append({"type": "text", "content": "[表格]"})
            continue
        text = getattr(element, "text", None) or getattr(element, "orig", None)
        if text is not None and isinstance(text, str) and text.strip():
            segments.append({"type": "text", "content": text.strip()})

    if not segments and not _HAS_PICTURE_ITEM:
        md = doc.export_to_markdown()
        return [{"type": "text", "content": md or ""}]

    if not segments:
        md = doc.export_to_markdown()
        return [{"type": "text", "content": md or ""}]

    return segments


async def batch_convert_documents_async(files: List[Dict[str, Any]], max_concurrent: int = 10, **kwargs) -> List[Dict[str, Any]]:
    semaphore = asyncio.Semaphore(max_concurrent)

    async def convert_single(idx: int, f: Dict[str, Any]) -> Dict[str, Any]:
        name = f.get("name") or "unnamed"
        content_bytes = f.get("content_bytes") or b""

        async with semaphore:
            print(f"[batch_convert_documents_async] ({idx}/{len(files)}) 转换: {name}")
            try:
                text = await asyncio.to_thread(convert_document, name, content_bytes)
                return {
                    "name": name,
                    "content": text,
                    "error": None,
                }
            except Exception as e:
                print(f"[batch_convert_documents_async] Error converting {name}: {e}")
                return {
                    "name": name,
                    "content": "",
                    "error": str(e),
                }

    tasks = [
        convert_single(idx, f)
        for idx, f in enumerate(files, start=1)
    ]

    results = await asyncio.gather(*tasks)
    return results


# test
if __name__ == "__main__":
    import asyncio
    import sys
    from pathlib import Path

    async def test_batch():
        pdf_paths = [
            Path("/Users/yan/Downloads/AIH2010_nofig.pdf"),
            Path("/Users/yan/Downloads/2024 专家共识：洛拉替尼治疗ALK+晚期非小细胞肺癌不良事件的管理.pdf")
        ]
        files = []
        for p in pdf_paths:
            content_bytes = p.read_bytes()
            files.append({"name": p.name, "content": content_bytes})
        results = await batch_convert_documents_async(files)
        for r in results:
            print("====", r["name"], "====")
            print("error:", r["error"])
            print("content preview:", r["content"][:200], "...\n")

    def test_parse_with_images(docx_path: str):
        """命令行测试：python -m utils.docs.parsing <path_to.docx>"""
        p = Path(docx_path)
        if not p.is_file():
            print(f"文件不存在: {docx_path}")
            return
        name = p.name
        file_bytes = p.read_bytes()
        segments = parse_document_with_images(name, file_bytes)
        print(f"共 {len(segments)} 个片段")
        for i, seg in enumerate(segments):
            if seg["type"] == "text":
                content = (seg["content"] or "")[:80].replace("\n", " ")
                print(f"  [{i}] text: {content}...")
            else:
                content = seg.get("content")
                size = len(content) if content else 0
                err = seg.get("error", "")
                err_str = f" error={err}" if err else " (ok)"
                print(f"  [{i}] image index={seg.get('index')} size={size} bytes{err_str}")

    if len(sys.argv) > 1:
        test_parse_with_images(sys.argv[1])
    else:
        asyncio.run(test_batch())
