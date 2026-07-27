import io
import os
from datetime import datetime
import traceback
from typing import Dict, Any, Optional
import re

class HallucinationChecker:
    """Utility class for checking hallucinations in LLM responses and saving results"""
    
    def __init__(self, language: str = 'en', enablePrecision: bool = False):
        """Initialize hallucination checker
        
        Args:
            output_dir: Base directory for saving outputs
        """
        self.precision_prompt = "可以缺失少部分用户提供信息的内容，但是不可超出用户提供信息的范围。" if language == 'zh-CN' else "It's acceptable to omit some content from the user-provided specification, but do not go beyond the scope of the user-provided specification."
        self.verification_prompt = """请根据下面提供的Prompt和基于该Prompt模型输出的临床方案板块，检查模型输出是否存在虚构的信息和未按照Prompt要求执行的内容，并按照Prompt要求进行修正。{precision_prompt}

        Prompt:
        {prompt}

        模型输出的临床方案:
        {response}

        结果请输出为两个部分：
        1. 在<check></check>标签中，列出你找到的所有错误
        2. 在<synopsis></synopsis>标签中，输出完整的修改后的临床方案，上下文数据一致

        请确保<check>标签中发现的错误和幻觉在<synopsis>标签中全部得到修正。
        尽量保留全部原始文本，只修正识别的问题。
        """ if language == 'zh-CN' else """Based on the provided prompt and the synopsis chunk output from the model, please check for any fabricated information and content that does not follow the prompt requirements, and make corrections according to the prompt requirements. {precision_prompt}

        Prompt:
        {prompt}

        Output:
        {response}

        Please provide the results in two parts:
        1. Within <check></check> tags, list all errors you found
        2. Within <synopsis></synopsis> tags, output the complete revised synopsis with consistent context data

        Please ensure all errors and hallucinations identified in the <check> tags are corrected in the <synopsis> tags.
        Keep as much of the original text as possible, only correcting the identified issues.
        """
        if enablePrecision:
            self.verification_prompt = self.verification_prompt.replace("{precision_prompt}", self.precision_prompt)
        else:
            self.verification_prompt = self.verification_prompt.replace("{precision_prompt}", "")
        
    async def check_and_save(self, model: Any, prompt: str, response: str, analysis_type: str, output_dir: str = './outputs') -> str:
        """Check for hallucinations and save both original and verified responses
        
        Args:
            model: LLM model instance
            prompt: Original prompt
            response: Model's response to check
            analysis_type: Type of analysis (e.g., 'technical', 'financial')
            
        Returns:
            Verified response
        """
        try:
            # Get verified response
            verified_response = await model.generate(self.verification_prompt.format(prompt=prompt, response=response))
            
            # Save both responses
            # self._save_responses(
            #     prompt=prompt,
            #     original_response=response,
            #     verified_response=verified_response,
            #     analysis_type=analysis_type,
            #     output_dir=output_dir
            # )
            
            
            return verified_response
            
        except Exception as e:
            print(f"Warning: Hallucination check failed: {str(e)}")
            # Still save the original response
            # self._save_responses(
            #     prompt=prompt,
            #     original_response=response,
            #     verified_response=None,
            #     analysis_type=analysis_type,
            #     output_dir=output_dir
            # )
            return response

    def _save_responses(self, prompt: str, original_response: str, 
                       verified_response: Optional[str], analysis_type: str, output_dir: str = './outputs'):
        """Save original and verified responses to files
        
        Args:
            prompt: Original prompt
            original_response: Original model response
            verified_response: Verified response (or None if verification failed)
            analysis_type: Type of analysis
            output_dir: Directory to save verification results
        """
        try:
            # Create verification directory
            verification_dir = os.path.join(output_dir, "verifications")
            os.makedirs(verification_dir, exist_ok=True)
            
            # Get current timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Create content with metadata
            content = f"""Timestamp: {timestamp}
Analysis Type: {analysis_type}

Original Prompt:
{prompt}

Original Response:
{original_response}

"""
            if verified_response:
                content += f"""
Verified Response:
{verified_response}
"""
            
            # Save to file
            filename = f"{analysis_type}_verification_{timestamp}.md"
            filepath = os.path.join(verification_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Verification results saved to: {filepath}")
                
        except Exception as e:
            print(f"Warning: Failed to save verification results: {str(e)}") 
            raise e
            
    async def check_and_save_stream(self, model: Any, prompt: str, response: str, analysis_type: str, output_dir: str = './outputs', format_kwargs: dict = {}):
        """Check for hallucinations and save both original and verified responses
        
        Args:
            model: LLM model instance
            prompt: Original prompt
            response: Model's response to check
            analysis_type: Type of analysis (e.g., 'technical', 'financial')
            
        Returns:
            Verified response
        """
        try:
            # Get verified response
            
            self.verified_response = response
            # Extract content after </think> if it exists
            think_pattern = re.compile(r'</think>(.*)', re.DOTALL)
            think_match = think_pattern.search(response)
            if think_match:
                self.verified_response = think_match.group(1).strip()
                
            verified_response_gen = model.generate_stream(self.verification_prompt.format(prompt=prompt, response=response, **format_kwargs))
            
            string_buffer = io.StringIO()
            async for chunk in verified_response_gen:
                if chunk:
                    string_buffer.write(chunk)
                    yield chunk
            self.verified_response = string_buffer.getvalue()
            string_buffer.close()
            # Save both responses
            # self._save_responses(
            #     prompt=prompt,
            #     original_response=response,
            #     verified_response=self.verified_response,
            #     analysis_type=analysis_type,
            #     output_dir=output_dir
            # )
            
        except Exception as e:
            traceback.print_exc()
            print(f"Warning: {analysis_type} Hallucination check failed: {str(e)}")
            
            # Still save the original response
            # self._save_responses(
            #     prompt=prompt,
            #     original_response=response,
            #     verified_response=self.verified_response,
            #     analysis_type=analysis_type,
            #     output_dir=output_dir
            # )
            
    
class HallucinationCheckerStrict(HallucinationChecker):
    
    def __init__(self, language: str = 'en', enablePrecision: bool = False):
        """Initialize hallucination checker
        
        Args:
            output_dir: Base directory for saving outputs
        """
        self.precision_prompt = "可以缺失少部分用户提供信息的内容，但是不可超出用户提供信息的范围。" if language == 'zh-CN' else "It's acceptable to omit some content from the user-provided specification, but do not go beyond the scope of the user-provided specification."
        self.verification_prompt = """请根据下面提供的Prompt和基于该Prompt模型输出的临床方案板块，检查模型输出是否存在虚构的信息、是否与<用户临床方案参数>冲突和未按照Prompt要求执行的内容，并按照Prompt要求进行修正。{precision_prompt}，

        <用户临床方案参数>
        {query_params}
        </用户临床方案参数>

        Prompt:
        {prompt}

        模型输出的临床方案板块:
        {response}

        结果请输出为两个部分：
        1. 在<check></check>标签中，列出你找到的所有错误
        2. 在<synopsis></synopsis>标签中，输出完整的修改后的临床方案，上下文数据一致

        请确保<check>标签中发现的错误、冲突和幻觉在<synopsis>标签中全部得到修正。
        尽量保留全部原始文本，只修正识别的问题。
        """ if language == 'zh-CN' else """Based on the provided prompt and the partial synopsis output from the model, please check for any fabricated information, any inconsistencies with <User Specification>, and content that does not follow the prompt requirements, and make corrections according to the prompt requirements. {precision_prompt}


        <User Specification>
        {query_params}
        </User Specification>

        <Prompt>
        {prompt}
        </Prompt>

        <Partial Synopsis Output>
        {response}
        </Partial Synopsis Output>

        Please provide the results in two parts:
        1. Within <check></check> tags, list all issues found
        2. Within <synopsis></synopsis> tags, output the complete revised summary with consistent context data

        Please ensure all issues identified in the <check> tags are corrected in the <synopsis> tags.
        Keep as much of the original text as possible, only correcting the identified issues.
        """
        if enablePrecision:
            self.verification_prompt = self.verification_prompt.replace("{precision_prompt}", self.precision_prompt)
        else:
            self.verification_prompt = self.verification_prompt.replace("{precision_prompt}", "")