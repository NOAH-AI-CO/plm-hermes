import re
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from bs4 import BeautifulSoup

from .base_extractor import BaseExtractor


class TextExtractor(BaseExtractor):
    """Text file extractor for various text formats"""
    
    def __init__(self, file_path: Path, save_path: Optional[Path] = None, **kwargs):
        """
        Initialize text extractor
        
        Args:
            file_path: Path to text file
            save_path: Optional save path for extracted content
            **kwargs: Additional arguments
        """
        super().__init__()
        self.file_path = Path(file_path)
        self.save_path = Path(save_path) if save_path else None
        self.logger = logging.getLogger(__name__)
    
    def can_extract(self, file_path: Path) -> bool:
        """Check if this extractor can handle the given file"""
        suffix = file_path.suffix.lower()
        return suffix in ['.txt', '.md', '.markdown', '.html', '.htm', '.docx', '.doc']
    
    def get_supported_extensions(self) -> List[str]:
        """Get supported file extensions"""
        return ['.txt', '.md', '.markdown', '.html', '.htm', '.docx', '.doc']
    
    def extract(self, file_path: Path) -> Dict[str, Any]:
        """Extract content from text file"""
        if not self.validate_file(file_path):
            return self.create_extraction_result(file_path, content="", 
                                               metadata={"error": "File validation failed"})
        
        try:
            suffix = file_path.suffix.lower()
            
            if suffix in ['.html', '.htm']:
                return self._extract_html(file_path)
            elif suffix in ['.md', '.markdown']:
                return self._extract_markdown(file_path)
            elif suffix in ['.docx', '.doc']:
                return self._extract_word(file_path)
            else:
                return self._extract_plain_text(file_path)
                
        except Exception as e:
            self.logger.error(f"Error extracting text file {file_path}: {e}")
            return self.create_extraction_result(
                file_path=file_path,
                content="",
                metadata={"error": str(e), "extraction_method": "failed"}
            )
    
    def _extract_plain_text(self, file_path: Path) -> Dict[str, Any]:
        """Extract content from plain text file"""
        try:
            # 尝试不同编码读取文件
            encodings = ['utf-8', 'latin-1', 'cp1252', 'utf-8-sig']
            content = None
            
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                return self.create_extraction_result(
                    file_path=file_path,
                    content="",
                    metadata={"error": "Failed to read file with any encoding"}
                )
            
            # 分割文本块
            text_blocks = self._split_text_into_blocks(content)
            
            # 创建提取结果
            result = self.create_extraction_result(
                file_path=file_path,
                content=content,
                tables=[],
                images=[],
                metadata={
                    "text_blocks": len(text_blocks),
                    "word_count": len(content.split()),
                    "line_count": len(content.splitlines()),
                    "extraction_method": "plain-text"
                }
            )
            
            # 保存结果（如果指定了保存路径）
            if self.save_path:
                self._save_extraction_result(result)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error extracting plain text file {file_path}: {e}")
            return self.create_extraction_result(
                file_path=file_path,
                content="",
                metadata={"error": str(e), "extraction_method": "failed"}
            )
    
    def _extract_markdown(self, file_path: Path) -> Dict[str, Any]:
        """Extract content from Markdown file"""
        try:
            # 读取文件内容
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 提取文本块
            text_blocks = self._extract_markdown_blocks(content)
            
            # 提取表格
            tables = self._extract_markdown_tables(content)
            
            # 创建提取结果
            result = self.create_extraction_result(
                file_path=file_path,
                content=content,
                tables=tables,
                images=[],
                metadata={
                    "text_blocks": len(text_blocks),
                    "tables": len(tables),
                    "word_count": len(content.split()),
                    "line_count": len(content.splitlines()),
                    "extraction_method": "markdown"
                }
            )
            
            # 保存结果（如果指定了保存路径）
            if self.save_path:
                self._save_extraction_result(result)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error extracting Markdown file {file_path}: {e}")
            return self.create_extraction_result(
                file_path=file_path,
                content="",
                metadata={"error": str(e), "extraction_method": "failed"}
            )
    
    def _extract_html(self, file_path: Path) -> Dict[str, Any]:
        """Extract content from HTML file"""
        try:
            # 读取文件内容
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 解析HTML
            soup = BeautifulSoup(content, 'html.parser')
            
            # 提取文本内容
            text_content = soup.get_text(separator='\n', strip=True)
            
            # 提取表格
            tables = self._extract_html_tables(soup)
            
            # 提取图片
            images = self._extract_html_images(soup)
            
            # 创建提取结果
            result = self.create_extraction_result(
                file_path=file_path,
                content=text_content,
                tables=tables,
                images=images,
                metadata={
                    "tables": len(tables),
                    "images": len(images),
                    "word_count": len(text_content.split()),
                    "line_count": len(text_content.splitlines()),
                    "extraction_method": "html"
                }
            )
            
            # 保存结果（如果指定了保存路径）
            if self.save_path:
                self._save_extraction_result(result)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error extracting HTML file {file_path}: {e}")
            return self.create_extraction_result(
                file_path=file_path,
                content="",
                metadata={"error": str(e), "extraction_method": "failed"}
            )
    
    def _extract_word(self, file_path: Path) -> Dict[str, Any]:
        """Extract content from Word document"""
        try:
            # 这里可以添加Word文档提取逻辑
            # 可以使用python-docx库或其他工具
            
            # 暂时返回基本信息
            return self.create_extraction_result(
                file_path=file_path,
                content=f"Word document: {file_path.name}",
                tables=[],
                images=[],
                metadata={
                    "note": "Word document extraction not implemented yet",
                    "extraction_method": "word-basic"
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error extracting Word file {file_path}: {e}")
            return self.create_extraction_result(
                file_path=file_path,
                content="",
                metadata={"error": str(e), "extraction_method": "failed"}
            )
    
    def _split_text_into_blocks(self, content: str) -> List[Dict]:
        """Split text into blocks"""
        blocks = []
        paragraphs = content.split('\n\n')
        
        for i, paragraph in enumerate(paragraphs):
            paragraph = paragraph.strip()
            if paragraph and len(paragraph) > 10:  # 只保留有意义的段落
                blocks.append({
                    "block_id": f"block_{i+1}",
                    "content": paragraph,
                    "title": f"Paragraph {i+1}",
                    "word_count": len(paragraph.split()),
                    "source": self.file_path.name
                })
        
        return blocks
    
    def _extract_markdown_blocks(self, content: str) -> List[Dict]:
        """Extract text blocks from Markdown content"""
        blocks = []
        lines = content.split('\n')
        current_block = []
        current_title = None
        current_level = 1
        
        for line in lines:
            # 检查是否是标题
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
            if heading_match:
                # 保存前一个块
                if current_block:
                    blocks.append({
                        "block_id": f"md_block_{len(blocks)+1}",
                        "content": '\n'.join(current_block),
                        "title": current_title,
                        "level": current_level,
                        "source": self.file_path.name
                    })
                
                # 开始新块
                current_level = len(heading_match.group(1))
                current_title = heading_match.group(2).strip()
                current_block = []
            else:
                current_block.append(line)
        
        # 保存最后一个块
        if current_block:
            blocks.append({
                "block_id": f"md_block_{len(blocks)+1}",
                "content": '\n'.join(current_block),
                "title": current_title,
                "level": current_level,
                "source": self.file_path.name
            })
        
        return blocks
    
    def _extract_markdown_tables(self, content: str) -> List[Dict]:
        """Extract tables from Markdown content"""
        tables = []
        
        # 使用正则表达式匹配Markdown表格
        table_pattern = r'\|(.+)\|\n\|[\s\-:]+\|\n((?:\|.+\|\n?)+)'
        matches = re.finditer(table_pattern, content, re.MULTILINE)
        
        for i, match in enumerate(matches):
            try:
                # 提取表头
                header_line = match.group(1)
                headers = [h.strip() for h in header_line.split('|') if h.strip()]
                
                # 提取数据行
                data_lines = match.group(2).strip().split('\n')
                rows = []
                
                for line in data_lines:
                    if line.strip():
                        row = [cell.strip() for cell in line.split('|')[1:-1] if cell.strip()]
                        if row:
                            rows.append(row)
                
                tables.append({
                    "table_id": f"md_table_{i+1}",
                    "title": f"Markdown Table {i+1}",
                    "headers": headers,
                    "rows": rows,
                    "source": self.file_path.name
                })
            except Exception as e:
                self.logger.warning(f"Failed to parse Markdown table {i+1}: {e}")
                continue
        
        return tables
    
    def _extract_html_tables(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract tables from HTML content"""
        tables = []
        
        for i, table in enumerate(soup.find_all("table")):
            try:
                # 提取表头
                headers = []
                header_row = table.find("tr")
                if header_row:
                    for th in header_row.find_all(["th", "td"]):
                        headers.append(th.get_text(strip=True))
                
                # 提取数据行
                rows = []
                for tr in table.find_all("tr")[1:]:  # 跳过表头行
                    row = []
                    for td in tr.find_all("td"):
                        row.append(td.get_text(strip=True))
                    if row:  # 只添加非空行
                        rows.append(row)
                
                # 提取标题
                caption = table.find("caption")
                title = caption.get_text(strip=True) if caption else f"HTML Table {i+1}"
                
                tables.append({
                    "table_id": f"html_table_{i+1}",
                    "title": title,
                    "headers": headers,
                    "rows": rows,
                    "source": self.file_path.name
                })
            except Exception as e:
                self.logger.warning(f"Failed to parse HTML table {i+1}: {e}")
                continue
        
        return tables
    
    def _extract_html_images(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract images from HTML content"""
        images = []
        
        for i, img in enumerate(soup.find_all("img")):
            try:
                src = img.get("src", "")
                alt = img.get("alt", "")
                title = img.get("title", "")
                
                images.append({
                    "image_id": f"html_image_{i+1}",
                    "title": title or alt or f"Image {i+1}",
                    "src": src,
                    "alt": alt,
                    "source": self.file_path.name
                })
            except Exception as e:
                self.logger.warning(f"Failed to extract HTML image {i+1}: {e}")
                continue
        
        return images
    
    def _save_extraction_result(self, result: Dict[str, Any]) -> None:
        """Save extraction result to file"""
        if not self.save_path:
            return
            
        try:
            # Create directory if it doesn't exist
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Save as JSON
            with open(self.save_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
                
            self.logger.info(f"Extraction result saved to {self.save_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to save extraction result: {e}") 