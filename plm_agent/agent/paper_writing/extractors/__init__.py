"""
Extractors module

This module provides a unified interface for extracting content from various file types.
All extractors inherit from BaseExtractor and provide consistent extraction results.
"""

from .base_extractor import BaseExtractor
from .document_extractor_factory import DocumentExtractorFactory
from .pdf_extractor import PDFExtractor
from .table_extractor import TableExtractor
from .text_extractor import TextExtractor

__all__ = [
    'BaseExtractor',
    'DocumentExtractorFactory', 
    'PDFExtractor',
    'TableExtractor',
    'TextExtractor'
]

# Version info
__version__ = "1.0.0" 