import re
import pytz
from datetime import datetime
import json
import shutil
import os
import asyncio
import io
import logging
import time
import traceback
from typing import Any, Callable, List, Type

from agent.core.preset import AgentPreset
from llm.azure_models import GPT4o
from llm.base_model import BaseLLM
from agent.explore.schema import ProcessingType, SearchNode, SearchType, WebSearchLink, WebSearchSubject
from agent.explore.helper import MindSearchHelper
from agent.synopsis.synopsis_analyzer_v2 import SynopsisAnalyzerV2
from utils.core.exception import UnexpectedException
from agent.synopsis.prompts.report_en import partial_prompt_template_post_en, partial_prompt_template_chain_en, partial_prompt_template_en
from agent.synopsis.prompts.report import partial_prompt_template_cn, partial_prompt_template_post_cn, partial_prompt_template_chain_cn
from llm.deepseek_models import DeepseekChat
from llm.gcp_models import ClaudeSonnet45, ClaudeSonnet46, Gemini35Flash
from agent.human_in_loop.utils import convert_md_to_docx
from utils.sql_client import get_connection_user, text

logger = logging.getLogger(__name__)


class SynopsisAgentV2(AgentPreset):
    analyzer_class: Type[SynopsisAnalyzerV2] = SynopsisAnalyzerV2
    llm: BaseLLM = GPT4o
    sys_prompt: str = ""
    mindsearch_helper: MindSearchHelper = MindSearchHelper()
    language: str = "zh-CN"
    test: bool = False
    synopsis_analyzer: SynopsisAnalyzerV2 = None
    query_params: dict = {}
    
    def __init__(self, query_params={}, **kwargs):
        super().__init__()
        logger.info(f"kwargs: {kwargs}")
        logger.info(f"query_params: {query_params}")
        
        if 'params' in kwargs and 'language' in kwargs['params']:
            from i18n.languages import normalize as _norm
            self.language = _norm(kwargs['params']['language'])
        if 'raw_data' in kwargs and kwargs['raw_data']:
            raw_data_items = list(kwargs['raw_data'].items())
            for key, val in raw_data_items:
                if val != False and not val:
                    kwargs['raw_data'].pop(key, None) 
            query_params = kwargs['raw_data']
        if 'language' in query_params:
            self.language = _norm(query_params.pop('language', ''))
        if 'language' in kwargs:
            self.language = _norm(kwargs.pop('language', ''))
            
        self.query_params = query_params
            
        logger.info(f"SynopsisAgentV2 language: {self.language}")
  
        output_dir = f"outputs/synopsis_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        self.synopsis_analyzer = self.analyzer_class(model=DeepseekChat(), query_params=query_params, language=self.language)
        self.synopsis_analyzer.set_output_dir(output_dir)

    async def run_func(self, func: Callable, buffer: io.StringIO):
        async_generator = func()
        try:
            async for item in async_generator:
                buffer.write(item)
        except Exception as e:
            logger.error(f"run_func failed: {str(e)}")
            raise e
                
        
    def init_search_graph(self):
        root = SearchNode(search_type=SearchType.UNKNOWN,
                    query="Synopsis generation",
                    key_word="")
        subject = WebSearchSubject.UNKNOWN.value
        root.subject = WebSearchSubject(subject)
        root.thought_process = "报告生成将经过三个步骤" if self.language == 'zh-CN' else "Synopsis generation follows a 3-step process"
        
        steps = ["Obtain clinical data (~5s)",
                "Synopsis generation (2-4 mins)",
                "Proofread synopsis (2-4 mins)"]
        steps_chinese = ["获取临床数据 (~5s)",
                        "临床方案生成 (2-4分钟)",
                        "临床方案校对 (2-4分钟)"]
        
        for subtitle in (steps_chinese if self.language == "zh-CN" else steps):
            
            node = SearchNode(search_type=SearchType.UNKNOWN,
                    query=subtitle,
                    key_word="")
            root.add_child(node)
        
        return root
    
    async def _task_with_heartbeat(self, func: Callable, buffer: io.StringIO = None, interval: float = 1, stream_status={}, **kwargs):
        r"""
        Since fetch web page contents may cost very long time. Send heartbeat at the same time to avoid connection close.
        """
        try:
            start_time = time.time()
            async def write_buffer():
                f = func(test=self.test, stream_status=stream_status, **kwargs)
                if asyncio.iscoroutine(f):
                    await f
                    return
                async for item in f:
                    if not buffer or not item:
                        continue
                    buffer.write(item)
            task = asyncio.create_task(write_buffer())
            shielded = asyncio.shield(task)

            while not task.done():
                yield None
                await asyncio.sleep(interval)
            
            await shielded
            end_time = time.time()
            logger.info(f"[_task_with_heartbeat]{callable} cost time total {end_time - start_time}s")
            yield None
        except Exception as e:
            traceback.print_exc()
            raise Exception(f"Task {func.__name__} with heartbeat failed: {str(e)}")
        
    async def use_tool(self, user_prompt: str = "", **kwargs):
        from utils.obs.client import upload_file
        translation_task = asyncio.create_task(self.synopsis_analyzer.translate_indication())
        try:
            # check whether need query
            start_time = time.time()
            # query rewrite
            response = self.mindsearch_helper.init_response(self)
            response.raw_data = self.query_params
            yield response
            response.search_graph = self.init_search_graph()
            response.processing_type = ProcessingType.PROCESSING
            yield response
            
            await asyncio.wait([translation_task])
            sa = self.synopsis_analyzer
            if sa.chinese_query_params:
                response.search_graph.children[0].thought_process += f"适应症译为: {sa.query_params['indication']}\n"
            yield response
            try:
                sa.run_search_trials()
            except Exception as e:
                traceback.print_exc()
                response.content = str(e)
                response.search_graph = None
                yield response
                return
                
            response.search_graph.children[0].processing_type = ProcessingType.DONE
            yield response
            
            buffer = io.StringIO()
            sa.model = DeepseekChat()
            await sa.build_trial_data()
            data_dict = {"query_params": sa.query_params, "trial_data": sa.outcome_data, 'other_params': sa.other_params,
            'current_date': datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d'), 'synopsis_output_template': sa.synopsis_template_parts[2], 'extra_requirements': "请用中文输出" if self.language == 'zh-CN' else "Please output in English"}
            partial_prompt_template = partial_prompt_template_cn if self.language == 'zh-CN' else partial_prompt_template_en
            async for _ in self._task_with_heartbeat(sa.build_synopsis_part, buffer=buffer, prompt_template=partial_prompt_template, data_dict=data_dict, response=response, idx=1, check=False, model=ClaudeSonnet46(), temperature=0.05):
                yield response  
                
            data_dict.update({"trial_data": sa.description_data, 'synopsis_output_template': sa.synopsis_template_parts[0]})
            partial_prompt_template_chain = partial_prompt_template_chain_cn if self.language == 'zh-CN' else partial_prompt_template_chain_en
            async for _ in self._task_with_heartbeat(sa.build_synopsis_part, buffer=buffer, prompt_template=partial_prompt_template_chain, data_dict=data_dict, response=response, idx=2, check=True, model=Gemini35Flash()):
                yield response  
                
            data_dict.update({"trial_data": sa.eligibility_data, 'synopsis_output_template': sa.synopsis_template_parts[1]})
            async for _ in self._task_with_heartbeat(sa.build_synopsis_part, buffer=buffer, prompt_template=partial_prompt_template_chain, data_dict=data_dict, response=response, idx=3, check=True, model=Gemini35Flash()):
                yield response  
            
            logger.info(f"Mindesearch final response input: {kwargs}")
            buffer.seek(0)
            buffer.truncate(0)
            # stream_status = {"enabled": True}
            data_dict['synopsis_output_template'] = sa.synopsis_template_parts[3]
            partial_prompt_template_post = partial_prompt_template_post_cn if self.language == 'zh-CN' else partial_prompt_template_post_en
            async for _ in self._task_with_heartbeat(sa.build_synopsis_part, buffer=buffer, prompt_template=partial_prompt_template_post, data_dict=data_dict, response=response, idx=4, check=False, model=DeepseekChat()):
                yield response  
            response.search_graph.children[4].processing_type = ProcessingType.DONE
            buffer.seek(0)
            buffer.truncate(0)
            retry = 0
            longest = ""
            
            # Replace consecutive spaces of length 3 or more with empty string
            cleaned_text = re.sub(r' {3,}', '', str(sa.synopsis_parts))
            parts_cleaned_len = len(cleaned_text) - cleaned_text.count(r'\n') - cleaned_text.count(r'-') - cleaned_text.count(r'#') - cleaned_text.count(r' ')
            
            while len(longest) < parts_cleaned_len*0.8 and retry < 2:
                async for _ in self._task_with_heartbeat(sa.synopsis_gen_stream, buffer=buffer, model=Gemini35Flash(), temperature=0):
                    s = buffer.getvalue()
                    # response.search_graph.children[4].thought_process = s
                    if not s:
                        continue
                    response.content = s
                    yield response  
                print("len(s):", len(s))
                print("len(sa.synopsis_parts):", len(str(sa.synopsis_parts)))
                if len(s)>len(longest):
                    longest = s
                retry += 1
                buffer.seek(0)
                buffer.truncate(0)
            response.content = longest
            yield response
            buffer.close()
            response.search_graph.children[5].processing_type = ProcessingType.DONE
            
            # Save report and outputs to zip file
            # zip_path = f"{sa.output_dir}.zip"
            doc_path = f"{sa.output_dir}/data/synopsis.docx"
            
            try:
                convert_md_to_docx(os.path.join(sa.output_dir, "data"))
            except Exception as e:
                logger.info(f"Failed to convert markdown to docx: {str(e)}")
            if not os.path.exists(sa.output_dir + '/data'):
                os.makedirs(sa.output_dir + '/data', exist_ok=True)
            shutil.make_archive(sa.output_dir, 'zip', sa.output_dir)
            logger.info(f"Output saved to {doc_path}")
            
            bucket_name = "noahai-userdata-test"
            user = kwargs.get("user", "unknown")
            # file_name = sa.output_dir + ".zip"
            file_name = sa.output_dir + "/data/" + "synopsis.docx"
            for _ in range(3):
                res = upload_file(bucket_name=bucket_name, object_key=f"synopsis/{user}/{file_name}", file_path=doc_path)
                if res: 
                    logger.info(f"File {doc_path} uploaded successfully")
                    response.search_graph.attachments_key = f"synopsis/{user}/{file_name}"
                    break
                await asyncio.sleep(3)
            else:
                logger.error(f"Failed to upload {doc_path}")
                
            # if hasattr(sa, "synopsis") and sa.synopsis:
            # response.content = sa.synopsis
            response.content = response.content.replace('```markdown', '').replace('```', '')
            response.content += "\n---\n\n"
            response.content += ("## 下载链接：[临床方案]" if self.language == 'zh-CN' else "## Download link: [Synopsis]") + f"(https://{bucket_name}.obs.cn-south-1.myhuaweicloud.com/{response.search_graph.attachments_key})"
            
            response.search_graph.children[-1].processing_type = ProcessingType.DONE
            response.search_graph.summary = "DONE"
            prev_content = response.content
            response.content = ''
            yield response
            
            response.content = prev_content
            yield response
            
        except Exception as e:
            traceback.print_exc()
            raise UnexpectedException(str(e))
        
    def init_search_graph(self):
        root = SearchNode(search_type=SearchType.UNKNOWN,
                    query="Synopsis generation",
                    key_word="")
        subject = WebSearchSubject.UNKNOWN.value
        root.subject = WebSearchSubject(subject)
        root.thought_process = "报告生成即将执行" if self.language == 'zh-CN' else "Synopsis generation will commence shortly"
        
        steps = ["Obtain clinical data (~5s)",
                 "Synopsis outcomes section generation & verification (3-5 mins)",
                 "Synopsis description section generation & verification (3-5 mins)",
                 "Synopsis eligibility section generation & verification (3-5 mins)",
                 "Synopsis discontinuation section generation & verification (3-5 mins)",
                 "Synopsis generation (2-4 mins)"
                 ]
        steps_chinese = ["获取临床数据 (~5s)",
                         "生成outcomes板块并验证 (3-5分钟)",
                         "生成description板块并验证 (3-5分钟)",
                         "生成eligibility板块并验证 (3-5分钟)",
                         "生成discontinuation板块并验证 (3-5分钟)",
                         "临床方案生成 (2-4分钟)"]
        
        for subtitle in (steps_chinese if self.language == "zh-CN" else steps):
            
            node = SearchNode(search_type=SearchType.UNKNOWN,
                    query=subtitle,
                    key_word="")
            root.add_child(node)
        
        return root
    