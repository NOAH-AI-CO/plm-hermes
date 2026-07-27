#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BP信息评估脚本
读取BP信息，调用PlanningAgent进行评估，并保存结果
"""

import json
import asyncio
import os
import logging
from datetime import datetime

from llm.gcp_models import Gemini31Pro

# logger
logger = logging.getLogger(__name__)

# Sets Google Cloud environment variables (if needed)
gcp_key_path = "/Users/chenzichu/Desktop/NoahServer/NoahAgent/noah_agent/gcp_key.json"
if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '') and os.path.exists(gcp_key_path):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path

os.environ['GOOGLE_CLOUD_PROJECT'] = "noahai-440408"
os.environ['GOOGLE_CLOUD_LOCATION'] = "global"
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"

key_mapping = {
    "company_name": "公司名称",
    "company_intro": "公司简介",
    "team_info": "团队情况",
    "tech_platform": "技术平台",
    "pipeline_info": "管线情况",
    "financing_info": "融资情况"
}

# Step 2 Schema: AI Analysis - Extract 1.1
bp_summary_extraction_schema = {
     "type": "OBJECT",
    "properties": {
        "team_analysis": {"type": "STRING", "description": "团队-AI分析"},
        "tech_analysis": {"type": "STRING", "description": "技术平台-AI分析"},
        "pipeline_analysis": {"type": "STRING", "description": "管线情况-AI分析"},
        "financing_analysis": {"type": "STRING", "description": "融资情况-AI分析"},
        "risk_analysis": {"type": "STRING", "description": "风险提示-AI分析"},
        "overall_analysis": {"type": "STRING", "description": "综合评估-AI分析"}
    },
    "required": ["team_analysis", "tech_analysis", "pipeline_analysis", "financing_analysis", "risk_analysis", "overall_analysis"]
}

# Step 3 Schema: AI Evaluation 3.0
bp_assessment_schema = {
    "type": "OBJECT",
    "properties": {
        "team_assessment": {"type": "STRING", "description": "团队-AI评估（一句话）"},
        "tech_assessment": {"type": "STRING", "description": "技术-AI评估（一句话）"},
        "pipeline_assessment": {"type": "STRING", "description": "管线-AI评估（一句话）"},
        "financing_assessment": {"type": "STRING", "description": "融资情况-AI评估（一句话）"},
        "overall_assessment": {"type": "STRING", "description": "综合评估-AI评估"},
        "suggestion": {"type": "STRING", "description": "跟进建议-AI评估（一句话）"}
    },
    "required": ["team_assessment", "tech_assessment", "pipeline_assessment", "financing_assessment", "overall_assessment", "suggestion"]
}

# Final Output Schema (Legacy compatibility)
evaluation_schema = {
    "type": "OBJECT",
    "properties": {
        "team_ai_analysis": {
            "type": "STRING",
            "description": "团队-AI分析"
        },
        "team_ai_summary": {
            "type": "STRING",
            "description": "团队-AI评估（一句话）"
        },
        "tech_ai_analysis": {
            "type": "STRING",
            "description": "技术平台-AI分析"
        },
        "tech_ai_summary": {
            "type": "STRING",
            "description": "技术-AI评估（一句话）"
        },
        "pipeline_ai_analysis": {
            "type": "STRING",
            "description": "管线情况-AI分析"
        },
        "pipeline_ai_summary": {
            "type": "STRING",
            "description": "管线-AI评估（一句话）"
        },
        "financing_ai_analysis": {
            "type": "STRING",
            "description": "融资情况-AI分析"
        },
        "financing_ai_summary": {
            "type": "STRING",
            "description": "融资情况-AI评估（一句话）"
        },
        "risk_ai_analysis": {
            "type": "STRING",
            "description": "风险提示-AI分析"
        },
        "overall_ai_analysis": {
            "type": "STRING",
            "description": "综合评估-AI分析"
        },
        "overall_ai_summary": {
            "type": "STRING",
            "description": "综合评估-AI评估"
        },
        "followup_ai_advice": {
            "type": "STRING",
            "description": "跟进建议-AI评估"
        },
        "followup_ai_summary": {
            "type": "STRING",
            "description": "跟进建议-AI评估（一句话）"
        }
    },
    "required": [
        "team_ai_analysis",
        "team_ai_summary",
        "tech_ai_analysis",
        "tech_ai_summary",
        "pipeline_ai_analysis",
        "pipeline_ai_summary",
        "financing_ai_analysis",
        "financing_ai_summary",
        "risk_ai_analysis",
        "overall_ai_analysis",
        "overall_ai_summary",
        "followup_ai_advice",
        "followup_ai_summary"
    ]
}


async def call_agent_func(prompt):
    """调用PlanningAgent进行评估"""
    from agent.human_in_loop.planning_v5 import PlanningAgent
    
    body = {
        "user_prompt": prompt,
        "language": "CN",
        "thread_id": f"evaluation-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "planning_task": {
            "id": f"evaluation-task-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "user": "evaluation_script"
        }
    }
    
    try:
        # Avoid circular import or runtime issues if run in a different context
        # Ideally imports should be at top but user provided it inside
        agent = PlanningAgent(**body)
        ret = None
        async for ret in agent.start_wo_dump(**body, api_mode=True):
            if ret.get('type') == 'summary':
                break
        
        return ret.get('message', '') if ret else ''
    except Exception as e:
        logger.error(f"PlanningAgent evaluation failed: {e}")
        raise Exception(f"评估失败: {str(e)}")


async def generate_agent_summary(bp_info_limited: dict) -> str:
    """Stage 1: Generate Agent Summary (AI Analysis 3.0)"""
    try:
        formatted_res = []
        for k, v in bp_info_limited.items():
            display_key = key_mapping.get(k, k)
            formatted_res.append(f"**{display_key}**:\n{v}")
        formatted_bp_info_limited = "\n\n".join(formatted_res)
        prompt = f"""# Role
你是一位拥有全球视野的资深硬科技/生物医药产业研究员。你擅长以 BP 为线索，通过外部数据比对、行业参数校验及竞争格局透视，还原项目的客观真相。

# Task
请基于提供的 BP 文本 {formatted_bp_info_limited}，将其作为原始线索，结合行业公认事实进行深度调研分析。
**核心原则**：禁止复述 BP 已知内容。你的输出必须是基于 BP 关键点的“增量信息”与“客观校验”。

# Research & Analysis Dimensions

1. **管线深度调研（重心：数据竞争力与市场真实性）**：
    * **横向指标对标**：针对 BP 披露的实验/产品数据，调取全球同类标杆（Benchmark）的最新临床/性能数据进行并列。指出该管线在有效性、安全性或核心参数上的真实排位。
    * **潜在市场穿透**：不采纳 BP 的预测逻辑。请基于发病率、现有标准疗法（SoC）的局限性、或国产替代的实际空间，客观推算该产品上市后的真实渗透逻辑及天花板。
    * **竞品动态监控**：列出与该管线处于同一研发阶段、或已有上市产品的全球竞争者名单，分析其在专利覆盖、准入进度上的客观差异。

2. **高管团队背景核实**：
    * **履历颗粒度还原**：基于 BP 提及的成员，分析其曾就职机构的业务关联性。例如：其主导的项目是否与当前管线领域一致？其过往成功的概率及在行业内的技术评价水位。
    * **核心职能缺口**：对比同阶段成功企业的标准配置，识别该团队在当前生命周期（如：从研发转向大规模商业化）中存在的结构性能力短板。

3. **技术平台稳定性与壁垒**：
    * **技术路径分位点**：分析该技术路径在全球范围内的成熟度（如：处于爆发期、瓶颈期或被替代风险期）。
    * **专利防御宽度**：客观评估其提及的专利布局是否能形成实质性的准入壁垒，是否存在核心底层专利被国际巨头封锁的风险。

4. **融资合理性与资本效率**：
    * **行业估值水位对标**：根据项目当前进度，对比同行业、同阶段近期融资案例的估值中位数，评估其估值的溢价或折价程度。
    * **现金流与里程碑逻辑**：分析本轮资金是否足以支撑其完成 BP 所述的下一个关键验证节点（如：流片、关键临床读数）。

5. **外部风险提示（压力测试）**：
    * **确定性风险**：列出该领域公认的客观难点（如：某靶点的脱靶效应、某工艺的良率瓶颈、或特定的出口管制政策）。
    * **证伪逻辑**：识别 BP 中逻辑自洽性最薄弱的环节，作为后续重点调研的“Red Flag”。

6. **综合分析素材（投资视角客观汇总）**：
    * **商业闭环的可行性路径**：梳理从研发到产生现金流的客观物理路径及关键节点。
    * **待核实事实清单**：列出 5-8 条需要通过专家访谈、现场核实或三方数据库确认的核心事实点。

# Constraints & Requirements
- **输出导向**：提供决策素材，而非提供主观建议。
- **信息增量**：如果 BP 说“我们很领先”，你要输出“根据 X 数据库，其参数对比 A 提升 X%，对比 B 落后 Y%”。
- **去形容词化**：严禁使用主观赞美或批评，只允许出现事实、数据、对比、逻辑。
- **纯文本输出**：保持清晰的逻辑层级，禁止使用表格。

请开始你的深度分析：
"""
        response_text = await call_agent_func(prompt)
        return response_text
    except Exception as e:
        logger.error(f"Error in generate_agent_summary: {e}")
        return ""

async def extract_agent_summary(agent_summary_text: str) -> dict:
    """Stage 2: Extract Analysis Points (AI Analysis - Extract 1.1)"""
    try:
        model = Gemini31Pro()
        prompt = f"""# Role
你是一位资深投研分析师，擅长从繁杂的调研资料中穿透表象，直接提取核心逻辑与定性观点。

# Task
请阅读“BP调研资料”，提取并总结以下六个维度的【核心观点】。

# Constraints
1. **观点优先**：重点提取原文对项目的评价、判断、逻辑推导和结论，而非枯燥的事实清单。
2. **极简事实**：事实仅作为支撑观点的必要补充（如：提及“进度领先”时可简述阶段），严禁罗列琐碎数据。
3. **字数控制**：每个部分严格控制在 260 字以内，保持高度精炼。
4. **拒绝自创**：所有观点必须源自所给资料，禁止加入 AI 的主观臆断。

# 参考案例 (Reference Case)
[
团队-AI分析：商业化实操经验已获验证：创始人具备成功将临床资产推进至大药企并购退出的实战背景，证明了其对临床价值变现的掌控力。
学术背书极高但职能失衡：科学顾问团队由美国青光眼协会主席等顶级专家组成，临床策略支撑强劲；但核心执行团队信息模糊，缺乏CMC及临床运营等关键职能的详细披露。
核心贡献度存疑：BP强调的“6个重磅新药”开发经验缺乏具体角色证明，大药企体系化成功未必能转化为初创企业的独立研发能力。
关键人物定位混淆：核心科学家的专利权属与实际参与深度不明，存在商业化贡献被夸大的风险。

技术平台-AI分析：给药机制具备理论创新但缺乏实证：眼睑给药技术在生理学上合理，但全球范围内缺乏独立临床证据，人体PK数据可靠性及患者依从性均存疑。
技术护城河深度不足：i-Gel及纳米胶束技术属于行业通用改良手段，非公司独有专利，面临“me-better”竞争压力，难以形成绝对技术壁垒。
基因治疗平台验证缺失：宣称的转染效率提升缺乏同行评议数据支持，且IIT阶段数据波动大，人体转化不确定性极高。
递送创新风险巨大：行业已有同类微剂量递送技术在III期失败的先例，证明给药途径创新极难直接转化为临床优效。

管线情况-AI分析：核心管线（IVW-1001）机制领先但数据脆弱：作为全球唯一靶向TRPM8的干眼症疗法，具备First-in-Class潜力，但II期数据处于显著性边缘且缺乏注册号，真实性待考。
结膜炎管线（IVIEW-1201）切入点精准但逻辑存疑：病毒性结膜炎市场空白真实，但宣称的“95.8%治愈率”远超行业常识，数据来源极度可疑。
近视管线（IVW-1802）进度严重滞后：赛道极度拥挤，在竞品即将上市时仍处于IND阶段，市场窗口期基本关闭，且面临同类技术失败的教训。
整体策略分散：管线跨度过大（五大领域），资源难以聚焦，且多数项目处于早期，缺乏爆发性的确定性支撑。

融资情况-AI分析：融资规模与管线需求严重错配：4000万美元B轮资金难以支撑多条管线（尤其是全球III期）的巨大开支，资金覆盖周期短，后续融资压力极大。
资本认可度及资源支持有限：现有股东缺乏眼科顶尖VC，在技术尽调、临床规划及全球BD合作上的资源赋能可能不足。
IPO策略过于激进：在核心数据存疑且多处于早期阶段时计划2026年IPO，估值可能面临大幅折价，且港股等市场对同类资产估值更为保守。
战略投资协同效应不明：主要战略投资者华海药业与眼科创新药研发的业务协同性有待核实。

风险提示-AI分析：数据真实性红旗：多项关键临床数据无法独立验证或极不合理，是动摇项目根基的核心风险。
临床转化与监管风险：新型给药途径若无法证明剂量一致性，可能触发FDA额外审查，导致进度大幅推迟或失败。
市场准入与竞争风险：近视及干眼症赛道先行者优势明显，后来者若无绝对优效性，将面临极高的市场教育成本和医保准入障碍。
财务与执行风险：资金链紧张可能导致临床入组中断，且早期资产在当前环境下获取高价BD授权的难度极大。

综合评估-AI分析：定论：该项目属于“高概念、弱验证”的早期标的。虽然在靶点前瞻性和临床空白点切入上有一定眼光，但核心竞争力建立在未经充分验证的数据之上。
优劣势对比：优势在于创始人的退出记录与专家背书；劣势在于临床数据可信度存疑、技术壁垒薄弱及管线进度滞后。
未来确定性：项目确定性极低。在未获得完整CSR报告、FDA对给药途径的明确意见及第三方数据审计前，其创新价值被严重的不确定性掩盖，理性的投资决策应坚持“证据为王”，审慎对待其宣传的逻辑。
]

# Output Format

### 1. 团队-AI分析
（重点提炼：原文对团队专业性、协同力、行业地位及背景背书的评价观点）

### 2. 技术平台-AI分析
（重点提炼：原文对技术独特性、护城河深度、替代风险及底层逻辑的定性评估）

### 3. 管线情况-AI分析
（重点提炼：原文对产品竞争力、市场切入点合理性及预期爆发力的核心判断）

### 4. 融资情况-AI分析
（重点提炼：原文对资本市场认可度、财务健康度及本轮融资策略价值的观点）

### 5. 风险提示-AI分析
（重点提炼：原文中认为可能动摇项目根基、影响进度或估值的核心担忧点）

### 6. 综合评估-AI分析
（重点提炼：原文对该项目在赛道中整体优劣势对比及未来确定性的最终定论）

---
# Input Data
{agent_summary_text}
"""
        response_text = await model(
            user_prompt=prompt,
            json_mode=True,
            response_schema=bp_summary_extraction_schema,
            temperature=0,
            thinking_budget="low"
        )
        return json.loads(response_text)
    except Exception as e:
        logger.error(f"Error in extract_agent_summary: {e}")
        # Return empty dict matching schema keys to avoid errors
        return {key: "" for key in bp_summary_extraction_schema["required"]}


async def generate_subjective_assessment(agent_summary_text: str, bp_info_limited: dict) -> dict:
    """Stage 3: Generate Subjective Assessment (AI Evaluation 3.0)"""
    try:
        model = Gemini31Pro()
        formatted_res = []
        for k, v in bp_info_limited.items():
            display_key = key_mapping.get(k, k)
            formatted_res.append(f"**{display_key}**:\n{v}")
        formatted_bp_info_limited = "\n\n".join(formatted_res)
        prompt = f"""# Role
你是一名资深的生物医药买方分析师。你拥有极强的独立思考能力，能够穿透“项目方自述”与“第三方调研”的表象，从全局视角审视项目的底层逻辑。

# Inputs
请基于以下两项核心输入：
1. 【BP的信息】：{formatted_bp_info_limited}
2. 【针对该BP做的调研（Agent Summary）】：{agent_summary_text}

# Task & Evaluation Logic
你不仅要汇总信息，更要作为一名具备辩证思维的分析师进行“主观判断”：
- **交叉验证**：将 BP 中的自我主张与 Agent Summary 中的客观数据进行对撞。
- **独立研判**：对于 Agent Summary 中给出的现成观点，你需要结合大环境进行批判性采纳，而非简单罗列，形成你自己的全局判断。

# Output Requirements (严格字数限制)

1. **团队-AI评估**：[评价团队背景、工业履历及执行力。限30字以内]
2. **技术-AI评估**：[评价底层逻辑、技术独特性及壁垒高度。限30字以内]
3. **管线-AI评估**：[评价临床获益、市场稀缺性及差异化策略。限30字以内]
4. **融资情况-AI评估**：[评价融资阶段、估值及现有股东背书情况。限30字以内]
5. **综合评估-AI评估**：[基于全局视角的深度逻辑推演。分析项目在当前医药周期下的核心风险、竞争优势及长期生存力，体现独立研判。限260字以内]
6. **跟进建议-AI评估**：[必须先选定“重点跟进 / 选择性交流 / 暂不跟进”之一，再简述核心理由。限30字以内]

# 判定标准：跟进建议
- **重点跟进**：亮点清晰集中，值得立即投入资源深入交流。
- **选择性交流**：有一定合理性但亮点强度不足，仅在合适时机交流。
- **暂不跟进**：尚未看到支撑进一步交流的明确亮点，暂不投入成本。

# Tone
冷静、专业、批判性。拒绝复述材料，直击核心痛点。
"""
        response_text = await model(
            user_prompt=prompt,
            json_mode=True,
            response_schema=bp_assessment_schema,
            temperature=0,
            thinking_budget="low"
        )
        return json.loads(response_text)
    except Exception as e:
        logger.error(f"Error in generate_subjective_assessment: {e}")
        return {key: "" for key in bp_assessment_schema["required"]}


async def evaluate_bp_json_text(bp_data_or_text) -> dict:
    """
    Main entry point: Input BP structured data (dict or JSON string), output evaluation structured dict.
    
    Orchestrates the 3-step evaluation process:
    1. Generate Agent Summary
    2. Extract Analysis Points
    3. Generate Subjective Assessment
    """
    if not bp_data_or_text:
        return {key: "" for key in evaluation_schema["required"]}

    try:
        if isinstance(bp_data_or_text, str):
            bp_data = json.loads(bp_data_or_text)
        elif isinstance(bp_data_or_text, dict):
            bp_data = bp_data_or_text
        else:
            logger.error(f"Invalid input type for BP evaluation: {type(bp_data_or_text)}")
            return {key: "" for key in evaluation_schema["required"]}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse BP JSON text: {e}")
        return {key: "" for key in evaluation_schema["required"]}

    # Step 1: Generate Agent Summary
    logger.info("Starting Step 1: Generate Agent Summary")
    agent_summary = await generate_agent_summary(bp_data)
    
    # Step 2: Extract Analysis Points
    logger.info("Starting Step 2: Extract Analysis Points")
    analysis_points = await extract_agent_summary(agent_summary)
    
    # Step 3: Generate Subjective Assessment
    logger.info("Starting Step 3: Generate Subjective Assessment")
    assessment_points = await generate_subjective_assessment(agent_summary, bp_data)
    
    # Map to final schema (legacy compatibility)
    result = {
        "team_ai_analysis": analysis_points.get("team_analysis", ""),
        "team_ai_summary": assessment_points.get("team_assessment", ""),
        
        "tech_ai_analysis": analysis_points.get("tech_analysis", ""),
        "tech_ai_summary": assessment_points.get("tech_assessment", ""),
        
        "pipeline_ai_analysis": analysis_points.get("pipeline_analysis", ""),
        "pipeline_ai_summary": assessment_points.get("pipeline_assessment", ""),
        
        "financing_ai_analysis": analysis_points.get("financing_analysis", ""),
        "financing_ai_summary": assessment_points.get("financing_assessment", ""),
        
        "risk_ai_analysis": analysis_points.get("risk_analysis", ""),
        
        "overall_ai_analysis": analysis_points.get("overall_analysis", ""),
        "overall_ai_summary": assessment_points.get("overall_assessment", ""),
        
        # Mapping suggestion to followup fields
        "followup_ai_advice": assessment_points.get("suggestion", ""), # putting short suggestion in advice too if no long advice
        "followup_ai_summary": assessment_points.get("suggestion", "")
    }
    
    logger.info(f"Evaluation completed. Result keys: {result.keys()}")
    return result

async def structure_evaluation_result(evaluation_text: str=None, prompt_override=None) -> dict:
    """将评估文本用 Gemini 结构化为 JSON"""
    if not evaluation_text and not prompt_override:
        return {key: "" for key in evaluation_schema["required"]}

    try:
        from llm.gcp_models import Gemini31Pro
        llm = Gemini31Pro()

        prompt = prompt_override or f"""请将以下评估文本结构化为 JSON，仅输出 JSON，不要输出任何多余文字。

## 输入前提

评估文本由第一步 agent 生成，**包含 6 个维度的客观分析**（团队、技术平台、管线、融资、风险、综合），你需要根据语义从文本中识别各维度内容并进行划分和结构化。

## 你的任务

1. **划分 6 个维度的分析内容**：从评估文本中按语义识别并截取各维度内容，填入对应的 team_ai_analysis、tech_ai_analysis、pipeline_ai_analysis、financing_ai_analysis、risk_ai_analysis、overall_ai_analysis。
2. **生成 6 个维度的一句话总结**：对上述 6 个维度分别根据分析内容概括成一句话，填入对应的 *_ai_summary，严格 30 字以内，偏买方视角的浓缩结论。
3. **生成跟进建议字段**：根据整体分析内容，从买方视角给出「是否值得跟进」的主观判断：\n   - 在 followup_ai_advice 中输出详细的跟进建议（理由、关注重点、建议行动等），风格与之前分析一致，无字数硬限制；\n   - 在 followup_ai_summary 中给出一句话结论，必须以「重点跟进」「选择性交流」「不跟进」三者之一开头，例如「重点跟进：XXX」，总字数不超过 30 字。

## 字数与定位

- *_ai_analysis：客观分析，完整返回文本内容
- *_ai_summary：买方视角一句话结论，限 30 字
- followup_ai_advice：买方视角的详细跟进建议，不做硬性字数限制
- followup_ai_summary：买方视角一句话跟进结论，须以「重点跟进/选择性交流/不跟进」开头，限 30 字

评估文本：
{evaluation_text}
"""

        response_text = await llm(
            user_prompt=prompt,
            temperature=0,
            response_mime_type="application/json",
            response_schema=evaluation_schema,
            thinking_budget="low"
        )

        logger.info(f"Evaluation struct response text: {response_text}")
        json_content = json.loads(response_text)
        logger.info(f"Parsed evaluation struct JSON: {json_content}")
        return json_content
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse evaluation JSON response: {e}")
        logger.error(f"Response text: {response_text if 'response_text' in locals() else 'N/A'}")
        return {key: "" for key in evaluation_schema["required"]}
    except Exception as e:
        logger.error(f"Error structuring evaluation result: {e}")
        raise