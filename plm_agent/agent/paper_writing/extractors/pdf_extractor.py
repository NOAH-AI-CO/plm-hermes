import logging
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

from .base_extractor import BaseExtractor


class PDFExtractor(BaseExtractor):
    """PDF file extractor using Azure Document Intelligence"""
    
    def __init__(self, file_path: Path, save_path: Optional[Path] = None, **kwargs):
        """
        Initialize PDF extractor
        
        Args:
            file_path: Path to PDF file
            save_path: Optional save path for extracted content
            **kwargs: Additional arguments
        """
        super().__init__()
        self.file_path = Path(file_path)
        self.save_path = Path(save_path) if save_path else None
        self.logger = logging.getLogger(__name__)
        self.azure_client = None
        
        # 尝试初始化Azure客户端
        try:
            from ..clients.azure_document_intelligence import AzureDocumentIntelligenceClient
            self.azure_client = AzureDocumentIntelligenceClient()
            self.logger.info("Azure Document Intelligence client initialized successfully")
        except Exception as e:
            self.logger.warning(f"Failed to initialize Azure client: {e}")
            self.azure_client = None
    
    def can_extract(self, file_path: Path) -> bool:
        """Check if this extractor can handle the given file"""
        return file_path.suffix.lower() == '.pdf'
    
    def get_supported_extensions(self) -> List[str]:
        """Get supported file extensions"""
        return ['.pdf']
    
    def extract(self, file_path: Path) -> Dict[str, Any]:
        """Extract content from PDF file using Azure Document Intelligence"""
        if not self.validate_file(file_path):
            return self.create_extraction_result(file_path, content="", 
                                               metadata={"error": "File validation failed"})
        
        try:
            if self.azure_client:
                # Use Azure Document Intelligence
                return self._extract_with_azure(file_path)
            else:
                # Fallback to basic extraction
                return self._extract_with_fallback(file_path)
                
        except Exception as e:
            self.logger.error(f"Error extracting PDF {file_path}: {e}")
            return self.create_extraction_result(
                file_path=file_path,
                content="",
                metadata={"error": str(e), "extraction_method": "failed"}
            )
    
    def _extract_with_azure(self, file_path: Path) -> Dict[str, Any]:
        """Extract content using Azure Document Intelligence"""
        if not self.azure_client:
            self.logger.error("Azure client not initialized")
            return self._extract_with_fallback(file_path)
            
        try:
            self.logger.info(f"Using Azure Document Intelligence to extract {file_path}")
            
            # Call Azure Document Intelligence
            azure_result = self.azure_client.analyze_pdf(
                pdf_path=str(file_path),
                save_path=str(self.save_path) if self.save_path else None
            )
            
            # Extract content from Azure result
            content = azure_result.get("markdown_content", "")
            tables = self._extract_tables_from_azure_result(azure_result)
            images = self._extract_images_from_azure_result(azure_result)
            
            # Create extraction result
            result = self.create_extraction_result(
                file_path=file_path,
                content=content,
                tables=tables,
                images=images,
                metadata={
                    "extraction_method": "azure-document-intelligence",
                    "azure_result_file": azure_result.get("markdown_file", ""),
                    "figures_count": len(azure_result.get("figures", [])),
                    "tables_count": len(azure_result.get("tables", [])),
                    "paragraphs_count": len(azure_result.get("paragraphs", [])),
                    "pages_count": len(azure_result.get("pages", []))
                }
            )
            
            # Save result if save_path is specified
            if self.save_path:
                self._save_extraction_result(result)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Azure extraction failed: {e}")
            # Fallback to basic extraction
            return self._extract_with_fallback(file_path)
    
    def _extract_tables_from_azure_result(self, azure_result: Dict) -> List[Dict]:
        """Extract tables from Azure result"""
        tables = []
        
        try:
            # Get tables from Azure result
            azure_tables = azure_result.get("tables", [])
            
            for i, table in enumerate(azure_tables):
                try:
                    # Extract table data from Azure table object
                    table_data = self._parse_azure_table(table, azure_result.get("content", ""))
                    
                    if table_data:
                        tables.append({
                            "table_id": f"azure_table_{i+1}",
                            "title": f"Table {i+1}",
                            "headers": table_data.get("headers", []),
                            "rows": table_data.get("rows", []),
                            "page_number": table_data.get("page_number", 1),
                            "table_index": i + 1,
                            "source": self.file_path.name,
                            "extraction_method": "azure-table"
                        })
                        
                except Exception as e:
                    self.logger.warning(f"Failed to parse Azure table {i+1}: {e}")
                    continue
                    
        except Exception as e:
            self.logger.warning(f"Failed to extract tables from Azure result: {e}")
        
        return tables
    
    def _parse_azure_table(self, table, content: str) -> Optional[Dict]:
        """Parse Azure table object into structured data"""
        try:
            # Extract table content from spans
            table_content = ""
            for span in table.spans:
                table_content += content[span.offset:span.offset + span.length]
            
            # Parse markdown table format
            lines = table_content.strip().split('\n')
            if len(lines) < 3:  # Need header, separator, and at least one data row
                return None
            
            # Extract headers (first line)
            headers = [h.strip() for h in lines[0].split('|')[1:-1] if h.strip()]
            
            # Extract data rows (skip header and separator lines)
            rows = []
            for line in lines[2:]:
                if line.strip():
                    row = [cell.strip() for cell in line.split('|')[1:-1] if cell.strip()]
                    if row:
                        rows.append(row)
            
            return {
                "headers": headers,
                "rows": rows,
                "page_number": getattr(table, 'page_number', 1) if hasattr(table, 'page_number') else 1
            }
            
        except Exception as e:
            self.logger.warning(f"Failed to parse Azure table: {e}")
            return None
    
    def _extract_images_from_azure_result(self, azure_result: Dict) -> List[Dict]:
        """Extract images from Azure result"""
        images = []
        
        try:
            # Get figures from Azure result
            figures = azure_result.get("figures", [])
            
            for i, figure in enumerate(figures):
                try:
                    images.append({
                        "image_id": figure.get("figure_id", f"image_{i+1}"),
                        "title": figure.get("caption", f"Image {i+1}"),
                        "image_path": figure.get("image_path", ""),
                        "caption": figure.get("caption", ""),
                        "content": figure.get("content", ""),
                        "page_number": 1,  # Azure doesn't provide page number for figures
                        "image_index": i + 1,
                        "source": self.file_path.name,
                        "extraction_method": "azure-figure"
                    })
                    
                except Exception as e:
                    self.logger.warning(f"Failed to extract image {i+1}: {e}")
                    continue
                    
        except Exception as e:
            self.logger.warning(f"Failed to extract images from Azure result: {e}")
        
        return images
    
    def _extract_with_fallback(self, file_path: Path) -> Dict[str, Any]:
        """Fallback extraction method using PyMuPDF when Azure is not available"""
        self.logger.warning("Azure Document Intelligence not available, using PyMuPDF fallback")
        
        try:
            # Try to import PyMuPDF
            import fitz  # PyMuPDF
            
            # Open PDF with PyMuPDF
            doc = fitz.open(str(file_path))
            content_parts = []
            tables = []
            images = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                
                # Extract text
                text = page.get_text()
                if text.strip():
                    content_parts.append(f"=== Page {page_num + 1} ===\n{text}\n")
                
                # Extract tables (basic table detection)
                tables_on_page = self._extract_tables_from_page(page, page_num + 1)
                tables.extend(tables_on_page)
                
                # Extract images
                images_on_page = self._extract_images_from_page(page, page_num + 1)
                images.extend(images_on_page)
            
            doc.close()
            
            # Create extraction result
            result = self.create_extraction_result(
                file_path=file_path,
                content="\n".join(content_parts),
                tables=tables,
                images=images,
                metadata={
                    "extraction_method": "pymupdf-fallback",
                    "pages_count": len(doc),
                    "tables_count": len(tables),
                    "images_count": len(images),
                    "note": "Azure Document Intelligence not available, used PyMuPDF"
                }
            )
            
            # Save result if save_path is specified
            if self.save_path:
                self._save_extraction_result(result)
            
            return result
            
        except ImportError:
            self.logger.error("PyMuPDF not installed. Please install with: pip install PyMuPDF")
            return self._create_basic_fallback_result(file_path)
        except Exception as e:
            self.logger.error(f"PyMuPDF extraction failed: {e}")
            return self._create_basic_fallback_result(file_path)
    
    def _extract_tables_from_page(self, page, page_num: int) -> List[Dict]:
        """Extract tables from a PDF page using PyMuPDF"""
        tables = []
        try:
            # Get table blocks from the page
            blocks = page.get_text("dict")
            
            for block in blocks.get("blocks", []):
                if block.get("type") == 1:  # Table block
                    table_data = self._parse_pymupdf_table(block, page_num)
                    if table_data:
                        tables.append(table_data)
                        
        except Exception as e:
            self.logger.warning(f"Failed to extract tables from page {page_num}: {e}")
        
        return tables
    
    def _parse_pymupdf_table(self, table_block, page_num: int) -> Optional[Dict]:
        """Parse PyMuPDF table block into structured data"""
        try:
            # Extract table content from PyMuPDF table block
            # This is a simplified implementation - PyMuPDF table extraction can be complex
            table_text = ""
            for line in table_block.get("lines", []):
                for span in line.get("spans", []):
                    table_text += span.get("text", "") + " "
                table_text += "\n"
            
            # Basic table parsing (this could be improved)
            lines = table_text.strip().split('\n')
            if len(lines) < 2:
                return None
            
            # Assume first line is headers
            headers = [h.strip() for h in lines[0].split() if h.strip()]
            rows = []
            
            for line in lines[1:]:
                if line.strip():
                    row = [cell.strip() for cell in line.split() if cell.strip()]
                    if row:
                        rows.append(row)
            
            return {
                "table_id": f"pymupdf_table_page_{page_num}",
                "title": f"Table on Page {page_num}",
                "headers": headers,
                "rows": rows,
                "page_number": page_num,
                "source": self.file_path.name,
                "extraction_method": "pymupdf-table"
            }
            
        except Exception as e:
            self.logger.warning(f"Failed to parse PyMuPDF table: {e}")
            return None
    
    def _extract_images_from_page(self, page, page_num: int) -> List[Dict]:
        """Extract images from a PDF page using PyMuPDF"""
        images = []
        try:
            # Get image list from the page
            image_list = page.get_images()
            
            for img_index, img in enumerate(image_list):
                try:
                    images.append({
                        "image_id": f"pymupdf_image_page_{page_num}_{img_index + 1}",
                        "title": f"Image {img_index + 1} on Page {page_num}",
                        "page_number": page_num,
                        "image_index": img_index + 1,
                        "source": self.file_path.name,
                        "extraction_method": "pymupdf-image"
                    })
                    
                except Exception as e:
                    self.logger.warning(f"Failed to extract image {img_index + 1} from page {page_num}: {e}")
                    continue
                    
        except Exception as e:
            self.logger.warning(f"Failed to extract images from page {page_num}: {e}")
        
        return images
    
    def _create_basic_fallback_result(self, file_path: Path) -> Dict[str, Any]:
        """Create basic fallback result when all extraction methods fail"""
        return self.create_extraction_result(
            file_path=file_path,
            content=f"PDF file: {file_path.name}\n\nExtraction failed. Please ensure PyMuPDF is installed: pip install PyMuPDF",
            tables=[],
            images=[],
            metadata={
                "extraction_method": "failed",
                "error": "No PDF extraction method available",
                "recommendation": "Install PyMuPDF: pip install PyMuPDF"
            }
        )
    
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