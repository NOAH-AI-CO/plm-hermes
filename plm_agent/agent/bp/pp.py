import asyncio
import socket
from io import BytesIO
import time
import httpx
import pymupdf
import requests
import tiktoken
from requests.adapters import HTTPAdapter
from agent.bp.toc_builder import pages_to_toc
from agent.bp.vlm import process_markdown_images
import os
import re
import base64
from openai import AsyncOpenAI
from config import api_config
from google.genai import types

from agent.human_in_loop.utils import get_attachment_content, get_attachments, update_attachment_content
from lite_llm.aliyun_models import AliyunQwenVLOCR

gcp_key_path = "/Users/andy/repos/NoahAgent/noah_agent/gcp_key.json"
if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', ''):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path

os.environ['GOOGLE_CLOUD_PROJECT'] = "noahai-440408"
os.environ['GOOGLE_CLOUD_LOCATION'] = "global"
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"

from google import genai
from google.genai.types import HttpOptions
import json
import logging
logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

# Shared clients to avoid connection overhead and SSL shutdown issues
_genai_client = None
_httpx_client = None


class _TCPKeepAliveAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        opts = [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
        ]
        if hasattr(socket, "TCP_KEEPIDLE"):      # Linux
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60))
        elif hasattr(socket, "TCP_KEEPALIVE"):   # macOS
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, 60))
        if hasattr(socket, "TCP_KEEPINTVL"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 30))
        if hasattr(socket, "TCP_KEEPCNT"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5))
        kwargs.setdefault("socket_options", opts)
        super().init_poolmanager(*args, **kwargs)


_requests_session = requests.Session()
_requests_session.mount("http://", _TCPKeepAliveAdapter())
_requests_session.mount("https://", _TCPKeepAliveAdapter())

def get_genai_client():
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(http_options=HttpOptions(api_version="v1"))
    return _genai_client

async def get_httpx_client():
    global _httpx_client
    if _httpx_client is None:
        _httpx_client = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30.0))
    return _httpx_client

# path = "/Users/andy/Downloads/医脉通/非小细胞肺癌靶向药物治疗相关基因检测的规范建议/非小细胞肺癌靶向药物治疗相关基因检测的规范建议.pdf"
# path = "/Users/andy/Downloads/医脉通/中国胰肾联合移植临床诊疗指南/中国胰肾联合移植临床诊疗指南.pdf"


gibberish_detection_schema = {
    "type": "BOOLEAN",
}

async def detect_gibberish(text):
    client = get_genai_client()
    response = await client.aio.models.generate_content(
        model="gemini-3-flash-preview",
        contents="Help me determine if the following text is is semantically meaningful or not. Respond with true if it is semantically meaningful, false otherwise:\n\n" + text,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=gibberish_detection_schema,
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_level="low")
        ),
    )
    logger.info(f"Gibberish detection response text: {response.text}")
    json_content = json.loads(response.text)
    logger.info(f"Parsed JSON content: {json_content}")
    return json_content
    
async def call_ocr(pdf_path, data=None):
    """Perform OCR on a PDF using agent.bp.ocr utilities.

    Returns a dict similar to the output of `call_mineru`, e.g.:
    {
        'results': {
            '<pdf_name>': {
                'md_content': [page_text1, page_text2, ...],
                'images': {}
            }
        }
    }
    """
    from agent.bp import ocr as ocr_module
    import tempfile
    
    pdf_name = os.path.basename(pdf_path)
    temp_file = None
    pages_text = []

    try:
        if data:
            tf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            try:
                tf.write(data)
                tf.flush()
            finally:
                tf.close()
            temp_file = tf.name
            path = temp_file
        else:
            path = pdf_path

        loop = asyncio.get_running_loop()
        
        def _convert_sync():
            try:
                return ocr_module.convert_from_path(path)
            except Exception:
                from pdf2image import convert_from_bytes
                if data:
                    return convert_from_bytes(data)
                raise

        logger.info(f"Converting PDF {pdf_name} to images in thread pool...")
        images = await loop.run_in_executor(None, _convert_sync)

        logger.info(f"PDF converted to {len(images)} images. Starting concurrent OCR...")

        ocr_model = AliyunQwenVLOCR()
        # 还是要控制下并发数量
        sem = asyncio.Semaphore(20)

        async def _process_page(img):
            async with sem:
                try:
                    messages = ocr_model.build_ocr_message(img)
                    res = await ocr_model.generate(input=messages)
                    # print("OCR result:")
                    # print(res)
                    return res if res else ""
                except Exception as e:
                    logger.error(f"OCR failed for a page: {e}")
                    return ""

        tasks = [_process_page(img) for img in images]
        
        pages_text = await asyncio.gather(*tasks)

        result = {
            'results': {
                pdf_name: {
                    'md_content': pages_text,
                    'images': {}
                }
            }
        }

        logger.info(f"OCR parsed pages: {len(pages_text)} for {pdf_name}")
        return result
    finally:
        if temp_file:
            try:
                os.remove(temp_file)
            except Exception:
                pass

def call_mineru(pdf_path, data=None):
    url = "http://136.110.229.215/file_parse"
    # url = "http://35.245.87.40:8000/file_parse"
    # url = "http://localhost:8001/file_parse"

    clean_path = pdf_path.split('?')[0]
    pdf_name = os.path.basename(clean_path) or f"{time.time()}.pdf"

    form_data = {
        'backend': 'pipeline',
        'formula_enable': 'false',
        'table_enable': 'false',
        'return_images': 'true',
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            if data:
                files = {'files': (pdf_name, BytesIO(data), 'application/pdf')}
                response = _requests_session.post(url, files=files, data=form_data, timeout=(20, 900), stream=True)
            else:
                with open(pdf_path, 'rb') as f:
                    files = {'files': (pdf_name, f, 'application/pdf')}
                    response = _requests_session.post(url, files=files, data=form_data, timeout=(20, 900), stream=True)
            response.raise_for_status()
            raw_content = b"".join(response.iter_content(chunk_size=65536))
            return json.loads(raw_content)
        except requests.exceptions.ChunkedEncodingError as exc:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(
                    "call_mineru ChunkedEncodingError on attempt %d/%d, retrying in %ds: %s",
                    attempt + 1, max_retries, wait, exc,
                )
                time.sleep(wait)
            else:
                raise

async def call_vlm(pdf_path, data=None):
    """Perform VLM processing on a PDF using Aliyun Qwen VL model.

    Returns a dict similar to the output of `call_mineru`, e.g.:
    {
        'results': {
            '<pdf_name>': {
                'md_content': [page_text1, page_text2, ...],
                'images': {}
            }
        }
    }
    """
    from agent.bp import ocr as ocr_module
    import tempfile
    
    # Initialize OpenAI client with Aliyun Dashscope
    client = AsyncOpenAI(
        api_key=api_config.ALIYUN_BAILIAN_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    
    pdf_name = os.path.basename(pdf_path)
    temp_file = None
    pages_text = []

    try:
        if data:
            tf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            try:
                tf.write(data)
                tf.flush()
            finally:
                tf.close()
            temp_file = tf.name
            path = temp_file
        else:
            path = pdf_path

        loop = asyncio.get_running_loop()
        
        def _convert_sync():
            try:
                return ocr_module.convert_from_path(path, dpi=100)
            except Exception:
                from pdf2image import convert_from_bytes
                if data:
                    return convert_from_bytes(data, dpi=100)
                raise

        logger.info(f"Converting PDF {pdf_name} to images in thread pool...")
        images = await loop.run_in_executor(None, _convert_sync)

        logger.info(f"PDF converted to {len(images)} images. Starting concurrent VLM processing...")

        # Control concurrency
        sem = asyncio.Semaphore(100)

        async def _process_page_with_vlm(i, img, detailed=1):
            from agent.bp.vlm import detailed_text_map
            async with sem:
                try:
                    # Convert PIL image to base64
                    buffered = BytesIO()
                    img.save(buffered, format="JPEG")
                    img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
                    img_data_uri = f"data:image/jpeg;base64,{img_base64}"
                    
                    # Send to VLM with retry logic
                    max_retries = 3
                    start_time = time.time()
                    for attempt in range(max_retries):
                        try:
                            completion = await client.chat.completions.create(
                                model="qwen3-vl-plus",
                                messages=[
                                    {
                                        "role": "user",
                                        "content": [
                                            {
                                                "type": "image_url",
                                                "image_url": {
                                                    "url": img_data_uri
                                                },
                                            },
                                            {
                                                "type": "text",
                                                "text": f"请提取这个图片的文字和内容,返回文本{ detailed_text_map.get(detailed, '') }。"
                                            },
                                        ],
                                    }
                                ],
                            )
                            if completion.usage:
                                elapsed = time.time() - start_time
                                logger.info(f"Page {i+1} token usage - Input: {completion.usage.prompt_tokens}, Output: {completion.usage.completion_tokens}, Total: {completion.usage.total_tokens}, Time: {elapsed:.2f}s")
                            res = completion.choices[0].message.content
                            logger.info(f"VLM result for page {i+1}: {res[:100] if res else 'None'}...")
                            return res if res else ""
                        except Exception as e:
                            if attempt < max_retries - 1:
                                wait_time = 2 ** attempt
                                logger.warning(f"VLM attempt {attempt + 1}/{max_retries} failed, waiting {wait_time}s: {e}")
                                await asyncio.sleep(wait_time)
                            else:
                                logger.error(f"VLM failed for page {i+1} after {max_retries} attempts: {e}")
                                raise
                    return ""
                except Exception as e:
                    logger.error(f"VLM processing failed for page {i+1}: {e}")
                    return ""

        tasks = [_process_page_with_vlm(i, img) for i, img in enumerate(images)]
        
        pages_text = await asyncio.gather(*tasks)

        result = {
            'results': {
                pdf_name: {
                    'md_content': pages_text,
                    'images': {}
                }
            }
        }

        logger.info(f"VLM parsed pages: {len(pages_text)} for {pdf_name}")
        return result
    finally:
        if temp_file:
            try:
                os.remove(temp_file)
            except Exception:
                pass
            
def clean_text(text):
    # Remove control characters like \u0007, \u0003, etc. but keep \n, \r, \t
    # return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text).strip()
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

def normalize_pages_content(content, file_name=""):
    if content is None:
        return []

    if isinstance(content, (list, tuple)):
        return ["" if page is None else str(page) for page in content]

    if isinstance(content, str):
        stripped = content.strip()
        if not stripped:
            return []
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return ["" if page is None else str(page) for page in parsed]
            except Exception:
                pass
        return [content]

    if isinstance(content, dict):
        if "md_content" in content:
            return normalize_pages_content(content.get("md_content"), file_name=file_name)
        if "pages" in content:
            return normalize_pages_content(content.get("pages"), file_name=file_name)

        numeric_keys = [k for k in content.keys() if str(k).isdigit()]
        if numeric_keys and len(numeric_keys) == len(content):
            ordered_keys = sorted(numeric_keys, key=lambda key: int(key))
            return ["" if content[key] is None else str(content[key]) for key in ordered_keys]

        logger.warning(f"Unexpected dict content format for {file_name or 'unknown file'}; converting to JSON string page")
        return [json.dumps(content, ensure_ascii=False)]

    logger.warning(
        f"Unexpected content type for {file_name or 'unknown file'}: {type(content).__name__}; coercing to single page"
    )
    return [str(content)]

async def get_text(path, stream=False):
    import functools

    # Detect file type from path (strip query params for URLs)
    raw_ext = path.split('.')[-1].split('?')[0].lower() if '.' in path else ''
    file_name = os.path.basename(path.split('?')[0])

    if raw_ext in ('md', 'txt'):
        if stream:
            client = await get_httpx_client()
            r = await client.get(path)
            if r.status_code != 200:
                logger.error(f"Failed to download file from {path}: Status {r.status_code}")
                raise Exception(f"Failed to download file: Status {r.status_code}")
            text_content = r.text
        else:
            with open(path, 'r', encoding='utf-8') as f:
                text_content = f.read()
        logger.info(f"Read {raw_ext.upper()} file directly: {file_name}, length={len(text_content)}")
        return {
            'results': {
                file_name: {
                    'md_content': [text_content],
                    'images': {}
                }
            }
        }

    data = None
    if not stream:
        doc = pymupdf.open(path) # open a document
    else:
        client = await get_httpx_client()
        r = await client.get(path)
        if r.status_code != 200:
            logger.error(f"Failed to download file from {path}: Status {r.status_code}, Response: {r.text[:200]}")
            raise Exception(f"Failed to download file: Status {r.status_code}")
            
        data = r.content
        if not data:
            raise Exception(f"Downloaded file content is empty for {path}")
            
        filetype = path.split('.')[-1].split('?')[0].lower() if '.' in path else 'pdf'
        if len(filetype) > 4 or '/' in filetype:
            filetype = 'pdf'

        try:
            doc = pymupdf.Document(stream=data, filetype=filetype)
        except Exception as e:
            logger.error(f"Failed to open document stream. Content length: {len(data)}, Filetype: {filetype}")
            try:
                logger.error(f"Content preview: {data[:500]}")
            except:
                pass
            raise e
    pages = []
    total = 0
    for page in doc: # iterate the document pages
        text = clean_text(page.get_text()) # get plain text encoded as UTF-8
        pages.append(text.strip())
        total += len(text)
    # print(total)
    p_contents = set()
    for p in pages:
        p_contents.add(p.strip())
    logger.info(f"Total pages: {len(pages)}")
    unique_pages = len(p_contents)
    logger.info(f"Unique page count: {len(p_contents)}")
    empty_pages = sum(1 for p in pages if not p.strip())
    logger.info(f"Empty pages: {empty_pages}")
    first_page = pages[0].strip()
    logger.info(f"First page preview:\n{first_page[:500]}\n")
    first_few_pages = "\n".join(pages[:3])
    
    if empty_pages / len(pages) > 0.6 or unique_pages / len(pages) < 0.3:
        is_image_type = True
    else:
        is_image_type = False
        if not await detect_gibberish(first_few_pages):
            logger.info("WARNING: Extracted text appears to be gibberish non meaningful content!")
    kwargs = {"data": data} if stream else {}

    if is_image_type:
        logger.info(f"Delegating to OCR (Async) for {path}...")
        # return await call_ocr(path, **kwargs)
        return await call_vlm(path, **kwargs)
    else:
        logger.info(f"Delegating to MinerU (Thread Pool) for {path}...")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, 
            functools.partial(call_mineru, path, **kwargs)
        )
        
default_question = 'What are these documents about?'

section_selection_schema = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "section": {"type": "STRING"},
            "page_range": {"type": "STRING"},
        },
        "required": ["section", "page_range"]
    }
}

toc_reading_prompt = """
You are an expert at selecting relevant sections from a document based on a user query and the document's Table of Contents (TOC).

<Query>
{query}
</Query>

<TOC>
{toc}
</TOC>

Select the sections from the TOC that are most relevant to answering the query.
Output a JSON list of the selected sections and their page ranges. Page range should include the starting page all the way up to the start of next section.
If no sections are relevant, output an empty list [].
"""

async def select_sections(query, toc):
    client = get_genai_client()
    
    max_retries = 3
    base_delay = 1
    
    for attempt in range(max_retries):
        try:
            response = await client.aio.models.generate_content(
                model="gemini-3.1-pro-preview",
                contents=toc_reading_prompt.format(query=query, toc=toc),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=section_selection_schema,
                    temperature=0,
                    thinking_config=types.ThinkingConfig(thinking_level="low")
            ),
            )
            break
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"All {max_retries} attempts failed")
                raise

    logger.info(f"Selected sections: {response.text}")
    json_content = json.loads(response.text)
    return json_content

async def parse_and_select(
    path,
    doc_name=None,
    query=default_question,
    remote_path=False,
    attachment_id=None,
    parse_only=False,
    detailed=2,
    include_toc=False,
    mode='sql',
):

    attachment_content = {}
    file_name = doc_name or path
    if attachment_id:
        attachment_content = await get_attachment_content(attachment_id, mode=mode)
    content = attachment_content.get('content', [])
    toc = attachment_content.get('toc', '')
    mode = attachment_content.get('mode', '')
    cached_detailed = attachment_content.get('detailed_level', None)
    
    if not content or mode != 'inhouse' or (cached_detailed != detailed):
        # concurrently fetch parsed results for all paths
        parsed_dict = await get_text(path, stream=remote_path)

        # combine results from all parsed documents
        if not isinstance(parsed_dict, dict):
            logger.error(f"Parsed result is not a dict: {parsed_dict}")
            return ""
        results = parsed_dict.get('results', {})

        # create tasks to process markdown images concurrently
        for file_name, result in results.items():
            if not isinstance(result, dict):
                logger.warning(f"Parsed result for {file_name} is not a dict, got {type(result).__name__}")
                result = {'md_content': result, 'images': {}}

            images = result.get('images', {})
            parsed_pages = normalize_pages_content(result.get('md_content', []), file_name=file_name)
            if not images:
                content = parsed_pages
            else:
                processed_content = await process_markdown_images(parsed_pages, images, detailed=detailed)
                content = normalize_pages_content(processed_content if processed_content is not None else parsed_pages, file_name=file_name)
            break
    
        file_name = doc_name or file_name

        # with open(f'{file_name}.json', 'w') as f:
        #     json.dump(pages, f, indent=2, ensure_ascii=False)
        logger.info(f"File: {file_name}, Processed text length: {len(str(content)) if content else 0}")
        
        if attachment_id:
            encoding = tiktoken.get_encoding("cl100k_base") 
            attachment_content['toc'] = toc
            attachment_content['content'] = content
            attachment_content['mode'] = 'inhouse'
            attachment_content['detailed_level'] = detailed
            attachment_content['tokens'] = len(encoding.encode(str(content))) if content else 0
            await update_attachment_content(attachment_id, attachment_content, mode=mode)

    content = normalize_pages_content(content, file_name=file_name)
        
    if parse_only:
        return content
    
    if not isinstance(content, list):
        raise Exception("Content should be a list of pages")
    
    if not toc or mode != 'inhouse':
        encoding = tiktoken.get_encoding("cl100k_base") 
        toc = await pages_to_toc(content)
        attachment_content['toc'] = toc
        attachment_content['content'] = content
        attachment_content['mode'] = 'inhouse'
        attachment_content['tokens'] = len(encoding.encode(str(content))) if content else 0
        await update_attachment_content(attachment_id, attachment_content, mode=mode)
        
    if include_toc:
        return content, toc
    
    selected_sections = await select_sections(query, toc)
    
    selected_pages_content = [f"# Document: {file_name}\n## Table of Contents:\n{toc}\n## Relevant Content:\n"]
    
    # Group sections by page_range to deduplicate
    page_range_map = {}
    for section in selected_sections:
        page_range = section.get('page_range')
        section_title = section.get('section', '')
        if not page_range:
            continue
        
        if page_range not in page_range_map:
            page_range_map[page_range] = []
        page_range_map[page_range].append(section_title)
    
    # Process each unique page range once
    for page_range, section_titles in page_range_map.items():
        try:
            if '-' in page_range:
                start_page, end_page = map(int, page_range.split('-'))
                # Slice is exclusive at the end, so we use end_page directly to include it (assuming 1-based indexing)
                # E.g. 5-5 means page 5. content[4:5]
                # E.g. 5-6 means page 5,6. content[4:6]
                section_content = "\n".join(content[start_page-1:end_page])
            else:
                page_num = int(page_range)
                section_content = content[page_num-1]
            
            # Merge section titles
            merged_titles = " / ".join(section_titles) if section_titles else ""
            title_prefix = f"### Sections: {merged_titles}\n" if merged_titles else ""
            
            section_content = [f"<Page {page_range}>\n{title_prefix}" + section_content + f"\n</Page {page_range}>\n"] 
                
            selected_pages_content.extend(section_content)
        except Exception as e:
            logger.error(f"Error processing page range {page_range}: {e}")
            continue
        
    logger.info(f"Selected pages content length: {len(selected_pages_content)}")
    logger.info(f"Selected pages content preview: {'\n'.join(c[:150] for c in selected_pages_content)}")
        
    
    return selected_pages_content
    

async def combine_content_and_query(contents: list | tuple, query: str, get_query_answer=True):
    header = "Heres a list of documents, their TOCs and selected relevant content:\n\n" if get_query_answer else ""
    footer = f"\n\nProvide a concise answer for the following query based on the relevant content from the documents.\n\nQuery: {query}" if get_query_answer else ""
    
    encoding = tiktoken.get_encoding("cl100k_base") 
    
    total_tokens = len(encoding.encode(header)) + len(encoding.encode(footer)) if get_query_answer else 0
    MAX_TOKENS = 200000
    
    final_chunks = []
    
    def flatten_chunks(chunks):
        if isinstance(chunks, str):
            yield chunks
        elif isinstance(chunks, (list, tuple)):
            for item in chunks:
                yield from flatten_chunks(item)

    for doc_chunks in contents:
        for chunk in flatten_chunks(doc_chunks):
            chunk_tokens = len(encoding.encode(chunk))
            if total_tokens + chunk_tokens > MAX_TOKENS:
                logger.warning(f"Token limit reached ({MAX_TOKENS}). Truncating remaining content.")
                break
            final_chunks.append(chunk)
            total_tokens += chunk_tokens
            
        if total_tokens > MAX_TOKENS:
            break
            
    combined_content = header + "\n".join(final_chunks) + footer
    
    logger.info(f"Combined content token count: {total_tokens}")
    with open('combined_content.txt', 'w', encoding='utf-8') as f:
        f.write(combined_content)
    logger.info("Combined content written to combined_content.txt")
    
    if not get_query_answer:
        return combined_content
        
    client = get_genai_client()
    
    max_retries = 3
    base_delay = 1
    
    for attempt in range(max_retries):
        try:
            response = await client.aio.models.generate_content(
                model="gemini-3-flash-preview",
                contents=combined_content,
                config={
                    "temperature": 0,
                },
            )
            logger.info(f"Answer: {response.text}")
            return response.text
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"All {max_retries} attempts failed")
                raise
    return None

async def fetch_context(paths: list[str], doc_names: list[str], attachment_ids: list[str]=None, query=default_question, parse_only=False, detailed=2, include_toc=False):
    # concurrently fetch parsed results for all paths
    start = time.time()
    if not attachment_ids:
        attachment_ids = [None] * len(paths)
    
    tasks = [parse_and_select(path, doc_name, query, remote_path=True, attachment_id=attachment_id, parse_only=parse_only, detailed=detailed, include_toc=include_toc) for path, doc_name, attachment_id in zip(paths, doc_names, attachment_ids)]
    ret = await asyncio.gather(*tasks)
    if parse_only or include_toc:
        return ret
    context = await combine_content_and_query(ret, query, False)
    end = time.time()
    logger.info(f"fetch_context for {doc_names} Total processing time: {end - start} seconds")
    return context

async def fetch_context_single(
    path: str,
    doc_name: str,
    attachment_id: str=None,
    query=default_question,
    parse_only=False,
    detailed=2,
    include_toc=False,
    mode='sql',
):
    # concurrently fetch parsed results for all paths
    start = time.time()
    if not attachment_id:
        attachment_id = None
    task = parse_and_select(
        path,
        doc_name,
        query,
        remote_path=True,
        attachment_id=attachment_id,
        parse_only=parse_only,
        detailed=detailed,
        include_toc=include_toc,
        mode=mode,
    )
    ret = await task
    if parse_only or include_toc:
        return ret
    context = await combine_content_and_query(ret, query, False)
    end = time.time()
    logger.info(f"fetch_context for {doc_name} Total processing time: {end - start} seconds")
    return context

if __name__ == "__main__":
    start = time.time()
    # ret = asyncio.run(parse_and_query(['/Users/andy/Downloads/BP.pdf','/Users/andy/Downloads/gender-analysis-barriers-immunization-indonesia(1).pdf'], 'What are these documents about?'))
    async def main():
        return await asyncio.gather(
            # parse_and_select('/Users/andy/Downloads/BP.pdf', 'What is this document about?'),
            # parse_and_select('/Users/andy/Downloads/gender-analysis-barriers-immunization-indonesia(1).pdf', 'What is this document about?')
            parse_and_select('/Users/andy/Downloads/抗肿瘤药在东西方人群差异 2021-05-23 10.33.pdf', 'What is this document about?')
        )
    ret = asyncio.run(main())
    combined_answer = asyncio.run(combine_content_and_query(ret, 'What are these documents about?'))
    # logger.info(f"Combined Answer: {combined_answer}")
    # asyncio.run(main())
    end = time.time()
    logger.info(f"P1 Total processing time: {end - start} seconds")
    # asyncio.run(parse_and_query('/Users/andy/Downloads/PDF合并(2).pdf'))
        # logger.info(f"File: {file_name}, Text length: {len(text)}, Images count: {len(images)}")
        
    # pdf_to_text(path)
    
    
    # end = time.time()
    # logger.info(f"P2 Total processing time: {end - start} seconds")
    # pages = pdf_to_text(path, by_page=True)
    # first_page = pages[0].strip()
    # print(f"First page preview:\n{first_page[:500]}\n")
    # print(f"Pages: {pages}")
    # if first_page:
    #     if not detect_gibberish(first_page):
    #         print("WARNING: Extracted text appears to be gibberish!")
    