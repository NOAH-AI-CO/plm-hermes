# -*- coding: utf-8 -*-
"""
Attachment Tools - 附件下载工具

提供给 Agent 使用的附件下载 Tool。
"""

import asyncio
import logging
from typing import List, Optional
from pydantic import BaseModel, Field

from tools.core.base_tool import BaseTool
from tools.explore.mindsearch_tools_v3 import FunctionCallResult
from utils.web_search.attachment_downloader import AttachmentDownloader

logger = logging.getLogger(__name__)

MAX_URLS = 10  # Maximum number of URLs per request

# Global downloader instance for reuse
_global_downloader: Optional[AttachmentDownloader] = None

def _get_downloader() -> AttachmentDownloader:
    """Get or create global downloader instance."""
    global _global_downloader
    if _global_downloader is None:
        _global_downloader = AttachmentDownloader()
    return _global_downloader


class AttachmentDownloadInputSchema(BaseModel):
    """AttachmentDownload 输入参数"""
    explanation: str = Field(
        description='The explanation of why downloading these attachments.'
    )
    urls: List[str] = Field(
        description='List of attachment URLs to download (PDF/Excel/CSV/Word/Image).'
    )


class AttachmentDownload(BaseTool):
    """
    下载并解析附件工具

    支持的文件类型:
    - PDF: 提取文本内容
    - Excel (.xlsx, .xls): 提取表格数据预览
    - CSV: 提取表格数据预览
    - Word (.docx, .doc): 提取文本内容
    - Image (.jpg, .png, .gif, .webp, .bmp, .tiff): 保存到 Blob，通过 AgentRunSandbox 处理

    返回:
    - filename: 文件名
    - blob_path: Blob 存储路径 (用于 AgentRunSandbox 加载)
    - text_preview: 内容预览
    - data_description: 数据结构描述
    """

    name: str = 'AttachmentDownload'
    description: str = '''Download and parse attachments (PDF/Excel/CSV/Word/Image) from URLs.

Returns for each file:
- filename: Original filename
- blob_path: Storage path (use this in AgentRunSandbox.files parameter)
- text_preview: Content preview
- data_description: Description of data structure

For Excel/CSV files that need computation, use AgentRunSandbox with:
- files: [blob_path from this result]
- The file will be available at /home/user/attachments/{filename}'''

    input_schema: BaseModel = AttachmentDownloadInputSchema
    strict: bool = True

    async def _download_one(self, url: str) -> dict:
        """Download a single attachment and return result dict."""
        downloader = _get_downloader()
        try:
            # save_to_blob=True 因为 AgentRunSandbox 需要从 Blob 加载文件
            result = await downloader.download_single(url, save_to_blob=True)

            if result.success:
                return {
                    'url': result.url,
                    'filename': result.filename,
                    'type': result.type.value,
                    'blob_path': result.blob_path,
                    'text_preview': result.text_preview[:3000] if result.text_preview else '',
                    'data_description': result.data_description,
                    'success': True,
                    'error': None
                }
            else:
                return {
                    'url': result.url,
                    'filename': result.filename,
                    'type': result.type.value,
                    'blob_path': '',
                    'text_preview': '',
                    'data_description': '',
                    'success': False,
                    'error': result.error
                }

        except Exception as e:
            logger.warning(f"[AttachmentDownload] Failed to download {url}: {e}")
            return {
                'url': url,
                'filename': '',
                'type': '',
                'blob_path': '',
                'text_preview': '',
                'data_description': '',
                'success': False,
                'error': str(e)
            }

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        urls = kwargs.get('urls', [])
        explanation = kwargs.get('explanation', '')

        if len(urls) > MAX_URLS:
            logger.warning(f"[AttachmentDownload] URL count {len(urls)} exceeds limit {MAX_URLS}, truncating")
            urls = urls[:MAX_URLS]

        logger.info(f"[AttachmentDownload] Downloading {len(urls)} attachments in parallel. Reason: {explanation}")

        # Download all attachments in parallel
        tasks = [self._download_one(url) for url in urls]
        results = await asyncio.gather(*tasks)

        logger.info(f"[AttachmentDownload] Completed. Success: {sum(1 for r in results if r.get('success'))}/{len(results)}")

        yield FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            name=self.name,
            args=kwargs,
            result=list(results)
        )
