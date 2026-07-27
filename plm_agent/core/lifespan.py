import httpx

from fastapi import FastAPI
from contextlib import asynccontextmanager

from utils.core.httpx_client import HttpxClientSingleton
from utils.core.elasticsearch_client import ElasticsearchClientSingleton
from utils.core.milvus_client import MilvusClientSingleton
from llm.azure_models import GPT4o, GPT41, GPTo3, GPTo4Mini, GPT4oWorkflow, Ada
from llm.gcp_models import GeminiClientSingleton, GoogleGenAIClientSingleton, ClaudeSonnet35, ClaudeSonnet4, ClaudeOpus4
from llm.deepseek_models import DeepseekChat, DeepseekChatR1, SiliconflowDeepseekChat, SiliconflowDeepseekChatR1, CompositeDeepseekChat, CompositeDeepseekReasoner, ClaudeThenDeepseekChat, ClaudeThenDeepseekChat2, CompositeDeepseekChatPlanning
from lite_llm.openai_models import OpenAI5Nano, OpenAI5Mini, OpenAI5, OpenAI51, OpenAI52
from lite_llm.azure_openai import AzureOpenAI5Nano, AzureOpenAI5Mini, AzureOpenAI54Mini, AzureOpenAI5, AzureOpenAI51, AzureOpenAI52
from lite_llm.vertex_claude import VertexClaude45Opus, VertexClaude45Sonnet, VertexClaude45Haiku
from lite_llm.google_models import Gemini25FlastLite, Gemini3FlastLite, Gemini31Pro
from lite_llm.aliyun_models import AliyunQwen3Max, AliyunQwenPlus, AliyunQwenFlash
from lite_llm.deepseek_models import DeepSeekChatModel
from lite_llm.llm_sdk_singleton import AsyncLlmSDKSingleton

from config import api_config, settings

granular_timeout = httpx.Timeout(45, connect=10.0)
low_timeout_0_retry = {"timeout": granular_timeout, "max_retries": 0}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database connection
    ElasticsearchClientSingleton.initialize()

    # MilvusClientSingleton.initialize()

    # Initialize clients
    HttpxClientSingleton.initialize()

    # Deprecated
    GeminiClientSingleton.initialize()

    GPT4o.initialize(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_GPT4_OPENAI_API_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT
    )
    GPT41.initialize(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_GPT4_1_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
        **low_timeout_0_retry
    )
    GPTo3.initialize(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_GPTo3_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
        **low_timeout_0_retry
    )
    GPTo4Mini.initialize(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_GPTo4_MIN_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
        **low_timeout_0_retry
    )
    GPT4oWorkflow.initialize(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_GPT4_OPENAI_API_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
        **low_timeout_0_retry
    )

    Ada.initialize(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_ADA002_OPENAI_API_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
        azure_deployment=api_config.AZURE_ADA002_AZURE_DEPLOYMENT
    )

    ClaudeSonnet35()
    ClaudeSonnet4()
    ClaudeOpus4()

    DeepseekChat()
    DeepseekChatR1()
    # HuoshanDeepseekChatR1()
    # HuoshanDeepseekChat()
    SiliconflowDeepseekChatR1()
    SiliconflowDeepseekChat()
    CompositeDeepseekChat()
    CompositeDeepseekReasoner()
    ClaudeThenDeepseekChat()
    ClaudeThenDeepseekChat2()
    CompositeDeepseekChatPlanning()

    # Lite LLM
    OpenAI5Nano()
    OpenAI5Mini()
    OpenAI5()
    OpenAI51()
    OpenAI52()
    VertexClaude45Opus()
    VertexClaude45Sonnet()
    VertexClaude45Haiku()
    AzureOpenAI5Nano()
    AzureOpenAI5Mini()
    AzureOpenAI54Mini()
    AzureOpenAI5()
    AzureOpenAI51()
    AzureOpenAI52()
    AliyunQwen3Max()
    AliyunQwenPlus()
    AliyunQwenFlash()
    DeepSeekChatModel()

    yield

    # Cleanup clients
    await HttpxClientSingleton.cleanup()

    await ElasticsearchClientSingleton.cleanup()

    # deprecated llm
    await GeminiClientSingleton.cleanup()
    await GoogleGenAIClientSingleton.cleanup()

    await GPT4o.cleanup(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_GPT4_OPENAI_API_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT
    )
    await GPT41.cleanup(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_GPT4_1_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
        **low_timeout_0_retry
    )
    await GPTo3.cleanup(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_GPTo3_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
        **low_timeout_0_retry
    )
    await GPTo4Mini.cleanup(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_GPTo4_MIN_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
        **low_timeout_0_retry
    )
    await GPT4oWorkflow.cleanup(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_GPT4_OPENAI_API_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
        **low_timeout_0_retry
    )

    Ada.cleanup(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_ADA002_OPENAI_API_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
        azure_deployment=api_config.AZURE_ADA002_AZURE_DEPLOYMENT
    )

    ClaudeSonnet35.cleanup()
    ClaudeSonnet4.cleanup()
    ClaudeOpus4.cleanup()

    DeepseekChat.cleanup()
    DeepseekChatR1.cleanup()
    # HuoshanDeepseekChatR1.cleanup()
    # HuoshanDeepseekChat.cleanup()
    SiliconflowDeepseekChatR1.cleanup()
    SiliconflowDeepseekChat.cleanup()
    CompositeDeepseekChat.cleanup()
    CompositeDeepseekReasoner.cleanup()
    ClaudeThenDeepseekChat.cleanup()
    ClaudeThenDeepseekChat2.cleanup()
    CompositeDeepseekChatPlanning.cleanup()

    # Lite LLM — clean up all singleton instances at once
    await AsyncLlmSDKSingleton.cleanup_all()

    # Cleanup database engines
    from utils.sql_client import engine, backup_engine, golden_engine, user_engine
    engine.dispose()
    backup_engine.dispose()
    golden_engine.dispose()
    user_engine.dispose()
