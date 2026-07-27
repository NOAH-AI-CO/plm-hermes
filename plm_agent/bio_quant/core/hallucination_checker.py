import io
import os
from datetime import datetime
from typing import Dict, Any, Optional

class HallucinationChecker:
    """Utility class for checking hallucinations in LLM responses and saving results"""
    
    
    def __init__(self, language: str = 'zh-CN'):
        """Initialize hallucination checker
        
        Args:
            output_dir: Base directory for saving outputs
        """
        self.verification_prompt = """请根据下面提供的Prompt和基于该Prompt模型输出的报告，检查模型输出是否存在使用prompt中不存在的数据，不合理的假设，错误的计算，错误的引用等。

        Prompt:
        {prompt}

        模型输出的报告:
        {response}

        结果请输出为两个部分：
        1. 在<check></check>标签中，列出你找到的所有幻觉和错误
        2. 在<report></report>标签中，输出完整的修改后的报告，上下文数据一致

        请确保<check>标签中发现的错误和幻觉在<report>标签中全部得到修正。
        """ if language == 'zh-CN' else """Please review the model's output report based on the given Prompt and check if the model output contains data not present in the prompt, unreasonable assumptions, calculation errors, incorrect references, etc.

Prompt:
{prompt}

Model output report:
{response}

Please provide your results in two parts:
1. In the <check></check> tags, list all hallucinations and errors you found
2. In the <report></report> tags, output the complete corrected report with consistent contextual data

Please ensure that all errors and hallucinations identified in the <check> tags are fully corrected in the <report> tags."""
        
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
            self._save_responses(
                prompt=prompt,
                original_response=response,
                verified_response=verified_response,
                analysis_type=analysis_type,
                output_dir=output_dir
            )
            
            
            return verified_response
            
        except Exception as e:
            print(f"Warning: Hallucination check failed: {str(e)}")
            # Still save the original response
            self._save_responses(
                prompt=prompt,
                original_response=response,
                verified_response=None,
                analysis_type=analysis_type,
                output_dir=output_dir
            )
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
            
    async def check_and_save_stream(self, model: Any, prompt: str, response: str, analysis_type: str, output_dir: str = './outputs'):
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
            verified_response_gen = model.generate_stream(self.verification_prompt.format(prompt=prompt, response=response))
            
            string_buffer = io.StringIO()
            async for chunk in verified_response_gen:
                if chunk:
                    string_buffer.write(chunk)
                    yield chunk
            self.verified_response = string_buffer.getvalue()
            string_buffer.close()
            
                # Save both responses
            self._save_responses(
                prompt=prompt,
                original_response=response,
                verified_response=self.verified_response,
                analysis_type=analysis_type,
                output_dir=output_dir
            )
            
        except Exception as e:
            print(f"Warning: Hallucination check failed: {str(e)}")
            # Still save the original response
            self._save_responses(
                prompt=prompt,
                original_response=response,
                verified_response=None,
                analysis_type=analysis_type,
                output_dir=output_dir
            )