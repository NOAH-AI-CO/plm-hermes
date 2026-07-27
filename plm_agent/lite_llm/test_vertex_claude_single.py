# -*- coding: utf-8 -*-
import os
import sys
import asyncio

# Add the noah_agent directory to Python path so we can import config
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, 'noah_agent'))

from config import api_config
from lite_llm.vertex_claude import VertexClaudeModel
from lite_llm.base_model import BaseLLM

async def test_vertex_claude_generate():
    print("Initializing VertexClaudeModel...")
    # Ensure these config values are set in your environment or config.py
    # You might need to check if the model ID matches the 3.5 Sonnet ID on Vertex AI
    # typically "claude-3-5-sonnet-v2@20241022" or similar
    
    model = VertexClaudeModel(
        project_id="noah-ai-claude",
        model=api_config.VERTEX_CLAUDE45_MODEL_ID, # Ensure this points to the correct Sonnet 3.5 model ID
        region=api_config.VERTEX_CLAUDEOPUS4_REGION, # Ensure this region supports the model
    )

    print(f"Testing model: {model.model}")
    
    input_messages = [{"role": "user", "content": "Hello, are you Claude 3.5 Sonnet?"}]
    sys_prompt = "You are a helpful assistant."
    
    print("\n--- Testing generate() ---")
    try:
        response = await model.generate(
            input=input_messages,
            sys_prompt=sys_prompt,
            reasoning={"effort": "medium", "summary": "auto"}, # Optional, if supported
        )
        print("Response:")
        print(response)
    except Exception as e:
        print(f"Error during generate: {e}")

    print("\n--- Testing stream_generate() ---")
    try:
        stream_response = model.stream_generate(
            input=input_messages,
            sys_prompt=sys_prompt
        )
        
        print("Stream Response:")
        async for chunk in stream_response:
            print(chunk, end="", flush=True)
        print("\n")
    except Exception as e:
        print(f"Error during stream_generate: {e}")

if __name__ == "__main__":
    asyncio.run(test_vertex_claude_generate())
