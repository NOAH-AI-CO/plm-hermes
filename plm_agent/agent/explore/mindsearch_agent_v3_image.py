# -*- coding: utf-8 -*-
import base64
import logging

from typing import List
from datetime import datetime
from google.genai import types as genai_types

import agent.explore.constants as constants
from agent.explore.mindsearch_agent_v3 import MindSearchAgentV3
from agent.explore.mindsearch_prompt_v3 import (
    gpt_image_thinking_sys_pt, 
    gpt_query_rewrite_user_pt, gpt_query_rewrite_with_attachment_user_pt,
    gpt_o_search_final_output_user_pt, gpt_image_final_output_sys_pt,
)
from llm.azure_models import GPT54
from lite_llm.google_models import Gemini31FlashLiteImage
from utils.utils.attachment import Storage
from agent.explore.schema import (
    SearchNode, MindSearchResponse, ProcessingType,
    SearchType,
)
from tools.explore.mindsearch_tools_v3 import ImageGeneration
from i18n import translate

logger = logging.getLogger(__name__)


class MindSearchImageGenerationAgent(MindSearchAgentV3):
    gemini_31_flash_lite_image_llm: Gemini31FlashLiteImage = Gemini31FlashLiteImage()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.thinking_agent.llm = GPT54

    def _init_response(
        self,
        user_prompt: str,
        attachments: List,
        floders: List,
        language: str = constants.ENGLISH) -> MindSearchResponse:
                    
        response = MindSearchResponse(
            search_graph=SearchNode(
                search_type=SearchType.UNKNOWN,
                query=user_prompt,
                thought_process=translate("ui.task_analysis", language),
                children=[SearchNode(
                        search_type=SearchType.UNKNOWN,
                        query=translate("ui.think", language),
                        summary=translate("ui.image_task_waiting", language),
                        processing_type=ProcessingType.THINKING)],
            ),
            processing_type=ProcessingType.PROCESSING,
            files=[{'name': f.get('name'), 'id': f.get('id')} for f in attachments],
            folders=[{'name': f.get('name'), 'id': f.get('id'), 'full_path': f.get('full_path')} for f in floders],
        )

        return response

    async def _format_final_output_prompt(
        self,
        user_prompt: str,
        history_messages: List[dict],
        runtime_info: dict,
        background: str,
        language: str = constants.ENGLISH
    ):
        # Response user's question
        websearch_results = self._format_final_searchresults(runtime_info, history_messages)

        final_user_prompt = gpt_o_search_final_output_user_pt.format(
            current_date=datetime.now().strftime('%Y-%m-%d.'),
            language=language,
            background=background,
            websearch_results=websearch_results,
            user_question=user_prompt)
        
        return gpt_image_final_output_sys_pt, final_user_prompt

    def _format_thinking_prompt(
        self,
        user_prompt: str,
        language: str = constants.ENGLISH):
        r"Format thinking prompt, return customer sys_prompt and user_prompt"

        logger.info(f"[_format_thinking_prompt] for image generation")
        user_prompt = (gpt_query_rewrite_with_attachment_user_pt if self.attachment_included else gpt_query_rewrite_user_pt).format(
            current_date=datetime.now().strftime('%Y-%m-%d'),
            language=language,
            user_question=user_prompt,
        )

        return gpt_image_thinking_sys_pt, user_prompt
    
    async def _llm_image_generation(
        self,
        image_prompt: str,
        image_name: str,
        related_image_urls: List[str],
        runtime_info: dict,
    ) -> str:
        """
        Generate image via LLM.
        """
        new_messages = []
        # Add history image urls for user to update or edite
        if related_image_urls:
            new_messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": url
                    }
                    for url in related_image_urls[-5:] if url
                ]
            })

        # Add user image prompt
        new_messages.append({
            "role": "user",
            "content": image_prompt
        })
        # Call llm model to generate image (with timeout + fallback)

        # Storage image path
        image_path = f"generated-images"
        task = runtime_info['task_context'].get('task_id')
        if task:
            image_path = image_path + f"/{task}"

        """
        base64_data = await asyncio.wait_for(
            self.gemini_31_flash_lite_image_llm.image_generate(
                input=new_messages,
                sys_prompt="You are a helpful assistant.",
                thinking_config=genai_types.ThinkingConfig(
                    include_thoughts=True,
                    thinking_level=genai_types.ThinkingLevel.HIGH,
                ),
            ),
            timeout=180,  # seconds; adjust if needed
        )
        """

        image_bytes = None
        b64_list = await self.image2_llm.generate_image(image_prompt)
        if b64_list:
            image_bytes = base64.b64decode(b64_list)

        if not image_bytes:
            image_bytes = await self.gemini_31_flash_lite_image_llm.image_generate(
                input=new_messages,
                sys_prompt="You are a helpful assistant.",
                thinking_config=genai_types.ThinkingConfig(
                    include_thoughts=True,
                    thinking_level=genai_types.ThinkingLevel.HIGH,
                ),
            )

        if image_bytes:
            image_url = self.image_storage.save_image(
                storage_meta={
                    "storage": Storage.AZURE_BLOB.value,
                    "container": "nudata",
                    "blob": f"{image_path}/{image_name}.png",
                },
                base64_data=image_bytes,
            )
            if image_url:
                return image_url 
        return None

    def _check_generated_images(self, runtime_info: dict) -> bool:
        # First check if there image generation tool call
        # Second check if there are generated images

        found_image_tool = False
        for tool_result in runtime_info.get('tool_results', []):
            if tool_result.name == ImageGeneration.__name__:
                found_image_tool = True
        
        # If no image generation tool call, return True, means no generated images
        if not found_image_tool:
            return True
        
        generated_images = runtime_info.get('generated_images', [])
        found = False
        for image in generated_images:
            if image.get('url'):
                found = True
                break
        return found
    
    async def _final_output_with_compact(
        self,
        user_prompt: str,
        history_messages: List[dict],
        runtime_info: dict,
        background: str,
        language: str = constants.ENGLISH
    ):
        # if no generated images, return directly
        if not self._check_generated_images(runtime_info):
            yield translate("error.image_generation_too_busy", language)
            return

        # call super method to get final output
        async for chunk in super()._final_output_with_compact(
            user_prompt,
            history_messages,
            runtime_info,
            background,
            language):
            yield chunk

    def _format_final_output(
        self,
        response: MindSearchResponse,
        language: str = constants.ENGLISH,
        runtime_info: dict = {},
        remove_citation: bool = False):

        # if no generated images, set processing type to failed
        # backend would return user's credits to AI model
        if not self._check_generated_images(runtime_info):
            response.processing_type = ProcessingType.FAILED

        super()._format_final_output(response, language, runtime_info, remove_citation)
