"""
Coder智能体使用示例
展示如何使用可插拔的Coder功能
"""
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
gcp_key_path = os.path.join(BASE_DIR, "gcp_key.json")
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path
import asyncio

from pydantic import Field
from agent.coder.simple_coder_agent import SimpleCoderAgent
from agent.coder.coder_agent import CoderAgent
from tools.core.base_tool import BaseTool


async def example_full_features():
    """
    示例1：使用完整功能的Coder智能体（沙箱模式）
    包含代码生成、执行、文件管理和审查
    """
    print("=== 完整功能Coder智能体示例（沙箱模式）===")

    # 创建完整功能的Coder智能体（沙箱模式）
    coder = SimpleCoderAgent(
        work_dir="./example_workspace",
        enable_file_management=True,  # 启用文件管理
        enable_code_review=True,      # 启用代码审查
        sandbox_url="http://0.0.0.0:8194",  # 沙箱服务地址
        use_sandbox=True              # 启用沙箱模式
    )
    
    # 使用智能体
    user_request = "请帮我创建一个简单的计算器类，包含加减乘除功能，然后测试它并保存到文件"
    
    async for response in coder.use_tool(
        user_prompt=user_request,
        language="python",
        ui_language="zh-CN"
    ):
        # 打印响应信息
        if hasattr(response, 'code_graph') and response.code_graph:
            print(f"当前操作: {response.code_graph.query}")
            
            # 显示子操作
            for child in response.code_graph.children:
                status = "✅" if child.processing_type == 3 else "🔄"  # 3 = DONE
                print(f"  {status} {child.query}: {child.summary}")
        
        if hasattr(response, 'content') and response.content:
            print(f"AI回复: {response.content}")


async def example_minimal_features():
    """
    示例2：使用最小功能的Coder智能体（沙箱模式）
    只包含代码生成和执行，不包含文件管理和审查
    """
    print("\n=== 最小功能Coder智能体示例（沙箱模式）===")

    # 创建最小功能的Coder智能体
    coder = SimpleCoderAgent(
        enable_file_management=False,  # 禁用文件管理
        enable_code_review=False,      # 禁用代码审查
        sandbox_url="http://0.0.0.0:8194",  # 沙箱服务地址
        use_sandbox=True               # 启用沙箱模式
    )
    
    # 使用智能体
    user_request = "我想知道第十个斐波那契数字是多少，生成一个Python函数来计算斐波那契数列，然后执行它"
    
    print(f"🔍 调试信息:")
    print(f"   - 用户请求: {user_request}")
    print(f"   - 工作目录: {coder.work_dir}")
    print(f"   - 沙箱URL: {coder.sandbox_url}")
    print(f"   - 使用沙箱: {coder.use_sandbox}")
    print(f"   - 工具列表: {[tool.__name__ for tool in coder.tools]}")
    print(f"   - 工具配置: {coder.tool_config}")
    print()
    
    async for response in coder.use_tool(
        user_prompt=user_request,
        language="python",
        # ui_language="en"
    ):
        print(f"\n📦 收到响应类型: {type(response)}")
        print('响应：', response)
        # 详细解析响应内容
        if hasattr(response, 'code_graph') and response.code_graph:
            print(f"🌳 Search Graph:")
            print(f"   - 根节点查询: {response.code_graph.query}")
            print(f"   - 处理状态: {response.code_graph.processing_type}")
            print(f"   - 思考过程: {response.code_graph.thought_process}")
            
            # 显示子节点
            for i, child in enumerate(response.code_graph.children):
                status_map = {0: "❓", 1: "🔄", 2: "💬", 3: "✅", 5: "💭", 9: "🤔"}
                status = status_map.get(child.processing_type, "❓")
                print(f"   └─ 子节点{i+1}: {status} {child.query}")
                if child.summary:
                    print(f"      摘要: {child.summary}")
                if child.key_word:
                    print(f"      关键词: {child.key_word}")
        
        # 检查LLM响应
        if hasattr(response, 'content') and response.content:
            print(f"🤖 LLM内容: {response.content}")
        
        # 检查工具调用
        if hasattr(response, 'tool_calls') and response.tool_calls:
            print(f"🔧 工具调用:")
            for i, tool_call in enumerate(response.tool_calls):
                print(f"   - 工具{i+1}: {tool_call.function.name}")
                print(f"     参数: {tool_call.function.arguments}")
        
        # 检查处理状态
        if hasattr(response, 'processing_type'):
            print(f"📊 处理状态: {response.processing_type}")
            if response.processing_type == 7:  # RESPONSEDONE
                print("🎉 任务完成!")
        
        # 如果是字典类型（工具执行结果）
        if isinstance(response, dict):
            print(f"📋 字典响应:")
            for key, value in response.items():
                if key == 'function':
                    print(f"   - 函数: {value}")
                elif key == 'params':
                    print(f"   - 参数: {value}")
                elif key == 'result' or key == 'execution_result':
                    print(f"   - 结果: {value}")
                elif key == 'error':
                    print(f"   ❌ 错误: {value}")
                else:
                    print(f"   - {key}: {value}")
            
            # 特殊处理：显示生成的代码
            if response.get('function') == 'CodeGeneration':
                generated_code = response.get('generated_code', '')
                if generated_code:
                    print(f"\n💻 生成的代码:")
                    print("=" * 40)
                    print(generated_code)
                    print("=" * 40)
            
            # 特殊处理：显示执行结果
            elif response.get('function') == 'CodeExecution':
                exec_result = response.get('result', {}) or response.get('execution_result', {})
                if isinstance(exec_result, dict):
                    status = exec_result.get('status', 'unknown')
                    output = exec_result.get('output', '')
                    errors = exec_result.get('errors')
                    
                    print(f"\n▶️ 代码执行结果:")
                    print(f"   状态: {status}")
                    if output:
                        print(f"   输出:")
                        print("   " + "-" * 30)
                        print(f"   {output}")
                        print("   " + "-" * 30)
                    if errors:
                        print(f"   ❌ 错误: {errors}")
        
        print("-" * 50)


async def print_example_minimal_features():
    """
    示例2：使用最小功能的Coder智能体（沙箱模式）
    只包含代码生成和执行，不包含文件管理和审查
    """
    print("\n=== 最小功能Coder智能体示例（沙箱模式）===")

    # 创建最小功能的Coder智能体
    coder = CoderAgent(
        enable_file_management=False,  # 禁用文件管理
        enable_code_review=False,      # 禁用代码审查
        sandbox_url="http://0.0.0.0:8194",  # 沙箱服务地址
        use_sandbox=True               # 启用沙箱模式
    )
    
    # 使用智能体
    user_request = "我想知道第十个斐波那契数字是多少，生成一个Python函数来计算斐波那契数列，然后执行它"
    
    print(f"🔍 调试信息:")
    print(f"   - 用户请求: {user_request}")
    print(f"   - 工作目录: {coder.work_dir}")
    print(f"   - 沙箱URL: {coder.sandbox_url}")
    print(f"   - 使用沙箱: {coder.use_sandbox}")
    print(f"   - 工具列表: {[tool.__name__ for tool in coder.tools]}")
    print(f"   - 工具配置: {coder.tool_config}")
    print()
    
    async for response in coder.use_tool(
        user_prompt=user_request,
        language="python",
        # ui_language="en"
    ):
        print(f"\n📦 收到响应类型: {type(response)}")
        print('*********************响应：', response)
        # 详细解析响应内容
        print("-" * 50)


async def example_local_mode():
    """
    示例3：本地模式的Coder智能体（沙箱服务不可用时的备选方案）
    """
    print("\n=== 本地模式Coder智能体示例 ===")

    # 创建本地模式的Coder智能体
    coder = SimpleCoderAgent(
        work_dir="./local_workspace",  # 本地工作目录
        enable_file_management=True,
        enable_code_review=True,
        use_sandbox=False              # 禁用沙箱，使用本地模式
    )

    # 使用智能体进行文件操作
    user_request = "创建一个Python模块，包含数据处理的工具函数"

    async for response in coder.use_tool(
        user_prompt=user_request,
        language="python",
        ui_language="zh-CN"
    ):
        # 处理响应...
        pass


async def example_custom_sandbox():
    """
    示例4：自定义沙箱地址的Coder智能体
    """
    print("\n=== 自定义沙箱地址Coder智能体示例 ===")

    # 创建自定义沙箱地址的Coder智能体
    coder = SimpleCoderAgent(
        enable_file_management=True,
        enable_code_review=True,
        sandbox_url="http://192.168.1.100:8194",  # 自定义沙箱地址
        use_sandbox=True
    )

    # 使用智能体
    user_request = "创建一个简单的Web服务器代码并测试"

    async for response in coder.use_tool(
        user_prompt=user_request,
        language="python",
        ui_language="zh-CN"
    ):
        # 处理响应...
        pass


def demonstrate_pluggable_design():
    """
    演示可插拔设计的优势
    """
    print("\n=== 可插拔设计演示 ===")

    # 场景1：只需要代码生成和执行（沙箱模式）
    basic_coder = SimpleCoderAgent(
        enable_file_management=False,
        enable_code_review=False,
        use_sandbox=True
    )
    print("✅ 基础沙箱Coder创建成功 - 只有代码生成和执行功能")

    # 场景2：需要完整功能（沙箱模式）
    full_coder = SimpleCoderAgent(
        enable_file_management=True,
        enable_code_review=True,
        use_sandbox=True
    )
    print("✅ 完整沙箱Coder创建成功 - 包含所有功能")

    # 场景3：本地模式（备选方案）
    local_coder = SimpleCoderAgent(
        enable_file_management=True,
        enable_code_review=False,
        use_sandbox=False
    )
    print("✅ 本地Coder创建成功 - 代码生成 + 本地文件管理")

    # 显示工具配置
    print(f"\n基础沙箱Coder工具数量: {len(basic_coder.tools)}")
    print(f"完整沙箱Coder工具数量: {len(full_coder.tools)}")
    print(f"本地Coder工具数量: {len(local_coder.tools)}")
    print(f"沙箱URL: {basic_coder.sandbox_url}")
    print(f"使用沙箱: {basic_coder.use_sandbox}")


async def example_search_node_tracking():
    """
    示例4：演示search_node的实时跟踪功能
    """
    print("\n=== Search Node实时跟踪示例 ===")
    
    coder = SimpleCoderAgent(
        work_dir="./tracking_workspace",
        enable_file_management=True,
        enable_code_review=True
    )
    
    user_request = "创建一个简单的待办事项管理器"
    
    async for response in coder.use_tool(
        user_prompt=user_request,
        language="python",
        ui_language="zh-CN"
    ):
        # 详细跟踪search_node状态
        if hasattr(response, 'code_graph') and response.code_graph:
            root = response.code_graph
            print(f"\n📋 根节点: {root.query}")
            print(f"   状态: {root.processing_type}")
            print(f"   思考: {root.thought_process}")
            
            # 遍历子节点
            for i, child in enumerate(root.children):
                status_map = {
                    0: "❓ 未知",
                    1: "🔄 处理中", 
                    2: "💬 响应中",
                    3: "✅ 完成",
                    5: "💭 思考中",
                    9: "🤔 分析中"
                }
                status = status_map.get(child.processing_type, "❓")
                
                print(f"   └─ 步骤{i+1}: {status} {child.query}")
                if child.summary:
                    print(f"      摘要: {child.summary}")
                if child.key_word:
                    print(f"      关键词: {child.key_word}")


def test():
    import os
    from openai import AzureOpenAI
    from config import api_config

    
    client = AzureOpenAI(
        api_key=api_config.AZURE_GPTo4_MIN_API_KEY,
        api_version=api_config.AZURE_GPTo4_MIN_VERSION,
        azure_endpoint=api_config.AZURE_GPTo4_MIN_ENDPOINT,
        )
    # print(completion.model_dump_json(indent=2))

    from pydantic import BaseModel
    class FinishedInputSchema(BaseModel):
        location: str = Field(
            description="城市名字"
        )

    class FinishedInputSchema1(BaseModel):
        from1: str = Field(
            description="源货币"
        )
        to: str = Field(
            description="目标货币"
        )

    class GET_WEATHER(BaseTool):

        name: str = 'GET_WEATHER'
        description: str = '查看城市的天气'
        input_schema: BaseModel = FinishedInputSchema
        
        def run(self, location):
            return f"The weather in {location} is sunny."

    class GET_EXCHANGE_RATE(BaseTool):
        name: str = 'GET_EXCHANGE_RATE'
        description: str = '查看货币汇率，比如人民币对美元的汇率'
        input_schema: BaseModel = FinishedInputSchema1
        
        def run(self, from1, to):
            return f"from1: {from1}, to: {to}"


    tools = [{
        "type": "function",  # ← 必需字段
        "function": {
            "name": "GET_WEATHER",
            "description": "查看城市的天气",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "城市名字"
                    }
                },
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "GET_EXCHANGE_RATE",
            "description": "查看货币汇率，比如人民币对美元的汇率",
            "parameters": {
                "type": "object",
                "properties": {
                    "from1": {"type": "string", "description": "源货币"},  # 源货币
                    "to": {"type": "string", "description": "目标货币"}     # 目标货币
                },
                "required": ["from1", "to"]
            }
        }
    }

    ]

    weather_tool = GET_WEATHER()
    exchange_tool = GET_EXCHANGE_RATE()

    from utils.core.get_tool_schema import get_openai_input_schema
    from llm.azure_models import GPTo4Mini
    llm = GPTo4Mini()
    tools = [
        get_openai_input_schema(weather_tool),
        get_openai_input_schema(exchange_tool)
    ]
    
    # 使用工具实例而不是手动配置
    # llm.stream_call(
    #     user_prompt= "查一下欧元兑人民币的汇率以及北京的天气，必须使用所有的工具，并且使用工具的名称",
    #     tools = tools,
    #     stream=True,
    #     tool_choice="auto"
    # )
    system_prompt = """
    你是一个具备工具调用能力的助手。回答用户问题时，需遵循以下步骤：
    1. 首先用自然语言简要说明你要执行的操作（例如：“我将为你计算第10个斐波那契数”），这部分直接作为回答内容返回。
    2. 完成说明后，再调用对应的工具函数（如计算工具），并确保工具参数完整。
    
    工具调用格式需符合要求，仅在完成自然语言说明后才进行工具调用。
    """

    
    stream = client.chat.completions.create(
        model="gpt-o4-mini-noah",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "查一下欧元兑人民币的汇率以及北京的天气"},
        ],
        # messages=[{"role": "user", "content": "帮我写首诗"}],
        tools = tools,
        stream=True,
        tool_choice="auto"
    )

    for event in stream:
        print(event)


    # completion = client.chat.completions.create(
    #     model="gpt-o4-mini-noah", # Replace with your model dpeloyment name.
    #     messages=[
    #         {"role": "system", "content": "You are a helpful assistant."},
    #         {"role": "user", "content": "给我写一首古诗"}
    #     ],
    #     stream = True
    #     )

    # for chunk in completion:
    #     if chunk.choices and chunk.choices[0].delta.content is not None:
    #         print(chunk.choices[0].delta.content)
    # print(completion.choices[0].message)




async def main():
    """主函数 - 运行所有示例"""
    print("🚀 Coder智能体示例程序启动")
    
    # 演示可插拔设计
    # demonstrate_pluggable_design()
    
    # 运行异步示例
    try:
        
        # await example_full_features()
        # await example_minimal_features()
        
        # await example_local_mode()
        # await example_custom_sandbox()
        # await example_search_node_tracking()
        # test()
        from config import settings
        print(type(settings), settings)
        print("2123", settings.get("CSRF_TRUSTED_ORIGINS123", '1233232'))
        # await print_example_minimal_features()
    except Exception as e:
        print(f"❌ 示例运行出错: {e}")
    
    print("\n🎉 所有示例运行完成")


if __name__ == "__main__":
    # 运行示例
    asyncio.run(main())


# ================================
# 重要说明和最佳实践
# ================================

"""
🔧 可插拔设计的优势：

1. 灵活配置：
   - 可以根据需求选择性启用功能
   - 减少不必要的工具加载
   - 提高性能和安全性

2. 沙箱安全隔离：
   - 代码在远程沙箱中执行，完全隔离
   - 文件操作通过沙箱API进行
   - 防止对主机系统的任何影响
   - 支持本地模式作为备选方案

3. 实时反馈：
   - search_node提供详细的操作进度
   - 用户可以实时看到AI的工作状态
   - 便于调试和监控

4. 易于扩展：
   - 新工具可以轻松添加
   - 现有工具可以独立修改
   - 支持自定义沙箱配置

📝 使用建议：

1. 根据实际需求选择功能：
   - 简单任务：只启用代码生成和执行
   - 项目开发：启用所有功能
   - 代码审查：重点启用审查功能

2. 沙箱配置建议：
   - 优先使用沙箱模式（更安全）
   - 确保沙箱服务可用性
   - 配置合适的沙箱地址
   - 本地模式作为备选方案

3. 监控执行状态：
   - 关注search_node的状态变化
   - 及时处理错误和异常
   - 记录重要操作日志

4. 安全注意事项：
   - 沙箱模式提供最高安全性
   - 定期审查生成的代码
   - 监控沙箱服务状态
   - 本地模式需要额外安全措施
"""
