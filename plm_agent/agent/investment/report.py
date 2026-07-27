import asyncio
import io
import logging
import time
import traceback
from typing import Any, Callable, List

from agent.core.preset import AgentPreset
from llm.azure_models import GPT4o
from llm.base_model import BaseLLM
from agent.explore.schema import ProcessingType, SearchNode, SearchType, WebSearchLink, WebSearchSubject
from agent.explore.helper import MindSearchHelper
from bio_quant.core.analyzer import StockAnalyzer
from bio_quant.data_sources.fmp_source import FMPDataSource
from bio_quant.data_sources.polygon_source import PolygonOptionsSource
from bio_quant.data_sources.twitter_source import TwitterDataSource
from bio_quant.data_sources.composite_source import CompositeDataSource
from utils.core.exception import UnexpectedException
from tools.core.base_tool import BaseTool
import shutil
import os

logger = logging.getLogger(__name__)

class InvestmentReportAgent(AgentPreset):
    llm: BaseLLM = GPT4o
    sys_prompt: str = ""
    tools: List[BaseTool] = []
    mindsearch_helper: MindSearchHelper = MindSearchHelper()
    stock_analyzer: StockAnalyzer = None
    language: str = "en-US"
    test: bool = False
    
    def __init__(self, symbol, **kwargs):
        from bio_quant.models.composite_model import CompositeModel
        super().__init__()
        try:
            if 'params' in kwargs and 'language' in kwargs['params']:
                from i18n.languages import normalize as _norm
                self.language = _norm(kwargs['params']['language'])
        except: pass
        if 'test' in kwargs and type(kwargs['test']) == bool:
            self.test = kwargs['test']
        fmp_source = FMPDataSource()  # Primary source for stock data and technical indicators
        polygon_source = PolygonOptionsSource()  # Source for options data
        twitter_source = TwitterDataSource()  # Source for tweets data
        # Create composite data source
        data_source = CompositeDataSource(
            primary_source=fmp_source,
            options_source=polygon_source,
            twitter_source=twitter_source
        )
        self.stock_analyzer = StockAnalyzer(
            symbol=symbol,
            # llm_model=CompositeModel(test_mode=True),
            llm_model=CompositeModel(),
            # llm_model=Gemini15Flash(),
            language=self.language,
            data_source=data_source,
            period="6mo",
            target_year=None,
            output_dir=None,
            one_step=None,
            two_step=None
        )

    async def run_func(self, func: Callable, buffer: io.StringIO):
        async_generator = func()
        try:
            async for item in async_generator:
                buffer.write(item)
        except Exception as e:
            logger.error(f"run_func failed: {str(e)}")
            raise e
                
    async def use_tool(self, user_prompt: str = "", **kwargs):
        from utils.obs.client import upload_file
        try:
            # check whether need query
            start_time = time.time()
            # query rewrite
            response = self.mindsearch_helper.init_response(self)
            yield response
            response.search_graph = self.init_search_graph()
            yield response
            
            sa = self.stock_analyzer
            ca = self.stock_analyzer.catalyst_analyzer
            rg = self.stock_analyzer.report_generator
            
            logger.info(f"Mindesearch final response input: symbol={self.stock_analyzer.symbol}")
            stream_status = {"enabled": True}
            buffer = io.StringIO()
            async for _ in self._task_with_heartbeat(buffer, sa.analyze_catalyst_stream, interval=1, stream_status=stream_status):
                if 'catalyst_data_obtained' in stream_status and not response.search_graph.children[0].summary:
                    response.search_graph.children[0].summary = "DONE"
                    response.search_graph.children[0].processing_type = ProcessingType.DONE
                # s = buffer.getvalue()
                s = stream_status['answer_content'].getvalue() if 'answer_content' in stream_status else buffer.getvalue()
                response.search_graph.children[1].thought_process = s
                yield response
            response.search_graph.children[1].summary = "DONE"
            response.search_graph.children[1].processing_type = ProcessingType.DONE
            buffer.seek(0)
            buffer.truncate(0)
            stream_status = {"enabled": True}
            # response.search_graph.children[2].thought_process = "Checking hallucination..."
            async for _ in self._task_with_heartbeat(buffer, ca.check_hallucination, interval=1,stream_status=stream_status):
                # s = buffer.getvalue()
                s = stream_status['answer_content'].getvalue() if 'answer_content' in stream_status else buffer.getvalue()
                response.search_graph.children[2].thought_process = s
                yield response
            # response.search_graph.children[2].thought_process = ""
            response.search_graph.children[1].thought_process = ca.analysis
            response.search_graph.children[2].summary = "DONE"
            response.search_graph.children[2].processing_type = ProcessingType.DONE
            buffer.seek(0)
            buffer.truncate(0)
            stream_status = {"enabled": True}
            async for _ in self._task_with_heartbeat(buffer, sa.generate_report_stream, stream_status=stream_status):
                s = buffer.getvalue()
                # response.search_graph.children[3].thought_process = s
                response.content = s
                yield response  
            response.search_graph.children[3].summary = "DONE"
            response.search_graph.children[3].processing_type = ProcessingType.DONE
            response.content += "\n\n\n"
            response.content += "## 报告下载链接将在校对后提供，请稍候" if self.language == "zh-CN" else "## Download link: will be ready after proofreading. Please wait for a moment."
            buffer.seek(0)
            buffer.truncate(0)
            
            
            # Set socket status as final responsing
            response.processing_type = ProcessingType.RESPONSING
            stream_status = {"enabled": True}
            # periods_cnt = 0
            async for _ in self._task_with_heartbeat(buffer, rg.check_hallucination, interval=1, stream_status=stream_status):
                # s = buffer.getvalue()
                # periods_cnt += 1
                if 'answer_content' in stream_status:
                    try:
                        s = stream_status['answer_content'].getvalue()
                        response.search_graph.children[4].thought_process = s
                    except Exception as e:
                        logger.error(f"Failed to get answer content: {str(e)}")
                        pass
                # response.search_graph.children[4].thought_process = "checking for errors" + (periods_cnt//3 +1) * "."
                # response.content = s
                yield response
            buffer.close()
            response.search_graph.children[4].summary = "DONE"
            response.search_graph.children[4].processing_type = ProcessingType.DONE
            yield response
            
            
            logger.info(f"MindSearch final output: time passed {time.time() - start_time}s")
            
            # Save report and outputs to zip file
            zip_path = f"{self.stock_analyzer.output_dir}.zip"
            if not os.path.exists(self.stock_analyzer.output_dir + '/data'):
                os.makedirs(self.stock_analyzer.output_dir + '/data', exist_ok=True)
            shutil.make_archive(self.stock_analyzer.output_dir, 'zip', self.stock_analyzer.output_dir + '/data')
            logger.info(f"Output saved to {zip_path}")
            
            bucket_name = "noahai-userdata-test"
            user = kwargs.get("user", "unknown")
            for _ in range(3):
                res = upload_file(bucket_name=bucket_name, object_key=f"investment-reports/{user}/{sa.file_name}", file_path=zip_path)
                if res: 
                    logger.info(f"File {zip_path} uploaded successfully")
                    response.search_graph.attachments_key = f"investment-reports/{user}/{sa.file_name}"
                    break
                await asyncio.sleep(3)
            else:
                logger.error(f"Failed to upload {zip_path}")
                
            if hasattr(rg, "verified_report") and rg.verified_report:
                response.content = rg.verified_report
                response.content += "\n---\n\n"
                response.content += ("## 下载链接：[报告与数据]" if self.language == 'zh-CN' else "## Download link: [Report & Data]") + f"(https://{bucket_name}.obs.cn-south-1.myhuaweicloud.com/{response.search_graph.attachments_key})"
                if self.test:
                    response.content += "\n\n" + f"```bucketdownload {response.search_graph.attachments_key}```"
            yield response
            
            response.search_graph.summary = "DONE"
            yield response
            
        except Exception as e:
            traceback.print_exc()
            raise UnexpectedException(str(e))
        
    def init_search_graph(self):
        root = SearchNode(search_type=SearchType.UNKNOWN,
                    query="Investment report generation",
                    key_word="")
        root.thought_process = "报告生成将经过五个步骤" if self.language == 'zh-CN' else "Investment report generation follows a 5-step process"
        subject = WebSearchSubject.UNKNOWN.value
        root.subject = WebSearchSubject(subject)
        steps = ["Obtain financial and clinical data (~1 mins)",
                    "Financial and clinical analyses draft (2-4 mins)",
                    "Proofread financial & clinical analyses (2-4 mins)",
                    "Report draft (2-4 mins)",
                    "Proofread report (2-4 mins)"]
        steps_chinese = ["获取财务和临床数据 (~1 分钟)",
                    "生成财务和临床分析初稿 (2-4 分钟)",
                    "校对财务和临床分析 (2-4 分钟)",
                    "生成报告初稿 (2-4 分钟)",
                    "校对报告 (2-4 分钟)"]
        
        for subtitle in (steps_chinese if self.language == "zh-CN" else steps):
            
            node = SearchNode(search_type=SearchType.UNKNOWN,
                                query=subtitle,
                                key_word="")
            root.add_child(node)
        
        return root
    
    async def _task_with_heartbeat(self, buffer: io.StringIO, func: Callable, interval: float = 0.3, stream_status={}):
        r"""
        Since fetch web page contents may cost very long time. Send heartbeat at the same time to avoid connection close.
        """
        try:
            start_time = time.time()
            async def write_buffer():
                async for item in func(test=self.test, stream_status=stream_status):
                    if item:
                        buffer.write(item)
            task = asyncio.create_task(write_buffer())
            shielded = asyncio.shield(task)

            while not task.done():
                yield None
                await asyncio.sleep(interval)
            
            result = await shielded
            end_time = time.time()
            logger.info(f"[_task_with_heartbeat]{callable} cost time total {end_time - start_time}s")
            yield None
        except Exception as e:
            traceback.print_exc()
            raise Exception(f"Task {func.__name__} with heartbeat failed: {str(e)}")