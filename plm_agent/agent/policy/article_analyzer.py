"""文章分析器模块"""

import json
import logging
from typing import Dict, Any

from llm.composite_models import LowEffortSlotFillingModels
from utils.core.get_json_schema import get_openai_json_schema_v3
from utils.human_in_loop.helpers import function_call_with_retry
from .schema import ArticleAnalysisSchema
import asyncio
import asyncpg
import os
from config import settings

logger = logging.getLogger(__name__)


class ArticleAnalyzer:
    """文章分析器
    
    用于分析文章内容，提取标题、描述和目录信息
    """
    
    def __init__(self):
        """初始化文章分析器"""
        self.llm = LowEffortSlotFillingModels()
        self.schema = get_openai_json_schema_v3(ArticleAnalysisSchema)
        self.tool_choice = {"type": "function", "function": {"name": self.schema[0]['function']['name']}}
    
    def _to_range_list(self, table_of_contents_str: str) -> Dict[str, str]:
        """补充缺失的页码
        
        Args:
            table_of_contents_str: 大模型返回的目录JSON字符串，格式如{"1":"凡例","8":"西药部分","68":"中成药部分"}
            
        Returns:
            JSON {"1":"凡例","8":"西药部分","68":"中成药部分"}
        """
        try:
            if type(table_of_contents_str) == str:
                table_of_contents = json.loads(table_of_contents_str)
            else:
                table_of_contents = table_of_contents_str
            
            page_items = [(int(page), title) for page, title in table_of_contents.items()]
            page_items.sort(key=lambda x: x[0])
            ending_pages = [page for page, _ in page_items[1:]] + [None]
            page_items = [(start, end, title) for (start, title), end in zip(page_items, ending_pages)]
            return page_items

        except json.JSONDecodeError:
            logger.warning(f"无法解析目录JSON: {table_of_contents_str}")
            raise ValueError("目录JSON格式错误")
        except Exception as e:
            logger.warning(f"处理目录时出错: {str(e)}")
            raise ValueError("处理目录时出错")

    async def analyze_article(self, content: str) -> Dict[str, Any]:
        """分析文章内容
        
        Args:
            content: 文章内容字符串
            
        Returns:
            包含标题、描述和目录的字典
        """
        if not content or not isinstance(content, str) or not content.strip():
            raise ValueError("content参数是必需的，且必须是非空字符串")
        
        user_prompt = f"""你是一个专业的文章分析助手。请分析提供的文章内容，提取文章的标题、简短描述和目录信息。

分析要求：
1. 标题：提取文档的标题，如果没有明确标题，根据内容推断一个合适的标题
2. 描述：用简洁的语言判断文档的主要内容，不超过100字
3. 目录：识别文章中的章节标题和对应的起始页码，构建目录字典
   - 当前仅当文档目录存在时提取目录，否则返回空字典
   - 提取章节名称（如"凡例"、"西药部分"）和对应的页码数字
   - 目录字典的key应该是页码数字（字符串格式），value是章节标题
   - 例如：{{"1":"凡例","8":"西药部分","68":"中成药部分","104":"协议期内谈判药品部分","151":"中药饮片部分"}}
4. 保持客观准确，不添加原文中没有的信息

请按照提供的schema格式返回结果。

请分析以下文章内容：

{content}"""
        for _ in range(2):
            try:
                result = await function_call_with_retry(
                    self.llm,
                    user_prompt=user_prompt,
                    tools=self.schema,
                    tool_choice=self.tool_choice,
                    temperature=0.3
                )
                
                # 补充缺失的页码
                if isinstance(result.get('table_of_contents'), str):
                    result['table_of_contents'] = self._to_range_list(result['table_of_contents'])
                
                return result
                
            except Exception as e:
                logger.error(f"文章分析失败: {str(e)}")
                # raise Exception(f"文章分析服务异常: {str(e)}")
        else:
            raise Exception("文章分析服务多次尝试均失败")

if __name__ == "__main__":
    async def main():
        # Database connection
        conn = await asyncpg.connect(
            dsn=settings.SQL_POLICYRAG_URI
        )
        
        try:
            # Initialize analyzer
            analyzer = ArticleAnalyzer()
            
            # Read content from database
            rows = await conn.fetch("SELECT id, content, meta FROM lightrag_doc_full WHERE meta is NULL AND content IS NOT NULL AND doc_name NOT LIKE '%.json'")

            for row in rows:
                doc_id = row['id']
                content = row['content'][:5000]
                result = row.get('meta', {})
                if result and isinstance(result, str):
                    try: result = json.loads(result)
                    except: result = {}
                if type(content) == list:
                    content = ("\n".join(content))
                    length = len(content)
                    if length > 10000:
                        content = content[:5000]
                    else:
                        continue
                if content and content.strip():
                    try:
                        if not result:
                        # Analyze article
                            result = await analyzer.analyze_article(content)
                            
                            # Store result in meta column
                            await conn.execute(
                                "UPDATE lightrag_doc_full SET meta = $1 WHERE id = $2",
                                json.dumps(result, ensure_ascii=False), doc_id
                            )
                        
                        table_of_contents = result.get('table_of_contents', [])
                        # Update related chunks with the analysis result
                        if len(table_of_contents) >= 2:
                            chunk_rows = await conn.fetch("SELECT id, full_doc_id, content, page_no FROM lightrag_doc_chunks WHERE full_doc_id = $1 AND contextualized = FALSE ", doc_id)
                            # chunk_rows = await conn.fetch("SELECT id, full_doc_id, content, page_no FROM lightrag_doc_chunks WHERE full_doc_id = $1", doc_id)
                            for chunk_row in chunk_rows:
                                chunk_id = chunk_row['id']
                                chunk_content = chunk_row['content']
                                chunk_page_no = chunk_row.get('page_no', [])
                                if chunk_page_no and isinstance(chunk_page_no, str):
                                    try: chunk_page_no = json.loads(chunk_page_no)
                                    except: chunk_page_no = []
                                chunk_start = chunk_page_no[0] if chunk_page_no else None
                                chunk_end = chunk_page_no[-1] if chunk_page_no else None
                                sections = []
                                if chunk_start:
                                    for section_start, section_end, section_title in table_of_contents:
                                        if section_end:
                                            if chunk_start >= section_start and chunk_end <= section_end:
                                                sections.append(section_title)
                                        else:
                                            if chunk_start >= section_start:
                                                sections.append(section_title)
                                # Prepend analysis result to chunk content
                                if sections:
                                    # analysis_text = f"此切片文档标题为《{section_title}》，内容属于小节: {json.dumps(sections, ensure_ascii=False)}\n"
                                    analysis_text = f"此切片内容属于小节: {json.dumps(sections, ensure_ascii=False)}\n"
                                    updated_content = analysis_text + (chunk_content or "")
                                    
                                    await conn.execute(
                                        "UPDATE lightrag_doc_chunks SET content = $1, orig_content = $3, contextualized = TRUE WHERE id = $2",
                                        updated_content, chunk_id, chunk_content
                                    )
                        
                        print(f"Processed document {doc_id}")
                        
                    except Exception as e:
                        print(f"Error processing document {doc_id}: {e}")
                        
        finally:
            await conn.close()

    asyncio.run(main())