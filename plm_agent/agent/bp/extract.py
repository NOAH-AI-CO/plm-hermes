import os
import json
import logging
from google import genai
from google.genai import types
from google.genai.types import HttpOptions

logger = logging.getLogger(__name__)

# 设置 Google Cloud 环境变量（如果需要）
gcp_key_path = "/Users/chenzichu/Desktop/NoahServer/NoahAgent/noah_agent/gcp_key.json"
if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', ''):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path

os.environ['GOOGLE_CLOUD_PROJECT'] = "noahai-440408"
os.environ['GOOGLE_CLOUD_LOCATION'] = "global"
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"

# 定义 BP 解析的 JSON Schema
bp_extraction_schema = {
    "type": "OBJECT",
    "properties": {
        "company_name": {
            "type": "STRING",
            "description": "公司名称"
        },
        "company_intro": {
            "type": "STRING",
            "description": "公司简介，包括公司定位、主营业务、核心价值等"
        },
        "team_info": {
            "type": "STRING",
            "description": "团队情况，包括核心团队成员、背景、经验等"
        },
        "tech_platform": {
            "type": "STRING",
            "description": "技术平台，包括核心技术、技术优势、技术壁垒等"
        },
        "pipeline_info": {
            "type": "STRING",
            "description": "管线情况，包括产品管线、研发进展、临床阶段等"
        },
        "financing_info": {
            "type": "STRING",
            "description": "融资情况，包括融资轮次、融资金额、投资方、估值等"
        }
    },
    "required": [
        "company_name",
        "company_intro",
        "team_info",
        "tech_platform",
        "pipeline_info",
        "financing_info"
    ]
}


async def extract_bp_info(markdown_text: str) -> dict:
    """
    从商业BP的markdown格式文本中提取八个维度的信息
    
    Args:
        markdown_text: BP的markdown格式纯文本
        
    Returns:
        dict: 包含六个维度信息的字典
        {
            "company_name": "公司名称",
            "company_intro": "公司简介",
            "team_info": "团队情况",
            "tech_platform": "技术平台",
            "pipeline_info": "管线情况",
            "financing_info": "融资情况"
        }
    """
    try:
        client = genai.Client(http_options=HttpOptions(api_version="v1"))
        
        prompt = f"""请从以下商业计划书(BP)的markdown文本中提取以下八个维度的信息。

## 提取维度说明：

1. **公司名称**：公司的正式英文名称或中文名称
2. **公司简介**：公司的定位、主营业务、核心价值主张、技术平台概述等（控制在150字以内，尽量接近150字以提供完整信息）
3. **团队情况**：核心团队成员的姓名、职位、背景、经验、专业能力等（格式：姓名 | 职位 + 详细背景描述，控制在260字以内，尽量接近260字以提供详细完整的团队信息）
4. **技术平台**：核心技术、技术优势、技术壁垒、平台特点等（包括技术背景、突破点、关键数据等，控制在260字以内，尽量接近260字以充分展示技术细节）
5. **管线情况**：产品管线、研发进展、临床阶段、适应症、关键数据等（按管线编号或名称列出，控制在260字以内，尽量接近260字以涵盖所有主要管线信息）
6. **融资情况**：融资轮次、融资金额、投资方、估值、融资时间等（控制在260字以内，尽量接近260字以提供完整的融资信息）

## 输出示例参考：
公司名称: Oncera Therapeutics
公司简介: Oncera Therapeutics 是一家专注于免疫抑制型实体瘤治疗的创新生物医药公司，围绕原创肿瘤微环境靶点 OMR-21 与自主研发的 NanoReach™ 深渗透肿瘤递送平台构建差异化产品管线。公司核心管线 OC-112 已在胰腺癌与三阴乳腺癌模型中实现动物水平的强力 POC，展现出 First-in-Class 潜力；同时布局 NANO-ADC 与安全性增强组合疗法等多元化早期管线。管理团队由在肿瘤免疫、递送工程与临床转化方面拥有深厚经验的科学家与临床专家组成，覆盖从靶点验证、平台构建到临床试验设计的全链条能力，为公司实现临床推进与全球 BD 创造坚实基础。
团队情况: David Collins, PhD | 创始人兼 CEO
•前跨国药企免疫治疗科学负责人
•主导过两个 I/II 期免疫肿瘤项目，均成功进入临床
•有丰富的国际协作、BD 和融资经验
Raj Patel, PhD | 联合创始人 & CSO
•在大型 Biotech 负责 TME 平台十余年
•擅长抗体工程、免疫激活机制和组合疗法开发
•推动过 1 个 FIC 机制进入临床，是 TME 机制落地的关键人物
Michael Sanderson, MD |联合创始人 & CMO
•来自美国虚构癌症中心
•熟悉临床设计、患者分层、生物标志物筛选
•专注胰腺癌、TNBC 等高难度实体瘤，主导多个 I 期/II 期实体瘤免疫治疗项目
技术平台: NanoReach™ 深渗透递送平台
背景：难治实体瘤往往具有：高间质压力、密集纤维化屏障、低氧微环境→ 导致药物"进不去""走不动""停不久"。
NanoReach™ 提供三个技术突破：
深层组织渗透：可在高压力/致密纤维组织中获得传统纳米颗粒 2–5 倍的扩散半径。
缺氧稳定性强：适应肿瘤缺氧环境，不易被清除，峰值滞留时间延长约 70%。
可控释放：通过材料设计，实现在肿瘤酸性环境中加速释放，提高有效肿瘤暴露量。
管线情况: 1.OC-112（主力品种，IND阶段）— OMR-21 抑制剂 / TME 重塑创新药
作用机制：抑制 TME 中关键免疫抑制通路，使效应 T 细胞浸润提升 3–5 倍；并降低 MDSC、Treg 比例。
适应症：胰腺癌、三阴乳腺癌及高度"冷肿瘤"。
关键数据：在胰腺癌 KPC 模型中 肿瘤生长延缓 68%，联合 PD-1 可实现超过 40% 的完全缓解（CR），已基于动物数据实现明确 POC
	1	OC-207（PCC阶段） — 深渗透纳米抗体偶联药物（NANO-ADC）
针对高基质、高压力实体瘤，结合 NanoReach™ 递送实现深层肿瘤组织分布。
初步数据显示药物在肿瘤核心区域的浓度是普通 ADC 的 3.2 倍。
融资情况: 2023–2024 年累计获得 1200 万美元 投资（种子轮 + Pre-A）。
当前正在启动 Pre-A+ / A 轮融资，本轮投前估值：人民币 4 亿元（约合 5500 万美元）

## 提取要求：

1. 仔细阅读BP文本，准确提取每个维度的信息
2. 保持信息的完整性和准确性，不要遗漏关键细节
3. **字数限制要求**：
   - **公司简介**：控制在150字以内，尽量接近150字以提供完整信息
   - **团队情况、技术平台、管线情况、融资情况**：每个维度控制在260字以内，**尽量接近260字上限**，充分利用字数空间提供详细、完整的信息
4. 对于团队情况，如果有多位成员，请按上述格式列出所有核心成员，充分利用260字空间提供每位成员的详细背景
5. 对于管线情况，请列出所有主要管线及其关键信息，充分利用260字空间涵盖尽可能多的管线细节
6. 如果某个维度在文档中没有明确信息，返回空字符串
7. **重要**：在不超过字数限制的前提下，尽量接近字数上限，提供尽可能详细和完整的信息，避免过度简洁。优先保留最核心、最重要的信息，同时充分利用可用的字数空间

## BP文本内容：

{markdown_text}
"""
        
        response = await client.aio.models.generate_content(
            model="gemini-3.1-pro-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=bp_extraction_schema,
                temperature=0,
                thinking_config=types.ThinkingConfig(thinking_level="low")
            ),
        )
        
        logger.info(f"BP extraction response text: {response.text}")
        json_content = json.loads(response.text)
        logger.info(f"Parsed JSON content: {json_content}")
        
        return json_content
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        logger.error(f"Response text: {response.text if 'response' in locals() else 'N/A'}")
        # 返回默认结构，避免程序崩溃
        return {
            "company_name": "",
            "company_intro": "",
            "team_info": "",
            "tech_platform": "",
            "pipeline_info": "",
            "financing_info": ""
        }
    except Exception as e:
        logger.error(f"Error extracting BP info: {e}")
        raise
