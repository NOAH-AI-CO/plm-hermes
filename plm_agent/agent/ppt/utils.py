import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception_type(Exception), # 不管什么错误都重试，即使是500以下的错误
    reraise=True,
)
def request_with_retry(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    resp = client.request(method, url, **kwargs)
    resp.raise_for_status()
    return resp


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception_type(Exception), # 不管什么错误都重试，即使是500以下的错误
    reraise=True,
)
async def arequest_with_retry(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    resp = await client.request(method, url, **kwargs)
    resp.raise_for_status()
    return resp
