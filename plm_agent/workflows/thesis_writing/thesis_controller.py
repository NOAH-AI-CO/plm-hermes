import datetime
import json
import re
from pathlib import Path
from typing import AsyncGenerator
from pydantic import BaseModel, Field
from transformers.models.electra.modeling_electra import ElectraSelfAttention

from llm.composite_models import CompositeGPT5Mini
from llm.gcp_models import ClaudeSonnet45, CompositeClaude, Gemini25Pro
from agent.explore.mindsearch_agent_v3_pubmed import MindSearchPubMedHitlAgent
from utils.oss_client import oss_singleton_client
from workflows.thesis_writing.temp_sinovac_thesis_data import sinovac11_thesis_section_data_dict, sinovac13_thesis_section_data_dict, sinovac20_thesis_section_data_dict, test_data_dict
from workflows.chunk_models import MessageChunk, MessageStatus, MessageType, SegmentType
from workflows.analyze_target import run_pubmed_agent, save_to_file
from workflows.thesis_writing.thesis_prompt import chapter_by_chapter_paper_prompt, coherence_and_consistency_prompt, gen_abstract_prompt, gen_conclusion_prompt, gen_discuss_prompt, gen_outline_prompt, gen_outline_prompt_v1, gen_thesis_from_outline_section_prompt, numbering_format_prompt, origin_text_prompt, polish_thesis_prompt, reference_format_instruction_prompt, section_abstract_prompt
from utils.human_in_loop.helpers import function_call_with_retry
from utils.core.get_json_schema import get_openai_json_schema_v3


THESIS_DATA_MAPPING = {
    'sinovac13_thesis_data': sinovac13_thesis_section_data_dict,
    'sinovac11_thesis_data': sinovac11_thesis_section_data_dict,
    "sinovac20_thesis_data": sinovac20_thesis_section_data_dict,
    "test_data": test_data_dict,
}

class GenSectionAbstractSchema(BaseModel):
    """
    生成单个章节的摘要，生成单个章节的上下文用
    """
    abstract: str = Field(description="The abstract of the section, 150-200 words")

class GenAbstractSchema(BaseModel):
    """
    论文摘要 Schema
    """
    abstract: str = Field(description="The abstract of the thesis, 200-300 words")

class GenConclusionSchema(BaseModel):
    """
    论文结论 Schema
    """
    conclusion: str = Field(description="The conclusion of the thesis, 350-400 words")

class GenDiscussSchema(BaseModel):
    """
    论文讨论部分 Schema
    """
    discuss: str = Field(description="The discuss of the thesis, 400-600 words")

class GenOutlineSchema(BaseModel):
    """
    论文大纲 Schema
    """
    outline_list: list[str] = Field(
        default_factory=list,
        description="The thesis outline will have 6-8 chapters, presented as a list of strings. Each string must elaborate on the chapter with subheadings, core objectives, and suggested word count."
    )
class PubmedController:
    
    async def run_pubmed_agent_with_tool_result(self, user_prompt: str, language: str = 'en', priority_pmids: list[str] = None,) -> AsyncGenerator[dict, None]:
        agent = MindSearchPubMedHitlAgent()

        async for chunk in agent.start_wo_dump(
            user_prompt=user_prompt,
            history_messages=[],
            language=language,
            params={'language': language},            
            prompt_template="",       
            template_kwargs={}, 
            priority_pubmed_ids=priority_pmids or [], 
        ):
            yield chunk


class ThesisControllerV2:
    def __init__(self, thesis_outline_data: dict, language: str = "en", simple_llm=CompositeClaude(), llm = Gemini25Pro(),):
        self.simple_llm = simple_llm
        self.llm = llm
        self.thesis_outline_data = thesis_outline_data or {}
        self.language = language
        self.pubmed_controller = PubmedController()  # en\zn
        self.output_section_list = list()   # 分章节输出
        self.output_thesis = str()          # 整体输出，中间状态

    @property
    def thesis_title(self) -> str:
        return self.thesis_outline_data.get('title', '')

    @property
    def thesis_outline_list(self) -> list[dict]:
        return self.thesis_outline_data.get('thesis_outline_list', [])

    @property
    def thesis_words(self) -> int:
        return self.thesis_outline_data.get('thesis_words', 10000)
    
    @property
    def thesis_outline(self) -> str:
        return "\n\n".join(
            section.get("outline_section", "").strip() for section in self.thesis_outline_list if section.get("outline_section")
            ) or ""

    async def gen_outline(self) -> list[dict]: 
        """
        生成论文大纲
        """
        llm = CompositeGPT5Mini()
        schema = get_openai_json_schema_v3(GenOutlineSchema)
        outline_words = int(self.thesis_words)
        tool_choice = {"type": "function", "function": {"name": schema[0]['function']['name']}}
        try:
            result = await function_call_with_retry(
                llm,
                user_prompt=gen_outline_prompt_v1.format(thesis_title=self.thesis_title, thesis_words=outline_words),
                tools=schema,
                tool_choice=tool_choice,
                temperature=0.3,
                # language=language
            )
            return result.get("outline_list", [])
        except Exception as e:
            raise Exception(f"论文大纲生成失败: {str(e)}")

    async def gen_section_content(self, priority_pmids: list[str] = []) -> str:
        """
        生成单个章节的内容
        args: priority_pmids: 优先级 PMID 列表，需要优先引用的文章
        """
        # thesis_data_dict = THESIS_DATA_MAPPING.get(thesis_section_data, [])
        result_chunk = None
        for idx, thesis_outline_dict in enumerate(self.thesis_outline_list):
            prompt = gen_thesis_from_outline_section_prompt.format(
                title = self.thesis_title,
                thesis_outline = self.thesis_outline,
                outline_section = thesis_outline_dict.get('outline_section', ''),
                # 构造上下文
                thesis_context = self._build_thesis_context(idx),
                language = self.language,
            )
            result_chunk = None
            max_retry = 3
            for _ in range(max_retry):
                async for chunk in self.pubmed_controller.run_pubmed_agent_with_tool_result(
                    prompt, language=self.language, priority_pmids=priority_pmids or []
                ):
                    result_chunk = chunk
                    if result_chunk.get('content'):

                        yield MessageChunk(
                            type=MessageType.CHAT,
                            status=MessageStatus.DOING,
                            segment_type=SegmentType.SECTION,
                            segment_info={"section_index": idx},
                            message=result_chunk.get('content', '')
                        ).model_dump()
                    else:
                        yield MessageChunk(
                            type=MessageType.TOOL,
                            status=MessageStatus.DOING,
                            segment_type=SegmentType.SECTION,
                            segment_info={"section_index": idx},
                            message=result_chunk
                        ).model_dump()

                # 检查 content 是否为空
                content_ok = bool(result_chunk and result_chunk.get("content"))
                if content_ok and len(result_chunk.get("content")) > 200:
                    yield MessageChunk(
                        type=MessageType.CHAT,
                        status=MessageStatus.DONE,
                        segment_type=SegmentType.SECTION,
                        segment_info={"section_index": idx},
                        message=result_chunk.get('content', '')
                    ).model_dump()
                    break 
            self.output_section_list.append(result_chunk)
            save_to_file(f'output_section_list_{idx}', str(self.output_section_list))

        # 存json 一个content字段和一个source字段
        save_data = list()
        for section in self.output_section_list:
            save_data.append({
                'content': section.get('content', ''),
                'source': section.get('search_graph', {}).get('source', {})
            })
        yield save_data
        # output_dir = Path("/Users/shey/workspace/NoahServer/NoahAgent/noah_agent/outputs")
        # output_dir.mkdir(parents=True, exist_ok=True)  # 确保目录存在

        # filename = output_dir / f"output_section_list_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        # with open(filename, "w", encoding="utf-8") as f:
        #     json.dump(save_data, f, ensure_ascii=False, indent=4)

    def _build_thesis_context(self, idx) -> str:
        """
        单章节生成部分，构造上下文
        """
        if idx == 0:
            return "此章节为第一章节，无上下文"
        else:
            return f"此章节为第{idx+1}章节，前一章节内容为：{self.output_section_list[idx-1].get('content', '')}\n\n"
    
    async def gen_abstract(self, thesis_data: str, conclusion: str, language: str = 'en') -> str:
        """
        论文的摘要生成
        """

        llm = CompositeGPT5Mini()
        schema = get_openai_json_schema_v3(GenAbstractSchema)
        tool_choice = {"type": "function", "function": {"name": schema[0]['function']['name']}}
        try:
            result = await function_call_with_retry(
                llm,
                user_prompt=gen_abstract_prompt.format(thesis_data=thesis_data, thesis_conclusion=conclusion, language=language),
                tools=schema,
                tool_choice=tool_choice,
                temperature=0.3,
                # language=language
            )
            return MessageChunk(
                        type=MessageType.CHAT,
                        status=MessageStatus.DONE,
                        segment_type=SegmentType.ABSTRACT,
                        message=result.get('abstract', '')
                    ).model_dump()
        except Exception as e:
            raise Exception(f"论文的摘要生成失败: {str(e)}")

    async def gen_conclusion(self, thesis_data: str, language: str = 'en') -> str:
        """
        论文的结论生成
        """

        llm = CompositeGPT5Mini()
        schema = get_openai_json_schema_v3(GenConclusionSchema)
        tool_choice = {"type": "function", "function": {"name": schema[0]['function']['name']}}
        try:
            result = await function_call_with_retry(
                llm,
                user_prompt=gen_conclusion_prompt.format(thesis_data=thesis_data, language=language),
                tools=schema,
                tool_choice=tool_choice,
                temperature=0.3,
                # language=language
            )
            return MessageChunk(
                        type=MessageType.CHAT,
                        status=MessageStatus.DONE,
                        segment_type=SegmentType.CONCLUSION,
                        message=result.get('conclusion', '')
                    ).model_dump()
        except Exception as e:
            raise Exception(f"论文结论的生成失败: {str(e)}")

    # 
    async def gen_discuss(self, thesis_data: list[dict[str, any]], language: str = 'en', priority_pmids: list[str] = []) -> str:
        """
        论文的讨论生成
        """
        thesis_data_str = "\n\n".join(section.get("content", "") for section in thesis_data)
        prompt = gen_discuss_prompt.format(thesis_data=thesis_data_str, language=language)
        result_chunk = None
        max_retry = 3
        for _ in range(max_retry):
            async for chunk in self.pubmed_controller.run_pubmed_agent_with_tool_result(
                prompt, language=self.language, priority_pmids=priority_pmids or []
            ):
                result_chunk = chunk
                yield MessageChunk(
                    type=MessageType.CHAT,
                    status=MessageStatus.DOING,
                    segment_type=SegmentType.DISCUSS,
                    message=result_chunk.get('content', '')
                ).model_dump()
            

            # 检查 content 是否为空
            content_ok = bool(result_chunk and result_chunk.get("content"))
            if content_ok and len(result_chunk.get("content")) > 200:
                yield MessageChunk(
                    type=MessageType.CHAT,
                    status=MessageStatus.DONE,
                    segment_type=SegmentType.DISCUSS,
                    message=result_chunk.get('content', '')
                ).model_dump()
                break 
        thesis_data.append({"content": result_chunk.get("content", ""), "source": result_chunk.get("search_graph", {}).get("source", {})})
        yield thesis_data

    async def output_the_thesis(self, full_text: str, abstract: str, conclusion: str, language: str = 'en') -> AsyncGenerator[str, str]:
        """
        润色论文，最终输出论文，不包含文献，只输出正文
         """

        # 要加摘讨结的字数
        complete_thesis_words = self.thesis_words + 1000
        filled_prompt = polish_thesis_prompt.format(language=language, thesis_title=self.thesis_title, thesis_abstract=abstract, thesis_conclusion=conclusion, thesis_data=full_text, thesis_words=complete_thesis_words, thesis_outline=self.thesis_outline)
        max_retry = 3
        for _ in range(max_retry):
            result = str()  
            async for chunk in self.llm.stream_call(user_prompt=filled_prompt):
                result += chunk
                yield MessageChunk(
                    type=MessageType.CHAT,
                    status=MessageStatus.DOING,
                    segment_type=SegmentType.THESIS,
                    message=result
                ).model_dump()
            
            if result:
                yield MessageChunk(
                    type=MessageType.CHAT,
                    status=MessageStatus.DONE,
                    segment_type=SegmentType.THESIS,
                    message=result
                ).model_dump()
                break
    
    async def save_md_to_oss(self, file_name: str, content: str) -> str:
        """
        保存论文到oss
        """
        # 保存html到oss
        base_path = "kybk/thesis/"
        oss_path = base_path + file_name
        oss_singleton_client.upload_string(content, oss_path, content_type='text/markdown')
        return oss_path


class SourceFormatter:
    """
    文献格式化
    """

    @classmethod
    def collect_sources(cls, sections: list[dict[str, any]]) -> list[dict[str, any]]:
        """
        按章节顺序、组内 id 顺序，使用 pubmed_id 去重，并给每条 source 加 group_index。

        1. 遍历章节顺序（第一组到最后一组）
        2. 组内按原先的 source['id'] 升序
        3. 以 pubmed_id 去重（先出现者保留）
        """
        seen_pubmed_ids = {}
        ordered_sources = []

        for group_idx, section in enumerate(sections, start=1):
            group_sources = sorted(section.get("source", []), key=lambda src: src.get("id", 0))
            for order_in_group, src in enumerate(group_sources, start=1):
                pubmed_id = src.get("pubmed_id")
                if not pubmed_id:
                    continue

                pos = {"group": group_idx, "order_in_group": order_in_group}

                if pubmed_id not in seen_pubmed_ids:
                    src_with_meta = dict(src)
                    src_with_meta["group_index"] = group_idx
                    src_with_meta["positions"] = [pos]
                    seen_pubmed_ids[pubmed_id] = src_with_meta
                    ordered_sources.append(src_with_meta)
                else:
                    seen_pubmed_ids[pubmed_id]["positions"].append(pos)

        for idx, src in enumerate(ordered_sources, start=1):
            src["new_index"] = idx
        return ordered_sources

    @classmethod
    def build_group_reference_map(cls, sections, sources):
        """
        sections: 全部，原始的sources
        sources: 经过去重和sort的sources
        返回形如：
        {
            1: [{1: 5}, {2: 7}],
            2: [{1: 3}],
            ...
        }
        其中键为组号，值为该组内引用的顺序列表。
        """
        # pubmed_id -> new_index
        pubmed_to_new = {
            src.get("pubmed_id"): src["new_index"]
            for src in sources
            if src.get("pubmed_id")
        }

        group_map = {}

        for group_idx, section in enumerate(sections, start=1):
            entries = []
            group_sources = sorted(section.get("source", []), key=lambda s: s.get("id", 0))
            for order_in_group, src in enumerate(group_sources, start=1):
                pubmed_id = src.get("pubmed_id")
                if not pubmed_id:
                    continue
                new_index = pubmed_to_new.get(pubmed_id)
                if new_index is None:
                    continue
                entries.append({order_in_group: new_index})
            if entries:
                group_map[group_idx] = entries

        return group_map
    
    @classmethod
    def merge_and_renumber_contents(cls, sections, group_mapping):
        """
        sections: 原 JSON 数组
        group_mapping: 形如 {1: [{1: 1}, {2: 2}], 2: [...]} 的字典
        返回拼接后、引用已替换的新正文
        """
        merged_parts = []

        for group_idx, section in enumerate(sections, start=1):
            content = section.get("content", "")
            if not content:
                continue

            mapping_entries = group_mapping.get(group_idx, [])
            if mapping_entries:
                # 合并成 {旧编号: 新编号}
                old_to_new = {}
                for pair in mapping_entries:
                    for old, new in pair.items():
                        try:
                            old_to_new[int(old)] = int(new)
                        except (ValueError, TypeError):
                            pass
                content = cls._replace_section_citations(content, old_to_new)

            merged_parts.append(content.strip())

        return "\n\n".join(part for part in merged_parts if part)

    @classmethod
    def _replace_section_citations(cls, text, old_to_new):
        """
        merge_and_renumber_contents用
        替换正文的引文
        """
        # 先处理 [旧](url) 形式
        def repl_link(match):
            old = int(match.group(1))
            url = match.group(2)
            new = old_to_new.get(old)
            if new is None:
                return match.group(0)
            return f"[{new}]"

        text = re.sub(r"\[(\d+)\]\((https?://[^\)]+)\)", repl_link, text)

        return text
    
    @classmethod
    def _replace_citation_numbers(cls, text, mapping):
        """
        text: 正文文本
        mapping: {旧编号: 新编号} 的字典
        返回替换后的文本
        """
        
        # 再处理独立的 [数字] 格式
        def repl_plain(match):
            old = int(match.group(1))
            new = mapping.get(str(old)) or mapping.get(old)

            if new is None:
                return match.group(0)
            return f"[{new}]"
    
        return re.sub(r"\[(\d+)\]", repl_plain, text)


    @classmethod
    def _add_reference_url(cls, text, url):
        """
        替换正文的引文 [序号]格式 替换成 [序号](url)格式
        """
        return text + f"({url})"

    @classmethod
    def dedupe_keep_order(cls, items):
        """
        去重，保持原顺序
        """
        return list(dict.fromkeys(items))
    
    @classmethod
    def format_reference_text(cls, text, source_list):
        """
        润色后的引文重排
        """
        def filter_and_reindex_sources(source_list, filter_matches):
            """
            source_list: 字典列表，每个字典有 new_index 字段
            filter_matches: 字符串列表，按正文中首次出现的顺序，如 ['1', '2', '3', '1'] -> ['1', '2', '3']
            返回：过滤后的列表，按首次出现顺序排序，并添加新的 index 字段（从 1 开始）
            """
            # 将 filter_matches 转为整数集合，方便查找
            filter_set = {int(x) for x in filter_matches if x.isdigit()}
            
            # 构建 new_index -> source 的映射
            new_index_to_source = {
                src.get("new_index"): src
                for src in source_list
                if isinstance(src, dict) and src.get("new_index") in filter_set
            }
            
            # 按照 filter_matches 的顺序（首次出现顺序）来构建结果
            filtered = []
            seen = set()
            for match in filter_matches:
                new_idx = int(match) if match.isdigit() else None
                if new_idx is not None and new_idx in new_index_to_source and new_idx not in seen:
                    filtered.append(dict(new_index_to_source[new_idx]))
                    seen.add(new_idx)
            
            # 添加新的 index 字段（从 1 开始）
            for idx, src in enumerate(filtered, start=1):
                src["index"] = idx
                src['text_index'] = filter_matches[idx-1]
            
            return filtered

        def build_new_index_to_index_mapping(source_list):
            """
            构建 new_index -> index 的映射字典
            """
            return {
                src.get("text_index"): src.get("index")
                for src in source_list
                if isinstance(src, dict) and src.get("text_index") is not None and src.get("index") is not None
            }

        def compress_citations(text):
            """
            将连续的 [n] 合并为区间：
            [1][2]         -> [1-2]
            [1][2][3][5]   -> [1-3, 5]
            [1][3][5]      -> [1, 3, 5]
            """
            pattern = r'(?:\[(\d+)\])+'
            def repl(match):
                full = match.group(0)
                nums = sorted(set(int(n) for n in re.findall(r'\[(\d+)\]', full)))
                if not nums:
                    return full
                ranges = []
                start = prev = nums[0]
                for n in nums[1:]:
                    if n == prev + 1:
                        prev = n
                    else:
                        if start == prev:
                            ranges.append(str(start))
                        else:
                            ranges.append(f"{start}-{prev}")
                        start = prev = n
                if start == prev:
                    ranges.append(str(start))
                else:
                    ranges.append(f"{start}-{prev}")
                return f"[{', '.join(ranges)}]"
            return re.sub(pattern, repl, text)

        # 1. 正则提取正文中所有的引文序号（保持出现顺序）
        regex = r"\[(\d+)\]"
        matches = re.findall(regex, text)  # ['1', '2', '3', '1', ...]
        
        # 2. 去重但保持首次出现的顺序
        filter_matches = cls.dedupe_keep_order(matches)  # ['1', '2', '3', ...]
        # 3. 按照首次出现顺序构建新的 source_list：为了构建新的文献，也为了重构正文中的引文
        filtered_sources = filter_and_reindex_sources(source_list, filter_matches)

        # 4. 构建映射：text_index -> 新的 index
        sources_mapping = build_new_index_to_index_mapping(filtered_sources)
        
        # 5. 对正文中的序号进行重排
        text = cls._replace_citation_numbers(text, sources_mapping)
        
        # 6. 对序号进行压缩 [1][2] -> [1-2]
        compress_text = compress_citations(text)
        
        return {
            'text': compress_text,
            'sources': filtered_sources
        }

    @classmethod
    def format_references(cls, entries: list[dict]) -> list[str]:
        """
        构建参考文献列表
        返回格式化后的参考文献列表
        list[dict] -> list[str]
        """
        def format_reference(entry):
            """
            entry: 单条引用 dict，包含 author/title/full_journal_name/pub_date/pubmed_id
            返回字符串：作者. 标题. [期刊] 日期. PMID: xxxx
            """
            authors = (entry.get("author") or "").split(",")
            authors = [a.strip() for a in authors if a.strip()]

            if len(authors) > 4:
                authors = authors[:3] + ["et al"]

            author_str = ", ".join(authors)
            title = entry.get("title", "").strip()
            journal = entry.get("full_journal_name", "").strip()
            pub_date = entry.get("pub_date", "").strip()
            pmid = entry.get("pubmed_id", "").strip()

            url = entry.get("url", "").strip()
            
            parts = []
            if author_str:
                parts.append(f"{author_str}")
            if title:
                parts.append(f"{title}")
            if journal:
                parts.append(f"[{journal}]")
            if pub_date:
                parts.append(pub_date)
            if pmid:
                parts.append(f"PMID: {pmid}")
            if url:
                parts.append(f"URL:({url})")
            
            return ". ".join(parts)
        reference_list = [format_reference(entry) for entry in entries]
        # 增加序号 替换..成.
        reference_list = [f"{idx+1}. {line}" for idx, line in enumerate(reference_list)]
        reference_list = [line.replace("..", ".") for line in reference_list]
        return reference_list
    
    @classmethod
    def expand_citations_to_individual(cls, text):
        """
        将文本中的所有引文格式展开为 [1][2][3] 这种格式
        
        支持的输入格式：
        - [1] -> [1]
        - [1-3] -> [1][2][3]
        - [3, 5] -> [3][5]
        - [1, 3, 5] -> [1][3][5]
        - [1, 3-5] -> [1][3][4][5]
        
        参数:
            text: 包含引文的文本
        
        返回:
            展开后的文本，所有引文都变成 [1][2][3] 格式
        """
        import re
        
        def parse_citation_content(content):
            """
            解析引文内容，返回所有数字的列表
            """
            numbers = []
            # 按逗号分割
            parts = [p.strip() for p in content.split(',')]
            
            for part in parts:
                if '-' in part:
                    # 处理范围，如 "1-3"
                    range_parts = part.split('-')
                    if len(range_parts) == 2:
                        try:
                            start = int(range_parts[0].strip())
                            end = int(range_parts[1].strip())
                            # 确保 start <= end
                            if start <= end:
                                numbers.extend(range(start, end + 1))
                        except ValueError:
                            # 如果解析失败，跳过
                            pass
                else:
                    # 处理单个数字
                    try:
                        num = int(part.strip())
                        numbers.append(num)
                    except ValueError:
                        # 如果解析失败，跳过
                        pass
            
            return numbers
        
        def repl_citation(match):
            """
            替换匹配到的引文，展开为 [1][2][3] 格式
            """
            content = match.group(1)  # 获取 [ ] 内的内容
            
            # 解析出所有数字
            numbers = parse_citation_content(content)
            
            if not numbers:
                # 如果解析失败，保持原样
                return match.group(0)
            
            # 去重并排序
            unique_nums = sorted(set(numbers))
            
            # 格式化为 [1][2][3] 格式
            return ''.join(f'[{num}]' for num in unique_nums)
        
        # 匹配 [内容] 格式，内容可以是数字、范围、逗号分隔等
        # 正则表达式：匹配 [ 开头，] 结尾，中间是数字、逗号、空格、连字符的组合
        pattern = r'\[([0-9\s,\-]+)\]'
        return re.sub(pattern, repl_citation, text)
    

async def gen_thesis(title: str, content: list[str], words: int, language: str, priority_pmids: list[str] = []) -> AsyncGenerator[dict, str]:
    """
    @summary: 生成论文接口
    
    POST 参数:
      - title: 论文标题
      - content: 大纲内容列表
      - words: 论文字数
      - language: 语言
      
    return: 流式返回论文结果
    """
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    thesis_outline_data = {
        "title": title,
        "thesis_outline_list": [{"outline_section": con} for con in content],
        "thesis_words": words,
    }

    thesis_controller = ThesisControllerV2(thesis_outline_data, language=language)

    async for chunk in thesis_controller.gen_section_content(priority_pmids=priority_pmids):
        thesis_dict_data = chunk
        yield chunk

    # 讨论加上引文
    async for chunk in thesis_controller.gen_discuss(thesis_dict_data, language, priority_pmids=priority_pmids):
        thesis_dict_data = chunk
        yield chunk
    # with open("/Users/shey/workspace/NoahServer/NoahAgent/noah_agent/outputs/output_section_list_20251229_124135.json", "r", encoding="utf-8") as f:
    #     data = json.load(f)
    # thesis_dict_data = data
    
    # 去重并排过序的引文
    sources = SourceFormatter.collect_sources(thesis_dict_data)
    source_mapping = SourceFormatter.build_group_reference_map(thesis_dict_data, sources)
    # 重新排过引文的正文
    sort_referenve_text = SourceFormatter.merge_and_renumber_contents(thesis_dict_data, source_mapping)
    # 构建文献
    # ['1. 作者. 标题. ...']
    # source_str = SourceFormatter.format_references(sources)
    # save_to_file(f'重排过的正文_{timestamp}', sort_referenve_text + full_source_str)

    # 构建摘要、讨论和总结 不需要引文
    
    conclusion = await thesis_controller.gen_conclusion(sort_referenve_text, language)
    yield conclusion
    abstract = await thesis_controller.gen_abstract(sort_referenve_text, conclusion, language)
    yield abstract
    # abstract = ""
    # conclusion = ""
    # discuss = ""
    # 润色 加上时间戳

    thesis_dict = ""
    async for chunk in thesis_controller.output_the_thesis(sort_referenve_text, abstract, conclusion, language):
        thesis_dict = chunk
        yield chunk
    thesis_data = thesis_dict.get('message', '')
    save_to_file(f'润色后_{timestamp}', thesis_data+'\n\n 引文列表: '+str(sources))
    

    # with open("/Users/shey/workspace/NoahServer/NoahAgent/noah_agent/outputs/润色后_20251229_152246.md", 'r', encoding="utf-8") as f:
    #     thesis_data = f.read()
    # text, sources_str = thesis_data.split('\n\n 引文列表: ')
    # import ast
    # sources = ast.literal_eval(sources_str)  # 使用 ast.literal_eval 而不是 json.loads
    # thesis_data = text 

    # 对正文序号进行重新编排 润色后可能出现
    # 范围格式[1-3]应该展开。
    # 多个数字[3, 5]应该展开。
    # 多个数字[1, 3, 5]应该展开。
    # 混合格式[1, 3-5]应该展开。 把这些情况全部变成[1][2][3]
    expand_thesis_data = SourceFormatter.expand_citations_to_individual(thesis_data)
    # 对润色后的文章的正文以及引文进行重新编排
    formatted_dict = SourceFormatter.format_reference_text(expand_thesis_data, sources)
    text = formatted_dict.get('text')
    sources = formatted_dict.get('sources')
    # 构造sources的结构字符串， ：临时先把url拼上，用于验证pubmed幻觉 
    final_source_str = SourceFormatter.format_references(sources)
    full_final_sources_str = ("\n\n## References\n\n" if language == "en-US" else "\n\n## 参考文献\n\n") + "\n\n".join(final_source_str)
    final_thesis = text + full_final_sources_str
    yield MessageChunk(
        type=MessageType.CHAT,
        status=MessageStatus.DOING,
        segment_type=SegmentType.FINAL_THESIS,
        message=final_thesis
    ).model_dump()
    save_to_file(f'{thesis_outline_data.get("title")}_{timestamp}', final_thesis)
    # 保存到阿里云
    oss_path = await thesis_controller.save_md_to_oss(f'{thesis_outline_data.get("title")}_{timestamp}.md', final_thesis)
    final_thesis += "\n\n## 下载链接: " + "[点击查看报告]" + "(" + "https://public.ruosheng.bio/" + oss_path + ")"
    yield MessageChunk(
        type=MessageType.CHAT,
        status=MessageStatus.DONE,
        segment_type=SegmentType.FINAL_THESIS,
        message=final_thesis
    ).model_dump()

async def gen_outline(thesis_title: str, thesis_words: int, language: str = 'en') -> list[str]:
    """
    @summary: 生成论文大纲
    args:
        - thesis_title: 论文标题
        - thesis_words: 论文字数
        - language: 语言
    return: outline_list
    """
    thesis_outline_data = {
        "title": thesis_title,
        "thesis_words": thesis_words,
        "thesis_outline_list": []
    }
    thesis_controller = ThesisControllerV2(thesis_outline_data, language=language)
    outline_list = await thesis_controller.gen_outline()
    yield outline_list
    save_to_file(f'{thesis_outline_data.get("title")}_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}', str(outline_list))

