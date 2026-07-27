import logging
from typing import Any, AsyncIterator, Optional
logger = logging.getLogger(__name__)

class LiteLLMAdapter:
    def __init__(self, lite_llm_model):
        self.lite_llm_model = lite_llm_model
        # If lite_llm model forgot to set .model but has .mode, normalize it here.
        if not getattr(lite_llm_model, "model", None) and getattr(lite_llm_model, "mode", None):
            lite_llm_model.model = lite_llm_model.mode
        self.model = getattr(lite_llm_model, 'model', 'unknown')
        self.provider = getattr(lite_llm_model, 'provider', 'unknown')
        logger.info(f"LiteLLMAdapter 初始化: provider={self.provider}, model={self.model}")
    
    async def generate_stream(self, prompt: str, temperature: float = 0.5, **kwargs) -> AsyncIterator[str]:
        messages = [{"role": "user", "content": prompt}]
        logger.debug(f"LiteLLMAdapter.generate_stream: temperature={temperature}, prompt_length={len(prompt)}")
        
        try:
            async for chunk in self.lite_llm_model.stream_generate(
                input=messages,
                temperature=temperature,
                **kwargs
            ):
                if chunk:
                    yield chunk
        except Exception as e:
            logger.error(f"LiteLLMAdapter.generate_stream 失败: {e}")
            raise
    
    async def stream_call(
        self, 
        prompt: str, 
        temperature: float = 0.5, 
        response_format: Optional[dict] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        """
        适配 stream_call 方法（带 JSON mode 支持）
        
        将旧接口的 stream_call(prompt, response_format=..., ...) 转换为
        lite_llm 的 stream_generate(input=[...], ...)
        
        注意: lite_llm 不直接支持 response_format 参数，
        所以我们在 prompt 中明确要求 JSON 格式输出
        """
        # 如果需要 JSON 输出，在 prompt 中明确说明
        if response_format and response_format.get("type") == "json_object":
            # 在原始 prompt 后添加 JSON 输出要求
            json_instruction = "\n\n重要：请严格按照 JSON 格式输出，不要包含任何 markdown 标记、解释文字或其他内容。"
            prompt = f"{prompt}{json_instruction}"
            logger.debug("LiteLLMAdapter.stream_call: 已添加 JSON 输出指令")
        
        messages = [{"role": "user", "content": prompt}]
        
        logger.debug(f"LiteLLMAdapter.stream_call: temperature={temperature}, response_format={response_format}")
        
        try:
            async for chunk in self.lite_llm_model.stream_generate(
                input=messages,
                temperature=temperature,
                **kwargs
            ):
                if chunk:  # 过滤空 chunk
                    yield chunk
        except Exception as e:
            logger.error(f"LiteLLMAdapter.stream_call 失败: {e}")
            raise
    
    async def __call__(self, sys_prompt: str = "", user_prompt: str = "", temperature: float = 0.5, **kwargs) -> str:
        """
        adapter for __call__ method
        """
        messages = []
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        if user_prompt:
            messages.append({"role": "user", "content": user_prompt})
        
        logger.debug(f"LiteLLMAdapter.__call__: temperature={temperature}")
        
        try:
            result = []
            async for chunk in self.lite_llm_model.stream_generate(
                input=messages,
                temperature=temperature,
                **kwargs
            ):
                if chunk:
                    result.append(chunk)
            
            return "".join(result)
        except Exception as e:
            logger.error(f"LiteLLMAdapter.__call__ 失败: {e}")
            raise
    
    def __repr__(self):
        return f"LiteLLMAdapter(provider={self.provider}, model={self.model})"
