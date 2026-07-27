import abc
import time
import asyncio
import datetime
import traceback
from abc import ABC

from tenacity import retry, stop_after_attempt, wait_random_exponential
import logging

logger = logging.getLogger(__name__)


class BaseLLM(ABC):
    """
    A base class for model req.
    """
    provider = ""
    stream_break = False
            
    @abc.abstractmethod
    async def __call__(self, sys_prompt:str="", user_prompt:str="", json_mode:bool=False, temperature:float=0.05, **kwargs) -> str:
        return "result"
    
    @abc.abstractmethod
    async def stream_call(self, sys_prompt:str="", user_prompt:str="", temperature=0.05, **kwargs):
        yield "result"
        
    async def batch_api(self, sys_prompt:str="", user_prompts:list[str]=None) -> list[str]:
        """
        Asynchronously sends a list of user prompts to the OpenAI API and retrieves the responses.

        Args:
            sys_prompt (str): The system prompt to send before each user prompt.
            user_prompts (list[str]): A list of user prompts to send to the model.

        Returns:
            list[str]: A list of responses from the model for each user prompt.
        """
        tasks = [asyncio.create_task(self(sys_prompt, user_prompt)) for user_prompt in user_prompts]
        return await asyncio.gather(*tasks)
    
    @abc.abstractmethod
    async def log_results(self, sys_prompt:str, user_prompt:str, content: str, usage: str) -> None:
        pass

    def get_error_detail(self, exception) -> dict:
        error_detail = {
            "error_type": type(exception).__name__,
            "error_message": str(exception),
            "status_code": getattr(exception, "status_code", None),
            "response_text": getattr(getattr(exception, "response", None), "text", None)
        }
        return error_detail
    
    async def break_stream(self):
        """
        Set the stream break flag to True.
        This is used to stop the streaming process.
        """
        self.stream_break = True

class CompositeModel():
    models = []
    
    def __init__(self) -> None:
        self.current_index = 0
        self.loop_count = 5  # Allow up to 5 attempts to switch models
        if self.models:
            self.current_model = self.models[self.current_index]
            self.provider = self.current_model.provider if hasattr(self.current_model, 'provider') else ''
        else:
            self.current_model = None
            self.provider = ''

    def _get_next_model_params(self, current_index, loop_count):
        """Stateless calculation of next model index"""
        next_index = current_index
        next_loop_count = loop_count
        
        # If not at the last model, just go to next
        if next_index < len(self.models) - 1:
            return next_index + 1, next_loop_count, True
            
        # If at last model, but have loops left, wrap to start
        if next_loop_count > 0:
            return 0, next_loop_count - 1, True
            
        return next_index, next_loop_count, False
        
    def _try_next_model(self):
        """Try to switch to the next available model in the chain"""
        next_idx, next_loop, can_switch = self._get_next_model_params(self.current_index, self.loop_count)
        if can_switch:
            self.current_index = next_idx
            self.loop_count = next_loop
            self.current_model = self.models[self.current_index]
            self.provider = self.current_model.provider if hasattr(self.current_model, 'provider') else ''
            logger.info(f"Switching to {self.current_model.__class__.__name__}...")
            return True
        return False

    async def __call__(self, **kwargs) -> str:
        start_time = time.time()
        last_error = None
        
        current_index = 0
        loop_count = 5
        
        while True:
            if not self.models:
                raise RuntimeError("No models configured in CompositeModel")
            
            current_model = self.models[current_index]
            used_model = current_model.__class__.__name__
            
            try:
                res = await current_model.__call__(**kwargs)
                return res
            except Exception as e:
                logger.warning(f"{used_model} Error: {e}")
                last_error = e
                
                next_index, next_loop, can_switch = self._get_next_model_params(current_index, loop_count)
                if can_switch:
                    current_index = next_index
                    loop_count = next_loop
                    current_model = self.models[current_index] # Just to be safe for logging etc, though loop re-evaluates
                    logger.info(f"Switching to {self.models[current_index].__class__.__name__}...")
                else:
                    raise RuntimeError(f"All models in chain failed. Last error: {str(last_error)}")
            finally:
                logger.info(f"Using model {used_model} cost {time.time() - start_time:.2f}s")
                
    async def stream_call(self, timeout: float = 15.0, **kwargs):
        start_time = time.time()
        last_error = None
        
        current_index = 0
        loop_count = 5
        
        while True:
            if not self.models:
                raise RuntimeError("No models configured in CompositeModel")

            current_model = self.models[current_index]

            try:
                async for chunk in current_model.stream_call(**kwargs):
                    yield chunk
                return

            except asyncio.TimeoutError:
                logger.warning(f"Stream call timeout after {timeout} seconds")
                last_error = f"Timeout after {timeout} seconds"
                
                next_index, next_loop, can_switch = self._get_next_model_params(current_index, loop_count)
                if can_switch:
                    current_index = next_index
                    loop_count = next_loop
                    logger.info(f"Switching to {self.models[current_index].__class__.__name__}...")
                else:
                    raise RuntimeError(f"All models in chain failed. Last error: {last_error}")

            except Exception as e:
                logger.warning(f"Error: {e}")
                logger.warning("Retrying with next model...")
                last_error = e
                
                next_index, next_loop, can_switch = self._get_next_model_params(current_index, loop_count)
                if can_switch:
                    current_index = next_index
                    loop_count = next_loop
                    logger.info(f"Switching to {self.models[current_index].__class__.__name__}...")
                else:
                    raise RuntimeError(f"All models in chain failed. Last error: {str(last_error)}")
            finally:
                logger.info(f"Using model {current_model.__class__.__name__} cost {time.time() - start_time:.2f}s")

    async def generate_stream(self, user_prompt, **kwargs):
        async for chunk in self.stream_call(user_prompt=user_prompt, **kwargs):
            yield chunk

    async def break_stream(self):
        """
        Set the stream break flag to True for the current model.
        This is used to stop the streaming process.
        """
        if hasattr(self.current_model, 'break_stream') and self.current_model:
            await self.current_model.break_stream()
        else:
            logger.warning(f"CompositeModel break_stream logic limited due to concurrent design.")