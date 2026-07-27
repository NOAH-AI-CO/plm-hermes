# -*- coding: utf-8 -*-
"""
Attachment Downloader - 下载和解析附件

职责：
1. 下载附件到内存
2. 存储到 Azure Blob (带 metadata)
3. 解析内容 (PDF/Excel/CSV/Word)
4. 返回解析结果
"""

import io
import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass

from utils.web_search.crawler import ContentFetcherBase
from utils.web_search.attachment_detector import (
    AttachmentType, DetectedAttachment
)
from utils.core.httpx_client import HttpxClientSingleton

logger = logging.getLogger(__name__)


@dataclass
class ParsedContent:
    """解析后的内容"""
    text_preview: str           # 文本预览 (给 LLM 看)
    data_description: str       # 数据描述 (描述数据结构)


@dataclass
class DownloadResult:
    """下载和解析结果"""
    url: str                    # 原始 URL
    filename: str               # 文件名
    type: AttachmentType        # 文件类型
    blob_path: str              # Blob 存储路径
    text_preview: str           # 文本预览
    data_description: str       # 数据描述
    success: bool               # 是否成功
    error: Optional[str] = None # 错误信息


class AttachmentDownloader(ContentFetcherBase):
    """下载和解析附件，继承 ContentFetcherBase 复用 Blob 存储"""

    # 配置
    MAX_FILE_SIZE = 50 * 1024 * 1024      # 50MB
    DOWNLOAD_TIMEOUT = 60                  # 60 秒
    BLOB_PREFIX = "attachments_ttl_1d"     # Blob 路径前缀

    # 解析限制
    MAX_PDF_PAGES = 50
    MAX_EXCEL_ROWS = 10000
    MAX_TEXT_LENGTH = 50000

    # 内容验证
    MIN_FILE_SIZES = {
        AttachmentType.PDF: 1024,
        AttachmentType.EXCEL: 512,
        AttachmentType.WORD: 512,
    }

    FILE_MAGIC_BYTES = {
        AttachmentType.PDF: b'%PDF',
        AttachmentType.EXCEL: b'PK',
        AttachmentType.WORD: b'PK',
    }

    CLOUD_ERROR_PATTERNS = [
        b'<Code>NoSuchKey</Code>',
        b'<Code>AccessDenied</Code>',
        b'<Code>BlobNotFound</Code>',
        b'<Error><Code>',
    ]

    async def download_and_process(
        self,
        attachments: List[DetectedAttachment],
        max_count: int = 5,
        save_to_blob: bool = False
    ) -> List[DownloadResult]:
        """
        批量下载并处理附件

        Args:
            attachments: 要下载的附件列表
            max_count: 最大下载数量
            save_to_blob: 是否保存到 Azure Blob (默认 False)

        Returns:
            List[DownloadResult]: 下载结果列表
        """
        results = []

        for attachment in attachments[:max_count]:
            try:
                result = await self._process_single(attachment, save_to_blob=save_to_blob)
                results.append(result)
            except Exception as e:
                logger.warning(f"Process attachment failed: {attachment.url}, {e}")
                results.append(DownloadResult(
                    url=attachment.url,
                    filename=attachment.filename,
                    type=attachment.type,
                    blob_path="",
                    text_preview="",
                    data_description="",
                    success=False,
                    error=str(e)
                ))

        return results

    async def download_single(
        self,
        url: str,
        filename: str = None,
        save_to_blob: bool = False
    ) -> DownloadResult:
        """
        下载单个附件

        Args:
            url: 附件 URL
            filename: 文件名 (可选，自动从 URL 提取)
            save_to_blob: 是否保存到 Azure Blob (默认 False，只下载解析)

        Returns:
            DownloadResult: 下载结果
        """
        if not filename:
            filename = self._extract_filename_from_url(url)

        file_type = self._detect_type(filename)

        attachment = DetectedAttachment(
            url=url,
            type=file_type,
            filename=filename,
            title=filename,
            source_context=""
        )

        return await self._process_single(attachment, save_to_blob=save_to_blob)

    @classmethod
    def _validate_downloaded_content(
        cls, file_bytes: bytes, file_type: AttachmentType, filename: str
    ) -> Optional[str]:
        """Validate downloaded content. Returns None if valid, or error string."""
        size = len(file_bytes)

        # Small files: check for cloud storage XML error responses
        if size < 2048:
            for pattern in cls.CLOUD_ERROR_PATTERNS:
                if pattern in file_bytes:
                    logger.warning(
                        f"Cloud error in {filename} ({size} bytes): {file_bytes[:200]}"
                    )
                    return (
                        f"Downloaded content is a cloud storage error, "
                        f"not a valid {file_type.value} file ({size} bytes)"
                    )

        # Minimum size check
        min_size = cls.MIN_FILE_SIZES.get(file_type)
        if min_size and size < min_size:
            return (
                f"File too small for {file_type.value}: "
                f"{size} bytes (minimum {min_size})"
            )

        # Magic bytes check
        expected = cls.FILE_MAGIC_BYTES.get(file_type)
        if expected and size >= 4:
            ole2 = b'\xd0\xcf\x11\xe0'
            if file_type in (AttachmentType.EXCEL, AttachmentType.WORD):
                if not (file_bytes[:len(expected)] == expected
                        or file_bytes[:len(ole2)] == ole2):
                    return f"Invalid {file_type.value} file header"
            elif file_bytes[:len(expected)] != expected:
                return f"Invalid {file_type.value} file header"

        return None

    async def _process_single(
        self,
        attachment: DetectedAttachment,
        save_to_blob: bool = False
    ) -> DownloadResult:
        """处理单个附件"""

        # 1. 下载到内存
        file_bytes, error, content_type = await self._download_to_memory(attachment.url)
        if error:
            # PMC 403 回退：尝试 EuropePMC
            fallback_url = self._get_pmc_fallback_url(attachment.url)
            if fallback_url:
                logger.info(f"PMC download failed ({error}), trying EuropePMC fallback: {fallback_url}")
                fb_bytes, fb_err, fb_ct = await self._download_to_memory(fallback_url)
                if not fb_err and fb_bytes:
                    file_bytes, error, content_type = fb_bytes, None, fb_ct

            if error:
                return DownloadResult(
                    url=attachment.url,
                    filename=attachment.filename,
                    type=attachment.type,
                    blob_path="",
                    text_preview="",
                    data_description="",
                    success=False,
                    error=error
                )

        # 检查文件大小
        if len(file_bytes) > self.MAX_FILE_SIZE:
            return DownloadResult(
                url=attachment.url,
                filename=attachment.filename,
                type=attachment.type,
                blob_path="",
                text_preview="",
                data_description="",
                success=False,
                error=f"File too large: {len(file_bytes)} bytes (max {self.MAX_FILE_SIZE})"
            )

        # 1a. 用 Content-Type + magic bytes 修正 UNKNOWN 类型
        if attachment.type == AttachmentType.UNKNOWN and file_bytes:
            refined_type = self._refine_type_from_content_type(content_type, file_bytes)
            if refined_type != AttachmentType.UNKNOWN:
                attachment = DetectedAttachment(
                    url=attachment.url,
                    type=refined_type,
                    filename=self._fix_filename(attachment.filename, refined_type),
                    title=attachment.title,
                    source_context=attachment.source_context,
                )

        # 1a2. 拦截 HTML 内容（UNKNOWN 类型时）
        if attachment.type == AttachmentType.UNKNOWN and file_bytes and self._is_html_content(file_bytes, content_type):
            # 尝试 PMC → EuropePMC 回退
            fallback_url = self._get_pmc_fallback_url(attachment.url)
            fallback_ok = False
            if fallback_url:
                logger.info(f"PMC returned HTML, trying EuropePMC fallback: {fallback_url}")
                fb_bytes, fb_err, fb_ct = await self._download_to_memory(fallback_url)
                if not fb_err and fb_bytes and not self._is_html_content(fb_bytes, fb_ct):
                    file_bytes, content_type = fb_bytes, fb_ct
                    refined = self._refine_type_from_content_type(content_type, file_bytes)
                    if refined != AttachmentType.UNKNOWN:
                        attachment = DetectedAttachment(
                            url=attachment.url, type=refined,
                            filename=self._fix_filename(attachment.filename, refined),
                            title=attachment.title, source_context=attachment.source_context,
                        )
                    fallback_ok = True
            if not fallback_ok:
                return DownloadResult(
                    url=attachment.url,
                    filename=attachment.filename,
                    type=attachment.type,
                    blob_path="",
                    text_preview="",
                    data_description="",
                    success=False,
                    error="URL returned an HTML page, not a downloadable file",
                )

        # 1b. 验证下载内容
        validation_error = self._validate_downloaded_content(
            file_bytes, attachment.type, attachment.filename
        )
        if validation_error:
            logger.warning(f"Content validation failed for {attachment.url}: {validation_error}")
            return DownloadResult(
                url=attachment.url,
                filename=attachment.filename,
                type=attachment.type,
                blob_path="",
                text_preview="",
                data_description="",
                success=False,
                error=validation_error
            )

        # 2. 可选：存储到 Blob
        blob_path = ""
        if save_to_blob:
            blob_path = self._save_attachment_to_blob(
                url=attachment.url,
                file_bytes=file_bytes,
                filename=attachment.filename
            )
            if not blob_path:
                logger.warning(f"Failed to save to blob, but continue parsing: {attachment.url}")

        # 3. 解析内容
        parsed = await self._parse_content(
            file_bytes, attachment.type, attachment.filename
        )

        # 检查解析是否失败
        if parsed.text_preview.startswith(("[Failed to parse", "[Unsupported file type")):
            logger.warning(f"Parse failed for {attachment.url}: {parsed.text_preview}")
            return DownloadResult(
                url=attachment.url,
                filename=attachment.filename,
                type=attachment.type,
                blob_path=blob_path,
                text_preview=parsed.text_preview,
                data_description=parsed.data_description,
                success=False,
                error=parsed.text_preview
            )

        return DownloadResult(
            url=attachment.url,
            filename=attachment.filename,
            type=attachment.type,
            blob_path=blob_path,
            text_preview=parsed.text_preview,
            data_description=parsed.data_description,
            success=True,
            error=None
        )

    async def _download_to_memory(self, url: str) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
        """下载文件到内存，返回 (file_bytes, error, content_type)"""
        try:
            client = HttpxClientSingleton.get_asynclient()
            response = await client.get(
                url,
                timeout=self.DOWNLOAD_TIMEOUT,
                follow_redirects=True,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                }
            )
            response.raise_for_status()
            content_type = response.headers.get('content-type', '')
            return response.content, None, content_type
        except Exception as e:
            logger.warning(f"Download failed: {url}, {e}")
            return None, str(e), None

    def _save_attachment_to_blob(
        self,
        url: str,
        file_bytes: bytes,
        filename: str
    ) -> Optional[str]:
        """保存附件到 Blob，返回 blob_path"""
        try:
            domain = self._get_domain(url)
            urlhash = self._urlhash(url)

            # 获取文件扩展名，保留在路径中
            ext = self._get_extension(filename)

            blob_path = f"{self.BLOB_PREFIX}/{domain}/{urlhash}{ext}"

            file_obj = io.BytesIO(file_bytes)

            self.blob_storage_client.upload_file(
                container=self.blob_container,
                blob=blob_path,
                file_obj=file_obj,
                metadata={
                    "url": url,
                    "filename": filename,
                    "extension": ext,
                },
            )

            logger.info(f"Attachment saved to blob: {blob_path}, filename: {filename}")
            return blob_path

        except Exception as e:
            logger.warning(f"Save attachment to blob failed: {e}")
            return None

    def _get_extension(self, filename: str) -> str:
        """获取文件扩展名（带点）"""
        filename_lower = filename.lower()
        for ext in ['.pdf', '.xlsx', '.xls', '.csv', '.docx', '.doc', '.pptx', '.ppt',
                    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif']:
            if filename_lower.endswith(ext):
                return ext
        return ''

    def fetch_attachment_from_blob(self, blob_path: str) -> Tuple[Optional[bytes], Optional[str]]:
        """
        从 Blob 读取附件

        Args:
            blob_path: Blob 路径

        Returns:
            (file_bytes, filename): 文件内容和文件名
        """
        try:
            # 获取 metadata
            meta = self.blob_storage_client.get_blob_meta(
                container=self.blob_container,
                blob=blob_path
            )
            blob_metadata = meta.get('metadata', {}) if meta else {}
            filename = blob_metadata.get('filename', 'unknown') if blob_metadata else 'unknown'

            # 下载内容
            file_bytes = self.blob_storage_client.load_file(
                container=self.blob_container,
                blob=blob_path
            )

            return file_bytes, filename

        except Exception as e:
            logger.warning(f"Fetch attachment from blob failed: {blob_path}, {e}")
            return None, None

    async def _parse_content(
        self,
        file_bytes: bytes,
        file_type: AttachmentType,
        filename: str
    ) -> ParsedContent:
        """解析附件内容"""

        if file_type == AttachmentType.PDF:
            return await self._parse_pdf(file_bytes, filename)
        elif file_type == AttachmentType.EXCEL:
            return await self._parse_excel(file_bytes, filename)
        elif file_type == AttachmentType.CSV:
            return await self._parse_csv(file_bytes, filename)
        elif file_type == AttachmentType.WORD:
            return await self._parse_word(file_bytes, filename)
        elif file_type == AttachmentType.IMAGE:
            size_kb = len(file_bytes) / 1024
            return ParsedContent(
                text_preview=f"Image file: {filename} ({size_kb:.1f} KB). Use AgentRunSandbox to process this image.",
                data_description=f"Image file: {filename}, {size_kb:.1f} KB"
            )
        else:
            return ParsedContent(
                text_preview=f"[Unsupported file type: {file_type}]",
                data_description=""
            )

    async def _parse_pdf(self, file_bytes: bytes, filename: str) -> ParsedContent:
        """解析 PDF"""
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=file_bytes, filetype="pdf")
            total_pages = len(doc)

            text_parts = []
            pages_to_read = min(total_pages, self.MAX_PDF_PAGES)

            for i in range(pages_to_read):
                page = doc[i]
                text_parts.append(page.get_text())

            text = "\n".join(text_parts)

            # 截断过长内容
            if len(text) > self.MAX_TEXT_LENGTH:
                text = text[:self.MAX_TEXT_LENGTH] + "\n...[truncated]"

            if total_pages > self.MAX_PDF_PAGES:
                text += f"\n[Note: Only first {self.MAX_PDF_PAGES} of {total_pages} pages shown]"

            doc.close()

            return ParsedContent(
                text_preview=text,
                data_description=f"PDF document: {filename}, {total_pages} pages"
            )

        except ImportError:
            logger.warning("PyMuPDF not installed, cannot parse PDF")
            return ParsedContent(
                text_preview="[PDF parsing requires PyMuPDF]",
                data_description=f"PDF document: {filename}"
            )
        except Exception as e:
            logger.warning(f"Parse PDF failed: {e}")
            return ParsedContent(
                text_preview=f"[Failed to parse PDF: {e}]",
                data_description=f"PDF document: {filename}"
            )

    async def _parse_excel(self, file_bytes: bytes, filename: str) -> ParsedContent:
        """解析 Excel"""
        try:
            import pandas as pd

            # 读取所有 sheet
            df_dict = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)

            text_parts = []
            data_desc_parts = []

            for sheet_name, df in df_dict.items():
                # 限制行数
                if len(df) > self.MAX_EXCEL_ROWS:
                    df = df.head(self.MAX_EXCEL_ROWS)

                columns = list(df.columns)
                row_count = len(df)

                # 文本预览
                text_parts.append(f"## Sheet: {sheet_name}")
                text_parts.append(f"Columns: {columns}")
                text_parts.append(f"Rows: {row_count}")
                text_parts.append(df.head(10).to_string())
                text_parts.append("")

                # 数据描述
                data_desc_parts.append(
                    f"Sheet '{sheet_name}': {row_count} rows, columns: {columns}"
                )

            text_preview = "\n".join(text_parts)
            if len(text_preview) > self.MAX_TEXT_LENGTH:
                text_preview = text_preview[:self.MAX_TEXT_LENGTH] + "\n...[truncated]"

            return ParsedContent(
                text_preview=text_preview,
                data_description=f"Excel file: {filename}. " + "; ".join(data_desc_parts)
            )

        except ImportError:
            logger.warning("pandas/openpyxl not installed, cannot parse Excel")
            return ParsedContent(
                text_preview="[Excel parsing requires pandas and openpyxl]",
                data_description=f"Excel file: {filename}"
            )
        except Exception as e:
            logger.warning(f"Parse Excel failed: {e}")
            return ParsedContent(
                text_preview=f"[Failed to parse Excel: {e}]",
                data_description=f"Excel file: {filename}"
            )

    async def _parse_csv(self, file_bytes: bytes, filename: str) -> ParsedContent:
        """解析 CSV"""
        try:
            import pandas as pd

            # 尝试不同编码
            df = None
            for encoding in ['utf-8', 'gbk', 'latin-1']:
                try:
                    df = pd.read_csv(io.BytesIO(file_bytes), encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue

            if df is None:
                return ParsedContent(
                    text_preview="[Failed to decode CSV with any encoding]",
                    data_description=f"CSV file: {filename}"
                )

            # 限制行数
            total_rows = len(df)
            if len(df) > self.MAX_EXCEL_ROWS:
                df = df.head(self.MAX_EXCEL_ROWS)

            columns = list(df.columns)

            text_preview = f"Columns: {columns}\n"
            text_preview += f"Total rows: {total_rows}\n\n"
            text_preview += df.head(20).to_string()

            if len(text_preview) > self.MAX_TEXT_LENGTH:
                text_preview = text_preview[:self.MAX_TEXT_LENGTH] + "\n...[truncated]"

            return ParsedContent(
                text_preview=text_preview,
                data_description=f"CSV file: {filename}, {total_rows} rows, columns: {columns}"
            )

        except ImportError:
            logger.warning("pandas not installed, cannot parse CSV")
            return ParsedContent(
                text_preview="[CSV parsing requires pandas]",
                data_description=f"CSV file: {filename}"
            )
        except Exception as e:
            logger.warning(f"Parse CSV failed: {e}")
            return ParsedContent(
                text_preview=f"[Failed to parse CSV: {e}]",
                data_description=f"CSV file: {filename}"
            )

    async def _parse_word(self, file_bytes: bytes, filename: str) -> ParsedContent:
        """解析 Word"""
        try:
            from docx import Document

            doc = Document(io.BytesIO(file_bytes))
            text = "\n".join([para.text for para in doc.paragraphs])

            if len(text) > self.MAX_TEXT_LENGTH:
                text = text[:self.MAX_TEXT_LENGTH] + "\n...[truncated]"

            return ParsedContent(
                text_preview=text,
                data_description=f"Word document: {filename}"
            )

        except ImportError:
            logger.warning("python-docx not installed, cannot parse Word")
            return ParsedContent(
                text_preview="[Word parsing requires python-docx]",
                data_description=f"Word document: {filename}"
            )
        except Exception as e:
            logger.warning(f"Parse Word failed: {e}")
            return ParsedContent(
                text_preview=f"[Failed to parse Word: {e}]",
                data_description=f"Word document: {filename}"
            )

    # Content-Type → AttachmentType 映射
    CONTENT_TYPE_MAP = {
        'application/pdf': AttachmentType.PDF,
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': AttachmentType.EXCEL,
        'application/vnd.ms-excel': AttachmentType.EXCEL,
        'text/csv': AttachmentType.CSV,
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': AttachmentType.WORD,
        'application/msword': AttachmentType.WORD,
        'image/jpeg': AttachmentType.IMAGE,
        'image/png': AttachmentType.IMAGE,
        'image/gif': AttachmentType.IMAGE,
        'image/webp': AttachmentType.IMAGE,
        'image/bmp': AttachmentType.IMAGE,
        'image/tiff': AttachmentType.IMAGE,
    }

    EXTENSION_FOR_TYPE = {
        AttachmentType.PDF: '.pdf',
        AttachmentType.EXCEL: '.xlsx',
        AttachmentType.CSV: '.csv',
        AttachmentType.WORD: '.docx',
        AttachmentType.IMAGE: '.jpg',
    }

    def _refine_type_from_content_type(self, content_type: str, file_bytes: bytes) -> AttachmentType:
        """用 HTTP Content-Type 和 magic bytes 修正文件类型"""
        if content_type:
            ct_lower = content_type.lower().split(';')[0].strip()
            for mime, att_type in self.CONTENT_TYPE_MAP.items():
                if ct_lower == mime:
                    return att_type
        # Magic bytes 检测
        if file_bytes[:4] == b'%PDF':
            return AttachmentType.PDF
        if file_bytes[:2] == b'PK':
            if b'xl/' in file_bytes[:2000]:
                return AttachmentType.EXCEL
            if b'word/' in file_bytes[:2000]:
                return AttachmentType.WORD
        # Image magic bytes
        if file_bytes[:3] == b'\xff\xd8\xff':
            return AttachmentType.IMAGE
        if file_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            return AttachmentType.IMAGE
        if file_bytes[:4] == b'GIF8':
            return AttachmentType.IMAGE
        if file_bytes[:4] == b'RIFF' and file_bytes[8:12] == b'WEBP':
            return AttachmentType.IMAGE
        if file_bytes[:2] == b'BM':
            return AttachmentType.IMAGE
        return AttachmentType.UNKNOWN

    def _is_html_content(self, file_bytes: bytes, content_type: str) -> bool:
        """检测内容是否为 HTML"""
        if content_type:
            ct_lower = content_type.lower()
            if 'text/html' in ct_lower or 'application/xhtml' in ct_lower:
                return True
        head = file_bytes[:500].lstrip().lower()
        if head.startswith((b'<html', b'<!doctype', b'<?xml')):
            return True
        return False

    def _get_pmc_fallback_url(self, url: str) -> Optional[str]:
        """从 PMC URL 提取 PMCID，生成 EuropePMC PDF 回退 URL"""
        import re
        if 'ncbi.nlm.nih.gov/pmc' not in url and 'pmc.ncbi.nlm.nih.gov' not in url:
            return None
        match = re.search(r'PMC(\d+)', url)
        if match:
            pmcid = f"PMC{match.group(1)}"
            return f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf"
        return None

    def _fix_filename(self, filename: str, file_type: AttachmentType) -> str:
        """修正文件名：确保有正确扩展名"""
        ext = self.EXTENSION_FOR_TYPE.get(file_type, '')
        if not ext:
            return filename
        if not filename or filename == 'unknown':
            return f"attachment{ext}"
        if not filename.lower().endswith(ext):
            return f"{filename}{ext}"
        return filename

    def _extract_filename_from_url(self, url: str) -> str:
        """从 URL 提取文件名"""
        from urllib.parse import urlparse, unquote
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        filename = path.split('/')[-1] if '/' in path else path
        return unquote(filename) or "unknown"

    def _detect_type(self, filename: str) -> AttachmentType:
        """检测文件类型"""
        filename_lower = filename.lower()
        if filename_lower.endswith('.pdf'):
            return AttachmentType.PDF
        elif filename_lower.endswith(('.xlsx', '.xls')):
            return AttachmentType.EXCEL
        elif filename_lower.endswith('.csv'):
            return AttachmentType.CSV
        elif filename_lower.endswith(('.docx', '.doc')):
            return AttachmentType.WORD
        elif filename_lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif')):
            return AttachmentType.IMAGE
        return AttachmentType.UNKNOWN
