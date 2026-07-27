from pydantic import BaseModel, Field


class BaseToolInputSchema(BaseModel):
    task_description: str = Field(
        description="""
        你是一个AI助手

        ## 重要要求：
        当你要调用工具时，请在 task_description 字段中详细说明：
        必须把任务参数展示出来
        1. **任务分析**：分析用户的需求和目标
        2. **解决思路**：说明你打算如何解决这个问题
        3. **具体步骤**：列出详细的执行步骤
        4. **预期结果**：说明你期望得到什么结果

        ## 示例格式：
        对于代码执行任务，task_description 应该包含：
        - 任务目标：明确要完成什么
        - 解决思路：使用什么算法或方法
        - 执行计划：如何运行和验证结果

        **示例输出格式：**
        任务：计算第十个斐波那契数字
        解决思路：
        使用迭代方法计算斐波那契数列
        从第1项开始，逐步计算到第10项
        使用两个变量 a, b 来存储相邻两项
        通过循环更新 a, b 的值

        打印序列和结果

        请确保 task_description 包含完整的思考过程和解决方案，而不仅仅是简单的任务描述。

        """
    )


    