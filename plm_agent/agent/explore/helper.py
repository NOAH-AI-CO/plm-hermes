import re
import tiktoken
from typing import List, Any, Callable
from functools import wraps
from urllib.parse import urlparse

import agent.explore.constants as constants
from i18n import translate, processing_stages as i18n_processing_stages, resolve_language
from agent.explore.schema import (MindSearchResponse, ProcessingType, SearchNode, SearchType, WebSearchSubject)



class MindSearchHelper:

    def init_response(self, agent_name) -> MindSearchResponse:
        return MindSearchResponse()
    
    def search_processing_stages(self, agent_name: str, response: MindSearchResponse) -> MindSearchResponse:
        # Extract language code from agent_name (e.g. "mindsearchcn" -> "cn")
        lang_code = 'en'
        for code in ('cn', 'jp', 'arsa'):
            if code in agent_name:
                lang_code = code
                break
        language = resolve_language(lang_code)
        response.processing_stages.stages = i18n_processing_stages(language)
        response.processing_stages.stage_index += 1

        return response
    
    def get_intention_language(self, language: str) -> str:
        return resolve_language(language)
        
    def get_context(self, kwargs: dict) -> tuple[str, str, str, bool]:
        r"""Get context"""

        params = kwargs.get('params', {})
        
        language = self.get_intention_language(params.get('language', ''))
        model = params.get('model', '')
        background = params.get('background', '')
        enable_rag = params.get('enable_rag', True)
        
        return language, background, model, enable_rag 

    
    def websearch_fail_reason(self, node: SearchNode, language: str) -> str:
        if node.search_type == SearchType.PUBMED:
            if node.key_word != '':
                return translate("error.websearch_fail_pubmed", language, key_word=node.key_word)

        return translate("error.websearch_fail_network", language)

    def websearch_no_results(self, node: SearchNode, language: str) -> str:
        return translate("error.websearch_no_results", language)

    def pubmed_search_query(self, language: str) -> str:
        return translate("query.pubmed_search", language)
    
    def get_finish_stages(self, response: MindSearchResponse) -> MindSearchResponse:
        stage = len(response.processing_stages.stages) - 1
        response.processing_stages.stage_index = stage
        return response

    def dict_to_xml(self, data, root_name: str):
        if isinstance(data, dict):
            xml_str = f"<{root_name}>"
            for key, value in data.items():
                xml_str += self.dict_to_xml(value, key)
                xml_str += f"</{root_name}>"
                return xml_str
        elif isinstance(data, list):
            xml_str = ""
            for item in data:
                xml_str += self.dict_to_xml(item, root_name)
                return xml_str
        else:
            return f"<{root_name}>{str(data)}</{root_name}>"
        
    def _count_tokens(self, text: str, model: str) -> int:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))

    def truncate_messages(self, user_prompt: str, history_messages: list[dict] = [], max_tokens: int = 128000, model: str = 'gpt-4') -> list:
        total_tokens = 0
        truncated_messages = []

        messages = history_messages + [{"role": "user", "content": user_prompt}]
        
        for message in reversed(messages):
            message_tokens = self._count_tokens(message.get('content', ''), model)
            if total_tokens + message_tokens <= max_tokens:
                truncated_messages.insert(0, message)
                total_tokens += message_tokens
            else:
                break
        
        truncated_messages.pop()
        return truncated_messages

    def format_reference(self, output: str, url_map: dict = {}, default_site_name: str = '') -> tuple[str, list]:
        pattern = r'\[(.*?)\]\(([\w+.-]+:[^\s\)]+)\)'

        def format_reference(output: str, url_map: dict) -> str:
            def replace_func(match):
                url = match.group(2)
                if url not in url_map:
                    site_name = self.get_site_name(url, default=default_site_name)
                    url_map[url] = {
                        'id': len(url_map) + 1,
                        'url': url,
                        'site_name': site_name,
                        'title': site_name,
                        'summary': '',
                    }
                num = url_map[url]['id']
                return f'[{num}]({url})'
            
            output = re.sub(pattern, replace_func, output)
            return output
        
        output = format_reference(output=output, url_map=url_map)

        return output, list(url_map.values())
    
    def get_site_name(self, url: str, default: str) -> str:
        # Try to extract domain from URL using regex
        pattern = r'(?:https?:\/\/)?(?:www\.)?([^\/\s]+)'
        match = re.search(pattern, url)
        if match:
            domain = match.group(1)
            # Remove TLD and split by dots
            site_name = domain.split('.')[0]
            # Convert to title case for better readability
            return site_name.title()
    
        return default
    
    def format_output_reference(self,
                                output: str,
                                reference_patterns: list[str] = [r'\[(.*?)\]\(([\w+.-]+:[^\s\)]+)\)']) -> str:
        def replace_func(match):
            num = match.group(1)
            url = match.group(2)
            return f'[{num}]({url})'
        
        for patterns in reference_patterns:
            output = re.sub(patterns, replace_func, output)
        return output
    
    def format_invalid_reference(self,
                                 output: str,
                                 node: SearchNode,
                                 reference_patterns: list[str] = [r'\[(.*?)\]\(([\w+.-]+:[^\s\)]+)\)']) -> str:
        
        def replace_func(match):
            num = match.group(1)
            if not num.isdigit():
                return ''
            num = int(num)
            if num - 1 >= 0 and num - 1 < len(node.search_results):
                url = node.search_results[num - 1].url
                return f'[{num}]({url})'
            else:
                return ''
        
        for patterns in reference_patterns:
            output = re.sub(patterns, replace_func, output)
        return output
    
    def get_domain(self, url: str) -> str:
        parsed_url = urlparse(url)
        domain_with_port = parsed_url.netloc
        domain = domain_with_port.split(':')[0]
        return domain
    
    def remove_empty_mermaid_blocks(self, markdown_text: str) -> str:
        pattern = re.compile(r'```mermaid\s*\n(.*?)\n?```', re.DOTALL)

        def replacer(match):
            content = match.group(1)
            if content.strip() == "":
                return ""
            else:
                return match.group(0)

        cleaned = pattern.sub(replacer, markdown_text)
        return cleaned
    
    def omit_markdown_block(self, markdown_text: str, pattern: str = r"```mermaid\s*(.*?)```") -> str:
        blocks = re.findall(pattern, markdown_text, re.S)
        if not blocks:
            return ""
        return f"```mermaid\n{blocks[-1]}```"
    
    def format_invalid_citation(self,
                                output: str,
                                reference_patterns: list[str] = [r'【citation:(\s+)】']) -> str:
        for patterns in reference_patterns:
            output = re.sub(patterns, r'[citation:\1]', output)

        output = re.sub(r'【citation:[^】]*】', '', output)
        return output

    @staticmethod
    def format_citation(
        content: str) -> str:
        # 先处理[citation:44, citation:45]等重复citation关键字的合并引用
        # 可以兼容[ citation: 44] [ ciation: 44 , citation:45 ] 前后出现空格的情况
        def split_multi_citation(match):
            nums = re.findall(r'citation:\s*(\d+)', match.group(0))
            return ''.join([f'[citation:{num}]' for num in nums])
        multi_citation_pattern = r'(\[\s*citation:\s*\d+[，,\s]*citation:\s*\d+(?:[，,\s]*citation:\d+)*\s*\])'
        content = re.sub(multi_citation_pattern, split_multi_citation, content)

        # 再处理[citation:44, 45]等合并引用
        # 可以支持[ citation: 44,45 ] 等情况
        def split_citation_group(match):
            nums_str = match.group(1)
            nums = re.split(r'[，,\s]+', nums_str)
            result = ''
            for num in nums:
                num = num.strip()
                if not num.isdigit():
                    continue
                result += f'[citation:{num}]'
            return result
        group_pattern = r'\[\s*citation:\s*([0-9,\s，]+)\s*\]'
        content = re.sub(group_pattern, split_citation_group, content)

        # 处理各种非英语符号引入的错误
        invalid_citation_pattern = [
            # Chinese
            r'【citation:(\d+)】',
            r'【citation:(\d+)\]',
            r'\[citation:(\d+)】',
            r'\[引用:(\d+)\]']
        for patterns in invalid_citation_pattern:
            content = re.sub(patterns, r'[citation:\1]', content)
        
        return content
    
    @staticmethod
    def convert_citation(
        url_list: list[dict],
        content: str) -> str:

        # 统一替换
        url_pattern = r'\[citation:(\d+)\]'
        def replace_func(match):
            idx = int(match.group(1))
            url = ''
            for link in url_list:
                if link['id'] == idx:
                    url = link.get('url', '')
            if url == '':
                return ''
            url = url.replace("(", "%28").replace(")", "%29")
            return f'[{idx}]({url})'
        content = re.sub(url_pattern, replace_func, content)
        
        return content

    @staticmethod
    def remove_unused_citation(
        url_list: List[dict],
        content: str) -> tuple[str, List[dict]]:

        # 创建 id 到 url 的映射，提高查找效率
        url_dict = {link['id']: link.get('url', '') for link in url_list}
        
        id_map = {}
        new_id_counter = 1
        
        # replace [citation:1] -> [1](https://www.health.com/xx.html)
        url_pattern = r'\[citation:(\d+)\]'
        def replace_func(match):
            nonlocal new_id_counter
            idx = int(match.group(1))
            
            # check citation id existed
            url = url_dict.get(idx, '')
            if url == '':
                return '' # remove invalid citationd
            
            # start from 1
            if idx not in id_map:
                id_map[idx] = new_id_counter
                new_id_counter += 1
            
            url = url.replace("(", "%28").replace(")", "%29")
            return f'[{id_map[idx]}]({url})'
        
        content = re.sub(url_pattern, replace_func, content)
        
        # remove unused reference
        nurl_list = [link for link in url_list if link['id'] in id_map]
        for link in nurl_list:
            link['id'] = id_map[link['id']]
        nurl_list.sort(key=lambda x: x['id'])

        return content, nurl_list

    def create_candlestick_chart(
        self,
        data: List[dict], 
        symbol: str,
        width: int = 800):
        """Create candlestick chart"""
        data_count = len(data)
        if data_count <= 10:
            padding = 0.3
        elif data_count <= 20:
            padding = 0.2
        else:
            padding = 0.1
        return {
            "$schema": "https://vega.github.io/schema/vega/v5.json",
            "width": width,
            "height": 400,
            "padding": {"left": 50, "top": 30, "right": 30, "bottom": 50},
            "title": {
                "text": f"{symbol}",
                "fontSize": 16,
                "anchor": "middle"
            },
            "data": [
                {
                    "name": "stock_data",
                    "values": data,
                    "transform": [
                        {
                            "type": "formula",
                            "expr": "datum.open <= datum.close",
                            "as": "up"
                        }
                    ]
                }
            ],
            "scales": [
                {
                    "name": "x",
                    "type": "band",
                    "range": "width",
                    "domain": {"data": "stock_data", "field": "date"},
                    "padding": padding
                },
                {
                    "name": "y",
                    "type": "linear",
                    "range": "height",
                    "nice": True,
                    "zero": False,
                    "domain": {
                        "data": "stock_data",
                        "fields": ["low", "high"]
                    }
                },
                {
                    "name": "color",
                    "type": "ordinal",
                    "range": ["#ae1325", "#06982d"],
                    "domain": [False, True]
                }
            ],
            "axes": [
                {
                    "orient": "bottom",
                    "scale": "x",
                    "title": "Date",
                    "labelAngle": -45,
                    "labelAlign": "right"
                },
                {
                    "orient": "left",
                    "scale": "y",
                    "title": "Price ($)"
                }
            ],
            "marks": [
                {
                    "type": "rule",
                    "from": {"data": "stock_data"},
                    "encode": {
                        "enter": {
                            "x": {"scale": "x", "field": "date", "band": 0.5},
                            "y": {"scale": "y", "field": "low"},
                            "y2": {"scale": "y", "field": "high"},
                            "stroke": {"scale": "color", "field": "up"},
                            "strokeWidth": {"value": 1}
                        }
                    }
                },
                {
                    "type": "rect",
                    "from": {"data": "stock_data"},
                    "encode": {
                        "enter": {
                            "x": {"scale": "x", "field": "date"},
                            "width": {"scale": "x", "band": 1},
                            "y": {"scale": "y", "signal": "min(datum.open, datum.close)"},
                            "y2": {"scale": "y", "signal": "max(datum.open, datum.close)"},
                            "fill": {"scale": "color", "field": "up"},
                            "stroke": {"scale": "color", "field": "up"},
                            "strokeWidth": {"value": 1}
                        },
                        "update": {
                            "fillOpacity": {"value": 0.8}
                        },
                        "hover": {
                            "fillOpacity": {"value": 1},
                            "tooltip": {
                                "signal": "{'Date': datum.date, 'Open': datum.open, 'High': datum.high, 'Low': datum.low, 'Close': datum.close}"
                            }
                        }
                    }
                }
            ]
        }

