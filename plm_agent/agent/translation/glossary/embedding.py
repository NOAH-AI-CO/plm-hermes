import os
from openai import OpenAI
import time
import random
from config import api_config

input_text = "衣服的质量杠杠的"

client = OpenAI(
    # 若没有配置环境变量，请用阿里云百炼API Key将下行替换为：api_key="sk-xxx",
    # 新加坡和北京地域的API Key不同。获取API Key：https://help.aliyun.com/zh/model-studio/get-api-key
    api_key=api_config.ALIYUN_BAILIAN_API_KEY,  
    # 以下是北京地域base-url，如果使用新加坡地域的模型，需要将base_url替换为：https://dashscope-intl.aliyuncs.com/compatible-mode/v1
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

def get_embedding(text: str):
    max_retries = 4
    backoff = 1.0

    for attempt in range(1, max_retries + 1):
        try:
            response = client.embeddings.create(
                model="text-embedding-v4",
                dimensions=1024,
                input=text,
                timeout=7,
            )
            return response.data[0].embedding
        except Exception as e:
            if attempt == max_retries:
                raise
            sleep_for = backoff * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            print(f"Embedding attempt {attempt} failed: {e}. Retrying in {sleep_for:.2f}s...")
            time.sleep(sleep_for)


def get_embeddings_batch(texts: list, batch_size: int = 10) -> list:
    """Get embeddings for a list of texts using batched API calls."""
    max_retries = 4
    backoff = 1.0
    results = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        for attempt in range(1, max_retries + 1):
            try:
                response = client.embeddings.create(
                    model="text-embedding-v4",
                    dimensions=1024,
                    input=batch,
                    timeout=30,
                )
                batch_results = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
                results.extend(batch_results)
                print(f"  Embedded batch {i // batch_size + 1}/{(len(texts) + batch_size - 1) // batch_size} ({len(batch)} items)")
                break
            except Exception as e:
                if attempt == max_retries:
                    raise
                sleep_for = backoff * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                print(f"Batch embedding attempt {attempt} failed: {e}. Retrying in {sleep_for:.2f}s...")
                time.sleep(sleep_for)

    return results


# completion = client.embeddings.create(
#     model="text-embedding-v4",
#     input=input_text
# )

# print(completion.model_dump_json())