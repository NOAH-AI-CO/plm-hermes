"""
RAG 助手客户端

基于检索增强生成的文档分析助手
"""

import os
import json
import time
from typing import List, Optional, Union, Dict, Any
from openai import AzureOpenAI
from pathlib import Path
from dataclasses import dataclass

from config import api_config



@dataclass
class UploadedFile:
    """Information about an uploaded file"""
    file_id: str
    file_path: Path
    file_name: str
    file_size: int
    upload_time: str
    original_file_type: Optional[str] = None  # 记录原始文件类型（如.csv, .xlsx等）


class RAGAssistantClient:
    """基于 RAG 的文档分析助手客户端"""
    
    def __init__(self,
                 name: str = "Document Analysis Assistant",
                 description: str = "",
                 model: str = "gpt-4o-noah",
                 azure_endpoint: str = None,
                 api_key: str = None,
                 api_version: str = "2024-08-01-preview"):
        
        self.model = model
        self.api_version = api_version
        
        self.client = AzureOpenAI(
            azure_endpoint=azure_endpoint or api_config.AZURE_GPT4_AZURE_ENDPOINT,
            api_key=api_key or api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=self.api_version
        )
        
        # 创建助手
        self.assistant = self._create_assistant(name, description)
        self.thread = self.client.beta.threads.create()
        
        # 存储上传的文件ID和文件信息
        self.uploaded_file_ids = []
        self.uploaded_files: Dict[str, UploadedFile] = {}
        
    def _create_assistant(self, name: str, description: str):
        """创建分析助手"""
        instructions = description or """
        You are a professional academic document analysis and file classification assistant. Your tasks include:

        1. FILE CLASSIFICATION:
           - Analyze uploaded files and classify them into categories (DATA_FILE, DOCUMENT_FILE, IMAGE_FILE)
           - Determine file format (csv, excel, pdf, docx, etc.)
           - Identify content type for document files (protocol, case_report, literature_review, etc.)
           - Provide confidence scores for classifications

        2. DOCUMENT ANALYSIS:
           - Study Type (e.g., Randomized Controlled Trial, Cohort Study, Case-Control Study, etc.)
           - Publication Type (e.g., Original Research, Review, Case Report, etc.)
           - Writing Purpose (e.g., Original Research, Literature Review, etc.)
           - Research Field (e.g., Clinical Medicine, Basic Science, etc.)

        You have access to file_search tools to examine file contents. Use these tools to analyze file structure, content, and format.

        For file classification tasks, always respond with a valid JSON object in the specified format:
        {
            "category": "DATA_FILE|DOCUMENT_FILE|IMAGE_FILE",
            "file_format": "csv|excel|json|tsv|txt_tabular|pdf|docx|pptx|txt|rtf|html|png|jpg|jpeg|tiff|bmp|svg",
            "content_type": "protocol|case_report|literature_review|original_research|meta_analysis|editorial|manuscript|unknown",
            "confidence": 0.95
        }

        For document analysis tasks, provide detailed analysis results including confidence scores, supporting evidence, and improvement suggestions in structured JSON format.
        """
        
        return self.client.beta.assistants.create(
            model=self.model,
            instructions=instructions,
            name=name,
            tools=[{"type": "file_search"}]
        )
    
    def upload_file(self, file_path: Path) -> str:
        """直接上传文件到助手，支持 backup 转换"""
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 检查文件类型，根据实际运行时的支持情况
        natively_supported_extensions = {'.c', '.cpp', '.cs', '.css', '.doc', '.docx', '.go', '.html', 
                                       '.java', '.js', '.json', '.md', '.pdf', '.php', '.pptx', '.py', 
                                       '.rb', '.sh', '.tex', '.ts', '.txt'}
        
        file_extension = file_path.suffix.lower()
        original_file_type = file_extension  # 记录原始文件类型
        
        # 如果文件类型不在原生支持列表中，先尝试转换
        if file_extension not in natively_supported_extensions:
            print(f"检测到不支持的文件类型 {file_extension}，尝试转换: {file_path.name}")
            converted_path = self._convert_unsupported_file(file_path)
            if converted_path:
                file_path = converted_path
                print(f"转换成功: {file_path.name}")
            else:
                print(f"无法转换文件类型 {file_extension}，跳过文件 {file_path.name}")
                return None
        
        # 上传文件（原生支持或转换后的文件）
        try:
            with open(file_path, "rb") as f:
                uploaded = self.client.files.create(file=f, purpose="assistants")
                self.uploaded_file_ids.append(uploaded.id)
                
                # 创建上传文件记录
                uploaded_file = UploadedFile(
                    file_id=uploaded.id,
                    file_path=file_path,
                    file_name=file_path.name,
                    file_size=file_path.stat().st_size if file_path.exists() else 0,
                    upload_time="now",  # Could use actual timestamp
                    original_file_type=original_file_type  # 记录原始文件类型
                )
                self.uploaded_files[uploaded.id] = uploaded_file
                
                print(f"上传文件: {uploaded.id} - {file_path.name}")
                return uploaded.id
        except Exception as e:
            print(f"上传文件失败 {file_path.name}: {e}")
            return None
    
    def upload_files(self, file_paths: List[Path]) -> List[str]:
        """
        Upload multiple files and return their IDs
        
        Args:
            file_paths: List of file paths to upload
            
        Returns:
            List of file IDs
        """
        file_ids = []
        
        for file_path in file_paths:
            try:
                file_id = self.upload_file(file_path)
                if file_id:
                    file_ids.append(file_id)
                else:
                    print(f"Failed to upload: {file_path.name}")
                    
            except Exception as e:
                print(f"Error uploading {file_path}: {e}")
        
        return file_ids
    
    def get_file_by_id(self, file_id: str) -> Optional[UploadedFile]:
        """Get uploaded file information by ID"""
        return self.uploaded_files.get(file_id)
    
    def get_uploaded_files(self) -> List[UploadedFile]:
        """Get all uploaded files"""
        return list(self.uploaded_files.values())
    
    def get_file_ids(self) -> List[str]:
        """Get all file IDs"""
        return list(self.uploaded_files.keys())
    
    def clear_uploads(self):
        """Clear all uploaded files"""
        self.uploaded_files.clear()
        self.uploaded_file_ids.clear()
        print("Cleared all uploaded files")
    
    def _convert_unsupported_file(self, file_path: Path) -> Optional[Path]:
        """转换不支持的文件类型为支持的格式（backup 机制）"""
        try:
            import pandas as pd
            
            file_extension = file_path.suffix.lower()
            
            if file_extension in {'.xlsx', '.xls'}:
                # 转换 Excel 文件为 TXT 格式
                df = pd.read_excel(file_path)
                txt_path = file_path.with_suffix('.txt')
                
                # 将 DataFrame 转换为可读的文本格式
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(f"Excel File: {file_path.name}\n")
                    f.write("=" * 50 + "\n\n")
                    
                    # 写入列名
                    f.write("Columns:\n")
                    f.write(", ".join(df.columns.tolist()) + "\n\n")
                    
                    # 写入数据摘要
                    f.write("Data Summary:\n")
                    f.write(f"Total rows: {len(df)}\n")
                    f.write(f"Total columns: {len(df.columns)}\n\n")
                    
                    # 写入前几行数据，跳过NaN值
                    f.write("First 10 rows of data:\n")
                    f.write("-" * 30 + "\n")
                    for i, row in df.head(10).iterrows():
                        # 过滤掉NaN值
                        clean_row = {k: v for k, v in dict(row).items() if pd.notna(v)}
                        if clean_row:  # 只有当行有非NaN值时才写入
                            f.write(f"Row {i+1}: {clean_row}\n")
                    
                    # 写入数据类型信息
                    f.write("\nData Types:\n")
                    f.write("-" * 30 + "\n")
                    for col, dtype in df.dtypes.items():
                        f.write(f"{col}: {dtype}\n")
                    
                    # 添加文件类型识别信息
                    f.write("\nFile Classification Information:\n")
                    f.write("-" * 30 + "\n")
                    f.write("This is an Excel data file containing structured data.\n")
                    f.write("Category: DATA_FILE\n")
                    f.write("Format: Excel spreadsheet\n")
                    f.write("Content: Tabular data with multiple columns and rows\n")
                    
                    # 如果有实际数据，添加更多描述
                    non_empty_rows = df.dropna(how='all').shape[0]
                    if non_empty_rows > 0:
                        f.write(f"Contains {non_empty_rows} rows with actual data\n")
                        # 尝试识别数据类型
                        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
                        text_cols = df.select_dtypes(include=['object']).columns.tolist()
                        if numeric_cols:
                            f.write(f"Numeric columns: {', '.join(numeric_cols)}\n")
                        if text_cols:
                            f.write(f"Text columns: {', '.join(text_cols)}\n")
                
                return txt_path
                
            elif file_extension == '.csv':
                # 转换 CSV 文件为 TXT 格式
                try:
                    df = pd.read_csv(file_path)
                except UnicodeDecodeError:
                    # 尝试不同编码
                    for encoding in ['utf-8', 'latin-1', 'cp1252']:
                        try:
                            df = pd.read_csv(file_path, encoding=encoding)
                            break
                        except:
                            continue
                    else:
                        print(f"无法读取 CSV 文件 {file_path}，编码问题")
                        return None
                
                txt_path = file_path.with_suffix('.txt')
                
                # 将 DataFrame 转换为可读的文本格式
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(f"CSV File: {file_path.name}\n")
                    f.write("=" * 50 + "\n\n")
                    
                    # 写入列名
                    f.write("Columns:\n")
                    f.write(", ".join(df.columns.tolist()) + "\n\n")
                    
                    # 写入数据摘要
                    f.write("Data Summary:\n")
                    f.write(f"Total rows: {len(df)}\n")
                    f.write(f"Total columns: {len(df.columns)}\n\n")
                    
                    # 写入前几行数据，跳过NaN值
                    f.write("First 10 rows of data:\n")
                    f.write("-" * 30 + "\n")
                    for i, row in df.head(10).iterrows():
                        # 过滤掉NaN值
                        clean_row = {k: v for k, v in dict(row).items() if pd.notna(v)}
                        if clean_row:  # 只有当行有非NaN值时才写入
                            f.write(f"Row {i+1}: {clean_row}\n")
                    
                    # 写入数据类型信息
                    f.write("\nData Types:\n")
                    f.write("-" * 30 + "\n")
                    for col, dtype in df.dtypes.items():
                        f.write(f"{col}: {dtype}\n")
                    
                    # 添加文件类型识别信息
                    f.write("\nFile Classification Information:\n")
                    f.write("-" * 30 + "\n")
                    f.write("This is a CSV data file containing structured data.\n")
                    f.write("Category: DATA_FILE\n")
                    f.write("Format: CSV (Comma-Separated Values)\n")
                    f.write("Content: Tabular data with multiple columns and rows\n")
                    
                    # 如果有实际数据，添加更多描述
                    non_empty_rows = df.dropna(how='all').shape[0]
                    if non_empty_rows > 0:
                        f.write(f"Contains {non_empty_rows} rows with actual data\n")
                        # 尝试识别数据类型
                        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
                        text_cols = df.select_dtypes(include=['object']).columns.tolist()
                        if numeric_cols:
                            f.write(f"Numeric columns: {', '.join(numeric_cols)}\n")
                        if text_cols:
                            f.write(f"Text columns: {', '.join(text_cols)}\n")
                
                return txt_path
                    
            else:
                return None
                
        except ImportError:
            print("警告: pandas 未安装，无法转换 Excel/CSV 文件")
            return None
        except Exception as e:
            print(f"转换文件失败 {file_path}: {e}")
            return None
    
    async def send_message_with_files(self, prompt: str, file_ids: Optional[List[str]] = None, kwargs: Optional[dict] = None) -> Union[str, dict]:
        """发送消息并获取响应"""
        # 构建 attachments
        attachments = [
            {"file_id": fid, "tools": [{"type": "file_search"}]}
            for fid in file_ids
        ] if file_ids else None
        
        # 发送消息
        message = self.client.beta.threads.messages.create(
            thread_id=self.thread.id,
            role="user",
            content=prompt,
            attachments=attachments
        )
        
        # 运行助手
        run = self.client.beta.threads.runs.create(
            thread_id=self.thread.id,
            assistant_id=self.assistant.id,
            **(kwargs or {})
        )
        
        # 等待完成
        while True:
            run_status = self.client.beta.threads.runs.retrieve(
                thread_id=self.thread.id,
                run_id=run.id
            )
            if run_status.status == "completed":
                break
            elif run_status.status == "failed":
                raise Exception(f"Run failed: {run_status.last_error}")
            time.sleep(2)
        
        return self._get_response_text()
    
    def _get_response_text(self) -> Union[str, dict]:
        """获取响应文本"""
        messages = self.client.beta.threads.messages.list(
            thread_id=self.thread.id
        )
        
        # 获取最新的助手回复
        message = messages.data[0]
        content_block = message.content[0].text
        text = content_block.value
        annotations = content_block.annotations
        
        # 处理引用
        citations = []
        for index, annotation in enumerate(annotations):
            text = text.replace(annotation.text, f'[{index + 1}]')
            
            if hasattr(annotation, 'file_citation') and annotation.file_citation:
                file_id = annotation.file_citation.file_id
                cited_file = self.client.files.retrieve(file_id)
                citations.append(f'[{index + 1}] Citation from file: {cited_file.filename}')
            
            elif hasattr(annotation, 'file_path') and annotation.file_path:
                file_id = annotation.file_path.file_id
                cited_file = self.client.files.retrieve(file_id)
                citations.append(f'[{index + 1}] File used: {cited_file.filename}')
        
        final_text = text + '\n\n' + '\n'.join(citations)
        
        # 尝试解析为 JSON
        try:
            return json.loads(final_text)
        except json.JSONDecodeError:
            return final_text
    
    def _extract_json_from_text(self, text: str) -> Dict[str, Any]:
        """从文本中提取 JSON"""
        try:
            # 尝试直接解析
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试找到 JSON 部分
            start = text.find('{')
            end = text.rfind('}') + 1
            if start != -1 and end != 0:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            
            # 返回解析失败的结果
            return {"error": "Failed to parse JSON", "raw_text": text}
    
    def cleanup_files(self):
        """清理上传的文件"""
        for file_id in self.uploaded_file_ids:
            try:
                self.client.files.delete(file_id)
                print(f"删除文件: {file_id}")
            except Exception as e:
                print(f"删除文件失败 {file_id}: {e}")
        
        self.uploaded_file_ids = [] 