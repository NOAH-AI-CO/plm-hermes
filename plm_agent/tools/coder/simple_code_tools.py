"""
简单的代码工具集合 - 可插拔设计
包含代码生成、执行、文件管理和审查功能
"""
import os
import re
import ast
import time
import json

from typing import Dict, List, Any, Optional, ClassVar
import aiohttp
from pydantic import BaseModel, Field

from tools.schema.base_schema import BaseToolInputSchema
from tools.core.base_tool import BaseTool
import config


class CodeGenerationInputSchema(BaseModel):
    task_description: str = Field(description="要生成的代码功能描述")
    language: str = Field(default="python3", description="编程语言")
    save_to_file: str = Field(default="", description="保存文件路径（可选）")

# 定义严格的输出格式
class CodeGenerationOutput(BaseModel):
    code: str = Field(description="Pure Python code without any markdown or JSON wrapper")
    language: str = Field(description="Programming language", default="python")
    explanation: str = Field(description="Brief explanation of what the code does")

class CodeGeneration(BaseTool):
    """
    @summary: 代码生成工具
    """
    name: str = 'CodeGeneration'
    description: str = """生成代码工具"""
    input_schema: BaseModel = CodeGenerationInputSchema
    
    async def run(self, task_description: str, language: str = "python3", save_to_file: str = "", **kwargs):
        """
        生成代码的核心逻辑
        重要：这里会调用LLM来生成代码，通过self.agent访问
        """
        try:
            # 构建代码生成提示词
            prompt = self._build_generation_prompt(task_description, language)
            kwargs.pop('work_dir', None)
            # 调用LLM生成代码（重要：通过agent访问LLM）
            generated_code = await self._generate_with_llm(prompt)
            # code = self._extract_code_from_json_str(generated_code)
            result = {
                "function": self.name,
                "task_description": task_description, 
                "result": generated_code,
                "code_length": len(generated_code),
                "language": language
            }
            
            # if save_to_file:
            #     result["file_saved"] = save_to_file
            #     result["save_success"] = True
            
            yield result
            
        except Exception as e:
            yield {"error": f"代码生成失败: {str(e)}"}

    def _extract_code_from_json_str(self, input_str: str, target_key: str = "code") -> Optional[str]:
        """
        从包含JSON的字符串中提取指定键（默认是'code'）的值
        
        :param input_str: 包含JSON的原始字符串（可能带有Markdown代码块标记）
        :param target_key: 要提取的目标键名，默认为'code'
        :return: 提取的目标值，失败时返回None
        """
        try:
            # 步骤1：移除Markdown代码块标记（支持```json、```JSON等大小写形式）
            code_block_pattern = re.compile(r'```\s*json\s*\n(.*?)\n```', re.DOTALL | re.IGNORECASE)
            match = code_block_pattern.search(input_str)
            if not match:
                # 如果没有代码块标记，默认整个字符串视为JSON内容
                json_content = input_str
            else:
                json_content = match.group(1).strip()

            # 步骤2：修复常见的JSON格式问题
            # 修复键名缺少引号的问题（如 code: 改为 "code":）
            json_content = re.sub(r'(\s*)(%s)(\s*):' % target_key, r'\1"\2"\3:', json_content)
            # 移除尾部可能多余的逗号
            json_content = re.sub(r',\s*(\}|\])', r'\1', json_content)

            # 步骤3：解析JSON并提取目标值
            json_data = json.loads(json_content)
            return json_data.get(target_key)

        except json.JSONDecodeError as e:
            print(f"JSON解析错误: {str(e)}")
        except Exception as e:
            print(f"提取失败: {str(e)}")
        return input_str
    
    def _build_generation_prompt(self, task_description: str, language: str) -> str:
        """构建LLM提示词"""
        return f"""
            你是一个专业的代码生成助手。请根据以下要求生成高质量的{language}代码：

            任务描述：{task_description}

            代码要求：
            1. 代码必须清晰易读，包含必要的注释
            2. 遵循{language}最佳实践和编码规范
            3. 包含适当的错误处理机制
            4. 代码必须可直接执行
            5. 结果必须通过print语句输出，不能使用其他展示方式
            6. 如果有计算结果，必须用print展示最终答案
            7. 可调用库：可调用预安装库：pandas（数据处理）,
            8. **重要：代码必须直接执行，不要使用 if __name__ == "__main__" 条件**
            9. **重要：所有代码都应该在模块级别直接执行，确保print语句会被调用**

            代码质量标准：
            - 使用有意义的变量名和函数名
            - 添加必要的文档字符串和注释
            - 处理边界情况和异常
            - 确保代码逻辑正确且高效
            - 避免硬编码，使用参数化设计

            重要提醒：
            - 只生成纯代码，不要包含任何解释文字
            - 不要包含markdown格式或代码块标记
            - 代码必须完整且可直接运行
            - 确保所有输出都通过print语句展示
            - **代码应该在模块级别直接执行，不要包装在main函数中**

            请生成符合上述要求的{language}代码。
                """
    
    async def _generate_with_llm(self, prompt: str) -> str:
        """使用LLM生成代码"""
        if hasattr(self, 'agent') and self.agent and hasattr(self.agent, 'llm'):
            try:
                # 重要：通过agent的LLM来生成代码
                # 修复：需要先实例化LLM
                # llm_instance = self.agent.llm()
                # response = await llm_instance.call_response(user_prompt=prompt)
                # return response.choices[0].message.content

                from utils.core.get_json_schema import get_openai_json_schema_v3
                from utils.human_in_loop.helpers import function_call_with_retry
                schema = get_openai_json_schema_v3(CodeGenerationOutput)
                tool_choice = {"type": "function", "function": {"name": schema[0]['function']['name']}}

                # 调用 LLM
                result = await function_call_with_retry(
                    self.agent.llm(), 
                    user_prompt=prompt, 
                    tools=schema, 
                    tool_choice=tool_choice
                )

                return result['code']
            except Exception as e:
                return f"# LLM调用失败: {str(e)}\n# TODO: 需手动实现功能"
        else:
            # 如果没有LLM，返回模板代码
            return f"# 生成的代码模板\n# TODO: 需实现功能 - {prompt[:100]}..."

class CodeExecutionInputSchema(BaseToolInputSchema):
    code: str = Field(description="要执行的代码")
    # code_b64: str = Field(default="python", description="base64编码版本的要执行的代码")
    language: str = Field(default="python", description="编程语言")
    timeout: int = Field(default=30, description="执行超时时间（秒）")

class CodeExecution(BaseTool):
    """
    @summary: 代码执行工具
    """
    name: str = 'CodeExecution'
    description: str = '在沙箱环境中执行代码'
    input_schema: BaseModel = CodeExecutionInputSchema

    sandbox_url: str = config.settings.get('NOAH_SANDBOX_URL', 'http://0.0.0.0:8194') if os.environ.get("ENVIRONMENT") == 'test' else "http://0.0.0.0:8194"
    sandbox_endpoint: str = f"{sandbox_url}/v1/sandbox/run"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if 'sandbox_url' in kwargs:
            self.sandbox_url = kwargs['sandbox_url']
            self.sandbox_endpoint = f"{self.sandbox_url}/v1/sandbox/run"

    async def run(self, code: str, language: str = "python", timeout: int = 30, **kwargs):
        """
        在沙箱中安全执行代码
        重要：使用远程沙箱服务，完全隔离执行环境
        """
        try:
            # 基础安全检查（可选，因为沙箱本身就很安全）
            # if not self._is_code_safe(code, language):
            #     yield {"error": "代码包含潜在不安全操作，建议检查后再执行"}
            #     return
            kwargs.pop('work_dir', None)
            # 在沙箱中执行代码
            exec_result = await self._execute_in_sandbox(code, language, timeout)

            result = {
                "function": self.name,
                "language": language,
                "result": exec_result,
                "code_length": len(code),
                "task_description": "执行代码",
                "sandbox_url": self.sandbox_url
            }

            yield result

        except Exception as e:
            yield {"error": f"沙箱代码执行失败: {str(e)}"}

    async def _execute_in_sandbox(self, code: str, language: str, timeout: int) -> dict:
        """
        在沙箱服务中执行代码
        重要：通过HTTP API调用远程沙箱服务
        """
        try:
            # 语言映射 - 将通用语言名映射到沙箱支持的格式
            language_map = {
                "python": "python3",
                "python3": "python3",
            }

            sandbox_language = language_map.get(language.lower(), "python3")

            # 准备请求数据
            payload = {
                "language": sandbox_language,
                "code": code  # 代码中的换行符会自动转换为\n
            }

            # 发送请求到沙箱服务
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.sandbox_endpoint,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:

                    if response.status == 200:
                        result_data = await response.json()
                        return {
                            "status": "success",
                            "output": result_data.get("output", ""),
                            "errors": result_data.get("error", None),
                            "execution_time": result_data.get("execution_time", 0),
                            "sandbox_language": sandbox_language,
                            "sandbox_response": result_data
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "status": "error",
                            "error": f"沙箱服务返回错误 {response.status}: {error_text}",
                            "sandbox_language": sandbox_language
                        }

        except aiohttp.ClientError as e:
            return {
                "status": "connection_error",
                "error": f"无法连接到沙箱服务: {str(e)}",
                "sandbox_url": self.sandbox_url
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"沙箱执行异常: {str(e)}"
            }

    def _is_code_safe(self, code: str, language: str) -> bool:
        """
        安全检查：防止危险操作
        重要：保护系统安全的关键函数
        """
        if language == "python":
            # 禁止的危险操作模式
            dangerous_patterns = [
                r'import\s+os\s*;.*os\.(system|remove|rmdir)',  # 系统操作
                r'import\s+subprocess',  # 子进程
                r'import\s+shutil',      # 文件操作
                r'open\s*\([^)]*["\'][/\\]',  # 绝对路径文件操作
                r'__import__',           # 动态导入
                r'eval\s*\(',           # 动态执行
                r'exec\s*\(',           # 动态执行
                r'globals\s*\(',        # 全局变量访问
                r'locals\s*\(',         # 局部变量访问
            ]
            
            for pattern in dangerous_patterns:
                if re.search(pattern, code, re.IGNORECASE):
                    return False
        
        return True


class FileManagementInputSchema(BaseModel):
    operation: str = Field(description="操作类型: read, write, create, list")
    file_path: str = Field(description="文件路径（相对于工作目录）")
    content: str = Field(default="", description="文件内容（写入时使用）")

class FileManagement(BaseTool):
    """
    @summary: 文件管理工具
    """
    name: str = 'FileManagement'
    description: str = '管理沙箱环境中的文件'
    input_schema: BaseModel = FileManagementInputSchema

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 沙箱服务配置
        self.sandbox_url = kwargs.get('sandbox_url', 'http://0.0.0.0:8194')
        self.use_sandbox = kwargs.get('use_sandbox', True)  # 是否使用沙箱

        # 本地工作目录（作为备选方案）
        self.work_dir = kwargs.get('work_dir', './coder_workspace')
        if not self.use_sandbox:
            self._ensure_work_dir()

    def _ensure_work_dir(self):
        """确保本地工作目录存在"""
        if not os.path.exists(self.work_dir):
            os.makedirs(self.work_dir, exist_ok=True)
    
    async def run(self, operation: str, file_path: str, content: str = "", **kwargs):
        """
        文件操作的核心逻辑
        重要：支持沙箱和本地两种模式
        """
        try:
            result = {
                "function": self.name,
                "params": {"operation": operation, "file_path": file_path},
                "use_sandbox": self.use_sandbox
            }

            if self.use_sandbox:
                # 使用沙箱文件系统
                result.update(await self._sandbox_file_operation(operation, file_path, content))
            else:
                # 使用本地文件系统（安全检查）
                safe_path = self._get_safe_path(file_path)
                if not safe_path:
                    yield {"error": "文件路径不安全，操作被阻止"}
                    return

                if operation == "read":
                    result.update(await self._read_file(safe_path))
                elif operation == "write":
                    result.update(await self._write_file(safe_path, content))
                elif operation == "create":
                    result.update(await self._create_file(safe_path, content))
                elif operation == "list":
                    result.update(await self._list_files(safe_path))
                else:
                    result["error"] = f"不支持的操作: {operation}"

            yield result

        except Exception as e:
            yield {"error": f"文件操作失败: {str(e)}"}

    async def _sandbox_file_operation(self, operation: str, file_path: str, content: str = "") -> dict:
        """
        在沙箱中执行文件操作
        重要：通过沙箱API进行文件管理，完全隔离
        """
        try:
            # 构建沙箱文件操作的API端点
            file_endpoint = f"{self.sandbox_url}/v1/sandbox/file"

            payload = {
                "operation": operation,
                "file_path": file_path,
                "content": content if content else ""
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    file_endpoint,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:

                    if response.status == 200:
                        result_data = await response.json()
                        return {
                            "success": True,
                            "message": result_data.get("message", "操作成功"),
                            "content": result_data.get("content", ""),
                            "files": result_data.get("files", []),
                            "file_size": result_data.get("file_size", 0),
                            "sandbox_response": result_data
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "error": f"沙箱文件操作失败 {response.status}: {error_text}"
                        }

        except aiohttp.ClientError as e:
            return {
                "error": f"无法连接到沙箱文件服务: {str(e)}",
                "fallback": "建议检查沙箱服务状态"
            }
        except Exception as e:
            return {
                "error": f"沙箱文件操作异常: {str(e)}"
            }

    def _get_safe_path(self, file_path: str) -> Optional[str]:
        """
        获取安全的文件路径
        重要：防止路径遍历攻击，限制在工作目录内
        """
        # 移除危险字符
        if '..' in file_path or file_path.startswith('/'):
            return None
        
        # 构建完整路径
        full_path = os.path.join(self.work_dir, file_path)
        
        # 确保路径在工作目录内
        if not full_path.startswith(os.path.abspath(self.work_dir)):
            return None
        
        return full_path
    
    async def _read_file(self, file_path: str) -> dict:
        """读取文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return {
                "content": content,
                "file_size": len(content),
                "message": "文件读取成功"
            }
        except FileNotFoundError:
            return {"error": "文件不存在"}
        except Exception as e:
            return {"error": f"读取失败: {str(e)}"}
    
    async def _write_file(self, file_path: str, content: str) -> dict:
        """写入文件"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return {
                "bytes_written": len(content),
                "message": "文件写入成功"
            }
        except Exception as e:
            return {"error": f"写入失败: {str(e)}"}
    
    async def _create_file(self, file_path: str, content: str) -> dict:
        """创建文件"""
        if os.path.exists(file_path):
            return {"error": "文件已存在"}
        return await self._write_file(file_path, content)
    
    async def _list_files(self, dir_path: str) -> dict:
        """列出目录文件"""
        try:
            if os.path.isfile(dir_path):
                dir_path = os.path.dirname(dir_path)
            
            files = []
            for item in os.listdir(dir_path):
                item_path = os.path.join(dir_path, item)
                files.append({
                    "name": item,
                    "type": "file" if os.path.isfile(item_path) else "directory",
                    "size": os.path.getsize(item_path) if os.path.isfile(item_path) else 0
                })
            
            return {
                "files": files,
                "count": len(files),
                "message": "目录列表获取成功"
            }
        except Exception as e:
            return {"error": f"列表获取失败: {str(e)}"}


class CodeReviewInputSchema(BaseModel):
    code: str = Field(description="要审查的代码")
    language: str = Field(default="python", description="编程语言")
    review_type: str = Field(default="basic", description="审查类型: basic, security, style")

class CodeReview(BaseTool):
    """
    @summary: 代码审查工具
    """
    name: str = 'CodeReview'
    description: str = '对代码进行质量审查'
    input_schema: BaseModel = CodeReviewInputSchema
    
    async def run(self, code: str, language: str = "python", review_type: str = "basic", **kwargs):
        """
        代码审查的核心逻辑
        重要：结合静态分析和LLM分析
        """
        try:
            result = {
                "function": self.name,
                "params": {"language": language, "review_type": review_type},
                "review_result": {}
            }
            
            if review_type == "basic":
                result["review_result"] = await self._basic_review(code, language)
            elif review_type == "security":
                result["review_result"] = await self._security_review(code, language)
            elif review_type == "style":
                result["review_result"] = await self._style_review(code, language)
            else:
                result["error"] = f"不支持的审查类型: {review_type}"
            
            yield result
            
        except Exception as e:
            yield {"error": f"代码审查失败: {str(e)}"}
    
    async def _basic_review(self, code: str, language: str) -> dict:
        """基础代码审查"""
        issues = []
        suggestions = []
        
        if language == "python":
            # 静态分析
            try:
                tree = ast.parse(code)
                # 分析代码结构
                functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
                classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
                
                # 基本检查
                lines = code.split('\n')
                for i, line in enumerate(lines, 1):
                    if len(line) > 100:
                        issues.append(f"第{i}行过长 ({len(line)}字符)")
                    if line.strip().startswith('print(') and not line.strip().startswith('# '):
                        suggestions.append(f"第{i}行：考虑使用日志而不是print")
                
                return {
                    "functions_found": len(functions),
                    "classes_found": len(classes),
                    "lines_of_code": len(lines),
                    "issues": issues[:5],  # 限制显示数量
                    "suggestions": suggestions[:5],
                    "overall_score": max(0, 100 - len(issues) * 10)
                }
                
            except SyntaxError as e:
                return {"error": f"语法错误: {str(e)}"}
        
        return {"message": f"暂不支持{language}的基础审查"}
    
    async def _security_review(self, code: str, language: str) -> dict:
        """安全审查"""
        security_issues = []
        
        if language == "python":
            # 检查安全问题
            security_patterns = {
                "潜在SQL注入": [r"execute\s*\(\s*.*\+.*\)", r"cursor\.execute.*%"],
                "命令注入风险": [r"os\.system\s*\(.*\+", r"subprocess.*shell\s*=\s*True"],
                "硬编码密码": [r"password\s*=\s*[\"'][^\"']+[\"']"],
                "不安全的反序列化": [r"pickle\.loads?", r"eval\s*\("],
            }
            
            for issue_type, patterns in security_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, code, re.IGNORECASE):
                        security_issues.append(issue_type)
        
        return {
            "security_issues": security_issues,
            "risk_level": "high" if security_issues else "low",
            "issues_count": len(security_issues)
        }
    
    async def _style_review(self, code: str, language: str) -> dict:
        """代码风格审查"""
        style_issues = []
        
        if language == "python":
            lines = code.split('\n')
            for i, line in enumerate(lines, 1):
                # 检查缩进
                if line.startswith('\t'):
                    style_issues.append(f"第{i}行：使用了Tab缩进，建议使用4个空格")
                # 检查行尾空格
                if line.endswith(' ') or line.endswith('\t'):
                    style_issues.append(f"第{i}行：行尾有多余空格")
        
        return {
            "style_issues": style_issues[:10],
            "issues_count": len(style_issues),
            "style_score": max(0, 100 - len(style_issues) * 5)
        }
        

class FinishedInputSchema(BaseModel):
    result: str = Field(
        description="Coder Success"
    )

class Finished(BaseTool):
    name: str = 'Finished'
    description: str = '标记Code任务完成'
    input_schema: BaseModel = FinishedInputSchema
    
    async def run(self, **kwargs):
        """标记任务完成"""
        result = kwargs.get('result', '')
        yield {
            "function": self.name,
            "message": "Code任务已完成",
            "result": result,
            "timestamp": time.time()
        }
