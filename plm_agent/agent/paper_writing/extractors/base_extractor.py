from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
import logging
from datetime import datetime
import time

from ..schema.extraction_result import ExtractionResult, ExtractedTable, ExtractedImage, FileMetadata, ExtractionMetadata, ExtractionMethod


class BaseExtractor(ABC):
    """Base class for all document extractors"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @abstractmethod
    def extract(self, file_path: Path) -> Any:
        pass
    
    @abstractmethod
    def can_extract(self, file_path: Path) -> bool:
        pass
    
    def get_supported_extensions(self) -> List[str]:
        return []
    
    def validate_file(self, file_path: Path) -> bool:
        if not file_path.exists():
            self.logger.error(f"File does not exist: {file_path}")
            return False
        
        if not file_path.is_file():
            self.logger.error(f"Path is not a file: {file_path}")
            return False
        
        if file_path.stat().st_size == 0:
            self.logger.error(f"File is empty: {file_path}")
            return False
        
        return True
    
    def get_file_metadata(self, file_path: Path) -> Any:
        if not self.validate_file(file_path):
            if FileMetadata:
                return FileMetadata.from_path(file_path)
            return {}
        
        if FileMetadata:
            return FileMetadata.from_path(file_path)
        
        # Fallback to old format
        stat = file_path.stat()
        return {
            "file_name": file_path.name,
            "file_path": str(file_path),
            "file_size": stat.st_size,
            "file_extension": file_path.suffix.lower(),
            "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "created_time": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "extraction_time": datetime.now().isoformat()
        }
    
    def create_extraction_result(self, file_path: Path, content: str = "", 
                                tables: Optional[List[Any]] = None, 
                                images: Optional[List[Any]] = None,
                                metadata: Optional[Dict] = None,
                                extraction_method: Optional[Any] = None,
                                processing_duration: Optional[float] = None,
                                error_message: Optional[str] = None) -> Any:
        """
        Create a standardized extraction result
        
        Args:
            file_path: Path to the extracted file
            content: Extracted text content
            tables: List of extracted tables
            images: List of extracted images
            metadata: Additional metadata
            extraction_method: Extraction method used
            processing_duration: Processing time in seconds
            error_message: Error message if extraction failed
            
        Returns:
            ExtractionResult (if schema available) or Dictionary containing extracted content and metadata
        """
        return self._create_schema_result(
            file_path, content, tables, images, metadata, 
            extraction_method, processing_duration, error_message
        )
    
    def _create_schema_result(self, file_path: Path, content: str = "",
                             tables: Optional[List[Any]] = None,
                             images: Optional[List[Any]] = None,
                             metadata: Optional[Dict] = None,
                             extraction_method: Optional[Any] = None,
                             processing_duration: Optional[float] = None,
                             error_message: Optional[str] = None) -> Any:
        """Create result using new schema"""
        
        # Convert dict tables to ExtractedTable objects
        schema_tables = []
        if tables and ExtractedTable:
            for table in tables:
                if isinstance(table, dict):
                    schema_tables.append(ExtractedTable(**table))
                elif isinstance(table, ExtractedTable):
                    schema_tables.append(table)
        
        # Convert dict images to ExtractedImage objects
        schema_images = []
        if images and ExtractedImage:
            for image in images:
                if isinstance(image, dict):
                    schema_images.append(ExtractedImage(**image))
                elif isinstance(image, ExtractedImage):
                    schema_images.append(image)
        
        # Create file metadata
        file_metadata = self.get_file_metadata(file_path)
        if FileMetadata and not isinstance(file_metadata, FileMetadata):
            file_metadata = FileMetadata.from_path(file_path)
        
        # Create extraction metadata
        method = extraction_method
        if not method and ExtractionMethod:
            method = ExtractionMethod.FALLBACK
            
        extraction_metadata = None
        if ExtractionMetadata and method:
            extraction_metadata = ExtractionMetadata(
                extraction_method=method,
                extraction_time=datetime.now().isoformat(),
                processing_duration=processing_duration,
                error_message=error_message,
                additional_info=metadata or {}
            )
        
        if ExtractionResult and file_metadata and extraction_metadata:
            return ExtractionResult(
                file_path=str(file_path),
                file_name=file_path.name,
                file_extension=file_path.suffix.lower(),
                content=content,
                file_metadata=file_metadata,
                extraction_metadata=extraction_metadata,
                tables=schema_tables,
                images=schema_images
            )
        else:
            return {}
    
    def _create_dict_result(self, file_path: Path, content: str = "",
                           tables: Optional[List[Dict]] = None,
                           images: Optional[List[Dict]] = None,
                           metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """Create result using old dictionary format (backward compatibility)"""
        
        base_metadata = self.get_file_metadata(file_path)
        if metadata and isinstance(base_metadata, dict):
            base_metadata.update(metadata)
        
        # Map file extension to file type
        file_extension = file_path.suffix.lower()
        file_type = self._map_extension_to_type(file_extension)
        
        return {
            "file_path": str(file_path),
            "file_name": file_path.name,
            "file_extension": file_extension,
            "file_type": file_type,
            "content": content,
            "tables": tables or [],
            "images": images or [],
            "metadata": base_metadata,
            "extraction_method": self.__class__.__name__,
            "extraction_time": datetime.now().isoformat()
        }
    
    def _map_extension_to_type(self, file_extension: str) -> str:
        """Map file extension to file type"""
        extension_to_type = {
            # Document files
            '.pdf': 'pdf',
            '.docx': 'docx',
            '.doc': 'doc',
            '.pptx': 'pptx',
            '.ppt': 'ppt',
            '.txt': 'txt',
            '.rtf': 'rtf',
            '.html': 'html',
            '.htm': 'html',
            
            # Data files
            '.csv': 'csv',
            '.xlsx': 'excel',
            '.xls': 'excel',
            '.json': 'json',
            '.tsv': 'tsv',
            
            # Image files
            '.png': 'png',
            '.jpg': 'jpg',
            '.jpeg': 'jpg',
            '.gif': 'gif',
            '.bmp': 'bmp',
            '.tiff': 'tiff',
            '.svg': 'svg'
        }
        
        return extension_to_type.get(file_extension, 'unknown')
    
    def extract_with_timing(self, file_path: Path) -> Any:
        """
        Extract content with timing information
        
        Args:
            file_path: Path to the file to extract from
            
        Returns:
            Extraction result with timing information
        """
        start_time = time.time()
        
        try:
            result = self.extract(file_path)
            processing_duration = time.time() - start_time
            
            # Add timing information
            if ExtractionResult and isinstance(result, ExtractionResult):
                if hasattr(result, 'extraction_metadata') and result.extraction_metadata:
                    result.extraction_metadata.processing_duration = processing_duration
            elif isinstance(result, dict):
                if "metadata" in result:
                    result["metadata"]["processing_duration"] = processing_duration
                else:
                    result["metadata"] = {"processing_duration": processing_duration}
            
            return result
            
        except Exception as e:
            processing_duration = time.time() - start_time
            error_message = str(e)
            
            if ExtractionResult:
                return ExtractionResult.create_error_result(file_path, error_message)
            else:
                return self._create_dict_result(
                    file_path, content="", 
                    metadata={"error": error_message, "processing_duration": processing_duration}
                ) 