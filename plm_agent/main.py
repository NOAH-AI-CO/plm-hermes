import asyncio
import json
import uuid
import traceback
import openai
from dotenv import load_dotenv

import os
import sys
import time
import pathlib
import tempfile

from agent.core.schema import BaseResponse
from utils.pubmed_opt.pubmed_es_only_search import es_only_search
from utils.sensitive_check.diting import DitingSensitiveChecker
from i18n.languages import normalize as normalize_language
from i18n.languages import resolve as resolve_language

import faulthandler
faulthandler.enable()  # Print C-level stack trace on segfault/SIGABRT


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
load_dotenv()

from llm.azure_models import GPT5Mini
from llm.gcp_models import ClaudeSonnet45
from llm.moonshot_models import KimiK2Thinking
from llm.deepseek_models import CompositeDeepseekChat
from starlette.background import BackgroundTask
from agent.human_in_loop.planning_v5 import PlanningAgent
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from utils.catalyst.retrieve import get_catalyst_list, get_catalysts_and_related_info_by_id, get_company_catalysts_and_related_info
from core import lifespan
from workflows.drug_compete import drug_compete
from utils.sql_client import get_connection, get_connection_user, text
from workflows.conf_paper_search import search_conference_papers
from workflows.clinical_trial_design import clinical_trial_design
from workflows.clinical_trial_result_comparison import compare_clinical_trial_results
from workflows.clinical_trial_search import clinical_trial_search
from structs import ClinicalTrialDesignComparison, RunPromptTest
from test_prompt import prepare_testset, run_testset
from agent.router import agent_routing
from agent.modules import pipeline as module_pipeline
from agent.modules.registry import is_pipeline_enabled
from agent.explore.schema import ProcessingType
from agent.core.preset import AgentPreset
from tools.general.helper import turncate_dict
from utils.core.prompt_fetcher import PromptFetcher
from llm.gcp_models import CompositeClaude
import logging.config
from logging_config import LOGGING_CONFIG, log_id_var, task_id_var
from agent.policy.article_analyzer import ArticleAnalyzer
from agent.knowledge.summary import batch_process_summary, search_and_context_detail_map, search_and_selection, search_and_selection_docs
from workflows.analyze_target import drug_target_analysis_stream, run_target_analysis_stream, search_clinical_trial, search_drug, split_table, target_for_indications_and_epidemiology_and_gold_standard, test_aggregate_epidemiology_and_gold_standard_of_treatment_and_summarize, test_drug_pubmed_agent, epidemiology_and_gold_standard_of_treatment_v2, test_guideline_agent, news_and_catalyst_agent, test_split_table_v4, split_table_v5, test_target_news_search
from workflows.sinovac_thesis import get_pmid_info_by_title_all, load_pmids_and_fetch_infos, output_the_thesis, build_full_thesis_from_parallel, hallucination_check, test_replace_pmids_with_refs, translate_thesis_chunked
from workflows.thesis_writing.thesis_controller import gen_outline, gen_thesis
from agent.explore.mindsearch_agent_v3_pubmed import fetch_pubmed_articles_by_existing_logic, pubmed_hybrid_search



# from utils.bio_quant.adapter import run_bio_quant_analysis


from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)
app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.config.dictConfig(LOGGING_CONFIG)

from agent.writing import writing_data_router
app.include_router(writing_data_router)

# Workspace tracker REST endpoints (assets / viewState / viewedFiles).
# Independent of /chat so the front-end can hydrate without a chat in flight.
from agent.workspace.routes import router as workspace_router
app.include_router(workspace_router)

from agent.patient_like_me.v1.custom_rag.kb_api import router as plm_custom_rag_router
app.include_router(plm_custom_rag_router)

@app.get("/ping")
def read_root():
    return {"Hello": "World"}

# RESTFUL API 是混乱的起点，所以我这里将 api 使用文字定义清楚，避免给其他人造成误解，所以就是 GET get_server_info 而不是 GET server_info
@app.get('/get_server_info')
async def get_server_info():
    """
    获取服务信息 版本号等等，我只关心版本号
    """
    info = {
        'version': '1.0.42',
        'message': 'ppt emit start status before cite image download'
    }
    return JSONResponse(info)

@app.get("/error")
def raise_error():
    raise Exception("Test error")

@app.post('/design_comparison')
async def design_comparison_api(body: ClinicalTrialDesignComparison):
    try:
        res = await clinical_trial_design(**dict(body))
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/clinical_results')
async def result_comparison_api(body: dict):
    try:
        res = await compare_clinical_trial_results(**body)
        return JSONResponse(res)
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/clinical_trial')
async def clinical_trial_api(body: dict):
    try:
        res = await clinical_trial_search(**body)
        return JSONResponse(res)
    except Exception as e:
        logger.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/drug_compete')
async def drug_compete_api(body: dict):
    try:
        res = await drug_compete(**body)
        return JSONResponse(res)
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post('/search_conference_papers')
def search_conference_papers_api(body: dict):
    try:
        res = search_conference_papers(**body)
        return JSONResponse(res)
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)

# Used when listing catalysts
@app.post('/catalyst_list')
def get_catalyst_list_api(body: dict):
    try:
        catalyst_id = body.pop('id', None)
        company = body.pop('company', None)
        top_n = body.pop('top_n', 10)
        page = body.pop('page', 1)
        body.pop('step_no', None)
        if catalyst_id:
            body = {'catalyst_id': catalyst_id}
        if company:
            body['focus_company'] = [company]
        res = get_catalyst_list(top_n=top_n, page=page, get_count=True, details=True, custom_impact=True, **body)
        return JSONResponse(res)
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)

# Used when referencing catalyst
@app.post('/catalyst_info')
async def catalyst_info_api(body: dict):
    try:
        ids = []
        id_keys = ['id', 'catalyst_id', 'ids']

        filters = body.get('filters', {})
        if filters:
            body = filters
        for key in id_keys:
            if key in body:
                ids = body[key]
                break
        res = await get_catalysts_and_related_info_by_id(ids)
        return JSONResponse(res)
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post('/run_prompt_playground_test')
async def test_playground_prompt(body: RunPromptTest):
    try:
        if not body.select_fields:
            res = await run_testset(testset=body.testset, prompt=body.prompt)
        else:
            testset = prepare_testset(nctids=body.nctids, select_fields=body.select_fields)
            res = await run_testset(testset=testset, prompt=body.prompt)
        return JSONResponse(json.dumps(res, ensure_ascii=False))
    except openai.BadRequestError as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e.message)}, status_code=400)
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post('/chat')
async def chat_api(body: dict, request: Request):
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else None
        
    logger.info(f"Received chat request from {client_ip}")
    
    try:
        for k,v in list(body.items()):
            if k in ['hitl_mode', 'approve', 'model']:
                continue
            if k != "user_prompt" and not v:
                body.pop(k)
        params = body.get('params', {})
        params['client_ip'] = client_ip
        agent_name = body.pop('agent', None)
        if not agent_name:
            return JSONResponse({"error": "Agent name is required"}, status_code=400)
        if agent_name == 'investment_report':
            symbol = body['user_prompt'].strip()
            agent: AgentPreset = agent_routing[agent_name](symbol=symbol, test=(True if symbol=='NOAH' else False), **body)
            return StreamingResponse(agent.start(**body), media_type='text/event-stream')
        # if 'files' in params and params['files'] and 'user_prompt' in body and body['user_prompt'].strip() and not agent_name.startswith('planning'):
        #     try:
        #         files = params['files']
        #         with get_connection_user() as conn:
        #             file_contents = conn.execute(text(f"""SELECT name, content, url, id FROM "API_attachment" WHERE id = ANY(ARRAY[:ids]::uuid[])"""), {"ids": [f for f in files]})
        #             file_contents = file_contents.fetchall()
        #             if not file_contents:
        #                 raise(Exception('no file_contents found'))
        #             body['attachments'] = file_contents
        #     except: 
        #         traceback.print_exc()
        #         print('error getting attachment content')
        if 'user_prompt' in body:
            if body['user_prompt']:
                body['user_prompt'] = body['user_prompt'].strip()
            if 'symbol' in body or body['user_prompt'].startswith('/IRG '):
                agent_name = 'investment_report'
                symbol = body.pop('symbol', body['user_prompt'][5:].strip())
                agent: AgentPreset = agent_routing[agent_name](symbol=symbol, test=(True if symbol=='NOAH' else False), **body)
                return StreamingResponse(agent.start(**body), media_type='text/event-stream')
            sig = ''
            if body['user_prompt'].startswith('/结构化 '):
                sig = '/结构化 '
                agent_name = 'multi-llm'
                body['user_prompt'] = body['user_prompt'][len(sig):].strip()
                body['bp_structurize'] = True
                agent = agent_routing[agent_name](**body)
                return StreamingResponse(agent.start(**body), media_type='text/event-stream')
            if body['user_prompt'].startswith('/评估 '):
                sig = '/评估 '
                agent_name = 'multi-llm'
                body['user_prompt'] = body['user_prompt'][len(sig):].strip()
                body['bp_eval'] = True
                agent = agent_routing[agent_name](**body)
                return StreamingResponse(agent.start(**body), media_type='text/event-stream')
            
            extract_configs = [('/提取1.0', 3), ('/提取1.1', 4), ('/提取 ', None)]
            for _sig, level in extract_configs:
                if body['user_prompt'].startswith(_sig):
                    sig = _sig
                    agent_name = 'multi-llm'
                    body['user_prompt'] = body['user_prompt'][len(_sig):].strip()
                    body['bp_extract'] = True
                    if level is not None:
                        body['detail_level'] = level
                    agent = agent_routing[agent_name](**body)
                    return StreamingResponse(agent.start(**body), media_type='text/event-stream')
            for option in ['/PAPER', '/paper', '/p', '/P']:
                if body['user_prompt'].startswith(option):
                    sig = option
                    break
            if sig:
                agent_name = 'planning_paper'
        if is_pipeline_enabled(agent_name):
            body['agent'] = agent_name
            return StreamingResponse(
                module_pipeline.stream_json(module_pipeline.dispatch(body)),
                media_type='text/event-stream',
            )
        agent = agent_routing[agent_name](**body)
        return StreamingResponse(agent.start(**body), media_type='text/event-stream')
    except KeyError as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400) 
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400) 

# agent_name, file , review_type("formal", "scientific", "both")
@app.post('/testiit')
async def test_iit(agent_name: str = Form(...), review_type: str = Form(...), file: UploadFile = File(...)):
    filename = file.filename
    ext = filename.split('.')[-1].lower()
    file_content = await file.read()
    agent: AgentPreset= agent_routing[agent_name]()
    return StreamingResponse(agent.start(file=file_content, ext=ext,review_type=review_type),media_type='text/event-stream')



@app.post('/bp_analysis')
async def bp_analysis_api(body: dict):
    from agent.bp.bp_analysis import batch_process_bp
    try:
        bp_requests = body.get('bp_requests', None)
        if not bp_requests:
            return JSONResponse({"error": "BP request required"}, status_code=400)
        
        # Create a background task to run the agent
        async def run_task_in_background():
            try:
                await batch_process_bp(bp_requests=bp_requests)
            except Exception as e:
                logging.error(f"Background agent execution failed: {traceback.format_exc()}")

        return JSONResponse(
            {"result": "success"}, 
            status_code=200,
            background=BackgroundTask(run_task_in_background)
        )
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post('/ocr_translate')
async def ocr_translate_api(body: dict):
    """Backend 上传文件后调用：根据 attachment_id 对应文件类型走文本翻译（md/doc/docx/txt）或 OCR 翻译（pdf/图片），并回调 Backend 写回译文。"""
    from pathlib import Path
    from agent.translation.ocr_translate import process_translation_by_attachment_id
    from agent.translation.txt_translate import (
        TEXT_EXTENSIONS,
        process_text_translation_by_attachment_id,
    )
    from utils.utils.attachment import AttachmentManager

    try:
        attachment_id = body.get('attachment_id')
        target_language = body.get('target_language', '').strip()
        backend_task_id = body.get('backend_task_id')
        if not attachment_id or not target_language or backend_task_id is None:
            return JSONResponse(
                {"error": "attachment_id, target_language and backend_task_id are required"},
                status_code=400,
            )
        input_language = (body.get('input_language') or '').strip() or None
        translation_model_id = (
            body.get("translation_model_id")
            or body.get("model_id")
            or ""
        )
        translation_model_id = str(translation_model_id).strip()
        translate_reference = (
            str(body.get("translate_reference", "false")).strip().lower() == "true"
        )

        # 根据附件文件名判断走文本翻译还是 OCR 翻译
        mgr = AttachmentManager(public=False)
        attachments = mgr.fetch_attachments([str(attachment_id)], False)
        if not attachments:
            return JSONResponse(
                {"error": "attachment not found"},
                status_code=404,
            )
        file_name = attachments[0].get("name") or ""
        suffix = Path(file_name).suffix.lower()
        is_text_type = suffix in TEXT_EXTENSIONS

        async def run_task_in_background():
            try:
                if is_text_type:
                    await process_text_translation_by_attachment_id(
                        attachment_id=str(attachment_id),
                        target_language=target_language,
                        input_language=input_language,
                        backend_task_id=int(backend_task_id),
                        translation_model_id=translation_model_id,
                        translate_reference=translate_reference,
                    )
                else:
                    await process_translation_by_attachment_id(
                        attachment_id=str(attachment_id),
                        target_language=target_language,
                        input_language=input_language,
                        backend_task_id=int(backend_task_id),
                        translation_model_id=translation_model_id,
                        translate_reference=translate_reference,
                    )
            except Exception as e:
                logging.error(f"ocr_translate background failed: {traceback.format_exc()}")

        return JSONResponse(
            {"result": "success"},
            status_code=200,
            background=BackgroundTask(run_task_in_background),
        )
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)
    
        
@app.post('/batch_process_summary')
async def batch_process_summary_api(body: dict):
    try:
        files = body.get('files', None)
        if not files:
            return JSONResponse({"error": "files is required"}, status_code=400)
        async def run_task_in_background():
            try:
                await batch_process_summary(files=files)
            except Exception:
                logging.error(f"Background summary execution failed: {traceback.format_exc()}")

        return JSONResponse(
            {"result": "success"},
            status_code=200,
            background=BackgroundTask(run_task_in_background)
        )
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)

# @app.post('/search_and_selection')
# async def search_and_selection_api(body: dict):
#     try:
#         user_query = body.get('user_query', None)
#         parent_id = body.get('parent_id', None)
#         if not user_query:
#             return JSONResponse({"error": "user_query is required"}, status_code=400)
#         async def run_task_in_background():
#             try:
#                 await search_and_selection(user_query=user_query, parent_id=parent_id)
#             except Exception:
#                 logging.error(f"Background search execution failed: {traceback.format_exc()}")

#         return JSONResponse(
#             {"result": "success"},
#             status_code=200,
#             background=BackgroundTask(run_task_in_background)
#         )
#     except Exception as e:
#         logging.error(traceback.format_exc())
#         return JSONResponse({"error": str(e)}, status_code=400)
    
@app.post('/iit_review')
async def iit_api(body: dict):
    from agent.iit.core.iit_review_agent import IITAgent
    try:
        iit_requests = body.get('iit_requests', None)
        if not iit_requests:
            return JSONResponse({"error": "IIT request required"}, status_code=400)
        agent = IITAgent(**body)
        
        # Create a background task to run the agent
        async def run_agent_in_background():
            try:
                async for _ in agent.start(**body):
                    pass
            except Exception as e:
                logging.error(f"Background agent execution failed: {traceback.format_exc()}")
            finally:
                await agent.close()

        return JSONResponse(
            {"result": "success"}, 
            status_code=200,
            background=BackgroundTask(run_agent_in_background)
        )
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/ethics/policy/index')
async def ethics_policy_index_api(body: dict):
    from agent.ethics.policy_service import index_policy_documents
    try:
        owner_id = str(body.get("owner_id") or "").strip()
        attachments = body.get("attachments") or []
        doc_ids = [str(a.get("doc_id") or "").strip() for a in attachments if str(a.get("doc_id") or "").strip()]
        if not owner_id:
            return JSONResponse({"error": "owner_id is required"}, status_code=400)
        if not doc_ids:
            return JSONResponse({"error": "attachments/doc_id is required"}, status_code=400)

        async def run_task_in_background():
            try:
                await index_policy_documents(owner_id=owner_id, attachments=attachments)
            except Exception:
                logging.error(f"Background ethics policy index failed: {traceback.format_exc()}")

        return JSONResponse(
            {"status": "accepted", "indexed_count": len(doc_ids)},
            status_code=200,
            background=BackgroundTask(run_task_in_background),
        )
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/ethics/policy/delete')
async def ethics_policy_delete_api(body: dict):
    from agent.ethics.policy_service import delete_policy_documents
    try:
        owner_id = str(body.get("owner_id") or "").strip()
        attachments = body.get("attachments") or []
        doc_ids = [str(a.get("doc_id") or "").strip() for a in attachments if str(a.get("doc_id") or "").strip()]
        if not owner_id:
            return JSONResponse({"error": "owner_id is required"}, status_code=400)
        if not doc_ids:
            return JSONResponse({"error": "attachments/doc_id is required"}, status_code=400)

        async def run_task_in_background():
            try:
                await delete_policy_documents(owner_id=owner_id, attachments=attachments)
            except Exception:
                logging.error(f"Background ethics policy delete failed: {traceback.format_exc()}")

        return JSONResponse(
            {"status": "accepted", "delete_count": len(doc_ids)},
            status_code=200,
            background=BackgroundTask(run_task_in_background),
        )
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/ethics/review/execute')
async def ethics_review_execute_api(body: dict):
    from agent.ethics.core.ethics_review_agent import EthicsReviewAgent
    try:
        review_id = str(body.get("review_id") or "").strip()
        owner_id = str(body.get("owner_id") or "").strip()
        if not review_id or not owner_id:
            return JSONResponse({"error": "review_id and owner_id are required"}, status_code=400)
        review_checklist = body.get("review_checklist")
        if not isinstance(review_checklist, list) or not review_checklist:
            return JSONResponse(
                {"error": "review_checklist must be provided as non-empty list"},
                status_code=400,
            )

        async def run_task_in_background():
            try:
                agent = EthicsReviewAgent(payload=body)
                await agent.run()
            except Exception:
                logging.error(f"Background ethics review execute failed: {traceback.format_exc()}")

        return JSONResponse(
            {"status": "accepted", "review_id": review_id},
            status_code=200,
            background=BackgroundTask(run_task_in_background),
        )
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/ethics/review/infer-sheet-code')
async def ethics_review_infer_sheet_code_api(body: dict):
    from agent.ethics.core.ethics_review_agent import EthicsReviewAgent
    try:
        owner_id = str(body.get("owner_id") or "").strip()
        if not owner_id:
            return JSONResponse({"error": "owner_id is required"}, status_code=400)
        if "doc_ids" in body and not isinstance(body.get("doc_ids"), list):
            return JSONResponse({"error": "doc_ids must be a list"}, status_code=400)

        agent = EthicsReviewAgent(payload=body)
        result = await agent.infer_sheet_code_only()
        return JSONResponse({"status": "success", **result}, status_code=200)
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/ethics/policy/search')
async def ethics_policy_search_api(body: dict):
    from agent.ethics.policy_service import search_policy_context
    try:
        owner_id = str(body.get("owner_id") or "").strip()
        query = str(body.get("query") or "").strip()
        top_k_raw = body.get("top_k", 5)
        top_k = int(top_k_raw) if str(top_k_raw).isdigit() else 5
        if not owner_id:
            return JSONResponse({"error": "owner_id is required"}, status_code=400)
        if not query:
            return JSONResponse({"error": "query is required"}, status_code=400)
        if top_k <= 0:
            top_k = 5
        hits = search_policy_context(owner_id=owner_id, query_text=query, top_k=min(top_k, 20))
        return JSONResponse(
            {
                "status": "success",
                "query": query,
                "top_k": min(top_k, 20),
                "hits_count": len(hits),
                "hits": hits,
            },
            status_code=200,
        )
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/journal_recommendation')
async def journal_recommendation_api(body: dict):
    from agent.journal_recommendation.journal_recommendation_agent_v2 import JournalRecommendationAgentV2
    try:
        journal_requests = body.get('journal_requests', None)
        if not journal_requests:
            return JSONResponse({"error": "Journal requests required"}, status_code=400)

        for req in journal_requests:
            if 'abstract' not in req or not req['abstract']:
                return JSONResponse({"error": "Abstract is required in each request"}, status_code=400)

        agent = JournalRecommendationAgentV2(**body)
        # Create a background task to run the agent
        async def run_agent_in_background():
            try:
                async for _ in agent.start(**body):
                    pass
            except Exception as e:
                logging.error(f"Background agent execution failed: {traceback.format_exc()}")

        return JSONResponse(
            {
                "result": "success", 
                "message": f"Processing {len(journal_requests)} journal recommendation requests"
            }, 
            status_code=200,
            background=BackgroundTask(run_agent_in_background)
        )
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/research_recommendation')
async def research_recommendation_api(body: dict):
    from agent.simple_research_rec.research_recommendation import stream_research_rec
    from fastapi.responses import StreamingResponse as FastAPIStreamingResponse

    query = (body.get('query') or '').strip()
    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)

    async def event_stream():
        try:
            async for event in stream_research_rec(query):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error("[ResearchRec] SSE stream error: %s\n%s", str(e), traceback.format_exc())
            yield f"data: {json.dumps({'status': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return FastAPIStreamingResponse(event_stream(), media_type='text/event-stream')


@app.post('/test')
async def test_api(body: dict):
    try:
        if body['agent'] == 'test':
            async def number_stream():
                for i in range(1, 61):
                    yield f"data: {i}\n\n"
                    await asyncio.sleep(1)
            return StreamingResponse(number_stream(), media_type='text/event-stream')
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)
    
@app.get('/conn')
async def conn_api():
    try:
        with get_connection() as conn:
            conn.execute(text("SELECT 1"))
        return JSONResponse({"result": "success"})
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)
    

# Used when generating investment report
@app.post('/catalyst_by_company')
async def catalyst_by_company_api(body: dict):
    try:
        catalyst_info, company_name = await get_company_catalysts_and_related_info(body["ticker"], include_past=body.get('include_past',False))
        return JSONResponse({"name":company_name, "data": catalyst_info})
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)
    
@app.post('/claude')
async def claude(body: dict):
    try:
        llm = GPT5Mini()
        temperature = body.get('temperature', 1)
        user_prompt = body.get('user_prompt', "Hi")
        system_prompt = body.get('system_prompt', "")
        gen = llm.stream_call(sys_prompt=system_prompt, user_prompt=user_prompt, temperature=temperature)
        return StreamingResponse(gen, media_type='text/event-stream')
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


async def _update_api_task(task_id: str, *, task_status: str, result_json: dict):
    """Update API_task row directly via the user DB connection (mirrors write_bp_context)."""
    sql = text("""
        UPDATE "API_task"
        SET task_status = :task_status,
            result_json = CAST(:result_json AS jsonb),
            time_updated = NOW()
        WHERE id = CAST(:task_id AS uuid)
    """)
    params = {
        "task_id": str(task_id),
        "task_status": task_status,
        "result_json": json.dumps(result_json, ensure_ascii=False),
    }

    def _do():
        with get_connection_user() as conn:
            conn.execute(sql, params)
            conn.commit()

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _do)
    except Exception as e:
        logger.error(f"Failed to update API task {task_id}: {e}")


@app.post('/agent_api_mode')
async def agent_api_mode(body: dict):
    from datetime import datetime
    try:
        prompt = body.get('prompt', '')
        language = normalize_language(body.get('language', ''))
        task_id = body.get('task_id')

        _body = {
            "user_prompt": prompt,
            "language": language,
            "thread_id": f"evaluation-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "planning_task": {
                "id": f"evaluation-task-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "user": "evaluation_script"
            }
        }

        async def run_task_in_background():
            try:
                if task_id:
                    await _update_api_task(task_id, task_status='process', result_json={'status': 'process'})
                agent = PlanningAgent(**_body)
                ret = None
                final_message = ''
                async for ret in agent.start_wo_dump(**_body, api_mode=True):
                    if not isinstance(ret, dict):
                        continue
                    if ret.get('message'):
                        final_message = ret.get('message', '')
                if not final_message and isinstance(ret, dict):
                    final_message = ret.get('message', '')
                if task_id:
                    await _update_api_task(task_id, task_status='complete', result_json={'status': 'complete', 'data': final_message})
            except Exception as e:
                logging.error(f"Background agent execution failed: {traceback.format_exc()}")
                if task_id:
                    await _update_api_task(task_id, task_status='error', result_json={'status': 'error', 'error': str(e)})

        return JSONResponse(
            {"result": "success"},
            status_code=200,
            background=BackgroundTask(run_task_in_background)
        )
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/search_api_mode')
async def search_api_mode(body: dict):
    from agent.explore.mindsearch_agent_v3_1 import MindSearchAgentV3_1
    try:
        prompt = (body.get('prompt') or '').strip()
        if not prompt:
            return JSONResponse({"error": "prompt is required"}, status_code=400)

        raw_language = body.get('language', '')
        language = normalize_language(raw_language)
        params = body.get('params', {})
        params['language'] = language
        # If API caller explicitly sets `language`, force response language accordingly
        # even when the user prompt text itself is in another language.
        params['force_output_language'] = bool(raw_language)
        if raw_language:
            params['preferred_output_language'] = resolve_language(language)
        params.setdefault('model', '')
        params.setdefault('enable_rag', True)
        params.setdefault('is_hitl', True)

        _body = {
            "user_prompt": prompt,
            "history_messages": body.get('history_messages', []),
            "params": params,
            "skip_followup": body.get('skip_followup', True),
        }

        agent = MindSearchAgentV3_1()
        final_output = ''

        async for ret in agent.start_wo_dump(**_body):
            if not isinstance(ret, dict):
                continue

            content = ret.get('content') or ''
            if content:
                final_output = content

            if ret.get('processing_type') in [
                ProcessingType.RESPONSEDONE,
                int(ProcessingType.RESPONSEDONE)
            ]:
                break

        return JSONResponse({"result": "success", "data": final_output})
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.middleware("http")
async def log_id_middleware(request: Request, call_next):
    # 生成或获取 log_id
    log_id = request.headers.get("X-Correlation-ID") or request.headers.get("x-correlation-id") or str(uuid.uuid4())
    task_id = request.headers.get("X-Task-ID") or request.headers.get("x-task-id") or str(uuid.uuid4())

    # 设置到 context variable
    log_id_var.set(log_id)
    task_id_var.set(task_id)

    try:
        # 处理请求
        response = await call_next(request)
        # 添加到响应头
        response.headers["X-Correlation-ID"] = log_id
        
        return response
    except Exception as e:
        logger.error(f"Request failed: {str(e)}")
        raise

# @app.middleware("http")
# async def request_logging_middleware(request: Request, call_next):
#     """
#     @summary: request log
#     """
#     # 参数打印
#     if request.path_params:
#         logger.info(f"Request path params: {request.path_params}")
#     if request.query_params:
#         logger.info(f"Request query params: {dict(request.query_params)}")

#     content_type = request.headers.get("content-type", "").lower()
#     method = request.method.upper()
    
#     # Store original body for reconstruction
#     original_body = None
    
#     if method in ("POST", "PUT", "PATCH", "DELETE"):
#         if "multipart/form-data" in content_type:
#             # Don't consume multipart data in middleware - it's complex to reconstruct
#             logger.info(f"Request content-type: multipart/form-data")
#         elif "application/x-www-form-urlencoded" in content_type:
#             # Don't consume form data in middleware - it's complex to reconstruct
#             logger.info(f"Request content-type: application/x-www-form-urlencoded")
#         elif "application/json" in content_type:
#             try:
#                 original_body = await request.body()
#                 if original_body:
#                     logger.info(f"Request JSON body: {original_body.decode('utf-8')}")
#                     # Reconstruct the request with the same body
#                     async def receive():
#                         return {"type": "http.request", "body": original_body}
#                     request._receive = receive
#             except Exception as e:
#                 logger.warning(f"Failed to read JSON body: {e}")
#         else:
#             try:
#                 original_body = await request.body()
#                 if original_body:
#                     logger.info(f"Request raw body: {original_body}")
#                     # Reconstruct the request with the same body
#                     async def receive():
#                         return {"type": "http.request", "body": original_body}
#                     request._receive = receive
#             except Exception as e:
#                 logger.warning(f"Failed to read raw body: {e}")
    
#     # 耗时记录
#     start_time = time.time()
#     response = await call_next(request)
#     duration = time.time() - start_time
#     logger.info(f"Request completed: {response.status_code}, duration: {duration:.3f}s")
#     return response

@app.post('/update_prompts')
async def update_prompts(request: Request):
    """
    @summary: Update prompts
    """
    try:
        data = await request.json()
        prompt_fetcher = PromptFetcher()
        prompt_fetcher.fetch(data.get('name'))
        # 处理更新逻辑
        return JSONResponse({"result": "update successful", "data": data})
    except Exception as e:
        logger.error(f"Failed to update prompts: {e}")
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post('/update_prompt_list')
async def update_prompts(request: Request):
    """
    @summary: Update prompts
    """
    try:
        data = await request.json()
        prompt_fetcher = PromptFetcher()
        prompt_fetcher.update_list(data.get('prompt_list'))
        # 处理更新逻辑
        return JSONResponse({"result": "update successful", "data": data})
    except Exception as e:
        logger.error(f"Failed to update prompts: {e}")
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/summarize_rag_results')
async def summarize_rag_results_api(body: dict):
    """
    @summary: RAG结果总结接口
    
    对RAG向量检索的结果进行大模型总结，并流式返回
    
    POST 参数:
      - content_list: 文本片段列表（必需），每个元素包含检索到的文本片段
      - query: 原始查询（可选），用于提供上下文
      - language: 输出语言（可选），默认中文
      - temperature: 模型温度（可选），默认0.3
    
    返回: 流式总结结果
    """
    try:
        content_list = body.get('content_list')
        if not isinstance(content_list, list):
            return JSONResponse({'error': 'content_list必须是列表类型'})
        
        for i, content in enumerate(content_list):
            if not isinstance(content, str) or not content.strip():
                return JSONResponse({'error': f'content_list[{i}]必须是非空字符串'})
        
        query = body.get('query')
        if not query or not isinstance(query, str) or not query.strip():
            return JSONResponse({'error': 'query参数是必需的，且必须是非空字符串'})
        
        language = normalize_language(body.get('language', 'zh'))
        temperature = float(body.get('temperature', 0.3))

        temperature = max(0.1, min(1.0, temperature))

        if language == 'zh-CN':
            sys_prompt = """你是一个专业的文本总结助手。请根据提供的文本片段和查询，生成一个准确、清晰的总结。

            总结要求：
            1. 保持客观准确，不添加原文中没有的信息
            2. 突出重要信息和关键点
            3. 使用清晰、简洁的语言
            4. 如果没有检索到的文本片段，请回答这个'关于这个问题，我暂时还不会。'
            5. 根据内容长度和复杂度，自动调整总结的详细程度

            请开始总结：
            """
        else:
            sys_prompt = """You are a professional text summarization assistant. Please generate an accurate and clear summary based on the provided text fragments and query.

            Summary requirements:
            1. Maintain objectivity and accuracy, do not add information not present in the original text
            2. Highlight important information and key points
            3. Use clear and concise language
            4. If no text segments are retrieved, please answer this 'Regarding this question, I don't know how to answer it yet.'
            5. Automatically adjust the level of detail based on content length and complexity

            Please begin the summary:
            """
        content_text = str()
        if content_list:
            content_text += "\n\n".join([f"片段 {i+1}: {content}" for i, content in enumerate(content_list)])
        user_prompt = f"原始查询: {query}\n\n检索到的文本片段:\n{content_text if content_text else '没有检索到的文本片段'}"
        
        llm = CompositeClaude()
        
        async def generate_summary():
            try:
                async for chunk in llm.stream_call(
                    sys_prompt=sys_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature
                ):
                    yield f"data: {json.dumps({'status': 'summary_doing', 'data': chunk}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'status': 'summary_done', 'data': ''}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error(f"总结生成失败: {str(e)}")
                yield f"data: {json.dumps({'status': 'summary_error', 'data': f'总结生成失败: {str(e)}'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'status': 'summary_done', 'data': ''}, ensure_ascii=False)}\n\n"
        
        return StreamingResponse(generate_summary(), media_type='text/event-stream')
        
    except ValueError as e:
        logger.error(f"总结接口参数错误: {str(e)}")
        return JSONResponse({"error": str(e)})
    except Exception as e:
        logger.error(f"总结接口失败: {str(e)}")
        return JSONResponse({"error": f"总结服务异常，请稍后重试 {str(e)}"})


@app.post('/analyze_article')
async def analyze_article_api(body: dict):
    """
    @summary: 文章分析接口
    
    分析文章的前几页文字，提取标题、描述和目录信息
    
    POST 参数:
      - content: 文章内容字符串（必需）
    
    返回: 包含标题、描述和目录的字典
    """
    try:
        content = body.get('content')
        if not content or not isinstance(content, str) or not content.strip():
            return JSONResponse({'error': 'content参数是必需的，且必须是非空字符串'})
        
        analyzer = ArticleAnalyzer()
        result = await analyzer.analyze_article(content)
        
        return JSONResponse(result, status_code=200)
        
    except ValueError as e:
        logger.error(f"文章分析接口参数错误: {str(e)}")
        return JSONResponse({"error": str(e)})
    except Exception as e:
        logger.error(f"文章分析接口失败: {str(e)}")
        return JSONResponse({"error": "文章分析服务异常，请稍后重试"})


@app.post("/test_epidemiology_and_gold_standard_of_treatment")
async def test_epidemiology_and_gold_standard_of_treatment_api(body: dict):
    """
    @summary: 靶点适应症、流行病学和治疗金标准分析流式接口
    
    靶点适应症、流行病学和治疗金标准分析流式接口
    
    POST 参数:
      - target: 靶点名称
      - indication: 适应症名称
      - language: 语言
    
    return: 流式返回靶点适应症、流行病学和治疗金标准分析结果
    """
    try:
        target = (body.get('target') or '').strip()
        indication = (body.get('indication') or '').strip()
        language = normalize_language(body.get('language', ''))

        async def gen():
            async for content in test_epidemiology_and_gold_standard_of_treatment(target, indication, language=language):
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"

        return StreamingResponse(gen(), media_type='text/event-stream')
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/test_news_and_catalyst_agent")
async def test_news_and_catalyst_agent_api(body: dict):
    """
    @summary: 靶点催化剂事件与新闻 流式接口
    
    靶点催化剂事件与新闻 流式接口
    
    POST 参数:
      - target: 靶点名称
      - language: 语言
    
    return: 流式返回靶点催化剂事件与新闻结果
    """
    try:
        target = (body.get('target') or '').strip()
        language = normalize_language(body.get('language', ''))
        async def gen():
            async for content in news_and_catalyst_agent(target, language):
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"

        return StreamingResponse(gen(), media_type='text/event-stream')
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/test_split_table_v5")
async def split_table_v5_api(body: dict):
    """
    @summary: 产品管线和临床试验 流程
        
    POST 参数:
      - target: 靶点名称
    
    return:  产品管线表 药物分析 临床实验表  临床试验对比 适应症横比 
    drug_trial_comparison_summary.update({'pipline_table': drug_table_md, 'drug_depth_analysis': last_drug_chunk})
    drug_trial_comparison_summary.update({'horizontal_comparison_of_indications': last_horizontal_comparison_of_indications_chunk})
    drug_trial_comparison_summary.update(last_clinical_trial_chunk)
    """
    try:
        target = (body.get('target') or '').strip()

        async def gen():
            async for content in split_table_v5(target):
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"

        return StreamingResponse(gen(), media_type='text/event-stream')
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/test_target_for_indications_and_epidemiology_and_gold_standard")
async def target_for_indications_and_epidemiology_and_gold_standard_api(body: dict):
    """
    @summary: 靶点适应症、流行病学和治疗金标准分析流式接口
    
    靶点适应症、流行病学和治疗金标准分析流式接口
    
    POST 参数:
      - target: 靶点名称
      - language: 语言
    
    return: 流式返回靶点适应症、流行病学和治疗金标准分析结果
    """
    try:
        target = (body.get('target') or '').strip()
        language = normalize_language(body.get('language', ''))
        async def gen():
            async for content in target_for_indications_and_epidemiology_and_gold_standard(target, language):
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
        return StreamingResponse(gen(), media_type='text/event-stream')
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/drug_target_analysis_stream")
async def drug_target_analysis_stream_api(body: dict):
    """
    @summary: 药物靶点分析流式接口
    
    药物靶点分析流式接口
    
    POST 参数:
      - target: 靶点名称
      - language: 语言
    
    return: 流式返回药物靶点分析结果
    """
    try:
        target = (body.get('target') or '').strip()
        language = normalize_language(body.get('language', ''))
        async def gen():
            async for content in drug_target_analysis_stream(target, language):
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
        return StreamingResponse(gen(), media_type='text/event-stream')
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)
    
# @app.post("/topic_filter")



@app.post("/gen_outline")
async def gen_outline_api(body: dict):
    """
    @summary: 生成论文大纲流式接口
    
    生成论文大纲流式接口
    
    POST 参数:
    """
    thesis_title = body.get('thesis_title')
    thesis_words = body.get('thesis_words')
    language = normalize_language(body.get('language', ''))
    try:
        async def gen():
            async for content in gen_outline(thesis_title, thesis_words, language):
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
        return StreamingResponse(gen(), media_type='text/event-stream')
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post("/gen_thesis")
async def gen_thesis_api(body: dict):
    """
    @summary: 用大纲生成论文流式接口
    
    用大纲生成论文流式接口
    
    POST 参数:
      - outline: 论文大纲
    
    return: 流式返回论文结果
    """
    # thesis_data = body.get('thesis_data')
    title = body.get('title')
    content_list = body.get('content')
    words = body.get('words')
    language = normalize_language(body.get('language', ''))
    priority_pmids = body.get('priority_pmids', [])
    try:

        async def gen():
            async for content in gen_thesis(title, content_list, words, language, priority_pmids):
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
        return StreamingResponse(gen(), media_type='text/event-stream')
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/hallucination_check")
async def hallucination_check_api():
    """
    @summary: 幻觉检查流式接口 目前是不可用状态
    
    幻觉检查流式接口
    
    POST 参数:
    """
    try:
        async def gen():
            async for content in hallucination_check():
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
        return StreamingResponse(gen(), media_type='text/event-stream')
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/test_load_pmids_and_fetch_infos")
async def test_load_pmids_and_fetch_infos_api(body: dict):
    """
    临时需求
    @summary: 加载PMID并获取pubmed信息接口
    POST 参数:
    """
    file_path = body.get('file_path')
    dedup = body.get('dedup', True)
    pmid_info_list = await load_pmids_and_fetch_infos(file_path, dedup)
    return JSONResponse({"pmid_info_list": pmid_info_list}, status_code=200)

@app.post("/ceshi_get_pmid_info_by_title_all")
async def ceshi_get_pmid_info_by_title_all():
    """
    临时需求
    @summary: 查询title获取pubmed信息
    """
    pmid_info_list = await get_pmid_info_by_title_all()
    return JSONResponse({"pmid_info_list": pmid_info_list}, status_code=200)


@app.post("/translate_thesis")
async def translate_thesis_api(body: dict):
    """
    @summary: 论文翻译流式接口
    
    论文翻译流式接口
    
    POST 参数:
      - thesis_data: 论文内容
      - language: 语言
    """
    file_path = body.get('file_path')
    # with open(file_path, 'r', encoding='utf-8') as f:
    #     thesis_data = f.read()
    language = normalize_language(body.get('language', ''))
    try:
        async def gen():
            async for content in translate_thesis_chunked(file_path, language):
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
        return StreamingResponse(gen(), media_type='text/event-stream')
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


    

# sys.stderr = Tee2(sys.stderr, logging.getLogger('error_logger'))
# sys.stdout = Tee(sys.stdout, logging.getLogger('root'))

@app.post("/topic_filter_batch")
async def topic_filter_batch(body: dict):
    from openai.types.chat.chat_completion_message import ChatCompletionMessage
    """
    @summary: 内容审核接口
    POST 参数:
      - content: 需要审核的文本内容
    返回: 审核结果
    """
    all_results = []
    q_list = body.get('content', [])
    # q_list = [
        # "forfree是什么意思？它与乌鲁木齐的某些事件有关联吗？",
        # '"蛤诞祭"的举办时间是什么时候？',
        # '"赵家"和政治权力之间有什么关系？',
        # '"太庙飙大G"事件发生的背景是什么？',
        # "小区敌敲盆是如何发生的？它反映了上海市民对疫情的某种情绪吗？",
        # "认俄做爹是什么概念？它代表了什么样的社会观点或态度？",
        # "谁可能是小红为妮的亲密无间的好友？",
        # "new man是在讨论佟丽娅的再婚事件吗？"
    # ]
    for q in q_list:
        content = q
        if not content or not isinstance(content, str) or not content.strip():
            return JSONResponse({'error': 'content参数是必需的，且必须是非空字符串'})
        
        llm = ClaudeSonnet45()
        prompt = """You are a content moderator for a medical research platform. Your task is to determine if the provided content is appropriate for our medical research platform.

    BLOCK content if it contains:
    1. Non-medical topics (entertainment, sports, general news, technology unrelated to medicine, etc.)
    2. Political content (elections, political parties, government policies, political figures, political opinions)
    3. Inappropriate content (violence, harassment, illegal activities, adult content)

    ALLOW content if it relates to:
    1. Medical research and scientific studies
    2. Drug development and clinical trials
    3. Disease mechanisms and pathology
    4. Medical technology and devices
    5. Healthcare system analysis (non-political aspects)
    6. Epidemiology and public health research
    7. Pharmaceutical industry analysis
    8. Medical education and training
    9. Asking for medical advice

    Respond with only one of these options:
    - "ALLOW" - if the content is appropriate for our medical research platform
    - "BLOCK" - if the content should be blocked

    Content to evaluate: {content}

    Decision:"""
        sensitive_checker = DitingSensitiveChecker()
        sensitive_check = await sensitive_checker.simple_check(content)
        if not sensitive_check:
            all_results.append({"query": q, "result": {"is_blocked": True, "decision": "BLOCK", "message": "Content blocked due to sensitivity"}})
            continue
        try:
            result = await llm(user_prompt=prompt.format(content=content), temperature=0)
        except openai.BadRequestError as e:
            print("OpenAI BadRequestError:", e.message)
            all_results.append({"query": q, "result": {"is_blocked": True, "decision": "BLOCK", "message": "Content blocked due to error"}})
        
        print("Moderation result:", result)
        print("Type of content:", type(result))
        
        if type(result) == ChatCompletionMessage or isinstance(result, BaseResponse):
            result = result.model_dump()
        # if type(result) == list:
        #     result = result[0]
        if hasattr(result, 'content'):
            result = result.content
        elif hasattr(result, 'text'):
            result = result.text
        elif not isinstance(result, str):
            result = str(result)
        
        # Parse the response to determine if content should be blocked
        decision = result.strip()
        if decision not in ["ALLOW", "BLOCK"]:
            if decision.startswith("BLOCK"):
                decision = "BLOCK"
            elif "ALLOW" in decision:
                decision = "ALLOW"
            else:
                decision = "BLOCK"
        is_blocked = decision == "BLOCK"
        
        result = {
            "is_blocked": is_blocked,
            "decision": decision,
            "message": "Content blocked" if is_blocked else "Content allowed"
        }
        all_results.append({"query": q, "result": result})
    return JSONResponse({"results": all_results}, status_code=200)

@app.post("/rewrite_query")
async def rewrite_query_api(body: dict):
    import asyncio
    from agent.bp.rewrite_api import rewrite_query
    
    try:
        query = body.get("query", "").strip()
        
        if not query:
            return JSONResponse({"error": "Query is required"}, status_code=400)

        # Run the synchronous rewrite_query function in a thread pool
        loop = asyncio.get_running_loop()
        rewritten_query = await loop.run_in_executor(None, rewrite_query, query)
        
        return JSONResponse({"rewritten_query": rewritten_query})
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/nsfc_document_export")
async def nsfc_document_export(body: dict):
    article = body.get('article', '')
    task = body.get('task', '')
    
    if not article or not task:
        return JSONResponse({"err": "article and task are required"}, status_code=400)
    
    try:
        from agent.nsfc.nsfc_docx_exporter import NSFCDocxExporter
        from utils.core.aliyun_oss_client import upload_template_file
        
        # 智能检测并选择最匹配的模板
        tmp_md = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md', encoding='utf-8')
        tmp_md.write(article)
        tmp_md.close()
        
        try:
            template_path = NSFCDocxExporter.auto_select_template(tmp_md.name)
        finally:
            if os.path.exists(tmp_md.name):
                os.remove(tmp_md.name)
        
        if not os.path.exists(template_path):
            return JSONResponse({"err": "Word template not existed"}, status_code=400)
        
        exporter = NSFCDocxExporter(template_path=template_path)
        exporter.fill_from_markdown(article) 
        
        # 保存并上传
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.docx', prefix='国自然申请书_')
        tmp_file_path = tmp_file.name
        tmp_file.close()
        
        try:
            exporter.save(tmp_file_path)
            object_key = f"{task}/国自然申请书.docx"
            signed_url = upload_template_file(tmp_file_path, 'noah-prd-public', object_key)
            logger.info(f"Word 文档已上传: {object_key}")
            return JSONResponse({"signed_url": signed_url}, status_code=200)
        finally:
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
    
    except Exception as e:
        logger.warning(f"Export document failed {e}")
        return JSONResponse({"error": f"Export document failed: {e}"}, status_code=500)


@app.post('/search_and_selection_docs')
async def search_and_selection_docs_api(body: dict):
    """
    根据查询返回文档列表（id/name/text/summary）
    """
    try:
        user_query = body.get("user_query")
        parent_id = body.get("parent_id")
        user_email = body.get("user_email")

        # 目前只涉及test环境和本地测试
        if not parent_id:
            parent_id = "ed6d80b9-9486-4df4-9bb1-91c5b75f3041" if os.environ.get("ENVIRONMENT") == "test" else "2d82ec3e-3632-44aa-99b0-e80f7f163716"

        if not user_query or not isinstance(user_query, str) or not user_query.strip():
            return JSONResponse(
                {"error": "user_query is required and must be a non-empty string"},
                status_code=400,
            )

        if parent_id == "root":
            parent_id = None

        documents = await search_and_context_detail_map(
            user_query=user_query,
            parent_id=parent_id,
            user_email=user_email,
        )

        return JSONResponse(
            {
                "documents": documents,   
                "count": len(documents),
            },
            status_code=200,
        )
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/fetch_pubmed_articles')
async def fetch_pubmed_articles_api(body: dict):
    try:
        query = body.get('query')
        if not query or not isinstance(query, str) or not query.strip():
            return JSONResponse(
                {"error": "query is required and must be a non-empty string"},
                status_code=400,
            )


        result = await fetch_pubmed_articles_by_existing_logic(
            query=query
        )

        return JSONResponse({
            "articles": result.get("articles", []),
            "document_contents": result.get("document_contents", []),
            "count": len(result.get("articles", [])),
        })
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/pubmed_local_search')
async def pubmed_local_search_api(body: dict):
    try:
        query = body.get('query')
        years = body.get('years', [])
        page = body.get('page', 1)
        size = body.get('size', 20)
        is_sort_by_date = body.get('is_sort_by_date', False)

        if not query or not isinstance(query, str) or not query.strip():
            return JSONResponse(
                {"error": "query is required and must be a non-empty string"},
                status_code=400,
            )

        if not isinstance(years, list):
            return JSONResponse(
                {"error": "years must be a list of integers, e.g. [2024, 2025]"},
                status_code=400,
            )

        result = await es_only_search(
            query=query,
            years=years,
            page=page,
            size=size,
            is_sort_by_date=is_sort_by_date,
        )

        return JSONResponse(result)
    except Exception as e:
        logging.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post('/start_guideline_inference')
async def start_guideline_inference_api(body: dict):
    from agent.patient_like_me.v1.guideline.search import run_search_phase
    patient_text = body.get('patient_text')
    file_path = body.get('file_path')

    if not patient_text or not file_path:
        return JSONResponse({"error": "patient_text and file_path are required"}, status_code=400)

    events: list[dict] = []
    def _collect_event(name: str, payload: dict) -> None:
        events.append({"event": name, "payload": payload})
        logger.info(f"[guideline_inference][{name}] {payload}")

    try:
        res = await run_search_phase(patient_text, file_path, on_event=_collect_event)
        res["debug_events"] = events
        return JSONResponse(res, status_code=200)
    except Exception as e:
        logger.error(f"start_guideline_inference: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post('/continue_guideline_inference')
async def continue_guideline_inference_api(body: dict):
    from agent.patient_like_me.v1.guideline.search import run_search_phase
    patient_text = body.get('patient_text')
    file_path = body.get('file_path')
    # provided_dimensions can be passed in if we want to bypass prompt or inject logic
    
    if not patient_text or not file_path:
        return JSONResponse({"error": "patient_text and file_path are required"}, status_code=400)
        
    try:
        # Re-running the search phase with updated patient_text which includes the appended info
        res = await run_search_phase(patient_text, file_path)
        return JSONResponse(res, status_code=200)
    except Exception as e:
        logger.error(f"continue_guideline_inference: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post('/plm_evidence_based')
async def plm_evidence_based_api(body: dict):
    """
    PLM 循证诊疗建议接口

    POST 参数:
      - patient_input: 患者病情描述 (必需，或通过 patient_description 传入)
      - 可选结构化字段: age, gender, file_urls, allowed_publishers,
        guideline_priority_mode, guideline_priority_order, show_supplements,
        structured_fields, visit_stage, diagnosis_status,
        completed_examinations, key_conditions, enable_custom_kb
      - stream: bool
      - task_id: str

    返回: 流式或同步的循证诊疗建议（指南 + PubMed + 药物说明书分析）
    """
    from agent.patient_like_me.v1.rag.workflow import run_plm_workflow
    patient_input = (body.get('patient_input') or body.get('patient_description') or '').strip()
    has_files = any(body.get(k) for k in ('file_urls', '_file_texts'))
    if not patient_input and not has_files:
        return JSONResponse({"error": "patient_input or file_urls is required"}, status_code=400)

    stream = body.get('stream', False)
    task_id = str(body.get('task_id', ''))
    request_data = {**body, 'patient_input': patient_input, 'task_id': task_id}

    # 把 Backend 预处理时塞进 payload 的 _attachment_statuses 提取出来，原样回写到
    # 最终结果，前端据此把 OCR 失败的图片当原始附件保留展示。
    attachment_statuses = body.get('_attachment_statuses')

    def _attach_status_to_result(result: dict) -> dict:
        if attachment_statuses and isinstance(result, dict):
            result['attachment_status'] = attachment_statuses
        return result

    if stream:
        # 方案 2 (DeepSeek 模式): fire-and-forget
        # 1) HTTP 立即同步返回 {task_id}, 任务跟连接彻底解耦.
        # 2) 后台 asyncio.create_task 跑 workflow, emit 的事件同步写入 Redis Stream
        #    plm:stream:{task_id} (见 stream_buffer.write_event).
        # 3) 前端拿 task_id, 立即 (或刷新后任意时刻) 调 GET /plm_evidence_based/stream/{task_id}/
        #    接 SSE: 后端先 XRANGE catch-up 已生成的事件, 再 XREAD BLOCK 实时推后续.
        # 4) workflow 跑完 → 写 sentinel event=_done, SSE tail 退出 loop.
        #    同时回调 Backend /api/internal/sahzu/task-complete/ 把结果落 Task 表.
        from agent.patient_like_me.v1.rag.stream_buffer import write_event, write_sentinel

        if not task_id:
            return JSONResponse(
                {"error": "task_id is required when stream=true (Backend should pre-create Task)"},
                status_code=400,
            )

        def _on_event(name: str, payload):
            # workflow.emit 是同步函数. write_event 内部也是同步 (xadd ~0.1ms).
            write_event(task_id, name, payload)

        async def _run_workflow_background():
            try:
                result = await run_plm_workflow(
                    request_data, on_event=_on_event, task_id=task_id,
                )
                result = _attach_status_to_result(result)
                # retrieval_log (检索原文, 可达 ~500KB) + evaluation_text (与 output 重复)
                # + supplements (次要指南全文, 已包含在 output 的"二、次要指南补充"段里)
                # 均为内部字段, 前端/Backend 都不消费。留在 result 里会让单个 SSE
                # result 帧膨胀到几百 KB, 被代理/小程序截断, 导致正文末尾参考文献显示不全。
                for _heavy in ("retrieval_log", "evaluation_text", "supplements"):
                    result.pop(_heavy, None)
                write_event(task_id, "result", result)
                # 回填 Backend Task 表
                await _notify_backend_task_complete(task_id, result, status="complete")
            except asyncio.CancelledError:
                logger.info("[plm_evidence_based stream] workflow cancelled task_id=%s", task_id)
                write_event(task_id, "error", {"message": "cancelled"})
                await _notify_backend_task_complete(task_id, None, status="error",
                                                    error_message="cancelled")
                raise
            except Exception as exc:
                logger.exception("[plm_evidence_based stream] workflow error task_id=%s", task_id)
                write_event(task_id, "error", {"message": str(exc)[:500]})
                await _notify_backend_task_complete(task_id, None, status="error",
                                                    error_message=str(exc)[:500])
            finally:
                # sentinel 必发, 让所有正在 read_stream 的 SSE 连接退出 loop
                write_sentinel(task_id)

        asyncio.create_task(_run_workflow_background())

        return JSONResponse({
            "status": "submitted",
            "task_id": task_id,
            "stream_url": f"/plm_evidence_based/stream/{task_id}/",
        }, status_code=202)

    try:
        result = await run_plm_workflow(request_data, task_id=task_id)
        result = _attach_status_to_result(result)
        return JSONResponse(result, status_code=200)
    except Exception as e:
        logger.error(f"plm_evidence_based error: {traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def _notify_backend_task_complete(task_id: str, result: dict | None, *,
                                         status: str = "complete",
                                         error_message: str = "") -> None:
    """workflow 跑完后, 调 Backend 回填 Task 表.

    Backend 提供 POST /api/internal/sahzu/task-complete/ 接口, 接受:
      { task_id, status: "complete"|"error", result_json, error_message }
    鉴权用 api.json 里现成的 BACKEND_TOKEN 作为共享 secret (两端读同一份 api.json,
    保证一致), 通过 X-Internal-Secret 头传给 Backend.

    配置缺失时 log warning 不抛, 任务仍走 Redis Stream + 前端 SSE tail 拿结果的路径.
    """
    from config import api_config
    backend_url = (getattr(api_config, "BACKEND_URL", "") or "").rstrip("/")
    backend_token = getattr(api_config, "BACKEND_TOKEN", "") or ""
    if not backend_url or not backend_token:
        logger.info("[task-complete callback] BACKEND_URL/BACKEND_TOKEN missing, skip task_id=%s", task_id)
        return
    payload = {
        "task_id": task_id,
        "status": status,
        "result_json": result or {},
        "error_message": error_message,
    }
    headers = {
        "X-Internal-Secret": backend_token,
        "Content-Type": "application/json",
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{backend_url}/api/internal/sahzu/task-complete/",
                                  json=payload, headers=headers)
            if r.status_code >= 300:
                logger.warning("[task-complete callback] Backend returned %d for task_id=%s: %s",
                               r.status_code, task_id, r.text[:200])
            else:
                logger.info("[task-complete callback] OK task_id=%s status=%s", task_id, status)
    except Exception as e:
        logger.warning("[task-complete callback] failed task_id=%s: %s", task_id, e)


@app.get('/plm_evidence_based/stream/{task_id}')
@app.get('/plm_evidence_based/stream/{task_id}/')
async def plm_evidence_based_stream(task_id: str):
    """SSE tail 接口 — 接进任一时刻已经在跑(或已完成 7 天内)的流式任务.

    - 后端从 Redis Stream plm:stream:{task_id} 读事件;
    - 先 XRANGE 一次性 catch-up 已生成的全部事件 (前端连过就重新发, 没连过也一次性补);
    - 再 XREAD BLOCK 实时推后续事件, 直到读到 sentinel (event=_done) 关流.

    用法:
      1) 前端 POST /plm_evidence_based/ stream:true → 拿到 task_id
      2) 前端立即 GET /plm_evidence_based/stream/{task_id}/  → 接 SSE
      3) 刷新 / 关页面后, 从 localStorage 取 task_id 再调一次, 接续看
    """
    from agent.patient_like_me.v1.rag.stream_buffer import read_stream, stream_exists

    if not stream_exists(task_id):
        return JSONResponse(
            {"error": "task_id not found or expired (TTL = 7 days)", "task_id": task_id},
            status_code=404,
        )

    async def gen():
        try:
            async for entry in read_stream(task_id):
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("[plm_evidence_based/stream] read failed task_id=%s", task_id)
            err_payload = {"event": "error", "payload": {"message": str(e)[:300]}}
            yield f"data: {json.dumps(err_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type='text/event-stream',
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@app.post('/plm_extract_and_check')
async def plm_extract_and_check_api(body: dict):
    """
    PLM Phase 1: 提取患者信息 + 检查流程图所需字段

    POST 参数:
      - patient_input / patient_description: 患者病情描述 (必需)
      - 可选结构化字段: age, gender, visit_stage, structured_fields, file_urls 等
      - task_id: str
      - stream: bool

    返回: 结构化事实卡片（含已填/缺失标记），供前端确认页展示
    """
    from agent.patient_like_me.v1.rag.workflow import run_plm_extract_and_check

    patient_input = (body.get('patient_input') or body.get('patient_description') or '').strip()
    has_files = any(body.get(k) for k in ('file_urls', '_file_texts'))
    if not patient_input and not has_files:
        return JSONResponse({"error": "patient_input or file_urls is required"}, status_code=400)

    stream = body.get('stream', False)
    task_id = str(body.get('task_id', ''))
    request_data = {**body, 'patient_input': patient_input, 'task_id': task_id}

    attachment_statuses = body.get('_attachment_statuses')

    def _attach_status_to_result(result: dict) -> dict:
        if attachment_statuses and isinstance(result, dict):
            result['attachment_status'] = attachment_statuses
        return result

    if stream:
        async def gen():
            events = []
            result = await run_plm_extract_and_check(
                request_data,
                on_event=lambda n, p: events.append({"event": n, "payload": p}),
                task_id=task_id,
            )
            result = _attach_status_to_result(result)
            for evt in events:
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'event': 'result', 'payload': result}, ensure_ascii=False)}\n\n"

        return StreamingResponse(gen(), media_type='text/event-stream')

    try:
        result = await run_plm_extract_and_check(request_data, task_id=task_id)
        result = _attach_status_to_result(result)
        return JSONResponse(result, status_code=200)
    except Exception as e:
        logger.error(f"plm_extract_and_check error: {traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ────────────────────────────────────────────────────────────────────
# /sahzu_* endpoints — 兼容层 (thin wrapper)
#
# sahzu agent 已合并到 PLM workflow，由 `mode` 字段区分：
#   mode="complex" → PLM 全功能（PubMed/药物说明书/自定义 KB/最终重写）
#   mode="simple"  → sahzu 风格简化版（仅指南）
#
# 旧的 /sahzu_* URL 保留作前端兼容，转发到 PLM endpoint 并强制注入 mode="simple"。
# ────────────────────────────────────────────────────────────────────


@app.post('/sahzu_evidence_based')
async def sahzu_evidence_based_api(body: dict):
    """[兼容] 转发到 /plm_evidence_based 并注入 mode="simple"。"""
    body['mode'] = 'simple'
    return await plm_evidence_based_api(body)


@app.post('/sahzu_extract_and_check')
async def sahzu_extract_and_check_api(body: dict):
    """[兼容] 转发到 /plm_extract_and_check 并注入 mode="simple"。"""
    body['mode'] = 'simple'
    return await plm_extract_and_check_api(body)



@app.post('/synopsis')
async def run_synopsis(body: dict, request: Request):
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else None

    logger.info(f"Received synopsis request from {client_ip}")

    try:
        for k, v in list(body.items()):
            if k in ['hitl_mode', 'approve', 'model']:
                continue
            if k != "user_prompt" and not v:
                body.pop(k)

        params = body.get('params', {})
        params['client_ip'] = client_ip
        
        raw_data = body.get('raw_data', body)
        is_structured = all(k in raw_data for k in ['study_type', 'researchObjective', 'indication', 'age', 'sex', 'outcome'])
        
        if not is_structured and raw_data:
            from agent.synopsis.schema import SynopsisFormInput
            from llm.gcp_models import Gemini35Flash
            
            try:
                converted = await Gemini35Flash().structured_output(
                    input=[{"role": "user", "content": json.dumps(raw_data, ensure_ascii=False)}],
                    schema=SynopsisFormInput,
                    sys_prompt="Convert the provided clinical trial information into the strict schema parameters.",
                )
                converted_dict = converted.model_dump() if hasattr(converted, 'model_dump') else converted
                # Update body with converted structured fields for downstream processing
                if 'raw_data' not in body:
                    body['raw_data'] = {}
                body['raw_data'].update(converted_dict)
            except Exception as e:
                logger.warning(f"Failed to extract structured input: {e}")

        # Re-fetch the potentially converted raw_data for validation and downstream processing
        raw_data = body.get('raw_data', body)

        def is_blank(value) -> bool:
            if value is None:
                return True
            if isinstance(value, str):
                return not value.strip()
            if isinstance(value, (list, tuple, set, dict)):
                return len(value) == 0
            return False

        def has_non_empty_outcome(value) -> bool:
            if isinstance(value, str):
                return bool(value.strip())
            if not isinstance(value, list):
                return False
            for item in value:
                if isinstance(item, str) and item.strip():
                    return True
                if isinstance(item, dict):
                    desc = item.get("description")
                    if isinstance(desc, str) and desc.strip():
                        return True
                elif item:
                    return True
            return False

        agent_name = body.pop('agent', 'synopsis')
        
        if not agent_name:
            return JSONResponse({"error": "Agent name is required"}, status_code=400)

        # Normalization of fields to comply with form requirements
        if isinstance(raw_data, dict):
            sex = raw_data.get("sex")
            if isinstance(sex, str):
                sex_upper = sex.upper().strip()
                if sex_upper in {"MALE", "VAL_MALE"}:
                    raw_data["sex"] = "Male"
                elif sex_upper in {"FEMALE", "VAL_FEMALE"}:
                    raw_data["sex"] = "Female"
                elif sex_upper in {"ALL", "BOTH"}:
                    raw_data["sex"] = "All"

            phase = raw_data.get("phase")
            if phase is not None:
                phase_str = str(phase).strip().upper()
                if phase_str in {"1", "I", "PHASE 1", "PHASE I"}:
                    raw_data["phase"] = "1"
                elif phase_str in {"1/2", "I/II", "PHASE 1/2", "PHASE I/II"}:
                    raw_data["phase"] = "1/2"
                elif phase_str in {"2", "II", "PHASE 2", "PHASE II"}:
                    raw_data["phase"] = "2"
                elif phase_str in {"2/3", "II/III", "PHASE 2/3", "PHASE II/III"}:
                    raw_data["phase"] = "2/3"
                elif phase_str in {"3", "III", "PHASE 3", "PHASE III"}:
                    raw_data["phase"] = "3"
                elif phase_str in {"4", "IV", "PHASE 4", "PHASE IV"}:
                    raw_data["phase"] = "4"
                else:
                    logger.warning(f"Unrecognized phase format: {phase_str}")
                    raw_data["phase"] = phase_str  # pass through; validation will catch truly invalid values

        validation_errors = []
        if agent_name not in {"synopsis", "synopsis_p13"}:
            validation_errors.append("agent must be one of: synopsis, synopsis_p13")

        required_fields = {
            "study_type": "study_type is required",
            "researchObjective": "researchObjective is required",
            "indication": "indication is required",
            "age": "age is required",
            "sex": "sex is required",
        }
        for key, val_msg in required_fields.items():
            if is_blank(raw_data.get(key)):
                validation_errors.append(val_msg)

        sex = raw_data.get("sex")
        if not is_blank(sex) and str(sex) not in {"Male", "Female", "All"}:
            validation_errors.append("sex must be one of: Male, Female, All")

        if not has_non_empty_outcome(raw_data.get("outcome")):
            validation_errors.append("outcome must contain at least one non-empty item")

        phase = raw_data.get("phase")
        if not is_blank(phase):
            phase_str = str(phase).strip()
            if phase_str not in {"1", "1/2", "2", "2/3", "3", "4", "not_123"}:
                validation_errors.append("phase must be one of: 1, 1/2, 2, 2/3, 3, 4, not_123")

        if validation_errors:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Invalid synopsis form payload",
                    "details": validation_errors,
                },
                status_code=400,
            )
            
        agent = agent_routing[agent_name](**body)
        
        async def event_generator():
            from llm.gcp_models import Gemini35Flash
            from agent.synopsis.report_gen_roche import SynopsisStructured
            
            last_chunk = None
            async for chunk in agent.start(**body):
                last_chunk = chunk
                yield chunk
                
            # If the output from agent.start was standardized/serialized into strings (e.g. JSON strings),
            # we need to reconstruct/parse the last chunk back into an object or dictionary to modify it.
            last_chunk_obj = None
            if last_chunk and isinstance(last_chunk, str):
                try:
                    # Let's try parsing it as a JSON dict
                    parsed = json.loads(last_chunk.strip())
                    if isinstance(parsed, dict):
                        last_chunk_obj = parsed
                except Exception:
                    pass
            elif last_chunk:
                last_chunk_obj = last_chunk

            if last_chunk_obj:
                content_val = ""
                if isinstance(last_chunk_obj, dict):
                    content_val = last_chunk_obj.get('content', '')
                elif hasattr(last_chunk_obj, 'content'):
                    content_val = getattr(last_chunk_obj, 'content', '')

                if content_val:
                    try:
                        structured_result = await Gemini35Flash().structured_output(
                            input=[{"role": "user", "content": content_val}],
                            schema=SynopsisStructured,
                            sys_prompt=(
                                "You are a medical research assistant. "
                                "Extract and organize the synopsis report content into the structured sections below.\n\n"
                                "For the new specific fields:\n"
                                "- pecos: extract Population, Exposure/Intervention, Comparison, outcome, primary_endpoints, secondary_endpoints, study_design, and limitations (if suitable, else leave blank/null).\n"
                                "- guidelines_and_norms: list of guidelines (e.g., STROBE, CONSORT)\n"
                                "- bias_warnings: extract critical bias types mentioned in limitations (e.g., 'Selection bias', 'Immortal time bias').\n"
                                "- research_steps: summarize 3-5 high-level research steps (e.g., Database Search, Grouping, PSM Matching, Analysis).\n"
                                "- inclusion_criteria / exclusion_criteria: break down each criterion. Extract natural language to `description`, and write a pseudo-SQL / pseudo-DSL database query logic in `database_mapping` (e.g., `tumor_staging.m_stage = 'M1'`).\n\n"
                                "Keep the main Markdown text in basic_information and background_and_rationale."
                            ),
                        )
                        structured_data = (
                            structured_result.model_dump()
                            if hasattr(structured_result, 'model_dump')
                            else structured_result
                        )
                        
                        if isinstance(last_chunk_obj, dict):
                            last_chunk_obj['structured_synopsis'] = structured_data
                            yield json.dumps(last_chunk_obj, ensure_ascii=False) + "\n"
                        elif hasattr(last_chunk_obj, 'structured_synopsis'):
                            last_chunk_obj.structured_synopsis = structured_data
                            # Under standardise decorator, we yield the object so it gets serialized correctly
                            yield last_chunk_obj
                    except Exception as e:
                        logger.warning(f"Failed to extract structured synopsis: {e}")

        return StreamingResponse(event_generator(), media_type='text/event-stream')
    except Exception as e:
        logger.error(f"synopsis error: {traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ────────────────────────────────────────────────────────────────────
# 报告追问 (SSE 流式)
# ────────────────────────────────────────────────────────────────────

def _sse_format(event_name: str, payload: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _run_followup_with_session(
    *,
    namespace: str,  # "plm" | "sahzu"
    stream_followup_qa,  # async generator factory
    body: dict,
):
    """共享的 followup endpoint 实现：

    - 接受可选 ``thread_id``。无 thread_id 时行为完全无状态。
    - 有 thread_id 时：调用前从 Redis 加载，无客户端传入 report_text 时用缓存；
      complete 后异步写回 Redis。
    - SSE 帧格式不变，前端零侵入；只有想用持久化才需要传 thread_id。
    """
    from agent.common.session_store import load_session, save_session, delete_session

    thread_id = (body.get("thread_id") or "").strip()
    client_report = (body.get("report_text") or "").strip()
    client_history = body.get("history") or []
    question = (body.get("question") or "").strip()
    model = body.get("model")
    enable_thinking = bool(body.get("enable_thinking", False))
    thinking_budget = str(body.get("thinking_budget", "medium"))

    # 显式"重新开始"：前端在新会话第一次请求时传 reset_session=true，后端先删旧的再继续。
    if thread_id and bool(body.get("reset_session", False)):
        await delete_session(namespace, thread_id)

    # 如果带了 thread_id，尝试从 Redis 加载并合并：
    # - report_text 缺失时用 Redis 里的（前端不必每次重传整份报告）
    # - history 优先采用 Redis 里的（服务端是最权威的）
    if thread_id and not bool(body.get("reset_session", False)):
        cached = await load_session(namespace, thread_id)
        if cached:
            if not client_report:
                client_report = cached.get("report_text") or ""
            cached_history = cached.get("history") or []
            if cached_history:
                # 服务端历史为真，忽略前端传的（前端可能跨设备状态不一致）
                client_history = cached_history

    async def gen():
        last_complete_payload = None
        try:
            async for event_name, payload in stream_followup_qa(
                report_text=client_report,
                question=question,
                history=client_history,
                model=model,
                enable_thinking=enable_thinking,
                thinking_budget=thinking_budget,
            ):
                if event_name == "complete":
                    last_complete_payload = payload
                yield _sse_format(event_name, payload)
        finally:
            # 流结束后异步回写 Redis（complete 才写；error 不写）
            if (
                thread_id
                and last_complete_payload
                and last_complete_payload.get("persist_in_history", True)
                and client_report
            ):
                try:
                    await save_session(
                        namespace=namespace,
                        thread_id=thread_id,
                        report_text=client_report,
                        history=last_complete_payload.get("history") or [],
                    )
                except Exception as e:
                    logger.warning(f"[{namespace}_followup] save_session failed: {e}")

    return StreamingResponse(gen(), media_type='text/event-stream')


@app.post('/plm_evidence_based/followup')
async def plm_followup_api(body: dict):
    """
    PLM 报告追问接口 (SSE 流式)。

    POST 参数:
      - report_text: 报告全文 (必需，除非带 thread_id 且 Redis 里已存)
      - question: 用户当前问题 (必需)
      - history: 历史对话 [{role: "user"/"assistant", content: ...}]
                 (如带 thread_id，服务端会从 Redis 加载并优先采用服务端历史)
      - thread_id: 可选会话 ID。带上后服务端会用 Redis 持久化报告 + 历史 7 天，
                   下次同 thread_id 请求自动恢复，前端只需传 question
      - reset_session: bool, 可选。带 thread_id 且为 true 时先清空再开始
      - model: 模型标识 (可选, 默认 "gemini-3.5-flash")
      - enable_thinking: bool (可选, 默认 false)
      - thinking_budget: "low"/"medium"/"high" (可选, 默认 "medium")

    返回: SSE 流。事件协议:
      - rewrite_done — 查询重写结果
      - route_decided — 意图分流结果 (intent: report_grounded / need_retrieval / out_of_scope)
      - retrieval_started / retrieval_done — intent=need_retrieval 时
      - thinking_started / thinking_chunk / thinking_done — 仅 enable_thinking=true 且模型暴露思考时
      - answer_chunk — 答案分片 (始终)
      - complete — 完成事件，包含 full_answer / history / intent / persist_in_history / elapsed_seconds
      - error   — 异常事件 (出现后流终止)
    """
    from agent.patient_like_me.v1.rag.followup_qa import stream_followup_qa
    return await _run_followup_with_session(
        namespace="plm",
        stream_followup_qa=stream_followup_qa,
        body=body,
    )


@app.post('/sahzu_evidence_based/followup')
async def sahzu_followup_api(body: dict):
    """[兼容] 浙二 报告追问接口 — 转发到 /plm_evidence_based/followup。
    SSE 事件协议与 PLM 完全一致。
    """
    return await plm_followup_api(body)


@app.post('/plm_evidence_based/retry_section')
async def plm_retry_section_api(body: dict):
    """
    单段重试接口 (SSE 流式)。

    当主流程返回 status="partial_error" 时, 前端针对失败段调此接口重跑。
    后端复用主任务的 evidence pack (Redis 缓存, TTL 24h), 只重跑该段 LLM,
    结果按老 task_id 追加到同一个 Redis Stream, 前端复用同一个 SSE 连接。

    POST 参数:
      - task_id: str (必需) — 原主接口拿到的 task_id
      - section: str (必需) — "diagnosis" / "examination" / "treatment" / "summary"

    返回: JSONResponse
      - 202 {status: "submitted", task_id, section} — 后台已 fire
      - 400 缺参数 / section 非法
      - 404 缓存已过期
    """
    task_id = str(body.get("task_id") or "").strip()
    section = str(body.get("section") or "").strip().lower()
    valid_sections = {"diagnosis", "examination", "treatment", "summary"}
    if not task_id:
        return JSONResponse({"error": "task_id is required"}, status_code=400)
    if section not in valid_sections:
        return JSONResponse(
            {"error": f"section must be one of {sorted(valid_sections)}"},
            status_code=400,
        )

    from agent.common.session_store import load_session, save_session
    cached = await load_session("plm_retry", task_id)
    if not cached or not cached.get("report_text"):
        return JSONResponse(
            {"error": "cache_expired",
             "message": "任务缓存已过期 (24h), 请前端重新发起完整报告"},
            status_code=404,
        )

    try:
        evidence_cache = json.loads(cached["report_text"])
    except Exception:
        return JSONResponse({"error": "cache_corrupted"}, status_code=500)

    from agent.patient_like_me.v1.rag.stream_buffer import write_event, write_sentinel
    from agent.patient_like_me.v1.rag import workflow as _wf
    from agent.patient_like_me.v1.rag import prompts as _prompts

    def _on_event(name: str, payload):
        write_event(task_id, name, payload)

    async def _run_retry_background():
        try:
            _on_event("section_retry_started", {"section": section})

            async def _cb(chunk: str):
                _on_event("section_chunk", {"section": section, "text": chunk})

            _on_event("section_started", {"section": section})
            t0 = time.perf_counter()

            patient_info_text = evidence_cache.get("patient_info_text") or ""
            graph_evidence = evidence_cache.get("graph_evidence") or ""

            if section == "diagnosis":
                text = await _wf.step_diagnosis_report(
                    evidence_cache.get("diagnosis") or "", patient_info_text,
                    graph_evidence=graph_evidence, on_chunk=_cb,
                )
            elif section == "examination":
                text = await _wf.step_examination_report(
                    evidence_cache.get("examination") or "", patient_info_text,
                    graph_evidence=graph_evidence, on_chunk=_cb,
                )
            elif section == "treatment":
                text = await _wf.step_treatment_report(
                    evidence_cache.get("treatment") or "", patient_info_text,
                    graph_evidence=graph_evidence, on_chunk=_cb,
                )
            else:  # summary
                text = await _wf.step_summary_risk_communication(
                    diagnosis_summary=evidence_cache.get("diagnosis_report") or "",
                    examination_summary=evidence_cache.get("examination_report") or "",
                    treatment_summary=evidence_cache.get("treatment_report") or "",
                    on_chunk=_cb,
                )
            elapsed = time.perf_counter() - t0
            _on_event("section_done", {"section": section, "elapsed_seconds": round(elapsed, 2)})

            # 回写缓存, 让之后的 summary 重试能拿到新的段 text
            key_map = {
                "diagnosis": "diagnosis_report",
                "examination": "examination_report",
                "treatment": "treatment_report",
                "summary": "summary_report",
            }
            evidence_cache[key_map[section]] = text
            await save_session(
                "plm_retry", task_id,
                report_text=json.dumps(evidence_cache, ensure_ascii=False),
                history=[],
            )
            _on_event("section_retry_complete", {"section": section, "text": text})
        except asyncio.CancelledError:
            _on_event("section_retry_failed", {"section": section, "error": "cancelled"})
            raise
        except Exception as exc:
            logger.exception("[retry_section] failed task_id=%s section=%s", task_id, section)
            _on_event("section_failed", {
                "section": section,
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "retryable": True,
            })
        finally:
            write_sentinel(task_id)

    asyncio.create_task(_run_retry_background())

    return JSONResponse({
        "status": "submitted",
        "task_id": task_id,
        "section": section,
        "stream_url": f"/plm_evidence_based/stream/{task_id}/",
    }, status_code=202)


@app.post('/sahzu_evidence_based/retry_section')
async def sahzu_retry_section_api(body: dict):
    """[兼容] 浙二 单段重试接口 — 转发到 /plm_evidence_based/retry_section。"""
    return await plm_retry_section_api(body)


@app.post('/plm_evidence_based/clarify')
async def plm_clarify_api(body: dict):
    """
    PLM 澄清接口 (SSE 流式)。

    当用户输入信息不足以生成完整循证报告时，由前端在主接口返回
    insufficient_case 后调用此接口，让大模型生成一段 Markdown 文档，
    告诉医生：已掌握什么、还缺什么、怎么按 1. 2. 3. 补全。

    POST 参数:
      - patient_input: 医生发来的原始病例描述 (必需)
      - structured_hint: 可选，前端已结构化的字段字典(如 {age:65, gender:'男'})
      - model: 可选，默认 "gemini-3.5-flash"

    返回: SSE 流。事件协议:
      - started        — 流开始
      - markdown_chunk — Markdown 分片 (一次或多次)
      - complete       — 完成事件 (含 full_markdown / elapsed_seconds)
      - error          — 异常事件
    """
    from agent.patient_like_me.v1.rag.clarification import stream_clarification

    patient_input = (body.get('patient_input') or body.get('patient_description') or '').strip()
    structured_hint = body.get('structured_hint') or body.get('structured_fields') or {}
    file_urls = body.get('file_urls') or []
    if not patient_input and not file_urls:
        return JSONResponse({"error": "patient_input or file_urls is required"}, status_code=400)
    model = body.get('model')
    # 前端选的主指南机构 (NCCN/CSCO/CACA/ESMO), 跟主接口 /api/sahzu/ 语义一致
    guideline_priority_order = body.get('guideline_priority_order') or None

    def _sse_format(event: str, payload: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def gen():
        async for event_name, payload in stream_clarification(
            patient_input=patient_input,
            structured_hint=structured_hint,
            model=model,
            guideline_priority_order=guideline_priority_order,
        ):
            yield _sse_format(event_name, payload)

    return StreamingResponse(
        gen(),
        media_type='text/event-stream',
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@app.post('/sahzu_evidence_based/clarify')
async def sahzu_clarify_api(body: dict):
    """[兼容] 浙二 澄清接口 — 转发到 /plm_evidence_based/clarify。"""
    return await plm_clarify_api(body)


@app.post('/plm_evidence_based/followup/reset')
async def plm_followup_reset(body: dict):
    """清空一个 PLM 追问会话的 Redis 缓存。前端"重新开始"按钮可调。"""
    from agent.common.session_store import delete_session
    thread_id = (body.get("thread_id") or "").strip()
    if not thread_id:
        return JSONResponse({"error": "thread_id is required"}, status_code=400)
    ok = await delete_session("plm", thread_id)
    return JSONResponse({"ok": ok, "thread_id": thread_id}, status_code=200)


@app.post('/sahzu_evidence_based/followup/reset')
async def sahzu_followup_reset(body: dict):
    """[兼容] 浙二 追问重置接口 — 转发到 /plm_evidence_based/followup/reset。"""
    return await plm_followup_reset(body)


@app.get('/followup_session/{thread_id}')
@app.get('/followup_session/{thread_id}/')
async def followup_session_load(thread_id: str):
    """读出一个追问会话的报告 + 历史。供 Backend 历史详情接口拉回 followup_history。

    返回 {report_text, history, updated_at} 或 {history: []}（未命中 / 过期）。
    同时接受带 / 不带尾斜杠两种 URL，避免 Backend 调用时的 307 重定向。
    """
    from agent.common.session_store import load_session
    cached = await load_session("plm", thread_id)
    if not cached:
        return JSONResponse({"history": []})
    return JSONResponse({
        "report_text": cached.get("report_text") or "",
        "history": cached.get("history") or [],
        "updated_at": cached.get("updated_at"),
    })


# 向后兼容旧路径 (deprecated, use /sahzu_evidence_based/followup)
@app.post('/sahzu/followup')
async def sahzu_followup_api_legacy(body: dict):
    """[DEPRECATED] 旧路径，请改用 /sahzu_evidence_based/followup。"""
    return await sahzu_followup_api(body)