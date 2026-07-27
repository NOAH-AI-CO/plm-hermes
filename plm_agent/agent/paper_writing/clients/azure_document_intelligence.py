import os
import pickle
import json
import logging
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path

from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeOutputOption, ContentFormat


from config import api_config

# 常量定义
BORDER_SYMBOL = "|"


class AzureDocumentIntelligenceClient:
    def __init__(self, save_result: bool = True, extract_figures: bool = True, merge_tables: bool = True):
        self.save_result = save_result
        self.extract_figures = extract_figures
        self.merge_tables = merge_tables
        
        self._init_client()
    
    def _init_client(self):
        try:
            endpoint = api_config.AZURE_DOCUMENT_INTELLIGENC_ENDPOINT
            key = api_config.AZURE_DOCUMENT_INTELLIGENC_KEY
            
            self.client = DocumentIntelligenceClient(
                endpoint=endpoint, 
                credential=AzureKeyCredential(key)
            )
            logging.info("Azure Document Intelligence 客户端初始化成功")
            
        except ImportError as e:
            logging.error(f"Azure Document Intelligence 包未安装: {e}")
            logging.error("请运行: pip install azure-ai-documentintelligence")
            raise ImportError("请安装 azure-ai-documentintelligence 包: pip install azure-ai-documentintelligence")
        except Exception as e:
            logging.error(f"初始化 Azure 客户端失败: {e}")
            raise
    
    def analyze_pdf(self, pdf_path: str, save_path: Optional[str] = None) -> Dict[str, Any]:
        """
        使用 Azure Document Intelligence 分析 PDF
        
        Args:
            pdf_path: PDF 文件路径
            save_path: 保存路径，如果为 None 则使用默认路径
            
        Returns:
            分析结果字典
        """
        if save_path is None:
            save_path = str(Path("./tmp/azure_results") / Path(pdf_path).stem)
        
        save_path_obj = Path(save_path)
        save_path_obj.mkdir(parents=True, exist_ok=True)
        
        try:
            # 调用 Azure API
            result = self._call_azure_api(pdf_path, save_path_obj)
            
            # 处理结果
            processed_result = self._process_azure_result(result, save_path_obj)
            
            return processed_result
            
        except Exception as e:
            logging.error(f"Azure Document Intelligence 分析失败: {e}")
            raise
    
    def _call_azure_api(self, pdf_path: str, save_path: Path) -> Any:
        """调用 Azure API"""
        with open(pdf_path, "rb") as f:
            poller = self.client.begin_analyze_document(
                "prebuilt-layout",
                analyze_request=f,
                output=[AnalyzeOutputOption.FIGURES],
                content_type="application/pdf",
                output_content_format=ContentFormat.MARKDOWN
            )
        
        result = poller.result()
        
        # 保存原始结果
        if self.save_result:
            result_file = save_path / f"{Path(pdf_path).stem}_azure.pkl"
            with open(result_file, "wb") as f:
                pickle.dump(result, f)
        
        return result
    
    def _process_azure_result(self, result: Any, save_path: Path) -> Dict[str, Any]:
        """处理 Azure 分析结果"""
        md_content = result.content
        
        # 提取图片
        figures_data = []
        if self.extract_figures and hasattr(result, 'figures') and result.figures:
            figures_data = self._extract_figures(result, save_path)
        
        # 合并表格
        if self.merge_tables and hasattr(result, 'tables') and result.tables:
            md_content = self._merge_cross_page_tables(result)
        
        # 保存 Markdown
        md_file = save_path / f"{Path(save_path).name}.md"
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(md_content)
        
        return {
            "markdown_content": md_content,
            "markdown_file": str(md_file),
            "figures": figures_data,
            "tables": getattr(result, 'tables', []),
            "paragraphs": getattr(result, 'paragraphs', []),
            "pages": getattr(result, 'pages', []),
            "raw_result": result
        }
    
    def _extract_figures(self, result: Any, save_path: Path) -> List[Dict]:
        """提取图片"""
        figures_data = []
        
        if not hasattr(result, 'figures') or not result.figures:
            logging.info("文档中未检测到图片")
            return figures_data
        
        operation_id = getattr(result, 'operation_id', None)
        figures_dir = save_path / f"{save_path.name}_figures"
        figures_dir.mkdir(exist_ok=True)
        
        for idx, figure in enumerate(result.figures):
            figure_content = ""
            figure_caption = ""
            
            # 提取图片内容
            if hasattr(figure, 'spans'):
                for span in figure.spans:
                    figure_content += result.content[span.offset:span.offset + span.length]
            
            if hasattr(figure, 'caption') and figure.caption:
                figure_caption = figure.caption.content
            
            # 下载图片
            if hasattr(figure, 'id') and figure.id:
                try:
                    response = self.client.get_analyze_result_figure(
                        model_id=getattr(result, 'model_id', 'prebuilt-layout'),
                        result_id=operation_id,
                        figure_id=figure.id
                    )
                    
                    # 保存图片
                    img_path = figures_dir / f"{figure.id}.png"
                    with open(img_path, "wb") as writer:
                        writer.writelines(response)
                    
                    # 保存元数据
                    meta_path = figures_dir / f"{figure.id}.json"
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump({
                            "content": figure_content,
                            "caption": figure_caption,
                            "figure_id": figure.id
                        }, f, ensure_ascii=False, indent=2)
                    
                    figures_data.append({
                        "figure_id": figure.id,
                        "image_path": str(img_path),
                        "meta_path": str(meta_path),
                        "content": figure_content,
                        "caption": figure_caption
                    })
                    
                except Exception as e:
                    logging.warning(f"提取图片失败 {figure.id}: {e}")
        
        return figures_data
    
    def _merge_cross_page_tables(self, result: Any) -> str:
        """合并跨页表格"""
        # 这里调用你的表格合并逻辑
        return self._identify_and_merge_cross_page_tables(result)
    
    def _identify_and_merge_cross_page_tables(self, result: Any) -> str:
        """识别并合并跨页表格"""
        if not hasattr(result, 'tables') or not result.tables:
            return result.content if hasattr(result, 'content') else ""
            
        merge_tables_candidates, table_integral_span_list = self._get_merge_table_candidates_and_table_integral_span(result.tables)
        print("----------------------------------------")

        SEPARATOR_LENGTH_IN_MARKDOWN_FORMAT = 2
        merged_table_list = []
        
        for i, merged_table in enumerate(merge_tables_candidates):
            pre_table_idx = merged_table["pre_table_idx"]
            start = merged_table["start"]
            end = merged_table["end"]
            has_paragraph = self._check_paragraph_presence(result.paragraphs, start, end)

            is_horizontal = self._check_tables_are_horizontal_distribution(result, pre_table_idx)
            is_vertical = (
                not has_paragraph and
                result.tables[pre_table_idx].column_count
                == result.tables[pre_table_idx + 1].column_count
                and table_integral_span_list[pre_table_idx + 1]["min_offset"]
                - table_integral_span_list[pre_table_idx]["max_offset"]
                <= SEPARATOR_LENGTH_IN_MARKDOWN_FORMAT
            )

            if is_vertical or is_horizontal:
                print(f"Merge table: {pre_table_idx} and {pre_table_idx + 1}")
                print("----------------------------------------")

                remark = ""
                cur_content = result.content[table_integral_span_list[pre_table_idx + 1]["min_offset"] : table_integral_span_list[pre_table_idx + 1]["max_offset"]]

                if is_horizontal:
                    remark = result.content[table_integral_span_list[pre_table_idx]["max_offset"] : table_integral_span_list[pre_table_idx + 1]["min_offset"]]
                
                merged_list_len = len(merged_table_list)
                if merged_list_len > 0 and len(merged_table_list[-1]["table_idx_list"]) > 0 and merged_table_list[-1]["table_idx_list"][-1] == pre_table_idx:
                    merged_table_list[-1]["table_idx_list"].append(pre_table_idx + 1)
                    merged_table_list[-1]["offset"]["max_offset"]= table_integral_span_list[pre_table_idx + 1]["max_offset"]
                    if is_vertical:
                        merged_table_list[-1]["content"] = self._merge_vertical_tables(merged_table_list[-1]["content"], cur_content)
                    elif is_horizontal:
                        merged_table_list[-1]["content"] = self._merge_horizontal_tables(merged_table_list[-1]["content"], cur_content)
                        merged_table_list[-1]["remark"] += remark
                else:
                    pre_content = result.content[table_integral_span_list[pre_table_idx]["min_offset"] : table_integral_span_list[pre_table_idx]["max_offset"]]
                    merged_table = {
                        "table_idx_list": [pre_table_idx, pre_table_idx + 1],
                        "offset": {
                            "min_offset": table_integral_span_list[pre_table_idx]["min_offset"],
                            "max_offset": table_integral_span_list[pre_table_idx + 1]["max_offset"],
                        },
                        "content": self._merge_vertical_tables(pre_content, cur_content) if is_vertical else self._merge_horizontal_tables(pre_content, cur_content),
                        "remark": remark.strip() if is_horizontal else ""
                    }
                    
                    if merged_list_len <= 0:
                        merged_table_list = [merged_table]
                    else:
                        merged_table_list.append(merged_table)

        optimized_content = ""
        if merged_table_list:
            print(f"{len(merged_table_list)} merged result totally.")
            print("=========================================================")
            start_idx = 0
            for merged_table in merged_table_list:
                print(f"Merged result of table {', '.join([str(idx) for idx in merged_table['table_idx_list']])}")
                print("-----------------------------------------------------")
                print(merged_table["content"])
                print("-----------------------------------------------------")

                optimized_content += result.content[start_idx : merged_table["offset"]["min_offset"]] + merged_table["content"] + merged_table["remark"]
                start_idx = merged_table["offset"]["max_offset"]
            
            optimized_content += result.content[start_idx:]
        else:
            optimized_content = result.content
            
        return optimized_content
    
    def _get_table_page_numbers(self, table: Any) -> List[int]:
        """获取表格出现的页码列表"""
        if hasattr(table, 'bounding_regions'):
            return [region.page_number for region in table.bounding_regions]
        return []

    def _get_table_span_offsets(self, table: Any) -> Tuple[int, int]:
        """计算表格跨度的最小和最大偏移量"""
        if hasattr(table, 'spans') and table.spans:
            min_offset = table.spans[0].offset
            max_offset = table.spans[0].offset + table.spans[0].length

            for span in table.spans:
                if span.offset < min_offset:
                    min_offset = span.offset
                if span.offset + span.length > max_offset:
                    max_offset = span.offset + span.length

            return min_offset, max_offset
        else:
            return -1, -1
    
    def _get_merge_table_candidates_and_table_integral_span(self, tables: List[Any]) -> Tuple[List[Dict], List[Dict]]:
        """获取合并表格候选者和表格积分跨度"""
        table_integral_span_list = []
        merge_tables_candidates = []
        pre_table_idx = -1
        pre_table_page = -1
        pre_max_offset = 0

        for table_idx, table in enumerate(tables):
            min_offset, max_offset = self._get_table_span_offsets(table)
            if min_offset > -1 and max_offset > -1:
                table_page = min(self._get_table_page_numbers(table))
                print(f"Table {table_idx} has offset range: {min_offset} - {max_offset} on page {table_page}")

                if table_page == pre_table_page + 1:
                    pre_table = {
                        "pre_table_idx": pre_table_idx,
                        "start": pre_max_offset,
                        "end": min_offset,
                        "min_offset": min_offset,
                        "max_offset": max_offset,
                    }
                    merge_tables_candidates.append(pre_table)
                    
                table_integral_span_list.append({
                    "idx": table_idx,
                    "min_offset": min_offset,
                    "max_offset": max_offset,
                })

                pre_table_idx = table_idx
                pre_table_page = table_page
                pre_max_offset = max_offset
            else:
                print(f"Table {table_idx} is empty")
                table_integral_span_list.append({
                    "idx": {table_idx}, "min_offset": -1, "max_offset": -1
                })

        return merge_tables_candidates, table_integral_span_list

    def _check_paragraph_presence(self, paragraphs: List[Any], start: int, end: int) -> bool:
        """检查指定范围内是否有段落"""
        for paragraph in paragraphs:
            if hasattr(paragraph, 'spans'):
                for span in paragraph.spans:
                    if span.offset > start and span.offset < end:
                        if not hasattr(paragraph, 'role'):
                            return True
                        elif hasattr(paragraph, 'role') and paragraph.role not in ["pageHeader", "pageFooter", "pageNumber"]:
                            return True
        return False

    def _check_tables_are_horizontal_distribution(self, result: Any, pre_table_idx: int) -> bool:
        """检查两个连续页面是否为水平分布"""
        INDEX_OF_X_LEFT_TOP = 0
        INDEX_OF_X_LEFT_BOTTOM = 6
        INDEX_OF_X_RIGHT_TOP = 2
        INDEX_OF_X_RIGHT_BOTTOM = 4

        THRESHOLD_RATE_OF_RIGHT_COVER = 0.99
        THRESHOLD_RATE_OF_LEFT_COVER = 0.01

        is_right_covered = False
        is_left_covered = False

        if (
            hasattr(result.tables[pre_table_idx], 'row_count') and
            hasattr(result.tables[pre_table_idx + 1], 'row_count') and
            result.tables[pre_table_idx].row_count
            == result.tables[pre_table_idx + 1].row_count
        ):
            for region in result.tables[pre_table_idx].bounding_regions:
                page_width = result.pages[region.page_number - 1].width
                x_right = max(
                    region.polygon[INDEX_OF_X_RIGHT_TOP],
                    region.polygon[INDEX_OF_X_RIGHT_BOTTOM],
                )
                right_cover_rate = x_right / page_width
                if right_cover_rate > THRESHOLD_RATE_OF_RIGHT_COVER:
                    is_right_covered = True
                    break

            for region in result.tables[pre_table_idx + 1].bounding_regions:
                page_width = result.pages[region.page_number - 1].width
                x_left = min(
                    region.polygon[INDEX_OF_X_LEFT_TOP],
                    region.polygon[INDEX_OF_X_LEFT_BOTTOM],
                )
                left_cover_rate = x_left / page_width
                if left_cover_rate < THRESHOLD_RATE_OF_LEFT_COVER:
                    is_left_covered = True
                    break

        return is_left_covered and is_right_covered

    def _remove_header_from_markdown_table(self, markdown_table: str) -> str:
        """从 Markdown 表格中移除表头"""
        HEADER_SEPARATOR_CELL_CONTENT = " - "

        result = ""
        lines = markdown_table.splitlines()
        for line in lines:
            border_list = line.split(HEADER_SEPARATOR_CELL_CONTENT)
            border_set = set(border_list)
            if len(border_set) == 1 and border_set.pop() == BORDER_SYMBOL:
                continue
            else:
                result += f"{line}\n"

        return result

    def _merge_horizontal_tables(self, md_table_1: str, md_table_2: str) -> str:
        """合并两个连续的水平 Markdown 表格"""
        rows1 = md_table_1.strip().splitlines()
        rows2 = md_table_2.strip().splitlines()

        merged_rows = []
        for row1, row2 in zip(rows1, rows2):
            merged_row = (
                (row1[:-1] if row1.endswith(BORDER_SYMBOL) else row1)
                + BORDER_SYMBOL
                + (row2[1:] if row2.startswith(BORDER_SYMBOL) else row2)
            )
            merged_rows.append(merged_row)

        merged_table = "\n".join(merged_rows)
        return merged_table

    def _merge_vertical_tables(self, md_table_1: str, md_table_2: str) -> str:
        """合并两个连续的垂直 Markdown 表格"""
        table2_without_header = self._remove_header_from_markdown_table(md_table_2)
        rows1 = md_table_1.strip().splitlines()
        rows2 = table2_without_header.strip().splitlines()

        num_columns1 = len(rows1[0].split(BORDER_SYMBOL)) - 2
        num_columns2 = len(rows2[0].split(BORDER_SYMBOL)) - 2

        if num_columns1 != num_columns2:
            raise ValueError("Different count of columns")

        merged_rows = rows1 + rows2
        merged_table = '\n'.join(merged_rows)

        return merged_table