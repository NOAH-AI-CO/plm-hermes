import re
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging
import json

from .base_extractor import BaseExtractor


class TableExtractor(BaseExtractor):
    """Table file extractor for Excel and CSV files"""
    
    def __init__(self, file_path: Path, save_path: Optional[Path] = None, **kwargs):
        """
        Initialize table extractor
        
        Args:
            file_path: Path to table file
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
        return suffix in ['.xlsx', '.xls', '.csv']
    
    def get_supported_extensions(self) -> List[str]:
        """Get supported file extensions"""
        return ['.xlsx', '.xls', '.csv']
    
    def extract(self, file_path: Path) -> Dict[str, Any]:
        """
        Extract content from table file
        
        Args:
            file_path: Path to table file
            
        Returns:
            Dictionary containing extracted content and metadata
        """
        if not self.validate_file(file_path):
            return self.create_extraction_result(file_path, content="", 
                                               metadata={"error": "File validation failed"})
        
        try:
            suffix = file_path.suffix.lower()
            
            if suffix in ['.xlsx', '.xls']:
                return self._extract_excel(file_path)
            elif suffix == '.csv':
                return self._extract_csv(file_path)
            else:
                return self.create_extraction_result(file_path, content="", 
                                                   metadata={"error": f"Unsupported file type: {suffix}"})
                
        except Exception as e:
            self.logger.error(f"Error extracting table file {file_path}: {e}")
            return self.create_extraction_result(
                file_path=file_path,
                content="",
                metadata={"error": str(e), "extraction_method": "failed"}
            )
    
    def _extract_excel(self, file_path: Path) -> Dict[str, Any]:
        """Extract content from Excel file"""
        try:
            # 读取所有工作表
            excel_file = pd.ExcelFile(file_path)
            all_tables = []
            all_content = []
            
            for sheet_name in excel_file.sheet_names:
                try:
                    # 读取工作表
                    df = pd.read_excel(file_path, sheet_name=sheet_name)
                    
                    if df.empty:
                        continue
                    
                    # 清理数据
                    df = df.dropna(how='all').dropna(axis=1, how='all')
                    
                    if df.empty:
                        continue
                    
                    # 转换为表格格式
                    table_data = {
                        "table_id": f"excel_{sheet_name}",
                        "title": f"Sheet: {sheet_name}",
                        "headers": df.columns.tolist(),
                        "rows": df.values.tolist(),
                        "sheet_name": sheet_name,
                        "row_count": len(df),
                        "column_count": len(df.columns),
                        "source": file_path.name
                    }
                    all_tables.append(table_data)
                    
                    # 添加到文本内容
                    all_content.append(f"=== Sheet: {sheet_name} ===")
                    all_content.append(f"Headers: {', '.join(df.columns.astype(str))}")
                    all_content.append(f"Rows: {len(df)}, Columns: {len(df.columns)}")
                    
                    # 添加前几行数据作为示例
                    for idx, row in df.head(5).iterrows():
                        row_str = ", ".join(str(val) for val in row.values)
                        all_content.append(f"Row {idx+1}: {row_str}")
                    
                    if len(df) > 5:
                        all_content.append(f"... and {len(df) - 5} more rows")
                    all_content.append("")
                    
                except Exception as e:
                    self.logger.warning(f"Failed to extract sheet {sheet_name}: {e}")
                    continue
            
            # 创建提取结果
            result = self.create_extraction_result(
                file_path=file_path,
                content="\n".join(all_content),
                tables=all_tables,
                metadata={
                    "sheet_count": len(excel_file.sheet_names),
                    "sheet_names": excel_file.sheet_names,
                    "extraction_method": "pandas-excel"
                }
            )
            
            # 保存结果（如果指定了保存路径）
            if self.save_path:
                self._save_extraction_result(result)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error extracting Excel file {file_path}: {e}")
            return self.create_extraction_result(
                file_path=file_path,
                content="",
                metadata={"error": str(e), "extraction_method": "failed"}
            )
    
    def _extract_csv(self, file_path: Path) -> Dict[str, Any]:
        """Extract content from CSV file"""
        try:
            # 尝试不同的编码
            encodings = ['utf-8', 'latin-1', 'cp1252', 'utf-8-sig']
            df = None
            
            for encoding in encodings:
                try:
                    df = pd.read_csv(file_path, encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
            
            if df is None:
                return self.create_extraction_result(
                    file_path=file_path,
                    content="",
                    metadata={"error": "Failed to read CSV file with any encoding"}
                )
            
            # 清理数据
            df = df.dropna(how='all').dropna(axis=1, how='all')
            
            if df.empty:
                return self.create_extraction_result(
                    file_path=file_path,
                    content="CSV file is empty or contains no valid data",
                    tables=[],
                    metadata={"extraction_method": "pandas-csv", "note": "empty_file"}
                )
            
            # 转换为表格格式
            table_data = {
                "table_id": f"csv_{file_path.stem}",
                "title": f"CSV: {file_path.name}",
                "headers": df.columns.tolist(),
                "rows": df.values.tolist(),
                "row_count": len(df),
                "column_count": len(df.columns),
                "source": file_path.name
            }
            
            # 创建文本内容
            content_parts = [
                f"=== CSV File: {file_path.name} ===",
                f"Headers: {', '.join(df.columns.astype(str))}",
                f"Rows: {len(df)}, Columns: {len(df.columns)}",
                ""
            ]
            
            # 添加前几行数据作为示例
            for idx, row in df.head(10).iterrows():
                row_str = ", ".join(str(val) for val in row.values)
                content_parts.append(f"Row {idx+1}: {row_str}")
            
            if len(df) > 10:
                content_parts.append(f"... and {len(df) - 10} more rows")
            
            # 创建提取结果
            result = self.create_extraction_result(
                file_path=file_path,
                content="\n".join(content_parts),
                tables=[table_data],
                metadata={
                    "extraction_method": "pandas-csv",
                    "data_types": df.dtypes.to_dict()
                }
            )
            
            # 保存结果（如果指定了保存路径）
            if self.save_path:
                self._save_extraction_result(result)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error extracting CSV file {file_path}: {e}")
            return self.create_extraction_result(
                file_path=file_path,
                content="",
                metadata={"error": str(e), "extraction_method": "failed"}
            )
    
    def _save_extraction_result(self, result: Dict[str, Any]) -> None:
        """Save extraction result to file"""
        if not self.save_path:
            return
        
        try:
            self.save_path.mkdir(parents=True, exist_ok=True)
            
            # 保存JSON结果
            json_path = self.save_path / f"{self.file_path.stem}_extraction.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            # 保存纯文本内容
            if result.get('content'):
                txt_path = self.save_path / f"{self.file_path.stem}_content.txt"
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(result['content'])
            
            self.logger.info(f"Extraction result saved to {self.save_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to save extraction result: {e}")
    
    def get_dataframe(self, file_path: Path) -> Optional[pd.DataFrame]:
        """Get pandas DataFrame from table file"""
        try:
            suffix = file_path.suffix.lower()
            
            if suffix in ['.xlsx', '.xls']:
                # For Excel files, return the first sheet
                return pd.read_excel(file_path, sheet_name=0)
            elif suffix == '.csv':
                # Try different encodings for CSV
                encodings = ['utf-8', 'latin-1', 'cp1252', 'utf-8-sig']
                for encoding in encodings:
                    try:
                        return pd.read_csv(file_path, encoding=encoding)
                    except UnicodeDecodeError:
                        continue
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to get DataFrame from {file_path}: {e}")
            return None 