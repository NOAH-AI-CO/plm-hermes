# -*- coding: utf-8 -*-
"""
Attachment Detector - 检测网页中的附件链接

从网页内容中检测：
1. 直接附件链接 (PDF/Excel/CSV/Word)
2. 可能包含附件的页面链接
"""

import re
import logging
from enum import Enum
from typing import List, Optional
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)


class AttachmentType(str, Enum):
    """附件类型"""
    PDF = "pdf"
    EXCEL = "excel"
    CSV = "csv"
    WORD = "word"
    IMAGE = "image"
    UNKNOWN = "unknown"


@dataclass
class DetectedAttachment:
    """检测到的直接附件"""
    url: str                              # 附件下载链接
    type: AttachmentType                  # 附件类型
    filename: str                         # 文件名
    title: str = ""                       # 链接文本
    source_context: str = ""              # 链接周围的上下文


@dataclass
class AttachmentPage:
    """可能包含附件的页面"""
    url: str                              # 页面链接
    hint: str                             # 匹配的关键词
    confidence: float                     # 置信度 (0-1)


@dataclass
class AttachmentDetectionResult:
    """检测结果"""
    direct: List[DetectedAttachment] = field(default_factory=list)   # 直接附件链接
    pages: List[AttachmentPage] = field(default_factory=list)        # 可能包含附件的页面


class AttachmentDetector:
    """检测网页中的附件链接"""

    # 文件扩展名映射
    EXTENSION_MAP = {
        '.pdf': AttachmentType.PDF,
        '.xlsx': AttachmentType.EXCEL,
        '.xls': AttachmentType.EXCEL,
        '.csv': AttachmentType.CSV,
        '.docx': AttachmentType.WORD,
        '.doc': AttachmentType.WORD,
    }

    # 支持的扩展名正则
    SUPPORTED_EXTENSIONS = r'\.(pdf|xlsx?|csv|docx?)(?:\?[^\s]*)?$'

    # 可能包含附件的页面关键词及其置信度
    ATTACHMENT_PAGE_KEYWORDS = [
        ('下载中心', 0.9), ('download center', 0.9),
        ('下载', 0.7), ('download', 0.7),
        ('附件', 0.9), ('attachment', 0.9),
        ('年报', 0.8), ('annual report', 0.8),
        ('财报', 0.8), ('financial report', 0.8),
        ('季报', 0.8), ('quarterly report', 0.8),
        ('报告', 0.6), ('report', 0.5),
        ('investor relations', 0.7), ('投资者关系', 0.7),
        ('sec filing', 0.9), ('sec filings', 0.9),
        ('完整版', 0.7), ('full version', 0.7),
        ('查看详情', 0.5), ('view details', 0.5),
        ('资料下载', 0.9), ('文档下载', 0.9),
    ]

    # 需要排除的链接模式
    EXCLUDE_PATTERNS = [
        r'^javascript:',
        r'^mailto:',
        r'^tel:',
        r'^#',
        r'\.(jpg|jpeg|png|gif|svg|ico|webp)(\?|$)',
    ]

    def detect(self, content: str, source_url: str) -> AttachmentDetectionResult:
        """
        检测网页内容中的附件链接

        Args:
            content: 网页内容 (Markdown 或 HTML)
            source_url: 来源网页 URL

        Returns:
            AttachmentDetectionResult: 检测结果
        """
        if not content:
            return AttachmentDetectionResult()

        direct = self._detect_direct_attachments(content, source_url)
        pages = self._detect_attachment_pages(content, source_url)

        return AttachmentDetectionResult(direct=direct, pages=pages)

    def _detect_direct_attachments(
        self,
        content: str,
        source_url: str
    ) -> List[DetectedAttachment]:
        """检测直接附件链接"""
        attachments = []
        seen_urls = set()

        # 模式1: Markdown 链接 [text](url)
        markdown_pattern = r'\[([^\]]*)\]\(([^)]+)\)'
        for match in re.finditer(markdown_pattern, content):
            title = match.group(1).strip()
            url = match.group(2).strip()

            attachment = self._try_create_attachment(
                url, source_url, title, content, match.start(), seen_urls
            )
            if attachment:
                attachments.append(attachment)

        # 模式2: HTML href 属性
        href_pattern = r'href=["\']([^"\']+)["\']'
        for match in re.finditer(href_pattern, content, re.IGNORECASE):
            url = match.group(1).strip()

            attachment = self._try_create_attachment(
                url, source_url, "", content, match.start(), seen_urls
            )
            if attachment:
                attachments.append(attachment)

        # 模式3: 纯 URL (以支持的扩展名结尾)
        url_pattern = r'https?://[^\s<>"\']+' + self.SUPPORTED_EXTENSIONS
        for match in re.finditer(url_pattern, content, re.IGNORECASE):
            url = match.group(0).strip()

            attachment = self._try_create_attachment(
                url, source_url, "", content, match.start(), seen_urls
            )
            if attachment:
                attachments.append(attachment)

        logger.info(f"Detected {len(attachments)} direct attachments from {source_url}")
        return attachments

    def _try_create_attachment(
        self,
        url: str,
        source_url: str,
        title: str,
        content: str,
        position: int,
        seen_urls: set
    ) -> Optional[DetectedAttachment]:
        """尝试创建附件对象"""

        # 检查是否是需要排除的链接
        for pattern in self.EXCLUDE_PATTERNS:
            if re.search(pattern, url, re.IGNORECASE):
                return None

        # 处理相对路径
        full_url = urljoin(source_url, url)

        # 检查是否已处理过
        if full_url in seen_urls:
            return None

        # 检查是否是附件链接
        file_type = self._detect_type_from_url(full_url)
        if file_type == AttachmentType.UNKNOWN:
            return None

        seen_urls.add(full_url)

        filename = self._extract_filename(full_url)
        context = self._extract_context(content, position)

        return DetectedAttachment(
            url=full_url,
            type=file_type,
            filename=filename,
            title=title or filename,
            source_context=context
        )

    def _detect_attachment_pages(
        self,
        content: str,
        source_url: str
    ) -> List[AttachmentPage]:
        """检测可能包含附件的页面链接"""
        pages = []
        seen_urls = set()

        # 提取所有链接
        patterns = [
            r'\[([^\]]*)\]\(([^)]+)\)',           # Markdown
            r'href=["\']([^"\']+)["\']',          # HTML href
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                if len(match.groups()) == 2:
                    title = match.group(1)
                    url = match.group(2)
                else:
                    title = ""
                    url = match.group(1)

                # 处理相对路径
                full_url = urljoin(source_url, url)

                # 排除已见过的和附件链接
                if full_url in seen_urls:
                    continue
                if self._detect_type_from_url(full_url) != AttachmentType.UNKNOWN:
                    continue

                # 检查是否需要排除
                should_exclude = False
                for exclude_pattern in self.EXCLUDE_PATTERNS:
                    if re.search(exclude_pattern, url, re.IGNORECASE):
                        should_exclude = True
                        break
                if should_exclude:
                    continue

                # 检查是否匹配关键词
                text_to_check = (title + ' ' + url).lower()
                max_confidence = 0
                matched_hint = ''

                for keyword, confidence in self.ATTACHMENT_PAGE_KEYWORDS:
                    if keyword.lower() in text_to_check:
                        if confidence > max_confidence:
                            max_confidence = confidence
                            matched_hint = keyword

                if max_confidence >= 0.5:
                    seen_urls.add(full_url)
                    pages.append(AttachmentPage(
                        url=full_url,
                        hint=matched_hint,
                        confidence=max_confidence
                    ))

        # 按置信度排序，取前 5 个
        pages.sort(key=lambda x: x.confidence, reverse=True)
        result = pages[:5]

        logger.info(f"Detected {len(result)} attachment pages from {source_url}")
        return result

    def _detect_type_from_url(self, url: str) -> AttachmentType:
        """从 URL 检测文件类型"""
        # 移除查询参数
        url_path = urlparse(url).path.lower()

        for ext, file_type in self.EXTENSION_MAP.items():
            if url_path.endswith(ext):
                return file_type

        return AttachmentType.UNKNOWN

    def _extract_filename(self, url: str) -> str:
        """从 URL 提取文件名"""
        parsed = urlparse(url)
        path = parsed.path

        # 获取路径最后一部分
        filename = path.split('/')[-1] if '/' in path else path

        # URL 解码
        try:
            from urllib.parse import unquote
            filename = unquote(filename)
        except Exception:
            pass

        return filename or "unknown"

    def _extract_context(self, content: str, position: int, window: int = 100) -> str:
        """提取链接周围的上下文"""
        start = max(0, position - window)
        end = min(len(content), position + window)
        context = content[start:end].strip()

        # 清理换行
        context = re.sub(r'\s+', ' ', context)

        return context
