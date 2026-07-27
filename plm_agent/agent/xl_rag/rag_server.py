from datetime import datetime
import re
import requests
import json
import os

from agent.core.preset import AgentPreset
from agent.explore.schema import MindSearchResponse, ProcessingType, SearchNode, SearchType
from agent.explore.helper import MindSearchHelper
from utils.oss_client import oss_singleton_client
from utils.crypt import encrypt_string


class XLRagServer(AgentPreset):

    mindsearch_helper: MindSearchHelper = MindSearchHelper()
    response: MindSearchResponse = None
    url: str = "http://rag_api_service:5003/api/v1/query_stream"
    headers: dict = {"Content-Type": "application/json"}
    data: dict = {"query": "如何确定关键的临床问题？"}
    cdn_base_url: str = "https://public.ruosheng.bio/"

    def __init__(self, url: str = None, headers: dict = None, data: dict = None, **kwargs):
        super().__init__(**kwargs)
        if url: object.__setattr__(self, "url", url)
        if headers: object.__setattr__(self, "headers", headers)
        if data: object.__setattr__(self, "data", data)

    async def extract_json_from_sse(self, query: str):
        """
        生成器版流式解析：逐块yield JSON字典，外部可迭代处理
        :param query: 用户查询语句
        :yield: 单个解析后的JSON字典
        """
        url = "http://rag_api_service:5003/api/v1/query_stream"
        # url = "http://localhost:5003/api/v1/query_stream"
        headers = {"Content-Type": "application/json"}
        data = {"query": query}

        try:
            response = requests.post(url, headers=headers, json=data, stream=True)
            response.raise_for_status()

            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue

                json_str = line.replace("data: ", "", 1)
                try:
                    json_dict = json.loads(json_str)
                    yield json_dict  # 逐块返回，不中断流式接收
                except json.JSONDecodeError:
                    yield {}

        except requests.exceptions.RequestException as e:
            print(f"请求失败：{e}")
            yield {}
    
    def append_search_graph(self, root: SearchNode, subtitle: str) -> SearchNode:
        child = SearchNode(search_type=SearchType.UNKNOWN,
                    query=subtitle,
                    key_word="",
                    processing_type=ProcessingType.PROCESSING
                    )
        root.children.append(child)
        # 这是工具里面的第一个工具最上面哪行字
        root.thought_process = f"开始执行"
        return root
    
    def update_search_graph(self, root: SearchNode, subtitle: str, summary: str, search_results: list) -> SearchNode:
        for child in root.children:
            if child.query == subtitle:
                child.summary = summary
                child.search_results = search_results
                child.processing_type = ProcessingType.DONE
                return child
        return None

    def init_search_graph(self, user_prompt: str):
        return SearchNode(search_type=SearchType.UNKNOWN,
                    query=user_prompt,
                    key_word="",
                    processing_type=ProcessingType.PROCESSING
                    )

    def update_response_search_node_search_results(self, response: MindSearchResponse, search_results: list[dict]):
        """
        更新响应的search_node的search_results
        """
        response.search_graph.children[-1].search_results = search_results
        response.search_graph.children[-1].processing_type = ProcessingType.DONE
        return response

    def replace_title(self, title: str) -> str:
        return title.split("/")[-1].replace(".txt", ".mp4")

    def replace_url(self, url: str, page: str = "") -> str:
        """
        相对路径替换成oss路径，三个路径（pdf，word和video）
        video路径需要特殊处理，txt->mp4
        url：video_audio_to_txt/Q3/F-5.前瞻性队列研究顶刊发表/第三节：眼科研究案例—如何描述预测因子或Biomarker.txt
        """
        type_map = {
            "pdf": "kybk/KnowledgeBase/数据中间处理结果/PDF/",
            "word": "kybk/KnowledgeBase/数据中间处理结果/Word/",
            "video_audio_to_txt": "kybk/KnowledgeBase/【Final】/",
        }

        if not url:
            return url

        url = url.lstrip("/")  # 去掉开头多余的斜杠，防止出现双斜杠

        parts = url.split("/")
        if len(parts) < 2:
            # 格式不对，直接返回原始 url 或按需处理
            return url

        type_, url_path = parts[0], parts[1:]
        if type_ not in type_map:
            # 未知类型，直接拼在 base_url 后或返回原始 url
            return self.cdn_base_url + "/".join(url_path)

        if type_ == "video_audio_to_txt":
            return self.cdn_base_url + type_map[type_] + "/".join(url_path).replace(".txt", ".mp4")
        else:
            return self.cdn_base_url + type_map[type_] + "/".join(url_path) + (f"#page={page}" if page else "")

    def encrypt_url(self, url: str) -> str:
        """
        加密url，并返回一个包含 Nonce, Tag, 和 Ciphertext 的单一十六进制字符串。
        添加view_source url的前缀
        """
        view_source_url = ""
        # TODO view_source_url要配进配置文件，目前配置文件+环境变量还未完善，先写死
        # 可以写成一个函数，根据环境变量返回 变量名，比如prod_view_source_url,test_view_source_url,dev_view_source_url
        # 配置文件配置好prod_view_source_url,test_view_source_url,dev_view_source_url三个变量
        match os.getenv("ENVIRONMENT"):
            case "test":
                view_source_url = "https://test.roche.noahai.co/view-source/"
            case "prod":
                view_source_url = "https://roche.noahai.co/view-source/"
            case _:
                view_source_url = "https://test.roche.noahai.co/view-source/"
        
        return view_source_url + encrypt_string(url)

    def save_html_to_oss(self, html_file_name: str, html_content: str) -> str:
        """
        保存html到oss
        """
        # 保存html到oss
        base_oss_path = "kybk/KnowledgeBase/数据中间处理结果/HTML/"
        oss_path = base_oss_path + html_file_name
        oss_singleton_client.upload_string(html_content, oss_path)
        return oss_path

    def replace_html_citation_links(self, html_content: str, reference_list: list[dict]) -> str:
        """
        替换 HTML 中所有以 /documents 开头的引用链接
        包括正文中的引用链接和引用来源部分的链接
        
        Args:
            html_content: HTML 字符串内容
            reference_list: 引用列表，每个元素包含 'url' 字段（已加密的 URL）
        
        Returns:
            替换后的 HTML 字符串
        """
        if not html_content or not reference_list:
            return html_content
        
        # 第一步：处理正文中的引用链接
        # 匹配模式：<a href="/documents/...">数字</a>（在 <sup> 标签内）
        pattern_body = r'(<a\s+href=["\'])(/documents/[^"\']+)(["\'][^>]*>)(\d+)(</a>)'
        
        def replace_body_match(match):
            citation_num = int(match.group(4))
            
            # 引用编号从1开始，列表索引从0开始
            if 1 <= citation_num <= len(reference_list):
                new_url = reference_list[citation_num - 1].get("url", "")
                
                if new_url:
                    quote_char = match.group(1)[-1]  # 获取引号字符
                    return f'{match.group(1)}{new_url}{quote_char}{match.group(3)}{match.group(4)}{match.group(5)}'
            
            return match.group(0)
        
        html_content = re.sub(pattern_body, replace_body_match, html_content)
        
        # 第二步：处理引用来源部分的链接
        # 匹配 <b>[数字]</b> 后面（中间可能有 <i> 标签）的 <a href="/documents/...">
        pattern_citations = r'(<b>\[(\d+)\]</b>\s*(?:<i[^>]*></i>)?<a\s+href=["\'])(/documents/[^"\']+)(["\'][^>]*>)'

        def replace_citations_match(match):
            citation_num = int(match.group(2))  # 从 [数字] 中提取的数字
            
            # 引用编号从1开始，列表索引从0开始
            if 1 <= citation_num <= len(reference_list):
                new_url = reference_list[citation_num - 1].get("url", "")
                
                if new_url:
                    return f'{match.group(1)}{new_url}{match.group(4)}'
            
            return match.group(0)

        html_content = re.sub(pattern_citations, replace_citations_match, html_content)
                
        return html_content
    
    def replace_html_display_text(self, html_content: str) -> str:
        """
        替换 HTML 中的显示文本
        - .txt → .mp4
        - 本地语料 → 本地知识库
        
        Args:
            html_content: HTML 字符串内容
        
        Returns:
            替换后的 HTML 字符串
        """
        if not html_content:
            return html_content
        
        # 替换 .txt 为 .mp4
        html_content = html_content.replace(".txt", ".mp4")
        
        # 替换 本地语料 为 本地知识库
        html_content = html_content.replace("本地语料", "本地知识库")
        
        return html_content


    def flatten_references(self, refs: dict) -> list[dict]:
        result = []
        # 处理 local：没有 title/url，用 source_file 填充
        for item in refs.get("local", []):
            new_item = dict(item)
            new_item["type"] = "local"
            sf = new_item.get("source_file", "")
            new_item["title"] = self.replace_title(sf)
            url = self.replace_url(sf, new_item.get('page', ""))
            new_item["url"] = self.encrypt_url(url)
            if url.endswith(".mp4"):
                new_item["cover"] = self.local_source_append_cover(url)
            else:
                new_item["cover"] = ""
            
            result.append(new_item)

        # 处理 external：已有 title/url，就补充 type
        for item in refs.get("external", []):
            new_item = dict(item)
            new_item["type"] = "external"
            # 如果缺 title/url，可按需要兜底
            if "title" not in new_item:
                new_item["title"] = new_item.get("url", "")
            if "url" not in new_item:
                new_item["url"] = ""
            result.append(new_item)

        return result

    def local_source_append_cover(self, url: str) -> str:
        """
        本地语料源添加封面
        """
        if not url:
            return ""
        
        cover = url.replace("/【Final】/", "/output_frames/")
        cover = cover.replace(".mp4", "_frame150.jpg")
        return cover
    

    async def use_tool(self, user_prompt: str = "", **kwargs):
        need_process_tool_names = ["本地知识检索", "执行网络搜索"]
        self.response = self.mindsearch_helper.init_response(self)
        yield self.response
        self.response.search_graph = self.init_search_graph(user_prompt)
        # yield self.response
        self.response.processing_type = ProcessingType.PROCESSING
        # yield self.response
        

        final_dict = dict()
        async for json_dict in self.extract_json_from_sse(user_prompt):
            # Tool result
            if json_dict.get("type") == "tool":
                if json_dict.get("status") == "running":
                    if json_dict.get("tool_name") in need_process_tool_names:
                        self.append_search_graph(self.response.search_graph, json_dict.get("tool_name"))
                        yield self.response 
                elif json_dict.get("status") == "done":
                    if json_dict.get("tool_name") in need_process_tool_names:
                        summary = json_dict.get("tool_name", "") + "执行完成"
                        search_results = json_dict.get("content")
                        if search_results:
                            have_title = any("title" in item for item in search_results)
                            if not have_title:
                                for con in search_results:
                                    con['title'] = con.get("source", "").split("/")[-1].replace(".txt", ".mp4")
                                
                        # search_results = [{"function": json_dict.get("tool_name"), "summary": summary, "result": json_dict.get("content")}]
                        self.update_search_graph(self.response.search_graph, json_dict.get("tool_name"), summary, search_results)
                        yield self.response 
                        
            # Message 
            elif json_dict.get("type") == "message":                
                content = json_dict.get("content", "")
                if content:
                    self.response.content = content
                    yield self.response

            # Final
            elif json_dict.get("code") == 0 and json_dict.get("message") == "Success":
                final_dict = json_dict.get("data", dict())
                # yield self.response

        # 处理最终结果
        summary_answer = final_dict.get("summary_answer", "")
        html_report_file_name = f"{user_prompt}_{datetime.now().strftime('%Y%m%d%H%M%S')}.html"
        html_report_content = final_dict.get("html_report_content", "")
        references_dict = final_dict.get("references", dict())
        # 合并local和search的reference
        reference_list = self.flatten_references(references_dict)
        
        # 替换reference_list  替换成阿里oss地址 
        # html里面的所有引用需要替换成阿里oss地址
        # 替换完成后，确认是否存在
        # 如果存在，加密URL
        encrypt_html_path = ""
        if html_report_content and reference_list:
            # 替换html中的链接
            html_report_content = self.replace_html_citation_links(html_report_content, reference_list)
            html_display_report_comtent = self.replace_html_display_text(html_report_content)
            html_path = self.save_html_to_oss(html_report_file_name, html_display_report_comtent)
            # 加密html path
            complete_html_path = self.cdn_base_url + html_path
            encrypt_html_path = self.encrypt_url(complete_html_path)
        self.response.search_graph.source = reference_list
        self.response.search_graph.processing_type = ProcessingType.DONE
        
        # 修复：更好的内容拼接
        if html_report_content:
            self.response.content = f"{summary_answer}\n\n下载链接：[点击查看报告]({encrypt_html_path})"
        else:
            self.response.content = summary_answer
        self.response.processing_type = ProcessingType.DONE
        yield self.response
        self.response.processing_type = ProcessingType.RESPONSEDONE
        yield self.response
            
            
        