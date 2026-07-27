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
from typing import Any, Callable, List, Optional, Type

from pydantic import BaseModel, Field
from agent.core.preset import AgentPreset
from llm.azure_models import GPT4o
from llm.base_model import BaseLLM
from agent.explore.schema import ProcessingType, SearchNode, SearchType, WebSearchLink, WebSearchSubject
from agent.explore.helper import MindSearchHelper
from agent.synopsis.synopsis_analyzer_roche import SynopsisAnalyzerV2
from llm.composite_models import CompositeHitlFinal, Compositeo3, DeepseekClaude
from utils.core.exception import UnexpectedException
from agent.synopsis.prompts.report_en import partial_prompt_template_post_en, partial_prompt_template_chain_en, partial_prompt_template_en
from agent.synopsis.prompts.report import partial_prompt_template_cn, partial_prompt_template_post_cn, partial_prompt_template_chain_cn
from agent.synopsis.prompts.roche_cn import *
from agent.synopsis.prompts.roche import *
from llm.deepseek_models import CompositeDeepseekChat, CompositeDeepseekReasoner
from llm.gcp_models import ClaudeSonnet4, CompositeClaude
from agent.human_in_loop.utils import convert_md_to_docx
from utils.sql_client import get_connection_user, text

logger = logging.getLogger(__name__)


class CriterionItem(BaseModel):
    description: str
    database_mapping: Optional[str] = None

class PECOSElements(BaseModel):
    population: str
    exposure_or_intervention: str
    comparison: str
    outcome: str
    primary_endpoints: list[str] = Field(default_factory=list)
    secondary_endpoints: list[str] = Field(default_factory=list)
    study_design: str
    limitations: Optional[str] = None

class ResearchStep(BaseModel):
    step_name: str
    description: str

class SynopsisStructured(BaseModel):
    basic_information: Optional[str] = None
    background_and_rationale: Optional[str] = None
    
    pecos: Optional[PECOSElements] = None
    guidelines_and_norms: list[str] = Field(default_factory=list)
    bias_warnings: list[str] = Field(default_factory=list)
    research_steps: list[ResearchStep] = Field(default_factory=list)
    inclusion_criteria: list[CriterionItem] = Field(default_factory=list)
    exclusion_criteria: list[CriterionItem] = Field(default_factory=list)

class SynopsisAgentV2(AgentPreset):
    analyzer_class: Type[SynopsisAnalyzerV2] = SynopsisAnalyzerV2
    llm: BaseLLM = GPT4o
    sys_prompt: str = ""
    mindsearch_helper: MindSearchHelper = MindSearchHelper()
    language: str = "zh-CN"
    test: bool = False
    synopsis_analyzer: SynopsisAnalyzerV2 = None
    query_mode: bool = False
    query_params: dict = {}
    
    def __init__(self, query_params={}, query_mode=False, gemini_mode=False, **kwargs):
        from llm.gcp_models import Gemini31Pro
        super().__init__()
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
        print("query_params", query_params)
            
        self.query_params = query_params
            
        if 'test' in kwargs and type(kwargs['test']) == bool:
            self.test = kwargs.pop('test',False)
  
        output_dir = f"outputs/synopsis_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.query_mode = query_mode
        
        self.synopsis_analyzer = self.analyzer_class(model=Gemini31Pro(), query_params=query_params, language=self.language)
        self.synopsis_analyzer.set_output_dir(output_dir)
        self.synopsis_analyzer.gemini_mode = gemini_mode

    async def run_func(self, func: Callable, buffer: io.StringIO):
        async_generator = func()
        try:
            async for item in async_generator:
                buffer.write(item)
        except Exception as e:
            logger.error(f"run_func failed: {str(e)}")
            raise e
        
    async def yield_until_coroutine_done(self, task: asyncio.Task, interval: float = 0.3):
        r"""
        Since fetch web page contents may cost very long time. Send heartbeat at the same time to avoid connection close.
        """
        try:
            start_time = time.time()
            while not task.done():
                yield None
                await asyncio.sleep(interval)
            await task
            end_time = time.time()
            logger.info(f"[yield_coroutine_until_done]{callable} cost time total {end_time - start_time}s")
            yield None
        except Exception as e:
            traceback.print_exc()
            raise Exception(f"Task {task.get_name()} yield until done failed: {str(e)}")
    
    async def _task_with_heartbeat(self, func: Callable, buffer: io.StringIO = None, interval: float = 0.3, **kwargs):
        r"""
        Since fetch web page contents may cost very long time. Send heartbeat at the same time to avoid connection close.
        """
        try:
            start_time = time.time()
            async def write_buffer():
                f = func(**kwargs)
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
        # translation_task = asyncio.create_task(self.synopsis_analyzer.translate_chinese())
        translate_and_indication_expansion_task = asyncio.create_task(self.synopsis_analyzer.translate_and_expand_indication())
        match_age_group_task = asyncio.create_task(self.synopsis_analyzer.match_age_group())
        web_search_task = None
        try:
            if self.query_mode:
                response = self.mindsearch_helper.init_response(self)
                response.raw_data = self.query_params
                yield response
                response.search_graph = self.init_search_graph(query_mode=True)
                response.processing_type = ProcessingType.PROCESSING
                
                yield response
                await asyncio.wait([translate_and_indication_expansion_task, match_age_group_task])
                sa = self.synopsis_analyzer
                response.search_graph.children[0].thought_process += f"{'适应症翻译/扩展为' if self.language == 'zh-CN' else 'Indication translated and expanded to'}: {sa.query_params['indication']}\n"
                if sa.age_match:
                    response.search_graph.children[0].thought_process += f"{'年龄匹配为' if self.language == 'zh-CN' else 'Age classified as'}: {sa.query_params['age']}\n"
                yield response
                try:
                    sa.run_search_trials()
                except Exception as e:
                    traceback.print_exc()
                    response.content = str(e)
                    response.search_graph.children[0].processing_type = ProcessingType.DONE
                    yield response
                    return
                response.search_graph.children[0].processing_type = ProcessingType.DONE
                
                yield response
                # sa.save_trial_data()
                bucket_name = "noahai-userdata-test"
                user = kwargs.get("user", "unknown")
                file_name = f"{sa.output_dir}.json"
                file_path = os.path.join(sa.output_dir, 'data', 'synopsis_trial_data.json')
                for _ in range(3):
                    res = upload_file(bucket_name=bucket_name, object_key=f"synopsis/{user}/{file_name}", file_path=file_path)
                    if res: 
                        logger.info(f"File {file_path} uploaded successfully")
                        response.search_graph.attachments_key = f"synopsis/{user}/{file_name}"
                        break
                    await asyncio.sleep(3)
                else:
                    logger.error(f"Failed to upload {file_path}")
                response.content = "## 下载链接：[临床实验数据]" if self.language == 'zh-CN' else "## Download link: [Trial Data]"
                response.content += f"(https://{bucket_name}.obs.cn-south-1.myhuaweicloud.com/{response.search_graph.attachments_key})" if response.search_graph.attachments_key else ""
                # response.content += f"\n\n```bucketdownload {response.search_graph.attachments_key}```" if response.search_graph.attachments_key else ""
                yield response
                return
            # check whether need query
            start_time = time.time()
            # query rewrite
            response = self.mindsearch_helper.init_response(self)
            response.raw_data = self.query_params
            yield response
            response.search_graph = self.init_search_graph()
            response.processing_type = ProcessingType.PROCESSING
            yield response
            sa = self.synopsis_analyzer
            web_search_task = asyncio.create_task(sa.web_search_for_background_info(response=response, idx=2))
            
            await asyncio.wait([translate_and_indication_expansion_task, match_age_group_task])
            logger.info(f"query_params: {sa.query_params}")
            logger.info(f"original_params: {sa.original_params}")
            # if sa.chinese_query_params:
            response.search_graph.children[0].thought_process += f"{'适应症翻译/扩展为' if self.language == 'zh-CN' else 'Indication translated and expanded to'}: {sa.query_params['indication']}\n"
            response.search_graph.children[0].thought_process += f"{'年龄匹配为' if self.language == 'zh-CN' else 'Age classified as'}: {sa.query_params['age']}\n"
            yield response
            try:
                sa.run_search_trials()
            except Exception as e:
                traceback.print_exc()
                response.content = str(e)
                response.search_graph = None
                yield response
                return
                
            for id_key in ['id', 'nctId', 'nct_id']:
                if sa.trial_data and sa.trial_data[0].get(id_key, None):
                    print(f"Using {id_key} as identifier")
                    break
            
            response.search_graph.children[0].thought_process += f'NCT IDs:\n'
            response.search_graph.children[0].thought_process += f"{','.join(t[id_key] for t in sa.trial_data)}\n"
            response.search_graph.children[0].thought_process += f"Creative Mode {'off' if sa.enablePrecision else 'on'}"
            # else:
            #     response.search_graph.children[0].thought_process += f"Version {version}\n"

            response.search_graph.children[0].processing_type = ProcessingType.DONE
            yield response
            
            buffer = io.StringIO()
            sa.model = Compositeo3()
            await sa.build_trial_data()
            fixed_rule = '固定为"请按照要求填写。"' 
            none_set = (None, [], {}, '', '未提供', '不适用', '未特别说明', 'none', 'null', 'Null', 'NULL')
            _setting_section = setting_section
            _database_section = database_section
            _covariate_section = covariate_section
            _effect_modifier_section = effect_modifier_section
            _loss_to_followup_section = loss_to_followup_section
            _matching_section = matching_section
            _sampling_section = sampling_section
            _multiplicity_section = multiplicity_section
            _subgroup_section = subgroup_section
            _interaction_section = interaction_section
            _data_missing_section = data_missing_section
            _sensitivity_section = sensitivity_section
            _special_considerations_section = special_considerations_section
            _setting_section_rule_1 = setting_section_rule_1
            _setting_section_rule_2 = setting_section_rule_2
            _setting_section_rule_3 = setting_section_rule_3
            _setting_section_rule_4 = setting_section_rule_4
            _setting_section_rule_5 = setting_section_rule_5
            _considerations_rule_1 = consideration_rule_1
            _considerations_rule_2 = consideration_rule_2
            _considerations_rule_3 = consideration_rule_3
            _extra_covariate_rule = extra_covariate_rule
            _considerations_rule = ''
            
            study_type = sa.original_params.get('study_type', None)

            if self.language == 'en-US':
                _setting_section = setting_section_en
                _database_section = database_section_en
                _covariate_section = covariate_section_en
                _effect_modifier_section = effect_modifier_section_en
                _loss_to_followup_section = loss_to_followup_section_en
                _matching_section = matching_section_en
                _sampling_section = sampling_section_en
                _multiplicity_section = multiplicity_section_en
                _subgroup_section = subgroup_section_en
                _interaction_section = interaction_section_en
                _data_missing_section = data_missing_section_en
                _sensitivity_section = sensitivity_section_en
                _special_considerations_section = special_considerations_section_en
                _setting_section_rule_1 = setting_section_rule_1_en
                _setting_section_rule_2 = setting_section_rule_2_en
                _setting_section_rule_3 = setting_section_rule_3_en
                _setting_section_rule_4 = setting_section_rule_4_en
                _setting_section_rule_5 = setting_section_rule_5_en
                _considerations_rule_1 = consideration_rule_1_en
                _considerations_rule_2 = consideration_rule_2_en
                _considerations_rule_3 = consideration_rule_3_en
                _extra_covariate_rule = extra_covariate_rule_en
                fixed_rule = 'Fixed as: "Please fill in according to the requirements."'
            template_sections = {"data_missing_section": _data_missing_section, "sensitivity_section": _sensitivity_section,
                                 "matching_section": _matching_section, "sampling_section": _sampling_section, "multiplicity_section": _multiplicity_section,
                                 "database_section": _database_section, "loss_to_followup_section": "", "sampling_section": "",
                                 "study_period_rule": fixed_rule, "effect_modifier_section": _effect_modifier_section,
                                 "special_considerations_section": "", "subgroup_section": _subgroup_section,
                                 "interaction_section": _interaction_section}
            data_dict = {"query_params": sa.original_params, "trial_data": sa.outcome_data, 'other_params': sa.other_params,
            'current_date': datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d'), 'synopsis_output_template': sa.synopsis_template_parts[2], 'few_shot_examples': sa.synopsis_fewshot_parts[2],
            'extra_requirements': "2. 请用中文输出" if self.language == 'zh-CN' else "2. Please output in English"}
            if sa.original_params.get('multiplicityAdjustment', "") in none_set and sa.original_params.get('multiplicityAdjustmentOther', "") in none_set:
                template_sections['multiplicity_section'] = ""
            if ((sa.original_params.get('dataSourceVariables', {}) or {}).get('research_database', {}) or {}).get('info', None) in none_set:
                template_sections['database_section'] = ""
            if sa.enablePrecision:
                if (exposureVariable := sa.original_params.get('exposureVariable', '')) not in none_set:
                    exposureVariable = sa.original_params.get('exposureVariable', '')
                if (interventions := sa.original_params.get('interventions', '')) not in none_set:
                    interventions = sa.original_params.get('interventions', '')
                if (outcome := sa.original_params.get('outcome', '')) not in none_set:
                    outcome = sa.original_params.get('outcome', '')
                if exposureVariable: exposureVariable = ': ' + str(exposureVariable)
                if interventions: interventions = ': ' + str(interventions)
                if outcome: outcome = ': ' + str(outcome) 
                
                data_dict['extra_requirements'] += ("\n3. 严格按照<试验方案摘要规范>生成内容，不要直接引用<Noah数据>，也不要编造数据库或组织名称等主体" if self.language == 'zh-CN' else "\n3. Strictly follow the <Synopsis Specification> to generate content, do not directly reference <Noah Data> or fabricate entities like database or organization names")
                data_dict['extra_requirements'] += (f"\n4. 暴露变量应与用户提供的<试验方案摘要规范>中的'exposureVariable'{exposureVariable}和'interventions'{interventions}字段内容完整地一一对应" if self.language == 'zh-CN' else f"\n4. Exposure variables should comprehensively reflect values one to one in 'exposureVariable'{exposureVariable} and 'interventions'{interventions} fields in the user-provided <Synopsis Specification>")
                data_dict['extra_requirements'] += (f"\n5. 结局变量应与用户提供的<试验方案摘要规范>中的'outcome'{outcome}字段内容完整地一一对应，若适用，按照主要结局、次要结局和探索性结局分类标记" if self.language == 'zh-CN' else f"\n5. Outcome variables should comprehensively reflect values one to one in 'outcome'{outcome} field in the user-provided <Synopsis Specification>, and if applicable, categorized and labeled as primary, secondary, or exploratory outcomes.")
                data_dict['extra_requirements'] += ('\n6. 调整缩进和markdown格式，使输出更加有层次感且易于阅读。' if self.language == 'zh-CN' else '\n6. Adjust indentation and markdown formatting to make the output more well-layered and easier to read.')
                # data_dict['extra_requirements'] += ('\n7. 不要生成<输出模板>以外的小节/板块' if self.language == 'zh-CN' else '\n7. Do not generate sections other than those in the <Output Template>')
                if sa.original_params.get('effectModifiers', []) in none_set:
                    template_sections['effect_modifier_section'] = ""
                if sa.original_params.get('covariates', []) in none_set and sa.original_params.get('confounders', []) in none_set:
                    _covariate_section = ""
                else:
                    if sa.original_params.get('confounders', []) in none_set:
                        _extra_covariate_rule = ""
                # hasSubgroup / subgroupVariables
                if sa.original_params.get('hasSubgroup', []) in none_set:
                    template_sections['subgroup_section'] = ""
                if sa.original_params.get('hasInteraction', []) in none_set:
                    template_sections['interaction_section'] = ""

                if study_type in none_set:
                    template_sections['loss_to_followup_section'] = ""
                    template_sections['matching_section'] = ""
                    template_sections['sampling_section'] = ""
                    template_sections['special_considerations_section'] = ""
                else:
                    # cohort_mapping = {'PROSPECTIVE_COHORT':'前瞻性队列研究', 'RETROSPECTIVE_COHORT':'回顾性队列研究', 'AMBISPECTIVE_COHORT':'双向性队列研究'}
                    if 'COHORT' in study_type:
                        template_sections['matching_section'] = ""
                        template_sections['sampling_section'] = ""
                    elif 'CASE_CONTROL' in study_type:
                        template_sections['loss_to_followup_section'] = ""
                        template_sections['sampling_section'] = ""
                    elif 'CROSS_SECTIONAL' in study_type:
                        template_sections['loss_to_followup_section'] = ""
                        template_sections['matching_section'] = ""
                    else:
                        template_sections['loss_to_followup_section'] = ""
                        template_sections['matching_section'] = ""
                        template_sections['sampling_section'] = "" 
                if sa.original_params.get('lossToFollowup', "") not in none_set or sa.original_params.get('lossToFollowupOther', "") not in none_set:
                    template_sections['loss_to_followup_section'] = _loss_to_followup_section
                if sa.original_params.get('matchingMethod', "") not in none_set:
                    template_sections['matching_section'] = _matching_section
                if sa.original_params.get('samplingStrategy', "") not in none_set:
                    template_sections['sampling_section'] = _sampling_section
                # missingDataOther and missingDataHandling
                if sa.original_params.get('missingDataOther', "") not in none_set or sa.original_params.get('missingDataHandling', "") not in none_set:
                    template_sections['data_missing_section'] = _data_missing_section
                # sensitivityAnalysis and sensitivityAnalysisOther
                if sa.original_params.get('sensitivityAnalysis', "") not in none_set or sa.original_params.get('sensitivityAnalysisOther', "") not in none_set:
                    template_sections['sensitivity_section'] = _sensitivity_section

                if (setting:=sa.original_params.get('studyPeriod', {}) or {}):
                    if setting.get('studyPeriod', None) in none_set:
                        _setting_section_rule_1 = fixed_rule
                    else:
                        template_sections['study_period_rule'] = "根据<试验方案摘要规范>填写" if self.language == 'zh-CN' else "Fill in according to the <Synopsis Specification>"
                    if setting.get('identificationPeriod', None) in none_set:
                        _setting_section_rule_2 = fixed_rule
                    if setting.get('indexDate', None) in none_set:
                        _setting_section_rule_3 = fixed_rule
                    if setting.get('prePeriod', None) in none_set:
                        _setting_section_rule_4 = fixed_rule
                    if setting.get('postPeriod', None) in none_set:
                        _setting_section_rule_5 = fixed_rule
                else:
                    _setting_section_rule_1 = _setting_section_rule_2 = _setting_section_rule_3 = _setting_section_rule_4 = _setting_section_rule_5 = fixed_rule
            else:
                data_dict['extra_requirements'] += ('\n3. 调整缩进和markdown格式，使输出更加有层次感且易于阅读。' if self.language == 'zh-CN' else '\n3. Adjust indentation and markdown markdown formatting to make the output more well-layered and easier to read.')
                # data_dict['extra_requirements'] += ('\n4. 不要生成<输出模板>以外的小节/板块' if self.language == 'zh-CN' else '\n4. Do not generate sections other than those in the <Output Template>')
                template_sections['loss_to_followup_section'] = _loss_to_followup_section
                if 'COHORT' in study_type:
                    _considerations_rule = _considerations_rule_1
                elif 'CASE_CONTROL' in study_type:
                    _considerations_rule = _considerations_rule_2
                elif 'CROSS_SECTIONAL' in study_type:
                    _considerations_rule = _considerations_rule_3
                if _considerations_rule:
                    template_sections['special_considerations_section'] = _special_considerations_section.format(consideration_rule=_considerations_rule)
            template_sections['setting_section'] = _setting_section.format(setting_section_rule_1=_setting_section_rule_1, setting_section_rule_2=_setting_section_rule_2, setting_section_rule_3=_setting_section_rule_3, setting_section_rule_4=_setting_section_rule_4, setting_section_rule_5=_setting_section_rule_5)
            template_sections['covariate_section'] = _covariate_section.format(extra_covariate_rule=_extra_covariate_rule) if _covariate_section else ""
            data_dict['template_sections'] = template_sections
            partial_prompt_template = partial_prompt_template_cn if self.language == 'zh-CN' else partial_prompt_template_en
            async for _ in self._task_with_heartbeat(sa.build_synopsis_part, buffer=buffer, prompt_template=partial_prompt_template, data_dict=data_dict, response=response, idx=1, check=False, model=Compositeo3(), temperature=0.05):
                yield response  
            async for _ in self.yield_until_coroutine_done(web_search_task):
                yield response  
            data_dict.update({"trial_data": sa.description_data, 'synopsis_output_template': sa.synopsis_template_parts[0], 'few_shot_examples': sa.synopsis_fewshot_parts[0],
                              "extra_requirements": "3. 在文本中适当位置添加引用和参考文献" if self.language == 'zh-CN' else "3. Place citations and references in the text where applicable"})
            data_dict['extra_requirements'] += ("\n4. 请用中文输出" if self.language == 'zh-CN' else " 4. Please output in English")
            data_dict['extra_requirements'] += ('\n5. 调整缩进和markdown格式，使输出更加有层次感且易于阅读。' if self.language == 'zh-CN' else '\n5. Adjust indentation and markdown formatting to make the output more well-layered and easier to read.')
            # data_dict['extra_requirements'] += ('\n6. 不要生成<输出模板>以外的小节/板块' if self.language == 'zh-CN' else '\n6. Do not generate sections other than those in the <Output Template>')
            if sa.enablePrecision:
                data_dict['extra_requirements'] += ("\n6. 严格按照<试验方案摘要规范>生成内容，不要直接引用<Noah数据>" if self.language == 'zh-CN' else "\n7. Strictly follow the <Synopsis Specification> to generate content, do not directly reference <Noah Data>")
                data_dict['extra_requirements'] += ("\n7. 如果在<试验方案摘要规范>已经给定终点，要保持生成的与给定的终点一致：只能是基于给定终点的描述改进，不能增加或者修改终点" if self.language == 'zh-CN' else "\n8. If endpoints are already given in the <Synopsis Specification>, the generated content must be consistent with the given endpoints: they can only be based on the given endpoints and cannot be modified or have new ones added.")
                if sa.background_info:
                    data_dict['extra_requirements'] += ("\n8. 背景与理论依据板块的内容尽可能多地参考<Background Info>，输出尽量详细" if self.language == 'zh-CN' else "\n9. Content in Background and Rationale section should refer to <Background Info> as much as possible, output as detailed as possible")
            else:
                if sa.background_info:
                    data_dict['extra_requirements'] += ("\n6. 背景与理论依据板块的内容尽可能多地参考<Background Info>，输出尽量详细" if self.language == 'zh-CN' else "\n7. Content in Background and Rationale section should refer to <Background Info> as much as possible, output as detailed as possible")
            partial_prompt_template_chain = partial_prompt_template_chain_cn if self.language == 'zh-CN' else partial_prompt_template_chain_en
            async for _ in self._task_with_heartbeat(sa.build_synopsis_part, buffer=buffer, prompt_template=partial_prompt_template_chain, data_dict=data_dict, response=response, idx=3, check=False, model=Compositeo3()):
                yield response  

            data_dict.update({"trial_data": sa.eligibility_data, 'synopsis_output_template': sa.synopsis_template_parts[1], 'few_shot_examples': sa.synopsis_fewshot_parts[1],
                              "extra_requirements": "3. 请用中文输出" if self.language == 'zh-CN' else " 3. Please output in English"})
            data_dict['extra_requirements'] += ('\n4. 调整缩进和markdown格式，使输出更加有层次感且易于阅读。' if self.language == 'zh-CN' else '\n4. Adjust indentation and markdown formatting to make the output more well-layered and easier to read.')
            # data_dict['extra_requirements'] += ('\n5. 不要生成<输出模板>以外的小节/板块' if self.language == 'zh-CN' else '\n5. Do not generate sections other than those in the <Output Template>')
            if sa.enablePrecision:
                data_dict['extra_requirements'] += ("\n5. 严格按照<试验方案摘要规范>生成内容，不要直接引用<Noah数据>" if self.language == 'zh-CN' else "\n6. Strictly follow the <Synopsis Specification> to generate content, do not directly reference <Noah Data>")
            async for _ in self._task_with_heartbeat(sa.build_synopsis_part, buffer=buffer, prompt_template=partial_prompt_template_chain, data_dict=data_dict, response=response, idx=4, check=False, model=Compositeo3()):
                yield response

            logger.info(f"Mindesearch final response input: {kwargs}")
            buffer.seek(0)
            buffer.truncate(0)
            data_dict['synopsis_output_template'] = sa.synopsis_template_parts[3]
            # data_dict['few_shot_examples'] = sa.synopsis_fewshot_parts[3]
            partial_prompt_template_post = partial_prompt_template_post_cn if self.language == 'zh-CN' else partial_prompt_template_post_en
            async for _ in self._task_with_heartbeat(sa.build_synopsis_part, buffer=buffer, prompt_template=partial_prompt_template_post, data_dict=data_dict, response=response, idx=5, check=False, model=Compositeo3()):
                yield response  
            response.search_graph.children[5].processing_type = ProcessingType.DONE
            buffer.seek(0)
            buffer.truncate(0)
            retry = 0
            longest = ""
            
            # Replace consecutive spaces of length 3 or more with empty string
            cleaned_text = re.sub(r' {3,}', '', str(sa.synopsis_parts))
            parts_cleaned_len = len(cleaned_text) - cleaned_text.count(r'\n')
            while len(longest) < parts_cleaned_len*0.9 and retry < 1:
                async for _ in self._task_with_heartbeat(sa.synopsis_gen_stream, buffer=buffer, model=DeepseekClaude(), temperature=0.05):
                    s = buffer.getvalue()
                    if not s:
                        continue
                    # response.search_graph.children[4].thought_process = s
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
            response.search_graph.children[6].processing_type = ProcessingType.DONE
            yield response
            
            # Save report and outputs to zip file
            # zip_path = f"{sa.output_dir}.zip"
            doc_path = f"{sa.output_dir}/data/synopsis.docx"
            
            try:
                convert_md_to_docx(os.path.join(sa.output_dir, "data"), logo_path="static/roche-logo.png")
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
            response.search_graph.processing_type = ProcessingType.RESPONSEDONE
            
            response.search_graph.children[-1].processing_type = ProcessingType.DONE
            response.search_graph.summary = "DONE"
            prev_content = response.content
            response.content = ''
            yield response
            response.content = prev_content
            yield response

        except Exception as e:
            if web_search_task:
                web_search_task.cancel()
            traceback.print_exc()
            raise UnexpectedException(str(e))
        
    def init_search_graph(self, query_mode=False):
        root = SearchNode(search_type=SearchType.UNKNOWN,
                    query="Synopsis generation",
                    key_word="")
        subject = WebSearchSubject.UNKNOWN.value
        root.subject = WebSearchSubject(subject)
        if query_mode:
            root.thought_process = "报告生成将经过以下步骤"
            steps = ["获取临床数据 (~5s)"] if self.language == 'zh-CN' else ["Obtain clinical data (~5s)"]
            for subtitle in steps:
                node = SearchNode(search_type=SearchType.UNKNOWN,
                        query=subtitle,
                        key_word="")
                root.add_child(node)
            return root
        root.thought_process = "报告生成即将执行" if self.language == 'zh-CN' else "Synopsis generation will commence shortly"
        
        steps = ["Obtain clinical data (~15s)",
                 "Synopsis outcomes section generation & verification (1-3 mins)",
                 "Web search for background information (2-4 mins)",
                 "Synopsis description section generation & verification (2-4 mins)",
                 "Synopsis eligibility section generation & verification (2-4 mins)",
                 "Synopsis limitation section generation & verification (2-4 mins)",
                 "Synopsis generation (3-5 mins)"
                 ]
        steps_chinese = ["获取临床数据 (~15s)",
                         "生成outcomes板块并验证 (1-3分钟)",
                         "背景信息网络搜索 (2-4分钟)",
                         "生成description板块并验证 (2-4分钟)",
                         "生成eligibility板块并验证 (2-4分钟)",
                         "生成limitation板块并验证 (2-4分钟)",
                         "临床方案生成 (3-5分钟)"]
        
        for subtitle in (steps_chinese if self.language == "zh-CN" else steps):
            
            node = SearchNode(search_type=SearchType.UNKNOWN,
                    query=subtitle,
                    key_word="")
            root.add_child(node)
        
        return root
    