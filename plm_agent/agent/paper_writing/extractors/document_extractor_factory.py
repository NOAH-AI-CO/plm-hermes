"""
Document Extractor Factory

Factory for creating document extractors based on file type
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional, Type

from .base_extractor import BaseExtractor
from .pdf_extractor import PDFExtractor
from .table_extractor import TableExtractor
from .text_extractor import TextExtractor


class DocumentExtractorFactory:
    """Factory for creating document extractors"""
    
    def __init__(self):
        """Initialize the factory"""
        self.logger = logging.getLogger(__name__)
        
        # Register extractors
        self._extractors: Dict[str, Type[BaseExtractor]] = {
            '.pdf': PDFExtractor,
            '.xlsx': TableExtractor,
            '.xls': TableExtractor,
            '.csv': TableExtractor,
            '.txt': TextExtractor,
            '.md': TextExtractor,
            '.html': TextExtractor,
            '.htm': TextExtractor,
            '.docx': TextExtractor,
            '.doc': TextExtractor,
        }
    
    def get_extractor(self, file_path: Path, save_path: Optional[Path] = None, **kwargs) -> Optional[BaseExtractor]:
        """Get appropriate extractor for the given file"""
        file_extension = file_path.suffix.lower()
        
        if file_extension not in self._extractors:
            self.logger.warning(f"No extractor found for file type: {file_extension}")
            return None
        
        extractor_class = self._extractors[file_extension]
        
        try:
            # Create extractor instance - concrete extractors accept file_path and save_path
            return extractor_class(file_path=file_path, save_path=save_path, **kwargs)  # type: ignore
                
        except Exception as e:
            self.logger.error(f"Failed to create extractor for {file_path}: {e}")
            return None
    
    def can_extract(self, file_path: Path) -> bool:
        """Check if the factory can extract the given file"""
        file_extension = file_path.suffix.lower()
        return file_extension in self._extractors
    
    def get_supported_extensions(self) -> list[str]:
        """Get list of supported file extensions"""
        return list(self._extractors.keys())
    
    def register_extractor(self, extension: str, extractor_class: Type) -> None:
        """Register a new extractor for a file extension"""
        if not issubclass(extractor_class, BaseExtractor):
            raise ValueError(f"Extractor class must inherit from BaseExtractor")
        
        self._extractors[extension.lower()] = extractor_class
        self.logger.info(f"Registered extractor {extractor_class.__name__} for extension {extension}")
    
    def extract_file(self, file_path: Path, save_path: Optional[Path] = None, **kwargs) -> Optional[Dict[str, Any]]:
        """Extract content from a file using the appropriate extractor"""
        extractor = self.get_extractor(file_path, save_path, **kwargs)
        
        if not extractor:
            return None
        
        try:
            return extractor.extract(file_path)
        except Exception as e:
            self.logger.error(f"Extraction failed for {file_path}: {e}")
            return None 