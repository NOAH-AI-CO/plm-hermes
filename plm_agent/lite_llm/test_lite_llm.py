# -*- coding: utf-8 -*-
import os
import sys

import io
import json
import asyncio

from IPython.display import Image, display

# Add the noah_agent directory to Python path so we can import config
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from pydantic import BaseModel, Field
from google.genai import types

from config import api_config
from lite_llm.base_model import BaseLLM
from tools.core.base_tool import BaseTool
from lite_llm.azure_openai import (
    AzureOpenAIModel, AzureOpenAI5Mini, AzureOpenAI5
)
from lite_llm.azure_claude import AzureClaudeModel
from lite_llm.google_models import GoogleModel
from lite_llm.openai_models import OpenAIModel
from lite_llm.vertex_claude import VertexClaudeModel
from lite_llm.deepseek_models import DeepSeekModel
from lite_llm.aliyun_models import AliyunModel
from lite_llm.composite_models import CompositeModel

def get_model(provider: str) -> BaseLLM:
    if provider == "azure_openai":
        return AzureOpenAIModel(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPT5_2_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            model=api_config.AZURE_GPT5_2_DEPLOYMENT,
        )
    elif provider == "google":
        return GoogleModel(
            model=api_config.VERTEX_GEMINI30_PRO_MODRL_ID,
        )
    elif provider == "openai":
        return OpenAIModel(
            api_key=api_config.OPENAI_API_KEY,
            model=api_config.OPENAI_GPT5_2,
        )
    elif provider == "vertex_claude":
        return VertexClaudeModel(
            project_id=api_config.VERTEX_CLAUDE_PROJECT_ID,
            model=api_config.VERTEX_CLAUDE45_MODEL_ID,
            region=api_config.VERTEX_CLAUDEOPUS4_REGION,
        )
    elif provider == "azure_claude":
        return AzureClaudeModel(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            azure_endpoint=api_config.AZURE_CLAUDE_SONNET_45_ENDPOINT, 
            model=api_config.AZURE_CLAUDE_SONNET_45_DEPLOYMENT,
        )
    elif provider == "deepseek":
        return DeepSeekModel(
            api_key=api_config.DEEPSEEK_API_KEYS.split(",")[0],
            base_url=api_config.DEEPSEEK_API_ENDPOINT,
            model=api_config.DEEPSEEK_API_CHAT_MODEL,
        )
    elif provider == "aliyun":
        return AliyunModel(
            api_key=api_config.QWEN_API_KEYS,
            base_url=api_config.QWEN_API_ENDPOINT,
            model=api_config.QWEN3_MAX_MODEL_ID,
        )
    elif provider == "composite_azure_openai_5_mini":
        return CompositeModel(models=[AzureOpenAI5Mini(), AzureOpenAI5()])

    else:
        raise ValueError(f"Invalid provider: {provider}")

class GetWeatherInputSchema(BaseModel):
    r"""
    Get the weather of the given city and date
    """
    city: str = Field(
        description="The name of the city")
    country: str = Field(
        default="United States",
        description="The name of the country")
    date: str = Field(
        default=None,
        description="The date of the weather format: yyyy-mm-dd")

class GetWeather(BaseTool):
    name: str = 'GetWeather'
    description: str = 'Get the weather of the given city and date'
    input_schema: BaseModel = GetWeatherInputSchema
    strict: bool = True

class BookingHotelInputSchema(BaseModel):
    r"""
    Book a hotel for the given city and date
    """
    city: str = Field(
        description="The name of the city")
    country: str = Field(
        default="United States",
        description="The name of the country")
    date: str = Field(
        default=None,
        description="The date of the hotel format: yyyy-mm-dd")

class BookingHotel(BaseTool):
    name: str = 'BookingHotel'
    description: str = 'Book a hotel for the given city and date'
    input_schema: BaseModel = BookingHotelInputSchema
    strict: bool = True

class TravelLineSchema(BaseModel):
    r"""
    Give a travel line by the given information
    """
    travel_line: str = Field(
        description="The travel line")
    reason: str = Field(
        description="The reason for the travel line")
    budget: float = Field(
        description="The budget for the travel line")
    duration: int = Field(
        description="The duration for the travel line")
    start_date: str = Field(
        description="The start date for the travel line")
    end_date: str = Field(
        description="The end date for the travel line")

class BookingTicketInputSchema(BaseModel):
    r"""
    Book a ticket for the given travel line
    """
    travel_line: str = Field(
        description="The travel line")
    reason: str = Field(
        description="The reason for the booking ticket")

class BookingTicket(BaseTool):
    name: str = 'BookingTicket'
    description: str = 'Book a ticket for the given travel line'
    input_schema: BaseModel = BookingTicketInputSchema
    strict: bool = True

async def test_function_call(model: BaseLLM):

    response = await model.function_call(
        input=[{"role": "user", "content": "Hello, I want to visit New York, US, on 2026-01-01, where to book the hotel?"}],
        tools=[GetWeather, BookingHotel],
        tool_choice="required",
        sys_prompt="You are a helpful assistant.",
        #reasoning={"effort": "medium", "summary": "auto"},
    )
    print(response)

async def test_structured_output(model: BaseLLM):

    response = await model.structured_output(
        input=[{"role": "user", "content": "Hello, I want to visit New York on 2026-01-01, what is the weather?"}],
        schema=GetWeatherInputSchema,
        sys_prompt="You are a helpful assistant.",
        #reasoning={"effort": "medium", "summary": "auto"},
    )
    print(response)

async def test_stream_generate(model: BaseLLM):

    response = model.stream_generate(
        input=[{"role": "user", "content": "Hello, I want to visit New York on 2026-01-01, what is the weather?"}],
        sys_prompt="You are a helpful assistant.",
        reasoning={"effort": "medium", "summary": "auto"},
    )
    print("="*10)
    buffer = io.StringIO()
    async for chunk in response:
        buffer.write(chunk)
        print("="*10)
        print(buffer.getvalue())

async def test_generate(model: BaseLLM):

    response = await model.generate(
        input=[{"role": "user", "content": "Hello, I want to visit New York on 2026-01-01, what is the weather?"}],
        sys_prompt="You are a helpful assistant.",
        reasoning={"effort": "medium", "summary": "auto"},
    )
    print("="*10)
    print(response)

async def test_exceeds_context_window(model: BaseLLM):

    response = model.stream_generate(
        input=[{"role": "user", "content": "Hello, I want to visit New York on 2026-01-01, what is the weather?" * 100000}],
        sys_prompt="You are a helpful assistant.",
    )
    print("-"*10)
    buffer = io.StringIO()
    async for chunk in response:
        buffer.write(chunk)
        print("="*10)
        print(buffer.getvalue())

async def test_gemini_function_call():
    # Define a function that the model can call to control smart lights
    set_light_values_declaration = {
        "name": "set_light_values",
        "description": "Sets the brightness and color temperature of a light.",
        "parameters": {
            "type": "object",
            "properties": {
                "brightness": {
                    "type": "integer",
                    "description": "Light level from 0 to 100. Zero is off and 100 is full brightness",
                },
                "color_temp": {
                    "type": "string",
                    "enum": ["daylight", "cool", "warm"],
                    "description": "Color temperature of the light fixture, which can be `daylight`, `cool` or `warm`.",
                },
            },
            "required": ["brightness", "color_temp"],
        },
    }

    # This is the actual function that would be called based on the model's suggestion
    def set_light_values(brightness: int, color_temp: str) -> dict[str, int]:
        """Set the brightness and color temperature of a room light. (mock API).

        Args:
            brightness: Light level from 0 to 100. Zero is off and 100 is full brightness
            color_temp: Color temperature of the light fixture, which can be `daylight`, `cool` or `warm`.

        Returns:
            A dictionary containing the set brightness and color temperature.
        """
        return {"brightness": brightness, "colorTemperature": color_temp}
    
    from google import genai
    from google.genai import types
    # Configure the client and tools
    client = genai.Client(location="global", http_options=types.HttpOptions(api_version='v1'))
    tools = types.Tool(function_declarations=[set_light_values_declaration])
    config = types.GenerateContentConfig(tools=[tools])

    # Define user prompt
    contents = [
        types.Content(
            role="user", parts=[types.Part(text="Turn the lights down to a romantic level")]
        )
    ]

    # Send request with function declarations
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=config,
    )

    print(response)
    print(response.candidates[0].content.parts[0].function_call)

    # Extract tool call details, it may not be in the first part.
    tool_call = response.candidates[0].content.parts[0].function_call

    if tool_call.name == "set_light_values":
        result = set_light_values(**tool_call.args)
        print(f"Function execution result: {result}")
    
    # Create a function response part
    function_response_part = types.Part.from_function_response(
        name=tool_call.name,
        response={"result": result},
    )

    # Append function call and result of the function execution to contents
    contents.append(response.candidates[0].content) # Append the content from the model's response.
    contents.append(types.Content(role="user", parts=[function_response_part])) # Append the function response

    final_response = client.models.generate_content(
        model="gemini-2.5-flash",
        config=config,
        contents=contents,
    )

    print(final_response.text)

async def test_chain_function_call(model: BaseLLM):

    input = [{"role": "user", "content": "Hello, I want to visit New York on 2026-01-01, where to book the hotel?"}]
    response = await model.function_call(
        input=input,
        tools=[GetWeather, BookingHotel],
        tool_choice="required",
        sys_prompt="You are a helpful assistant.",
    )
    print('-'*10)
    print(response)

    input.append(response)

    if model.provider in ["azure_openai", "openai"]:
        for item in response:
            if item.type == 'function_call':
                output = 'Call function failed'
                if item.name == 'GetWeather':
                    output = 'New York weather is sunny and temperature is 20 degrees Celsius'
                elif item.name == 'BookingHotel':
                    output = 'Hotel booked successfully with booking ID: 123456 and hotel name is Hilton New York'
                input.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": output
                })
    elif model.provider == "google":
        for item in response.parts:
            if item.function_call.name == 'GetWeather':
                output = 'New York weather is sunny and temperature is 20 degrees Celsius'
            elif item.function_call.name == 'BookingHotel':
                output = 'Hotel booked successfully with booking ID: 123456 and hotel name is Hilton New York'
            function_response_part = types.Part.from_function_response(
                name=item.function_call.name,
                response={"result": output},
            )
            input.append(types.Content(role="user", parts=[function_response_part]))
    elif model.provider == "aliyun":
        for item in response.tool_calls:
            if item.type == 'function':
                output = 'Call function failed'
                if item.function.name == 'GetWeather':
                    output = 'New York weather is sunny and temperature is 20 degrees Celsius'
                elif item.function.name == 'BookingHotel':
                    output = 'Hotel booked successfully with booking ID: 123456 and hotel name is Hilton New York'
                input.append({
                    "role": "tool",
                    "content": output,
                    "tool_call_id": item.id
                })

    input.append({
        "role": "user",
        "content": "Give a travel line by the given information: travel_line: New York, reason: Visit New York, budget: 1000, duration: 10, start_date: 2026-01-01, end_date: 2026-01-10"
    })

    response = await model.structured_output(
        input=input,
        schema=TravelLineSchema,
        sys_prompt="You are a helpful assistant.",
    )
    print('-'*10)
    print(response)
    
    input.append({
        "role": "assistant",
        "content": response.model_dump_json()
    })

    input.append({
        "role": "user",
        "content": "Please book a goback ticket for the travel line"
    })

    response = await model.function_call(
        input=input,
        tools=[BookingTicket],
        tool_choice="required",
        sys_prompt="You are a helpful assistant.",
    )
    print('-'*10)
    print(response)

    input.append(response)
    if model.provider in ["azure_openai", "openai"]:
        input.append({
            "type": "function_call_output",
            "call_id": response[0].call_id,
            "output": 'Book the ticket successfully with ticket ID: 123456 and ticket name is New York to Los Angeles'
        })
    elif model.provider == "google":
        function_response_part = types.Part.from_function_response(
            name=response.parts[0].function_call.name,
            response={"result": 'Book the ticket successfully with ticket ID: 123456 and ticket name is New York to Los Angeles'},
        )
        input.append(types.Content(role="user", parts=[function_response_part]))
    elif model.provider == "aliyun":
        input.append({
            "role": "tool",
            "content": 'Book the ticket successfully with ticket ID: 123456 and ticket name is New York to Los Angeles',
            "tool_call_id": response.tool_calls[0].id
        })

    response = model.stream_generate(
        input=input,
        sys_prompt="You are a helpful assistant.",
    )
    buffer = io.StringIO()
    async for chunk in response:
        buffer.write(chunk)
    print('-'*10)
    print(buffer.getvalue())
    buffer.close()

async def test_azure_claude_compact_generate(model: BaseLLM):
    response = await model.compact_generate(
        input=[{"role": "user", "content": "Hello, I want to visit New York on 2026-01-01, what is the weather?"}],
        summary_prompt="You are a helpful assistant.",
    )
    print('-'*10)
    print(response)

async def test_gemini_image_generate():
    model = GoogleModel(
        model=api_config.VERTEX_GEMINI31_FLASH_LITE_IMAGE_MODEL_ID,
    )
    response = await model.image_generate(
        input=[
            {
                "role": "user",
                "content": (
                    "A high-contrast, grainy black and white street photography shot. "
                    "A woman in dark sunglasses is captured in mid-stride with elegant motion blur. "
                    "Overlaid on the image are large, white, pillowy bubble lines that curve around her "
                    "to trace her silhouette. A word is added to the top of the image in the same white, "
                    "bubble font: STYLE."
                ),
            }
        ],
        sys_prompt="",
    )
    print("-" * 10)

    # `response` is the raw image bytes from `image_generate`, save to local file.
    #output_path = "generated_image.png"
    #with open(output_path, "wb") as f:
    #    f.write(response)
    #print(f"Image saved to {output_path}")

async def test_azure_openai_image_generate():
    model = AzureOpenAIModel(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_GPT5_2_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
        model=api_config.AZURE_GPT5_DEPLOYMENT,
    )
    response = await model.image_generate(
        input=[{"role": "user", "content": "Hello, I want to visit New York on 2026-01-01, what is the weather?"}], 
        sys_prompt="You are a helpful assistant.",
    )
    print("-" * 10)
    print(response)

if __name__ == "__main__":
    asyncio.run(test_gemini_image_generate())
