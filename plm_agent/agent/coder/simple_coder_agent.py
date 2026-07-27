"""
简单的Coder智能体 - 可插拔设计
包含代码生成、执行、文件管理和审查功能
"""
import time
import json
import logging
from typing import List, Dict, Any, Optional

from pydantic import Field
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

logger = logging.getLogger(__name__)


class SimpleCoderAgent(AgentPreset):
    """
    简单的Coder智能体
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
    # 你是一位专业且严谨的代码助手，擅长通过规范流程为用户提供代码相关服务，具体包括：
    工具列表:
    {tool_prompt}

    ## 重要工作流程（必须严格按照此顺序执行）：

    ### 1. 解析用户需求
    用户需求: {user_prompt}

    ### 2. 代码生成阶段
    - 使用 CodeGeneration 工具生成代码
    - 生成的代码必须包含 print 语句来输出结果
    - 代码必须完整可执行

    ### 3. 代码执行阶段（必须执行）
    - 使用 CodeExecution 工具执行上一步生成的代码
    - 将 CodeGeneration 返回的代码作为 CodeExecution 的输入
    - 确保看到代码的实际执行结果

    ### 4. 完成标记
    - 使用 Finished 工具标记任务完成

    ## 强制要求：
    - 每次使用 CodeGeneration 后，必须立即使用 CodeExecution 执行生成的代码
    - 不允许跳过代码执行步骤
    - 必须看到代码的实际运行结果

    ## 示例工作流程：
    1. CodeGeneration: 生成计算斐波那契数的代码
    2. CodeExecution: 执行生成的代码，显示计算结果
    3. Finished: 标记任务完成
    """

    tool_choice: str = "auto"
    
    # 新增字段声明 - 重要：必须在类级别声明所有字段
    work_dir: str = Field(default="./coder_workspace", description="工作目录路径")
    sandbox_url: str = Field(default="http://0.0.0.0:8194", description="沙箱服务地址")
    use_sandbox: bool = Field(default=True, description="是否使用沙箱模式")
    enable_file_management: bool = Field(default=True, description="是否启用文件管理功能")
    enable_code_review: bool = Field(default=True, description="是否启用代码审查功能")
    tool_config: dict = Field(default_factory=dict, description="工具配置字典")
    tool_prompt: str = Field(default="", description="工具提示词描述")
    
    # 辅助组件
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
        # 重要：必须先调用父类初始化，传递所有参数
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

        # 重要：可插拔功能配置
        # 根据参数动态配置工具列表
        self.tools = [CodeGeneration, CodeExecution, Finished]  # 核心工具

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

    def _return_exec_result(self, result: dict) -> str:
        """代码执行结果处理"""
        result = result.get("result", {})
        if result.get("errors"):
            return "代码执行失败..."
        else:
            data = result.get("sandbox_response", {}).get("data", {})
            return "代码执行成功: \n" + data.get("stdout", "") if data.get('stdout') else "代码执行失败: \n" + data.get("error", "代码执行结果失败...")

    @standardize_yield_wo_dump
    async def start_wo_dump(self, *args, **kwargs):
        async for chunk in self.use_tool(*args, **kwargs):
            yield chunk
    
    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], **kwargs):
        """
        重写use_tool方法，实现Coder特定的逻辑和search_node管理
        
        重要流程：
        1. 初始化响应和search_graph
        2. 添加思考节点显示分析过程
        3. 执行工具调用并实时更新节点状态
        4. 生成会话总结
        """        

        # 1. 上下文
        code_context = {
            'work_dir': self.work_dir,
            'sandbox_url': self.sandbox_url,
            'use_sandbox': self.use_sandbox,
            'language': kwargs.get('language', 'python'),
            'operations': [],
            'files_created': [],
            'code_generated': [],
            'executions': [],
            'reviews': []
        }
        response_content = str()
        language = kwargs.get('ui_language', 'en-US')  # 界面语言
        
        # 2. 初始化响应和
        response = self._init_coder_response(user_prompt, language)
        yield response
        
        # 3. 添加思考节点
        self._add_thinking_node(response, user_prompt, language)
        yield response
        
        current_node = None
        
        # 过滤kwargs，只保留LLM支持的参数，避免work_dir等参数传递到LLM层
        allowed_keys = {'language', 'ui_language', 'images', 'temperature', 'max_tokens', 'json_mode', 'history_messages'}
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in allowed_keys}

        prompt = self.sys_prompt.format(tool_prompt=self.tool_prompt, user_prompt=user_prompt)

        async for chunk in super().use_tool(prompt, history_messages, **filtered_kwargs):
            
            # 5. 处理LLM的工具调用响应
            if hasattr(chunk, 'tool_calls') and chunk.tool_calls:

                need_auto_code_execution = False
                for tool_call in chunk.tool_calls:
                    if tool_call.function.name == "CodeGeneration":
                        need_auto_code_execution = True
                    if tool_call.function.name == "CodeExecution":
                        need_auto_code_execution = False
                    # 为每个工具调用创建专门的节点
                    current_node = self._add_tool_node(response, tool_call.function.name, language)
                    # 更新节点的初始信息
                    self._update_node_from_tool_call(current_node, tool_call, language)
            
            # 6. 处理工具执行结果
            elif isinstance(chunk, dict) and 'function' in chunk:

                # 更新当前节点的完成状态
                function_name = chunk.get('function', '')
                if response.search_graph and response.search_graph.children:
                    for child in response.search_graph.children:
                        if child.search_type == SearchType.UNKNOWN:
                            child.summary = child.query
                            response_content += child.summary + "\n"
                            response.content = response_content
                            yield response
                        if function_name == 'CodeGeneration' and child.search_type == SearchType.CODEGENERATION:
                            code_result = {
                                "type": "code_gen_result",
                                "function": function_name,
                                "content": chunk.get('result', {}),
                                "language": code_context.get("language")
                            }
                            child.search_results.append(code_result)
                            child.processing_type = ProcessingType.DONE
                            child.summary = self._format_operation_summary(chunk, language)
                            response_content += "```python \n"
                            response_content += chunk.get('result', {}) + "\n"
                            response_content += "``` \n"
                            response.content = response_content
                            yield response
                        elif function_name == 'CodeExecution' and child.search_type == SearchType.CODEEXECUTION:
                            exec_result = {
                                "type": "code_exec_result",
                                "function": function_name,
                                "content": chunk.get('result', {}),
                                "language": code_context.get("language")
                            }
                            child.search_results.append(exec_result)
                            child.processing_type = ProcessingType.DONE
                            child.summary = self._format_operation_summary(chunk, language)
                            code_result = self._return_exec_result(chunk.get('result', {}))
                            response_content += code_result + "\n"
                            response.content = response_content
                            yield response
                 # 记录操作到上下文
                        await self._record_operation(chunk, code_context)
                        

                # 处理 CodeGeneration 结果并自动补 CodeExecution
                if need_auto_code_execution and chunk.get('function') == 'CodeGeneration' and chunk.get('language') == "python":
                    generated_code = chunk.get('result', "")

                    exec_args = {
                        "code": generated_code,
                        "language": chunk.get('language', 'python')
                    }
                    code_execution_tool = CodeExecution(agent=self)
                    async for exec_result in code_execution_tool.run(**exec_args):
                        # 构造 CodeExecution 节点
                        exec_node = self._add_tool_node(response, "CodeExecution", language)
                        exec_node.query = "代码执行"
                        exec_node.processing_type = ProcessingType.DONE
                        exec_node.search_results.append({
                            "type": "code_result",
                            "function": "CodeExecution",
                            "content": exec_result,
                            "language": exec_args["language"]
                        })
                        code_result = self._return_exec_result(exec_result)
                        exec_node.summary = f"{code_result}"
                        response_content += exec_node.summary + "\n"
                        response.content = response_content

                        # 记录到上下文
                        code_context['executions'].append(exec_result)
                        code_context['operations'].append({
                            "function": "CodeExecution",
                            "params": exec_args,
                            "result": exec_result
                        })
                        temp_chunk = {
                            "function": "CodeExecution",
                            "params": exec_args,
                            "result": exec_result
                        }
                        await self._record_operation(temp_chunk, code_context)
                        yield response
                    need_auto_code_execution = False


            # 7. 处理其他响应（如LLM的文本输出）
            else:
                # print(f"🔍 DEBUG: 其他类型响应: {chunk}")
                yield response
        
        # 8. 生成会话总结节点
        self._add_summary_node(response, code_context, language)
        yield response
        
        # 9. 标记响应完成
        response.processing_type = ProcessingType.RESPONSEDONE
        yield response
        
    
    def _init_coder_response(self, user_prompt: str, language: str) -> MindSearchResponse:
        """初始化Coder响应"""
        
        def get_thought_process(lang: str) -> str:
            if lang == 'zh-CN':
                return "代码助手正在分析您的需求..."
            elif lang == 'ja':
                return "コードアシスタントがあなたの要件を分析しています..."
            elif lang == 'ar':
                return "مساعد الكود يحلل متطلباتك..."
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
        
        def get_thinking_text(lang: str) -> str:
            if lang == 'zh-CN':
                return "正在分析代码需求..."
            elif lang == 'ja':
                return "コード要件を分析中..."
            elif lang == 'ar':
                return "تحليل متطلبات الكود..."
            else:
                return "Analyzing code requirements..."

        thinking_node = SearchNode(
            search_type=SearchType.UNKNOWN,
            subject=WebSearchSubject.CODE,
            query=get_thinking_text(language),
            processing_type=ProcessingType.THINKING
        )
        
        response.search_graph.add_child(thinking_node)
        return thinking_node
    
    def _add_tool_node(self, response: MindSearchResponse, tool_name: str, language: str) -> SearchNode:
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
    
    def _update_node_from_tool_call(self, node: SearchNode, tool_call, language: str):
        """从工具调用更新节点信息"""
        try:
            import json
            args = json.loads(tool_call.function.arguments)
            
            if 'thought_process' in args:
                node.thought_process = args['thought_process']
            
            # 根据工具类型设置查询
            if tool_call.function.name == 'CodeGeneration':
                node.query = args.get('task_description', '生成代码')
            elif tool_call.function.name == 'CodeExecution':
                node.query = '执行代码'
            elif tool_call.function.name == 'FileManagement':
                node.query = f"文件操作: {args.get('operation', '')}"
            elif tool_call.function.name == 'CodeReview':
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
            exec_result = result.get('execution_result', {})
            status = exec_result.get('status', 'unknown')
            if language == 'zh-CN':
                return f"代码执行{status}，状态: {status}"
            else:
                return f"Code execution {status}"

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
