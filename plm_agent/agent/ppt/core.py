import asyncio
from enum import Enum
import logging
import os
import base64
import json
import random
import re
import time
from typing import AsyncIterator, Awaitable, Literal
import httpx
from pydantic import BaseModel, Field
from config import api_config
from agent.ppt.code_fix import fix_bug
from utils.sql_client import get_connection_user
from sqlalchemy import text
from azure.storage.blob.aio import BlobServiceClient
from .llm import LLMReq, async_stream, role_user, role_system, content_text, content_image
from .utils import arequest_with_retry
from .prompt import make_prompt
from .get_image import get_images_from_cite

logger = logging.getLogger(__name__)

# PPTXSDKDOC_URL = "http://localhost:10001/api/v1/get_pptxsdk_info" # 本地调试
# CODE2PPTX_URL = "http://localhost:10001/api/v1/makeppt" # 本地调试
# PPTXSDKDOC_URL = "http://noah-ppt-sandbox:10001/api/v1/get_pptxsdk_info" # 线上
# CODE2PPTX_URL = "http://noah-ppt-sandbox:10001/api/v1/makeppt" # 线上
PPTXSDKDOC_URL = api_config.PPTXSDKDOC_URL # 线上
CODE2PPTX_URL = api_config.CODE2PPTX_URL # 线上


class AgentStatus(str, Enum):
    START = "start"
    RUNNING = "running"
    STOPPED = "stopped"


class DataPPT(BaseModel):
    total_page_count: int = 0
    title: str = ""
    images: list[dict] = Field(default_factory=list)  # [{"url": "xxx"}]
    pptx: dict = Field(default_factory=dict)  # {"url": "xxx"}
    source_task_id: str = ""


class DataForFrontend(BaseModel):
    agentStatus: AgentStatus = AgentStatus.START
    agent: Literal["pptx"] = "pptx"
    type: Literal["pptx"] = "pptx"
    sender: Literal["assistant"] = "assistant"
    message: DataPPT = Field(default_factory=DataPPT)
    startedAt: int = 0

    def to_json_string(self) -> str:
        d = self.model_dump() # 先转为 python 字典
        d['message'] = json.dumps(d['message'], ensure_ascii=False) # 前端需要这个字段为字符串
        d = json.dumps(d, ensure_ascii=False)
        return d


def get_cite_id_to_url(report: str) -> dict[int, str]:
    """
    从 report 中提取 cite-id -> url 的 MAP
    """
    import re

    ref_line = re.compile(r"^\s*(?:-\s*)?\[\d+\]\.\s.*https?://")
    link = re.compile(r"\[(\d+)\]\((https?://[^)]+)\)")

    # 1. 删除所有匹配引用行正则的行，将处理后的结果给到 new_report 变量
    lines = report.split("\n")
    new_report = "\n".join(ln for ln in lines if not ref_line.match(ln)).rstrip()

    # 2. 从 new_report 中提取 id -> url 的 MAP，赋值给 id_to_url 变量
    id_to_url: dict[int, str] = {}
    for m in link.finditer(new_report):
        k = int(m.group(1))
        if k not in id_to_url:
            id_to_url[k] = m.group(2)

    # 3. 找到 new_report 中所有的 [数字](URL) 这样的格式，使用 [cite:ID] 这样的格式替换
    new_report = link.sub(lambda m: f"[cite:{m.group(1)}]", new_report)

    return new_report, id_to_url


def clean_report(report: str) -> str:
    """删除报告中没用的内容"""
    # 删除报告中的引用
    # report = re.sub(r"\[\d+\]\([^)]+\)", "", report)
    # 删除报告尾部的 "## 下载链接：[结果与数据]"
    idx = report.rfind("## 下载链接：[结果与数据]")
    if idx != -1:
        report = report[:idx]
    # 删除报告尾部的 "## Download link: [Results & Data]"
    idx = report.rfind("## Download link: [Results & Data]")
    if idx != -1:
        report = report[:idx]
    return report


async def get_prompt(report: str):
    try:
        report = clean_report(report)
        async with httpx.AsyncClient() as client:
            response = await client.get(PPTXSDKDOC_URL)
            pptxsdkdoc = response.text
        prompt = make_prompt(report, pptxsdkdoc)
        return prompt
    except Exception as e:
        m = f"get_prompt 失败 {e}"
        logger.error(m)
        raise Exception(m)


def is_code_danger(code: str) -> bool:
    """
    代码安全检查，禁止 删库跑路 ! [开启子进程 执行系统命令 读写文件 网络访问 危险函数 ...]
    """
    return False


def clean_python_code(code: str) -> tuple[int, str]:
    """
    code 是不完整的 python 代码， 把他做成可执行的 python 代码
    原理是找到最后一个 def make_page_[number](): 然后删除后面所有内容
    然后添加调用所有 make_page_[number](): 的代码和PRS.save(OUTPUT_PATH)
    """
    matches = list(re.finditer(r"def make_page_\d+\(\):", code))
    if len(matches) < 2:
        return 0, ""

    make_page_functions = []  # ['def make_page_1():', 'def make_page_2():', ...]
    for x in matches:
        y = code[x.start() : x.end()]  # 'def make_page_1():'
        z = re.search(r"(make_page_[\d]+)", y)
        if z:
            make_page_functions.append(z.group(1))
        else:
            m = f"make_page_functions 匹配失败: {y}"
            logger.error(m)
            raise Exception(m)

    code = code[: matches[-1].start()]
    code += "\n"
    make_page_functions = make_page_functions[:-1]
    for x in make_page_functions:
        code += f"{x}()\n"
    code += "PRS.save(OUTPUT_PATH)\n"
    return len(make_page_functions), code


def extract_total_count(code: str) -> int:
    """
    提取 code 中 TOTAL_PAGE_COUNT 的值
    TOTAL_PAGE_COUNT = 15
    """
    # 删除最后一行（防止 TOTAL_PAGE_COUNT = 1）
    lines = code.split("\n")
    if len(lines) > 0:
        lines = lines[:-1]
    code = "\n".join(lines)
    matches = list(re.finditer(r"TOTAL_PAGE_COUNT[ ]*=[ ]*(\d+)", code))
    if len(matches) != 1:
        return 0
    return int(matches[0].group(1))


def extract_title(code: str) -> str:
    """
    提取 code 中 PPT_TITLE 的值
    PPT_TITLE = "xxx"
    同时替换标题中的所有特殊字符
    """
    # 删除最后一行（防止 PPT_TITLE = "xx）
    lines = code.split("\n")
    if len(lines) > 0:
        lines = lines[:-1]
    code = "\n".join(lines)

    # 找到标题
    matches = list(re.finditer(r'PPT_TITLE[ ]*=[ ]*["\']([^"\']*)["\']', code))
    if len(matches) != 1:
        return ""
    # 整理标题
    title = matches[0].group(1)
    bad_title_chars = (" ", "\t", "\n", "\r", "\u00a0", "/", "\\", ":", "*", "?", "<", ">", "|", '"', "'", "`", "~", "!", "@", "#", "$", "%", "&", ";", "(", ")", "[", "]", "{", "}", ".", ",", "。", "，", "、", "：", "；", "？", "！", "（", "）", "【", "】", "《", "》")
    for ch in bad_title_chars:
        title = title.replace(ch, "-")
    if len(title) > 100:
        title = title[:100]
    return title


async def code_to_pptx(code: str, first_page: int, last_page: int, base64_images: dict) -> dict:
    """
    执行 python 代码，生成 pptx 和预览图
    base64_images: {name -> b64data}, PPT代码所需要的图片资源
    first_page: 从第几页开始，最小是 1
    last_page: 到第几页结束，包含这一页
    如果 last_page 为 -1，则表示制作到最后一页
    """
    result = {
        "pptx_data": b"",
        "images": [],
        "stderr": "",
        "python_return_code": 0
    }

    if is_code_danger(code):
        m = f"is_code_danger 失败, {code}"
        logger.error(m)
        raise Exception(m)

    # 制作 pptx 并获取图片
    payload = {
        "code": code,
        "first_page": first_page,  # 从第几页开始，最小是 1
        "last_page": last_page,  # 到第几页结束，包含这一页
        "base64_images": base64_images
    }
    resp_json = {} # {code: int, message: str, data: any} # data {"base64_pptx": "xxx", "base64_images": ["xxx", "xxx", ...], "stdout": "", "stderr": "", "python_return_code": 0}
    try:
        async with httpx.AsyncClient(timeout=150) as client:
            # 如果这里重试之后依然失败，就会抛出异常
            response = await arequest_with_retry(client, "POST", CODE2PPTX_URL, json=payload)
            resp_json = response.json()
            api_code = resp_json.get('code')
            if api_code is not None and api_code != 0:
                raise Exception("resp_json['code'] != 0")
    except Exception as e:
        m = f"code_to_pptx 失败1 {e}"
        logger.error(m)
        raise Exception(m)

    try:
        job_result = resp_json['data']
        if job_result['python_return_code'] != 0 or job_result['stderr'] != "":
            result['python_return_code'] = job_result['python_return_code']
            result['stderr'] = job_result['stderr']
            return result
        # 服务器返回的是 base64 编码的数据，需要解码
        result['pptx_data'] = base64.b64decode(job_result["base64_pptx"])
        images = []
        for i in range(len(job_result["base64_images"])):
            images.append(base64.b64decode(job_result["base64_images"][i]))
        result['images'] = images
    except Exception as e:
        m = f"code_to_pptx 失败2 {e}"
        logger.error(m)
        raise Exception(m)

    return result


def is_code_to_pptx_error(result: dict) -> bool:
    """
    判断 code_to_pptx 是否失败
    """
    return result['python_return_code'] != 0 or result['stderr'] != ""


def get_stdout_stderr_content(result: dict) -> str:
    """
    获取 stdout 和 stderr 的内容
    """
    stdout = result.get('stdout', '')
    stderr = result.get('stderr', '')
    stdout = stdout[:20000]
    stderr = stderr[:20000]
    return f"stdout:\n{stdout}\nstderr:\n{stderr}\n"


async def call_llm(messages: list, openrouter: bool) -> AsyncIterator[str]:
    """
    llm组件还没稳定，这里对llm组件的变动进行屏蔽，总之我要一个输入，然后输出一个流式内容
    图片：单张图片体积（API内联传递）：最大 5 MB，总请求最大 20MB(不同供应商不一样，20MB最保险)，最多100张图片
    """
    def _log_call_llm_exception(exc: BaseException) -> None:
        import io
        import pprint
        import traceback

        buf = io.StringIO()
        try:
            traceback.print_exception(exc, file=buf, chain=True)
        except TypeError:
            traceback.print_exception(type(exc), exc, exc.__traceback__, chain=True, file=buf)
        logger.warning("call_llm 失败 traceback+串联异常:\n%s", buf.getvalue())
        vd = getattr(exc, "__dict__", None)
        if isinstance(vd, dict) and vd:
            logger.warning("call_llm 失败 exc.__dict__:\n%s", pprint.pformat(vd, indent=2, width=200))

    try:
        if openrouter:
            # model = 'anthropic/claude-sonnet-4.6'
            # model = 'anthropic/claude-opus-4.6'
            model = 'anthropic/claude-opus-4.7'
            # model = 'minimax/minimax-m2.5'
            # model = 'moonshotai/kimi-k2.6'
            # model = 'google/gemini-3-flash-preview'
            # model = 'google/gemini-3.1-pro-preview'
            # model = 'google/gemini-3.1-flash-lite-preview'
            # model = "openai/gpt-5.5"
            req = LLMReq(model=model, messages=messages, reasoning_effort="medium")
            async for chunk in async_stream(req):
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        else:
            from lite_llm.composite_models import CompositeModel
            from lite_llm.azure_claude import AzureClaudeSonnet45
            from lite_llm.google_models import Gemini31Pro, Gemini3FlastLite
            llm = CompositeModel([Gemini31Pro(), AzureClaudeSonnet45(), Gemini3FlastLite()])
            async for chunk in llm.stream_generate(
                input=[{"role": "user", "content": messages[1]['content'][0]['text']}],
                sys_prompt="You are a helpful assistant.",
                reasoning={"effort": "medium"},
            ):
                yield chunk
    except Exception as e:
        _log_call_llm_exception(e)
        raise Exception(f"call_llm 失败 {e}") from e


async def upload_file_to_oss(object_key, data):
    async with BlobServiceClient.from_connection_string(
        api_config.get('AZURE_STORAGE_CONNECTION_STRING'),
        connection_timeout=500,
        read_timeout=500
    ) as client:
        container = client.get_container_client("nudata")
        blob = container.get_blob_client(object_key)
        await blob.upload_blob(data, blob_type="BlockBlob", overwrite=True, timeout=500)
        return blob.url


async def is_pptx_exists(taskid: str) -> bool:
    """
    TODO 检查这个 taskid 是否已经做过 pptx，后续放到数据库
    """
    async with BlobServiceClient.from_connection_string(
        api_config.get('AZURE_STORAGE_CONNECTION_STRING'),
        connection_timeout=500,
        read_timeout=500
    ) as client:
        container = client.get_container_client("nudata")
        blob = container.get_blob_client(f"pptx/{taskid}/start.txt")
        return await blob.exists()


async def upload_pptx_start(taskid: str):
    """
    TODO 上传 pptx 开始的标志文件，后续放到数据库
    """
    boj_key = f'pptx/{taskid}/start.txt'
    await upload_file_to_oss(boj_key, b'start')


async def save_file(file_path: str, data: bytes) -> str:
    """
    保存文件到云存储，返回文件的下载链接
    """
    return await upload_file_to_oss(file_path, data)
    # 本地调试
    file_path = os.path.join('/Users/tanght/noah/code/NoahAgent/noah_agent/tmp/', file_path)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(data)
    return file_path


class ReportToPPTXContext(BaseModel):
    report: str = ""
    thread_id: str = ""
    taskid: str = ""
    start_time: int = 0
    openrouter: bool = False # 是否使用 openrouter
    images: dict = {}
    times: int = 0


async def report_to_pptx(ctx: ReportToPPTXContext) -> AsyncIterator[DataForFrontend]:
    """
    将 report 制作为 pptx
    """
    if ctx.report.strip() == "" or ctx.taskid.strip() == "":
        m = f"report 和 taskid 不能为空"
        logger.error(m)
        raise Exception(m)
    
    # 准备一些数据
    prompt = await get_prompt(ctx.report)
    llm_text = "" # llm的返回值
    pre_page_count = 0 # 上一次制作图片到了第几页，最小是 1
    ddd = DataForFrontend()
    ddd.agentStatus = AgentStatus.START
    ddd.message.source_task_id = ctx.taskid
    ddd.startedAt = ctx.start_time
    # yield ddd # 先 yield 一次，让前端知道我们开始执行了
    ddd.agentStatus = AgentStatus.RUNNING
    
    async def save_file_help(filename: str, data: bytes):
        p = f'pptx/{ctx.taskid}/{ctx.times}/{filename}' # TODO 没考虑权限，以后与 planning 一起处理，需要一个好用的 oss 权限组件
        return await save_file(p, data)

    # 保存一些信息
    logger.info(f"保存 prompt 和 report")
    await save_file_help("prompt.txt", prompt.encode("utf-8"))
    await save_file_help("report.txt", ctx.report.encode("utf-8"))

    async def save_images(images):
        """把图片保存到 oss，并更新 ddd.message.images"""
        nonlocal ddd
        for x in images:
            name = f"{len(ddd.message.images) + 1:03d}.png"
            url = await save_file_help(name, x)
            ddd.message.images.append({"url": url})
    
    has_sent_title = False # 是否已经发送过 title 和 page count

    # 准备 LLM 的输入数据
    user_messages = [content_text(prompt)]
    cite_images = []
    for name, b64data in ctx.images.items():
        cite_images.append({"name": name, "b64data": b64data})
    cite_images.sort(key=lambda x: x['name'])
    for x in cite_images:
        mime_type = "image/png" # 下载图片时已经全部转为 png 了
        b64data = x.get('b64data')
        image_name = x.get('name')
        if not b64data or not image_name:
            continue
        cite_id = int(image_name.split('-')[0])
        user_messages.append(content_text(f"下面是 [{image_name}] ，来自[cite:{cite_id}]"))
        user_messages.append(content_image(b64data, mime_type))
    llm_messages = [
        role_system("You are a helpful assistant."),
        role_user(user_messages)
    ]

    # LLM stream 输出完整的 pptx python 代码, 我们边生成边解析
    logger.info(f"开始 LLM stream")
    last_log_time = 0
    stop_preview = False

    async for delta in call_llm(llm_messages, ctx.openrouter):
        
        # 累加 llm_text
        llm_text += delta
        if time.time() - last_log_time > 5:
            logger.info(f"LLM正在输出 {len(llm_text)} 字符")
            last_log_time = time.time()

        # 提取总页数
        if ddd.message.total_page_count == 0:
            ddd.message.total_page_count = extract_total_count(llm_text)
            if ddd.message.total_page_count != 0:
                logger.info(f"提取到总页数: {ddd.message.total_page_count}")

        # 提取标题
        if ddd.message.title == "":
            ddd.message.title = extract_title(llm_text)
            if ddd.message.title != "":
                logger.info(f"提取到标题: {ddd.message.title}")
        
        # 发送 title 和 page count, 需要 标题 和 页数 齐了之后才能发送，不然前端有 UI 问题
        is_title_data_ok = ddd.message.total_page_count != 0 and ddd.message.title != ""
        if not has_sent_title and is_title_data_ok:
            has_sent_title = True
            logger.info(f"发送 title 和 page count")
            yield ddd

        if stop_preview:
            continue

        # 制作预览图
        current_page_count, code = clean_python_code(llm_text)
        if current_page_count != 0 and pre_page_count != current_page_count:
            # 有页数变化，说明来新页了，需要制作图片
            logger.info(f"页数变化 {pre_page_count} -> {current_page_count}")
            tmp = time.time()
            result = await code_to_pptx(code, pre_page_count + 1, current_page_count, ctx.images) # 如果这里报错我们能怎么办？没有任何办法
            if is_code_to_pptx_error(result):
                logger.warning(f"制作预览图失败, 等待最后一步修复代码")
                stop_preview = True # 停止预览图，因为代码有BUG，需要修复
            else:
                images = result['images']
                logger.info(f"制作预览图成功 cost {time.time() - tmp:.2f} 秒")
                await save_images(images)
                pre_page_count = current_page_count
                yield ddd
    
    logger.info(f"LLM stream 结束")
    main_py_content = llm_text
    await save_file_help('main-init.py', main_py_content.encode("utf-8")) # 保存初始代码

    # 检查是否需要修复
    tmp = await code_to_pptx(main_py_content, 0, 0, ctx.images)
    need_fix_bug = is_code_to_pptx_error(tmp)
    stdout_stderr_content = get_stdout_stderr_content(tmp)
    if need_fix_bug:
        # 修复代码
        ddd.message.images = [] # 清空图片，重新制作
        for i in range(1, 5):
            logger.info(f"开始修复代码 第{i}次")
            try:
                main_py_content = await fix_bug(main_py_content, stdout_stderr_content)
                await save_file_help(f'main-fix-{i}.py', main_py_content.encode("utf-8"))
                tmp = await code_to_pptx(main_py_content, 0, 0, ctx.images)
                if not is_code_to_pptx_error(tmp):
                    logger.info(f"修复代码成功 第{i}次")
                    break
                stdout_stderr_content = get_stdout_stderr_content(tmp)
            except Exception as e:
                logger.warning(f"修复代码失败 第{i}次: {e}")
            await asyncio.sleep(0.3)

    # pre_page_count + 1 页到最后一页的所有页制作为图片，同时保存 pptx 文件
    logger.info(f"制作结尾")
    first_page = pre_page_count + 1
    if need_fix_bug:
        # 如果有BUG则从第1页开始制作
        first_page = 1
    result = await code_to_pptx(main_py_content, first_page, -1, ctx.images)
    if is_code_to_pptx_error(result):
        logger.warning(f"制作 PPT 失败")
        raise Exception(f"制作 PPT 失败")
    pptxdata = result['pptx_data']
    images = result['images']
    pptxname = ddd.message.title
    pptxname = pptxname or "noah"
    pptxname = f'{pptxname}.pptx'
    ppt_url = await save_file_help(pptxname, pptxdata)
    ddd.message.pptx = {"url": ppt_url}
    await save_images(images)
    logger.info(f"制作 PPT 成功")
    yield ddd
    ddd.agentStatus = AgentStatus.STOPPED
    yield ddd

    # 把 pptx 的 python 代码保存下来，方便查BUG
    await save_file_help('main.py', main_py_content.encode("utf-8"))


async def report_to_pptx_with_retry(ctx: ReportToPPTXContext) -> AsyncIterator[DataForFrontend]:
    """
    将 report 制作为 pptx，带重试
    单次成功率 90% 左右，4 次失败的概率是 0.1^4 = 0.0001，万分之一
    """
    success = False
    wait = 1
    try_times = 4
    for i in range(try_times):
        try:
            ctx.times = i + 1
            logger.info(f"开始第 {ctx.times} 次")
            async for x in report_to_pptx(ctx):
                yield x
        except Exception as e:
            logger.warning(f"第 {ctx.times} 次失败: {e}")
            await asyncio.sleep(wait)
            # wait *= 2
            continue
        success = True
        logger.info(f"第 {ctx.times} 次成功了，哦耶")
        break
    if not success:
        logger.error(f"{try_times} 次全失败")


def get_report_by_taskid(taskid: str) -> tuple[str, str]:
    """
    获取 文章内容 和 thread_id
    """
    try:
        report = ""
        thread_id = ""
        with get_connection_user() as conn:
            result = conn.execute(text('SELECT context, thread_id FROM "API_task" WHERE id = CAST(:taskid AS uuid)'), {"taskid": taskid},).fetchone()
        if not result:
            return "", ""
        context_data, thread_id = result
        thread_id = str(thread_id) if thread_id else ""
        context = json.loads(context_data) if isinstance(context_data, str) else context_data
        if isinstance(context, dict):
            tool_uses = context.get("tool_uses", [])
            if isinstance(tool_uses, list) and len(tool_uses) > 0:
                last_tool = tool_uses[-1]
                if isinstance(last_tool, dict) and last_tool.get("tool") == "Generate-Summary":
                    report = last_tool.get("result", "")
            # feedback = context.get("feedback", [])
            # feedback = "\n".join(feedback)
            # question = context.get("question", "")
        return report, thread_id
    except Exception as e:
        m = f"get_report_by_taskid 失败 {e}"
        logger.error(m)
        raise Exception(m)


def get_pptx_cfg():
    """
    获取 pptx 配置
    """
    result = {
        'openrouter': 0.0, # 使用 openrouter 的概率
        'overwrite': False, # 是否允许重复制作
    }
    try:
        with get_connection_user() as conn:
            sqlresult = conn.execute(text('SELECT data FROM "Config_someconfig" ORDER BY id DESC LIMIT 1')).fetchone()
            if not sqlresult:
                return result
            data = sqlresult[0]
            if not data:
                return result
            if isinstance(data, str):
                data = json.loads(data)
            if not isinstance(data, dict):
                return result
            data = data.get('pptx', {})
            result['openrouter'] = data.get('openrouter', 0.0)
            result['overwrite'] = data.get('overwrite', False)
    except Exception:
        pass
    return result


def is_use_openrouter(pptx_cfg: dict) -> bool:
    """
    读取配置，判断是否使用 openrouter
    """
    try:
        openrouter = pptx_cfg.get('openrouter', 0)
        openrouter = max(0, float(openrouter))
        if openrouter > 1:
            openrouter = 1
        if openrouter == 0:
            return False
        if openrouter == 1:
            return True
        return random.random() < openrouter
    except Exception as e:
        m = f"is_use_openrouter 失败 {e}"
        logger.error(m)
        return False


def is_can_overwrite(pptx_cfg: dict) -> bool:
    overwrite = pptx_cfg.get('overwrite', False)
    if not isinstance(overwrite, bool):
        False
    return overwrite


class PPTXAgent:
    def __init__(self, *args, **kwargs):
        # 我什么都不需要，但是外部会传，需要防止外部崩溃
        pass

    async def start(self, *args, **kwargs):
        start_time = int(time.time())
        logger.info(f"start")
        # 检查入参
        x = kwargs.get('pptxdata', {})
        source_taskid = x.get('taskid', '') # 将这个 taskid 的 summary 制作为 PPTX
        if not source_taskid:
            m = f"taskid is required"
            logger.warning(m)
            raise Exception(m) # 先报错，不知道怎么办
        report, _ = await asyncio.to_thread(get_report_by_taskid, source_taskid)
        if not report:
            m = f"report is required"
            logger.warning(m)
            raise Exception(m) # 先报错，不知道怎么办
        logger.info(f"参数成功")
        
        # 读取配置
        pptx_cfg = await asyncio.to_thread(get_pptx_cfg)
        use_openrouter = is_use_openrouter(pptx_cfg)
        can_overwrite = is_can_overwrite(pptx_cfg)
        logger.info(f"读取配置成功，use_openrouter: {use_openrouter}")
        
        # TODO 是否重复制作？前端同时发多个相同的请求可能会有BUG，概率很低，后续使用分布式锁解决
        if not can_overwrite:
            if await is_pptx_exists(source_taskid):
                m = f"{source_taskid} 已经做过 pptx"
                logger.warning(m)
                raise Exception(m)
        
        # 立即发送一个消息，让前端知道我们开始制作了
        tmp = DataForFrontend()
        tmp.agentStatus = AgentStatus.START
        tmp.message.source_task_id = source_taskid
        tmp.startedAt = start_time
        yield f'{tmp.to_json_string()}\n'
        
        # 收集网络中的图片
        logger.info(f"download images from cite start")
        new_report, id_to_url = get_cite_id_to_url(report)
        id_to_url_new = {}
        for k, v in id_to_url.items():
            # 删除无需抓图的网站
            if "noahai.co/tool" in v:
                continue
            if "noah.bio/tool" in v:
                continue
            id_to_url_new[k] = v
        id_to_url = id_to_url_new
        image_map = await get_images_from_cite(id_to_url)
        image_map_new = {}
        for name, data in image_map.items():
            image_map_new[name] = base64.b64encode(data).decode()
        image_map = image_map_new
        logger.info(f"download images from cite end [len: {len(image_map)}]")
        # 最多 90 张图片，多出的图片随机删除一些
        max_image_count = 90
        if len(image_map) > max_image_count:
            keys = random.sample(list(image_map), max_image_count)
            image_map = {k: image_map[k] for k in keys}
        # 所有图片 base64 加起来最多 19MB，多出的删除，优先删最大的（按 base64 字符串字节长度）
        max_image_size = 19 * 1024 * 1024
        total_b64 = sum(len(s) for s in image_map.values())
        if total_b64 > max_image_size:
            keys_largest_first = sorted(image_map.keys(), key=lambda k: len(image_map[k]), reverse=True)
            for k in keys_largest_first:
                if total_b64 <= max_image_size:
                    break
                total_b64 -= len(image_map[k])
                del image_map[k]
        logger.info(f"after filter images, len: {len(image_map)}, size: {total_b64}")

        # 制作 PPTX
        logger.info(f"upload_pptx_start")
        await upload_pptx_start(source_taskid)
        logger.info(f"start")
        ctx = ReportToPPTXContext()
        ctx.report = new_report
        ctx.taskid = source_taskid
        ctx.start_time = start_time
        ctx.openrouter = use_openrouter
        ctx.images = image_map # {name -> b64data}
        logger.info(f"开始制作ppt，use_openrouter: {use_openrouter}, source_taskid: {ctx.taskid}")
        async for x in report_to_pptx_with_retry(ctx):
            d = x.to_json_string()
            logger.info(f"yield {d}")
            yield f'{d}\n' # 与 standardize_yield 保持一致
        t1 = int(time.time())
        logger.critical(f"makepptx cost: {t1 - start_time} 秒, openrouter: {use_openrouter}, source_taskid: {ctx.taskid}")


# async def test():
#     with open('/Users/tanght/noah/code/NoahAgent/noah_agent/agent/ppt/report3.txt', 'r') as f:
#         report = f.read()

#     new_report, id_to_url = get_cite_id_to_url(report)
#     # 删除无需抓图的网站
#     id_to_url_new = {}
#     for k, v in id_to_url.items():
#         if "noahai.co/tool" in v:
#             continue
#         if "noah.bio/tool" in v:
#             continue
#         id_to_url_new[k] = v
#     id_to_url = id_to_url_new
#     image_map = await get_images_from_cite(id_to_url)
#     image_map_new = {}
#     for name, data in image_map.items():
#         image_map_new[name] = base64.b64encode(data).decode()
#     image_map = image_map_new

#     for name, b64data in image_map.items():
#         p = f"/Users/tanght/noah/code/NoahAgent/noah_agent/agent/ppt/images"
#         os.makedirs(p, exist_ok=True)
#         with open(f"{p}/{name}", "wb") as f:
#             f.write(base64.b64decode(b64data))

#     ctx = ReportToPPTXContext()
#     ctx.report = new_report
#     ctx.taskid = "3cbd896b-8e37-42e0-ad09-e9ab45662805"
#     ctx.thread_id = "123"
#     ctx.start_time = int(time.time())
#     ctx.openrouter = True
#     ctx.images = image_map # {name -> b64data}


#     async for x in report_to_pptx_with_retry(ctx):
#         print(f'images count: {len(x.message.images)}, pptx: {x.message.pptx.get("url")}')

# if __name__ == '__main__':
#     import asyncio
#     asyncio.run(test())
