"""Self-contained DashScope text-embedding-v4 wrapper for PLM knowledge base."""
import asyncio
import logging
import random
import time

from openai import OpenAI

from config import api_config

logger = logging.getLogger(__name__)

_client: OpenAI | None = None

_MODEL = "text-embedding-v4"
_DIMS = 1024
_MAX_INPUT_CHARS = 8000
_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=api_config.ALIYUN_BAILIAN_API_KEY,
            base_url=_BASE_URL,
        )
    return _client


def get_embedding(text: str) -> list[float]:
    max_retries = 4
    backoff = 1.0
    truncated = text[:_MAX_INPUT_CHARS]

    for attempt in range(1, max_retries + 1):
        try:
            resp = _get_client().embeddings.create(
                model=_MODEL,
                dimensions=_DIMS,
                input=truncated,
                timeout=7,
            )
            return resp.data[0].embedding
        except Exception as e:
            if attempt == max_retries:
                raise
            sleep_for = backoff * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning(
                "Embedding attempt %d failed: %s. Retrying in %.2fs...",
                attempt, e, sleep_for,
            )
            time.sleep(sleep_for)


async def get_embedding_async(text: str) -> list[float]:
    return await asyncio.to_thread(get_embedding, text)


async def batch_embed(
    texts: list[str],
    max_concurrent: int = 5,
) -> list[list[float]]:
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _one(t: str) -> list[float]:
        async with semaphore:
            return await get_embedding_async(t)

    return await asyncio.gather(*[_one(t) for t in texts])
