"""
Extraction result schemas

Defines the standardized data structures for document extraction results
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from pathlib import Path
from enum import Enum


class ExtractionMethod(Enum):
    """Supported extraction methods"""
    AZURE_DOCUMENT_INTELLIGENCE = "azure-document-intelligence"
    PANDAS_EXCEL = "pandas-excel"
    PANDAS_CSV = "pandas-csv"
    PLAIN_TEXT = "plain-text"
    MARKDOWN = "markdown"
    HTML_PARSER = "html-parser"
    WORD_DOCUMENT = "word-document"
    FALLBACK = "fallback"
    FAILED = "failed"


class TableFormat(Enum):
    """Table data formats"""
    MARKDOWN = "markdown"
    HTML = "html"
    CSV = "csv"
    JSON = "json"
    PANDAS = "pandas"


@dataclass
class ExtractedTable:
    """Extracted table data structure"""
    table_id: str
    title: str
    headers: List[str]
    rows: List[List[str]]
    source: str = ""
    extraction_method: str = ""
    format: TableFormat = TableFormat.JSON
    page_number: Optional[int] = None
    table_index: Optional[int] = None
    raw_content: Optional[str] = None
    description: Optional[str] = None
    sheet_name: Optional[str] = None  # For Excel files
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    
    def __post_init__(self):
        if self.row_count is None:
            self.row_count = len(self.rows)
        if self.column_count is None:
            self.column_count = len(self.headers) if self.headers else 0


@dataclass
class ExtractedImage:
    """Extracted image data structure"""
    image_id: str
    title: str
    source: str = ""
    extraction_method: str = ""
    image_path: Optional[str] = None
    caption: Optional[str] = None
    content: Optional[str] = None
    page_number: Optional[int] = None
    image_index: Optional[int] = None
    alt_text: Optional[str] = None
    file_size: Optional[int] = None
    dimensions: Optional[Dict[str, int]] = None


@dataclass
class FileMetadata:
    """File metadata information"""
    file_name: str
    file_path: str
    file_size: int
    file_extension: str
    modified_time: str
    created_time: str
    extraction_time: str
    
    @classmethod
    def from_path(cls, file_path: Path) -> "FileMetadata":
        """Create metadata from file path"""
        if not file_path.exists():
            # Return metadata with default values for non-existent files
            return cls(
                file_name=file_path.name,
                file_path=str(file_path),
                file_size=0,
                file_extension=file_path.suffix.lower(),
                modified_time=datetime.now().isoformat(),
                created_time=datetime.now().isoformat(),
                extraction_time=datetime.now().isoformat()
            )
        
        stat = file_path.stat()
        return cls(
            file_name=file_path.name,
            file_path=str(file_path),
            file_size=stat.st_size,
            file_extension=file_path.suffix.lower(),
            modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            created_time=datetime.fromtimestamp(stat.st_ctime).isoformat(),
            extraction_time=datetime.now().isoformat()
        )


@dataclass
class ExtractionMetadata:
    """Extraction process metadata"""
    extraction_method: ExtractionMethod
    extraction_time: str
    processing_duration: Optional[float] = None  # seconds
    error_message: Optional[str] = None
    warning_messages: List[str] = field(default_factory=list)
    additional_info: Dict[str, Any] = field(default_factory=dict)
    
    # Method-specific metadata
    azure_result_file: Optional[str] = None
    figures_count: Optional[int] = None
    tables_count: Optional[int] = None
    paragraphs_count: Optional[int] = None
    pages_count: Optional[int] = None
    sheet_count: Optional[int] = None
    sheet_names: Optional[List[str]] = None
    text_blocks: Optional[int] = None
    word_count: Optional[int] = None
    line_count: Optional[int] = None


@dataclass
class ExtractionResult:
    """Standardized extraction result"""
    # File information
    file_path: str
    file_name: str
    file_extension: str
    
    # Extracted content
    content: str
    
    # Metadata
    file_metadata: FileMetadata
    extraction_metadata: ExtractionMetadata
    
    # Additional fields for backward compatibility
    tables: List[ExtractedTable] = field(default_factory=list)
    images: List[ExtractedImage] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    extraction_method: str = ""
    extraction_time: str = ""
    
    def __post_init__(self):
        # Set backward compatibility fields
        if not self.extraction_method:
            self.extraction_method = self.extraction_metadata.extraction_method.value
        if not self.extraction_time:
            self.extraction_time = self.extraction_metadata.extraction_time
        
        # Update metadata dict for backward compatibility
        self.metadata.update({
            "file_name": self.file_metadata.file_name,
            "file_path": self.file_metadata.file_path,
            "file_size": self.file_metadata.file_size,
            "file_extension": self.file_metadata.file_extension,
            "modified_time": self.file_metadata.modified_time,
            "created_time": self.file_metadata.created_time,
            "extraction_time": self.file_metadata.extraction_time,
            "extraction_method": self.extraction_metadata.extraction_method.value,
            "processing_duration": self.extraction_metadata.processing_duration,
            "error_message": self.extraction_metadata.error_message,
            "warning_messages": self.extraction_metadata.warning_messages,
            **self.extraction_metadata.additional_info
        })
    
    @classmethod
    def create_error_result(cls, file_path: Path, error_message: str) -> "ExtractionResult":
        """Create an error result"""
        file_metadata = FileMetadata.from_path(file_path)
        extraction_metadata = ExtractionMetadata(
            extraction_method=ExtractionMethod.FAILED,
            extraction_time=datetime.now().isoformat(),
            error_message=error_message
        )
        
        return cls(
            file_path=str(file_path),
            file_name=file_path.name,
            file_extension=file_path.suffix.lower(),
            content="",
            tables=[],
            images=[],
            file_metadata=file_metadata,
            extraction_metadata=extraction_metadata
        )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractionResult":
        """Create from dictionary (for backward compatibility)"""
        # Convert tables
        tables = []
        for table_data in data.get("tables", []):
            if isinstance(table_data, dict):
                tables.append(ExtractedTable(**table_data))
        
        # Convert images
        images = []
        for image_data in data.get("images", []):
            if isinstance(image_data, dict):
                images.append(ExtractedImage(**image_data))
        
        # Create file metadata
        file_metadata = FileMetadata(
            file_name=data.get("file_name", ""),
            file_path=data.get("file_path", ""),
            file_size=data.get("metadata", {}).get("file_size", 0),
            file_extension=data.get("file_extension", ""),
            modified_time=data.get("metadata", {}).get("modified_time", ""),
            created_time=data.get("metadata", {}).get("created_time", ""),
            extraction_time=data.get("extraction_time", "")
        )
        
        # Create extraction metadata
        extraction_metadata = ExtractionMetadata(
            extraction_method=ExtractionMethod(data.get("extraction_method", "failed")),
            extraction_time=data.get("extraction_time", ""),
            additional_info=data.get("metadata", {})
        )
        
        return cls(
            file_path=data.get("file_path", ""),
            file_name=data.get("file_name", ""),
            file_extension=data.get("file_extension", ""),
            content=data.get("content", ""),
            tables=tables,
            images=images,
            file_metadata=file_metadata,
            extraction_metadata=extraction_metadata,
            metadata=data.get("metadata", {})
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (for backward compatibility)"""
        return {
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_extension": self.file_extension,
            "content": self.content,
            "tables": [table.__dict__ for table in self.tables],
            "images": [image.__dict__ for image in self.images],
            "metadata": self.metadata,
            "extraction_method": self.extraction_method,
            "extraction_time": self.extraction_time
        }
    
    @property
    def is_successful(self) -> bool:
        """Check if extraction was successful"""
        return self.extraction_metadata.extraction_method != ExtractionMethod.FAILED
    
    @property
    def has_tables(self) -> bool:
        """Check if result contains tables"""
        return len(self.tables) > 0
    
    @property
    def has_images(self) -> bool:
        """Check if result contains images"""
        return len(self.images) > 0
    
    @property
    def table_count(self) -> int:
        """Get number of tables"""
        return len(self.tables)
    
    @property
    def image_count(self) -> int:
        """Get number of images"""
        return len(self.images)
    
    def get_table_by_id(self, table_id: str) -> Optional[ExtractedTable]:
        """Get table by ID"""
        return next((table for table in self.tables if table.table_id == table_id), None)
    
    def get_image_by_id(self, image_id: str) -> Optional[ExtractedImage]:
        """Get image by ID"""
        return next((image for image in self.images if image.image_id == image_id), None) 