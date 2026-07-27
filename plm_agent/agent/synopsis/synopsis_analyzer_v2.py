import re
import asyncio
import io
import traceback
import json
import pytz
import os
from abc import ABC
from datetime import datetime
from agent.explore.schema import MindSearchResponse, ProcessingType
from agent.synopsis.hallucination_checker import HallucinationChecker
from agent.synopsis.synopsis_query_trials import search_trials
from utils.bio_quant.dummy_stream import dummy_stream
from agent.synopsis.prompts.output import synopsis_output_template, synopsis_output_template_order, synopsis_output_template_order_cn
from agent.synopsis.prompts.output_partial_en import synopsis_output_template_a_en, synopsis_output_template_b_en, synopsis_output_template_c_en, synopsis_output_template_d_en
from agent.synopsis.prompts.output_partial import synopsis_output_template_a, synopsis_output_template_b, synopsis_output_template_c, synopsis_output_template_d
from utils.sql_client import get_connection, text
from agent.synopsis.prompts.report_en import merge_prompt_en, partial_prompt_template_en
from agent.synopsis.prompts.report import merge_prompt_cn, partial_prompt_template_cn
from llm.azure_models import GPT5Mini
from agent.synopsis.schema import SynopsisTranslationSchema
from llm.base_model import BaseLLM
from llm.composite_models import SlotFillingModels
from utils.core.get_json_schema import get_openai_json_schema_v3
from utils.human_in_loop.helpers import function_call_with_retry
from utils.sql_client import get_connection_user
from i18n.languages import normalize as _norm
import logging

logger = logging.getLogger(__name__)

class SynopsisAnalyzerV2(ABC):
    slot_filling_llm: BaseLLM = SlotFillingModels(max_retries=0, timeout=15, first_chunk_timeout=10)

    def __init__(self, model, query_params={}, **kwargs):
        logger.info(f"SynopsisAnalyzerV2 init, kwargs: {kwargs}")
        """Initialize synopsis analyzer with LLM model"""
        self.synopsis = ''
        self.trial_data = {}
        self.model = model
        self.query_params = query_params
        self.chinese_query_params = False
        self.output_dir = './outputs'
        self.gemini_mode = False
        self.synopsis_parts = []
        self.language = _norm(kwargs.get('language', ''))
        logger.info(f"SynopsisAnalyzerV2 language: {self.language}")
        if self.language == 'en-US':
            self.synopsis_template_parts = [synopsis_output_template_a_en, synopsis_output_template_b_en, synopsis_output_template_c_en, synopsis_output_template_d_en]
        else:
            self.synopsis_template_parts = [synopsis_output_template_a, synopsis_output_template_b, synopsis_output_template_c, synopsis_output_template_d]

    def set_output_dir(self, output_dir: str):
        """Set output directory for synopsis results"""
        self.output_dir = output_dir

    async def check_hallucination(self, test=False, **kwargs):
        try:
            # hallucination checking
            verified_synopsis = dummy_stream("check_hallucination", stream_status=kwargs["stream_status"]) if test else self.hallucination_checker.check_and_save_stream(
                model=self.model,
                prompt=self.prompt,
                response=self.draft,
                analysis_type="synopsis",
                output_dir=self.output_dir
            ) 
            
            async for chunk in verified_synopsis:
                if test:
                    await asyncio.sleep(0.1)
                yield chunk

            verified_result = getattr(self.hallucination_checker, "verified_response", None)
            if not verified_result:
                print("临床方案幻觉检查失败")
                return
            
            # Extract verified synopsis from verified_synopsis, tagged by <synopsis>...</synopsis>
            verified_synopsis_search = re.search(r'<synopsis>(.*?)</synopsis>', verified_result, re.DOTALL)
            self.synopsis = verified_synopsis_search.group(1) if verified_synopsis_search else verified_result
            if not self.synopsis:
                raise Exception("临床方案幻觉检查失败, 未能匹配<synopsis>")
            
            data_dir = os.path.join(self.output_dir, "data")
            synopsis_file = os.path.join(data_dir, 'synopsis.md')
            with open(synopsis_file, 'w', encoding='utf-8') as f:
                f.write(self.synopsis)
            print(f"- 临床方案已保存至：{synopsis_file}")
            
            full_synopsis_file = os.path.join(data_dir, 'synopsis_full.md')
            with open(full_synopsis_file, 'w', encoding='utf-8') as f:
                f.write(verified_result)
            print(f"- 临床方案已保存至：{full_synopsis_file}")            
            
            
            print("- 临床方案幻觉检查完成")
        except Exception as e:
            traceback.print_exc()
            raise Exception(str(e))
            
            
    def run_search_trials(self):
        trials, other_params = search_trials(**self.query_params)
        self.other_params = list(other_params.keys())
        # self.cleanup_trial_data(trials)
        if not trials:
            raise Exception("未找到符合条件的临床实验数据")
        trial_ids = [trial['id'] for trial in trials]

        sql = f" SELECT nct_id, efficacy, safety, design FROM biomedtracker_trial_workflow WHERE nct_id IN :trial_ids"
        params = {'trial_ids': tuple(trial_ids)}
        with get_connection() as conn:
            result = conn.execute(text(sql), params)
            data = result.fetchall()
        result_dict = {}
        for row in data:
            result_dict[row[0]] = {'efficacy': row[1], 'safety': row[2], 'design': row[3]}
        for trial in trials:
            if trial['id'] in result_dict:
                trial['efficacy'] = result_dict[trial['id']]['efficacy']
                trial['safety'] = result_dict[trial['id']]['safety']
                trial['design'] = result_dict[trial['id']]['design']
        data_dir = os.path.join(self.output_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        trial_data_file = os.path.join(data_dir, 'synopsis_trial_data.json')
        with open(trial_data_file, 'w', encoding='utf-8') as f:
            json.dump(trials, f, indent=4, ensure_ascii=False)
        print(f"- 临床实验数据(all)已保存至：{trial_data_file}")
        self.trial_data = trials
        
    def save_trial_data(self):
        data_dir = os.path.join(self.output_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        trial_data_file = os.path.join(data_dir, 'synopsis_trial_data.json')
        with open(trial_data_file, 'w', encoding='utf-8') as f:
            json.dump(self.trial_data, f, indent=4, ensure_ascii=False)
        print(f"- 临床实验数据已保存至：{trial_data_file}")
        
    def is_chinese(self, text):
        """Check if text is predominantly Chinese"""
        if not text:
            return False
        # Check for Chinese character ranges
        chinese_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\u2f00-\u2fdf\u3000-\u303f\u31c0-\u31ef\u3200-\u32ff\u3300-\u33ff\ufe30-\ufe4f\ufe10-\ufe1f\uf900-\ufaff]')
        chinese_chars = len(chinese_pattern.findall(text))
        # If more than 15% of characters are Chinese, consider it Chinese
        print(f"Chinese characters found: {chinese_chars}, Total characters: {len(text)}")
        return chinese_chars / len(text) > 0.15
        
    async def translate_indication(self):
        """Translate indication name to English if it's in Chinese"""
        retry = 5
        while self.is_chinese(self.query_params['indication']) and retry > 0:
            self.chinese_query_params = True
            tool_filling_msg_json = await function_call_with_retry(self.slot_filling)
            self.query_params['indication'] = tool_filling_msg_json.get('translated_indication', self.query_params['indication'])
            retry -= 1 
        
    
    async def slot_filling(self):
        slot_filling_prompt = f"Please translate {self.query_params['indication']} into an english indication name\n"
        
        schema_format = get_openai_json_schema_v3(SynopsisTranslationSchema)
        function_name = schema_format[0]['function']['name']
        response = await self.slot_filling_llm(user_prompt=slot_filling_prompt, tools=schema_format, tool_choice={"type": "function", "function": {"name": function_name}}, temperature=0, max_tokens=8192)
        return response
    
    async def synopsis_gen_stream(self, test=False, stream_status={}, model=None, temperature=0.2):
        """Analyze synopsis data and return insights"""
        try:
            
            synopsis_parts_str = json.dumps(self.synopsis_parts, ensure_ascii=False, separators=(',', ':'))
            print("len(synopsis_parts_str)", len(synopsis_parts_str))
            
            self.prompt_template = merge_prompt_cn if self.language == 'zh-CN' else merge_prompt_en
            self.hallucination_checker = HallucinationChecker(language=self.language)

            
            print("- 生成合成提示词")
   
            prompt = self.prompt_template.format(
                query_params=self.query_params,
                current_date=datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d'),
                synopsis_parts=synopsis_parts_str,
                synopsis_output_template=synopsis_output_template_order_cn if self.language == 'zh-CN' else synopsis_output_template_order,
            )
            
            # Save prompt to file
            prompt_dir = os.path.join(self.output_dir, "prompts")
            os.makedirs(prompt_dir, exist_ok=True)
            prompt_file = os.path.join(prompt_dir, 'synopsis_merge_prompt.txt')
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(prompt)
            print(f"- 提示词已保存至：{prompt_file}")
            
            self.prompt = prompt
            
            stream_status['trial_data_obtained'] = True
            print("- 调用 AI 模型进行分析")
            # Get synopsis from LLM
            model = model or self.model
            synopsis_gen = model.stream_call(user_prompt=prompt, stream=True, stream_status=stream_status, system_prompt=False, temperature=temperature)
            string_buffer = io.StringIO()
            async for chunk in synopsis_gen:
                if chunk:
                    string_buffer.write(chunk)
                    yield chunk
            draft = string_buffer.getvalue()
            string_buffer.close()
            self.draft = draft.replace('```markdown', '').replace('```', '')
            
            data_dir = os.path.join(self.output_dir, "data")
            synopsis_file = os.path.join(data_dir, 'synopsis.md')
            with open(synopsis_file, 'w', encoding='utf-8') as f:
                f.write(self.draft)
            print(f"- 临床方案已保存至：{synopsis_file}")
            
        except Exception as e:
            print(f"\n错误详情：")
            import traceback
            print(traceback.format_exc())
            raise Exception(str(e))
        
    async def check_hallucination_part(self, checker:HallucinationChecker, prompt:str,result:str, analysis_type:str, test=False, **kwargs):
        try:
            # hallucination checking
            verified_synopsis = dummy_stream("check_hallucination", stream_status=kwargs["stream_status"]) if test else checker.check_and_save_stream(
                model=self.model,
                prompt=prompt,
                response=result,
                analysis_type=analysis_type,
                output_dir=self.output_dir
            ) 
            
            async for chunk in verified_synopsis:
                if test:
                    await asyncio.sleep(0.1)
                yield chunk

            verified_result = getattr(checker, "verified_response", None)
            if not verified_result:
                print(f"临床方案{analysis_type}幻觉检查失败")
                return
            
            # Extract verified synopsis from verified_synopsis, tagged by <synopsis>...</synopsis>
            verified_synopsis_search = re.search(r'<synopsis>(.*?)</synopsis>', verified_result, re.DOTALL)
            if verified_synopsis_search:
                checker.synopsis = verified_synopsis_search.group(1) 
            else:
                print(f"临床方案{analysis_type}幻觉检查失败, 未能匹配<synopsis>")
                checker.synopsis = result
            
            data_dir = os.path.join(self.output_dir, "data")
            synopsis_file = os.path.join(data_dir, 'synopsis.md')
            with open(synopsis_file, 'w', encoding='utf-8') as f:
                f.write(checker.synopsis)
            print(f"- 临床方案{analysis_type}已保存至：{synopsis_file}")
                    
            
            print(f"- 临床方案{analysis_type}幻觉检查完成")
        except Exception as e:
            traceback.print_exc()
            raise Exception(str(e))
        
    async def build_synopsis_part(self, prompt_template:str, data_dict, response: MindSearchResponse, idx, check=True, model=None, **kwargs):
        
        prompt = prompt_template.replace(r'{query_params}', str(data_dict['query_params'])).replace(r'{trial_data}', str(data_dict['trial_data']))
        prompt = prompt.replace(r'{current_date}', str(data_dict['current_date'])).replace(r'{synopsis_output_template}', str(data_dict['synopsis_output_template']))
        prompt = prompt.replace(r'{extra_requirements}', str(data_dict.get('extra_requirements','')))
        prompt = prompt.replace(r'{other_params}', str(data_dict.get('other_params','[]')))
        prompt = prompt.replace(r'{synopsis_parts}', str(self.synopsis_parts))
        
        prompts_dir = os.path.join(self.output_dir, "prompts")
        os.makedirs(prompts_dir, exist_ok=True)
        prompt_data_file = os.path.join(prompts_dir, f'synopsis_partial_prompt_{idx}.txt')
        with open(prompt_data_file, 'w', encoding='utf-8') as f:
            f.write(prompt)
        print(f"- 提示词{idx}已保存至：{prompt_data_file}")
        temp = kwargs.get('temperature', None)
        generate_args = {}
        if temp:
            generate_args['temperature'] = temp
        model = model or self.model
        synopsis_part_gen = model.stream_call(user_prompt=prompt, stream=True, stream_status={}, system_prompt=False, **generate_args)
        string_buffer = io.StringIO()
        result = ""
        async for chunk in synopsis_part_gen:
            if chunk:
                string_buffer.write(chunk)
                if len(response.search_graph.children) > idx:
                    response.search_graph.children[idx].thought_process = string_buffer.getvalue()
                else:
                    response.content = string_buffer.getvalue()
        result = string_buffer.getvalue().replace('```markdown', '').replace('```', '')
        verified_result = None
        string_buffer.seek(0)
        string_buffer.truncate(0)
        if check:
            response.search_graph.children[idx].thought_process += "\n\n报告校验中..."
            response.search_graph.children[idx].thought_process += "\n---\n\n"
            response.search_graph.children[idx].thought_process += '## 校验结果:\n'
            checker = HallucinationChecker()
            async for chunk in self.check_hallucination_part(checker, prompt, result, analysis_type=f"part{idx}", test=False):
                string_buffer.write(chunk)
                response.search_graph.children[idx].thought_process += chunk
            verified_result = getattr(checker, "synopsis", None)
            if not verified_result:
                print(f"临床方案p{idx}幻觉检查失败")
        response.search_graph.children[idx].processing_type = ProcessingType.DONE
        res = verified_result or result
        self.synopsis_parts.append(res)
        return res
        
    async def build_trial_data(self):
        trial_data = self.trial_data
        description_data_fields = ['description','armsInterventionsModule','conditionsModule','outcomesModule','location','design', 'safety','efficacy']
        eligibility_data_fields = ['eligibilityModule']
        outcome_data_fields = ['outcomesModule','designModule','statusModule','armsInterventionsModule','design', 'safety','efficacy']
        shared_data_fields = ['identificationModule']
        
        description_data = [{k:trial[k] for k in shared_data_fields+description_data_fields if k in trial} for trial in trial_data]
        eligibility_data = [{k:trial[k] for k in shared_data_fields+eligibility_data_fields if k in trial} for trial in trial_data]
        outcome_data = [{k:trial[k] for k in shared_data_fields+outcome_data_fields if k in trial} for trial in trial_data]
        
        flag_a, flag_b, flag_c, flag_d = False, False, False, False
        for i in range(len(trial_data),0,-1):
            if not flag_a and len(str(description_data[:i])) < 165000:
                description_data = description_data[:i]
                flag_a = True
            if not flag_b and len(str(eligibility_data[:i])) < 160000:
                eligibility_data = eligibility_data[:i]
                flag_b = True
            if not flag_c and len(str(outcome_data[:i])) < 170000:
                outcome_data = outcome_data[:i]
                flag_c = True
            if flag_a and flag_b and flag_c:
                break
        data_names = (('description', description_data), ('eligibility', eligibility_data), ('outcome', outcome_data))
        data_dir = os.path.join(self.output_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        for name, data in data_names:
            trial_data_file = os.path.join(data_dir, f'synopsis_{name}_data_selected.json')
            with open(trial_data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            print(f"- 临床实验数据已保存至：{trial_data_file}")
        for i, part in enumerate(self.synopsis_template_parts):
            self.synopsis_template_parts[i] = part.replace("{query_params}", str(self.query_params))
        self.description_data = description_data
        self.eligibility_data = eligibility_data
        self.outcome_data = outcome_data
        
        
    async def build_synopsis_parts(self, mind_response: MindSearchResponse, **kwargs):
        # Create a list of tasks for each part
        await self.build_trial_data()

        data_prompts = ((self.description_data, self.synopsis_template_parts[0]), (self.eligibility_data, self.synopsis_template_parts[1]), (self.outcome_data, self.synopsis_template_parts[2]))
        data_dict_base = {
            'query_params': self.query_params,
            'other_params': self.other_params,
            'current_date': datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d'),
            'extra_requirements': ''
        }
        
        tasks = []
        partial_prompt_template = partial_prompt_template_cn if self.language == 'zh-CN' else partial_prompt_template_en
        for i, (data, prompt_template) in enumerate(data_prompts):
            data_dict = {**data_dict_base, 
                         'synopsis_output_template': prompt_template,
                         'trial_data': json.dumps(data, ensure_ascii=False, separators=(',', ':'))}
            extra_args = {}
            if i == 2:
                extra_args['model'] = GPT5Mini()
                extra_args['temperature'] = 0.2
                extra_args['check'] = False
                data_dict['extra_requirements'] = "2.注意终点及其预设值设定要科学，样本数量应当是根据primary endpoints一步一步计算出来的，写明计算过程"
            tasks.append(asyncio.create_task(self.build_synopsis_part(partial_prompt_template, data_dict, mind_response, 1+i, **extra_args)))

        # Wait for all tasks to complete
        self.synopsis_parts = await asyncio.gather(*tasks)
        # self.synopsis_parts.append(self.synopsis_template_parts[3])
    
    