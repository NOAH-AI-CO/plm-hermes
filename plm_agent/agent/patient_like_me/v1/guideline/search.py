#!/usr/bin/env python3
"""
阶段驱动的指南搜索（保留旧版 search_guideline.py，不替换）。
"""
import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# 必须在 import llm.gcp_models 之前设置：gcp_models 在模块加载时会立刻 auth.default()
# sys.path 须为「含 agent/、llm/、utils/ 的 noah_agent 目录」：
# __file__ = .../noah_agent/agent/patient_like_me/xxx.py → parents[2] = noah_agent
# 注意：若用 Path(__file__).parent（已是 patient_like_me）再 parents[2]，会错跳到 NoahAgent 外层。
_FILE = Path(__file__).resolve()
_SCRIPT_DIR = _FILE.parent
_NOAH_PKG_ROOT = _FILE.parents[4]  # v1/guideline → patient_like_me → agent → noah_agent
if str(_NOAH_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_NOAH_PKG_ROOT))

if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    for _key in (
        _NOAH_PKG_ROOT / "gcp_key.json",
        _NOAH_PKG_ROOT.parent / "gcp_key.json",
    ):
        if _key.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_key)
            break
if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = "noahai-440408"
if not os.environ.get("GOOGLE_CLOUD_LOCATION"):
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
if not os.environ.get("GOOGLE_GENAI_USE_VERTEXAI"):
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

from agent.patient_like_me.v1.guideline import guidance_db
from agent.patient_like_me.v1.guideline.graph_path import build_and_render as _build_graph_path
from llm.gcp_models import GoogleGenAIClientSingleton
# 在线 LLM 调用统一走 GLM-5.2 (DashScope).
# 保留 Gemini31Pro/Gemini35Flash 名字, 但绑到 GLM 类, 避免改散落在文件里的调用站点。
from llm.ali_models import Glm52Pro as Gemini31Pro
from llm.ali_models import Glm52Flash as Gemini35Flash

DEFAULT_FILE_PATH = "/Users/andy/Downloads/NCCN-AML-2024 V3_13-22(1).pdf"
PATIENT_TEXT = "患者确诊 APL，WBC 8 x 10^9/L，无心脏问题。"
PATIENT_TEXT_1 = "老年男性，有严重心衰，但对砒霜有严重不良反应，确诊APL，该怎么治疗"
PATIENT_TEXT_2 = "老年男性，有QT间期延长，小于70岁APL，该怎么治疗"
PATIENT_TEXT_3 = "中年女性，因当地缺少ATO，ATRA+gemtuzumab ozogamicin 治疗后。第28~35天血象恢复（血小板＞100×10⁹/L，中性粒细胞绝对值 ANC＞1×10⁹/L），行骨髓穿刺及活检，以证实原始细胞＜5% 且无异常早幼粒细胞。应该用什么巩固治疗？"
PATIENT_TEXT_3_NEW = '中年女性，因当地缺少ATO，ATRA+idarubicin 治疗后。第28~35天血象恢复（血小板＞100×10⁹/L，中性粒细胞绝对值 ANC＞1×10⁹/L），行骨髓穿刺及活检，以证实原始细胞＜5% 且无异常早幼粒细胞。应该用什么巩固治疗？'
PATIENT_TEXT_4 = '患者男，确诊APL，白细胞计数12*10^9/L，心脏健康无异常，但对ATO和GO有严重不良反应，可选的诱导治疗和巩固治疗分别有什么？'
PATIENT_TEXT_5 = '患者男，49 岁，新确诊 APL。先天性长 QT 综合征，无肾功能异常、无心脏病史、无药物过敏史。当地有 ATO、伊达比星、柔红霉素、GO，所有药物均可及。该患者首选的诱导治疗方案是什么？'
MAX_SUPPLEMENT_ROUNDS = 1
MAX_CANDIDATE_PATHS = 0  # 0 表示不截断，允许所有候选路径进入
MAX_PATHS_PER_TARGET = 3
MAX_PATH_DEPTH = 14 

PHASE_DECISION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "primary_phase_code": {"type": "STRING"},
        "secondary_phase_code": {"type": "STRING"},
        "additional_phase_codes": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "若患者信息涵盖多个治疗阶段（如综合评估问题涉及诱导、巩固、维持、监测），列出除 primary/secondary 之外所有需要检索的阶段 code。",
        },
        "confidence": {"type": "NUMBER"},
        "reason": {"type": "STRING"},
        "missing_dimensions": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["primary_phase_code", "secondary_phase_code", "confidence", "reason", "missing_dimensions"],
}

PATH_SELECT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "decision_type": {
            "type": "STRING",
            "description": "match | insufficient | guideline_gap",
        },
        "matched_node_ids": {
            "type": "ARRAY",
            "items": {"type": "INTEGER"},
            "description": "guideline_gap 时必须为空数组；不得为凑答案硬选节点。",
        },
        "analysis": {"type": "STRING"},
        "speculative_note": {
            "type": "STRING",
            "description": "仅当 guideline_gap 且需写通识层面参考时填写；须明确「非指南原文、仅为推测性讨论」；否则空字符串。",
        },
        "clarify_markdown": {
            "type": "STRING",
            "description": "完整给医生看的 Markdown,含 ## 已掌握信息 + ## 仍需澄清 两个章节;直接转给前端,不再二次加工。",
        },
    },
    "required": [
        "decision_type",
        "matched_node_ids",
        "analysis",
        "clarify_markdown",
    ],
}


POST_CHAIN_ANALYSIS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "analysis": {"type": "STRING"},
        "speculative_note": {
            "type": "STRING",
            "description": "如无必要可为空字符串。",
        },
    },
    "required": ["analysis", "speculative_note"],
}


def _build_phase_prompt(patient_text: str, phases: list[dict], guideline_name: str = "") -> str:
    lines = []
    for p in phases:
        lines.append(
            f"- code={p['code']}, zh={p.get('display_name_zh','')}, "
            f"en={p.get('display_name_en','')}, desc={p.get('description','')}"
        )
    guide_block = f"## 本指南\n{guideline_name}\n\n" if (guideline_name or "").strip() else ""
    return (
        "你是临床指南分诊助手。任务：判断患者当前处在【本指南】诊疗流程的哪个阶段，"
        "以便系统只在相关阶段的图谱节点里做精细匹配。\n\n"
        f"{guide_block}"
        "## 判断规则\n"
        "1. 从【可用阶段】中选出患者当前最可能所处的 primary_phase_code；如还涉及其他阶段，"
        "用 secondary_phase_code / additional_phase_codes 补上。\n"
        "2. 若患者叙述为综合评估、或明确跨越多个治疗阶段，**必须**在 additional_phase_codes 中"
        "列全所有相关阶段的 code，不要只返回单一阶段。凡涉及某项操作/评估的时机、后续监测随访时，"
        "把相邻的相关阶段一并纳入，避免漏掉这些阶段的节点与注脚。\n"
        "3. 不要过早推进阶段：患者若尚在某阶段的中期评估中（疗程未完、结果未出），仍属于该阶段，"
        "不要划入下一阶段。\n"
        "4. 信息不足以判断阶段时，confidence 设低，并在 missing_dimensions 里**一次列全**所有"
        "会影响阶段判断、但患者叙述未明确的关键事实。\n"
        "5. 【out_of_scope 严格限制】本指南已由上游按病种选为与患者最匹配的指南，"
        "因此**默认患者属于本指南范围**。仅当患者被明确确诊为与本指南病种**完全不同的另一种疾病**"
        "（或检测结果明确排除了本指南对应病种）时，才可将 primary_phase_code 设为 `out_of_scope`。"
        "**严禁**因为患者属于本指南病种下的某个少见亚型、分期特殊、或叙述里没出现典型治疗药物，"
        "就判 out_of_scope——这类情况应正常选阶段（信息不足则走 missing_dimensions）。\n\n"
        f"## 患者信息\n{patient_text}\n\n## 可用阶段\n" + "\n".join(lines)
    )


def _build_path_prompt(
    patient_text: str,
    node_registry: dict,
    paths: list[dict],
    condition_hints: list[dict],
    global_rules_text: str = "",
    page_footnotes_text: str = "",
) -> str:
    gr = (global_rules_text or "").strip()
    global_block = (
        "## 本指南全局规则（最高优先级——必须在任何候选节点分析前通读全文）\n"
        "以下规则适用于本指南的所有页面和所有患者，优先级高于任何单个节点内容。\n"
        "全局规则通常包含：疾病亚型的等价性声明（如某亚型与一般类型治疗方法相同）、"
        "特定药物在本疾病中的禁忌或特殊用法、操作时机的限制要求、以及方案一致性要求等。\n"
        "**必须逐条阅读，并在 `analysis` 开头明确列出哪些全局规则与当前患者相关、如何适用。不得跳过。**\n"
        f"{gr}\n\n"
    ) if gr else ""
    footnote_block = (
        "## 候选页面注脚原文（命中节点所在页的完整注脚；须通读并应用全部约束）\n"
        "注脚中包含对特定患者特征（年龄、合并症、既往治疗史等）的修饰规则、"
        "剂量调整条件、操作时机要求、以及方案一致性约束。与节点正文具有同等约束力。\n"
        f"{page_footnotes_text}\n\n"
    ) if (page_footnotes_text or "").strip() else ""
    return f"""你是临床指南路径匹配助手。在候选路径中选择最符合患者信息的节点。

**数值阈值**：引用节点数值时使用 `target_content` 的精确文字（如 "≥50 × 10⁹/L"），不得替换为近似值。

**【第一步——必须先通读全局规则和注脚，再分析候选节点】**
在评估任何候选节点之前，**必须先完整阅读上方「本指南全局规则」和「候选页面注脚原文」的全部内容**。
全局规则定义了适用于所有患者的疾病级别原则，往往包含关键信息（如：某疾病亚型与一般类型治疗等价性声明、某类药物在本疾病中的特殊用法、操作的时机要求等），这些内容不会出现在单个节点正文中，**必须主动从全局规则中检索**。
**在 `analysis` 开头，必须首先列出已阅读的全局规则和相关注脚，并说明哪些与当前患者直接相关**。如果某条全局规则或注脚直接回答了患者问题的某一方面，必须优先引用该规则/注脚，而非仅依赖候选节点内容。

**【多重禁忌交集分析——适用于所有问题类型】**
当患者同时存在多个会产生药物或操作禁忌的并发症/特征时，必须执行以下四步逻辑，**严禁跳过**：
① **列举禁用药物及程序性禁忌**：对每个条件单独列出其禁用的具体药物和操作。同时务必评估临床流程禁忌（例如：在存在严重凝血障碍或血小板极低时，禁止进行腰椎穿刺或其他侵入性操作；某类药物治疗后与后续特定操作之间存在必须遵守的安全时间间隔；对于可能引发大出血风险的操作，须明确捆绑要求的支持治疗措施等）。
② **合并禁用集合**：将所有条件的禁用药物与禁忌操作取并集，得到完整"禁用药物与禁忌操作集合"。
③ **逐节点扫描（含 "or" 并列方案节点的特殊处理）**：对每个候选终端节点（target_node），逐字扫描其 `content` 字段：
  - **若 content 以 "or"/"or a" 等词语明确分隔多个平行治疗选项**，须对每个 "or" 分支**分别独立**判断是否包含禁用项。**只要有任一 "or" 分支不含任何禁用药物和禁忌操作，该节点即为有效候选节点，不得整体排除**；应在 `matched_node_ids` 中包含该节点 id，并在 `analysis` 中明确说明哪些分支被排除、哪些分支适用。
  - **若 content 不含 "or" 分隔的并列独立选项**，该节点 content 包含至少一种禁用项时被排除，不含任何禁用项时为有效候选节点。
④ **交集结论**：若存在任何有效候选节点（包括经 "or" 分支分析后仍有可用分支的节点），则应返回 `match`，不得返回 `guideline_gap`。`guideline_gap` 仅在所有候选节点均确认无任何可用选项时才允许使用。
如果在分析中发现医生方案遗漏了关键的并发症预防或忽视了致命的程序性禁忌，必须在 `analysis` 中予以明确指正，并基于指南注脚等提供相应的安全说明。

**【剂量折减 vs Guideline Gap】**
如果患者遭遇严重毒性（例如高剂量阿糖胞苷导致的小脑毒性，或高龄/肾功能不全），在判定 `guideline_gap` 放弃当前指南路径之前，**务必优先检查注脚或全局规则中是否允许“剂量调整/折减”（Dose modification/adjustment）或暂时停药**。如果在当前路径体系内仅靠下调剂量（减量）就能合规，则应在 `analysis` 中指出减量建议，并继续保留原节点作为 `match`，严禁仅因遇到毒性且未见减量数字就判定 `guideline_gap` 或错误建议混搭别的研究方案。

**【多条件患者的分支覆盖规则】**
当患者同时满足多个分支的入口条件时，须将所有匹配分支的终端节点均纳入候选集后，再执行上述多重禁忌交集分析。不得仅因某一分支的多数节点被排除就放弃整个分支——该分支中仍可能存在不含任何禁用药物的安全节点。

**复发/难治性患者分析要求**：对于复发/难治性阶段的患者，必须在 `analysis` 的开头首先明确剖析患者进入当前特定前置路径的指南核心意图与用药原则（例如：早期复发通常提示对既往诱导方案中的核心药物产生耐药，故必须更换机制不同的药物、不能再重新暴露于原方案），随后再依据具体禁忌症排除当前路径下的不适用项，得出最终推荐方案。**对于"早期复发（< 6个月）"场景，`analysis` 中必须显式解释**：① 早期复发在药理学上提示对原方案核心药物（如ATO）存在耐药或获益不确定性；② 因此该药物必须被排除，须说明机制理由（"< 6个月的早期复发意味着继续使用该药物疗效不确定或存在耐药可能"），不能仅以"根据指南不推荐"一笔带过；③ 说明当前替代方案是合理的机制替代。

**【防迎合强行找错——评估性问句最高优先级保护】**
当问句含「请指出错误」「是否正确」「请评估」「指出其中的致命错误」等措辞时，**必须严格按以下步骤执行，不得跳过**：
① 先不管问句措辞，对医生方案的每一条举措单独对照候选节点、注脚和全局规则进行独立核查；
② **如果核查结果显示医生方案的所有条目均符合指南**：`decision_type` **必须为 `match`**（绝对禁止改为 `guideline_gap`）；`analysis` 必须明确、肯定地说明「经核查，医生的方案完全符合指南推荐，无需修改」并逐条引用指南依据；**不得捏造「偏差」「不足」或「细微错误」**；
③ **如果核查确实发现具体条目不符合指南节点/注脚/全局规则原文**，才在 `analysis` 中引用精确原文指出错误；
④ 严禁使用「指南未明确规定」「理论上存在偏差」「未明确说明某细节」等语句为并不存在的错误辩护；
⑤ **严禁因问句含「指出错误」就返回 `guideline_gap`**——`guideline_gap` 仅在指南中确实找不到任何匹配节点时使用；绝对不能仅因「需要找错」而选择 `guideline_gap`。

**评估性问句**（叙述含「评估/是否正确/指出错误」等）：找出指南正确路径节点用于比对；`analysis` 依据候选节点内容**及页面注脚/全局规则（须精确引用原文片段）**作判断；节点、注脚与全局规则均未覆盖的方面须注明「未覆盖，无法评估」；禁止从叙述句序推断操作先后顺序；等价表述不构成临床偏差。**若医生方案完全脱离指南所有推荐分支（如使用了指南中任何分支均未包含的药物组合），须在 `analysis` 中引用全局规则或注脚中关于该疾病必须使用特定治疗原则的原文（如适用），以说明该方案偏离指南基本要求的依据。在给出正确方案时，必须同时分析与其处于同等地位但被排除的「其他指南备选方案/分支」，明确指出它们因何种先决条件而在当前患者身上不可用或被排除，详述其被排除的临床逻辑。**

**【并列方案数值匹配优先级】**（评估性问句涉及具体用药数值时）：若患者叙述中医生方案包含具体数值参数（如某药物剂量、给药频率/时间表），且同一指南页面存在多个并列方案候选节点时，**优先将 `content` 与医生方案数值参数完全匹配的节点纳入 `matched_node_ids`** 作为评估基准。只有在不存在数值完全匹配的节点时，才选取最接近的节点并在 `analysis` 中注明差异。不得仅因某节点排序靠前或被认为是「首选」而忽略与医生方案数值完全匹配的并列节点。

**【操作时序与前提条件合规性检查】**（评估性问句涉及已执行操作时）：当患者叙述包含医生**已执行的具体操作**，须**首先检查该操作本身是否符合指南规定的时序或前提条件要求**，再评估其结果处理：
- 许多指南会在注脚或正文中规定某类操作的执行时机（如「须在血细胞计数恢复后」「须在某治疗完成至少N周后」「须在凝血功能纠正且疾病缓解后」「须在首次完全缓解后、下一阶段治疗前」等），若实际执行时机不满足这些前提，**该操作本身即为违规**，须在 `analysis` 中明确指出。
- 同时须解释早于规定时机执行该操作的风险（例如：在特定治疗机制下，早期评估结果可能具有误导性，容易导致假阴性/假阳性判断，进而引发不必要的方案更改）。
- **操作时机违规与结果处理相互独立**：不得因后续节点存在「若结果为X则如何处理」的规则，而对时机本身违规的操作默许或背书——结果处理规则仅规范结果发生后的处置逻辑，不对违规时机进行事后授权。
- **负面规则检查（操作禁忌）**：若患者信息中包含某项操作，须检查全局规则和注脚中是否存在明确禁止或不推荐该操作的规定（负面规则往往不在节点正文中，而在注脚或全局规则中）；发现负面规则时必须在 `analysis` 中明确指出。注意：「不推荐常规在诊断时进行某操作」「不常规推荐某处置方式」等表述同样是负面规则。

**【多步骤不良事件处理流程完整性】**
若指南规定了某类不良事件的阶梯式处理流程（先纠正可逆因素、再复查、最后才升级/停药），须完整呈现所有步骤。在涉及药物毒性管理时，须同时核查：① 是否已优化可逆因素（电解质、合并用药等）；② 是否已在优化后复查相关指标；③ 是否在优化无效后才升级处置（如暂停药物）。暂时性中断与永久停药是不同概念，须严格区分。

**幻觉防护**：`analysis` 中所有「指南规定/推荐/要求X」的陈述，必须能在①候选节点 `target_content`，②全局规则/注脚原文，或③通用医学实践（须明确标注「基于通用临床实践，非本指南节点原文」）中找到依据；若无任何依据，注明「节点未覆盖此项，无法评估」，不得凭推断补充。禁止从叙述句序推断操作先后顺序并将其列为错误（等价表述不构成临床偏差）。

**条件性节点**：含 "if included"/"may be given"/"if applicable" 等短语时仅在条件满足时适用，非绝对要求（直接进入监测期不是错误）。

**诊断确认**：临床/形态学已高度明确时即满足「Confirmed 诊断」条件，不得因基因结果待回而返回 guideline_gap。若叙述经历「初步疑诊 → 后续基因排除」两阶段，须在 `speculative_note` 中分阶段评估各阶段操作，引用注脚/全局规则对比两种诊断情境下相反的指南规则，并写明诊断变更后应停用并转为替代方案。

**注脚约束**：下方「候选页面注脚原文」是命中节点所在指南页的完整注脚，须通读并直接应用所有约束：节点内容中出现的上标（如 `<sup>g</sup>`）对应同字母注脚；若患者特征（年龄、合并症等）满足注脚的调整条件，必须在 `analysis` 中明确写出；若注脚要求跨阶段方案一致性（如 "use the regimen consistently through all components"），须据此检验跨阶段候选节点是否同属同一路径分支，不同分支的诱导与巩固方案不得混搭。

**【年龄/肾功能条件性剂量变体强制核查】** 若候选节点 `content` 中含有针对不同年龄段或肾功能的剂量变体（如 "for those aged >70 y"、"age 50–60 y"、"aged >60 y"、"patients >60 years or patients with renal dysfunction" 等），**必须**：① 逐一列出节点中所有年龄/肾功能阈值；② 将患者实际年龄与肾功能状态和每个阈值明确比较；③ 应用适合该患者的折减变体，而非默认成人标准剂量；④ 若医生方案使用了不适用于该年龄段或肾功能状态的剂量，须在 `analysis` 中以错误明确指出并给出正确变体。此核查优先级不低于主要药物禁忌检查。

## 决策类型（三选一）
1. **match**：有符合的候选节点；选最具体的叶子；并列方案可同时返回多个 id，说明为平行选项非序贯；多阶段问题须覆盖所有相关阶段的节点。
2. **insufficient**：信息不足；需要医生补充 entry_condition。
   - **强制核对方法（不得跳过）**：遍历所有候选路径节点（含 matched 节点上游已走过节点）的 `entry_conditions` 数组，对每一项 `entry_condition.symbol` 都必须在 `analysis` 中显式核对一次：患者描述中是否给出该事实的取值？给出则跳过；未给出（或患者文本中未提及）则纳入 missing。**不得仅凭患者主诉看似"完整"就跳过此核对**。
   - **抽取来源**：仅从 `entry_conditions` 中取 `key/symbol`；这些 entry_conditions 是机器可求值的客观事实或医生决策意向（如 BRCA 状态、Oncotype 评分、ECOG、心脏功能、是否考虑术前全身治疗、患者是否选择保乳等）——只要患者描述没明确给出取值，都视为 missing 抛给医生。
   - **决策意向也算 missing**：若某 entry_condition 描述的是医生治疗意向（如 `considering_preop_systemic_therapy`、`planned_for_BCS`），且患者描述没提及医生计划，**应当**写入 missing。
   - **禁止抽取**：单纯的路径下游"治疗方案标签"（如节点 title 仅是 "BCS"、"Mastectomy"、"Whole breast RT" 而无对应 entry_condition.symbol）不要硬造成 missing；仅当某项被建图为 entry_condition.symbol 时才纳入。
   - **decision_type 判断顺序**：先做上述强制核对 → 若有任意 missing → 必须返回 `insufficient`；只有 0 missing 时才能返回 `match`。
3. **guideline_gap**：在完成上述「多重禁忌交集分析」四步骤后，若所有候选终端节点（含逐一检查每个 "or" 分支后）均无任何可用选项，才可返回此类型；`matched_node_ids = []`；禁止用于评估性问句或仅信息不足时；**禁止仅因某一分支被整体排除、而未逐一扫描其他分支（或同一节点内其他 "or" 选项）就返回此类型**。`speculative_note` 须逐项解答（含评估性问句的各项操作评价，引用注脚/全局规则原文佐证），若有多子问题须逐一作答并标明「非指南原文、仅为推测性讨论」。

## `clarify_markdown` 写作规范（**直接呈现给医生，不再二次加工**）

请用**自然流畅的中文**写一份完整 Markdown，通常含两个章节；若「患者信息」含 `[前端结构化输入]` 与 `[医生填写原文]` 两段且在**关键事实（性别、年龄、明确诊断/分期）** 上明显互斥，开头插入 `## 信息冲突提示` 章节：编号列出每条冲突（`**字段**: 结构化=X，原文=Y，请确认`），末尾一句 `如需修改结构化字段请返回上一步，否则以医生原文为准。` 字段缺失不算冲突，走"仍需澄清"。

### `## 已掌握信息`
- 综合患者原始描述 + 已抽取信息，按"基本信息 / 主诊断与分期 / 病理与基因 / 现病史与症状 / 既往与用药 / 家族史"等业务逻辑归纳；每条 `- **<标题>**: <自然语句>`。
- 若患者原文是英文，**翻译成中文**呈现给医生看，但保留关键英文术语（如 BRCA2 carrier、cT2 cN+ M0、ER-positive、HER2-negative）。
- 不要逐字段机械列表，要像医生写病历摘要一样可读。

### `## 仍需澄清`
- 用编号列表 `1. 2. 3. ...` 列出每条 missing 项；
- 每条 = 一句问句 + 一句简短理由（括号内告诉医生：**为什么要问**、**补全后能解锁什么**）；
- **指南来源标注**：
  - 若所有 missing 项**整体来自同一份指南**，**不要**在每条括号内重复提，只在编号列表后用一句话整体标注（例如：`以上各项均参考 NCCN 乳腺癌指南。`）；
  - 若各项来自不同指南，则在各条括号末附 `(来自 <指南名>)`；
  - **禁止写**"来自节点 XXX" / page_code / 节点 title 这种内部细节，只给医生看得懂的指南名称。
- **同一 symbol 只写 1 次**；
- 全部输出末尾紧跟 1 句平铺文字告诉医生：按编号直接续写即可，未掌握的写"不详"。
- 若属于"主指南限定的诊断必要事实尚未明确"（例如未知病理亚型、未做关键分型检测、患者根本未确诊），应措辞为"为明确诊断需补这些检查"，而不是"为选择治疗方案需补这些"。

**整体规范**：
- 只输出 `## 信息冲突提示`（可选）+ `## 已掌握信息` + `## 仍需澄清`；不要加 `## 怎么补充` / `## 下一步` / `## 备注`；
- 不写诊断结论、不写治疗建议、不写 `[citation:xx]`；
- 直接输出 Markdown 正文，不要 ```markdown 代码块，不要前置/结尾寒暄。
- 当 `decision_type = match` 时，`## 仍需澄清` 段写"指南所需关键事实已齐备，无需补充。"
- 当 `decision_type = guideline_gap` 时，`clarify_markdown` 留空字符串（由上层走 no_graph 兜底）。

**`target_incoming_edge_rule`**：进入目标节点的决定性边条件，是区分平行路径的首要依据；当多条路径 `entry_conditions` 相同时，优先用此字段区分（如 "No cardiac issues" vs "Cardiac issues"）。

{footnote_block}{global_block}## 患者信息
{patient_text}

## 候选路径

`node_registry`：以 node_id 字符串为 key，存放节点 title、page_id；目标节点额外含 content（最多 600 字符）和 entry_conditions。
`paths`：每条含 target_node_id、target_incoming_edge_rule（进入目标节点的决定性边条件）、route（node_id + via 出边标签序列，末项 via 为空）。

```json
{json.dumps({"node_registry": node_registry, "paths": paths}, ensure_ascii=False)}
```

## 条件维度提示
```json
{json.dumps(condition_hints[:120], ensure_ascii=False)}
```
"""


def _load_file_graph(file_id: int, guideline_id: int | None = None) -> dict:
    """Load graph data for a file from ES via guidance_db."""
    if guideline_id is not None:
        target_data = guidance_db.get_guideline_doc(guideline_id)
    else:
        target_data = None
        for doc in guidance_db._scan_all_guidelines():
            if any(f.get("id") == file_id for f in doc.get("files", [])):
                target_data = doc
                break

    if not target_data:
        return {
            "pages": [], "nodes": [], "edges": [],
            "links": [], "entry_conditions": [],
            "footnote_texts_by_anchor": {},
        }

    pages = []
    for p in target_data.get("pages", []):
        if p.get("file_id") == file_id:
            pages.append((p["id"], p["page_number"], p.get("code"), p.get("is_entry")))

    page_ids = {p[0] for p in pages}

    nodes = []
    for n in target_data.get("nodes", []):
        if n.get("page_id") in page_ids:
            nodes.append((
                n["id"], n["page_id"], n.get("title"), n.get("content"),
                n.get("is_entry"), n.get("is_end"), n.get("care_phase_id"),
            ))

    node_ids = {n[0] for n in nodes}

    edges = []
    for e in target_data.get("edge_rules", []):
        if e.get("source_node_id") in node_ids:
            edges.append((e["id"], e["source_node_id"], e["target_node_id"], e.get("rule_text")))

    links = []
    for lnk in target_data.get("page_links", []):
        if lnk.get("source_page_id") in page_ids:
            links.append((lnk["source_page_id"], lnk["target_page_id"]))

    entry_conditions = []
    for c in target_data.get("node_entry_conditions", []):
        if c.get("node_id") in node_ids:
            entry_conditions.append((
                c["node_id"], c.get("symbol"), c.get("condition_text"),
                c.get("condition_type"), c.get("value_type"),
                c.get("operator"), c.get("threshold_value"),
            ))

    _pid_to_code = {
        int(p.get("id", 0)): (p.get("code") or "").strip()
        for p in target_data.get("pages", [])
    }
    footnote_texts_by_anchor: dict[str, str] = {}
    for p in target_data.get("pages", []):
        if p.get("page_type") == "footnote":
            anchor_id = p.get("anchor_page_id")
            anchor = _pid_to_code.get(int(anchor_id), "").strip() if anchor_id is not None else ""
            raw = (p.get("raw_text") or "").strip()
            if anchor and raw:
                footnote_texts_by_anchor[anchor] = raw

    return {
        "pages": pages,
        "nodes": nodes,
        "edges": edges,
        "links": links,
        "entry_conditions": entry_conditions,
        "footnote_texts_by_anchor": footnote_texts_by_anchor,
    }


def _build_reverse_graph(
    graph_data: dict,
    entry_page_id: int,
) -> tuple[dict, dict, set[int], dict]:
    node_by_id = {}
    entry_conditions_by_node: dict[int, list[dict]] = defaultdict(list)
    for r in graph_data.get("entry_conditions", []):
        node_id = int(r[0])
        entry_conditions_by_node[node_id].append({
            "symbol": (r[1] or "").strip(),
            "condition_text": (r[2] or "").strip(),
            "condition_type": (r[3] or "").strip().lower(),
            "value_type": (r[4] or "").strip(),
            "operator": (r[5] or "").strip(),
            "threshold_value": (r[6] or "").strip(),
        })

    nodes_by_page: dict[int, list[int]] = defaultdict(list)
    for r in graph_data["nodes"]:
        nid, pid = int(r[0]), int(r[1])
        node_by_id[nid] = {
            "id": nid,
            "page_id": pid,
            "title": (r[2] or "").strip(),
            "content": (r[3] or "").strip(),
            "is_entry": bool(r[4]),
            "is_end": bool(r[5]),
            "care_phase_id": r[6],
            "entry_conditions": entry_conditions_by_node.get(nid, []),
        }
        nodes_by_page[pid].append(nid)

    out_adj: dict[int, list[tuple[int, str]]] = defaultdict(list)
    in_deg: dict[int, int] = defaultdict(int)
    out_deg: dict[int, int] = defaultdict(int)
    for _, src, tgt, rule_text in graph_data["edges"]:
        s, t = int(src), int(tgt)
        out_adj[s].append((t, (rule_text or "").strip()))
        in_deg[t] += 1
        out_deg[s] += 1

    # page_link 仅作为兜底：当某源节点没有任何真实出边时，才补跨页启发式边。
    for src_page_id, tgt_page_id in graph_data["links"]:
        src_page_id = int(src_page_id)
        tgt_page_id = int(tgt_page_id)
        src_nodes = nodes_by_page.get(src_page_id, [])
        tgt_nodes = nodes_by_page.get(tgt_page_id, [])
        if not src_nodes or not tgt_nodes:
            continue
        src_terminals = [nid for nid in src_nodes if out_deg.get(nid, 0) == 0]
        if not src_terminals:
            continue
        tgt_entries = [nid for nid in tgt_nodes if node_by_id[nid]["is_entry"]]
        tgt_entries = tgt_entries or [nid for nid in tgt_nodes if in_deg.get(nid, 0) == 0] or tgt_nodes
        for s in src_terminals:
            for t in tgt_entries:
                out_adj[s].append((t, f"cross_page:{src_page_id}->{tgt_page_id}"))

    rev_adj: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for src, items in out_adj.items():
        for tgt, label in items:
            rev_adj[tgt].append((src, label))

    root_nodes = {nid for nid in nodes_by_page.get(entry_page_id, []) if node_by_id[nid]["is_entry"]}
    root_nodes = root_nodes or set(nodes_by_page.get(entry_page_id, []))
    return node_by_id, rev_adj, root_nodes, out_adj


_REVERSE_BFS_STACK_BUDGET = 5000  # 单 target 最多扩展 N 个 stack 节点; 防网状大图谱指数爆炸


def _reverse_paths_to_root(
    target_node_id: int,
    rev_adj: dict[int, list[tuple[int, str]]],
    root_nodes: set[int],
    max_paths: int,
    max_depth: int,
) -> list[list[tuple[int, str]]]:
    found: list[list[tuple[int, str]]] = []
    stack: list[tuple[int, list[tuple[int, str]], set[int]]] = [(target_node_id, [(target_node_id, "")], {target_node_id})]
    expanded = 0
    while stack and len(found) < max_paths:
        if expanded > _REVERSE_BFS_STACK_BUDGET:
            break
        cur, path, seen = stack.pop()
        expanded += 1
        if cur in root_nodes:
            found.append(list(reversed(path)))
            continue
        if len(path) >= max_depth:
            continue
        for prev, edge_label in rev_adj.get(cur, []):
            if prev in seen:
                continue
            stack.append((prev, path + [(prev, edge_label)], seen | {prev}))
    return found


def _build_post_page_subgraph(
    graph_data: dict,
    node_by_id: dict[int, dict],
    matched_nodes: list[dict],
) -> dict:
    pages = graph_data.get("pages") or []
    nodes = graph_data.get("nodes") or []
    links = graph_data.get("links") or []
    edges = graph_data.get("edges") or []

    page_meta: dict[int, dict] = {}
    for row in pages:
        pid = int(row[0])
        page_meta[pid] = {
            "page_id": pid,
            "page_number": int(row[1]),
            "code": (row[2] or "").strip(),
            "is_entry": bool(row[3]),
        }

    titles_by_page: dict[int, list[str]] = defaultdict(list)
    for row in nodes:
        pid = int(row[1])
        title = (row[2] or "").strip()
        if title and title not in titles_by_page[pid]:
            titles_by_page[pid].append(title)

    page_adj: dict[int, set[int]] = defaultdict(set)
    edge_reason: dict[tuple[int, int], set[str]] = defaultdict(set)
    for src_page, tgt_page in links:
        s = int(src_page)
        t = int(tgt_page)
        if s == t:
            continue
        page_adj[s].add(t)
        edge_reason[(s, t)].add("page_link")

    for _, src_nid, tgt_nid, _rule_text in edges:
        src_page = node_by_id.get(int(src_nid), {}).get("page_id")
        tgt_page = node_by_id.get(int(tgt_nid), {}).get("page_id")
        if src_page is None or tgt_page is None or int(src_page) == int(tgt_page):
            continue
        s = int(src_page)
        t = int(tgt_page)
        page_adj[s].add(t)
        edge_reason[(s, t)].add("node_flow")

    start_pages = {
        int(n.get("page_id"))
        for n in matched_nodes
        if n.get("page_id") is not None
    }
    if not start_pages:
        return {"mermaid": "graph TD\n", "pages": []}

    reachable: set[int] = set()
    stack: list[int] = list(start_pages)
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        for nxt in page_adj.get(cur, set()):
            if nxt not in reachable:
                stack.append(nxt)

    visible_pages = [pid for pid in reachable if pid in page_meta]
    visible_pages.sort(key=lambda x: (page_meta[x]["page_number"], x))

    mermaid_lines = ["graph TD"]
    for pid in visible_pages:
        m = page_meta[pid]
        label = f"P{m['page_number']}"
        if m["code"]:
            label = f"{label} {m['code']}"
        label = label.replace('"', "'")
        mermaid_lines.append(f'PG{pid}["{label}"]')

    for s in visible_pages:
        for t in sorted(page_adj.get(s, set())):
            if t not in reachable:
                continue
            reasons = "/".join(sorted(edge_reason.get((s, t), {"flow"})))
            mermaid_lines.append(f'PG{s} -->|{reasons}| PG{t}')

    pages_payload = []
    for pid in visible_pages:
        m = page_meta[pid]
        pages_payload.append({
            "page_id": pid,
            "page_number": m["page_number"],
            "code": m["code"],
            "is_start_page": pid in start_pages,
            "top_node_titles": titles_by_page.get(pid, [])[:6],
        })

    return {"mermaid": "\n".join(mermaid_lines), "pages": pages_payload}


def _build_post_chain_prompt(
    patient_text: str,
    decision_type: str,
    matched_nodes: list[dict],
    page_mermaid: str,
    page_payload: list[dict],
    base_analysis: str,
    base_speculative_note: str,
    global_rules_text: str = "",
    sibling_context_nodes: list[dict] | None = None,
) -> str:
    gr = (global_rules_text or "").strip()
    global_block = ""
    if gr:
        global_block = (
            "## 本指南各页全局规则（最高优先级——必须在任何复核分析前通读全文）\n"
            "以下规则适用于本指南的所有页面和所有患者，优先级高于任何单个节点内容。\n"
            "全局规则通常包含疾病亚型的等价性声明、特定药物禁忌、操作时机要求等重要原则。\n"
            "**必须逐条阅读，并在 `analysis` 中明确引用与当前患者相关的全局规则。**\n"
            f"{gr}\n\n"
        )
    sibling_block = ""
    if sibling_context_nodes:
        _sibling_json = json.dumps(sibling_context_nodes, ensure_ascii=False)
        sibling_block = (
            "\n## 同页并列方案节点（未选中；用于识别数值混淆陷阱）\n"
            "以下节点与已命中节点位于同一指南页面，是该治疗阶段的并列方案（未被第一轮选中）。"
            "评估时若发现医生方案数值与此处某节点相同但使用语境不同，须在 `analysis` 中说明数值来源与混淆原因。\n"
            "```json\n" + _sibling_json + "\n```\n"
        )
    return f"""你是临床指南分析助手。下面已有第一轮路径判定结果，请基于「命中节点所在页及其后续 page 子图」做一轮复核分析。

要求：
0. **【第一步——必须先通读全局规则，再复核分析】**
在任何复核分析之前，**必须先完整阅读上方「本指南各页全局规则」的所有内容**（如有）。全局规则定义了适用于全部患者的疾病级别原则，往往包含关键的等价性声明、药物适用范围限制、操作时机要求等，这些内容不会出现在单个节点中。**若全局规则直接回答了患者问题的某一方面，必须在 `analysis` 中明确引用，不得仅依赖 page 子图节点内容**。
1. 不得改写 decision_type 与 matched_node_ids。若第一轮 analysis 存在无节点原文依据的推断性错误（如凭句序推断操作顺序），**必须予以纠正**；本轮以 page 子图节点内容为最终依据，覆盖第一轮结论。**【操作时序独立性保护】**：若第一轮 analysis 发现某操作本身的执行时机不符合指南前提条件（如在要求的前提条件满足之前过早进行了某项评估操作），该时机违规判断属于独立事实判断，**不可**仅因后续 page 子图中存在描述该操作结果处理方式的节点而将其撤回——结果处理节点仅规范结果处置逻辑，不对违规时机进行事后授权，两者相互独立；纠正时须同时保留时机违规说明和结果处置建议，不得以后者替代前者。
2. **幻觉防护**：所有「指南规定X」或「指南推荐X」的陈述须在 page 子图内容、全局规则或下方并列节点中有精确字面依据；若无依据，注明「当前节点未覆盖此项，无法基于本指南评估」。条件性节点（含 "if included" 等）仅在条件满足时适用；对初始方案未含维持治疗的患者，进入监测期不是错误。
3. **【严禁主动推翻正确临床安全原则】** 本规则优先级高于"幻觉防护"：若第一轮 analysis 基于通用临床医学实践或注脚给出了正确的安全原则（例如：存在严重凝血功能障碍时禁止腰椎穿刺等有创操作；须在疾病缓解且凝血功能正常后才进行筛查性腰穿；某类药物治疗后须等待足够时间后才能进行特定后续操作等），即使当前节点正文未包含该陈述的**精确字面**，**绝对禁止**将其标注为「推断性错误」并予以撤回。正确处理方式：在 `analysis` 中**保留**该安全原则，并加注「该原则基于通用临床实践，非本指南当前节点原文，建议参考相关支持治疗原则及指南」。**【例外——指南注脚已为该患者群体明确提供低剂量替代方案时】** 若第一轮 analysis 将某药物的严重毒性判定为永久停药适应症，但指南注脚已为该患者群体（年龄、肾功能等）明确规定了低剂量替代方案，且该低剂量方案在设计上不会达到毒性剂量级别，则本轮**应优先推荐该低剂量替代方案**，而非维持永久停药结论。推荐低剂量替代方案不构成"推翻临床安全原则"，不受本条限制。
4. **评估性问句**：依据 page 子图节点内容**及全局规则/注脚（须精确引用原文片段）**作判断；子图与注脚均未覆盖的方面须逐项注明「无法基于现有节点评估」；禁止强行制造偏差，禁止从叙述句序推断操作先后顺序，等价表述不构成临床偏差；若医生计划在节点覆盖范围内完全正确，直接写明并逐条引用精确内容。**若医生方案完全脱离指南所有推荐分支，须引用页面注脚或全局规则中关于该疾病必须维持特定治疗基础的原文（如适用）**，以说明违背指南基本要求的具体依据。在说明为何选择最佳方案时，须详细说明为何指南当页的其他「备选方案分支/用药组合」不适用于该患者，指明其被排除的临床逻辑。
5. **复发/难治性患者分析要求**：必须在 `analysis` 的开头首先明确剖析患者进入当前特定前置路径的指南核心意图与用药原则（早期复发通常提示对既往诱导方案中的核心药物产生耐药，故必须全面更换机制不同的药物，不能再重新暴露于任何原方案中的核心药物），随后再依据具体禁忌症排除当前路径下的不适用项，得出最终推荐方案。**早期复发（<6个月）场景中，须在 `analysis` 中显式说明**：① 早期复发在药理学上提示对原核心药物存在耐药或获益不确定性；② 明确指出因此不能重新使用原核心药物，并说明机制理由而非仅引用指南条文；③ 当前替代方案为何是合理的机制替代。
6. **数值/方案混淆陷阱**（评估性问句）：检查下方「同页并列方案节点」是否有节点包含与医生方案相同的数值但属于不同给药语境；若有，须在 `analysis` 中明确数值的正确来源、医生混淆语境的具体错误，以及正确方案（含精确剂量与时间表）。**【须先排除合法并列方案匹配】**：在报告混淆错误前，须先判断医生方案的数值是否直接来源于某并列节点的完整方案——若医生方案与该并列节点在全部关键参数上自洽，则应认定为合法并列方案选择，不得强行报告数值混淆。
7. **支持治疗数值逐项核查**：若评估涉及凝血支持、电解质管理或特定药物监测，须对相关节点中**每一条**具体数值标准**逐条**核查医生描述与指南的偏差，不得在发现首个匹配项后停止扫描。**若节点 `content` 包含年龄或肾功能分组剂量变体（如 ">70 y"、">60 y" 等），须逐一列出所有阈值、与患者实际年龄/肾功能比较，并应用适用该患者的变体；若医生方案使用了错误剂量变体须明确指出。**
8. **【阶梯式不良事件处理流程完整性】** 若指南注脚或节点中规定了某类不良事件的阶梯式处理流程，须完整呈现所有步骤及其顺序，不得仅呈现最后一步（如直接永久停药）而跳过前置干预步骤。处理流程中的暂时性中断与永久停药是不同概念，须严格区分。
9. **【药物毒性与剂量层级】** 若涉及某药物引发的严重毒性，须明确：① 该具体剂量/方案对该患者的禁忌范围；② 若禁忌仅针对特定剂量级别，在当前方案路径内的减量/调整方案（须引用注脚的调整条件）在无其他禁忌时仍为合规选项；③ 更换至完全不同路径须检查指南的方案一致性要求。**【剂量分级区分——不得将高剂量毒性等同于全剂量永久禁忌】** 若毒性事件发生于特定高剂量级别（例如高剂量阿糖胞苷 ≥2 g/m²），而指南注脚为该患者特征（年龄 >60 岁、肾功能不全等）提供了更低剂量的替代方案（如 1 g/m²），则该低剂量替代方案在原方案路径内仍属合规选项，不得仅凭高剂量毒性史宣判该药物在任何剂量下均永久禁用。"永久停药"仅适用于毒性在注脚允许的最低剂量下仍无法规避的情形。
10. **【治疗与后续操作的时间安全间隔】** 若患者使用过某类已知与后续操作存在时间冲突的药物或治疗，且后续计划包含该操作，须在 `analysis` 中以**主要结论**明确警告相关的时间安全间隔要求。此警告须作为主要结论而非 speculative_note，即便当前页面节点原文未明确写出该间隔。
11. speculative_note 仅在必要时给出，须标明「非指南原文、仅为推测性讨论」。
{global_block}## 患者信息
{patient_text}

## 第一轮结果（仅供参考）
```json
{json.dumps({
    "decision_type": decision_type,
    "matched_nodes": matched_nodes,
    "analysis": base_analysis,
    "speculative_note": base_speculative_note,
}, ensure_ascii=False)}
```

## page 子图（Mermaid）
```mermaid
{page_mermaid}
```

## page 维度补充数据
```json
{json.dumps(page_payload, ensure_ascii=False)}
```
{sibling_block}"""


def _build_condition_hints(guideline_id: int) -> list[dict]:
    """Build condition dimension hints from ES via guidance_db."""
    data = guidance_db.get_guideline_doc(guideline_id)
    if not data:
        return []

    edge_hints: list[dict] = []
    seen: set[str] = set()
    for r in sorted(data.get("conditions", []), key=lambda x: x.get("id", 0)):
        symbol = (r.get("symbol") or "").strip()
        if symbol and symbol not in seen:
            seen.add(symbol)
            edge_hints.append({
                "key": symbol,
                "condition_text": r.get("condition_text", ""),
                "value_type": r.get("value_type", ""),
                "operator": r.get("operator", ""),
                "threshold_value": r.get("threshold_value", ""),
                "source": "edge",
            })

    entry_hints: list[dict] = []
    seen = set()
    for r in sorted(data.get("node_entry_conditions", []), key=lambda x: x.get("id", 0)):
        symbol = (r.get("symbol") or "").strip()
        if symbol and symbol not in seen:
            seen.add(symbol)
            entry_hints.append({
                "key": symbol,
                "condition_text": r.get("condition_text", ""),
                "value_type": r.get("value_type", ""),
                "operator": r.get("operator", ""),
                "threshold_value": r.get("threshold_value", ""),
                "source": "entry_node",
            })

    merged: dict[str, dict] = {}
    for h in edge_hints + entry_hints:
        if h["key"] not in merged:
            merged[h["key"]] = h
    return list(merged.values())


async def _ask_entry(patient_text: str, entry_pages: list[dict]) -> int | None:
    """多入口图谱场景:让 LLM 在多个独立入口里挑跟患者最匹配的一个。

    entry_pages: [{id, code, page_number, summary_text}] (来自 guidance_db.list_entry_pages)
    返回选中的 page_id;若失败 / 唯一候选 / 无候选则按 fallback 处理。
    """
    if not entry_pages:
        return None
    if len(entry_pages) == 1:
        return int(entry_pages[0]["id"])

    lines = []
    for i, p in enumerate(entry_pages, 1):
        summary = (p.get("summary_text") or "").replace("\n", " ")[:500]
        lines.append(f"{i}. [{p.get('code','')}] {summary}")

    prompt = (
        "你是临床指南分诊助手。一份指南可能含多个独立入口路径,"
        "请基于患者描述选出最匹配的入口。\n\n"
        f"## 患者描述\n{patient_text}\n\n## 候选入口\n" + "\n".join(lines)
        + "\n\n输出 JSON: {\"choice\": <数字>}。"
    )
    llm = Gemini35Flash()
    try:
        content = await llm(
            user_prompt=prompt,
            response_mime_type="application/json",
            response_schema={"type": "object", "properties": {"choice": {"type": "integer"}}, "required": ["choice"]},
            thinking_budget="low",
        )
        j = json.loads((content or "").strip() or "{}")
        idx = int(j.get("choice", 1))
        if 1 <= idx <= len(entry_pages):
            return int(entry_pages[idx - 1]["id"])
    except Exception:
        logger.exception("[_ask_entry] LLM choice failed, fallback to first entry")
    return int(entry_pages[0]["id"])


async def _ask_phase(patient_text: str, phases: list[dict], guideline_name: str = "") -> dict:
    prompt = _build_phase_prompt(patient_text, phases, guideline_name=guideline_name)
    logger.debug("[_ask_phase] prompt (len=%d):\n%s", len(prompt), prompt)
    llm = Gemini31Pro()
    content = await llm(
        user_prompt=prompt,
        temperature=0.1,
        response_mime_type="application/json",
        response_schema=PHASE_DECISION_SCHEMA,
        thinking_budget="low",
    )
    logger.debug("[_ask_phase] raw response: %s", content)
    try:
        return json.loads((content or "").strip() or "{}")
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════════
# 轻量澄清专用 (clarify) — 独立于主报告的 path_select
#
# 设计:
#   - 只看 "当前可达节点 + 它们的 entry_conditions",不塞整本指南脚注
#   - prompt 1-2K 指令 + 5-15K 数据,不超过 30K
#   - 一次 LLM 调用,Flash 模型够用,目标 5-15s
#   - 输出包含完整 markdown,直接给前端
# ══════════════════════════════════════════════════════════════════════

CLARIFY_LITE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "decision_type": {
            "type": "STRING",
            "description": "match | insufficient",
        },
        "matched_node_ids": {
            "type": "ARRAY",
            "items": {"type": "INTEGER"},
            "description": "患者当前确定到达的节点 id; insufficient 时可空数组",
        },
        "clarify_markdown": {
            "type": "STRING",
            "description": "完整给医生看的 Markdown,含 ## 已掌握信息 + ## 仍需澄清 两段",
        },
    },
    "required": ["decision_type", "matched_node_ids", "clarify_markdown"],
}


def _build_clarify_lite_prompt(
    patient_text: str,
    guideline_name: str,
    current_nodes: list[dict],
    candidate_next_nodes: list[dict],
) -> str:
    """轻量澄清 prompt — 当前位置 + 一阶下游 节点 title。
    注意: 节点 entry_conditions (cT/cN/M 等"期望值") 是图谱内部的判断逻辑,
    不是医生原文已确认的事实。如果把它们喂给 LLM, LLM 会误把这些临床判断
    抄进"已掌握信息" → 编造。因此本 prompt 只暴露 node title (用于定位),
    不暴露 entry_conditions。
    """
    cur_block = [f"- 节点 id={n.get('node_id')} [{(n.get('title') or '').strip()}]" for n in current_nodes]
    nxt_block = [f"- 节点 id={n.get('node_id')} [{(n.get('title') or '').strip()}]" for n in candidate_next_nodes]

    return f"""你是临床决策树定位助手。在指南决策树上定位患者当前位置,并告诉医生还缺什么。

# 患者信息
{patient_text}

# 指南
{guideline_name}

# 当前可达节点(后台定位用,**禁止**反推任何临床事实写进"已掌握信息")
{chr(10).join(cur_block) if cur_block else "(无)"}

# 下一步候选节点(后台定位用,**禁止**反推任何临床事实写进"已掌握信息")
{chr(10).join(nxt_block) if nxt_block else "(无)"}

# 输出
第 1 行必须是 `MATCHED:<逗号分隔的 node_id>`,选 1-3 个患者当前真正停留的节点(下游还有未明确分支的判断点),已走过或不会到达的不选。
第 2 行起是 markdown 正文,含且仅含两个章节:

## 已掌握信息
- **只复述**医生原始描述里已经写明的内容,一项一行,用顺畅的中文重写。
- **严禁**添加原文未出现的临床判断(分期 M0/cT/cN、分型、可手术/绝经/转移等状态、阴/阳性结论、"未/非/无……" 否定补全);原文没说的就什么都不写。
- **禁止**因为看到上方节点 title(如 `[BCS ± surgical axillary staging]`) 就反推患者"可手术"等临床事实。

## 仍需澄清
- 用编号列表 `1. 2. 3.` 列出需要医生补充的关键判断点。
- 每条 = 一句问句 +(括号内一句话简短临床意义)。**不要**写"为什么要问 / 补全后能解锁什么"这种自创小节标题。
- 若患者根本未确诊,措辞改为"为明确诊断需补这些检查"。
- 列表后用一句话整体标注来源 `以上各项均参考 {guideline_name}` 作为 markdown 最后一段,**不要**追加任何文字(不寒暄、不代医生填答案、不加第三个 `## 标题`)。

若所有判断点都已明确无需澄清, `## 仍需澄清` 段写"指南所需关键事实已齐备,无需补充。"
"""


async def _stream_clarify_lite(
    patient_text: str,
    guideline_name: str,
    current_nodes: list[dict],
    candidate_next_nodes: list[dict],
):
    """流式澄清生成器。

    LLM 协议:第 1 行 MATCHED:<ids>,之后是 markdown 正文。
    本函数 yield 两类事件:
      ("matched", [node_id, ...])     —— 解析完 MATCHED 行后,只 yield 一次
      ("text", "<markdown chunk>")    —— markdown 部分的每个 chunk 实时 yield 给前端
    """
    prompt = _build_clarify_lite_prompt(patient_text, guideline_name, current_nodes, candidate_next_nodes)
    logger.info(
        "[_stream_clarify_lite] current_nodes=%d next_nodes=%d prompt_len=%d",
        len(current_nodes), len(candidate_next_nodes), len(prompt),
    )
    try:
        import time as _t
        _dump_path = f"/tmp/ask_clarify_lite_prompt_{int(_t.time())}.txt"
        with open(_dump_path, "w") as f:
            f.write(prompt)
        logger.info("[_stream_clarify_lite] full prompt dumped to %s", _dump_path)
    except Exception:
        pass

    llm = Gemini35Flash()
    # 状态机: 收 chunk 拼到 head_buf,直到见到第一个 \n;
    # 解析 head_buf 拿到 MATCHED ids,后面所有 chunk 直接 yield 给前端
    head_buf = ""
    header_parsed = False
    matched_ids: list[int] = []

    # 不支持 stream_call 的 lineup (GLM/DeepSeek/Kimi/Qwen) 兜底: 走 __call__ 非流式,
    # 拿到完整 text 后用一次 yield 模拟流式,保持下游协议一致
    async def _chunk_stream():
        if hasattr(llm, "stream_call"):
            async for c in llm.stream_call(user_prompt=prompt, temperature=0.1):
                yield c
        else:
            full = await llm(user_prompt=prompt, temperature=0.1)
            yield (full or "")

    async for chunk in _chunk_stream():
        if not chunk:
            continue
        if header_parsed:
            yield ("text", chunk)
            continue
        head_buf += chunk
        if "\n" in head_buf:
            header_line, _, rest = head_buf.partition("\n")
            header_line = header_line.strip()
            if header_line.upper().startswith("MATCHED:"):
                ids_str = header_line.split(":", 1)[1].strip()
                for tok in ids_str.split(","):
                    tok = tok.strip()
                    if tok.isdigit():
                        matched_ids.append(int(tok))
            else:
                # LLM 没按格式来,把 head_buf 全当 markdown
                rest = head_buf
                matched_ids = []
            header_parsed = True
            yield ("matched", matched_ids)
            if rest:
                yield ("text", rest)

    # LLM 一个字都没吐出 \n,兜底
    if not header_parsed:
        yield ("matched", [])
        if head_buf:
            yield ("text", head_buf)


# 保留 _ask_clarify_lite 名字给主报告用 — 内部走流式,拼成完整结果返回
async def _ask_clarify_lite(
    patient_text: str,
    guideline_name: str,
    current_nodes: list[dict],
    candidate_next_nodes: list[dict],
) -> dict:
    """主报告用:跑完流式,聚合返回 dict。"""
    matched_ids: list[int] = []
    text_parts: list[str] = []
    async for event_name, payload in _stream_clarify_lite(
        patient_text, guideline_name, current_nodes, candidate_next_nodes,
    ):
        if event_name == "matched":
            matched_ids = payload
        elif event_name == "text":
            text_parts.append(payload)
    full_markdown = "".join(text_parts).strip()
    logger.info("[_ask_clarify_lite] aggregated: matched=%d markdown=%dc",
                len(matched_ids), len(full_markdown))
    return {
        "decision_type": "match" if not matched_ids else "insufficient",
        "matched_node_ids": matched_ids,
        "clarify_markdown": full_markdown,
    }


def _collect_clarify_context(
    target_node_ids: list[int],
    out_adj: dict,
    node_by_id: dict,
    max_next: int = 30,
) -> tuple[list[dict], list[dict]]:
    """收集澄清需要的最小上下文:
    - current_nodes:patient 已确定可达的 phase 内入口节点(带 entry_conditions)
    - candidate_next_nodes:这些节点的一阶下游节点(也带 entry_conditions)
    返回 (current_nodes, candidate_next_nodes) — 都已去重。
    """
    cur_ids = set(target_node_ids)
    current = []
    for nid in target_node_ids:
        n = node_by_id.get(nid)
        if not n:
            continue
        current.append({
            "node_id": nid,
            "title": n.get("title", ""),
            "entry_conditions": n.get("entry_conditions") or [],
        })
    # 一阶下游
    next_ids: list[int] = []
    seen_next: set[int] = set()
    for nid in target_node_ids:
        for tgt, _label in out_adj.get(nid, []):
            if tgt in cur_ids or tgt in seen_next:
                continue
            seen_next.add(tgt)
            next_ids.append(tgt)
            if len(next_ids) >= max_next:
                break
        if len(next_ids) >= max_next:
            break
    candidate_next = []
    for nid in next_ids:
        n = node_by_id.get(nid)
        if not n:
            continue
        candidate_next.append({
            "node_id": nid,
            "title": n.get("title", ""),
            "entry_conditions": n.get("entry_conditions") or [],
        })
    return current, candidate_next


def _build_clarify_path_mermaid(
    matched_node_ids: list[int],
    node_by_id: dict,
    out_adj: dict,
    rev_adj: dict,
    root_nodes: set,
    forward_depth: int = 3,
) -> str:
    """从 matched_node_ids 出发,反向走回 root + 正向走 forward_depth 跳,
    渲染成 mermaid 图 — 表达 "之前路程 + 当前位置 + 后续可走"。

    设计:
    - 反向用 _reverse_paths_to_root(单 target,带 budget 防爆炸)
    - 正向用简单 BFS,每步沿 out_adj 走,最多 forward_depth 跳
    - 节点角色:matched=★(当前),on_path=●(走过),sibling=○(后续候选)
    """
    if not matched_node_ids:
        return ""
    matched_set = {int(x) for x in matched_node_ids if x in node_by_id}
    if not matched_set:
        return ""

    on_path: set[int] = set(matched_set)
    edges: set[tuple[int, int, str]] = set()

    # 1. 反向:从每个 matched 节点找到 root
    for nid in matched_set:
        paths = _reverse_paths_to_root(nid, rev_adj, root_nodes, max_paths=2, max_depth=14)
        for p in paths:
            for i in range(len(p) - 1):
                nxt = int(p[i][0])
                cur = int(p[i + 1][0])
                edge_label = (p[i][1] or "").strip()
                on_path.add(nxt)
                on_path.add(cur)
                edges.add((cur, nxt, edge_label))

    # 2. 正向 BFS:每个 matched 节点走 forward_depth 跳
    # 限制总节点数防止链路过大(乳腺癌从 BINV-1 一跳会铺开几十个 PHYLL/PREG/IBC 旁支)
    sibling: set[int] = set()
    from collections import deque
    queue = deque((nid, 0) for nid in matched_set)
    visited = set(matched_set)
    MAX_SIBLING = 25
    while queue and len(sibling) < MAX_SIBLING:
        cur, depth = queue.popleft()
        if depth >= forward_depth:
            continue
        # 跳过跨页"cross_page" 启发式边 — 它们经常把不相关的入口拽进来
        for tgt, label in out_adj.get(cur, []):
            if tgt in visited:
                continue
            label_lower = (label or "").lower()
            if label_lower.startswith("cross_page:") or label_lower.startswith("see "):
                continue
            visited.add(tgt)
            sibling.add(tgt)
            edges.add((cur, tgt, (label or "").strip()))
            if len(sibling) >= MAX_SIBLING:
                break
            queue.append((tgt, depth + 1))

    # 3. 渲染 mermaid (不含 ```mermaid 围栏 — 上层 _format_graph_evidence 会自己加)
    lines = ["graph TD"]
    # 节点定义
    all_nids = on_path | sibling
    for nid in all_nids:
        n = node_by_id.get(nid, {})
        title = (n.get("title") or "").strip()
        # 清掉 mermaid 不喜欢的字符
        title = title.replace('"', "'").replace("\n", " ").replace("[", "(").replace("]", ")")
        if len(title) > 60:
            title = title[:58] + "…"
        marker = ""
        if nid in matched_set:
            marker = " ★"  # 当前位置
        elif nid in on_path:
            marker = " ✓"  # 走过
        else:
            marker = " ?"  # 后续候选
        lines.append(f'    N{nid}["{title}{marker}"]')
    # 边
    for src, tgt, label in sorted(edges):
        label = label.replace('"', "'").replace("\n", " ")
        if len(label) > 40:
            label = label[:38] + "…"
        if label:
            lines.append(f'    N{src} -->|"{label}"| N{tgt}')
        else:
            lines.append(f'    N{src} --> N{tgt}')
    # 样式
    for nid in matched_set:
        lines.append(f'    style N{nid} fill:#90EE90,stroke:#333,stroke-width:3px')
    for nid in on_path - matched_set:
        lines.append(f'    style N{nid} fill:#FFFFFF,stroke:#666,stroke-width:1px')
    for nid in sibling:
        lines.append(f'    style N{nid} fill:#FFF8DC,stroke:#999,stroke-width:1px,stroke-dasharray:5 5')
    return "\n".join(lines)


async def _ask_path_select(
    patient_text: str,
    node_registry: dict,
    paths: list[dict],
    condition_hints: list[dict],
    global_rules_text: str = "",
    page_footnotes_text: str = "",
) -> dict:
    prompt = _build_path_prompt(patient_text, node_registry, paths, condition_hints, global_rules_text, page_footnotes_text)
    logger.info(
        "[_ask_path_select] candidate_paths=%d global_rules_len=%d footnotes_len=%d prompt_len=%d",
        len(paths),
        len(global_rules_text),
        len(page_footnotes_text),
        len(prompt),
    )
    # 落盘完整 prompt (供产品调试 / 检查)
    try:
        import time as _t
        _dump_path = f"/tmp/ask_path_select_prompt_{int(_t.time())}.txt"
        with open(_dump_path, "w") as f:
            f.write(prompt)
        logger.info("[_ask_path_select] full prompt dumped to %s", _dump_path)
    except Exception:
        pass
    logger.debug("[_ask_path_select] prompt:\n%s", prompt)
    llm = Gemini31Pro()
    content = await llm(
        user_prompt=prompt,
        temperature=0.1,
        response_mime_type="application/json",
        response_schema=PATH_SELECT_SCHEMA,
        thinking_budget="low",
    )
    logger.debug("[_ask_path_select] raw response: %s", content)
    try:
        return json.loads((content or "").strip() or "{}")
    except Exception:
        return {}


async def _ask_post_chain_analysis(
    patient_text: str,
    decision_type: str,
    matched_nodes: list[dict],
    page_mermaid: str,
    page_payload: list[dict],
    base_analysis: str,
    base_speculative_note: str,
    global_rules_text: str = "",
    sibling_context_nodes: list[dict] | None = None,
) -> dict:
    empty_pages = [p.get("code") or str(p.get("page_id")) for p in page_payload if not p.get("top_node_titles")]
    if empty_pages:
        logger.warning(
            "[_ask_post_chain_analysis] pages with NO nodes (content blind spot): %s",
            empty_pages,
        )
    prompt = _build_post_chain_prompt(
        patient_text=patient_text,
        decision_type=decision_type,
        matched_nodes=matched_nodes,
        page_mermaid=page_mermaid,
        page_payload=page_payload,
        base_analysis=base_analysis,
        base_speculative_note=base_speculative_note,
        global_rules_text=global_rules_text,
        sibling_context_nodes=sibling_context_nodes,
    )
    logger.debug("[_ask_post_chain_analysis] prompt (len=%d):\n%s", len(prompt), prompt)
    llm = Gemini31Pro()
    content = await llm(
        user_prompt=prompt,
        temperature=0.1,
        response_mime_type="application/json",
        response_schema=POST_CHAIN_ANALYSIS_SCHEMA,
        thinking_budget="low",
    )
    logger.debug("[_ask_post_chain_analysis] raw response: %s", content)
    try:
        return json.loads((content or "").strip() or "{}")
    except Exception:
        return {}


async def run_post_analysis_for_potential_nodes(
    patient_text: str,
    file_path: str,
    decision_type: str,
    matched_nodes: list[dict],
    base_analysis: str,
    base_speculative_note: str,
    on_event: Callable[[str, dict], None] | None = None,
) -> dict:
    """
    在补充信息回合结束后，对“可能匹配节点”补做一轮完整链路分析。
    该函数不改变决策类型，仅补充解释信息。
    """
    if not matched_nodes:
        return {"matched_node_full_chains": [], "post_chain_analysis": "", "post_chain_speculative_note": ""}

    path_str = str(Path(file_path).resolve())
    loaded = guidance_db.load_file_and_pages_by_path(path_str)
    if loaded is None:
        return {"matched_node_full_chains": [], "post_chain_analysis": "", "post_chain_speculative_note": ""}
    guideline_id, file_id, _pages_by_num, _ = loaded
    entry = guidance_db.get_entry_page_code(file_id, guideline_id)
    if not entry:
        return {"matched_node_full_chains": [], "post_chain_analysis": "", "post_chain_speculative_note": ""}
    entry_page_id = int(entry[0])

    graph_data = _load_file_graph(file_id, guideline_id)
    node_by_id, _rev_adj, _root_nodes, _out_adj = _build_reverse_graph(
        graph_data, entry_page_id
    )
    global_rules_text = guidance_db.merged_guideline_global_rules_text(guideline_id)

    # Sibling context nodes: parallel entry nodes on the same pages as matched nodes,
    # used to expose dosage confusion traps in the post-chain analysis prompt.
    _matched_page_ids = {n["page_id"] for n in matched_nodes}
    _matched_nids = {n["node_id"] for n in matched_nodes}
    _matched_phase_ids = {n.get("care_phase_id") for n in matched_nodes}
    sibling_context_nodes: list[dict] = [
        {
            "node_id": node["id"],
            "title": node["title"],
            "content": node["content"][:800],
            "page_id": node["page_id"],
            "care_phase_id": node["care_phase_id"],
        }
        for nid, node in node_by_id.items()
        if node["page_id"] in _matched_page_ids
        and node["is_entry"]
        and nid not in _matched_nids
        and node["care_phase_id"] in _matched_phase_ids
    ]

    post_page_subgraph = _build_post_page_subgraph(
        graph_data=graph_data,
        node_by_id=node_by_id,
        matched_nodes=matched_nodes,
    )
    page_payload = post_page_subgraph.get("pages") or []
    page_mermaid = post_page_subgraph.get("mermaid") or "graph TD\n"
    if not page_payload:
        return {"matched_node_full_chains": [], "post_chain_analysis": "", "post_chain_speculative_note": ""}

    post_chain_analysis = await _ask_post_chain_analysis(
        patient_text=patient_text,
        decision_type=decision_type,
        matched_nodes=matched_nodes,
        page_mermaid=page_mermaid,
        page_payload=page_payload,
        base_analysis=base_analysis,
        base_speculative_note=base_speculative_note,
        global_rules_text=global_rules_text,
        sibling_context_nodes=sibling_context_nodes or None,
    )
    if on_event:
        on_event("post_chain_analysis_after_supplement", post_chain_analysis)

    return {
        "matched_node_full_chains": page_payload,
        "post_chain_analysis": post_chain_analysis.get("analysis") or "",
        "post_chain_speculative_note": (
            post_chain_analysis.get("speculative_note") or ""
        ).strip(),
    }


def _build_out_of_scope_analysis_prompt(
    patient_text: str,
    out_of_scope_reason: str,
    global_rules_text: str = "",
) -> str:
    gr = (global_rules_text or "").strip()
    global_block = (
        "## 本指南全局规则\n"
        f"{gr}\n\n"
    ) if gr else ""
    return f"""你是临床指南分析助手。患者信息涉及两个阶段：（1）初始怀疑本指南目标疾病并已启动相应治疗；（2）后续检测排除该诊断。

**任务——分两步评估**：

**第一步——评估初始疑诊阶段的处理是否正确**：
依据上方「本指南全局规则」，判断在初始怀疑本指南目标疾病时所采取的处理（如立即启动特异性治疗）是否符合指南规定。若全局规则明确规定"在形态学怀疑时应立即启动治疗，无需等待分子/遗传学确诊"，则该初始处理是正确的，须予以明确肯定并引用相关全局规则原文。若存在违规处，明确指出。

**第二步——排除诊断后的正确处置**：
明确说明：一旦细胞遗传学/分子学结果排除了本指南目标疾病，**必须立即停用本指南专属治疗方案**（须具体指出哪些药物/方案应停用）；患者应按照其实际确诊疾病的相应指南进行治疗。

在 `speculative_note` 中（须标注"非本指南原文、仅为推测性讨论"）：
基于患者实际的分子学/基因检测结果，讨论其可能的真实诊断，并逐项分析：在本指南中被特别限制或禁忌的某些治疗（例如：FLT3抑制剂在本指南目标疾病中被明确禁用），在患者实际确诊的疾病中是否发生了推荐方向的反转。须逐项列出所有可能发生推荐方向反转的关键药物或操作，并说明在真实诊断下的正确推荐。

{global_block}## 患者信息
{patient_text}

## 系统判断排除本指南适用范围的原因
{out_of_scope_reason}"""


async def _ask_out_of_scope_analysis(
    patient_text: str,
    out_of_scope_reason: str,
    global_rules_text: str = "",
) -> dict:
    prompt = _build_out_of_scope_analysis_prompt(patient_text, out_of_scope_reason, global_rules_text)
    logger.debug("[_ask_out_of_scope_analysis] prompt (len=%d):\n%s", len(prompt), prompt)
    llm = Gemini31Pro()
    content = await llm(
        user_prompt=prompt,
        temperature=0.1,
        response_mime_type="application/json",
        response_schema=POST_CHAIN_ANALYSIS_SCHEMA,
        thinking_budget="low",
    )
    logger.debug("[_ask_out_of_scope_analysis] raw response: %s", content)
    try:
        return json.loads((content or "").strip() or "{}")
    except Exception:
        return {}


async def run_search_phase(
    patient_text: str,
    file_path: str,
    on_event: Callable[[str, dict], None] | None = None,
) -> dict:
    path_str = str(Path(file_path).resolve())
    loaded = guidance_db.load_file_and_pages_by_path(path_str)
    if loaded is None:
        return {"error": "DB 中未找到该 file_path 的指南，请先入库。"}
    guideline_id, file_id, _pages_by_num, _ = loaded
    entry = guidance_db.get_entry_page_code(file_id, guideline_id)
    if not entry:
        return {"error": "该 file 下无入口页。"}
    entry_page_id = int(entry[0])

    phases = guidance_db.list_guidance_care_phases(guideline_id)
    if not phases:
        return {"error": f"guideline_id={guideline_id} 下无 care phases。"}

    # 取指南可读名喂给分诊 prompt 做病种锚定, 防止 LLM 脑补病种误判 out_of_scope。
    try:
        _doc_full = guidance_db.get_guideline_doc(guideline_id)
        _files = _doc_full.get("files", []) if _doc_full else []
        guideline_name = (_files[0].get("file_name") if _files else "") or (_doc_full or {}).get("filename", "") or ""
    except Exception:
        guideline_name = ""

    phase_decision = await _ask_phase(patient_text, phases, guideline_name=guideline_name)
    if on_event:
        on_event("phase_decision", phase_decision)

    primary = (phase_decision.get("primary_phase_code") or "").strip().lower()
    secondary = (phase_decision.get("secondary_phase_code") or "").strip().lower()
    additional = [c.strip().lower() for c in (phase_decision.get("additional_phase_codes") or []) if c.strip()]
    phase_codes = list(dict.fromkeys([c for c in [primary, secondary, *additional] if c]))
    phase_code_to_id = {(p.get("code") or "").strip().lower(): p["id"] for p in phases}
    phase_ids = [phase_code_to_id[c] for c in phase_codes if c in phase_code_to_id]
    if primary == "out_of_scope":
        _oos_global_rules = guidance_db.merged_guideline_global_rules_text(guideline_id)
        _oos_reason = phase_decision.get("reason") or ""
        _oos_analysis = await _ask_out_of_scope_analysis(
            patient_text=patient_text,
            out_of_scope_reason=_oos_reason,
            global_rules_text=_oos_global_rules,
        )
        if on_event:
            on_event("out_of_scope_analysis", _oos_analysis)
        return {
            "guideline_id": guideline_id,
            "file_id": file_id,
            "phase_decision": phase_decision,
            "phase_codes": ["out_of_scope"],
            "decision_type": "guideline_gap",
            "analysis": _oos_reason,
            "speculative_note": "",
            "clarify_markdown": "",
            "matched_nodes": [],
            "matched_node_full_chains": [],
            "post_chain_analysis": _oos_analysis.get("analysis") or "",
            "post_chain_speculative_note": (_oos_analysis.get("speculative_note") or "").strip(),
            "candidate_path_count": 0,
        }
    if not phase_ids:
        return {
            "insufficient": True,
            "phase_decision": phase_decision,
            "clarify_markdown": "## 已掌握信息\n\n- (系统暂无法基于患者描述完成结构化抽取)\n\n## 仍需澄清\n\n1. 请补充当前治疗阶段(诱导/巩固/维持/复发):系统无法可靠判断阶段。\n\n请按编号直接续写补充,未掌握的写\"不详\"。",
            "matched_nodes": [],
        }

    graph_data = _load_file_graph(file_id, guideline_id)
    node_by_id, rev_adj, root_nodes, out_adj = _build_reverse_graph(
        graph_data, entry_page_id
    )

    # Log pages that exist in the graph but have no parsed nodes — these are blind spots
    # where the LLM cannot see guideline content (e.g. supportive-care pages like APL-A).
    _pages_in_graph = {int(r[0]): (r[2] or "").strip() for r in graph_data.get("pages", [])}
    _node_page_ids = {n["page_id"] for n in node_by_id.values()}
    _empty_pages = {pid: code for pid, code in _pages_in_graph.items() if pid not in _node_page_ids}
    if _empty_pages:
        logger.warning(
            "[run_search_phase] guideline_id=%d has %d page(s) with NO nodes "
            "(content invisible to path matching): %s",
            guideline_id,
            len(_empty_pages),
            _empty_pages,
        )

    target_node_ids = [nid for nid, n in node_by_id.items() if n.get("care_phase_id") in set(phase_ids)]

    # Expand: also include nodes from pages linked directly from target-phase pages.
    # This captures supportive-care pages (e.g. APL-A) that carry no explicit care_phase_id
    # matching the active treatment phase but are directly reachable in the flowchart.
    _target_phase_page_ids = {node_by_id[nid]["page_id"] for nid in target_node_ids}
    _linked_page_ids = {
        int(tgt)
        for src, tgt in graph_data["links"]
        if int(src) in _target_phase_page_ids
    } - _target_phase_page_ids
    if _linked_page_ids:
        _extra_ids = [nid for nid, n in node_by_id.items() if n["page_id"] in _linked_page_ids]
        if _extra_ids:
            logger.debug(
                "[run_search_phase] expanding target_node_ids with %d nodes from %d linked pages: %s",
                len(_extra_ids),
                len(_linked_page_ids),
                _linked_page_ids,
            )
            target_node_ids = list({*target_node_ids, *_extra_ids})

    # Build a deduplicated node registry + compact path list to minimise prompt tokens.
    # Each node's title/page_id is stored once in node_registry; target nodes additionally
    # carry content and entry_conditions (also stored once, regardless of how many paths
    # lead to the same target).  Each path entry contains only node_ids + via edge labels.
    node_registry: dict[str, dict] = {}
    compact_paths: list[dict] = []
    for nid in target_node_ids:
        found_paths = _reverse_paths_to_root(
            nid,
            rev_adj,
            root_nodes,
            max_paths=MAX_PATHS_PER_TARGET,
            max_depth=MAX_PATH_DEPTH,
        )
        for p in found_paths:
            route = []
            for node_id_raw, edge_label in p:
                node_id = int(node_id_raw)
                if str(node_id) not in node_registry:
                    node = node_by_id[node_id]
                    node_registry[str(node_id)] = {
                        "title": node["title"],
                        "page_id": node["page_id"],
                    }
                route.append({"node_id": node_id, "via": edge_label})
            # Enrich target node with content + entry_conditions exactly once.
            target_key = str(nid)
            if "content" not in node_registry.get(target_key, {}):
                node = node_by_id[nid]
                node_registry.setdefault(target_key, {"title": node["title"], "page_id": node["page_id"]})
                node_registry[target_key]["content"] = node["content"][:600]
                node_registry[target_key]["entry_conditions"] = node.get("entry_conditions") or []
            # The "via" on each non-last route step = edge FROM that node TO the next.
            # So the incoming edge rule for the target is carried by its parent (route[-2]).
            target_incoming_edge_rule = route[-2]["via"] if len(route) >= 2 else ""
            compact_paths.append({
                "target_node_id": int(nid),
                "target_incoming_edge_rule": target_incoming_edge_rule,
                "route": route,
            })
            if MAX_CANDIDATE_PATHS > 0 and len(compact_paths) >= MAX_CANDIDATE_PATHS:
                break
        if MAX_CANDIDATE_PATHS > 0 and len(compact_paths) >= MAX_CANDIDATE_PATHS:
            break

    condition_hints = _build_condition_hints(guideline_id)
    global_rules_text = guidance_db.merged_guideline_global_rules_text(guideline_id)
    _page_id_to_code = {int(r[0]): (r[2] or "").strip() for r in graph_data.get("pages", [])}
    _candidate_page_ids = {
        int(v["page_id"]) for v in node_registry.values() if v.get("page_id")
    }
    # Expand to sibling and ancestor pages so that cross-branch footnotes reach the LLM.
    # Sibling pages share the same parent (e.g. APL-3 and APL-4 are siblings under APL-1).
    # Ancestor pages are the parent/grandparent/root flowchart pages — critical because
    # footnotes like footnote-c ("must use regimen consistently across all components") and
    # footnote-a ("t-APL treated identically to de novo APL") live on the root/parent page's
    # footnote file, not on the leaf candidate pages.
    _page_link_children: dict[int, set[int]] = defaultdict(set)
    _page_link_parents: dict[int, set[int]] = defaultdict(set)
    for _src, _tgt in graph_data["links"]:
        _page_link_children[int(_src)].add(int(_tgt))
        _page_link_parents[int(_tgt)].add(int(_src))
    _sibling_page_ids = set(_candidate_page_ids)
    # Add siblings (pages sharing the same parent)
    for _cand_pid in _candidate_page_ids:
        for _parent_children in _page_link_children.values():
            if _cand_pid in _parent_children:
                _sibling_page_ids.update(_parent_children)
    # Walk ancestors upward from each candidate page (BFS) to collect all ancestor pages.
    # This is bounded: typical APL flowcharts have ≤5 levels of nesting.
    _ancestor_frontier = set(_candidate_page_ids)
    for _ in range(6):  # max ancestor depth
        _next_frontier: set[int] = set()
        for _pid in _ancestor_frontier:
            _next_frontier.update(_page_link_parents.get(_pid, set()))
        _new_ancestors = _next_frontier - _sibling_page_ids
        if not _new_ancestors:
            break
        _sibling_page_ids.update(_new_ancestors)
        _ancestor_frontier = _new_ancestors
    _candidate_page_codes = {
        _page_id_to_code.get(pid, "") for pid in _sibling_page_ids
    } - {""}
    _footnote_map = graph_data.get("footnote_texts_by_anchor", {})
    page_footnotes_text = "\n\n".join(
        f"[{code}]\n{_footnote_map[code]}"
        for code in sorted(_candidate_page_codes)
        if code in _footnote_map
    )
    select_decision = await _ask_path_select(
        patient_text, node_registry, compact_paths, condition_hints, global_rules_text, page_footnotes_text
    )
    if on_event:
        on_event("path_decision", select_decision)

    decision_type = (select_decision.get("decision_type") or "").strip().lower()
    raw_matched_ids = list(select_decision.get("matched_node_ids") or [])
    if decision_type == "guideline_gap":
        raw_matched_ids = []

    matched_nodes = []
    for nid in raw_matched_ids:
        node = node_by_id.get(int(nid))
        if not node:
            continue
        matched_nodes.append({
            "node_id": node["id"],
            "title": node["title"],
            "content": node["content"],
            "page_id": node["page_id"],
            "care_phase_id": node["care_phase_id"],
        })

    # Collect sibling entry nodes on the same pages as matched nodes (but not yet matched).
    # These are parallel regimens (e.g. intermittent ATO 0.3 mg/kg schedule) that share
    # numerical values with a doctor's erroneous plan but in a different clinical context.
    # Surfacing them lets the post-chain LLM explain dosage confusion traps.
    _matched_page_ids = {n["page_id"] for n in matched_nodes}
    _matched_nids = {n["node_id"] for n in matched_nodes}
    _matched_phase_ids = {n["care_phase_id"] for n in matched_nodes}
    sibling_context_nodes: list[dict] = [
        {
            "node_id": node["id"],
            "title": node["title"],
            "content": node["content"][:800],
            "page_id": node["page_id"],
            "care_phase_id": node["care_phase_id"],
        }
        for nid, node in node_by_id.items()
        if node["page_id"] in _matched_page_ids
        and node["is_entry"]
        and nid not in _matched_nids
        and node["care_phase_id"] in _matched_phase_ids
    ]

    clarify_markdown = (select_decision.get("clarify_markdown") or "").strip()
    if decision_type == "guideline_gap":
        clarify_markdown = ""

    matched_chains: list[dict] = []
    post_chain_analysis: dict = {}
    should_run_post_analysis = decision_type == "match" and bool(matched_nodes)
    if should_run_post_analysis:
        post_page_subgraph = _build_post_page_subgraph(
            graph_data=graph_data,
            node_by_id=node_by_id,
            matched_nodes=matched_nodes,
        )
        matched_chains = post_page_subgraph.get("pages") or []
        page_mermaid = post_page_subgraph.get("mermaid") or "graph TD\n"
        if matched_chains:
            post_chain_analysis = await _ask_post_chain_analysis(
                patient_text=patient_text,
                decision_type=decision_type,
                matched_nodes=matched_nodes,
                page_mermaid=page_mermaid,
                page_payload=matched_chains,
                base_analysis=select_decision.get("analysis") or "",
                base_speculative_note=(select_decision.get("speculative_note") or "").strip(),
                global_rules_text=global_rules_text,
                sibling_context_nodes=sibling_context_nodes or None,
            )
            if on_event:
                on_event("post_chain_analysis", post_chain_analysis)

    _all_page_codes = {
        (r[2] or "").strip().upper()
        for r in graph_data.get("pages", [])
        if (r[2] or "").strip()
    }
    graph_path_result = _build_graph_path(
        node_by_id=node_by_id,
        out_adj=out_adj,
        matched_node_ids=[n["node_id"] for n in matched_nodes],
        compact_paths=compact_paths,
        page_codes=_all_page_codes,
    )

    return {
        "guideline_id": guideline_id,
        "file_id": file_id,
        "phase_decision": phase_decision,
        "phase_codes": phase_codes,
        "decision_type": decision_type,
        "clarify_markdown": clarify_markdown,
        "matched_nodes": matched_nodes,
        "matched_node_full_chains": matched_chains,
        "candidate_path_count": len(compact_paths),
        "pruned_tree_mermaid": graph_path_result["mermaid"],
        "pruned_tree_stats": graph_path_result["stats"],
    }


async def run_search_phase_by_doc_id(
    patient_text: str,
    doc_id: int,
    on_event: Callable[[str, dict], None] | None = None,
    mode: str = "report",
    text_stream_cb: Callable[[str], "Awaitable[None]"] | None = None,
) -> dict:
    """Generic Path 2 entry point using doc_id instead of file_path.

    Loads graph data from the unified plm_guidelines index by doc_id.

    mode:
      "report"  — 主报告(诊疗建议)用,走完整 _ask_path_select 链路,
                  prompt 含整本脚注、condition_hints、反向 BFS 候选路径。
      "clarify" — 澄清接口用,走轻量 _ask_clarify_lite,
                  prompt 只含当前节点 + 一阶下游 entry_conditions,5-10K 字符。
    """
    loaded = guidance_db.load_graph_by_doc_id(doc_id)
    if loaded is None:
        return {"error": f"doc_id={doc_id} 无图谱数据（has_graph=false 或无 files）。"}
    guideline_id, file_id = loaded

    # 列出全部 entry 候选;一份 NCCN PDF 常含多个独立路径入口
    # (如乳腺癌的 DCIS / Invasive / IBC / PHYLL / PAGET / PREG),
    # 让 LLM 基于患者描述挑出对的那个,避免误把整本 PDF 的第 1 个入口当唯一入口。
    entry_candidates = guidance_db.list_entry_pages(file_id, guideline_id)
    if not entry_candidates:
        entry = guidance_db.get_entry_page_code(file_id, guideline_id)
        if not entry:
            return {"error": "该 file 下无入口页。"}
        entry_page_id = int(entry[0])
    else:
        entry_page_id = await _ask_entry(patient_text, entry_candidates)
        if entry_page_id is None:
            return {"error": "该 file 下无入口页。"}
        if on_event:
            on_event("entry_decision", {"chosen_page_id": entry_page_id,
                                        "candidate_count": len(entry_candidates)})

    phases = guidance_db.list_guidance_care_phases(guideline_id)
    if not phases:
        return {"error": f"guideline_id={guideline_id} 下无 care phases。"}

    # 取指南可读名喂给分诊 prompt 做病种锚定, 防止 LLM 脑补病种误判 out_of_scope。
    try:
        _doc_full = guidance_db.get_guideline_doc(guideline_id)
        _files = _doc_full.get("files", []) if _doc_full else []
        guideline_name = (_files[0].get("file_name") if _files else "") or (_doc_full or {}).get("filename", "") or ""
    except Exception:
        guideline_name = ""

    phase_decision = await _ask_phase(patient_text, phases, guideline_name=guideline_name)
    if on_event:
        on_event("phase_decision", phase_decision)

    primary = (phase_decision.get("primary_phase_code") or "").strip().lower()
    secondary = (phase_decision.get("secondary_phase_code") or "").strip().lower()
    additional = [c.strip().lower() for c in (phase_decision.get("additional_phase_codes") or []) if c.strip()]
    phase_codes = list(dict.fromkeys([c for c in [primary, secondary, *additional] if c]))
    phase_code_to_id = {(p.get("code") or "").strip().lower(): p["id"] for p in phases}
    phase_ids = [phase_code_to_id[c] for c in phase_codes if c in phase_code_to_id]

    if primary == "out_of_scope":
        _oos_global_rules = guidance_db.merged_guideline_global_rules_text(guideline_id)
        _oos_reason = phase_decision.get("reason") or ""
        _oos_analysis = await _ask_out_of_scope_analysis(
            patient_text=patient_text,
            out_of_scope_reason=_oos_reason,
            global_rules_text=_oos_global_rules,
        )
        if on_event:
            on_event("out_of_scope_analysis", _oos_analysis)
        return {
            "guideline_id": guideline_id,
            "file_id": file_id,
            "phase_decision": phase_decision,
            "phase_codes": ["out_of_scope"],
            "decision_type": "guideline_gap",
            "analysis": _oos_reason,
            "speculative_note": "",
            "clarify_markdown": "",
            "matched_nodes": [],
            "matched_node_full_chains": [],
            "post_chain_analysis": _oos_analysis.get("analysis") or "",
            "post_chain_speculative_note": (_oos_analysis.get("speculative_note") or "").strip(),
            "candidate_path_count": 0,
        }

    if not phase_ids:
        return {
            "insufficient": True,
            "phase_decision": phase_decision,
            "clarify_markdown": "## 已掌握信息\n\n- (系统暂无法基于患者描述完成结构化抽取)\n\n## 仍需澄清\n\n1. 请补充当前治疗阶段(诱导/巩固/维持/复发):系统无法可靠判断阶段。\n\n请按编号直接续写补充,未掌握的写\"不详\"。",
            "matched_nodes": [],
        }

    import time as _ttt
    _trace_t0 = _ttt.perf_counter()
    def _trace(msg):
        print(f"      [search-trace+{_ttt.perf_counter()-_trace_t0:.1f}s] {msg}", flush=True)

    _trace("load_file_graph START")
    graph_data = _load_file_graph(file_id, guideline_id)
    node_by_id, rev_adj, root_nodes, out_adj = _build_reverse_graph(graph_data, entry_page_id)
    _trace(f"graph loaded: nodes={len(node_by_id)} links={len(graph_data.get('links',[]))} pages={len(graph_data.get('pages',[]))}")

    target_node_ids = [nid for nid, n in node_by_id.items() if n.get("care_phase_id") in set(phase_ids)]
    _target_phase_page_ids = {node_by_id[nid]["page_id"] for nid in target_node_ids}
    _linked_page_ids = {
        int(tgt) for src, tgt in graph_data["links"] if int(src) in _target_phase_page_ids
    } - _target_phase_page_ids
    if _linked_page_ids:
        _extra_ids = [nid for nid, n in node_by_id.items() if n["page_id"] in _linked_page_ids]
        if _extra_ids:
            target_node_ids = list({*target_node_ids, *_extra_ids})
    _trace(f"target_node_ids={len(target_node_ids)}")

    # ── mode="clarify" 走轻量路径,直接返回 ──
    if mode == "clarify":
        # 拿入口页 + 当前 phase 的入口节点作为 current_nodes;
        # 候选下游 = 这些节点在 out_adj 上的一阶邻居 + 入口页本身的所有节点(让 LLM 有路径定位上下文)
        entry_phase_nodes = [nid for nid in target_node_ids if node_by_id[nid].get("is_entry")]
        if not entry_phase_nodes:
            entry_phase_nodes = target_node_ids[:10]
        current_nodes, candidate_next_nodes = _collect_clarify_context(
            entry_phase_nodes, out_adj, node_by_id, max_next=30,
        )
        _trace(f"clarify mode: current_nodes={len(current_nodes)} candidate_next={len(candidate_next_nodes)}")
        # 取指南 filename 作为可读名
        try:
            doc_full = guidance_db.get_guideline_doc(guideline_id)
            files = doc_full.get("files", []) if doc_full else []
            guideline_name = (files[0].get("file_name") if files else "") or doc_full.get("filename", "") or ""
        except Exception:
            guideline_name = ""
        # 流式跑: text_stream_cb 不为空时(澄清接口)实时把 markdown chunk 回调出去;
        # 为空时(主报告)聚合等结果。
        matched_ids: list[int] = []
        markdown_parts: list[str] = []
        async for evt_name, payload in _stream_clarify_lite(
            patient_text=patient_text,
            guideline_name=guideline_name or "NCCN 指南",
            current_nodes=current_nodes,
            candidate_next_nodes=candidate_next_nodes,
        ):
            if evt_name == "matched":
                matched_ids = payload or []
            elif evt_name == "text":
                markdown_parts.append(payload)
                if text_stream_cb is not None:
                    try:
                        await text_stream_cb(payload)
                    except Exception:
                        logger.exception("[run_search_phase] text_stream_cb failed")
        clarify_result = {
            "decision_type": "match" if not matched_ids else "insufficient",
            "matched_node_ids": matched_ids,
            "clarify_markdown": "".join(markdown_parts).strip(),
        }
        if on_event:
            on_event("clarify_decision", clarify_result)
        # 把 matched_node_ids 转成 matched_nodes(给主报告 graph_evidence 用同一格式)
        raw_matched_ids = clarify_result.get("matched_node_ids") or []
        valid_matched_ids = []
        matched_nodes_lite = []
        for nid in raw_matched_ids:
            try:
                nid_int = int(nid)
            except Exception:
                continue
            n = node_by_id.get(nid_int)
            if n:
                valid_matched_ids.append(nid_int)
                matched_nodes_lite.append({
                    "node_id": n["id"],
                    "title": n.get("title", ""),
                    "content": n.get("content", ""),
                    "page_id": n.get("page_id"),
                    "care_phase_id": n.get("care_phase_id"),
                })

        # 构造完整决策树链路: 当前节点 + 之前路程(反向到 root) + 后续 2-3 跳
        pruned_tree_mermaid = _build_clarify_path_mermaid(
            matched_node_ids=valid_matched_ids,
            node_by_id=node_by_id,
            out_adj=out_adj,
            rev_adj=rev_adj,
            root_nodes=root_nodes,
            forward_depth=3,
        )
        _trace(f"clarify mermaid built: chars={len(pruned_tree_mermaid)} matched={len(valid_matched_ids)}")

        return {
            "guideline_id": guideline_id,
            "file_id": file_id,
            "phase_decision": phase_decision,
            "phase_codes": phase_codes,
            "decision_type": clarify_result.get("decision_type") or "insufficient",
            "clarify_markdown": clarify_result.get("clarify_markdown") or "",
            "matched_nodes": matched_nodes_lite,
            "matched_node_full_chains": [],
            "candidate_path_count": 0,
            "pruned_tree_mermaid": pruned_tree_mermaid,
            "pruned_tree_stats": {
                "matched": len(valid_matched_ids),
                "has_mermaid": bool(pruned_tree_mermaid),
            },
        }

    node_registry: dict[str, dict] = {}
    compact_paths: list[dict] = []
    _tn_t0 = _ttt.perf_counter()
    for _tn_i, nid in enumerate(target_node_ids):
        if _tn_i > 0 and _tn_i % 20 == 0:
            _trace(f"_reverse_paths_to_root iter {_tn_i}/{len(target_node_ids)} elapsed={_ttt.perf_counter()-_tn_t0:.1f}s compact_paths={len(compact_paths)}")
        _per_t0 = _ttt.perf_counter()
        found_paths = _reverse_paths_to_root(nid, rev_adj, root_nodes, MAX_PATHS_PER_TARGET, MAX_PATH_DEPTH)
        _per_dt = _ttt.perf_counter() - _per_t0
        if _per_dt > 1.0:
            _trace(f"!! _reverse_paths_to_root nid={nid} took {_per_dt:.1f}s found={len(found_paths)}")
        for p in found_paths:
            route = []
            for node_id_raw, edge_label in p:
                node_id = int(node_id_raw)
                if str(node_id) not in node_registry:
                    node = node_by_id[node_id]
                    node_registry[str(node_id)] = {"title": node["title"], "page_id": node["page_id"]}
                route.append({"node_id": node_id, "via": edge_label})
            target_key = str(nid)
            if "content" not in node_registry.get(target_key, {}):
                node = node_by_id[nid]
                node_registry.setdefault(target_key, {"title": node["title"], "page_id": node["page_id"]})
                node_registry[target_key]["content"] = node["content"][:600]
                node_registry[target_key]["entry_conditions"] = node.get("entry_conditions") or []
            target_incoming_edge_rule = route[-2]["via"] if len(route) >= 2 else ""
            compact_paths.append({
                "target_node_id": int(nid),
                "target_incoming_edge_rule": target_incoming_edge_rule,
                "route": route,
            })
            if MAX_CANDIDATE_PATHS > 0 and len(compact_paths) >= MAX_CANDIDATE_PATHS:
                break
        if MAX_CANDIDATE_PATHS > 0 and len(compact_paths) >= MAX_CANDIDATE_PATHS:
            break

    _trace(f"compact_paths={len(compact_paths)} node_registry={len(node_registry)}")

    condition_hints = _build_condition_hints(guideline_id)
    _trace(f"condition_hints={len(condition_hints)}")
    global_rules_text = guidance_db.merged_guideline_global_rules_text(guideline_id)
    _trace(f"global_rules_text len={len(global_rules_text)}")
    _page_id_to_code = {int(r[0]): (r[2] or "").strip() for r in graph_data.get("pages", [])}
    _candidate_page_ids = {int(v["page_id"]) for v in node_registry.values() if v.get("page_id")}
    _page_link_children: dict[int, set[int]] = defaultdict(set)
    _page_link_parents: dict[int, set[int]] = defaultdict(set)
    for _src, _tgt in graph_data["links"]:
        _page_link_children[int(_src)].add(int(_tgt))
        _page_link_parents[int(_tgt)].add(int(_src))
    # 兄弟节点 = 跟候选页共享父节点的所有页。原写法 O(|cand| × |links|) 在大图谱(乳腺癌)
    # 上会跑爆 CPU 几分钟,改为 cand → parents → siblings 直接 O(|cand| + |siblings|)。
    _sibling_page_ids = set(_candidate_page_ids)
    _trace(f"siblings: candidate_pages={len(_candidate_page_ids)}")
    for _cand_pid in _candidate_page_ids:
        for _parent in _page_link_parents.get(_cand_pid, ()):
            _sibling_page_ids.update(_page_link_children.get(_parent, ()))
    _trace(f"siblings: after sibling expand={len(_sibling_page_ids)}")
    _ancestor_frontier = set(_candidate_page_ids)
    for _round in range(6):
        _next_frontier: set[int] = set()
        for _pid in _ancestor_frontier:
            _next_frontier.update(_page_link_parents.get(_pid, set()))
        _new_ancestors = _next_frontier - _sibling_page_ids
        if not _new_ancestors:
            break
        _sibling_page_ids.update(_new_ancestors)
        _ancestor_frontier = _new_ancestors
    _trace(f"siblings: after ancestor expand={len(_sibling_page_ids)}")
    _candidate_page_codes = {_page_id_to_code.get(pid, "") for pid in _sibling_page_ids} - {""}
    _footnote_map = graph_data.get("footnote_texts_by_anchor", {})
    _trace(f"footnote_map keys={len(_footnote_map)}")
    page_footnotes_text = "\n\n".join(
        f"[{code}]\n{_footnote_map[code]}" for code in sorted(_candidate_page_codes) if code in _footnote_map
    )
    select_decision = await _ask_path_select(
        patient_text, node_registry, compact_paths, condition_hints, global_rules_text, page_footnotes_text
    )
    if on_event:
        on_event("path_decision", select_decision)

    decision_type = (select_decision.get("decision_type") or "").strip().lower()
    raw_matched_ids = list(select_decision.get("matched_node_ids") or [])
    if decision_type == "guideline_gap":
        raw_matched_ids = []

    matched_nodes = []
    for nid in raw_matched_ids:
        node = node_by_id.get(int(nid))
        if not node:
            continue
        matched_nodes.append({
            "node_id": node["id"],
            "title": node["title"],
            "content": node["content"],
            "page_id": node["page_id"],
            "care_phase_id": node["care_phase_id"],
        })

    _matched_page_ids = {n["page_id"] for n in matched_nodes}
    _matched_nids = {n["node_id"] for n in matched_nodes}
    _matched_phase_ids = {n["care_phase_id"] for n in matched_nodes}
    sibling_context_nodes: list[dict] = [
        {
            "node_id": node["id"], "title": node["title"],
            "content": node["content"][:800], "page_id": node["page_id"],
            "care_phase_id": node["care_phase_id"],
        }
        for nid, node in node_by_id.items()
        if node["page_id"] in _matched_page_ids and node["is_entry"]
        and nid not in _matched_nids and node["care_phase_id"] in _matched_phase_ids
    ]

    clarify_markdown = (select_decision.get("clarify_markdown") or "").strip()
    if decision_type == "guideline_gap":
        clarify_markdown = ""

    matched_chains: list[dict] = []
    post_chain_analysis: dict = {}
    if decision_type == "match" and matched_nodes:
        post_page_subgraph = _build_post_page_subgraph(graph_data, node_by_id, matched_nodes)
        matched_chains = post_page_subgraph.get("pages") or []
        page_mermaid = post_page_subgraph.get("mermaid") or "graph TD\n"
        if matched_chains:
            post_chain_analysis = await _ask_post_chain_analysis(
                patient_text=patient_text, decision_type=decision_type,
                matched_nodes=matched_nodes, page_mermaid=page_mermaid,
                page_payload=matched_chains,
                base_analysis=select_decision.get("analysis") or "",
                base_speculative_note=(select_decision.get("speculative_note") or "").strip(),
                global_rules_text=global_rules_text,
                sibling_context_nodes=sibling_context_nodes or None,
            )
            if on_event:
                on_event("post_chain_analysis", post_chain_analysis)

    _all_page_codes = {
        (r[2] or "").strip().upper()
        for r in graph_data.get("pages", [])
        if (r[2] or "").strip()
    }
    graph_path_result = _build_graph_path(
        node_by_id=node_by_id,
        out_adj=out_adj,
        matched_node_ids=[n["node_id"] for n in matched_nodes],
        compact_paths=compact_paths,
        page_codes=_all_page_codes,
    )

    return {
        "guideline_id": guideline_id,
        "file_id": file_id,
        "phase_decision": phase_decision,
        "phase_codes": phase_codes,
        "decision_type": decision_type,
        "clarify_markdown": clarify_markdown,
        "matched_nodes": matched_nodes,
        "matched_node_full_chains": matched_chains,
        "candidate_path_count": len(compact_paths),
        "pruned_tree_mermaid": graph_path_result["mermaid"],
        "pruned_tree_stats": graph_path_result["stats"],
    }


def _print_event(name: str, payload: dict) -> None:
    print(f"[{name}] {json.dumps(payload, ensure_ascii=False)}")


async def main_async() -> None:
    patient_text = (PATIENT_TEXT_3 or "").strip()
    file_path = (DEFAULT_FILE_PATH or "").strip()
    if not patient_text or not file_path:
        print("请设置 PATIENT_TEXT 与 DEFAULT_FILE_PATH")
        return

    accumulated = patient_text
    rounds = 0
    try:
        while rounds <= MAX_SUPPLEMENT_ROUNDS:
            result = await run_search_phase(accumulated, file_path, on_event=_print_event)
            print("\n=== 结果 ===")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result.get("error"):
                return
            dt = (result.get("decision_type") or "").strip().lower()
            if dt == "guideline_gap":
                return
            if dt == "match" and result.get("matched_nodes"):
                return
            missing = (result.get("clarify_markdown") or "").strip()
            if not missing or rounds >= MAX_SUPPLEMENT_ROUNDS:
                if dt == "insufficient" and result.get("matched_nodes"):
                    print("\n--- 补充回合结束，执行可能节点的后续链路分析 ---")
                    post = await run_post_analysis_for_potential_nodes(
                        patient_text=accumulated,
                        file_path=file_path,
                        decision_type=dt,
                        matched_nodes=result.get("matched_nodes") or [],
                        base_analysis=result.get("analysis") or "",
                        base_speculative_note=result.get("speculative_note") or "",
                        on_event=_print_event,
                    )
                    merged = {**result, **post}
                    print("\n=== 补充后 Post 分析结果 ===")
                    print(json.dumps(merged, ensure_ascii=False, indent=2))
                return
            print("\n--- 请根据 clarify_markdown 补充信息（回车结束） ---")
            print(missing)
            try:
                extra = input("补充信息: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n结束。")
                return
            if not extra:
                return
            accumulated = accumulated + "\n\n[用户补充] " + extra
            rounds += 1
    finally:
        await GoogleGenAIClientSingleton.cleanup()


if __name__ == "__main__":
    asyncio.run(main_async())
