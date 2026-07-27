"""
从网页中获取有用的图片
需要 cairosvg 来处理 SVG 图片，没有零依赖的方案来处理 SVG 图片，所以只能这样了，我也不想这样的
MAC:
brew install cairo pango gdk-pixbuf libffi
Linux:
sudo apt-get update && sudo apt-get install -y libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi8 libgobject-2.0-0
"""

import datetime
import math
import os
# os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = "/opt/homebrew/lib:" + os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "") # 本地调试
import cairosvg
from PIL import Image
from copy import deepcopy
import base64
import json
import os
import io
import asyncio
import random
import time
import aiohttp
from pathlib import PurePosixPath
from urllib.parse import urlparse
from firecrawl import Firecrawl
from pydantic import BaseModel, Field

from config import api_config
from . import llm


class ImageInfo(BaseModel):
    url: str
    body: bytes | None = None
    mime_type: str | None = None
    suffix: str | None = None
    description: str | None = None
    wh: tuple[int, int] | None = None
    debug_name: str | None = None


async def url_to_md(url: str) -> tuple[str, str]:

    def get_data_type(content_type: str, url: str) -> str:
        """
        根据 content_type 和 URL 分类为 text pdf other
        """
        import mimetypes
        from urllib.parse import urlparse, unquote
        import posixpath

        text_mime_types = {
            "text/plain",
            "text/html",
            "text/markdown",
            "text/csv",
            "text/xml",
            "text/yaml",
            "text/json",
            "application/json",
            "application/xml",
            "application/yaml",
            "application/x-yaml",
            "application/csv",
            "application/rss+xml",
            "application/atom+xml",
            "application/xhtml+xml",
            "application/javascript",
            "text/javascript",
        }

        text_extensions = {
            ".txt", ".md", ".markdown", ".html", ".htm", ".csv",
            ".json", ".xml", ".yaml", ".yml", ".rss", ".atom",
            ".tsv", ".log",
        }

        # 1) 先规范化 content_type
        ct = (content_type or "").split(";", 1)[0].strip().lower()

        # 2) 优先相信 content_type
        if ct == "application/pdf":
            return "pdf"

        if ct in text_mime_types:
            return "text"

        # 大多数 text/* 都归到普通文本
        if ct.startswith("text/"):
            return "text"

        # 结构化文本常见后缀
        if ct.endswith("+json") or ct.endswith("+xml"):
            return "text"

        # 3) content_type 不够用时，再看 URL
        url = url or ""
        try:
            parsed = urlparse(url)
            path = unquote(parsed.path or "")
            _, ext = posixpath.splitext(path)
            ext = ext.lower()
        except Exception:
            ext = ""

        if ext == ".pdf":
            return "pdf"

        if ext in text_extensions:
            return "text"

        # 4) 再用标准库 mimetypes 按 URL/扩展名兜底猜一次
        guessed_mime, _ = mimetypes.guess_type(url)
        guessed_ct = (guessed_mime or "").split(";", 1)[0].strip().lower()

        if guessed_ct == "application/pdf":
            return "pdf"

        if guessed_ct in text_mime_types:
            return "text"

        if guessed_ct.startswith("text/"):
            return "text"

        if guessed_ct.endswith("+json") or guessed_ct.endswith("+xml"):
            return "text"

        # 5) 其余都归 other
        return "other"

    def firecrawl_scrape(url: str) -> tuple[str, str]:
        firecrawl = Firecrawl(api_key=api_config.FIRECRAWL_API_KEY)
        doc = firecrawl.scrape(
            url,
            formats=["markdown", "html"],
            parsers=[],
            max_age=172800000, # 2 days
            remove_base64_images=True,
            proxy="stealth"
        )
        data_type = get_data_type(doc.metadata.content_type, url)
        return doc.markdown, doc.html, data_type

    for _ in range(3):
        try:
            return await asyncio.to_thread(firecrawl_scrape, url)
        except Exception as e:
            print(f"firecrawl_scrape error: {e}")
            await asyncio.sleep(0.5)

    return "", "", ""


async def get_important_image_urls(markdown: str) -> list[str]:
    markdown = markdown[:250000] # 25万字符，对于一个网页来说够了，防止超过 token 限制
    prompt = f"""
<网页转Markdown内容>
{markdown}
</网页转Markdown内容>

## 你的任务

请从上面这段网页转 Markdown 的内容中提取具有信息价值的正文图片URL（如数据图表、流程图、架构图等），严格排除网页噪音（如logo、icon、按钮、广告及UI装饰图）
请结合图片的alt文本、URL特征及上下文语义进行综合判断
将结果按价值从高到低排序，最终输出一个json数组，数组元素为图片URL

## 返回格式要求

请以 JSON 格式返回
格式如下：{{"important_image_urls": ["url1", "url2"]}}
如果没有任何有价值的图片URL，请返回空数组：{{"important_image_urls": []}}

## 严格要求

- 你返回的URL必须与 "网页内容" 中的URL完全一致
    """
    class ImportantImageUrls(BaseModel):
        """重要图片URL列表, 如果没有重要图片URL，则important_image_urls为空数组[]"""
        important_image_urls: list[str] = Field(..., description="重要图片URL列表")
    
    response_format = llm.to_openrouter_response_format(ImportantImageUrls, name="important_image_urls")
    prompt = prompt.strip()
    # 新模型有新模型的BUG，旧模型有旧模型的BUG，所以需要 merge
    models = (
        "google/gemini-3.1-flash-lite-preview",
        "google/gemini-3-flash-preview",
        "openai/gpt-5.4-nano",
        # "openai/gpt-4o-mini",
        # "openai/gpt-5-nano", 太慢
        # "openai/gpt-5-mini", 太慢
        # "deepseek/deepseek-v3.2", 太慢
    )
    messages = [
        llm.role_system("You are a helpful assistant."),
        llm.role_user(prompt)
    ]

    async def call_model(m: str) -> list[str]:
        try:
            t0 = time.time()
            x = await llm.async_chat(llm.LLMReq(
                model=m,
                messages=messages,
                response_format=response_format,
            ))
            raw = x.choices[0].message.content
            if raw is None:
                return []
            x = json.loads(llm.strip_llm_json(raw))
            x = x['important_image_urls']
            x = [y for y in x if y in markdown]
            t1 = time.time()
            # print(f"{m} {len(x)}个 {t1 - t0}秒")
            return x
        except Exception as e:
            return []

    lists = await asyncio.gather(*(call_model(m) for m in models))
    max_len = max((len(lst) for lst in lists), default=0)
    merged: list[str] = []
    for i in range(max_len):
        for lst in lists:
            if i < len(lst) and lst[i] not in merged:
                merged.append(lst[i])

    return merged


async def download_images(urls: list[str], max_concurrent: int) -> list[bytes | None]:
    """
    必须有下面的两个包
    uv add brotli
    uv add "backports.zstd"
    """
    if len(urls) == 0:
        return []
    if max_concurrent < 1:
        max_concurrent = 1

    def image_request_headers(url: str) -> dict[str, str]:
        ua_pool = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
        ua = random.choice(ua_pool)
        h: dict[str, str] = {
            "User-Agent": ua,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }
        if origin:
            h["Referer"] = origin + "/"
        return h

    sem = asyncio.Semaphore(max_concurrent)
    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(limit=max_concurrent, limit_per_host=max_concurrent, ssl=False)

    async def fetch_indexed(session: aiohttp.ClientSession, idx: int, url: str) -> tuple[int, bytes | None]:
        async with sem:
            for _ in range(2):
                try:
                    headers = image_request_headers(url)
                    async with session.get(url, headers=headers, allow_redirects=True) as resp:
                        resp.raise_for_status()
                        body = await resp.read()
                    return idx, body
                except Exception:
                    await asyncio.sleep(0.3)
            return idx, None

    async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers={"Connection": "keep-alive"}) as session:
        pairs = await asyncio.gather(*(fetch_indexed(session, i, u) for i, u in enumerate(urls)))
    pairs.sort(key=lambda p: p[0])
    return [p[1] for p in pairs]


def annotate_image_mime_types(image_infos: list[ImageInfo]) -> list[ImageInfo]:
    """
    输入 ImageInfo 列表（含 url、body）
    输出每项增加 type: str | None（MIME，如 image/png；无法确定则为 None）
    """
    if len(image_infos) == 0:
        return []

    extension_to_mime: dict[str, str] = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".jfif": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".svg": "image/svg+xml",
    }

    def mime_from_magic(body: bytes) -> str | None:
        if len(body) < 3:
            return None
            
        # JPEG 80% 的网页中存在这种类型
        if body.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
            
        # PNG 80% 的网页中存在这种类型
        if body.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
            
        # GIF 20% 的网页中都是这种类型，但是很少有 AI 能接收 GIF
        if body.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
            
        # WEBP 20% 的网页中存在这种类型
        if len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP":
            return "image/webp"
            
        # AVIF 1% 的网页中存在这种类型
        if len(body) >= 12 and body[4:8] == b"ftyp" and body[8:12] in (b"avif", b"avis"):
            return "image/avif"

        # SVG 50% 的网页中存在这种类型，但是很少有 AI 能接收 SVG
        head_preview = body[:1024].lstrip(b"\xef\xbb\xbf").lstrip()
        if head_preview.startswith(b"<?xml"):
            return "image/svg+xml"
        if head_preview[:128].lower().startswith(b"<svg"):
            return "image/svg+xml"
            
        return None

    def mime_from_url_path(url: str) -> str | None:
        path = PurePosixPath(urlparse(url).path)
        ext = path.suffix.lower()
        if not ext:
            return None
        return extension_to_mime.get(ext)

    # 给每个 ImageInfo 填写 mime_type
    out: list[ImageInfo] = []
    for item in image_infos:
        body = item.body
        
        # 没有 body
        if body is None or body == b"":
            item_copy = item.model_copy()
            item_copy.mime_type = None
            out.append(item_copy)
            continue

        # 根据 body 猜测 mime_type
        mime = mime_from_magic(bytes(body))
        if mime is None:
            # 根据 url 猜测 mime_type
            mime = mime_from_url_path(item.url)
        
        # 填写 mime_type
        item_copy = item.model_copy()
        item_copy.mime_type = mime
        out.append(item_copy)
    
    return out


def normalize_images_for_llm(image_infos: list[ImageInfo]) -> list[ImageInfo]:
    """
    清洗图片信息以供 LLM 使用：
    - 丢弃 非 jpeg、png、svg、webp 类型的图片
    - 将 svg、webp、jpeg 转换为 png
    - 最终仅输出 png（原 png 保持不变）
    """

    out_infos: list[ImageInfo] = []

    for info in image_infos:
        mime = info.mime_type
        body = info.body
        url = info.url

        if mime is None or body is None or body == b"":
            continue

        if mime not in ("image/jpeg", "image/png", "image/svg+xml", "image/webp"):
            continue

        item = info.model_copy()

        try:
            if mime == "image/svg+xml":
                png_bytes = cairosvg.svg2png(bytestring=body)
                scale = 1.0
                TARGET_EDGE = 1024
                with Image.open(io.BytesIO(png_bytes)) as img:
                    w, h = img.size
                    max_edge = max(w, h)
                    if max_edge > 0 and (max_edge < 400 or max_edge > 2000):
                        scale = TARGET_EDGE / max_edge
                if scale != 1.0:
                    png_bytes = cairosvg.svg2png(bytestring=body, scale=scale)
                with Image.open(io.BytesIO(png_bytes)) as img:
                    if img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGBA")
                    out_io = io.BytesIO()
                    img.save(out_io, format="PNG")
                    item.body = out_io.getvalue()
                    item.mime_type = "image/png"

            elif mime in ("image/webp", "image/jpeg"):
                with Image.open(io.BytesIO(body)) as img:
                    if img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGBA")
                    out_io = io.BytesIO()
                    img.save(out_io, format="PNG")
                    item.body = out_io.getvalue()
                    item.mime_type = "image/png"

            else:
                item.body = body
                item.mime_type = mime

            with Image.open(io.BytesIO(item.body)) as dim_img:
                item.wh = dim_img.size

            out_infos.append(item)
        except Exception as e:
            print(f"处理图片 {url} (类型: {mime}) 时发生错误: {e}")
            continue

    return out_infos


def compress_images(image_infos: list[ImageInfo]):
    """
    原地修改 image_infos 中的 body，压缩图片到 1MB 以内
    输入图片必须是 PNG 格式
    """

    def compress_image_one( image_binary_data: bytes, max_size_mb: float) -> tuple[bytes, tuple[int, int]]:
        """
        将 PNG 图片压缩到指定大小以内，并最大程度保留图片视觉信息。
        """
        target_bytes = int(max_size_mb * 1024 * 1024)
        original_bytes = image_binary_data

        if len(original_bytes) <= target_bytes:
            with Image.open(io.BytesIO(original_bytes)) as im:
                return original_bytes, im.size

        # 打开图片并尝试纯无损优化 (仅优化压缩字典，不改尺寸)
        img = Image.open(io.BytesIO(original_bytes))
        img.load()
        buffer = io.BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        current_size = buffer.tell()
        if current_size <= target_bytes:
            return buffer.getvalue(), img.size

        # 动态缩放逻辑
        # 初始缩放比例：根据目标体积和当前体积的比例，开平方根得到线性维度的缩放比。
        # 乘以 0.95 作为安全系数，防止压缩后刚好超标一点点。
        scale = (target_bytes / current_size) ** 0.5 * 0.95

        while scale > 0.1:  # 设定一个最低下限，防止死循环
            new_width = max(1, int(img.width * scale))
            new_height = max(1, int(img.height * scale))

            # 始终用原始 `img` 进行缩放，不使用已经被缩放过的图片，避免画质多次受损。
            # 使用 Image.Resampling.LANCZOS (高质量重采样)，保留最多的锐利度。
            resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            resized_img.save(buffer, format="PNG", optimize=True)
            size = buffer.tell()

            if size <= target_bytes:
                return buffer.getvalue(), resized_img.size
            else:
                # 如果依然超标，根据当前的差距继续下调比例
                ratio = target_bytes / size
                scale *= (ratio ** 0.5) * 0.95

        best_bytes = buffer.getvalue()
        with Image.open(io.BytesIO(best_bytes)) as out_im:
            return best_bytes, out_im.size
    
    for info in image_infos:
        new_body = b''
        new_wh = (0, 0)
        try:
            new_body, new_wh = compress_image_one(info.body, 1.0)
        except Exception as e:
            print(f"compress_images error: {e}")
        info.body = new_body
        info.wh = new_wh


async def filter_noise_images(image_infos: list[ImageInfo]) -> list[ImageInfo]:
    """
    输入 image_infos: ImageInfo 列表（含 url、body、type）
    输出 有价值的图片列表
    """
    if len(image_infos) == 0:
        return []
    prompt = f"""
# 你的任务
这是从某个网页中提取出的部分图片。帮我识别哪些是无价值的“噪音图片”

# 判断标准
噪音图片：
- 网站Logo、UI图标(icon)、交互按钮、广告图、背景装饰
- 没有任何信息的背景图、PPT背景图等
- 无信息的人物图等等
- 模糊到无法分辨的缩略图等无实质阅读价值的图片
- 没有任何信息的空白图、占位图等
有价值的图片：
- 文章核心插图、数据图表、原理图、流程图、主图等有信息价值的图片

# 注意
有些图片乍一看是数据图表或者有价值的图，但是分辨率已经低到看不清实际内容，这也算噪音图片
没有信息的图片都算作噪声，比如一个人坐在电脑前

# 输出要求
请以 JSON 格式返回
    """
    class NoiseImageItem(BaseModel):
        filename: str = Field(..., description="被判定为噪音图片的文件名")
        reason: str = Field(..., description="判定为噪音的简短理由")
    
    class NoiseImages(BaseModel):
        """噪音图片列表, 如果没有噪音图片，则noise_images为空数组[]"""
        noise_images: list[NoiseImageItem] = Field(..., description="噪音图片列表")

    
    response_format = llm.to_openrouter_response_format(NoiseImages, name="noise_images")
    prompt = prompt.strip()
    user_messages = [llm.content_text(prompt)]
    for idx, info in enumerate(image_infos):
        user_messages.append(llm.content_text(f"下面是{idx+1}.{info.suffix}"))
        base64_data = base64.b64encode(info.body).decode()
        user_messages.append(llm.content_image(base64_data, info.mime_type))
    
    messages = [
        llm.role_system("You are a helpful assistant."),
        llm.role_user(user_messages)
    ]
    
    models = [
        "google/gemini-3.1-flash-lite-preview",
        "openai/gpt-5.4-nano",
        "anthropic/claude-haiku-4.5"
    ]

    async def call_model(model: str) -> list[dict]:
        try:
            x = await llm.async_chat(llm.LLMReq(
                model=model,
                messages=messages,
                response_format=response_format,
            ))
            raw = x.choices[0].message.content
            x = json.loads(llm.strip_llm_json(raw))
            noise_images = x['noise_images']
            return noise_images
        except Exception as e:
            # print(f"[{model}] error: {e}")
            return None
    
    # 并行所有模型
    tasks = [call_model(model) for model in models]
    all_model_result = await asyncio.gather(*tasks)
    all_model_result = [result for result in all_model_result if result is not None]
    if len(all_model_result) == 0:
        print(f"filter_noise_images 所有模型都失败了")
        return []

    # 取交集
    def get_idx_set_from_one_result(result: list[dict]) -> set[int]:
        # [{filename: "3.jpg"}, {filename: "5.jpg"}] -> {2, 4}
        idxs = set()
        for item in result:
            try:
                idx = int(item["filename"].split('.')[0])
                idx -= 1
                idxs.add(idx)
            except Exception as e:
                print(f"filename error: {e}")
                continue
        return idxs
    
    # 每个模型返回一组idx(噪音图片的idx) idxs_sets [{1, 2}, {1, 2}]
    all_model_idxs_set = [get_idx_set_from_one_result(result) for result in all_model_result]
    idx_count = {} # 2 局 2 胜, 3 局 2 胜, 4 局 3 胜, 5 局 3 胜
    for idxs in all_model_idxs_set:
        for idx in idxs:
            idx_count[idx] = idx_count.get(idx, 0) + 1
    threshold = math.ceil(float(len(models)) / 2.0 + 0.01)
    noise_idxs = [idx for idx, count in idx_count.items() if count >= threshold]

    out = [] # 有价值的图片
    for idx, info in enumerate(image_infos):
        if idx not in noise_idxs:
            out.append(info.model_copy())

    return out


async def download_url_important_image_core(url: str) -> list[ImageInfo]:
    yield {"type": "log", "data": f"我要访问[{url}]，预计需要5秒"}
    markdown, html, data_type = await url_to_md(url)
    if data_type != "text":
        yield {"type": "log", "data": f"不是文本类型的网页，结束分析"}
        return
    if len(markdown) < 10:
        yield {"type": "log", "data": f"网页为空，结束分析"}
        return
    yield {"type": "log", "data": f"我成功获取了网页内容，内容长度为[{len(markdown)}]"}
    important_image_urls = await get_important_image_urls(markdown)
    yield {"type": "log", "data": f"值得进一步分析的图片有[{len(important_image_urls)}]个"}
    images = await download_images(important_image_urls, 20)
    yield {"type": "log", "data": f"下载到的图片有[{len(images)}]个"}
    image_infos = [ImageInfo(url=u, body=image) for u, image in zip(important_image_urls, images)]
    image_infos = annotate_image_mime_types(image_infos)
    image_infos = await asyncio.to_thread(normalize_images_for_llm, image_infos) # 丢弃异常图片，同时将所有图片转为 png
    await asyncio.to_thread(compress_images, image_infos) # 压缩图片到 1MB 以内，原地修改 image_infos
    image_infos = [image_info for image_info in image_infos if image_info.body is not None and image_info.body != b""] # 过滤掉 body 为空的图片

    def is_small_image(image_info: ImageInfo) -> bool:
        # 扔掉明显过小的图片
        if image_info.wh is None:
            return True
        w, h = image_info.wh
        if w is None or h is None:
            return True
        if w * h < 50000: # 50 * 1000 能承载信息吗？ 100 * 500 能承载信息吗？ 我统计了500张图片，面积小于 50000 的图片没有价值
            return True
        return False

    image_infos = [image_info for image_info in image_infos if not is_small_image(image_info)]
    image_infos = image_infos[:30] # 限制一下图片数量
    # 给所有图片添加 suffix
    for x in image_infos:
        x.suffix = x.mime_type.split('/')[-1] if x.mime_type is not None else None
    for idx, x in enumerate(image_infos):
        x.debug_name = f"{idx:03d}.{x.suffix}"
    yield {"type": "log", "data": f"准备进行价值分析的图片有[{len(image_infos)}]个"}
    image_infos_before = deepcopy(image_infos)
    image_infos = await filter_noise_images(image_infos)
    yield {"type": "result", "data": {"image_infos": image_infos, "image_infos_before": image_infos_before}}


async def get_images_from_cite(id_to_url: dict) -> dict[str, bytes]:
    """
    下载 URL 中的图片
    id_to_url { cite-id -> url }
    返回 { "图片名称": "图片二进制数据" }
    其中图片名称的格式为 [3位cite-id]-[3位图片序号].png
    """
    url_to_id = { v: k for k, v in id_to_url.items() } # 如果 url 重复则覆盖前面的 id
    urls = list(url_to_id.keys())
    sem = asyncio.Semaphore(30)

    def print_log(log: str):
        # now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # print(f"[{now}] {log}")
        pass

    async def get_result_of_download_url_important_image(url: str):
        async with sem:
            cite_id = f"{url_to_id[url]:03d}"
            try:
                async for chunk in download_url_important_image_core(url):
                    if chunk["type"] == "log":
                        print_log(f'[{cite_id}] {chunk["data"]}')
                    if chunk["type"] != "result":
                        continue
                    print_log(f'[{cite_id}] 任务完成')
                    return {"url": url, "image_infos": chunk["data"]["image_infos"]}
            except Exception as e:
                print(f"get_result_of_download_url_important_image error: {e}")
                return None
    tasks = [get_result_of_download_url_important_image(url) for url in urls]
    results = await asyncio.gather(*tasks)
    results = [result for result in results if result is not None]

    out = {} # { "图片名称": "图片二进制数据" }

    for result in results:
        url = result["url"]
        cite_id = url_to_id.get(url, "")
        if not cite_id:
            continue
        image_infos = result["image_infos"]
        for idx, image_info in enumerate(image_infos):
            name = f"{cite_id:03d}-{idx:03d}.{image_info.suffix}"
            out[name] = image_info.body

    return out


# 此注释仅为了触发 CICD