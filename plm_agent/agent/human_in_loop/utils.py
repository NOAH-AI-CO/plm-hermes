import asyncio
import json
import os
import io
import re
import shutil
import logging
import time
import traceback
import glob
import pickle
import hashlib
import requests
from urllib.parse import urlparse
from llm.deepseek_models import DeepseekChat
from utils.sql_client import get_connection_user, text
from utils.redis_client import create_engines
from config import api_config
cache = create_engines(decode_responses=False)

logger = logging.getLogger(__name__)

async def upload_archive(output_dir, object_path, bucket_name, source='azure'):
    if source == 'hw':
        from utils.obs.client import upload_file
    else:
        from utils.azure.blob_client import upload_file
    # Save report and outputs to zip file
    zip_path = f"{output_dir}.zip"
    if not os.path.exists(output_dir + '/data'):
        os.makedirs(output_dir + '/data', exist_ok=True)
    shutil.make_archive(output_dir, 'zip', output_dir)
    logger.info(f"Output saved to {zip_path}")
    
    for _ in range(3):
        res = upload_file(bucket_name, object_path, zip_path)
        if res: 
            logger.info(f"File {zip_path} uploaded successfully")
            # Delete zip and original folder when upload is successful
            try:
                os.remove(zip_path)  # Delete the zip file
                shutil.rmtree(output_dir)  # Delete the original folder
                logger.info(f"Cleaned up {zip_path} and {output_dir}")
            except Exception as e:
                logger.error(f"Failed to clean up files: {str(e)}")
            break
        await asyncio.sleep(3)
    else:
        logger.error(f"Failed to upload {zip_path}")

async def send_message_and_save(ret):
    new_ret = ret.copy()
    # for _ in range(0):
    #     yield new_ret
    #     await asyncio.sleep(0.1)
    new_ret['saveChat'] = True
    yield new_ret
        
async def send_editable_message(ret, message, editable=True):
    new_ret = ret.copy()
    new_ret['sender'] = 'assistant'
    new_ret['type'] = 'chat'
    new_ret['editable'] = editable
    new_ret['message'] = message
    async for new_ret in send_message_and_save(new_ret):
        yield new_ret
        
        
async def send_editable_rewrite_question(ret, rewrite_question, editable=True):
    new_ret = ret.copy()
    new_ret['sender'] = 'assistant'
    new_ret['type'] = 'chat'
    new_ret['editable'] = editable
    new_ret['message'] = rewrite_question
    new_ret['rewrite_question'] = rewrite_question
    async for new_ret in send_message_and_save(new_ret):
        yield new_ret
        
async def save_and_hide(ret, hide=True):
    new_ret = ret.copy()
    new_ret['saveChat'] = True
    new_ret['hide'] = hide
    yield new_ret

async def send_confirm_tool(ret, feedback, approve):
    new_ret = ret.copy()
    new_ret['type'] = 'confirmTool'
    new_ret['sender'] = 'user'
    new_ret['message'] = feedback
    new_ret['accept'] = approve
    async for new_ret in send_message_and_save(new_ret):
        yield new_ret
        
async def send_user_message(ret, message, attachments=[], folders=[]):
    new_ret = ret.copy()
    new_ret.pop('chunkIdx', None)
    new_ret['type'] = 'chat'
    new_ret['sender'] = 'user'
    new_ret['message'] = message
    if attachments:
        new_ret['files'] = [{'name': a.get('name'), 'url': a.get('url'), 'id': a.get('id')} for a in attachments]
    if folders:
        new_ret['folders'] = [{'name': f.get('name'), 'id': f.get('id'), 'full_path': f.get('full_path')} for f in folders]
    async for new_ret in send_message_and_save(new_ret):
        yield new_ret
        
async def send_agent_status_update(ret, status, countdown_seconds=10):
    new_ret = ret.copy()
    new_ret['type'] = 'statusUpdate'
    new_ret['sender'] = 'assistant'
    new_ret['agentStatus'] = status
    if status == 'waiting':
        new_ret['countDown'] = countdown_seconds
    async for new_ret in send_message_and_save(new_ret):
        yield new_ret
        
async def send_plan_update(ret):
    new_ret = ret.copy()
    new_ret['type'] = 'planUpdate'
    new_ret['message'] = ""
    async for new_ret in send_message_and_save(new_ret):
        yield new_ret
        
async def send_error_message(ret, error_message):
    new_ret = ret.copy()
    new_ret["error"] = error_message
    async for new_ret in send_message_and_save(new_ret):
        yield new_ret
        
async def check_errors(ret):
    if not ret['plan']:
        return "Planning failed"
    if ret['current_step']-1 >= len(ret['plan']):
        return "All steps completed"
    return None

async def task_with_heartbeat(gen, interval: float = 0.3, stream=False):
    r"""
    Since fetch web page contents may cost very long time. Send heartbeat at the same time to avoid connection close.
    """
    try:
        buffer = io.StringIO()
            
        newest_chunk = None
        start_time = time.time()
        last_pos = 0
        # 记录上一次的hash值，兼容增量，全量返回
        newest_hash = hashlib.sha256("".encode()).hexdigest()  
        async def write_buffer():
            nonlocal newest_chunk
            async for chunk in gen:
                if not chunk:
                    continue
                if stream:
                    buffer.write(chunk)
                else:
                    if type(chunk) == str:
                        newest_chunk = chunk
                    elif type(chunk) == dict:
                        newest_chunk = chunk
        task = asyncio.create_task(write_buffer())
        shielded = asyncio.shield(task)

        while not task.done():
            if stream:
                current_value = buffer.getvalue()
                if len(current_value) > last_pos:
                    yield current_value
                    last_pos = len(current_value)
                else:
                    # 无新数据时发送 None 作为心跳，让调用方知道任务仍在运行
                    yield None
            elif newest_chunk:
                temp_newest_str = str(newest_chunk)
                temp_newest_hash = hashlib.sha256(temp_newest_str.encode()).hexdigest()
                if temp_newest_hash != newest_hash:
                    newest_hash = temp_newest_hash
                    yield newest_chunk
            await asyncio.sleep(interval)
        
        await shielded
        end_time = time.time()
        if stream:
            current_value = buffer.getvalue()
            if len(current_value) > last_pos:
                yield current_value
        elif newest_chunk:
            temp_newest_str = str(newest_chunk)
            temp_newest_hash = hashlib.sha256(temp_newest_str.encode()).hexdigest()
            if temp_newest_hash != newest_hash:
                yield newest_chunk
        logger.info(f"[_task_with_heartbeat]{callable} cost time total {end_time - start_time}s")
    except Exception as e:
        traceback.print_exc()
        raise Exception(f"Task {gen.__name__} with heartbeat failed: {str(e)}")
    
async def process_chunks(chunk, ret, data):
    try:
        last_appearance_end = data['last_appearance_end']
        ret['plan'][ret['current_step']-1]['result'] = chunk
        if type(chunk) == dict:
            content = chunk.get('content', '')
        else:
            content = chunk
        if ret['type'] == 'thought' and type(chunk) == dict and content:
            async for _ret in send_message_and_save(ret, save=True):
                yield _ret
            ret['type'] = 'chat'
        matches = None
        if ret['type'] == 'chat':
            code_block_ranges = [(0,0)]
            # Look for code blocks in the chunk
            pattern = r'```(?:vega|mermaid)[\s\S]*?```'
            matches = list(re.finditer(pattern, content[last_appearance_end:]))
            
        # Store index ranges of all matches
        if matches:
            code_block_ranges = [(m.start(), m.end()) for m in matches]
            _last_appearance_end = last_appearance_end
            for code_block_range in code_block_ranges:
                appearance_end = code_block_range[1]
                
                latest_content = content[_last_appearance_end:_last_appearance_end+appearance_end]
                ret['message'] = latest_content
                async for _ret in send_message_and_save(ret, save=False):
                    yield _ret
                ret['chunkIdx'] += 1
                data['last_appearance_end'] = _last_appearance_end + appearance_end
            # ret['saveChat'] = False
        if ret['type'] == 'thought':
            latest_content = json.dumps(chunk, ensure_ascii=False) + '\n'
        else:
            latest_content = content[last_appearance_end:]
        ret['message'] = latest_content
        if ret['message']:
            yield ret
    except Exception as e:
        trace = traceback.format_exc()
        logger.info(f"Error in chunk processing: {trace}")
        raise e
    
def convert_md_to_docx(dir, logo_path='static/logo.png'):
    from agent.human_in_loop.md2docx import MarkdownToWordTool
    markdown_to_word_tool = MarkdownToWordTool()
    input_dir = output_dir = dir
    # 获取所有 Markdown 文件
    md_files = glob.glob(os.path.join(input_dir, "*.md"))
    
    if not md_files:
        print(f"在 {input_dir} 目录下未找到 Markdown 文件")
        return
    
    print(f"找到 {len(md_files)} 个 Markdown 文件，开始处理...")
    
    # 处理每个 Markdown 文件
    for md_file in md_files:
        # 从输入文件名获取基本文件名
        base_name = os.path.basename(md_file)
        output_filename = os.path.splitext(base_name)[0] + ".docx"
        output_path = os.path.join(output_dir, output_filename)
        
        print(f"正在处理: {md_file} -> {output_path}")
        
        # 使用run方法调用工具
        try:
            result = markdown_to_word_tool.run(
                input_path=md_file,
                output_path=output_path,
                logo_path=logo_path
            )
            
            # 打印结果
            print(result)
            print("-" * 50)
            # Delete the markdown file after successful conversion
            if os.path.exists(output_path):
                try:
                    # os.remove(md_file)
                    print(f"Successfully deleted the original markdown file: {md_file}")
                except Exception as delete_error:
                    print(f"Warning: Failed to delete {md_file}: {str(delete_error)}")
        except Exception as e:
            print(f"处理 {md_file} 时出错: {str(e)}")
            print("-" * 50)
            raise e
    
    print("所有文件处理完成！")
    
async def wait_for_confirm_tool_input(self, seconds=10):
    """
    Wait for user to confirm the tool input.
    """
    stop_auto_run = None
    for _ in range(seconds):
        stop_auto_run = cache.get(f':1:{self.thread_id}-stop-auto-run')
        if stop_auto_run:
            break
        await asyncio.sleep(1)
    else:
        stop_auto_run = cache.get(f':1:{self.thread_id}-stop-auto-run')
    if stop_auto_run:
        stop_auto_run = pickle.loads(stop_auto_run)
        self.auto_run_stopped = stop_auto_run 
        cache.delete(f':1:{self.thread_id}-stop-auto-run')
        return not stop_auto_run
    return None
        
async def wait_for_interrupt_input(self, thread_id):
    """
    Wait for user to confirm the tool input.
    """
    stop_run = cache.get(f':1:{thread_id}-stop')
    if stop_run:
        stop_run = pickle.loads(stop_run)
        cache.delete(f':1:{thread_id}-stop')
        self.stopped = True
        return stop_run
    return False

async def get_attachments(files):
    def _sync():
        try:
            with get_connection_user() as conn:
                file_contents = conn.execute(text(f"""SELECT name, url, content FROM "API_attachment" WHERE id = ANY(ARRAY[:ids]::uuid[])"""), {"ids": [f for f in files]})
                file_contents = file_contents.fetchall()
                if not file_contents:
                    raise(Exception('no file_contents found'))
                return file_contents
        except:
            traceback.print_exc()
            print('error getting attachment content')
            return {}

    return await asyncio.get_event_loop().run_in_executor(None, _sync)

def _normalize_attachment_content_mode(mode):
    normalized_mode = str(mode or 'sql').strip().lower()
    if normalized_mode not in {'sql', 'api'}:
        logger.warning(f"Unknown attachment content mode '{mode}', fallback to 'sql'")
        return 'sql'
    return normalized_mode


async def get_attachment_content(attachment_id, mode='sql', base_url=api_config.get("YH_BACKEND_URL", "http://localhost"), timeout=30):
    def _sync():
        _mode = _normalize_attachment_content_mode(mode)
        if _mode == 'api':
            token = api_config.get("YH_BACKEND_TOKEN", "")
            if not token:
                logger.error("YH_BACKEND_TOKEN is empty, cannot call attachment content API")
                return {}
            url = f"{base_url.rstrip('/')}/api/filesystem/content/"
            headers = {
                "Authorization": f"Token {token}",
            }
            params = {"attachment_id": str(attachment_id)}
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=timeout)
                resp.raise_for_status()
                return resp.json().get('content', {}) or {}
            except requests.RequestException:
                traceback.print_exc()
                logger.info(f"error getting attachment content by api: {traceback.format_exc()}")
                return {}

        try:
            with get_connection_user() as conn:
                result = conn.execute(text(f"""SELECT content FROM "API_attachment" WHERE id = :id"""), {"id": attachment_id})
                file_content = result.scalar()
                if not file_content:
                    return {}
                return file_content
        except:
            traceback.print_exc()
            print('error getting attachment content')
            return {}

    return await asyncio.get_event_loop().run_in_executor(None, _sync)

def _sanitize_for_jsonb(value):
    if isinstance(value, str):
        return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', value)
    if isinstance(value, list):
        return [_sanitize_for_jsonb(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_for_jsonb(item) for item in value)
    if isinstance(value, dict):
        sanitized = {}
        for key, val in value.items():
            safe_key = _sanitize_for_jsonb(key) if isinstance(key, str) else key
            sanitized[safe_key] = _sanitize_for_jsonb(val)
        return sanitized
    return value
    
async def update_attachment_content(attachment_id, content, mode='sql', base_url=api_config.get("YH_BACKEND_URL", "http://localhost"), timeout=30):
    def _sync():
        _mode = _normalize_attachment_content_mode(mode)
        sanitized_content = _sanitize_for_jsonb(content)

        if _mode == 'api':
            token = api_config.get("YH_BACKEND_TOKEN", "")
            if not token:
                logger.error("YH_BACKEND_TOKEN is empty, cannot call attachment content API")
                return {}
            url = f"{base_url.rstrip('/')}/api/filesystem/content/"
            headers = {
                "Authorization": f"Token {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "attachment_id": str(attachment_id),
                "content": sanitized_content,
            }
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
                resp.raise_for_status()
                return resp.json().get('content', {})
            except requests.RequestException:
                traceback.print_exc()
                logger.info(f"error updating attachment content by api: {traceback.format_exc()}")
                return {}

        try:
            with get_connection_user() as conn:
                # Merge with existing content using JSONB concatenation operator
                query = text("""UPDATE "API_attachment"
                            SET content = COALESCE(content, '{}'::jsonb) || CAST(:content AS jsonb)
                            WHERE id = :id""")
                conn.execute(query, {
                    "id": attachment_id,
                    "content": json.dumps(sanitized_content, ensure_ascii=False)
                })
                conn.commit()
        except Exception as e:
            traceback.print_exc()
            logger.info(f"error updating attachment content: {traceback.format_exc()}")
            return {}

    return await asyncio.get_event_loop().run_in_executor(None, _sync)

async def download_attachments(files, dest):
    def _sync():
        try:
            with get_connection_user() as conn:
                file_contents = conn.execute(text(f"""SELECT name, url FROM "API_attachment" WHERE id = ANY(ARRAY[:ids]::uuid[])"""), {"ids": [f for f in files]})
                file_contents = file_contents.fetchall()
                if not file_contents:
                    raise(Exception('no file_contents found'))
                for file in file_contents:
                    file_name, file_url = file
                    try:
                        response = requests.get(file_url, stream=True)
                        response.raise_for_status()

                        # Extract filename from URL if not provided
                        if not file_name:
                            parsed_url = urlparse(file_url)
                            file_name = os.path.basename(parsed_url.path) or 'downloaded_file'

                        # Ensure destination directory exists
                        os.makedirs(dest, exist_ok=True)

                        # Full path for the downloaded file
                        file_path = os.path.join(dest, file_name)

                        # Download and save the file
                        with open(file_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)

                        print(f"Downloaded: {file_name} to {file_path}")

                    except requests.RequestException as e:
                        print(f"Failed to download {file_name} from {file_url}: {str(e)}")
                    except Exception as e:
                        print(f"Error saving {file_name}: {str(e)}")
        except:
            traceback.print_exc()
            print('error getting attachment content')
            return {}

    return await asyncio.get_event_loop().run_in_executor(None, _sync)
    

async def call_index_api(attachment_ids, query, base_url=getattr(api_config, "BACKEND_URL", "http://localhost"), timeout=90, pages=[]):
    """
    Send a POST request to {base_url}/api/index/ similar to the provided curl command.
    Returns response JSON (or text if JSON decode fails). Raises requests exceptions on failure.
    """
    def _sync():
        url = f"{base_url.rstrip('/')}/api/index/"
        headers = {
            "Authorization": f"Token {api_config.BACKEND_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {"attachment_ids": attachment_ids, "query": query, "pages": pages}
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json()['chunks']
        except requests.RequestException as e:
            logger.error(f"call_index_api failed: {e}")
            return {}

    return await asyncio.get_event_loop().run_in_executor(None, _sync)
    
async def extract_page_number_from_response(q, attachment):
    json_schema = [
        {
            "type": "function",
            "function": {
                "name": "extract_page_number",
                "description": "Return a list of page numbers the user is asking about; return an empty list if no page numbers are present",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "page_numbers": {
                            "type": "array",
                            "items": {"type": "integer"},
                        }
                    },
                    "required": ["page_numbers"]
                }
            }
        }
    ]
    response = await DeepseekChat()(user_prompt=f"User prompt: {q}, they also uploaded a document with name: {attachment[0]}. Tell me if the user is trying to search for a certain page and return in json format. If no specific range is provided, return an empty list.", tools=json_schema, tool_choice={"type": "function", "function": {"name": "extract_page_number"}})
    try:
        args = response.tool_calls[0].function.arguments
        try:
            page_numbers = json.loads(args).get('page_numbers', [])
            try:
                selected_count = len(page_numbers)
                content = attachment[2].get('content', [])
                if type(content) == str:
                    content = [content]
                total_count = len(content)
                print("Selected pages:", page_numbers, "Total pages:", total_count)
                if selected_count / total_count > 0.5:
                    return []
            except:
                pass
            return page_numbers
        except:
            try:
                return args['page_numbers']
            except:
                return []
    except:
        traceback.print_exc()
        return []