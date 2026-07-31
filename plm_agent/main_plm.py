"""
Minimal server for testing PLM endpoints only.
Usage: uvicorn main_plm:app --host 0.0.0.0 --port 8000
"""
import json
import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from agent.patient_like_me.v1.custom_rag.kb_api import router as plm_custom_rag_router
app.include_router(plm_custom_rag_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# 报告缓存 + 异步生成: 报告要 6-9 分钟且体量大(综合报告数十KB)。
# 让 agent 的 curl 秒回一个 report_id(status=generating), 后台异步跑 workflow,
# 前端按 id 轮询 /plm/report/<id> 直到 ready 再渲染。彻底避开长 curl 超时/沙箱审批。
import uuid as _uuid_r
import asyncio as _asyncio
_REPORTS: dict = {}
_REPORTS_ORDER: list = []
_REPORT_QUEUES: dict = {}   # report_id -> asyncio.Queue(分区流式事件)
_REPORT_BY_CLARIFY: dict = {}   # clarify_session_id -> report_id(幂等: 同一澄清只生成一份)
_GUIDELINES: dict = {}          # guidelines_id -> 候选列表(compact 模式: agent 只吐 id, 前端 fetch 渲染)
_GUIDELINES_ORDER: list = []    # 简单 LRU 上限


# ============================================================
# 用户鉴权 + 行级归属(复用 biz-backend DRF Token; 仅只读校验)
# 生成走 agent 内网(无 token, owner=None); 检索/管理端点强制 token。
# 归属: 生成即归属(浏览器带 token) + 首次认领(agent 路径 owner 空时第一个合法 token 认领)。
# ============================================================
_OWNER_LOCK = _asyncio.Lock()
_TOKEN_CACHE: dict = {}          # token -> (expires_at_monotonic, identity|None)
_TOKEN_TTL = 60.0


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization") or ""
    parts = auth.split(None, 1)
    if len(parts) == 2 and parts[0].lower() in ("token", "bearer"):
        return parts[1].strip()
    return (request.query_params.get("token") or "").strip()   # SSE 走 ?token=


async def _fetch_is_admin(base: str, token: str) -> bool:
    """调 biz /api/access/me/ 判断是否 B 端管理员(组管理员 / 企业管理员 / 平台超管 任一)。
    拿不到当作非管理员。"""
    try:
        async with _httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{base}/api/access/me/",
                            headers={"Authorization": f"Token {token}", "Host": "localhost"})
        if r.status_code != 200:
            return False
        prof = (r.json() or {}).get("access", {}) or {}
        aa = prof.get("access_admin", {}) or {}
        return bool(aa.get("visible") or aa.get("is_group_admin") or aa.get("is_company_admin")
                    or aa.get("is_superuser") or prof.get("is_group_admin"))
    except Exception as e:
        logger.warning("[auth] %s /api/access/me/ 判管理员失败(当作非管理员): %s", base, e)
        return False


async def _identity_and_admin_from_token(token: str):
    """token → (身份 username|email 小写, 是否管理员)。身份取自 /api/users/;管理员取自
    /api/access/me/(组/企业/平台管理员任一)。无效返回 (None, False)。60s 缓存。"""
    if not token:
        return (None, False)
    import time as _time
    now = _time.monotonic()
    ent = _TOKEN_CACHE.get(token)
    if ent and ent[0] > now:
        return (ent[1], ent[2])
    identity, is_admin, net_ok = None, False, False
    for base in _BK_BASES:   # 依次试多后端(测试/线上), 谁认就用谁
        try:
            async with _httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{base}/api/users/",
                                headers={"Authorization": f"Token {token}", "Host": "localhost"})
        except Exception as e:
            logger.warning("[auth] %s /api/users/ 请求失败: %s", base, e)
            continue
        net_ok = True
        if r.status_code == 200:
            try:
                data = r.json()
            except Exception:
                data = None
            u = {}
            if isinstance(data, dict) and isinstance(data.get("results"), list):
                u = data["results"][0] if data["results"] else {}
            elif isinstance(data, list):
                u = data[0] if data else {}
            elif isinstance(data, dict):
                u = data
            identity = (str(u.get("username") or u.get("email") or "").strip().lower()) or None
            if identity:
                is_admin = await _fetch_is_admin(base, token)   # 调 /api/access/me/ 判管理员
                break   # 命中一个后端即可, 不再试其余
    if not net_ok and identity is None:
        return (None, False)   # 全部后端网络失败, 不缓存(避免把临时故障固化成拒绝)
    _TOKEN_CACHE[token] = (now + (_TOKEN_TTL if identity else 10.0), identity, is_admin)
    while len(_TOKEN_CACHE) > 500:
        _TOKEN_CACHE.pop(next(iter(_TOKEN_CACHE)), None)
    return (identity, is_admin)


async def _identity_from_token(token: str):
    return (await _identity_and_admin_from_token(token))[0]


async def _auth_identity(request: Request):
    return await _identity_from_token(_bearer(request))


async def _auth_admin(request: Request):
    """→ (身份, 是否管理员)。供管理端点区分 401(未登录) / 403(非管理员)。"""
    return await _identity_and_admin_from_token(_bearer(request))


async def _maybe_bind_owner(rid: str, identity) -> None:
    """生成即归属: 报告 owner 为空且带了身份时绑定(不持久化, 由后续 save_report 落盘)。"""
    if not identity:
        return
    async with _OWNER_LOCK:
        r = _REPORTS.get(rid)
        if r is not None and r.get("owner") is None:
            r["owner"] = identity


async def _claim_or_check(entry: dict, rid_for_save, identity: str, *, persist: bool) -> bool:
    """行级归属: owner 为空则本用户原子认领, 否则必须匹配。返回是否放行。"""
    async with _OWNER_LOCK:
        cur = entry.get("owner")
        if cur is None:
            entry["owner"] = identity
            if persist and rid_for_save:
                try:
                    from agent.common.session_store import save_report
                    await save_report(rid_for_save, entry)
                except Exception:
                    pass
            return True
        return cur == identity


def _new_report_id() -> str:
    rid = _uuid_r.uuid4().hex[:12]
    # live: 边生成边累积各分区文本(引擎分区名 -> 文本), 让 report_stream 支持刷新重连/继续流。
    _REPORTS[rid] = {"status": "generating", "live": {}, "owner": None}
    _REPORTS_ORDER.append(rid)
    while len(_REPORTS_ORDER) > 30:  # 只留最近 30 份
        old = _REPORTS_ORDER.pop(0)
        _REPORTS.pop(old, None)
    return rid

async def _ensure_confirmed_info(rd: dict) -> None:
    """report 门要求 confirmed_patient_info。skill 的 curl 只传 patient_input 时, 在后台从它重抽
    (不依赖 Redis; 与澄清阶段抽取一致——用户澄清答复是自由文本, 本就不进 patient_info)。
    放后台执行, 让 compact 的 curl 能秒回 report_id, 不被这 30 多秒抽取阻塞。"""
    if rd.get('confirmed_patient_info'):
        return
    pin = (rd.get('patient_input') or '').strip()
    if not pin:
        return
    try:
        from agent.patient_like_me.v1.rag.workflow import step_extract_patient_info as _extract
        pinfo, _ = await _extract(pin)
        if pinfo:
            rd['confirmed_patient_info'] = pinfo
    except Exception as e:
        logger.warning("[plm_evidence_based] 后台重抽 patient_info 失败: %s", e)


def _fill_report(rid: str, result: dict) -> None:
    _prev_owner = (_REPORTS.get(rid) or {}).get("owner")   # ready 覆盖时保住归属
    _REPORTS[rid] = {
        "status": "ready",
        "owner": _prev_owner,
        "__plm_report__": True,
        "guideline": (result.get("primary_organization") or "") + (" · 主指南" if result.get("primary_organization") else ""),
        "primary_organization": result.get("primary_organization") or "",
        "diagnosis": result.get("diagnosis_report") or "",
        "examination": result.get("examination_report") or "",
        "treatment": result.get("treatment_report") or "",
        "drug": result.get("drug_manual_text") or "",
        "comprehensive": result.get("output") or "",
        "secondary": result.get("secondary_comparison") or "",
        "citations": result.get("citations") or [],
        # 下载文件名用: 优先主诊断, 退回机构
        "title": ((result.get("patient_info") or {}).get("primary_diagnosis")
                  or ((result.get("primary_organization") or "") + "循证诊疗报告")).strip(),
    }


@app.post('/plm_evidence_based')
async def plm_evidence_based_api(body: dict, request: Request):
    from agent.patient_like_me.v1.rag.workflow import run_plm_workflow

    patient_input = (body.get('patient_input') or body.get('patient_description') or '').strip()
    # 前端直连报告(极小 run 块): 只带 clarify_session_id 时, 从澄清会话还原 patient_input + confirmed_patient_info,
    # agent 就不必把整个 patient_info 塞进对话里的代码块。
    clarify_sid = (body.get('clarify_session_id') or '').strip()
    # patient_input 缺失时尽力从澄清会话补回(仅当 Redis 可用); 通常 skill 的 curl 已自带 patient_input。
    if clarify_sid and not patient_input:
        try:
            from agent.common.session_store import load_session
            cached = await load_session("plm", clarify_sid)
            meta = json.loads((cached or {}).get("report_text") or "{}")
            patient_input = (meta.get("patient_input") or "").strip()
        except Exception as e:
            logger.warning("[plm_evidence_based] clarify_session 还原 patient_input 失败: %s", e)
    has_structured = any(body.get(k) for k in ('age', 'gender', 'visit_stage', 'key_conditions', 'confirmed_patient_info', 'patient_input_raw', 'structured_fields'))
    if not patient_input and not has_structured:
        return JSONResponse({"error": "patient_input is required"}, status_code=400)

    stream = body.get('stream', False)
    compact = bool(body.get('compact', False))  # skill 传 true: 只回小 report_id, 全文存服务端
    task_id = str(body.get('task_id', ''))
    request_data = {**body, 'patient_input': patient_input, 'task_id': task_id}
    # 本产品固定走 complex(含药物说明书)。自建RAG 默认不开(用户库为空)。
    request_data.setdefault('mode', 'complex')

    if stream:
        async def gen():
            events = []
            await _ensure_confirmed_info(request_data)
            result = await run_plm_workflow(
                request_data,
                on_event=lambda n, p: events.append({"event": n, "payload": p}),
                task_id=task_id,
            )
            for evt in events:
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'event': 'result', 'payload': result}, ensure_ascii=False)}\n\n"

        return StreamingResponse(gen(), media_type='text/event-stream')

    # compact 模式: 秒回 report_id; 后端边生成边把分区事件塞进队列, 前端 SSE 实时渲染。
    if compact:
        # 幂等键: 优先用 clarify_session_id —— 它是 agent 从 clarify_sync 逐字复制的 token, 最稳定;
        # 同一次澄清无论 agent curl 几次(重试/重复), 只生成一份、复用同一 report_id, 前端才不会连到空的那个。
        # 无 session 时退回 选定指南+病情指纹(病情措辞可能微变, 故仅作兜底)。
        import hashlib as _hl
        _owner_id = await _auth_identity(request)   # 浏览器直连带 token → 生成即归属
        _doc = str(body.get('selected_doc_id') or body.get('doc_id') or '')
        idem_key = clarify_sid or ((_doc + ":" + _hl.md5((patient_input or "").encode("utf-8")).hexdigest()[:12]) if (_doc and patient_input) else "")
        if idem_key:
            prev = _REPORT_BY_CLARIFY.get(idem_key)
            # 只复用"正在生成/已就绪"的报告; error/clarification_required 等异常终态不复用,
            # 否则卡死报告会被无限复用, 重试永远拿不到真报告(死锁)。
            if prev and _REPORTS.get(prev) and _REPORTS[prev].get("status") in ("generating", "ready"):
                logger.info("[plm_evidence_based] 复用 report_id=%s (key=%s)", prev, idem_key)
                await _maybe_bind_owner(prev, _owner_id)
                return JSONResponse({"status": "generating", "report_id": prev,
                                     "message": "报告生成中(复用已有)"}, status_code=200)
            elif prev:
                _REPORT_BY_CLARIFY.pop(idem_key, None)   # 清掉失效映射, 允许重新生成
        rid = _new_report_id()
        await _maybe_bind_owner(rid, _owner_id)
        if idem_key:
            _REPORT_BY_CLARIFY[idem_key] = rid
        async def _bg():
            def _on_event(name, payload):
                # 边生成边把分区文本累积进 _REPORTS[rid]['live'](按引擎分区名), report_stream 轮询读取:
                # 多个/刷新后的消费者都能读到当前进度 → 没流完继续流、流完直接展示。
                try:
                    if name == "section_chunk":
                        st = _REPORTS.get(rid)
                        if st is not None and st.get("status") == "generating":
                            sec = payload.get("section") or ""
                            live = st.setdefault("live", {})
                            live[sec] = live.get(sec, "") + (payload.get("text") or "")
                except Exception:
                    pass
            try:
                await _ensure_confirmed_info(request_data)   # 后台重抽 patient_info(不阻塞 curl 秒回)
                result = await run_plm_workflow(request_data, on_event=_on_event, task_id=task_id)
                if result.get("route") == "clarification_required" or not result.get("output"):
                    _REPORTS[rid] = {"status": "clarification_required"}
                else:
                    _fill_report(rid, result)   # 覆盖为权威全文 + citations, status=ready
                    try:
                        from agent.common.session_store import save_report
                        await save_report(rid, _REPORTS[rid])   # 持久化, 刷新/重启可重看
                    except Exception as _e:
                        logger.warning("[plm_evidence_based] 报告持久化失败: %s", _e)
            except Exception as e:
                logger.error(f"plm_evidence_based bg error: {traceback.format_exc()}")
                _REPORTS[rid] = {"status": "error", "error": str(e)}
        _asyncio.create_task(_bg())
        return JSONResponse({"status": "generating", "report_id": rid,
                             "message": "报告生成中, 前端会分区流式加载"}, status_code=200)

    try:
        await _ensure_confirmed_info(request_data)
        result = await run_plm_workflow(request_data, task_id=task_id)
        return JSONResponse(result, status_code=200)
    except Exception as e:
        logger.error(f"plm_evidence_based error: {traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def _get_report(report_id: str):
    """先查内存, 没有再查 Redis 持久化(刷新/8002重启后仍能取回旧报告); 命中则回填内存。"""
    r = _REPORTS.get(report_id)
    if r:
        return r
    try:
        from agent.common.session_store import load_report
        r = await load_report(report_id)
        if r:
            _REPORTS[report_id] = r        # 回填, 后续 stream/download 直接用
            if report_id not in _REPORTS_ORDER:
                _REPORTS_ORDER.append(report_id)
            return r
    except Exception as e:
        logger.warning("[plm_evidence_based] 读取持久化报告失败: %s", e)
    return None


@app.get('/plm/report/{report_id}')
async def plm_report_get(report_id: str, request: Request):
    """前端按 report_id 拉取报告全文(SSE 流断了时的兜底)。status: generating / ready / ...。"""
    identity = await _auth_identity(request)
    if not identity:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    r = await _get_report(report_id)
    if not r:
        return JSONResponse({"error": "report not found or expired", "status": "missing"}, status_code=404)
    if not await _claim_or_check(r, report_id, identity, persist=True):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return JSONResponse(r, status_code=200)


_MD_TO_WORD_URL = "https://test.noahai.co/markdown-to-word/convert-text"   # 同 demo report_export
_WORD_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _report_markdown(r: dict) -> str:
    """把整份报告各分区拼成一个 markdown 文档。"""
    org = r.get("primary_organization") or ""
    parts = [f"# 循证诊疗报告{(' — ' + org) if org else ''}"]
    for label, key in [("诊断", "diagnosis"), ("检查", "examination"), ("治疗", "treatment"),
                       ("药物说明书", "drug"), ("次要指南补充", "secondary"), ("综合报告", "comprehensive")]:
        txt = (r.get(key) or "").strip()
        if txt:
            parts.append(f"\n\n---\n\n# {label}\n\n{txt}")
    return "".join(parts)


def _md_to_word_bytes(markdown: str) -> bytes:
    """调 noah-markdown-to-word 微服务(同 demo)返回 .docx 二进制。"""
    import requests as _rq
    resp = _rq.post(_MD_TO_WORD_URL, json={"content": markdown, "format_type": "chinese"}, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"md-to-word {resp.status_code}: {resp.text[:200]}")
    return resp.content


def _md_to_pdf_bytes(markdown: str) -> bytes:
    """Markdown → PDF(纯 Python, markdown-it-py + PyMuPDF), 同 demo report_export。"""
    import fitz
    from markdown_it import MarkdownIt
    from io import BytesIO
    html_body = MarkdownIt("commonmark", {"html": True, "breaks": True}).enable("table").render(markdown)
    html_doc = ('<!doctype html><html><head><meta charset="utf-8"/><style>'
                'body{font-family:Arial,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;line-height:1.6;font-size:12pt;}'
                'h1,h2,h3,h4,h5,h6{margin-top:1.2em;margin-bottom:0.5em;}p,ul,ol,pre,blockquote,table{margin:0.5em 0;}'
                'pre{white-space:pre-wrap;word-break:break-word;}table{border-collapse:collapse;width:100%;}'
                'th,td{border:1px solid #ddd;padding:6px;}</style></head><body>' + html_body + '</body></html>')
    page_rect = fitz.paper_rect("a4")
    content_rect = fitz.Rect(45, 57, page_rect.width - 45, page_rect.height - 57)
    buf = BytesIO(); writer = fitz.DocumentWriter(buf)
    try:
        story = fitz.Story(html=html_doc); more = 1; pages = 0
        while more and pages < 300:
            dev = writer.begin_page(page_rect); more, _ = story.place(content_rect); story.draw(dev); writer.end_page(); pages += 1
    finally:
        writer.close()
    raw = buf.getvalue()
    # 字体子集化 + 压缩(garbage/deflate/objstms): PDF 体积可从数 MB 降到几十 KB, 大幅加速下载。
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
        doc.subset_fonts()
        raw = doc.tobytes(garbage=4, deflate=True, use_objstms=1)
        doc.close()
    except Exception:
        logger.warning("[pdf] subset/compress failed, return raw", exc_info=True)
    return raw


def _safe_name(v: str, fallback: str) -> str:
    import re as _re
    v = _re.sub(r'[\\/:*?"<>|\r\n\t]', "", v or "").strip()[:80]
    return v or fallback


@app.get('/plm/report/{report_id}/download')
async def plm_report_download(report_id: str, request: Request, fmt: str = "word", title: str = ""):
    """下载整份报告为 Word(fmt=word) 或 PDF(fmt=pdf)。文件名: 病例报告_<全名>.docx/.pdf(同 demo)。"""
    from fastapi.responses import Response as _Resp
    from urllib.parse import quote as _quote
    identity = await _auth_identity(request)
    if not identity:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    r = await _get_report(report_id)
    if not r or r.get("status") != "ready":
        return JSONResponse({"error": "report not ready"}, status_code=404)
    if not await _claim_or_check(r, report_id, identity, persist=True):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    md = _report_markdown(r)
    name = _safe_name(title or r.get("title") or "", fallback=report_id)
    ext = "pdf" if fmt == "pdf" else "docx"
    fname = f"病例报告_{name}.{ext}"
    try:
        if fmt == "pdf":
            content, ct = await _asyncio.to_thread(_md_to_pdf_bytes, md), "application/pdf"
        else:
            content, ct = await _asyncio.to_thread(_md_to_word_bytes, md), _WORD_CT
    except Exception as e:
        logger.error("[plm_report_download] %s 失败: %s", fmt, e)
        return JSONResponse({"error": f"导出{fmt}失败: {e}"}, status_code=500)
    return _Resp(content=content, media_type=ct,
                 headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_quote(fname)}"})


@app.get('/plm/report_stream/{report_id}')
async def plm_report_stream(report_id: str, request: Request):
    """报告分区流式 SSE(状态累积式, 支持刷新重连/多消费者):
    轮询 _REPORTS[rid]['live'] 发增量 chunk, ready 时补齐权威全文并发 _done。
    没流完的新连接会从当前累积继续流, 流完的直接补齐——刷新不会重新生成。"""
    def _sse(evt: dict) -> str:
        return f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

    identity = await _auth_identity(request)   # SSE 不能设 header → token 走 ?token=
    if not identity:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if report_id not in _REPORTS:
        await _get_report(report_id)   # 内存没有→尝试从 Redis 回填(刷新/重启后仍能重放)
    _r0 = _REPORTS.get(report_id)
    if not _r0:
        return JSONResponse({"error": "stream not found"}, status_code=404)
    if not await _claim_or_check(_r0, report_id, identity, persist=True):
        return JSONResponse({"error": "forbidden"}, status_code=403)

    # 引擎分区名 -> ready 后的权威字段(综合报告 summary 由前端在 _done 后 reconcile 拉全文, 不在此逐块补)
    _SEC_FIELD = [("diagnosis", "diagnosis"), ("examination", "examination"),
                  ("treatment", "treatment"), ("drug", "drug"),
                  ("secondary_comparison", "secondary")]

    async def gen():
        sent: dict = {}   # 引擎分区名 -> 已发送长度(支持本连接自己的进度, 刷新重连从 0 重发当前累积)
        for _ in range(2400):   # 最多 ~20min 兜底
            r = _REPORTS.get(report_id)
            if r is None:
                yield _sse({"event": "error", "payload": {"error": "report expired"}}); return
            status = r.get("status")
            if status == "clarification_required":
                yield _sse({"event": "clarification_required", "payload": {}}); return
            if status == "error":
                yield _sse({"event": "error", "payload": {"error": r.get("error", "")}}); return
            if status == "ready":
                for sec, key in _SEC_FIELD:   # 补齐权威全文的增量(live 未覆盖到的尾巴)
                    full = r.get(key) or ""
                    if len(full) > sent.get(sec, 0):
                        yield _sse({"event": "section_chunk", "payload": {"section": sec, "text": full[sent.get(sec, 0):]}})
                        sent[sec] = len(full)
                yield _sse({"event": "result", "payload": {"status": "ready"}})
                yield _sse({"event": "_done", "payload": {}})
                return
            # generating: 发 live 增量
            live = r.get("live") or {}
            for sec, txt in list(live.items()):
                if len(txt) > sent.get(sec, 0):
                    yield _sse({"event": "section_chunk", "payload": {"section": sec, "text": txt[sent.get(sec, 0):]}})
                    sent[sec] = len(txt)
            await _asyncio.sleep(0.5)
        yield _sse({"event": "_done", "payload": {}})

    return StreamingResponse(gen(), media_type='text/event-stream',
                             headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


async def _select_guidelines_via_catalog(diagnosis: str, doc_query: str, product_scope: str,
                                         allowed_publishers, max_docs: int = 5) -> list:
    """小库(如 yiyong ~85篇)直接把全部指南名给 GLM Flash(不带思考)挑 TOP-5, 绕开 KNN
    召回缺口: 全目录可见 → 亚型带出大类(FL→B细胞淋巴瘤)、近义病名纠偏(浆母 vs 淋巴浆细胞)。
    目录过大(>200篇)或任何异常时返回 [], 由上层回退 KNN。"""
    from agent.patient_like_me.v1.es.plm_index import get_es_client, PLM_INDEX
    from agent.patient_like_me.v1.rag.workflow import _gemini_flash, _call_llm, _loads_first_json_object
    client = get_es_client()
    must = [{"term": {"product_scope": product_scope}}] if product_scope else []
    # 机构(学会)硬过滤: 只把用户选的机构的指南放进目录(与 search_guideline_documents 一致)。
    if allowed_publishers:
        pub_set = {p.upper() for p in allowed_publishers if p}
        non_other = [p for p in pub_set if p != "OTHER"]
        should = []
        if non_other:
            should.append({"terms": {"organization": non_other}})
        if "OTHER" in pub_set:
            should.append({"bool": {"should": [
                {"term": {"organization": "OTHER"}}, {"term": {"organization": ""}},
                {"bool": {"must_not": [{"exists": {"field": "organization"}}]}},
            ], "minimum_should_match": 1}})
        if should:
            must.append({"bool": {"should": should, "minimum_should_match": 1}})
    body = {"size": 500, "query": ({"bool": {"must": must}} if must else {"match_all": {}}),
            "_source": ["filename", "guideline_key", "organization", "year", "title_cn"]}
    resp = await _asyncio.to_thread(lambda: client.search(index=PLM_INDEX, body=body))
    catalog = []
    for h in resp.get("hits", {}).get("hits", []):
        s = h.get("_source", {})
        name = s.get("filename") or s.get("guideline_key") or s.get("title_cn") or ""
        if name:
            catalog.append((str(h["_id"]), name))
    if not catalog or len(catalog) > 200:
        return []
    lines = "\n".join(f"{i}:{n}" for i, (_, n) in enumerate(catalog))
    pref = "、".join(p for p in allowed_publishers if p) if allowed_publishers else ""
    sysp = (
        f"你是临床指南检索助手。下面是候选指南目录(编号:文件名)。根据患者主诊断按相关度从高到低排序, 返回最相关的 {max_docs} 份(目录不足则全给)。规则:"
        "①病名精确匹配优先;②若患者所患疾病是某更大类别下的亚型/分型, 且目录中存在覆盖该大类完整诊疗路径的综合性指南, 应将其选入并靠前(综合大类指南通常涵盖该亚型的诊疗内容);"
        "③亚型专属指南与综合大类指南可一并选入;④真正对口的排最前, 其余按相关度递减补足名额。"
        + (f"⑤同等相关时机构优先: {pref}。" if pref else "")
        + '只输出JSON:{"ids":[编号]}'
    )
    up = f"候选指南目录:\n{lines}\n\n患者主诊断:{diagnosis or doc_query}\n输出:"
    raw = await _call_llm(_gemini_flash(), sysp, up, json_mode=True)
    picked = [catalog[i][0] for i in _loads_first_json_object(raw).get("ids", [])
              if isinstance(i, int) and 0 <= i < len(catalog)][:max_docs]
    # 补齐到 max_docs(LLM 少给时用目录里其余的填, 保持 TOP-N 交互)
    if picked and len(picked) < max_docs:
        for cid, _ in catalog:
            if cid not in picked:
                picked.append(cid)
                if len(picked) >= max_docs:
                    break
    if not picked:
        return []
    mg = await _asyncio.to_thread(lambda: client.mget(index=PLM_INDEX, body={"ids": picked}))
    by_id = {}
    for d in mg.get("docs", []):
        if not d.get("found"):
            continue
        s = d.get("_source", {})
        by_id[str(d["_id"])] = {"id": str(d["_id"]),
                                "name": s.get("filename") or s.get("guideline_key") or s.get("title_cn") or "",
                                "organization": s.get("organization"), "summary": s.get("summary"),
                                "year": s.get("year"), "guideline_key": s.get("guideline_key")}
    return [by_id[i] for i in picked if i in by_id]  # 保留 LLM 排序


@app.post('/plm_evidence_based/select_guideline')
async def plm_select_guideline_api(body: dict, request: Request):
    """PLM-on-Hermes 步骤①: 抽取患者信息 + 返回 TOP-5 候选指南供用户选 (默认 yiyong 库)。"""
    from agent.patient_like_me.v1.rag.workflow import step_extract_patient_info
    from agent.patient_like_me.v1.rag.evidence import search_guideline_documents

    patient_input = (body.get('patient_input') or body.get('patient_description') or '').strip()
    if not patient_input:
        return JSONResponse({"error": "patient_input is required"}, status_code=400)
    product_scope = (body.get('product_scope') or 'yiyong').strip().lower()
    max_docs = int(body.get('max_docs') or 5)
    # 指南范围(机构): 用户在前端必选(默认 NCCN), 用来把 TOP-5 限定在该机构指南内。
    allowed_publishers = body.get('guideline_priority_order') or body.get('allowed_publishers') or None
    if allowed_publishers and not isinstance(allowed_publishers, list):
        allowed_publishers = [allowed_publishers]

    try:
        patient_info, _ = await step_extract_patient_info(patient_input, fast=True)  # 交互式求快, Flash 抽取
    except Exception as e:
        logger.error(f"select_guideline extract error: {traceback.format_exc()}")
        return JSONResponse({"error": f"extract failed: {e}"}, status_code=500)

    diagnosis = (patient_info.get('primary_diagnosis') or '').strip()

    def _flat(v):
        if isinstance(v, (list, tuple)):
            return "、".join(str(x) for x in v if x)
        if isinstance(v, dict):
            return ", ".join(f"{k}: {val}" for k, val in v.items() if val)
        return str(v or "")

    key_features = " ".join(x for x in [_flat(patient_info.get('current_symptoms')),
                                        _flat(patient_info.get('test_results'))] if x).strip()
    doc_query = " ".join(x for x in [diagnosis, key_features] if x).strip() or patient_input

    scope_fallback = False
    # 首选: 把该 scope 全部指南名丢给 GLM Flash 挑 TOP-5 —— 小库无召回缺口, 懂疾病层级(FL→B细胞)。
    try:
        docs = await _select_guidelines_via_catalog(diagnosis, doc_query, product_scope, allowed_publishers, max_docs)
    except Exception:
        logger.warning("[select_guideline] 全目录 LLM 挑选失败, 回退 KNN", exc_info=True)
        docs = []

    if not docs:
        # 回退: KNN 多召回 → lite 选择器重排(疾病层级/近义病名)→ 截到 max_docs
        _pool = max(int(max_docs) * 2, 12)
        try:
            docs = await search_guideline_documents(
                query=doc_query, diagnosis=diagnosis, max_docs=_pool,
                multi_org=True, product_scope=product_scope,
                allowed_publishers=allowed_publishers,
            )
            if not docs and allowed_publishers:
                scope_fallback = True
                docs = await search_guideline_documents(
                    query=doc_query, diagnosis=diagnosis, max_docs=_pool,
                    multi_org=True, product_scope=product_scope,
                )
        except Exception as e:
            logger.error(f"select_guideline search error: {traceback.format_exc()}")
            return JSONResponse({"error": f"search failed: {e}"}, status_code=500)
        if docs and len(docs) > 1:
            try:
                from agent.patient_like_me.v1.rag.workflow import _select_document_ids
                ranked = await _select_document_ids(diagnosis, doc_query, docs, lite=True)
                if ranked:
                    order = {str(x): i for i, x in enumerate(ranked)}
                    docs = sorted(docs, key=lambda d: order.get(str(d.get("id")), 10**6))
            except Exception:
                logger.warning("[select_guideline] lite 重排失败, 保留 KNN 顺序", exc_info=True)
        docs = docs[:max_docs]

    candidates = [{
        "doc_id": d.get("id"),
        "name": d.get("name"),
        "organization": d.get("organization"),
        "summary": d.get("summary"),
        "year": d.get("year"),
        "score": d.get("score"),
    } for d in docs]

    # 标注每个候选是否有决策图谱(有图谱才能出完整报告); 无图谱的排后面。
    try:
        from agent.patient_like_me.v1.es.plm_index import get_es_client, PLM_INDEX
        _ids = [str(c["doc_id"]) for c in candidates if c.get("doc_id")]
        if _ids:
            _mg = get_es_client().mget(index=PLM_INDEX, body={"ids": _ids})
            _hg = {d["_id"]: bool((d.get("_source") or {}).get("has_graph")) for d in _mg.get("docs", [])}
            for c in candidates:
                c["has_graph"] = _hg.get(str(c.get("doc_id")), False)
        candidates.sort(key=lambda c: (0 if c.get("has_graph") else 1))  # 有图谱优先
    except Exception:
        for c in candidates:
            c.setdefault("has_graph", True)

    # compact: 缓存候选并返回一个 guidelines_id, agent 只吐 {guidelines_id} 小块(前端 fetch 渲染),
    # 免去 agent 把 5 条候选(含 summary)整段再序列化一遍 —— 省 token/延迟, 杜绝吐错/漏/截断。
    if body.get('compact'):
        gid = _uuid_r.uuid4().hex[:12]
        _GUIDELINES[gid] = {"candidates": candidates, "patient_info": patient_info,
                            "scope_fallback": scope_fallback, "requested_publishers": allowed_publishers,
                            "owner": await _auth_identity(request)}   # 浏览器带 token 即归属; agent 路径为 None(首次认领)
        _GUIDELINES_ORDER.append(gid)
        while len(_GUIDELINES_ORDER) > 200:      # 简单 LRU 上限, 防内存无限增长
            _GUIDELINES.pop(_GUIDELINES_ORDER.pop(0), None)
        try:   # 落 Redis: 内存被 LRU 挤掉/引擎重启后, 刷新/切历史回来仍能渲染卡片
            from agent.common.session_store import save_guidelines
            await save_guidelines(gid, _GUIDELINES[gid])
        except Exception:
            pass
        # 回给 agent 的精简清单(doc_id/name/organization, 无 summary): 供其把"选第N个"映射回 doc_id, 不用于渲染。
        slim = [{"n": i + 1, "doc_id": c["doc_id"], "name": c["name"], "organization": c["organization"]}
                for i, c in enumerate(candidates)]
        return JSONResponse({"guidelines_id": gid, "patient_info": patient_info,
                             "candidates_brief": slim, "scope_fallback": scope_fallback}, status_code=200)

    return JSONResponse({"patient_info": patient_info, "candidates": candidates,
                         "scope_fallback": scope_fallback,
                         "requested_publishers": allowed_publishers}, status_code=200)


@app.get('/plm/guidelines_candidates/{gid}')
async def plm_guidelines_candidates_get(gid: str, request: Request):
    """前端按 guidelines_id 拉取 TOP-5 候选渲染卡片(与 report_id 同理, agent 不再重吐候选 JSON)。"""
    identity = await _auth_identity(request)
    if not identity:
        return JSONResponse({"error": "unauthorized", "candidates": []}, status_code=401)
    g = _GUIDELINES.get(gid)
    if not g:   # 内存 miss(LRU 挤掉/引擎重启) → 回落 Redis, 命中则回填内存
        try:
            from agent.common.session_store import load_guidelines
            g = await load_guidelines(gid)
        except Exception:
            g = None
        if g:
            _GUIDELINES[gid] = g
            _GUIDELINES_ORDER.append(gid)
            while len(_GUIDELINES_ORDER) > 200:
                _GUIDELINES.pop(_GUIDELINES_ORDER.pop(0), None)
    if not g:
        return JSONResponse({"error": "guidelines not found or expired", "candidates": []}, status_code=404)
    claimed = g.get("owner") is None
    if not await _claim_or_check(g, None, identity, persist=False):   # 含 patient_info PHI, 严格按用户归属
        return JSONResponse({"error": "forbidden", "candidates": []}, status_code=403)
    if claimed:   # 首次认领的 owner 落 Redis, 重启/换机后归属不丢
        try:
            from agent.common.session_store import save_guidelines
            await save_guidelines(gid, g)
        except Exception:
            pass
    return JSONResponse({"candidates": g["candidates"], "scope_fallback": g.get("scope_fallback", False),
                         "requested_publishers": g.get("requested_publishers")}, status_code=200)


@app.post('/plm_evidence_based/clarify')
async def plm_clarify_api(body: dict):
    """PLM-on-Hermes 步骤②: 按用户选定的 doc_id 出澄清 (SSE),带 yiyong scope。"""
    from agent.patient_like_me.v1.rag.clarification import stream_clarification

    patient_input = (body.get('patient_input') or body.get('patient_description') or '').strip()
    if not patient_input:
        return JSONResponse({"error": "patient_input is required"}, status_code=400)
    structured_hint = body.get('structured_hint') or body.get('structured_fields') or {}
    model = body.get('model')
    guideline_priority_order = body.get('guideline_priority_order') or None
    doc_id = body.get('doc_id') or body.get('selected_doc_id') or None
    product_scope = (body.get('product_scope') or 'yiyong').strip().lower() or None

    def _sse(event: str, payload: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def gen():
        async for name, payload in stream_clarification(
            patient_input=patient_input,
            structured_hint=structured_hint,
            model=model,
            guideline_priority_order=guideline_priority_order,
            doc_id=doc_id,
            product_scope=product_scope,
        ):
            yield _sse(name, payload)

    return StreamingResponse(gen(), media_type='text/event-stream',
                             headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@app.post('/plm_evidence_based/clarify_sync')
async def plm_clarify_sync_api(body: dict):
    """非流式澄清: 阻塞收完澄清, 返回干净 JSON(clarify_markdown/clarify_session_id/patient_info/no_graph)。
    agent 直接把 clarify_markdown 呈现给用户即可, 不需要解析 SSE、不要存文件。"""
    from agent.patient_like_me.v1.rag.clarification import stream_clarification
    patient_input = (body.get('patient_input') or body.get('patient_description') or '').strip()
    if not patient_input:
        return JSONResponse({"error": "patient_input is required"}, status_code=400)
    structured_hint = body.get('structured_hint') or body.get('structured_fields') or {}
    model = body.get('model')
    guideline_priority_order = body.get('guideline_priority_order') or None
    doc_id = body.get('doc_id') or body.get('selected_doc_id') or None
    product_scope = (body.get('product_scope') or 'yiyong').strip().lower() or None
    full_md = ""; sid = ""; pinfo = {}; no_graph = False; err = None
    try:
        async for name, payload in stream_clarification(
            patient_input=patient_input, structured_hint=structured_hint, model=model,
            guideline_priority_order=guideline_priority_order, doc_id=doc_id, product_scope=product_scope,
        ):
            if name == "no_graph":
                no_graph = True
            elif name == "patient_info_done":
                pinfo = payload.get("patient_info") or pinfo
            elif name == "complete":
                full_md = payload.get("full_markdown") or payload.get("clarify_markdown") or full_md
                sid = payload.get("clarify_session_id") or sid
                pinfo = payload.get("patient_info") or pinfo
            elif name == "error":
                err = payload
    except Exception as e:
        logger.error(f"clarify_sync error: {traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)
    if err:
        return JSONResponse({"status": "error", **err}, status_code=200)
    return JSONResponse({"status": "ok", "no_graph": no_graph,
                         "clarify_markdown": full_md, "clarify_session_id": sid,
                         "patient_info": pinfo}, status_code=200)


@app.post('/plm_extract_and_check')
async def plm_extract_and_check_api(body: dict):
    from agent.patient_like_me.v1.rag.workflow import run_plm_extract_and_check

    patient_input = (body.get('patient_input') or body.get('patient_description') or '').strip()
    has_structured = any(body.get(k) for k in ('age', 'gender', 'visit_stage', 'key_conditions', '_file_texts', 'structured_fields'))
    if not patient_input and not has_structured:
        return JSONResponse({"error": "patient_input is required"}, status_code=400)

    stream = body.get('stream', False)
    task_id = str(body.get('task_id', ''))
    request_data = {**body, 'patient_input': patient_input, 'task_id': task_id}

    if stream:
        async def gen():
            events = []
            result = await run_plm_extract_and_check(
                request_data,
                on_event=lambda n, p: events.append({"event": n, "payload": p}),
                task_id=task_id,
            )
            for evt in events:
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'event': 'result', 'payload': result}, ensure_ascii=False)}\n\n"

        return StreamingResponse(gen(), media_type='text/event-stream')

    try:
        result = await run_plm_extract_and_check(request_data, task_id=task_id)
        return JSONResponse(result, status_code=200)
    except Exception as e:
        logger.error(f"plm_extract_and_check error: {traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================
# PLM 管理端点: 成员管理 + 上传解锁指南 (yiyong 库)
# ============================================================
import os as _os, json as _json, uuid as _uuid, base64 as _b64, tempfile as _tmp

import httpx as _httpx

# PLM 面向所有 B 端登录用户开放, 不做成员/组织授权 —— 已移除成员管理。
# _BK_BASES 仅用于 token 校验(调 /api/users)。支持逗号分隔多后端，依次尝试、谁认就用谁。
_BK_BASES = []
for _backend_base in (
    _os.environ.get("PLM_BACKEND_BASE", "https://yiyong.noahai.co"),
    _os.environ.get("PLM_BACKEND_FALLBACK_BASES", "https://yiyong2.noahai.co"),
):
    for _backend_url in _backend_base.split(","):
        _backend_url = _backend_url.strip().rstrip("/")
        if _backend_url and _backend_url not in _BK_BASES:
            _BK_BASES.append(_backend_url)


@app.get("/plm/me")
async def plm_me(request: Request):
    """当前登录身份 + 是否管理员。前端据此决定是否显示"管理"入口。未登录 401。"""
    identity, is_admin = await _auth_admin(request)
    if not identity:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"identity": identity, "is_admin": is_admin}, status_code=200)


@app.get("/plm/guidelines")
async def plm_guidelines_list(request: Request, scope: str = "yiyong"):
    """列出指南 (name/organization/paid)。paid=true 即"付费/上锁", 需解锁。
    scope 默认 yiyong —— 与对话报告实际检索的库一致, 否则会出现"解锁了但报告用不上"。"""
    if not await _auth_identity(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from agent.patient_like_me.v1.es.plm_index import get_es_client, PLM_INDEX
    client = get_es_client()
    body = {"size": 2000, "query": {"term": {"product_scope": scope}},
            "_source": ["name", "filename", "guideline_key", "title_cn", "organization", "paid", "year"]}
    try:
        resp = client.search(index=PLM_INDEX, body=body)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    out = []
    for h in resp.get("hits", {}).get("hits", []):
        s = h.get("_source", {})
        name = (s.get("filename") or s.get("guideline_key") or s.get("title_cn")
                or s.get("name") or "(未命名)")
        out.append({"doc_id": h.get("_id"), "name": name,
                    "organization": s.get("organization"), "year": s.get("year"),
                    "paid": bool(s.get("paid", False))})
    out.sort(key=lambda x: (x.get("organization") or "", x.get("name") or ""))
    return JSONResponse({"scope": scope, "count": len(out), "guidelines": out}, status_code=200)


@app.post("/plm/unlock")
async def plm_unlock(body: dict, request: Request):
    """解锁/上锁一份指南: 翻转 yiyong ES 的 paid 标志。
    - 上传解锁: 传 name/filename, 按文件名匹配 yiyong doc → paid=false
    - 撤销上锁: 传 doc_id + locked=true → paid=true"""
    _uid, _adm = await _auth_admin(request)
    if not _uid:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _adm:
        return JSONResponse({"error": "forbidden", "detail": {"message": "仅组织管理员可解锁指南"}}, status_code=403)
    from agent.patient_like_me.v1.es.plm_index import get_es_client, PLM_INDEX
    client = get_es_client()
    locked = bool(body.get("locked", False))
    scope = (body.get("scope") or "yiyong").strip().lower()  # 与报告检索库一致
    doc_id = str(body.get("doc_id") or "").strip()
    if not doc_id:
        fname = (body.get("name") or body.get("filename") or "").strip()
        if not fname:
            return JSONResponse({"error": "doc_id or filename required"}, status_code=400)
        base = fname.rsplit(".", 1)[0]  # 去 .pdf 后缀再匹配
        q = {"size": 1, "query": {"bool": {
            "filter": [{"term": {"product_scope": scope}}],
            "should": [
                {"match_phrase": {"filename": base}},
                {"match_phrase": {"name": base}},
                {"match_phrase": {"guideline_key": base}},
                {"match_phrase": {"title_cn": base}},
            ], "minimum_should_match": 1}}}
        try:
            r = client.search(index=PLM_INDEX, body=q)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        hits = r.get("hits", {}).get("hits", [])
        if not hits:
            return JSONResponse({"ok": False, "detail": {"message": f"未在 {scope} 库匹配到该指南"}}, status_code=422)
        doc_id = hits[0]["_id"]
    try:
        client.update(index=PLM_INDEX, id=doc_id, body={"doc": {"paid": locked}})
        client.indices.refresh(index=PLM_INDEX)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"ok": True, "doc_id": doc_id, "paid": locked}, status_code=200)


@app.post("/plm/upload_guideline")
async def plm_upload_guideline(body: dict, request: Request):
    """上传单个指南 PDF → 抽取文本 → 嵌入 → 索引进 yiyong 库(默认 paid=True 上锁)。
    入参: {filename, organization, pdf_base64}. (文本型 PDF; 扫描件 OCR 走批量管线)"""
    _uid, _adm = await _auth_admin(request)
    if not _uid:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _adm:
        return JSONResponse({"error": "forbidden", "detail": {"message": "仅组织管理员可上传解锁指南"}}, status_code=403)
    filename = (body.get("filename") or "").strip() or ("上传指南_" + _uuid.uuid4().hex[:6] + ".pdf")
    org = (body.get("organization") or "其他").strip()
    b64 = body.get("pdf_base64") or ""
    if not b64:
        return JSONResponse({"error": "pdf_base64 is required"}, status_code=400)
    try:
        raw = _b64.b64decode(b64.split(",")[-1])
    except Exception as e:
        return JSONResponse({"error": f"bad base64: {e}"}, status_code=400)
    try:
        try:
            import pymupdf
        except ModuleNotFoundError:
            import fitz as pymupdf
        with _tmp.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tf.write(raw); path = tf.name
        d = pymupdf.open(path)
        pages = [d.load_page(i).get_text() for i in range(min(len(d), 200))]
        d.close(); _os.unlink(path)
        text = "\n".join(pages).strip()
        if len(text) < 40:
            return JSONResponse({"error": "PDF 无可抽取文本(可能是扫描件, 需走 OCR 批量管线)"}, status_code=422)
        from agent.patient_like_me.v1.rag.evidence import _embed
        from agent.patient_like_me.v1.es.plm_index import get_es_client, PLM_INDEX
        title = filename.rsplit(".", 1)[0]
        vec = await _embed((title + "\n" + text[:2000]).strip())
        doc = {
            "name": filename, "title": title, "summary": text[:1500],
            "organization": org, "product_scope": "yiyong",
            "paid": True, "has_graph": False,
            "full_text": text,
            "title_vector": vec, "summary_vector": vec, "text_vector": vec,
        }
        client = get_es_client()
        r = client.index(index=PLM_INDEX, body=doc)
        client.indices.refresh(index=PLM_INDEX)
        return JSONResponse({"ok": True, "doc_id": r.get("_id"), "name": filename,
                             "organization": org, "chars": len(text)}, status_code=200)
    except Exception as e:
        logger.error("upload_guideline error: %s", traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)
