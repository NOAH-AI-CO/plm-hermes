"""
简单的Coder智能体 - 可插拔设计
包含代码生成、执行、文件管理和审查功能
"""
import time
import json
import logging
from typing import List, Dict, Any, Optional
import base64, binascii
import re
import asyncio

from aiohttp.http_parser import ChunkState
from pydantic import Field
from pydantic_core.core_schema import NoneSchema
from sqlalchemy.engine import ChunkedIteratorResult
from agent.core.preset import AgentPreset
from agent.explore.schema import (
    MindSearchResponse, SearchNode, SearchType, 
    ProcessingType, WebSearchSubject
)
from agent.explore.helper import MindSearchHelper
from llm.azure_models import GPT4o, GPTo4Mini
from llm.base_model import BaseLLM


from utils.core.standardize import standardize_yield_wo_dump
from tools.coder.simple_code_tools import (
    CodeGeneration, CodeExecution, FileManagement, 
    CodeReview, Finished
)
import agent.explore.constants as constants


logger = logging.getLogger(__name__)


class CoderAgent(AgentPreset):
    """
    Coder智能体
    重要特性：
    1. 可插拔工具设计 - 可以选择性启用功能
    2. 安全的工作环境 - 限制在指定目录内操作
    3. 实时进度跟踪 - 通过search_node显示状态
    4. 智能代码处理 - 结合LLM和静态分析
    """
    
    # 基础配置
    llm: BaseLLM = GPTo4Mini
    # TODO 放进prompt文件中
    sys_prompt: str = """
    你是资深的软件工程师，通过编写代码解决用户的问题。你精通Python语言。

    工具列表:
    {tool_prompt}

    用户需求: {user_prompt}

    # 技能列表
    ## 代码编写与执行
    1. 深度解析用户的编程需求，明确目标、限制及预期输出。
    2. 确保代码简洁、高效且易于理解。

    ### python代码编写要求
    1. 使用 print(...) 输出关键结果与重要中间值。
    2. 处理可能的边缘情况和错误，使用 CodeExecution 工具执行代码并验证结果。
    3. 数学运算：数学运算必须用 Python 原生语法。
    4. 金融数据获取：金融数据获取仅限 yfinance 库：
        - 通过 yf.download() 获取历史数据。
        - 使用 Ticker 对象访问公司信息。
        - 合理设置日期范围检索数据。
    5. 可调用库：可调用预安装库：pandas（数据处理）、numpy（数值计算）、matplotlib (图表数据处理)。
    6. 注释要求：使用注释增强代码的可读性。
    7. 禁用：禁止生成代码时使用没有安装的依赖库，禁止安装依赖库。
    6. 如果有计算结果，必须用print展示最终答案
    7. **重要：代码必须直接执行，不要使用 if __name__ == "__main__" 条件**
    8. **重要：所有代码都应该在模块级别直接执行，确保print语句会被调用**
    9. 请以{ui_language}回答

    重要提醒：
        - 只生成纯代码，不要包含任何解释文字
        - 不要包含markdown格式或代码块标记

    ## 代码原理解释
    解释代码的工作原理和实现思路，帮助用户理解代码逻辑。

    ## 代码调试优化
    帮助用户调试和优化代码，提升代码质量和性能。
    """

    tool_choice: str = "auto"

    field_display_config: dict = Field(
        default={
            "task_description": {
                "prefix": "\n\n**Task Analysis:**\n",
                "suffix": "\n",
            },
            "code": {
                "prefix": "\n\n### Code Generation...\n```python\n",
                "suffix": "\n```\n"
            }
        },
        description="字段显示配置，控制前缀后缀"
    )
    
    work_dir: str = Field(default="./coder_workspace", description="工作目录路径")
    sandbox_url: str = Field(default="http://0.0.0.0:8194", description="沙箱服务地址")
    use_sandbox: bool = Field(default=True, description="是否使用沙箱模式")
    enable_file_management: bool = Field(default=True, description="是否启用文件管理功能")
    enable_code_review: bool = Field(default=True, description="是否启用代码审查功能")
    tool_config: dict = Field(default_factory=dict, description="工具配置字典")
    tool_prompt: str = Field(default="", description="工具提示词描述")
    tools_list: list = Field(default=[], description="工具列表")
    
    helper: MindSearchHelper = Field(default_factory=MindSearchHelper)
    
    def __init__(self, work_dir: str = "./coder_workspace", enable_file_management: bool = True,
                 enable_code_review: bool = True, sandbox_url: str = "http://0.0.0.0:8194",
                 use_sandbox: bool = True, **kwargs):
        """
        初始化Coder智能体

        Args:
            work_dir: 本地工作目录路径（沙箱模式下作为备选）
            enable_file_management: 是否启用文件管理功能
            enable_code_review: 是否启用代码审查功能
            sandbox_url: 沙箱服务地址
            use_sandbox: 是否使用沙箱模式
        """
        from utils.core.get_tool_schema import get_openai_input_schema_v3
        super().__init__(
            work_dir=work_dir,
            enable_file_management=enable_file_management,
            enable_code_review=enable_code_review,
            sandbox_url=sandbox_url,
            use_sandbox=use_sandbox,
            tool_config={
                'work_dir': work_dir,
                'sandbox_url': sandbox_url,
                'use_sandbox': use_sandbox
            },
            **kwargs
        )

        # 根据参数动态配置工具列表
        self.tools = [CodeExecution]
        self.tools_list = [get_openai_input_schema_v3(CodeExecution())]

        # 文件系统
        if self.enable_file_management:
            self.tools.insert(-1, FileManagement)

        # 代码审查
        if self.enable_code_review:
            self.tools.insert(-1, CodeReview)

        tool_prompt_dict = {
            "CodeGeneration": "- CodeGeneration（代码生成）代码：依据需求生成符合行业最佳实践的高质量代码，确保逻辑清晰、可读性强、可直接执行。输出格式必须是python字符串格式，不要包含任何其他内容",
            "CodeExecution": "- CodeExecution:**生成代码后，必须立即使用 CodeExecution 工具执行**，并通过 print 输出完整执行结果（包括输入数据、执行过程、输出结果 / 报错信息）。\n 若代码执行成功：输出 '执行成功' + 具体结果\n若代码执行失败：输出 '执行失败' + 完整报错信息（不得省略）",
            "FileManagement": "- FileManagement:协助进行项目文件的规范化管理与组织",
            "CodeReview": "- CodeReview:从安全性、效率及规范性角度审查质量",
            "Finished": "- 标记完成"
        }
        self.tool_prompt = ""
        for tool_class in self.tools:
            tool_instance = tool_class()
            self.tool_prompt += tool_prompt_dict.get(tool_instance.name, "")
            self.tool_prompt += "\n"

        # 为工具传递沙箱配置
        self.tool_config = {
            'work_dir': self.work_dir,
            'sandbox_url': self.sandbox_url,
            'use_sandbox': self.use_sandbox
        }

        if 'field_display_config' in kwargs:
            self.field_display_config.update(kwargs['field_display_config'])

    def _decode_b64_safe(self, s: str) -> str:
        try:
            return base64.b64decode(s, validate=False).decode('utf-8', errors='replace')
        except (binascii.Error, UnicodeDecodeError):
            return ""

    def _return_exec_result(self, result: dict, ui_language: str) -> str:
        """代码执行结果处理"""
        result = result.get("result", {})
        if ui_language == constants.CHINESE:
            if result.get("error"):
                return f"## 代码执行失败，原因：{result.get('error')}"
            else:
                data = result.get("sandbox_response", {}).get("data", {})
                return "## 代码执行成功: \n```\n" + data.get("stdout", "") + "\n```" if data.get('stdout') else "## 代码执行失败，原因：\n" + "```cmd" + data.get("error", "代码执行结果失败...") + "\n```"
        else:
            if result.get("error"):
                return f"## Code execution failed, reason: {result.get('error')}"
            else:
                data = result.get("sandbox_response", {}).get("data", {})
                return "## Code execution successful: \n```\n" + data.get("stdout", "") + "\n```" if data.get('stdout') else "## Code execution failed, reason: \n" + "```cmd" + data.get("error", "Code execution failed...") + "\n```"

    async def parse_stream_output_precise_debug(self, chunk):
        """
        全量流式返回：每次返回完整的格式化字符串
        """      
        chunk_type = chunk.get("type")
        
        if chunk_type == "chat":
            content = chunk.get("content", "")
            if content:
                return content
            return ""
            
        elif chunk_type == "tool":
            arguments_str = chunk.get("arguments", "")
            
            if arguments_str and isinstance(arguments_str, str):
                output_parts = []
                
                def extract_field(field_name):
                    """提取指定字段并添加配置的前缀后缀"""
                    if field_name not in self.field_display_config:
                        return ""
                    
                    config = self.field_display_config[field_name]
                    
                    # 使用正则表达式提取字段值
                    pattern = f'"{field_name}"\\s*:\\s*"([^"\\\\]*(?:\\\\.[^"\\\\]*)*)"'
                    pattern = f'"{field_name}"\\s*:\\s*"([^"\\\\]*(?:\\\\.[^"\\\\]*)*)'
                    match = re.search(pattern, arguments_str)
                    if match:
                        content = match.group(1).replace('\\"', '"').replace('\\n', '\n')
                        return f"{config['prefix']}{content}{config['suffix']}"
                    else:
                        # print(f"🔍 正则表达式未匹配到字段")
                        pass
                    return ""
                
                for field_name in self.field_display_config:
                    field_output = extract_field(field_name)
                    if field_output:
                        output_parts.append(field_output)
                    else:
                        pass
                        # print(f"⚠️ 字段 {field_name} 提取失败")
                
                result = "".join(output_parts)
                return result
                
            elif arguments_str and isinstance(arguments_str, dict):
                if chunk.get("is_end", False):
                    return chunk
                else:
                    return chunk
            else:
                # print(f"arguments 不是字符串或为空: {arguments_str}")
                # print(type(arguments_str))
                return ""
        
        return ""

    @standardize_yield_wo_dump
    async def start_wo_dump(self, *args, **kwargs):
        async for chunk in self.use_tool(*args, **kwargs):
            yield chunk

    def update_response_search_node_summary(self, response: MindSearchResponse, summary: str):
        """
        更新响应的search_node的summary
        """
        response.search_graph.children[-1].summary = summary
        return response

    def update_response_search_node_search_results(self, response: MindSearchResponse, search_results: List[dict]):
        """
        更新响应的search_node的search_results
        """
        response.search_graph.children[-1].search_results = search_results
        response.search_graph.children[-1].processing_type = ProcessingType.DONE
        return response
    
    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], **kwargs):
        """
        重写use_tool方法，实现Coder特定的逻辑和search_node管理，包含重试机制
        """        
        from utils.human_in_loop.helpers import stream_function_call_with_retry
        response = kwargs.get('code_response', None)
        response_content = str()
        ui_language = kwargs.get('ui_language', constants.CHINESE)  # 界面语言
        if not response:
            response = self._init_coder_response(user_prompt, ui_language)
            yield response
        
        self._add_thinking_node(response, user_prompt, ui_language)
        response = self.update_response_search_node_summary(response, "### 代码准备中... \n\n" if ui_language == constants.CHINESE else "### Code preparation... \n\n")
        yield response
        
        # 重试机制
        max_retries = 5
        current_retry = 0
        failure_reasons = []
        
        while current_retry < max_retries:
            try:
                
                # 构建当前的重试提示词
                current_prompt = self._build_retry_prompt(user_prompt, failure_reasons, current_retry)

                allowed_keys = {'language', 'images', 'temperature', 'max_tokens', 'json_mode', 'history_messages'}
                filtered_kwargs = {k: v for k, v in kwargs.items() if k in allowed_keys}

                prompt = self.sys_prompt.format(tool_prompt=self.tool_prompt, user_prompt=current_prompt, ui_language=ui_language)

                code_generated = False
                code_executed = False
                
                async for chunk in stream_function_call_with_retry(self.llm().stream_call_origin, sys_prompt=prompt, user_prompt=current_prompt, history_messages=history_messages, tools=self.tools_list, **filtered_kwargs):

                    parsed_content = await self.parse_stream_output_precise_debug(chunk)
                    
                    if parsed_content:
                        if isinstance(parsed_content, str):
                            response_content = parsed_content
                            response.content = response_content
                            response = self.update_response_search_node_summary(response, response_content)
                            response.processing_type = ProcessingType.PROCESSING
                            yield response
                        elif isinstance(parsed_content, dict):
                            tool_name = parsed_content.get('name', '')
                            language = parsed_content.get("arguments", {}).get('language', 'python')
                   
                            # 执行工具
                            try:
                                tool_class = None
                                for tool in self.tools:
                                    if tool.__name__ == tool_name:
                                        tool_class = tool
                                        break
                                
                                if tool_class:
                                    # 标记代码生成成功（LLM返回了代码）
                                    if tool_name == "CodeExecution" and parsed_content.get("arguments", {}).get("code", ""):
                                        code_generated = True

                                    async for tool_response in tool_class(agent=self).run(**parsed_content.get("arguments")):
                                        tool_result = self._return_exec_result(tool_response, ui_language)
                                        response = self.update_response_search_node_search_results(response, [{"function": tool_name, "result": tool_result}])
                                        response_content += tool_result + "\n"
                                        response.content = response_content
                                        response = self.update_response_search_node_summary(response, response_content)
                                        response.processing_type = ProcessingType.PROCESSING
                                        yield response
                                        
                                        # 检查代码执行结果
                                        if tool_name == "CodeExecution":
                                            if "代码执行成功" in tool_result or "Code execution successful" in tool_result:
                                                code_executed = True
                                            elif "代码执行失败" in tool_result or "Code execution failed" in tool_result:
                                                failure_reason = self._extract_failure_reason(tool_result)
                                                failure_reasons.append(failure_reason)
                                else:
                                    print(f"⚠️ 未找到工具: {tool_name}")
                                    
                            except Exception as e:
                                error_msg = f"工具执行失败: {str(e)}"
                                print(f"❌ {error_msg}")
                                response_content += error_msg + "\n"
                                response.content = response_content
                                response = self.update_response_search_node_summary(response, response_content)
                                
                                yield response
                                
                                # 记录失败原因
                                failure_reasons.append(f"工具 {tool_name} 执行失败: {str(e)}")

                # 检查是否成功
                if code_generated and code_executed:
                    print("✅ 代码生成和执行成功，无需重试")
                    break
                else:
                    if not code_generated:
                        failure_reasons.append("代码生成失败：LLM没有生成可执行的代码")
                    if not code_executed:
                        if not failure_reasons:  # 如果没有具体的执行失败原因
                            failure_reasons.append("代码执行失败：代码执行过程中出现未知错误")
                    
                    current_retry += 1
                    if current_retry < max_retries:
                        print(f"⚠️ 第 {current_retry} 次尝试失败，准备重试...")
                        print(f"📝 失败原因: {failure_reasons[-1]}")
                        await asyncio.sleep(1)
                    else:
                        print(f"❌ 已达到最大重试次数 ({max_retries})，停止重试")
                        
            except Exception as e:
                error_msg = f"LLM调用失败: {str(e)}"
                print(f"❌ {error_msg}")
                failure_reasons.append(error_msg)
                current_retry += 1
                
                if current_retry < max_retries:
                    print(f"⚠️ 准备重试...")
                    await asyncio.sleep(1)
                else:
                    print(f"❌ 已达到最大重试次数，停止重试")
                    break

        if current_retry >= max_retries:
            response.content += f"\n\n⚠️ 经过 {max_retries} 次尝试后仍然失败。失败原因：\n" + "\n".join(failure_reasons) if ui_language == constants.CHINESE else f"\n\n⚠️ After {max_retries} attempts, it still failed. Failure reasons: \n" + "\n".join(failure_reasons)
            response = self.update_response_search_node_summary(response, response.content)

        
        response.processing_type = ProcessingType.DONE
        yield response

    def _init_coder_response(self, user_prompt: str, language: str) -> MindSearchResponse:
        """初始化Coder响应"""
        
        def get_thought_process(lang: str) -> str:
            if lang == constants.CHINESE:
                return "代码助手正在分析您的需求..."
            else:
                return "Code assistant is analyzing your requirements..."

        # 创建根节点
        root_node = SearchNode(
            search_type=SearchType.ASSISTANT,
            query=user_prompt,
            thought_process=get_thought_process(language),
            processing_type=ProcessingType.PROCESSING
        )

        response = MindSearchResponse(
            processing_type=ProcessingType.PROCESSING,
            search_graph=root_node,
            content="",
            role="assistant"
        )
        
        return response
    
    def _add_thinking_node(self, response: MindSearchResponse, query: str, language: str) -> SearchNode:
        """添加思考节点"""
        
        if response.search_graph.children[-1].search_type == SearchType.CODEEXECUTION:
            return 
        
        def get_thinking_text(lang: str) -> str:
            if lang == constants.CHINESE:
                return "正在分析代码需求..."
            else:
                return "Analyzing code requirements..."

        thinking_node = SearchNode(
            # search_type=SearchType.CODEEXECUTION,
            search_type=SearchType.UNKNOWN,
            subject=WebSearchSubject.UNKNOWN,
            query=get_thinking_text(language),
            summary="",
            processing_type=ProcessingType.THINKING
        )
        
        response.search_graph.add_child(thinking_node)
        return thinking_node
    
    def _add_tool_node(self, response: MindSearchResponse, tool_name: str) -> SearchNode:
        """为工具调用创建节点"""
        
        # 工具类型映射
        tool_type_map = {
            'CodeGeneration': SearchType.CODEGENERATION,
            'CodeExecution': SearchType.CODEEXECUTION,
            'FileManagement': SearchType.FILEMANAGEMENT,
            'CodeReview': SearchType.CODEREVIEW,
            'Finished': SearchType.ASSISTANT
        }
        
        tool_node = SearchNode(
            search_type=tool_type_map.get(tool_name, SearchType.UNKNOWN),
            subject=WebSearchSubject.CODE,
            query=f"执行 {tool_name}",
            processing_type=ProcessingType.PROCESSING
        )
        
        response.search_graph.add_child(tool_node)
        return tool_node
    
    def _update_node_from_tool_call(self, node: SearchNode, tool_name):
        """从工具调用更新节点信息"""
        try:
            
            # 根据工具类型设置查询
            if tool_name == 'CodeGeneration':
                node.query =  '生成代码'
            elif tool_name == 'CodeExecution':
                node.query = '执行代码'
            elif tool_name == 'FileManagement':
                node.query = f"文件操作"
            elif tool_name == 'CodeReview':
                node.query = '代码审查'

        except Exception as exc:
            print(f"更新节点信息失败: {exc}")
    
    async def _record_operation(self, result: dict, context: dict):
        """
        记录操作到上下文
        重要：跟踪所有操作历史
        """
        function_name = result.get('function', '')
        context['operations'].append({
            'function': function_name,
            'timestamp': time.time(),
            'result': result
        })
        
        # 按类型分类记录
        if function_name == 'CodeGeneration':
            context['code_generated'].append(result)
        elif function_name == 'CodeExecution':
            context['executions'].append(result)
        elif function_name == 'FileManagement':
            if result.get('params', {}).get('operation') in ['create', 'write']:
                context['files_created'].append(result)
        elif function_name == 'CodeReview':
            context['reviews'].append(result)
    
    def _format_operation_summary(self, result: dict, language: str) -> str:
        """
        格式化操作结果摘要
        重要：为用户提供清晰的操作反馈
        """
        function_name = result.get('function', '')
        
        if function_name == 'CodeGeneration':
            task_desc = result.get('task_description', '缺失任务描述')
            gen_result = result.get('result', "生成代码失败")
            
            return f"任务: {task_desc}\n执行结果: {gen_result}"
        
        elif function_name == 'CodeExecution':
            exec_result = result.get('result', {})
            if language == 'zh-CN':
                return f"代码执行成功: " + exec_result
            else:
                return f"Code execution Success: " + exec_result

        elif function_name == 'FileManagement':
            operation = result.get('params', {}).get('operation', '')
            if language == 'zh-CN':
                return f"文件{operation}操作完成"
            else:
                return f"File {operation} operation completed"

        elif function_name == 'CodeReview':
            review_result = result.get('review_result', {})
            issues = review_result.get('issues_count', 0)
            if language == 'zh-CN':
                return f"代码审查完成，发现 {issues} 个问题"
            else:
                return f"Code review completed, found {issues} issues"

        return "操作完成" if language == 'zh-CN' else "Operation completed"
    
    def _add_summary_node(self, response: MindSearchResponse, context: dict, language: str) -> SearchNode:
        """
        添加会话总结节点
        重要：为用户提供完整的操作总结
        """
        def get_summary_query(lang: str) -> str:
            queries = {
                'zh-CN': '生成代码会话总结...',
                'en-US': 'Generating code session summary...',
                'ja-JP': 'コードセッションサマリーを生成中...'
            }
            return queries.get(lang, queries['en-US'])
        
        # 生成总结内容
        summary_content = self._generate_session_summary(context, language)
        
        summary_node = SearchNode(
            search_type=SearchType.ASSISTANT,
            query=get_summary_query(language),
            summary=summary_content,
            processing_type=ProcessingType.DONE
        )
        
        response.search_graph.add_child(summary_node)
        return summary_node
    
    def _generate_session_summary(self, context: dict, language: str) -> str:
        """
        生成会话总结内容
        重要：提供有价值的操作统计
        """
        total_ops = len(context['operations'])
        code_generated = len(context['code_generated'])
        executions = len(context['executions'])
        files_created = len(context['files_created'])
        reviews = len(context['reviews'])
        
        sandbox_status = "=沙箱模式" if context['use_sandbox'] else "本地模式"
        sandbox_status_en = "Sandbox Mode" if context['use_sandbox'] else "Local Mode"

        if language == 'zh-CN':
            summary = f"""
            代码会话总结：
                总操作数: {total_ops}
                代码生成: {code_generated} 次
                代码执行: {executions} 次
                文件创建: {files_created} 个
                代码审查: {reviews} 次
                {sandbox_status}: {context['sandbox_url'] if context['use_sandbox'] else context['work_dir']}
                主要语言: {context['language']}
            """
        else:
            summary = f"""
            Code Session Summary:
                Total operations: {total_ops}
                Code generations: {code_generated}
                Code executions: {executions}
                Files created: {files_created}
                Code reviews: {reviews}
                {sandbox_status_en}: {context['sandbox_url'] if context['use_sandbox'] else context['work_dir']}
                Primary language: {context['language']}
            """

        return summary

    def _extract_failure_reason(self, tool_result: str) -> str:
        """
        从 _return_exec_result 的返回结果中提取失败原因
        """
        if "代码执行失败" in tool_result:
            error_start = tool_result.find("原因：")
            if error_start != -1:
                error_info = tool_result[error_start + 3:].strip()
                error_info = error_info.replace("```cmd", "").replace("```", "").strip()
                return f"代码执行失败：{error_info}"
        return tool_result

    def _build_retry_prompt(self, original_prompt: str, failure_reasons: List[str], current_retry: int) -> str:
        """
        构建重试提示词，包含之前的失败信息
        """
        if not failure_reasons:
            return original_prompt
        
        retry_prompt = f"{original_prompt}\n\n"
        retry_prompt += f"⚠️ 这是第 {current_retry + 1} 次尝试。之前的尝试失败原因：\n"
        
        for i, reason in enumerate(failure_reasons, 1):
            retry_prompt += f"{i}. {reason}\n"
        
        retry_prompt += f"\n请根据以上失败原因，改进你的解决方案：\n"
        retry_prompt += f"1. 仔细分析失败原因\n"    
        retry_prompt += f"2. 确保代码语法正确\n"
        retry_prompt += f"3. 确保代码逻辑完整且可执行\n"
        retry_prompt += f"4. 如果之前有代码执行错误，请修复这些问题\n"
        retry_prompt += f"\n请生成一个简单、正确、可执行的Python代码来解决用户的问题。"
        
        return retry_prompt
