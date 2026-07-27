# -*- coding: utf-8 -*-
from main import chat_api
    
import asyncio
import json
from datetime import datetime
from fastapi import Request

from utils.oss_client import oss_singleton_client

async def test_mindsearch(print_chunk: bool = False):
    body = {

        # Finance search
        #"user_prompt": "康方医药股价近期波动", 
        #"user_prompt": "康方医药股价近期波动原因分析",
        #"user_prompt": "APPLE最新股价新闻", 

        # PubMed
        #"user_prompt": "偏头疼致病机理最新研究进展", 
        "user_prompt": "The patient is 68 years old. Diagnosed with colorectal tumor and presenting with fever. After administration of 2 ml of compound aminopyrine and phenobarbital injection, the fever persisted. Following the use of 30 mg of indomethacin suppository, the patient’s temperature decreased temporarily but then spiked again. May I continue using 30 mg of indomethacin suppository? Please provide me with some medical diagnostic advice, as I will diagnose it to the patient and medince.", 

        # General
        #"user_prompt": "偏头疼常用药",
        #"user_prompt": "give me a short joke",

        "agent": "mindsearch",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearchchina(print_chunk: bool = False):
    body = {
        "user_prompt": "偏头疼最新研究进展", 
        "agent": "mindsearchofficialsitechina",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearchreferchina(print_chunk: bool = False):
    body = {
        'user_prompt': '请解读这篇文献的创新点和临床意义', 
        'history_messages': [], 
        'agent': 'mindsearchworkflowreferchina', 
        'params': {
            'language': 'CN', 
            'model': '', 
            'enable_rag': False, 
            'files': [],
            'user': 'roche_chinese_drug_department/814@enterprise.local',
            'background': """Selected conference data: {'results': [{'presentation_id': '59c0a416-0f78-419c-96de-7fec77220fd9', 'session_title': 'High-Impact Clinical Trials - 2', 'presentation_title': 'Beyond Clinical Response in the REGENCY Trial: The Impact of Obinutuzumab on Histologic Remission in Patients with Active Lupus Nephritis', 'presentation_type': 'Oral', 'presentation_study_type': 'Phase III, randomized, double-blind, obinutuzumab plus standard therapy vs placebo', 'presentation_website': 'https://www.asn-online.org/education/kidneyweek/2025/program-abstract.aspx?controlId=4393943', 'main_author': 'Rovin, Brad', 'main_author_institution': 'The Ohio State University College of Medicine, Columbus, Ohio, United States', 'authors': ['Rovin, Brad', 'Alberton, Valeria Gabriela', 'Gonçalves Martins, Elsa', 'Garg, Jay P.', 'Santiago, Mittermayer Barreto', 'Aroca Martinez, Gustavo', 'Irazoque, Fedra C', 'Baczkowska, Teresa M', 'Alfaro, Jose', 'Ravelo, Jorge Luis', 'Furie, Richard', 'Pinto, Luis Fernando', 'Albiero, Eduardo Horacio', 'Larsen, Christopher Patrick', 'Pulley, Jennifer A', 'Schindler, Thomas', 'Omachi, Theodore A.', 'Pendergraft, William Franklin', 'Malvar, Ana'], 'institutions': ['The Ohio State University College of Medicine, Columbus, Ohio, United States', 'Fernández Hospital, Buenos Aires, Argentina', 'F. Hoffmann-La Roche Ltd, Basel, Switzerland', 'Genentech, Inc., San Francisco, California, United States', 'Bahiana School of Medicine and Public Health and UFBA, Federal University of Bahia, and Clínica SER da Bahia, Salvador, Brazil', 'Universidad Simón Bolívar, Barranquilla, Colombia y Clínica de la Costa, Barranquilla, Colombia', 'Centro de Investigación y Tratamiento Reumatológico S.C., Mexico City, Mexico', 'Medical University of Warsaw, Warsaw, Poland', 'Instituto Peruano del Hueso y la Articulación, Lima, Peru', 'Clinica San Juan Bautista, Unidad de Investigacion en Reumatologia e Inmunologia, Lima, Peru', 'Division of Rheumatology, Northwell Health, Great Neck, New York, United States', 'Hospital Pablo Tobon Uribe, Medellín, Antioquia, Colombia', 'Sanatorio Allende, Córdoba, Córdoba Province, Argentina', 'Arkana Laboratories, Little Rock, Arkansas, United States', 'Roche Products Ltd, Welwyn Garden City, United Kingdom', 'F. Hoffmann-La Roche Ltd, Basel, Switzerland', 'Genentech, Inc., San Francisco, California, United States', 'Genentech, Inc., San Francisco, California, United States', 'Organización Médica de Investigación, Buenos Aires, Argentina'], 'abstract': 'BACKGROUND\\n\\nThe REGENCY trial (NCT04221477) randomized adults with active lupus nephritis (LN) to placebo or obinutuzumab plus standard therapy (PBO+ST; OBI+ST). At Week 76 (W76), significantly more OBI+ST patients (pts) vs PBO+ST pts achieved complete renal response (CRR) (46.4% vs 33.1% [adjusted difference 13.4%, 95% CI, 2.0% to 24.8%; P=0.0232]). Evaluating histologic changes of paired baseline and W76 biopsies, we postulated that OBI+ST would yield greater rates of histologic remission at W76 than PBO+ST.\\n\\n\\n\\nMETHODS\\n\\nSixty-four (32 OBI+ST, 32 PBO+ST) blinded baseline and W76 biopsies were interpreted by Arkana Laboratories using 2018 ISN/RPS LN classification and NIH activity index (AI) and chronicity index. Proportions of pts achieving histologic or near-histologic remission (AI=0 or AI≤1) were determined.\\n\\n\\n\\nRESULTS\\n\\nBaseline characteristics were balanced and consistent with the overall REGENCY cohort (Table 1). Significantly more pts achieved AI≤1 or AI=0 with OBI+ST vs PBO+ST at W76 (Figure 1). For pts who did not achieve CRR, 52.6% (10/19) in the OBI+ST group had AI=0 at W76 vs 8.3% (2/24) in the PBO+ST group.\\n\\n\\n\\nCONCLUSION\\n\\nIn the largest longitudinal kidney biopsy cohort ever reportedfor a registrational LN clinical trial, significantly more pts treated with OBI+ST achieved complete and/or near-complete histologic remission vs PBO+ST. The higher proportion of pts achieving histologic remission vs CRR suggests that the impact of OBI in LN is greater than that implied by CRR rate. Achieving histologic remission reduces future LN flare risk and should preserve functional kidney mass.\\n\\n\\n', 'design': 'Randomized, double-blind, phase III', 'efficacy': 'At Week76, 46.4% of obinutuzumab+standard therapy patients achieved complete renal response vs 33.1% for placebo+standard therapy (adjusted difference 0.134, 95% CI: 0.02 to 0.248, P=0.0232). For histologic remission (NIH activity index=0), 52.6% (10/19) of non-CRR obinutuzumab+ST patients achieved AI=0 vs 8.3% (2/24) in placebo+ST. Significantly more patients achieved AI≤1 or AI=0 with obinutuzumab+ST vs placebo+ST at Week 76.', 'safety': 'Not Reported', 'summary': ['REGENCY trial evaluated obinutuzumab plus standard therapy vs placebo in active lupus nephritis.', 'Significantly higher complete renal response rate with obinutuzumab+ST (46.4%) vs placebo+ST (33.1%) at Week 76.', 'Histologic remission rates (AI=0 or ≤1) were higher in obinutuzumab+ST group, even among non-CRR patients.', 'Largest longitudinal kidney biopsy cohort in a registrational LN trial.', 'Histologic remission may better predict long-term kidney outcomes than clinical response alone.'], 'drugs': ['Obinutuzumab', 'Standard therapy', 'Placebo'], 'diseases': ['Active lupus nephritis, relapsed/refractory'], 'targets': ['CD20'], 'phases': ['III'], 'series_id': '7d7d3d09-c079-489f-9774-256942ef5749', 'series_name': 'American Society of Nephrology Kidney Week', 'series_abbreviation': 'ASN Kidney Week', 'series_organization': 'American Society of Nephrology', 'series_website': 'https://www.asn-online.org/education/kidneyweek/', 'series_area': None, 'conference_id': '9a2e6e32-7921-4cca-8b09-ca64c51b7275', 'conference_name': 'ASN Kidney Week 2025', 'conference_abbreviation': 'ASN 2025', 'conference_website': 'https://www.asn-online.org/education/kidneyweek/2025/meeting-overview.aspx', 'conference_start_date': '2025-11-05', 'conference_end_date': '2025-11-09', 'conference_location': 'Houston, TX, USA'}], 'data_type': 'conference_presentation', 'total_count': 1, 'from_n': None, 'size': None}""", 
            'reference': '9a2e6e32-7921-4cca-8b09-ca64c51b7275', 
            'reference_type': 'conference_v1'},
            'is_hitl': True
        }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearch_history_attachments(print_chunk: bool = False):
    body = {

        "user_prompt": "请翻译附件的摘要",
        #"user_prompt": "give me a short joke",

        "agent": "mindsearchofficialsite",
        "history_messages": [{
            "role": "user",
            "content": "请仔细阅读附件，并简单总结",
        }, {
            "role": "assistant",
            "content": """直接结论：DeepSeek‑V3.2 是一款面向开放式大型语言模型的长上下文、高效注意力与大规模后训练（RL）相结合的系统化方案。其三大核心贡献为（1）DeepSeek Sparse Attention（DSA）——显著降低长序列注意力计算成本；（2）可扩展且稳定的 RL 后训练框架（改进 GRPO 等技术与扩大 RL 预算）以提升推理与代理能力；（3）大规模合成 agentic 任务流水线（数千环境与万级提示）用于提升工具使用与泛化。高算力变体 DeepSeek‑V3.2‑Speciale 在若干推理/竞赛基准上达到或超过闭源前沿模型的成绩（例如 IMO/IOI/ICPC 等金牌级表现），但在知识覆盖（训练 FLOPs）与 token 效率上仍存在限制。[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D)

---

## 简要概述
DeepSeek‑V3.2 在模型架构与后训练两个层面同时发力：在架构上引入 DSA（lightning indexer + 精细 token 选择）以把注意力复杂度从 O(L^2) 降到 O(L·k) 并保持长上下文性能；在后训练上通过放大 RL 计算（RL 预算 >10% 的 pre‑training 成本）、专科蒸馏（specialist distillation）与混合 RL（mixed RL）训练，把推理能力和 agent 能力联合优化；同时构建大规模合成与真实工具交互的 agent 任务集来增强泛化与工具调用能力。[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D)

---

## 关键点对照表

| 关键点 | 具体做法 / 重要细节 | 带来的效果 / 结果 |
|---|---:|---|
| DeepSeek Sparse Attention (DSA) | lightning indexer + fine‑grained top‑k key‑value 选择；在 MLA/MQA 下实现并可用 FP8；训练流程包含 dense warm‑up（2.1B tokens）与 sparse stage（约943.7B tokens，k=2048）[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D) | 将主注意力复杂度由 O(L^2) 降为 O(L·k)，在 128K 上下文下显著降低推理成本且保持或提升长上下文性能；端到端速度与成本均优化[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D) |
| 可扩展 RL 后训练（基于 GRPO） | 改进点包括无偏 KL 估计、Off‑Policy Sequence Masking、Keep Routing（MoE 路由一致性）、Keep Sampling Mask 等；合并 reasoning/agent/alignment 为单阶段 RL | 提升训练稳定性与可扩展性，使得增加 RL 预算能持续带来性能提升（本文分配的 RL 预算已超过预训练的 10% 并观察到收益）[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D) |
| 大规模 agentic 任务合成流水线 | 生成并筛选真实/合成环境（如 code agent、search agent、code interpreter、general agent），合成 1,827 个环境并产出 ~85,000+ 复杂提示/样本；并用验证 agent 进行多轮校验 | 为 RL 提供了多样且可验证的数据，能把在合成任务上学习到的能力迁移到真实工具使用基准，显著提高 agent 性能与泛化[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D) |
| 专家蒸馏 + 混合 RL | 为多个领域训练 specialist，再蒸馏回主模型；同时在一个 RL 阶段合并不同目标（reasoning/agent/alignment） | 蒸馏数据能快速接近 specialist 性能，混合 RL 避免灾难性遗忘并实现跨域平衡性能[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D) |
| 变体与效果 | DeepSeek‑V3.2（成本/效率优化）与 DeepSeek‑V3.2‑Speciale（高算力、放宽长度惩罚用于极限推理） | V3.2 在多数推理与 agent 基准上与 GPT‑5‑high 接近；Speciale 在多项数学/编程竞赛达到金牌级或优于部分闭源模型，但 token 效率较差且代价更高[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D) |
| 局限 | 知识覆盖受限于总 FLOPs；生成轨迹通常更长（token 效率低）；仍落后于最前沿闭源模型的某些方面 | 需要通过扩大预训练 FLOPs、提升推理/推理链的“智力密度”与减少冗余自检来改进[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D) |

---

## 补充说明（要点与限制）
- 训练/上下文要点：基线上下文扩展到 128K，warm‑up 用 2.1B tokens，稀疏训练阶段用 ~943.7B tokens；DSA 在实际 H800 集群测得推理成本显著下降。[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D)  
- RL 可扩展技术细节：提出了无偏 KL 估计、序列掩码以过滤高离线偏差样本、保持 MoE 路由与采样掩码一致性等多项工程/算法改进以保证大规模 RL 稳定性与效率。[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D)  
- Agent 数据与流水线：结合真实工具（搜索 API、Jupyter、代码环境）与合成环境，总计生成数千可验证环境与上万训练样本，示例包括 trip‑planning 等可自动校验的任务设计；实验证明在某些合成任务上 RL 可以有效迁移至真实基准。[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D)  
- 评测摘要：在 MMLU‑Pro、GPQA、HLE、LiveCodeBench、Codeforces、AIME/HMMT/IMO 等多个 benchmark 上给出详细结果（论文内表格），总体上 V3.2 与 GPT‑5‑high 可比，Speciale 在部分基准优于或可比 Gemini‑3.0‑Pro（含 IMO/IOI/ICPC 金牌成果），但仍存在 token 效率与知识规模差距。[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D)  
- 实践建议（论文暗含）：如果关注部署成本与响应延迟，优先使用 V3.2 变体；若追求极限推理结果并接受更高代价，可采用 Speciale 风格的大规模 RL 与较少长度惩罚的策略。[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D)

---

## 一句话结论
DeepSeek‑V3.2 通过架构级稀疏注意力与可扩展、工程化的后训练（RL）与大规模 agentic 数据流水线，有效缩小了开源模型与闭源前沿系统间的性能差距，但仍需在预训练规模（知识覆盖）与生成 token 效率上进一步优化以达到长期可部署的全面竞争力。[1](https://noahdevuser.blob.core.windows.net/nudata/attachments/123%40qq.com/1766218396-paper.pdf?st=2025-12-28T07%3A53%3A24Z&se=2025-12-29T07%3A53%3A24Z&sp=r&sv=2025-07-05&sr=b&sig=8yFWEbb5vNKFDWJFQUPYLsqomV7amWyKsJppG1j5t24%3D)

若需要，我可以基于论文中的具体章节（如 DSA 数学推导、GRPO 的无偏 KL 推导、或合成任务流水线的具体实现伪代码）进一步展开每一部分的技术细节或复述其中的关键公式与实验数值。""",
        }],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
            "history_files":[
                ["5e1113be-0c79-4ec0-8faa-16a29c2e6a38"],
            ],
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearch_images(print_chunk: bool = False):
    body = {
        "user_prompt": "怎么了", 
        "agent": "mindsearchofficialsite",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
            "files": ['a42ac340-b3e5-4fdb-b843-ca354ec98040'],
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearch_norag(print_chunk: bool = False):
    body = {
        "user_prompt": "苯甲酸利扎曲普坦的不良反应是什么",
        "agent": "mindsearchofficialsite",
        "history_messages": [
            {
                "role": "user",
                "content": "苯甲酸利扎曲普坦和佐米曲普坦哪个效果更好"
            },
            {
                "role": "assistant",
                "content": """在比较苯甲酸利扎曲普坦和佐米曲普坦的疗效时，需要考虑多方面的因素，包括药物的成分、适应症、临床试验结果、副作用以及患者的偏好等。以下是对这两种药物的详细分析：

## 苯甲酸利扎曲普坦

### 成分与规格
- 活性成分：利扎曲普坦
- 剂型：口服片剂和口腔崩解片

### 适应症
- 用于治疗有或无先兆的偏头痛发作，适用于成人和6至17岁的儿童。

### 临床试验与疗效
- 临床试验表明，利扎曲普坦在急性偏头痛的治疗中至少与其他口服偏头痛特异性药物一样有效，甚至优于其他药物。其快速缓解疼痛的能力受到患者的偏好[1](https://pmc.ncbi.nlm.nih.gov/articles/PMC2671815/)[2](https://www.ncbi.nlm.nih.gov/books/NBK116760/)。

### 副作用
- 常见不良反应包括头晕、嗜睡、疲劳和恶心。这些不良反应通常是短暂的，且强度为轻至中度。

### 禁忌症与注意事项
- **禁忌症**：
  - 不适用于有缺血性冠心病、未控制的高血压、脑卒中或短暂性脑缺血发作史的患者。
  - 正在使用单胺氧化酶抑制剂的患者。

## 佐米曲普坦

### 成分与规格
- 活性成分：佐米曲普坦
- 剂型：口服片剂、口腔崩解片和鼻喷剂

### 适应症
- 用于治疗急性偏头痛，适用于成人和12岁及以上的儿童。

### 临床试验与疗效
- 佐米曲普坦在改善偏头痛相关症状（如恶心、畏光和畏声）方面表现出良好的疗效。其鼻喷剂形式能够快速起效，在15分钟内即显示出效果[4](https://pubmed.ncbi.nlm.nih.gov/30698272/)[5](https://pubmed.ncbi.nlm.nih.gov/12828501/)。

### 副作用
- 常见不良反应包括味觉异常、鼻腔刺激、头晕和疲劳。大多数不良反应为轻度至中度且短暂。

### 禁忌症与注意事项
- **禁忌症**：
  - 与其他曲坦类药物相似，可能增加心血管事件的风险，尤其是在有心脏病史的患者中。

## 比较研究

- 一项研究比较了利扎曲普坦（10 mg）和佐米曲普坦（2.5 mg）在急性偏头痛治疗中的疗效。结果显示，利扎曲普坦在服药后60分钟内更快缓解疼痛，2小时后更多患者无痛（43.2% vs. 35.6%），且光敏感和恶心症状较少[11](https://pubmed.ncbi.nlm.nih.gov/11037741/)。
- 利扎曲普坦通常在30分钟内起效，而佐米曲普坦通常在2小时内起效[10](https://www.goodrx.com/compare/maxalt-vs-zomig)。

综上所述，苯甲酸利扎曲普坦和佐米曲普坦在治疗偏头痛方面各有优劣。利扎曲普坦因其快速缓解疼痛的能力而受到患者偏好，而佐米曲普坦的鼻喷剂形式则提供了便利性。选择哪种药物应根据患者的具体需求、药物的副作用、给药方式以及患者的偏好进行。""",
            }
        ],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)


async def test_mindsearch_history(print_chunk: bool = False):
    body = {
        # General
        "user_prompt": "效果最好的CGRP是哪款？",

        "agent": "mindsearch",
        "history_messages": [{'role': 'user', 'content': '偏头疼常用药物有哪些'}, {'role': 'assistant', 'content': '## 偏头痛常用药物总览  \n\n临床用药分为  \n1) 急性期止痛/缓解（acute/abortive）；  \n2) 预防/减少发作频率（preventive/prophylaxis）。  \n\n下面列出各自推荐的一线与常用药，并给出典型成人剂量及主要不良反应，方便快速查阅与处方时参考。\n\n### 1. 急性期常用药  \n\n| 药物（类别） | 代表制剂 & 常用成人剂量* | 备注/主要不良反应 |\n|--------------|-------------------------|------------------|\n| NSAIDs & 对乙酰氨基酚 | • 布洛芬 400-800 mg PO<br>• 双氯芬酸钾 50-100 mg PO<br>• 对乙酰氨基酚 1000 mg PO | 胃肠不适、溃疡/出血风险；乙酰氨基酚大剂量肝毒性[2](https://www.aafp.org/pubs/afp/issues/2018/0215/p243.html) |\n| 复方镇痛 | 乙酰氨基酚+阿司匹林+咖啡因（Excedrin Migraine®）2 片 | 咖啡因可触发心悸、焦虑；长期易“药物过度性头痛”[3](https://www.ncbi.nlm.nih.gov/books/NBK553159/) |\n| 曲普坦 (5-HT1B/1D 激动剂) | • 苏美曲坦 50-100 mg PO；6 mg SC<br>• 利扎曲坦 5-10 mg PO<br>• 依来曲坦 40 mg PO | 胸部/咽部压迫感、颜面潮红；禁用于冠脉病/严重高血压[1](https://www.uptodate.com/contents/acute-treatment-of-migraine-in-adults) |\n| CGRP 小分子拮抗剂 (gepant) | • 乌布瑞吉潘 50-100 mg PO<br>• 瑞美吉潘 75 mg ODT<br>• 扎夫瑞吉潘 10 mg 鼻喷 | 口干、嗜睡；可用于合并心血管疾病患者[21](https://www.mayoclinic.org/diseases-conditions/migraine-headache/diagnosis-treatment/drc-20360207) |\n| 5-HT1F 激动剂 | 拉斯米地坦 50-200 mg PO | 明显嗜睡、眩晕→服药后 8 h 内禁止驾驶[14](https://www.mayoclinic.org/diseases-conditions/migraine-with-aura/diagnosis-treatment/drc-20352077) |\n| 麦角胺类 | 二氢麦角胺 0.5-1 mg IM/SC 或鼻喷 0.5 mg | 恶心呕吐↑，须合并止吐药；禁用于妊娠、外周血管病[3](https://www.ncbi.nlm.nih.gov/books/NBK553159/) |\n| 止吐药（伴重度恶心时） | 甲氧氯普胺 10-20 mg IV/PO<br>丙氯拉嗪 10 mg IV/PO | 锥体外系反应，可加苯海拉明预防[2](https://www.aafp.org/pubs/afp/issues/2018/0215/p243.html) |\n\n\\*PO=口服；SC=皮下注射。所有口服药物在“头痛加重前尽早、单次足量”效果最佳[1](https://www.uptodate.com/contents/acute-treatment-of-migraine-in-adults)。  \n\n#### 小贴士  \n• ≥2 次/周使用急性药物提示需评估预防治疗；过度使用（>10-15 d/月）可诱发“用药过度性头痛”[8](https://www.ncbi.nlm.nih.gov/books/NBK538150/)。  \n\n### 2. 预防用药  \n\n| 首选等级 | 药物（类别） | 起始-常用剂量区间 | 常见不良反应 & 适用要点 |\n|----------|--------------|-------------------|------------------------|\n| 一级推荐（循证最强） | β受体阻滞剂：普萘洛尔 40→160-320 mg/d<br>美托洛尔 25→100-200 mg/d | 疲劳、低血压、梦魇；哮喘禁用[12](https://www.aafp.org/pubs/afp/issues/2019/0101/p17.html) |\n| | 抗癫痫药：托吡酯 25→50-100 mg bid<br>丙戊酸/二乙酸丙戊酸 250→500 mg bid | 体重变化、感觉异常；丙戊酸致胎畸风险—育龄女性慎用[11](https://www.ncbi.nlm.nih.gov/books/NBK507873/) |\n| | CGRP 单抗（月/季注射）：Erenumab 70-140 mg SC q4w；Fremanezumab 225 mg q4w / 675 mg q12w 等 | 注射部位反应、便秘；价格高，多用于三线失败后[22](https://secure.medicalletter.org/TML-article-1678a) |\n| 二级推荐 | 三环类抗抑郁：阿米替林 10→25-75 mg qHS | 口干、嗜睡、体重↑；兼治失眠/抑郁[12](https://www.aafp.org/pubs/afp/issues/2019/0101/p17.html) |\n| | 钙通道阻滞剂：氟桂利嗪 5-10 mg qHS；维拉帕米 120-240 mg/d | 体重↑、嗜睡；心动过缓时慎用[11](https://www.ncbi.nlm.nih.gov/books/NBK507873/) |\n| | ARB/ACEI：坎地沙坦 8→16-32 mg/d；利辛普利 5→20 mg/d | 低血压、咳嗽(ACEI)；兼治高血压[12](https://www.aafp.org/pubs/afp/issues/2019/0101/p17.html) |\n| 三线及特殊情况 | OnabotulinumtoxinA 155-195 U 逐肌注 q12w（仅用于慢性偏头痛≥15 d/月） | 注射部位疼痛、颈部无力[12](https://www.aafp.org/pubs/afp/issues/2019/0101/p17.html) |\n| | 经期相关：福罗瓦曲坦 2.5 mg bid ×5 d；布洛芬 400 mg tid ×5 d （围经期） | 短程序贯预防，经期第一天前开始[11](https://www.ncbi.nlm.nih.gov/books/NBK507873/) |\n\n### 3. 处方与随访要点  \n\n1. 启动预防治疗指征：  \n   • ≥4 次头痛/月或 ≥8 头痛日/月；  \n   • 急性药物疗效差或禁忌；  \n   • 特殊亚型（基底/偏瘫型等）或患者意愿[12](https://www.aafp.org/pubs/afp/issues/2019/0101/p17.html)。  \n\n2. 起始低剂量→每 2-4 周缓慢滴定，至少连续 8-12 周方可评估疗效（目标：头痛频率或天数↓≥50%）。  \n\n3. 建议患者保持“头痛日记”，记录频率、严重度与用药，用于评估疗效及避免用药过度。  \n\n4. 预防成功 ≥6-12 个月后，可考虑逐渐减量停药以评估是否仍需长期治疗。  \n\n### 4. 简明决策路径  \n\n```\n轻-中度发作 → NSAID/对乙酰氨基酚（±止吐药）  \n中-重度或NSAID无效 → 曲普坦（首选）  \n心血管疾病不能用曲普坦 → Gepant 或 拉斯米地坦  \n仍难控制 → DHE、静脉止吐药、急诊处理  \n≥2次/周使用急性药物 → 评估预防治疗（β阻滞剂/托吡酯/丙戊酸…）  \n多线失败 → CGRP 单抗、Botox、神经调控设备\n```\n\n---\n\n**参考剂量基于成年患者；老年、儿童、肝肾功能异常者需个体化调整。**  \n以上信息来自 UpToDate、AAFP 临床综述与 StatPearls 最新药物章节等权威文献[1](https://www.uptodate.com/contents/acute-treatment-of-migraine-in-adults)[2](https://www.aafp.org/pubs/afp/issues/2018/0215/p243.html)[11](https://www.ncbi.nlm.nih.gov/books/NBK507873/)。'}],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearchpatent(print_chunk: bool = False):
    body = {
        "user_prompt": "偏头疼常用单抗药物有哪些",
        "agent": "mindsearchpatent",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearchmedical(print_chunk: bool = False):
    body = {
        "user_prompt": """在PubMed数据库等学术资源中检索关于食管鳞状细胞癌(ESCC)中Notch1过度表达及激活性突变的研究，重点关注免疫组化和基因测序数据的大型队列研究、TCGA数据库分析、系统性回顾和荟萃分析，并统计其发生率/突变频率，时间范围2010-2025。

query_params: 搜索词: "食管鳞状细胞癌 Notch1 过度表达 激活性突变 发生率 免疫组化 基因测序"; 英文搜索词: "esophageal squamous cell carcinoma ESCC Notch1 overexpression activating mutation frequency prevalence immunohistochemistry gene sequencing"
; 附加搜索词: "Notch1 expression ESCC cohort study mutation rate TCGA database"; 重点关注: PubMed数据库、大型队列研究、癌症基因组图谱(TCGA)数据、系统性回顾和荟萃分析; 时间范围: 2010-2025

Note: Please don't make assumptions on data (especially data that can easily be verified such as stock price and NCT ids) and don't make up citations, only use whatever context/data has been provided to you.""",
        "agent": "mindsearchmedical",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearchrefer_discovery():
    body = {
        "user_prompt": "Promising CRISPR Therapy will be success?",
        "agent": "mindsearchrefer",
        "history_messages": [],
        "params": {
            "background": """Selected article content: Title: Intellia's Promising CRISPR Therapy for Hereditary Angioedema Faces Market Challenges
Intellia Therapeutics has reported encouraging Phase II results for its CRISPR-based therapy, NTLA-2002, showing an 81% reduction in hereditary angioedema attacks. The treatment was well-tolerated and showed potential as a functional cure. However, the company faced a significant stock drop due to unmet investor expectations and competition from other therapies demonstrating higher efficacy. Intellia plans to further investigate the therapy's capabilities in a Phase III trial despite market challenges.

Intellia's CRISPR Breakthrough in Phase II Study
Intellia Therapeutics has reported encouraging Phase II data for its CRISPR-based therapy, NTLA-2002, aimed at treating hereditary angioedema (HAE), showcasing an 81% reduction in monthly attack rates for patients receiving the 50 mg dose over the weeks five to 16 period[1][2]. In this cohort, 8 out of 11 patients experienced complete response, remaining attack-free over a median follow-up of eight months, highlighting the potential of NTLA-2002 to serve as a long-term solution[2][3]. Despite these promising outcomes, Intellia's shares fell by 9% amid market concerns, driven by high previous expectations and competition from emerging therapies[1].

Details and Efficacy of NTLA-2002
Intellia Therapeutics' NTLA-2002 has shown impressive Phase II results as a CRISPR-based therapy for hereditary angioedema (HAE). The therapy demonstrated an 81% reduction in monthly attack rates at a 50-mg dose from weeks five to 16[1][2]. Impressively, eight out of 11 patients on this dose achieved a complete response, remaining attack-free over a median follow-up of eight months, highlighting the therapy's potential as a functional cure[2][3]. Despite its efficacy and safety profile, market challenges and high expectations have impacted Intellia's stock as the therapy progresses towards a Phase 3 trial[1][2].

Market Reactions and Stock Impact
Intellia Therapeutics recently faced a challenging market reaction following the announcement of their Phase II trial results for NTLA-2002, a CRISPR therapy aimed at treating hereditary angioedema. Despite the promising data showing up to an 81% reduction in attack rates with the 50 mg dose, Intellia's stock dropped by approximately 9% to 20% in premarket trading[1][3]. The decline is attributed to market concerns over competition and high expectations based on prior data, as well as questions surrounding the novelty and potential safety of the therapy[2]. Despite this, analysts remain cautiously optimistic about NTLA-2002's potential as it advances to late-stage development[1].

Comparative Analysis with Competitors
Intellia's CRISPR therapy, NTLA-2002, faces significant competition in the hereditary angioedema (HAE) market, particularly from companies like Pharmaaris, which reported a 93% reduction in attack rates—surpassing Intellia's 81% reduction at a 50 mg dose[1]. Despite achieving a promising 81% reduction, the comparatively lower efficacy and the novel approach of a CRISPR-based therapy create additional market perception challenges[2]. Competitors like BioCryst with Orladeyo and Takeda’s Takhzyro are already established, offering traditional treatments and creating a competitive landscape Intellia must navigate[2].

Future Directions and Phase III Plans
Intellia Therapeutics is planning to advance NTLA-2002 into a Phase III trial to further validate its promising Phase II outcomes for hereditary angioedema (HAE). The therapy demonstrated an 81% reduction in monthly attack rates at the 50-mg dose, with patients experiencing sustained benefits, positioning NTLA-2002 as a potential game-changer[1][2]. The forthcoming larger Phase III trial aims to confirm efficacy and evaluate safety further, with hopes for a potential 2026 approval[2]. Despite facing market challenges and investor skepticism, the durable efficacy and safety profile of NTLA-2002 are central to Intellia's strategy, marking a significant shift away from traditional treatments[3].

Intellia Therapeutics' promising Phase II results for NTLA-2002 highlight the therapy's potential to significantly reduce hereditary angioedema attacks and potentially serve as a one-time cure. Despite strong data, Intellia's stock suffered due to high market expectations and formidable competition. As the company moves toward a Phase III trial, it will need to demonstrate consistent efficacy and address market concerns. The future success of NTLA-2002 hinges on overcoming these hurdles and proving itself as a viable alternative to traditional treatments, setting a new precedent in gene-based therapies.""",
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body)

async def test_mindsearchrefer_history():
    body = {
        "user_prompt": "CRISPR基础疗法有哪些已经投产的产品？",# no need web search
        #user_prompt="Could give me more detail of the company in the article?",
        "agent": "mindsearchrefer",
        "history_messages": [
            {
                "role": "assistant",
                "content": """## Raw issue content: Title: Intellia's Promising CRISPR Therapy for Hereditary Angioedema Faces Market Challenges
Intellia Therapeutics has reported encouraging Phase II results for its CRISPR-based therapy, NTLA-2002, showing an 81% reduction in hereditary angioedema attacks. The treatment was well-tolerated and showed potential as a functional cure. However, the company faced a significant stock drop due to unmet investor expectations and competition from other therapies demonstrating higher efficacy. Intellia plans to further investigate the therapy's capabilities in a Phase III trial despite market challenges.

Intellia's CRISPR Breakthrough in Phase II Study
Intellia Therapeutics has reported encouraging Phase II data for its CRISPR-based therapy, NTLA-2002, aimed at treating hereditary angioedema (HAE), showcasing an 81% reduction in monthly attack rates for patients receiving the 50 mg dose over the weeks five to 16 period[1][2]. In this cohort, 8 out of 11 patients experienced complete response, remaining attack-free over a median follow-up of eight months, highlighting the potential of NTLA-2002 to serve as a long-term solution[2][3]. Despite these promising outcomes, Intellia's shares fell by 9% amid market concerns, driven by high previous expectations and competition from emerging therapies[1].

Details and Efficacy of NTLA-2002
Intellia Therapeutics' NTLA-2002 has shown impressive Phase II results as a CRISPR-based therapy for hereditary angioedema (HAE). The therapy demonstrated an 81% reduction in monthly attack rates at a 50-mg dose from weeks five to 16[1][2]. Impressively, eight out of 11 patients on this dose achieved a complete response, remaining attack-free over a median follow-up of eight months, highlighting the therapy's potential as a functional cure[2][3]. Despite its efficacy and safety profile, market challenges and high expectations have impacted Intellia's stock as the therapy progresses towards a Phase 3 trial[1][2].

Market Reactions and Stock Impact
Intellia Therapeutics recently faced a challenging market reaction following the announcement of their Phase II trial results for NTLA-2002, a CRISPR therapy aimed at treating hereditary angioedema. Despite the promising data showing up to an 81% reduction in attack rates with the 50 mg dose, Intellia's stock dropped by approximately 9% to 20% in premarket trading[1][3]. The decline is attributed to market concerns over competition and high expectations based on prior data, as well as questions surrounding the novelty and potential safety of the therapy[2]. Despite this, analysts remain cautiously optimistic about NTLA-2002's potential as it advances to late-stage development[1].

Comparative Analysis with Competitors
Intellia's CRISPR therapy, NTLA-2002, faces significant competition in the hereditary angioedema (HAE) market, particularly from companies like Pharmaaris, which reported a 93% reduction in attack rates—surpassing Intellia's 81% reduction at a 50 mg dose[1]. Despite achieving a promising 81% reduction, the comparatively lower efficacy and the novel approach of a CRISPR-based therapy create additional market perception challenges[2]. Competitors like BioCryst with Orladeyo and Takeda’s Takhzyro are already established, offering traditional treatments and creating a competitive landscape Intellia must navigate[2].

Future Directions and Phase III Plans
Intellia Therapeutics is planning to advance NTLA-2002 into a Phase III trial to further validate its promising Phase II outcomes for hereditary angioedema (HAE). The therapy demonstrated an 81% reduction in monthly attack rates at the 50-mg dose, with patients experiencing sustained benefits, positioning NTLA-2002 as a potential game-changer[1][2]. The forthcoming larger Phase III trial aims to confirm efficacy and evaluate safety further, with hopes for a potential 2026 approval[2]. Despite facing market challenges and investor skepticism, the durable efficacy and safety profile of NTLA-2002 are central to Intellia's strategy, marking a significant shift away from traditional treatments[3].

Intellia Therapeutics' promising Phase II results for NTLA-2002 highlight the therapy's potential to significantly reduce hereditary angioedema attacks and potentially serve as a one-time cure. Despite strong data, Intellia's stock suffered due to high market expectations and formidable competition. As the company moves toward a Phase III trial, it will need to demonstrate consistent efficacy and address market concerns. The future success of NTLA-2002 hinges on overcoming these hurdles and proving itself as a viable alternative to traditional treatments, setting a new precedent in gene-based therapies.
                """
            },
            {
                "role": "user",
                "content": "Could you give me a summary of the article?"
            },
            {
                "role": "assistant",
                "content": """Intellia Therapeutics最近公布了其CRISPR基础疗法NTLA-2002在治疗遗传性血管水肿（HAE）方面的二期临床试验结果，显示出令人鼓舞的效果，患者每月发作率减少了81%。在接受50毫克剂量的患者中，有8名患者在随访8个月的中位时间内完全无发作，显示出该疗法作为长期解决方案的潜力。然而，尽管结果积极，Intellia的股票因未能满足投资者的高期望而下跌了约9%。市场对竞争对手的疗法表现出更高的疗效感到担忧，尤其是Pharmaaris的疗法报告了93%的发作率减少。

尽管面临市场挑战，Intellia计划将NTLA-2002推进至三期临床试验，以进一步验证其疗效和安全性。该公司希望在2026年获得潜在的批准。尽管市场对其疗法的看法存在疑虑，NTLA-2002的持久疗效和安全性仍是Intellia战略的核心，标志着基因治疗领域的重大转变。 processing_type=<ProcessingType.RESPONSING: 2> search_graph=None followup_questions=[] content='Intellia Therapeutics最近公布了其CRISPR基础疗法NTLA-2002在治疗遗传性血管水肿（HAE）方面的二期临床试验结果，显示出令人鼓舞的效果，患者每月发作率减少了81%。在接受50毫克剂量的患者中，有8名患者在随访8个月的中位时间内完全无发作，显示出该疗法作为长期解决方案的潜力。然而，尽管结果积极，Intellia的股票因未能满足投资者的高期望而下跌了约9%。市场对竞争对手的疗法表现出更高的疗效感到担忧，尤其是Pharmaaris的疗法报告了93%的发作率减少。\n\n尽管面临市场挑战，Intellia计划将NTLA-2002推进至三期临床试验，以进一步验证其疗效和安全性。该公司希望在2026年获得潜在的批准。尽管市场对其疗法的看法存在疑虑，NTLA-2002的持久疗效和安全性仍是Intellia战略的核心，标志着基因治疗领域的重大转变。"""
            }
        ],
        "params": {
            "background": '',
            "language": 'CN',
            "model": 'deepseek-r1',
            "enable_rag": False,
        }
    }
    await chat(body=body)

async def test_mindsearchworkflowrefer_conference():
    body = {
        "user_prompt": "哪项研究提供了最有力的证据或采用了最严谨的研究方法?",
        "agent": "mindsearchworkflowrefer",
        "history_messages": [],
        "params": {
            "background": """Selected conference data: [{"abstract":"Pancreatic ductal adenocarcinoma (PDAC) is one of the most lethal types of cancer, characterized by a dismal 5-year overall survival rate, primarily due to lack of early detection and limited effective treatment. Gemcitabine (GEM) is most effective therapy for pancreatic cancer (PanCa), but it only offers a marginal survival benefit of 6 months. A combination of Paclitaxel (PTX) albumin nano-formulation (Abraxane) and GEM has shown marginal improvement in PanCa treatment. This poor treatment response has been associated with desmoplastic stroma, microbiome effects, altered tumor microenvironment (TME), suppressive immune cells and PDAC-specific signaling pathways. Our research has demonstrated that MUC13 is highly overexpressed in PanCa and is associated with cancer progression and metastases. Considering these facts, we have generated an MUC13 antibody targeted nanoparticle formulation for tumor specific targeted delivery of paclitaxel using a multi-layered Pluronic F127 and polyvinyl alcohol stabilized and poly-L-lysine coated poly(lactic-co-glycolic acid) nanoparticles (PPNPs) to improve therapeutic outcome of PanCa therapy. Our MUC13-targeted PPNPs (MUC13-PPNPs) showed enhanced cellular uptake of MUC13-PPNPs formulation in HPAF-II (MUC13+) compared with Panc-1 (MUC13­) PanCa cells as determined by immunofluorescence. Further, our novel formulation effectively inhibits growth and metastatic phenotypes in MUC13+ cells as compared with MUC13- cells of PanCain vitro.In our PanCa xenograft mouse model (HPAF-II + stromal cells), we found that PPNPs alone significantly inhibited growth of tumor (P < 0.05 when compared with control (PLGA) and treatment group PTX. Furthermore, the tumor volume of MUC13-PPNPs group was not only highly significantly lower than control PLGA and PTX (P < 0.05), but also lower than PPNPs alone group (P < 0.05) or control (P < 0.05). Our findings also demonstrated that PPNPs/MUC13-PPNPs synergize GEM therapy responsein vitroandin vivomouse models. Further, tumor tissue treated with PPNPs/MUC13-PPNPs demonstrate the downregulated expression of sonic hedgehog and other oncogenic signaling axis determined by qPCR, Western blots, and immunofluorescence analyses. Additionally, our nano formulation effectively reduced tumor volume in syngeneic orthotopic xenograft mouse model involving injection of KPC-Luc in C57Black/6 mice and target tumor-associated macrophages (TAM) by repolarizing M2 into M1 phenotypeviainhibiting expression of M2 markers and an increase in M1 markers. In conclusion, we observed that our novel formulation has high therapeutic ability for achieving pancreatic tumor specific delivery PTX, synergize GEM therapy response and altered the tumor immune surveillance mechanisms. Thus, this unique approach can effectively enhance therapeutic efficacy main line chemotherapies and immune checkpoint immunotherapies.","authors":["Vivek Kumar Kashyap","Neeraj Chauhan","Mohammed Sikander","Eswara N. HK Ghali","Fnu Shabnam","Rahul Tiwari","Sheema Khan","Bilal B. Hafeez","Murali M. Yallapu","Meena Jaggi","Subhash C. Chauhan"],"citation_author":"Vivek Kumar Kashyap","citation_author_institution":"University of Texas Rio Grande Valley, McAllen, TX, TX","citation_title":"MUC13-targeted PPNPs efficiently inhibited pancreatic tumor growth and influenced tumor immune surveillance","design":"Preclinical, nanoparticle, in vitro","disease":"Pancreatic ductal adenocarcinoma","drug":["Paclitaxel","Gemcitabine"],"efficacy":"PPNPs and MUC13-PPNPs reduced tumor volume and synergized GEM response.","id":"6388","link":"https://www.abstractsonline.com/pp8/#!/20273/presentation/3867","organizations":["University of Texas Rio Grande Valley, McAllen, TX, TX"],"phase":"Preclinical","presentation_type":"Poster Session","safety":"Not Reported","session_location":"Section 25","session_time":"April 28, 2025, 9:00 AM - 12:00 PM","session_title":"Session PO.CH01.02 - Drug Delivery","study_type":"Development of nanoparticle delivery system","summary":["Pancreatic ductal adenocarcinoma is highly lethal with poor treatment options.","MUC13-targeted nanoparticles enhance paclitaxel delivery in cancer cells.","MUC13-PPNPs reduce tumor growth in preclinical models.","Synergistic effect with gemcitabine improves therapy response.","New formulation alters immune mechanisms, offering therapeutic potential."],"target":["MUC13"]},{"abstract":"Background: Ad5/3-E2F-D24-hTNFa-IRES-hIL-2 (TILT-123) is an oncolytic adenovirus armed with TNFa and IL-2. The cytokine pairing demonstrated superior tumor immunomodulation in preclinical studies. Subsequent studies supported evaluation of TILT-123 in PROTA, a phase 1 study of TILT-123 in combination with pembrolizumab in platinum resistant or refractory ovarian cancer patients. Biomarker analysis is ongoing.Experimental procedures: In this phase 1a dose escalation trial (NCT05271318), 15 patients received an initial single intravenous dose of TILT-123 ranging from 3x1011to 4x1012VPs , followed by intratumoural and/or intraperitoneal injections ranging from 1x1011to 5x1011VPs. Patients also received i.v. pembrolizumab (200mg) every three weeks starting on day 36. The primary endpoint was safety by day 92, while efficacy by RECIST1.1 and overall survival (OS) were secondary endpoints. Collection of tumour biopsies and blood, including PBMCs and serum, enabled evaluation of MoA and identification of preliminary biomarkers.Summary of data: ORR was 7.1% in evaluable patients (1/14). Disease control rate was 64% in evaluable patients (n = 14) and median OS was 190 days (n =15). Patients with disease control and no disease control by 92 achieved a median OS of 571 days and 138 days respectively. Correlations of complete blood count with differential to OS (n =15) and imaging response (n = 14) revealed a greater drop in lymphocyte count after treatment, as well as baseline lymphocyte count positively correlated with OS and disease control (PR/SD vs PD). Correlation of prothrombin INR to OS revealed patients with a slower blood-clotting rate at baseline and post-treatment positively correlated with OS. Analysis of anti-adenovirus neutralizing antibody (nAb) titer revealed 77% of all patients were positive for nAbs prior to treatment. All patients developed nAbs in blood and ascites (ascites n = 3). Patients presenting with nAbs at baseline achieved longer OS than those not positive. Additionally, a higher titer post-treatment positively correlated with OS and disease control. Percentage and fold change increase in IgM expression on plasma cells on day 36 positively correlated with OS. In addition, a higher expression of IgM on the surface of plasma cells at baseline was observed in patients achieving disease control.Conclusion: These preliminary results identify a key role of circulating lymphocyte re-distribution and humoral immune response as markers of treatment benefit. Initial phenotyping implicates IgM producing plasma cells as a potentially relevant immune cell population. Additionally we observed a correlation between the coagulation cascade and OS.","authors":["James H. A. Clubb","Matthew Block","Johanna Mäenpää","Victor Arias","Mirte Van der Heijden","Santeri Pakola","Dafne C. A. Quixabeira","Tatiana Kudling","Elise Jirovec","Lyna Haybout","Tuomo Alanko","Daniel Adamo","Susan Ramadan","Jorma Sormunen","Juha Kononen","Michael J. Chisamore","Julia W. Cohen","Nadena Singh","John Goldfinch","Suvi Sorsa","Riikka Havunen","Claudia Kistler","João M. Santos","Víctor Cervera-Carrascon","Akseli Hemminki"],"citation_author":"James H. A. Clubb","citation_author_institution":"TILT Biotherapeutics Oy, Helsinki, Finland","citation_title":"Clinical-immunological correlates in platinum resistant or refractory ovarian cancer patients treated with chimeric oncolytic adenovirus encoding TNFa and IL-2 (TILT-123) in combination with pembrolizumab","design":"Dose escalation trial.","disease":"Platinum-resistant ovarian cancer","drug":["TILT-123","Pembrolizumab"],"efficacy":"ORR was 7.1%, Disease control rate was 64%, Median OS was 190 days","id":"6387","link":"https://www.abstractsonline.com/pp8/#!/20273/presentation/4869","organizations":["TILT Biotherapeutics Oy, Helsinki, Finland","Mayo clinic, Rochester, MN, MN","Docrates Cancer Center, Helsinki, Finland","University of Helsinki, Helsinki, Finland","Merck & Co., Inc, Rahway, NJ, NJ","TILT Biotherapeutics Oy, Orchard Park, NY, NY"],"phase":"I","presentation_type":"Poster Session","safety":"Primary endpoint was safety by day 92. Specific safety outcomes not reported.","session_location":"Section 31","session_time":"April 28, 2025, 9:00 AM - 12:00 PM","session_title":"Session PO.CL01.08 - Predictive Biomarkers 3","study_type":"Phase 1a, dose escalation","summary":["TILT-123 combined with pembrolizumab studied in ovarian cancer.","Primary endpoint was safety, with efficacy and OS as secondary endpoints.","ORR was 7.1% and disease control rate was 64%.","Median OS was 190 days.","Lymphocyte count, IgM, and coagulation factors correlated with treatment outcomes."],"target":["TNFa","IL-2"]},{"abstract":"Pancreatic ductal adenocarcinoma (PDAC) is an aggressive malignancy with a high fatality rate. Because there are few effective treatments for advanced pancreatic cancer, the development of new molecular targeted therapies is desired. CD109 is a glycosylphosphatidylinositol-anchored glycoprotein, whose expression is upregulated in some types of malignant tumors. We recently reported that positive expression of CD109 in tumor cells was significantly associated with poor prognosis in PDAC. In addition, CD109 expression was also detected in the stroma surrounding the tumor cells, suggesting its expression in cancer-associated fibroblasts. The stromal CD109 expression significantly correlated with tumor progression in PDAC. In the present study, we aimed to further investigate the histopathological and prognostic significance of CD109 in PDAC using the mouse model. In the normal mouse pancreas, CD109 expression was almost undetectable by X-gal staining and in situ hybridization. In the PDAC tissues, CD109 expression was detected not only in the tumor cells but also in the surrounding stromal cells, which was similar to that in human PDAC. CD109 expression was predominantly detected in undifferentiated tumor cells rather than differentiated tumor cells. In addition, we generated a CD109-deficient PDAC mouse model line, KPC-CD109KO, and it was revealed that CD109-deficinet KPC mice tended to develop differentiated adenocarcinomas compared with KPC mice with wild-type CD109. However, CD109 deficiency did not affect the survival of KPC mouse. Taken together, CD109 is expressed not only in the tumor cells but also in the stroma in PDAC, and is associated with tumor differentiation in PDAC.","authors":["Yoshiki Murakumo","Yasutaka Sakurai","Masaaki Ichinoe"],"citation_author":"Yoshiki Murakumo","citation_author_institution":"Kitasato Univ. School of Medicine, Sagamihara, Japan","citation_title":"Analysis of the pathological significance of CD109 in pancreatic cancer using the mouse model","design":"Not Reported","disease":"Advanced pancreatic cancer","drug":["Not Reported"],"efficacy":"CD109-deficient mice developed differentiated tumors","id":"6386","link":"https://www.abstractsonline.com/pp8/#!/20273/presentation/6752","organizations":["Kitasato Univ. School of Medicine, Sagamihara, Japan"],"phase":"Preclinical","presentation_type":"Poster Session","safety":"Not Reported","session_location":"Section 13","session_time":"April 30, 2025, 9:00 AM - 12:00 PM","session_title":"Session PO.MCB11.02 - Pathological Impact of Oncogenes and Tumor Suppressors","study_type":"Study in PDAC mouse model","summary":["CD109 is upregulated in PDAC tumors.","CD109 associated with poor prognosis in PDAC.","Detected in both tumor and stromal cells.","CD109-deficient mice had differentiated adenocarcinomas.","CD109 deficiency did not affect survival in mice."],"target":["CD109"]},{"abstract":"Triple-negative breast cancer (TNBC) remains the most aggressive subtype of breast cancer, with a high propensity for metastasis. Tumor cell heterogeneity has been closely linked to metastatic progression, therapy resistance, and disease recurrence in solid tumors, including TNBC. Within tumors, metabolic heterogeneity emerges as cancer cells adapt to diverse environmental pressures, further driving tumor aggressiveness. However, the role of metastasis suppressors, such as Raf Kinase Inhibitory Protein (RKIP), in regulating metabolic heterogeneity is not yet fully understood. Analysis of RNA sequencing data from breast cancer patients revealed a strong correlation between RKIP expression and oxidative phosphorylation (OXPHOS) genes. Together with this, by performing gene set enrichment analysis of bulk RNA sequencing of mouse xenografts we observed an enrichment of hallmark of OXPHOS in RKIP-overexpressing tumors compared to controls. Consistent with these findings, RKIP was shown to modulate oxygen consumption rates in vitro. Using stable isotope tracing with [U-13C] glucose in vivo, we observed higher glucose contribution to citrate labeling in RKIP-overexpressing tumors compared to controls. Through single-cell RNA sequencing, we demonstrate that RKIP reduces overall transcriptional heterogeneity, particularly by decreasing the variability of genes involved in mitochondrial respiration. Importantly, treatment with the OXPHOS inhibitor metformin selectively inhibited the growth of RKIP-overexpressing tumors, while control tumors were unaffected. This study suggests that RKIP or drugs that mimic its action have the potential to promote OXPHOS in tumor cells, presenting an opportunity to suppress tumor growth by subsequent therapeutic targeting of mitochondrial respiration in TNBC.","authors":["Joana Pinheiro","Dongbo Yang","Madeline Henn","Long Chi Nguyen","Olga Martinho","Brandon Faubert","Marsha Rich Rosner"],"citation_author":"Joana Pinheiro","citation_author_institution":"University of Chicago, Chicago, IL, IL","citation_title":"Metastasis suppressor RKIP modulates mitochondrial metabolism in triple-negative breast cancer","design":"Xenograft, gene analysis","disease":"Triple-negative breast cancer","drug":["Metformin"],"efficacy":"RKIP reduced transcriptional heterogeneity and promoted OXPHOS, metformin inhibited RKIP-overexpressing tumor growth.","id":"6385","link":"https://www.abstractsonline.com/pp8/#!/20273/presentation/4247","organizations":["University of Chicago, Chicago, IL, IL","University of Minho, Braga, Portugal"],"phase":"Preclinical","presentation_type":"Poster Session","safety":"Not Reported","session_location":"Section 12","session_time":"April 29, 2025, 2:00 PM - 5:00 PM","session_title":"Session PO.MCB09.02 - Metabolic Reprogramming","study_type":"Preclinical, xenografts, isotope tracing","summary":["RKIP associated with oxidative phosphorylation.","RKIP modulates oxygen consumption rates in vitro.","Stable isotope tracing shows higher glucose in citrate.","RKIP reduces transcriptional heterogeneity in mitochondrial genes.","Metformin inhibits growth of RKIP-overexpressing tumors."],"target":["OXPHOS"]},{"abstract":"First-line immunochemotherapy fails to achieve a durable response in up to one third of patients with diffuse large B-cell lymphoma (DLBCL). Therapy resistance is mediated, in part, by ineffective elimination of B-cells protected by a metabolic tumor-stroma interaction. Carnitine palmitoyltransferase 1A (CPT1A), a component of the prognostic DLBCL-LAMI signature, plays a major role in transporting fatty acids - partly provided by stromal cells - into mitochondria to support B-cell metabolism. We investigated the CPT1A inhibitors ST1326 and perhexiline for their ability to eliminate lymphoma cells in the presence of stromal cells and the potential of sensitizing them to the therapeutic BCL2 inhibitor venetoclax.CPT1A protein expression was evaluated in primary tumor specimens by immunohistochemistry using TMAs. CPT1A inhibitors and venetoclax (ABT-199) were tested on different pre-clinical models: (1) 15 DLBCL cell lines, (2) co-culture models of DLBCL cell lines and either stromal cell line HS-5 or primary DLBCL-cancer associated fibroblasts to evaluate the induction of B-cell death in a stromal environment, and (3) patient-derived DLBCL cells. Therapeutic efficacy was assessed using MTT cytotoxicity and CellTiter Glo 2.0 assays. Effects on lipid metabolism, molecular signaling and induction of cell death were investigated by oil red O staining, immunoblots and AnxV/TMRM flow cytometry, respectively.CPT1A protein was expressed in 77% (67/87) of primary DLBCL (cytoplasmic staining, cut-off 20%). Both CPT1A inhibitors impaired the viability of lymphoma cells: perhexiline treatment was cytotoxic in 5/5 cell lines (IC50 = 5.5-7.5 µM), ST1326 in 10/15 cell lines (IC50 = 5-18 µM). Viability of normal fibroblasts was not affected by either drug. Perhexiline lost its cytotoxic effect against lymphoma cells when co-cultured with stromal cells. In contrast, ST1326 remained effective in killing DLBCL cells also in stromal environment. Suppression of fatty acid transport into mitochondria by ST1326 resulted in cytoplasmic lipid accumulation, suppression of anti-apoptotic Bcl-XL and phospho-AKT, and induction of apoptotic cell death. The combination of ST1326 with the BCL2 inhibitor venetoclax increased its cytotoxic efficacy. Three DLBCL cell lines that were BCL2-positive but resistant to venetoclax were sensitized by ST1326 to the BCL2 inhibitor, an effect that persisted in the presence of stromal cells. In patient-derived DLBCL models (partly from patients with poor response to standard immunochemotherapy), CPT1A inhibition impaired the viability of primary DLBCL cells and enhanced the antitumor activity of venetoclax.Targeting fatty acid metabolism using ST1326 effectively eliminates lymphoma cells in the presence of stromal cells and increases significantly the efficacy of the BCL2-specific inhibitor venetoclax, thus providing a new candidate approach in the treatment of DLBCL.","authors":["Sophia Steinlein","Heike Horn","Emma Attwood","Annette M. Staiger","Katrin S. Kurz","Andreas Rosenwald","German Ott","Claudia Kalla"],"citation_author":"Sophia Steinlein","citation_author_institution":"Dr. Margarete Fischer-Bosch Institute of Clinical Pharmacology, Stuttgart, Germany","citation_title":"CPT1A inhibition sensitizes diffuse large B-cell lymphoma to venetoclax treatment","design":"Not Reported","disease":"Diffuse large B-cell lymphoma","drug":["ST1326","Perhexiline","Venetoclax"],"efficacy":"ST1326 reduced lymphoma cell viability, sensitized cells to venetoclax, efficacy persisted with stromal cells.","id":"6384","link":"https://www.abstractsonline.com/pp8/#!/20273/presentation/7650","organizations":["Dr. Margarete Fischer-Bosch Institute of Clinical Pharmacology, Stuttgart, Germany","Robert Bosch Hospital, Stuttgart, Germany","University of Würzburg, Würzburg, Germany"],"phase":"Preclinical","presentation_type":"Poster Session","safety":"CPT1A inhibitors did not affect normal fibroblasts, ST1326 effective in stromal environment.","session_location":"Section 34","session_time":"April 27, 2025, 2:00 PM - 5:00 PM","session_title":"Session PO.CL08.01 - Targeted Therapies and Combinations 1","study_type":"Preclinical, co-culture models","summary":["CPT1A is overexpressed in 77% DLBCL.","CPT1A inhibitors impair lymphoma viability.","ST1326 remains effective with stromal cells.","ST1326 enhances venetoclax efficacy.","Potential therapeutic approach for DLBCL."],"target":["Carnitine palmitoyltransferase 1A (CPT1A)","BCL2"]},{"abstract":"The spatial organization of the genome plays a vital role in maintaining the cell type-specific chromatin structures and regulating gene expression. The three-dimensional (3D) genome structures can be measured by sequencing-based techniques such as Hi-C on the ensemble level or by imaging-based techniques such as chromatin tracing on the single-molecule level. Chromatin tracing is a multiplexed DNA fluorescence in situ hybridization (FISH) technique that can directly trace the 3D positions of genomic loci along individual chromosomes in single cells. By designing the primary probes targeting specific genomic regions and dye-labeled secondary probes to indicate their positions, chromatin tracing can construct the 3D trace of chromatin at high resolution using microscopy. However, few computational tools have been developed for differential analysis of chromatin tracing data. Major challenges include the high variability of chromatin traces and missing values in the 3D coordinates of some loci. Here, we present Dory, a statistical method for identifying differential patterns from two groups of chromatin traces without imputation of missing data. Dory measures the spatial distance between each pair of regions in each chromatin trace and employs multi-level statistical tests to quantify the distance difference between the two groups of chromatin traces. The output of Dory includes the differential score for each region pair comparing chromatin traces between two biological conditions. We applied Dory to chromatin tracing data from six cell types in mouse fetal liver and from a mouse lung cancer progression model. We found that the changes in chromatin structure are associated with A-B compartment alterations and promoter-enhancer interaction alterations that cause differential gene expression. Dory is a user-friendly computational tool that can be applied to multiple types of imaging-based 3D genome data analysis for studying genome functions and gene regulation.","authors":["Zhaoxia Ma","Miao Liu","Mengwei Hu","Shengyuan Wang","Siyuan Wang","Chongzhi Zang"],"citation_author":"Zhaoxia Ma","citation_author_institution":"University of Virginia, Charlottesville, VA, VA","citation_title":"Dory: a computational method for differential chromatin tracing analysis","design":"Not Reported","disease":"Mouse lung cancer progression","drug":[],"efficacy":"Differential patterns identified without imputation","id":"6383","link":"https://www.abstractsonline.com/pp8/#!/20273/presentation/3535","organizations":["University of Virginia, Charlottesville, VA, VA","Yale University, New Haven, CT, CT"],"phase":"Preclinical","presentation_type":"Poster Session","safety":"Not applicable","session_location":"Section 46","session_time":"April 29, 2025, 2:00 PM - 5:00 PM","session_title":"Session PO.BCS01.11 - New Software Tools and Machine Learning Methods","study_type":"Computational method for differential chromatin trace analysis","summary":["Dory is a statistical method for chromatin tracing.","Identifies differential patterns without needing missing data imputation.","Applied to six cell types in mouse fetal liver.","Used in mouse lung cancer progression model.","Associations found with chromatin structure changes and gene expression."],"target":["Genomic loci"]},{"abstract":"Introduction: CAR-T cell therapy represents a significant advancement in the management of relapsed/refractory hematological malignancies. Adverse events include cytokine release syndrome (CRS), infections, and neurological and cardiovascular events. Though real-world data from referral centers regarding the uptake of CAR-T cell therapy in different populations and the incidence of various adverse events are available, we used the National Inpatient Sample (NIS) with weighted analysis to provide contemporary data representing national estimates for patients and complications profile with CAR-T therapy.Methods: A retrospective study was conducted by obtaining patients who underwent CAR-T cell therapy using ICD-10-PCS procedure codes (XW033C3, XW043C3, XW23346, XW24346, XW23376 and XW24376) from NIS 2021 dataset. Demographic characteristics, as well as the incidence of infectious complications and adverse cardiovascular events, were obtained using ICD-10-CM diagnostic codes. Different grades of CRS were identified using specific ICD-10 codes (Grade 1-5: D89.831-D89.835).Results: Of 2,235 patients who underwent CAR-T cell therapy between January 2021 and December 2021, 64.2% were male, 73.5% identified as Caucasian, 12.3% as Asian and 5.5% as African American. 50.6% had private insurance, 36.5% had Medicare, and 6.7% had Medicaid. Most patients had lymphomas (64.9%), followed by myelomas (17.9%) and leukemias (13%). Acute myocardial infarction and stroke were documented in 0.4% of patients each. Notably, 21.7% of patients experienced cardiac arrhythmias, and major cardiovascular events were recorded in 4.3% of the cohort. Additionally, 4.9% of patients were diagnosed with pneumonia, while sepsis occurred in 7.6% of patients, and 3.4% experienced septic shock. Moreover, 1.1% of patients developed HLH. CRS was observed in 59.3% of the patients. Among those with CRS, grade 1 and grade 2 reactions were reported in 32% and 21% of patients, respectively, while grade 3 and grade 4 reactions were noted in 4.7% and 2% of patients, with no cases of grade 5 identified. The mean total cost of hospitalization was 324,972.8 USD. The overall in-hospital mortality rate was found to be 3.4%.Conclusion: In our study, most patients were males, and the majority belonged to the Caucasian ethnicity. Over half of the patients had private insurance. CRS was common but mostly low-grade intensity. Infections present a considerable challenge with CAR-T therapy, making early identification and appropriate antimicrobial treatment critical. Adverse cardiovascular events were frequently reported among patients receiving CAR-T cell therapy, underscoring the necessity for close cardiac monitoring to detect such events and to implement comprehensive care strategies effectively.","authors":["Himil Mahadevia","Karnav Modi","Akhil Jain","Furha Cossor","Deepthi Vodnala","Taiyeb Khumri"],"citation_author":"Himil Mahadevia","citation_author_institution":"University of Missouri - Kansas City School of Medicine, Kansas City, MO, MO","citation_title":"Demographic characteristics and incidence of cardiovascular events, infections and cytokine response syndrome (CRS) in patients treated with chimeric antigen receptor (CAR) T cell therapy: a nationwide analysis","design":"Retrospective study","disease":"Relapsed/refractory hematological malignancies","drug":["CAR-T cell therapy"],"efficacy":"Not Reported","id":"6382","link":"https://www.abstractsonline.com/pp8/#!/20273/presentation/7441","organizations":["University of Missouri - Kansas City School of Medicine, Kansas City, MO, MO","University of Iowa, Iowa City, IA, IA","Saint Luke's Hospital of Kansas City, Kansas City, MO, MO"],"phase":"Others","presentation_type":"Poster Session","safety":"21.7% cardiac arrhythmias, 59.3% CRS, 4.3% major cardiovascular events, 7.6% sepsis, 3.4% septic shock, 1.1% HLH","session_location":"Section 33","session_time":"April 28, 2025, 2:00 PM - 5:00 PM","session_title":"Session PO.CL10.02 - Real-World Data and Real-World Evidence: Clinical Informatics and Data Science 1","study_type":"Retrospective study using NIS, 2021","summary":["CAR-T therapy analyzed in national dataset.","CRS observed in 59.3% of patients.","Majority of CRS were low-grade.","Common infections: pneumonia and sepsis.","Cardiovascular events require monitoring."],"target":["Not Reported"]}]""",
            "language": 'CN',
            "model": '',
            "enable_rag": False,
        }
    }
    await chat(body=body)

async def test_mindsearchworkflowrefer_drug():
    body = {
        "user_prompt": "对选中的数据，生成竞争格局分析",
        "agent": "mindsearchworkflowrefer",
        "history_messages": [],
        "params": {
            "background": """Selected drug data: [{"name":"REC-648647","other_names":["REC 648647","REC648647"],"lead_company":"Recursion Pharmaceuticals","partner_companies":[],"target":[],"drug_modality":["Small Molecule"],"drug_feature":[],"route_of_administration":["Unknown"],"indication":"Neuronal ceroid lipofuscinosis","phase":"Preclinical","location":"USA","id":"0000acd5-ae71-4344-bd66-377c113ff246_1185_68d475ad-0578-41a5-bf85-14c631084f47_USA"},{"name":"selectin inhibitors, Organon","other_names":["selectin inhibitors, Ontogen"],"lead_company":"Merck & Co.","partner_companies":["Ontogen"],"target":[],"drug_modality":["Small Molecule"],"drug_feature":[],"route_of_administration":["Unknown"],"indication":"Dermatitis atopic","phase":"Preclinical","location":"Japan","id":"00010d4b-0bec-4dfe-ac9b-81e600d32977_181_17d27ad3-5901-409e-895a-24396613b37c_Japan"},{"name":"selectin inhibitors, Organon","other_names":["selectin inhibitors, Ontogen"],"lead_company":"Merck & Co.","partner_companies":["Ontogen"],"target":[],"drug_modality":["Small Molecule"],"drug_feature":[],"route_of_administration":["Unknown"],"indication":"Dermatitis atopic","phase":"Preclinical","location":"USA","id":"00010d4b-0bec-4dfe-ac9b-81e600d32977_181_17d27ad3-5901-409e-895a-24396613b37c_USA"},{"name":"selectin inhibitors, Organon","other_names":["selectin inhibitors, Ontogen"],"lead_company":"Ontogen","partner_companies":["Merck & Co."],"target":[],"drug_modality":["Small Molecule"],"drug_feature":[],"route_of_administration":["Unknown"],"indication":"Dermatitis atopic","phase":"Preclinical","location":"Japan","id":"00010d4b-0bec-4dfe-ac9b-81e600d32977_181_e49cd869-ba77-4af3-8dda-e7cbbbf12f7b_Japan"},{"name":"selectin inhibitors, Organon","other_names":["selectin inhibitors, Ontogen"],"lead_company":"Ontogen","partner_companies":["Merck & Co."],"target":[],"drug_modality":["Small Molecule"],"drug_feature":[],"route_of_administration":["Unknown"],"indication":"Dermatitis atopic","phase":"Preclinical","location":"USA","id":"00010d4b-0bec-4dfe-ac9b-81e600d32977_181_e49cd869-ba77-4af3-8dda-e7cbbbf12f7b_USA"}]""",
            "language": 'CN',
            "model": '',
            "enable_rag": False,
        },
        "is_hitl": True
    }
    await chat(body=body)

async def test_mindsearchworkflowrefer_noselectbackground():
    body = {
        "user_prompt": "对选中的数据，生成竞争格局分析",
        "agent": "mindsearchworkflowrefer",
        "history_messages": [],
        "params": {
            "background": """Selected drug data: []""",
            "language": 'CN',
            "model": '',
            "enable_rag": False,
        }
    }
    await chat(body=body)

async def test_mindsearchworkflowrefer_catalyst():
    body = {
        "user_prompt": "请分析这个催化剂事件的成功率",
        "agent": "mindsearchworkflowrefer",
        "history_messages": [],
        "params": {
            "background": """Selected catalyst data: [{"title":"Phase III HARMONi - Top-Line Results","expected_date_start":"2025-04-01","expected_date_end":"2025-09-30","clinical_analysis_phase":"III","expected_catalyst_type":"Trial Data - Updated Results","drug_name":"Ivonescimab","indication_name":"Non-Small Cell Lung Cancer (NSCLC)","lead_company_symbol":"","company":["Akeso Inc.","Summit Therapeutics plc (SMMT)"],"id":609277,"clinical_trial_data":[{"nct_id":"NCT05247684","primary_id":"NCT05247684","last_updated":"2022-02-09","official_title":"Phase II Clinical Study of AK112, an Anti-PD-1 and VEGF Bispecific Antibody, Alone or in Combination With Chemotherapy for the Neoadjuvant/Adjuvant Treatment of Resectable Non-small Cell Lung Cancer","lead_company":"Summit Therapeutics plc (SMMT)","partner_companies":["Akeso Inc."],"drug_name":["Ivonescimab/AK112"],"drug_modality":["Small Molecule"],"drug_feature":["Reformulation"],"route_of_administration":["Intravenous (IV)"],"indication_name":["Non-small-cell lung cancer"],"target":["VEGF (Vascular endothelial growth factor)","Immune System","Programmed death-1 receptor (PD-1)"],"phase":"II","phase_mapping":["II"],"current_status":"Interim Data Released","gender":"Both","actual_enrollment":null,"locations":null,"key_findings":[{"finding":"Combination therapy showed superior efficacy with pCR rate of 52.7% and MPR rate of 72.7%","timestamp":"09/08/2024"},{"finding":"Particularly strong efficacy in squamous NSCLC subgroup with pCR rate of 63.6% and MPR rate of 84.1%","timestamp":"09/08/2024"},{"finding":"Promising 12-month EFS rate of 80.3% (95% CI: 59.6, 91.1)","timestamp":"09/08/2024"},{"finding":"Manageable safety profile with 32.7% Grade ≥3 AEs in combination therapy, no surgical complications","timestamp":"09/08/2024"}],"label":"positive","events":[{"event_date":"2024-09-08","analysis":"Akeso announced the results from the Phase II study of ivonescimab either as a monotherapy or in combination with chemotherapy, for the perioperative treatment of resectable non-small cell lung cancer. The abstract entitled \"A Phase II Study of Perioperative Ivonescimab Alone or Combined with Chemotherapy in Resectable Non-Small Cell Lung Cancer\" was presented at the 25th World Conference on Lung Cancer (WCLC) on September 8, 2024.DesignThe study is designed to assess patients receiving either ivonescimab monotherapy or ivonescimab plus chemotherapy prior to surgical resection and then ivonescimab monotherapy after surgery. At the time of data cutoff, 49 patients had been enrolled into the ivonescimab plus chemotherapy arm in the neo-adjuvant setting; of these 49 patients, 39 went on to complete surgery. As of February 2024, the AK112-205 study enrolled 60 patients, with 78.3% in stage III and 90% in N+ stage (among N+ stage patients, 70% are in N2 stage). Of these, 49 underwent surgery (all R0 resections).Per the abstract, this was an open-label, multi-center Phase II study, pts diagnosed with resectable stage II, IIIA or IIIB (N2) NSCLC per AJCC 8th edition were enrolled into two cohorts. Pts received neoadjuvant ivonescimab (20 mg/kg) monotherapy in cohort 1 or ivonescimab (20 mg/kg or 30 mg/kg) plus cisplatin/carboplatin and paclitaxel in cohort 2 once every 3 weeks for 3-4 cycles, followed by surgery and adjuvant ivonescimab once every 3 weeks for up to 16 cycles. A total of 60 pts were enrolled from March 09, 2022 to July 31, 2023 (11 pts in cohort 1 and 49 pts in cohort 2, 24 pts received ivonescimab 20 mg/kg plus chemotherapy, 25 pts received ivonescimab 30 mg/kg plus chemotherapy). Of these pts, the median age at baseline was 64 [range: 31-74] years, 85% were male, 75% with squamous carcinoma, 78% with stage III, and 90% with lymph node metastasis.EndpointsPer the abstract, primary endpoints were safety and major pathological response (MPR).ResultsDue to the maturity of the data and the timing of the data cutoff, the results were limited to the neo-adjuvant, or pre-surgery, portion of the clinical trial. Compared with ivonescimab monotherapy, rates of MPR and pCR in ivonescimab combined with chemotherapy were numerically higher, and across tumor stage and PD-L1 expression subgroups. Ivonescimab + chemotherapy cohort: pCR rate was 43.6%, MPR rate was 71.8%. 69.2% of patients are with residual viable tumor (RVT) ＜ 5%.As of August 2024, 55 patients in this cohort completed surgery, pCR and MPR rates were improved to 52.7% and 72.7%, respectively. For squamous NSCLC, pCR and MPR rates were 63.6% and 84.1%, respectively.Ivonescimab monotherapy cohort: pCR rate was 30.0%, MPR rate was 60.0%.In the 49 patients enrolled, median event-free survival (EFS) was not yet reached after 8.9 months of median follow-up time; the 12-month EFS rate was 80.3% (95% CI: 59.6, 91.1). Per the abstract, as of January 08, 2024, in cohort 1, 10 pts completed surgery, the rate of MPR was 60% and the rate of pathological complete response (pCR) was 30%. In cohort 2, 39 pts completed surgery, the rate of MPR was 71.8% and the rate of pCR was 43.6%. The pathological response was better in 30 pts with squamous carcinoma: the rate of MPR and pCR were 83.3% and 53.3%, respectively. MPR and pCR occurred in 70% and 40% of pts with ivonescimab 20 mg/kg plus chemotherapy, 73.7% and 47.4% of pts with ivonescimab 30 mg/kg plus chemotherapy, respectively. Median event-free survival and overall survival were not reached with the median follow-up duration of 10.1 months.Most Common Adverse EventsThe safety profile was manageable. There were no TRAEs that led to cancelled or delayed surgery or wound healing complication. Of the 49 patients who received ivonescimab plus chemotherapy in the neo-adjuvant setting, Grade 3 or higher adverse events were observed in 32.7% of patients; there was one patient who experienced a treatment-related serious adverse event.Per the abstract, the treatment was well tolerated during the perioperative period. There were no treatment related adverse events (TRAEs) that led to cancelled or delayed surgery or wound healing complications. The most common TRAEs (incidence ≥5%) of grade 3 or higher were decreased neutrophil count and decreased white blood cell count. The safety profiles were similar in the two groups of ivonescimab 20 mg/kg and 30 mg/kg in cohort 2.ConclusionThe study results demonstrated that perioperative ivonescimab monotherapy or combined with chemotherapy for resectable NSCLC demonstrated high rates of pathological complete response (pCR) and major pathological response (MPR) in this Phase II study."}],"url":"https://test.noahai.co/detail/clinical-trial/84716"},{"nct_id":"NCT06396065","primary_id":"NCT06396065","last_updated":"2024-10-01","official_title":"A Randomized, Double-blind, Multi-center, Phase III Study of AK112 or Placebo Combined With Pemetrexed and Carboplatin in Patients With EGFR-mutant Locally Advanced or Metastatic Non-squamous NSCLC Who Have Failed to EGFR-TKI Treatment","lead_company":"Summit Therapeutics plc (SMMT)","partner_companies":["Akeso Inc."],"drug_name":["Ivonescimab/AK112"],"drug_modality":["Polyclonal Antibodies","Bi-specific Antibodies","Monoclonal Antibodies"],"drug_feature":["Precision Medicine"],"route_of_administration":["Intravenous (IV)"],"indication_name":["Non-small-cell lung cancer"],"target":["VEGF (Vascular endothelial growth factor)","Immune System","Programmed death-1 receptor (PD-1)"],"phase":"III","phase_mapping":["III"],"current_status":"Interim Data Released","gender":"Both","actual_enrollment":null,"locations":["Canada","France","Italy","Spain","United Kingdom","United States"],"key_findings":[{"finding":"Ivonescimab plus chemotherapy significantly improved PFS with 54% risk reduction (HR 0.46; p<0.001) compared to chemotherapy alone","timestamp":"05/31/2024"},{"finding":"Superior ORR (50.6% vs 35.4%) and DCR (93.1% vs 83.2%) in ivonescimab arm compared to placebo","timestamp":"05/31/2024"},{"finding":"Strong efficacy in key subgroups including brain metastases (HR 0.40) and T790M mutation positive patients (HR 0.22)","timestamp":"05/31/2024"},{"finding":"OS trend favorable for ivonescimab arm though data not mature (HR 0.80 at 17.6 months follow-up)","timestamp":"05/31/2024"},{"finding":"Manageable safety profile with no treatment-related deaths and similar rates of Grade ≥3 VEGF-related AEs between arms","timestamp":"05/31/2024"}],"label":"positive","events":[{"event_date":"2024-05-31","analysis":"Akeso announced the data from the Phase III HARMONi-A study of ivonescimab combined with chemotherapy in patients with EGFR-mutant non-squamous non-small cell lung cancer at the American Society of Clinical Oncology Annual Meeting. Abstracts entitled \"Ivonescimab combined with chemotherapy in patients with EGFR-mutant non-squamous non-small cell lung cancer who progressed on EGFR tyrosine-kinase inhibitor treatment (HARMONi-A): A randomized, double-blind, multi-center, phase 3 trial\" and \"Ivonescimab Plus Chemotherapy in Non-Small Cell Lung Cancer With EGFR Variant: A Randomized Clinical Trial\" were presented at the meeting and simultaneously published in the Journal of the American Medical Association on May 31, 2024.DesignPer the abstract, patients were randomized 1:1 to receive ivonescimab (20 mg/kg) plus pemetrexed (500 mg/m2) and carboplatin (AUC 5) or placebo plus chemotherapy once every 3 weeks for four cycles, with stratification according to the third-generation EGFR TKI (received vs not received) and brain metastases (presence vs absence), followed by maintenance therapy of ivonescimab and pemetrexed or placebo and pemetrexed.EndpointsThe primary endpoint was progression-free survival (PFS) in the intention-to-treat (ITT) population assessed by independent radiographic review committee (IRRC) per RECIST v1.1. Here we report the results of the first planned interim analysis.ResultsPFS, the primary endpoint of the study, was significantly improved in the ivonescimab plus chemotherapy arm (HR 0.46; 95% CI: 0.34 – 0.62; p<0.001), representing a 54% reduction in the risk of disease progression compared to chemotherapy. Median PFS for ivonescimab plus chemotherapy was 7.1 months (95% CI: 5.9 – 8.7), as compared to 4.8 months (95% CI: 4.2 – 5.6) for placebo plus chemotherapy. In addition, for the subgroup of patients receiving a 3rd generation TKI (e.g., osimertinib or other locally approved 3rd generation TKIs), patients experienced a reduced risk of disease progression of 52% (HR: 0.48; 95% CI: 0.35 – 0.66). The PFS benefit was demonstrated across all clinical subgroups.While not yet mature, overall survival (OS) analyses performed on request of the NMPA trended positively for ivonescimab plus chemotherapy vs. chemotherapy alone: after 10.2 months of median follow-up, the hazard ratio (HR) was 0.72 (95% CI: 0.48 – 1.09). An additional analysis performed after approximately 17.6 months of median follow-up showed a hazard ratio of 0.80 (95% CI: 0.59 – 1.08). Both overall survival curves appear to demonstrate clear separation between the two arms of the trial and show a trend in improvement of survival towards ivonescimab plus chemotherapy.Overall response rate (ORR) was 50.6% (95% CI: 42.6% – 58.6%) for those receiving ivonescimab plus chemotherapy vs. 35.4% (95% CI: 28.0% - 43.3%) for those receiving chemotherapy alone. Ivonescimab plus chemotherapy usage resulted in a disease control rate (DCR) – those who either responded or were considered to have stable disease under RECIST 1.1 criteria – of 93.1% (95% CI: 88.0% - 96.5%) vs. 83.2% (95% CI: 76.5% - 88.6%) for those receiving placebo plus chemotherapy.Per the abstract, 322 patients were randomized (161 to the ivonescimab plus chemotherapy arm, 161 to the placebo plus chemotherapy arm). 86.3% versus 85.1% of patients had received 3rd generation EGFR TKI treatment, 21.7% versus 23.0% of patients had brain metastases. As of March 10, 2023, median follow-up time was 7.89 months. The prespecified subgroup analysis showed PFS benefit favoring patients receiving ivonescimab over placebo across almost all subgroups, including those with brain metastases (HR 0.40, 0.22-0.73), those with EGFR mutation of deletion 19 (HR 0.48, 0.32-0.73), and those who were T790M mutation positive (HR 0.22, 0.09-0.54).Most Common Adverse EventsIvonescimab demonstrated an acceptable and manageable safety profile. The most common treatment-related adverse events (TRAEs), both all grades and Grade 3 or higher, were hematological, laboratory count-based events: white blood cell count decreases, anemia, neutrophil count decreases, and platelet count decreases. There were nine patients (5.6%) who discontinued ivonescimab due to TRAEs compared to four patients (2.5%) who discontinued placebo due to TRAEs. Grade 3 or higher immune-related adverse events occurred in 6.2% of patients receiving ivonescimab plus chemotherapy and 2.5% of patients receiving placebo plus chemotherapy. Grade 3 or higher VEGF-related adverse events between the two arms were similar (3.1% vs. 2.5%, respectively); there were no Grade 3 bleeding or arterial thrombotic events in the ivonescimab plus chemotherapy arm. No TRAEs resulted in the death of a patient in either arm in this Phase III study.Per the abstract, Grade ≥3 TEAEs occurred in 99 (61.5%) patients versus 79 (49.1%) patients, the most common grade ≥3 TEAEs were chemotherapy-related adverse events.ConclusionsPer the abstract, Ivonescimab plus chemotherapy significantly improved PFS while maintaining a manageable safety profile in patients who had failed previous EGFR TKI treatments."}],"url":"https://test.noahai.co/detail/clinical-trial/74627"},{"nct_id":"NCT04736823","primary_id":"NCT04736823","last_updated":"2023-08-01","official_title":"A Phase II Trial of AK112 (PD1/VEGF Bispecific) in Combination With Chemotherapy in Patients With NSCLC","lead_company":"Summit Therapeutics plc (SMMT)","partner_companies":["Akeso Inc."],"drug_name":["Ivonescimab/AK112"],"drug_modality":["Small Molecule"],"drug_feature":["Non-NME"],"route_of_administration":["Oral (PO)"],"indication_name":["Non-small-cell lung cancer"],"target":["VEGF (Vascular endothelial growth factor)","Immune System","Programmed death-1 receptor (PD-1)"],"phase":"II","phase_mapping":["II"],"current_status":"Final Data","gender":"Both","actual_enrollment":null,"locations":["China"],"key_findings":[{"finding":"Ivonescimab plus chemotherapy showed strong efficacy in first-line squamous NSCLC with 71.4% ORR and 11.1-month median PFS","timestamp":"<2024-03-22>"},{"finding":"Significant intracranial activity demonstrated with 34% ORR and 23% complete response rate in brain metastases","timestamp":"<2024-03-22>"},{"finding":"Promising activity in EGFRm+ patients post-TKI with 68.4% ORR and 8.5-month median PFS","timestamp":"<2023-08-03>"},{"finding":"Manageable safety profile with 8.4% Grade ≥3 WBC decrease as most common severe TRAE","timestamp":"<2023-08-03>"}],"label":"positive","events":[{"event_date":"2023-08-03","analysis":"Analysis:\n\nAkeso announced the publication of results from the Phase II study of ivonescimab combined with chemotherapy for the treatment of non-small cell lung cancer (NSCLC). The article entitled \"AK112, a novel PD-1/VEGF bispecific antibody, in combination with chemotherapy in patients with advanced non-small cell lung cancer (NSCLC): an open-label, multicenter, phase II trial\" was published in the eClinical Medicine, a sub-journal of The Lancet, on August 3, 2023.Data from this study were last seen in June 2023.ContextAkeso announced that a New Drug Application (NDA) has been submitted for ivonescimab.Following the acceptance of marketing application for an indication of ivonescimab by the China CDE, five pivotal registrational Phase III clinical trials have been initiated/are being conducted worldwide, including three head-to-head trials with PD-1 monoclonal antibody as the positive control drug and two international multicenter Phase III clinical trials:An international multicenter Phase III study (HARMONi) of Ivonescimab in combination with chemotherapy for patients with EGFR-mutated, locally advanced or metastatic non-squamous NSCLC progressing on third-generation EGFR-TKI therapy. Akeso's partner, Summit Therapeutics(Summit), has completed the first patient dosing in the United States.An international multicenter Phase III study of ivonescimab in combination with chemotherapy versus pembrolizumab monoclonal antibody in combination with chemotherapy as the first-line treatment for metastatic squamous NSCLC is conducted in the United States (HARMONi-3). Summit intends to dose the first patient in the second half of 2023.A Phase III study of ivonescimab monotherapy versus pembrolizumab monotherapy as the first-line treatment for NSCLC patients with positive PD-L1 expression in China is undergoing. The enrollment will be completed soon.A Phase III study in China for the first-line treatment of advanced squamous NSCLC with ivonescimab in combination with chemotherapy versus tislelizumab in combination with chemotherapy is undergoing.Ivonescimab has received breakthrough therapy designation status in China from the NMPA for three indications:Ivonescimab combined with chemotherapy for the treatment of EGFR-mutated locally advanced or metastatic NSCLC patients who progressed on EGFR-TKI treatment.Ivonescimab as the first-line treatment for locally advanced or metastatic NSCLC patients with positive PD-L1 expression.Ivonescimab combined with docetaxel for the treatment of locally advanced or metastatic NSCLC patients who failed to respond to prior PD-(L)1 inhibitor combined with platinum-based doublet chemotherapy.DesignPer the abstract, this open-label, multicenter, Phase II clinical trial was conducted in 11 hospitals in China. Eligible participants were adults aged 18–75 years with locally advanced or metastatic NSCLC, an Eastern Cooperative Oncology Group performance status of 0 or 1, at least one measurable lesion, and an estimated life expectancy of at least 3 months. The participants were categorized into three cohorts based on prior therapy and functional genomic alterations. Patients in cohort 1 were previously untreated advanced NSCLC, had no epidermal growth factor receptor (EGFR) or anaplastic lymphoma kinase (ALK) gene modifications, and received AK112 combined with pemetrexed (500 mg/m2) for non-squamous (non-sq)-NSCLC or paclitaxel (175 mg/m2) for sq-NSCLC plus carboplatin (area under the curve of 5 mg/mL per min) for four cycles, followed by AK112 with pemetrexed for non-sq-NSCLC and AK112 alone for sq-NSCLC as maintenance therapy. The participants in cohort 2 had advanced NSCLC with EGFR-sensitive mutations, failed previous EGFR-tyrosine kinase inhibitor (TKI) therapy, and received pemetrexed plus AK112 and carboplatin for four cycles, followed by pemetrexed plus AK112 as maintenance therapy. The participants in cohort 3 had advanced NSCLC who failed systemic platinum-based chemotherapy and anti-PD-1/programmed death-ligand 1 (PD-L1) treatments and received AK112 plus docetaxel (75 mg/m2). Two dosages of AK112 (10 or 20 mg/kg) were examined in each cohort, and the drug was administered intravenously on day 1 of each 3-week treatment cycle. Eighty-three patients were enrolled from February 2021 to August 2022 and received the study treatment. Cohorts 1, 2, and 3 had 44, 19, and 20 patients, respectively.EndpointsPer the abstract, the primary endpoints were the investigator-assessed objective response rate (ORR) and safety.ResultsPer the abstract, the confirmed ORR was 53.5% (23/43) [95% CI, 36.9–67.1], 68.4% (13/19) [95% CI, 43.4–87.4], and 40.0% (8/20) [95% CI, 19.1–63.9] in cohorts 1, 2, and 3, respectively. In cohort 1, the median PFS was not reached, and the 12-month PFS rate was 59.1%. In cohorts 2 and 3, the median PFS were 8.5 [95% CI, 5.5-NE] and 7.5 [95% CI, 2.3-NE] months, and the 12-month PFS rates were 35.5% and 44.5%, respectively.Most Common Adverse EventsPer the abstract, the most common grade ≥3 treatment-related adverse events were decreased white blood cell count [7 (8.4%)], neutropenia [5 (6.0%)], thrombocytopenia [2 (2.4%)], anemia [4 (4.8%)], and myelosuppression [2 (2.4%)].ConclusionThe combination of ivonescimab and platinum-doublet showed antitumor activity for first-line treatment of advanced NSCLC without driver mutation, as well as for advanced NSCLC patients with EGFR-activating mutation that failed prior EGFR-TKI therapy. Additionally, AK112 in combination with docetaxel has shown favorable antitumor activity in advanced NSCLC patients who failed prior treatments with systemic platinum-based chemotherapy and PD-1/L1 inhibitor."},{"event_date":"2022-06-07","analysis":"The abstract entitled \"A phase II study of AK112 (PD-1/VEGF bispecific) in combination with chemotherapy in patients with advanced non-small cell lung cancer\" was presented at ASCO 2022.Data summarized in this event is solely based on data contained in the abstract from the ASCO abstract website. Citeline was unable to obtain updated data, if any, from the actual presentation at the ASCO conference.DesignThis was an open-label, multi-center phase II study evaluating the efficacy and safety of AK112 in combination with chemotherapy in pts with advanced NSCLC. Enrolled pts were divided into three cohorts: Previously untreated advanced NSCLC pts with wide-type EGFR/ALK (Cohort 1), pts with EGFR mutations who had failed prior EGFR-TKI therapies without T790M mutation or failed osimertinib treatment (Cohort 2), and pts who progressed after anti-PD-1/L1 and platinum-based chemotherapy (Cohort 3). Pts were treated with 10mg/kg or 20mg/kg AK112 once every 3 weeks in combination with carboplatin and pemetrexed or carboplatin and paclitaxel for Cohort 1/2, and docetaxel for Cohort 3. Primary endpoint was ORR as assessed by investigator per RECIST v1.1.Results133 pts were enrolled from Feb 03, 2021 to Dec 31, 2021 and received AK112 plus chemotherapy (44 received AK112 10 mg/kg and 89 received AK112 20 mg/kg). As of Dec 31, 2021, in cohort-1, among 26 evaluable pts with squamous cell carcinoma, 20 partial response and 6 stable disease were observed for a 76.9% ORR and a 100.0% DCR, median DOR and median PFS was not reached while 6-month PFS rate was 86.2%. In Cohort-2, among 19 evaluable pts, 13 partial response and 5 stable disease were observed for a 68.4% ORR and a 94.7% DCR while median DOR was 5.5 months, and median PFS was 8.3 months. In Cohort-3, among 20 evaluable pts, 8 partial response and 8 stable disease were observed for a 40.0% ORR and a 80.0% DCR, median DOR and median PFS was not reached while 6-month PFS rate was 71.1%.Most Common Adverse EventsTreatment emergent adverse events (TEAE) occurred in 86.5% (115/133) of the pts, and grade ≥3 AEs occurred in 28.6% (38/133) of pts including two deaths. Most common AE (incidence ≥ 5%) included alanine/aspartate aminotransferase increased, epistaxis, anemia, vomiting, nausea, rash, leukopenia, thrombocytopenia, and neutropenia. Treatment discontinuation due to AE occurred in 3.0% (4/133) of the pts.ConclusionAK112 plus chemotherapy has shown a promising anti-tumor efficacy in each cohort and warrants potentially superior safety in comparison to anti-PD-(L)1 and anti-VEGF combination therapies in advanced NSCLC. PFS and ORR were also significantly improved with AK112 plus chemotherapy. Therefore, Phase III registration studies of AK112 plus chemotherapy in advanced NSCLC will be initiated in 2022."},{"event_date":"2024-03-22","analysis":"Summit Therapeutics announced data from a Phase II studies of ivonescimab for NSCLC at the 2024 European Lung Cancer Congress (ELCC 2024). The abstract entitled \"Intracranial (IC) activity of ivonescimab (ivo) alone or in combination with platinum doublet chemotherapy (PC) in patients (Pts) with advanced non-small cell lung cancer (aNSCLC) and brain metastases (BMs)\" was presented on March 22, 2024.Data from these studies were last seen in October 2023 and January 2024 respectively.ContextSummit continues its clinical development of ivonescimab in order to establish its efficacy and safety in two NSCLC indications:HARMONi Phase III trial: ivonescimab combined with chemotherapy in patients with EGFR-mutated, locally advanced or metastatic non-squamous NSCLC who have progressed after treatment with a third-generation EGFR TKI.HARMONi-3 Phase III trial: ivonescimab combined with chemotherapy in first-line metastatic squamous NSCLC patients.DesignThese patients were enrolled in either AK112-202, in which ivonescimab is delivered as monotherapy, or AK112-201, in which ivonescimab is delivered in combination with platinum doublet chemotherapy, both of which are Phase II clinical trials for patients with advanced or metastatic NSCLC. This analysis consisted of the 35 patients with advanced or metastatic NSCLC who had asymptomatic brain metastases at baseline; 28 patients were treated with ivonescimab plus chemotherapy in AK112-201, and seven patients were treated with monotherapy ivonescimab in AK112-202.Per the abstract, pts with aNSCLC of any histology, no prior systemic therapy for cancer, and a performance status of 0-1 were eligible for ivo combined with PC or ivo alone on the AK112-201 and AK112-202 trials, respectively, enrolled from 2 centers in China. PC was continued for up to 4 cycles on AK112-201, while ivo continued until progressing disease or up to 2 years in both trials. Initial workup at BL included brain imaging with a brain MRI or head CT with cuts 5mm or smaller to identify BMs; pts with BMs at BL were eligible if without symptoms attributable to BMs. Pts who received pre-study radiotherapy to BMs or who could not undergo follow-up MRI with contrast due to an allergy were not evaluable for IC response. For those with BMs at BL, repeat brain imaging (with a brain MRI every 6 weeks) was pursued while on protocol-based treatment. BMs were evaluated serially by Response Assessment in Neuro-Oncology (RANO) criteria by 2 independent neuroradiologists (US and China) and adjudicated by a third (US-based) as needed.ResultsMedian intracranial progression-free survival was 19.3 months across all patients analyzed. Patients across both cohorts experienced an intracranial response rate of 34%, and eight patients (23%) experienced a complete response by RANO criteria. All patients who did not achieve a response demonstrated stable disease or non-progression; no patients experienced intracranial disease progression at the time of the initial follow-up scan.Per the abstract, a combined group of 35 pts met the criteria for inclusion in this analysis: 28 out of 174 on AK112-201, and 7 out of 108 on AK112-202. These pts had a median age of 60 (range 42-68), 77% male, 74% adenocarcinoma/14% squamous/11% other, 46% with PD-L1 >1%. Review of response of BMs across both studies showed 12 pts (34%) achieved an IC response. Of these, 11 had received PC/ivo, among whom 7 achieved an IC complete response (CR); 1 pt achieved an IC CR among the 7 pts who received ivo alone. Median IC progression-free survival was 19.3 months (mo) across both studies (19.3 mo in AK112-201, 16.6 mo in AK112-202).Most Common Adverse EventsNo cases of intracranial bleeding complications were observed in these patients.Per the abstract, No pts with BMs experienced IC bleeding on or in the 3 mo following ivo +/- PC.ConclusionPer the abstract, Ivo +/- PC led to IC responses in a subset of pts with previously untreated BMs at BL, including CR in pts receiving ivo with chemo and as monotherapy. Ivo was not associated with IC hemorrhage in these studies."},{"event_date":"2024-03-22","analysis":"Summit Therapeutics announced data from a Phase II study of ivonescimab for NSCLC at the 2024 European Lung Cancer Congress (ELCC 2024). The abstract entitled \"Phase II results of ivonescimab (ivo) a novel PD-1/VEGF bispecific in combination with chemotherapy for first-line treatment of patients (pts) with advanced/metastatic squamous (Sq) non-small cell lung cancer (NSCLC)\" was presented on March 22, 2024.Data from this study were last seen in January 2024.DesignThe Phase II trial AK112-201 is centered around the cohort of patients in which ivonescimab is combined with chemotherapy for first-line treatment of squamous and non-squamous advanced or metastatic NSCLC in patients without actionable genomic alterations (e.g., positive for endothelial growth factor receptor (EGFR) mutations or anaplastic lymphoma kinase (ALK)).Per the abstract, pts were treated with 10 mg/kg (n=10) or 20 mg/kg(n=53) ivo q3wks combined with carboplatin and pemetrexed (non-Sq) or carboplatin and paclitaxel (Sq). Pts were excluded if they had tumor encircling blood vessels, necrosis and cavitation, or had central, cavitary sq NSCLC, or risk of hemorrhage.EndpointsPer the abstract, the primary endpoint was ORR per RECISTv1.1 by investigator.ResultsOf significance, first-line advanced or metastatic squamous NSCLC patients experienced a median PFS of 11.1 months (95% CI: 9.5 – 16.3 months). In addition, first-line patients with advanced or metastatic non-squamous tumors experienced a median PFS of 13.3 months (95% CI: 8.3 – 16.4 months). Median overall survival was not reached in either subset of patients after a median follow-up time of 22.1 months.Per the abstract, 63 pts with advanced Sq-NSCLC received ivo plus chemotherapy. Median age was 59 yrs. 3% and 97% pts had ECOG PS 0 and 1, respectively, and 8% of pts had baseline brain metastasis. Pts with Sq-NSCLC experienced a 71.4% ORR with median DOR 12.7 mo, 90.5% DCR and 21-mo OS rate was 69.5%.Most Common Adverse EventsThe frequency of treatment-emergent adverse events (TEAEs) leading to the discontinuation of ivonescimab was 11.1% and 2.8%, respectively, in patients with squamous and non-squamous tumors. The most frequent TEAEs were anemia and decreased neutrophil counts in squamous patients and anemia and constipation in non-squamous patients.Per the abstract, Grade ≥3 TRAEs occurred in 44.4%. Overall incidence of bleeding events was 46% (grade 1-2) with one grade ≥3 event (hemoptysis) at 10mg/kg dose.ConclusionPer the abstract, Ivonescimab plus chemotherapy has good anti-tumor activity in pts with advanced NSCLC and was administered safely in combination with platinum doublet chemotherapy to pts with Sq histology."},{"event_date":"2024-01-08","analysis":"Analysis:\n\nSummit Therapeutics announced updated results from a Phase II study of ivonescimab for the treatment of non-small cell lung cancer. Data from this study were last seen in August 2023. ContextIn part, data generated from this trial has supported Summit’s decision to advance ivonescimab into two global Phase III clinical trials.Summit is enrolling patients in two global Phase III clinical trials involving ivonescimab: HARMONi intends to evaluate ivonescimab combined with chemotherapy compared to a placebo plus chemotherapy in patients with EGFR-mutated, locally advanced or metastatic non-squamous NSCLC who have progressed after treatment with a third-generation EGFR TKI, and HARMONi-3 is designed to evaluate ivonescimab combined with chemotherapy compared to pembrolizumab combined with chemotherapy in patients with 1L metastatic squamous NSCLC In addition to the ongoing Phase III clinical trials sponsored by Summit, Akeso is sponsoring four Phase III clinical trials investigating ivonescimab in China in NSCLC. Near-term catalyst events for both Summit and Akeso include expected key milestones for two of Akeso’s Phase III randomized clinical trials evaluating ivonescimab in China:AK112-301, which reflects the patient population of Summit’s HARMONi trial, was submitted for marketing approval to the Chinese health authority in 2023, and a decision from the Chinese Center for Drug Evaluation (CDE) is expected in the second quarter of 2024, along with a read-out of topline data from the study by Akeso, andAK112-303, which is evaluating monotherapy ivonescimab vs. pembrolizumab in 1L NSCLC patients whose tumors have a PD-L1 TPS >1%, has a planned interim analysis by Akeso, which is expected to be completed in the second quarter of 2024.DesignAK112-201 is an open-label Phase II study evaluating ivonescimab plus chemotherapy across three cohorts of patients. Updated data includes patients from Cohorts 1 & 2 of this study:Cohort 1: Patients with first line advanced or metastatic non-small cell lung cancer (NSCLC) without actionable genomic alterations (i.e., patients’ tumors do not have actionable mutations in endothelial growth factor receptor (EGFR) or anaplastic lymphoma kinase (ALK)).The updated data centers on the 63 patients whose tumors are of squamous histology.Cohort 2: Patients with second or third line advanced or metastatic NSCLC whose tumors are positive for EGFR mutations (EGFRm) and have progressed following an EGFR tyrosine kinase inhibitor (TKI) (n=19).ResultsThe estimated 1-year overall survival rate was 85.6%, and the 2-year overall survival rate was 64.8% for patients in Cohort 1 with squamous histology NSCLC. After a median follow-up time of 21.0 months, the median overall survival (OS) was not reached. The 19 patients in Cohort 2, primarily second or third line patients with EGFRm NSCLC, demonstrated a median overall survival of 22.5 months. After a median follow-up time of 25.8 months, the estimated 1-year overall survival rate was 74%.Most Common Adverse EventsIn Cohort 1, the frequency of treatment-related adverse events (TRAEs) leading to discontinuation of ivonescimab was 11%; there were no TRAEs leading to the death of a patient. The most frequent treatment-emergent adverse events were anemia, decreased neutrophil counts, and decreased white-blood cell counts.In Cohort 2, Ivonescimab had an acceptable safety profile in combination with platinum-doublet chemotherapy for patients with advanced or metastatic NSCLC who had progressed following an EGFR-TKI. There were no TRAEs leading to permanent discontinuation of therapy or patient death."},{"event_date":"2023-06-04","analysis":"Summit Therapeutics announced that data for ivonescimab was presented in the abstract entitled “Phase II results of ivonescimab (AK112/ SMT112), a novel PD-1/VEGF bispecific, in combination with chemotherapy for first line treatment of advanced or metastatic non-small cell lung cancer (NSCLC) without actionable genomic alterations (AGA) in EGFR/ALK” at the American Society of Clinical Oncology on June 4, 2023.Data from this study was last seen in June 2022.ContextThe poster features data from 135 patients in Cohort 1 of this study: patients who are treatment-naïve with advanced or metastatic non-small cell lung cancer (NSCLC) whose tumors do not have actionable genomic alterations (i.e., patients’ tumors do not have actionable mutations in endothelial growth factor receptor (EGFR) or anaplastic lymphoma kinase (ALK)). Summit has begun clinical development activities on the Phase III HARMONi-3 study, which intends to evaluate ivonescimab combined with chemotherapy in first-line metastatic squamous NSCLC patients. Summit intends to treat patients in the HARMONi-3 trial during the second half of 2023.In May 2023, the first patient was treated in Summit’s license territories in the Phase III HARMONi clinical trial. HARMONi intends to evaluate ivonescimab combined with chemotherapy in patients with EGFR-mutated, locally advanced or metastatic non-squamous NSCLC who have progressed after treatment with a third-generation EGFR tyrosine kinase inhibitor (TKI) (AK112-301).As per abstract, data from pts with prior therapy for advanced or metastatic disease were presented in ASCO 2022 and here the company reports additional pts and longer-term data from pts with NSCLC without AGA receiving first line therapy for advanced/metastatic disease.DesignAK112-201 is an open-label Phase II study evaluating ivonescimab plus chemotherapy for 174 patents across three cohorts of patients. Cohort 1 includes updated data from 72 patients with non-squamous histology.As per abstract, the sponsor aimed to assess the efficacy and safety of ivonescimab combined with chemotherapy for first line advanced or metastatic NSCLC in patients (pts) with squamous (SCC) or non-SCC NSCLC. An open-label, multi-center Phase II study evaluating the efficacy and safety of ivonescimab combined with chemotherapy in pts with advanced or metastatic NSCLC. Pts were enrolled into 3 cohorts based on prior therapy and presence of AGA. Pts were treated with 10 or 20 mg/kg ivonescimab once every 3wks combined with carboplatin and pemetrexed (non-SCC) or carboplatin and paclitaxel (SCC).EndpointsAs per abstract, the primary endpoint was ORR per RECIST by investigator.ResultsThis Phase II data set summarizes results to date from 63 patients with squamous histology. These patients experienced a median progression-free survival (PFS) of 11.0 months (95% CI: 9.5 to 16.8 months) and an overall response rate (ORR) of 67% (95% CI: 53% to 78%). After a median follow-up time of 13.3 months, median overall survival (OS) was not reached; although, estimated 9-month OS was 93.2%. Median PFS experienced by these patients was 12.3 months (95% CI: 8.3 to 19.3 months) and median overall survival was not reached after 13.3 months of median follow-up time. Of the 19 patients in Cohort 2, median PFS of 8.5 months was experienced; median overall survival was not reached. The ORR for patients in this cohort was 68% and the median duration of response (DOR) was 8.5 months. Approximately 32% of patients in this cohort remained on treatment at 12 months. There were 20 patients in Cohort 3; these patients experienced a median PFS of 7.1 months and median OS was 15.6 months. The ORR for patients in this cohort was 40% and the median DOR was 12.4 months. Approximately 35% of patients in this cohort remained on treatment at 12 months.As per abstract, 135 pts with advanced or metastatic NSCLC received ivonescimab plus chemotherapy including 63 with SCC and 72 with non-SCC. Median age was 61 yrs (. 78% male, 3% and 97% pts had ECOG PS 0 and 1, respectively, and 20% pts had baseline brain metastasis. Median follow-up was 11.5 mo. Pts with SCC experienced a 75% ORR with median DOR 15.4 mo, 95% DCR, the 9-mo PFS and OS rate was 67% and 93%, respectively. Pts with non-SCC experienced a 55% ORR, DOR was not reached, 100% DCR, the 9-mo PFS rate and OS rate was 61% and 81%, respectively.Most Common Adverse EventsThe frequency of Grade ≥3 treatment-related adverse events (TRAEs) was 41%. The most frequent treatment-emergent adverse events were anemia, decreased neutrophil counts, and alopecia. The frequency of Grade ≥3 TRAEs was 19%. The most frequent treatment-emergent adverse events were anemia, decreased neutrophil counts and constipation.Ivonescimab had an acceptable safety profile in combination with platinum-doublet chemotherapy for patients with advanced or metastatic NSCLC who had progressed following an EGFR-TKI, as well as in combination with chemotherapy for patients who had progressed following treatment with a PD-(L)1 inhibitor plus platinum-doublet chemotherapy in this clinical study.As per abstract, the most common treatment related adverse events (TRAEs)≥ 10% were epistaxis, proteinuria, rash, amylase increased, anemia, ALT increased, infusion related reaction, AST increased, pruritus, decreased appetite, and WBC decreased. Grade ≥3 TRAEs occurred in 28.1% TRAE leading to discontinuation occurred in 6.7% of pts.ConclusionAs per abstract, ivonescimab, plus chemotherapy has shown promising anti-tumor activity in pts with advanced/metastatic NSCLC without AGA and can be administered safely in combination with platinum doublet chemotherapy to patients with SCC and non-SCC histology."}],"url":"https://test.noahai.co/detail/clinical-trial/72343"},{"nct_id":"NCT05499390","primary_id":"NCT05499390","last_updated":"2025-03-01","official_title":"A Randomized Controlled, Multi-center Phase III Clinical Trial of AK112 Versus Pembrolizumab as First-line Treatment for PD-L1-Positive Locally-Advanced or Metastatic Non-Small Cell Lung Cancer","lead_company":"Summit Therapeutics plc (SMMT)","partner_companies":["Akeso Inc."],"drug_name":["Ivonescimab/AK112"],"drug_modality":["Polyclonal Antibodies","Bi-specific Antibodies","Monoclonal Antibodies"],"drug_feature":["Precision Medicine"],"route_of_administration":["Intravenous (IV)"],"indication_name":["Non-small-cell lung cancer"],"target":["VEGF (Vascular endothelial growth factor)","Immune System","Programmed death-1 receptor (PD-1)"],"phase":"III","phase_mapping":["III"],"current_status":"Final Data","gender":"Both","actual_enrollment":398,"locations":["China"],"key_findings":[{"finding":"Ivonescimab demonstrated superior PFS vs pembrolizumab (11.14 vs 5.82 months, HR 0.51, P<0.0001) in PD-L1+ NSCLC","timestamp":"09/08/2024"},{"finding":"Significant efficacy improvement across all subgroups including PD-L1 expression levels and histology types","timestamp":"09/08/2024"},{"finding":"Higher response rates with ivonescimab (ORR: 50.0% vs 38.5%; DCR: 89.9% vs 70.5%)","timestamp":"09/08/2024"},{"finding":"Manageable safety profile with slightly higher Grade ≥3 TRAEs (29% vs 16%) but similar immune-related AEs","timestamp":"09/08/2024"},{"finding":"First randomized Phase III trial showing superiority over pembrolizumab in this setting","timestamp":"03/07/2025"}],"label":"positive","events":[{"event_date":"2025-03-07","analysis":"Analysis:\n\nAkeso announced the publication results from Phase III clinical study (HARMONi-2/AK112-303) ivonescimab, as a monotherapy compared to pembrolizumab monotherapy in the first-line treatment of PD-L1 positive (PD-L1 TPS ≥1%) locally advanced or metastatic non-small cell lung cancer (NSCLC). The article entitled \"Ivonescimab versus pembrolizumab for PD-L1-positive non-small cell lung cancer (HARMONi-2): a randomised, double-blind, phase 3 study in China\" will be published in the Journal The Lancet on March 8, 2025.Data from this study were last seen in September 2024.ContextAt the 2024 World Conference on Lung Cancer (WCLC), the results of the HARMONi-2 study were presented as an oral report. Based on these results, the sNDA for ivonescimab monotherapy as a first-line treatment for PD-L1 positive NSCLC is under review with priority status in China. Ivonescimab in combination with chemotherapy for EGFR-TKI-resistant non-squamous NSCLC, has already been approved and included in the 2024 China National Reimbursement Drug List.Three international multicenter Phase III clinical trials, led by our partner Summit Therapeutics, are progressing efficiently or are being initiated:The HARMONi study, an international multicenter Phase III clinical trial evaluating ivonescimab in combination with chemotherapy for non-squamous NSCLC with progression after third-generation EGFR-TKI treatment, has had patient enrollment completed and has received Fast Track Designation (FTD) from the U.S. Food and Drug Administration (FDA),The HARMONi-3 study, an international multicenter Phase III clinical trial comparing ivonescimab combined with chemotherapy as first-line treatment for both squamous and non-squamous NSCLC (versus pembrolizumab combined with chemotherapy),The HARMONi-7 study, an international multicenter Phase III clinical trial evaluating ivonescimab monotherapy as first-line treatment for PD-L1 high-expressing NSCLC (versus pembrolizumab).Several Phase III clinical trials are progressing efficiently or are being initiated in China, including:Ivonescimab combined with chemotherapy as first-line treatment for squamous NSCLC (vs. tislelizumab combined with chemotherapy, HARMONi-6/AK112-306),Ivonescimab combined with chemotherapy as first-line treatment for biliary tract cancer (vs. durvalumab combined with chemotherapy, HARMONi-GI1/AK112-309),Ivonescimab combined with AK117 (CD47) as first-line treatment for PD-L1 positive head and neck squamous cell carcinoma (vs. pembrolizumab, SOLO-10/AK117-302),First-line treatment for triple-negative breast cancer (HARMONi-BC1/AK112-308).DesignPer the abstract, HARMONi-2 is a randomised, double-blind, phase 3 trial across 55 hospitals in China. Eligible patients were aged 18 years or older and had locally advanced or metastatic PD-L1-positive non-small cell lung cancer without sensitising epidermal growth factor receptor mutations or anaplastic lymphoma kinase translocations and an Eastern Cooperative Oncology Group performance-status of 0 or 1. Patients were randomly assigned (1:1) to receive 20 mg/kg ivonescimab or 200 mg pembrolizumab intravenously every 3 weeks. Randomisation was stratified by histology, clinical stage, and PD-L1 expression. Between Nov 9, 2022, and Aug 26, 2023, 398 (45%) of 879 screened patients were randomly assigned to receive ivonescimab (n=198) or pembrolizumab (n=200). EndpointsPer the abstract, the primary endpoint was progression-free survival (PFS) assessed by a masked independent radiographic review committee per RECIST v1.1 in the intention-to-treat population.ResultsThe HARMONi-2 study demonstrated that in the intent-to-treat population, ivonescimab monotherapy significantly extended progression-free survival (PFS) compared to pembrolizumab monotherapy, reducing the risk of disease progression by 49% (PFS HR 0.51, P<0.0001). Subgroup analyses revealed that regardless of patients' age, gender, ECOG performance status, PD-L1 expression, histological type, or the presence of liver or brain metastases, the ivonescimab group showed significant improvement in efficacy compared to the pembrolizumab group. Per the abstract, the PFS benefit of ivonescimab over pembrolizumab was broadly consistent within prespecified subgroups, including patients with PD-L1 tumour proportion score (TPS) 1–49% (HR 0·54 [95% CI 0·37–0·78]) and PD-L1 TPS of 50% of higher (HR 0·48 [0·29–0·79]). Most Common Adverse EventsPer the abstract, grade 3 or higher treatment-related adverse events occurred in 58 (29%) patients with ivonescimab and 31 (16%) patients with pembrolizumab. Immune-related adverse events of grade 3 or higher were observed in 14 (7%) of 197 patients on ivonescimab and 16 (8%) of 199 patients on pembrolizumab. Ivonescimab demonstrated a manageable safety profile in patients with both squamous and non-squamous non-small cell lung cancer. In patients with squamous cell carcinoma, grade 3 or higher treatment-related adverse events were comparable between the two groups.ConclusionThe ivonescimab HARMONi-2 study is the randomized, double-blind, controlled Phase III clinical trial to achieve significantly positive results compared to pembrolizumab."},{"event_date":"2024-05-30","analysis":"Summit Therapeutics announced interim data from the Phase III clinical trial HARMONi-2 or AK112-303 of ivonescimab in patients with locally advanced or metastatic non-small cell lung cancer (NSCLC) whose tumors have positive PD-L1 expression (PD-L1 TPS >1%).ContextThe Phase III HARMONi-2 study, along with the approval of ivonescimab in China in combination with chemotherapy based on the results of the HARMONi-A trial, provides clear evidence supporting the purposefully engineered, differentiated mechanism of action of ivonescimab and its opportunity to improve upon the existing standards of care for solid tumors.DesignHARMONi-2 is a single region, multi-center, double-blinded Phase III study conducted in China sponsored by Akeso. ResultsAt a prespecified interim analysis conducted by an independent Data Monitoring Committee, ivonescimab demonstrated a statistically significant and clinically meaningful improvement in PFS by blinded independent central radiology review committee (BICR) compared to pembrolizumab. The PFS benefit was demonstrated across clinical subgroups, including those with PD-L1 low expression (PD-L1 TPS 1-49%), PD-L1 high expression (PD-L1 TPS >50%), squamous and non-squamous histologies, as well as other high-risk patients.ConclusionThe Phase III HARMONi-2 study of ivonescimab met its primary endpoint of progression-free survival (PFS)."},{"event_date":"2024-09-08","analysis":"Akeso announced data from the primary analysis of the Phase III HARMONi-2 study of ivonescimab monotherapy to pembrolizumab monotherapy as a first-line treatment for PD-L1-positive locally advanced or metastatic non-small cell lung cancer (NSCLC). The abstract entitled \"Phase 3 Study of Ivonescimab (AK112) vs. Pembrolizumab as First-line Treatment for PD-L1-positive Advanced NSCLC: Primary Analysis of HARMONi-2\" was presented at the International Association for the Study of Lung Cancer’s (IASLC) 2024 World Conference on Lung Cancer (WCLC 2024) on September 8, 2024.Data from the study were last seen in May 2024.ContextBased on the results of HARMONi-2, the company's partner, Summit, plans to initiate HARMONi-7 in early 2025. HARMONi-7 is currently planned as a multi-regional Phase III clinical trial that will compare ivonescimab monotherapy to pembrolizumab monotherapy in metastatic NSCLC patients whose tumors have high PD-L1 expression (PD-L1 TPS≥50%).DesignHARMONi-2 is a single-region, multi-center, double-blinded Phase III study conducted in China. 45.5% of the enrolled patients had squamous (sq)-NSCLC, and 54.5% had non-squamous (nsq)-NSCLC. In this study, 12.6% of patients treated with ivonescimab had liver metastasis, and 7% had brain metastasis. In the study, 72.2% of patients with squamous cell carcinoma (sq-NSCLC) treated with ivonescimab had centrally located tumors, 10.0% had tumors with cavitation or necrosis, and 6.7% had tumors encasing large blood vessels. The HARMONi-2 study enrolled participants with PD-L1 TPS ≥50%, accounting for 42.2%, aligning with the distribution in real-world populations.Per the abstract, eligible pts with untreated locally advanced or metastatic NSCLC, ECOG PS 0-1, PD-L1-positive (TPS ≥1%) but negative EGFR mutations or ALK rearrangements were randomized (in a 1:1 ratio) to receive either 20 mg/kg of ivonescimab or 200 mg of pembrolizumab every 3 weeks. Randomization was stratified by histology (squamous vs. non-squamous), clinical stage (IIIB/IIIC vs. IV) and PD-L1 expression (TPS 1-49% vs. TPS ≥50%). From November 2022 to August 2023, a total of 398 pts from 55 centers in China were randomized (198 in the ivonescimab arm and 200 in the pembrolizumab arm). EndpointsPer the abstract, the primary endpoint was progression-free survival (PFS), as assessed by blinded, independent radiographic review committee (IRRC) per RECIST v1.1. Secondary endpoints included overall survival (OS), which is to be tested based on the number of prespecified events when these events occurred, investigator-assessed PFS, objective response rate (ORR), duration of response (DoR), disease control rate (DCR), and safety.ResultsIn the HARMONi-2 study, baseline characteristics were well balanced between the experimental and control groups. In the intention-to-treat (ITT) population, ivonescimab significantly improved PFS compared to pembrolizumab, reducing the risk of disease progression or death. Subgroup analyses revealed that ivonescimab outperformed pembrolizumab across various factors, including age, sex, ECOG performance status, PD-L1 expression, histological type, and the presence of liver or brain metastases. PFS-Stratified HR 0.51, mPFS 11.14 MonthsIvonescimab as first-line treatment for PD-L1-positive NSCLC significantly extends median progression-free survival (mPFS) compared to pembrolizumab, with both statistical and clinical significance.In the ITT population, ivonescimab demonstrated a median progression-free survival (mPFS) of 11.14 months compared to 5.82 months for pembrolizumab. The PFS hazard ratio (HR) was 0.51 (P<0.0001), indicating a significant 49% reduction in the risk of disease progression or death.Ivonescimab significantly improved the objective response rate (ORR) and disease control rate (DCR) compared to pembrolizumab in the first-line treatment of PD-L1-positive non-small cell lung cancer (NSCLC) patients. The ORR for ivonescimab was 50.0%, versus 38.5% for pembrolizumab, while the DCR was 89.9% for ivonescimab versus 70.5% for pembrolizumab. These results highlight ivonescimab's effective anti-tumor effect.Overall survival data were not yet mature at the time of the data cutoff and will be evaluated in the future.Significant Progression-Free Survival Benefits of Ivonescimab Across PD-L1 Expression SubgroupsIvonescimab demonstrated significant progression-free survival benefits in patients with both low and high PD-L1.In the PD-L1 TPS ≥50% population, the PFS HR for ivonescimab versus pembrolizumab was 0.46, reducing the risk of disease progression/death by 54%.In the PD-L1 TPS 1-49% population, the PFS HR for ivonescimab versus pembrolizumab was 0.54, reducing the risk of disease progression/death by 46%.Ivonescimab showed meaningful progression-free survival benefits in both squamous and non-squamous subgroupsIn sq-NSCLC subgroup, the PFS HR for ivonescimab and pembrolizumab was 0.48.In nsq-NSCLC subgroup, the PFS HR for ivonescimab and pembrolizumab was 0.54.Ivonescimab monotherapy demonstrated significant efficacy regardless of liver metastasis, brain metastasis, or a history of hemoptysis.The PFS HR for ivonescimab and pembrolizumab in patients with brain metastasis was 0.55; in those without brain metastasis, the PFS HR was 0.53.The PFS HR for ivonescimab and pembrolizumab in patients with liver metastasis was 0.47; in those without liver metastasis, the PFS HR was 0.53.Most Common Adverse EventsIvonescimab demonstrated an acceptable and manageable safety profile across subgroupsDespite the factors, which typically contraindicate traditional anti-VEGF therapies due to bleeding risks, ivonescimab did not significantly increase bleeding compared to the control group. The study confirms that ivonescimab has an acceptable and manageable overall safety profile, consistent with prior research.The incidence of grade 3 or higher treatment-related adverse events (TRAEs) in sq-NSCLC patients treated with ivonescimab was comparable to that in the pembrolizumab group (22.2% vs.7%).HRQoL with ivonescimab was comparable to pembrolizumab.Comparable serious treatment-related adverse events and TRAE-led discontinuation rates were observed; serious TRAEs were 20.8% vs. 16.1%, respectively, in ivonescimab and pembrolizumab arms. The most frequent treatment-related adverse events (TRAEs) for ivonescimab treatment were proteinuria (Grade 3+: ivonescimab, 3.0%; pembrolizumab 0.0%), hypertension (Grade 3+: ivonescimab, 5.1%; pembrolizumab 0.5%), and various laboratory abnormalities, including AST increases, hypercholesterolemia, anemia, and bilirubin increases. Grade 3 or higher immune-related adverse events occurred in 7.1% of patients receiving ivonescimab and 8.0% of patients receiving pembrolizumab. Grade 3 or higher adverse events that were possibly VEGF-related in the ivonescimab monotherapy arm were 10.2% vs. 1.0% for pembrolizumab, all of which were classified as Grade 3. Of note, Grade 3 hemorrhage events were observed in two patients in the ivonescimab arm (both were of non-squamous histology) compared to one patient in the pembrolizumab arm in this study.ConclusionThe clinical outcomes of ivonescimab versus pembrolizumab in this Phase III study demonstrated efficacy and a manageable safety profile, while affirming the ability of ivonescimab as a treatment in cancer immunotherapy."}],"url":"https://test.noahai.co/detail/clinical-trial/65504"},{"nct_id":"NCT04900363","primary_id":"NCT04900363","last_updated":"2023-10-01","official_title":"A Phase Ib/II Trial of AK112 (PD-1/VEGF Bispecific Antibody) in Patients With Advanced NSCLC","lead_company":"Summit Therapeutics plc (SMMT)","partner_companies":["Akeso Inc."],"drug_name":["Ivonescimab/AK112"],"drug_modality":["Polyclonal Antibodies","Bi-specific Antibodies","Monoclonal Antibodies"],"drug_feature":["Precision Medicine"],"route_of_administration":["Intravenous (IV)"],"indication_name":["Non-small-cell lung cancer"],"target":["VEGF (Vascular endothelial growth factor)","Immune System","Programmed death-1 receptor (PD-1)"],"phase":"I/II","phase_mapping":["I","II"],"current_status":"Final Data","gender":"Both","actual_enrollment":108,"locations":["China"],"key_findings":[{"finding":"Significant intracranial activity demonstrated with median PFS of 19.3 months in brain metastases patients","timestamp":"2024-03-22"},{"finding":"Strong PD-L1-dependent efficacy with ORR of 51.4% in PD-L1 ≥1% patients and 57.1% in PD-L1 ≥50% patients","timestamp":"2023-10-23"},{"finding":"Favorable safety profile with 22.2% Grade ≥3 TRAEs and low discontinuation rate (0.9%)","timestamp":"2023-10-23"},{"finding":"No intracranial bleeding complications in brain metastases patients, supporting safety in this high-risk population","timestamp":"2024-03-22"}],"label":"positive","events":[{"event_date":"2023-10-23","analysis":"Akeso announced that the results of a Phase Ib clinical trial for PD-1/VEGF bispecific antibody (ivonecimab AK112/SMT112) as first- or second-line therapy for advanced or metastatic immunotherapy naïve non-small-cell lung cancer (NSCLC) were published in the Journal of Thoracic Oncology (JTO), the official journal of the International Association for the Study of Lung Cancer (IASLC), in an article entitled \"A phase Ib study of ivonescimab, a PD-1/VEGF bispecific antibody, as first- or second-line therapy for advanced or metastatic immunotherapy naïve non-small-cell lung cancer\" on October 23, 2023.Data from this study were last seen in June 2022.ContextPreviously, the clinical results of ivonescimab in combination with chemotherapy for NSCLC were published in the eClinical Medicine (part of The Lancet). Currently, following an acceptance of the marketing application with priority review of ivonescimab by the Center for Drug Evaluation (CDE) of the China National Medical Products Administration (NMPA), four registrational Phase III clinical trials have been initiated/are being conducted worldwide, including three head-to-head trials with PD-1 monoclonal antibody as the positive control drug, and two international multicenter clinical trials.DesignThe Phase Ib study, published in JTO, aims to determine the optimal dose, safety, and efficacy of ivonescimab monotherapy as a first- or second-line treatment for advanced NSCLC patients.Per the article, this study aimed to evaluate the safety and efficacy of ivonescimab (a bispecific antibody against programmed death-1 [PD-1] and vascular endothelial growth factor [VEGF]) as first- or second-line monotherapy in advanced immunotherapy naïve non-small-cell lung cancer (NSCLC) patients. Eligible patients received intravenous ivonescimab 10mg/kg every 3 weeks (Q3W), 20 mg/kg every 2 weeks (Q2W), 20 mg/kg Q3W or 30mg/kg Q3W. EndpointsPer the article, the primary endpoints were safety and objective response rate (ORR) per RECIST v1.1.ResultsFrom the data published in JTO, patients with advanced or metastatic NSCLC can benefit from ivonescimab monotherapy regardless of treatment dosage, prior treatment history, and PD-L1 expression. This data was based on a median follow-up of 10.4 months (as of October 5, 2022). Furthermore, updated data from the study (with a median follow-up of 19.3 months) as of June 30, 2023 demonstrates the increased safety and survival benefits of ivonescimab monotherapy.Per the article, at data cutoff (October 5, 2022), 108 patients were enrolled and received ivonescimab. Programmed death ligand-1 (PD-L1) tumor proportion score (TPS) was ≥1% in 74 (68.5%) patients, including 35 (32.4%) with TPS ≥50%. The median follow-up was 10.4 months (range 8.4 to 10.9 months). For all patients, ORR and disease control rate (DCR) were 39.8% and 86.1%, respectively. ORR by TPS was 14.7%, 51.4% and 57.1% in patients with TPS <1%, ≥1%, and ≥50%, respectively. In the 67 PD-L1 positive patients receiving first-line ivonescimab, the ORR was 33.3%, 52.6%, 60.0%, and 75.0% at the doses of 10mg/kg Q3W, 20 mg/kg Q2W, 20 mg/kg Q3W and 30mg/kg Q3W, respectively.Most Common Adverse Events​​​​​​​Per the article, grade ≥3 treatment-related adverse events (TRAEs) were observed in 24 (22.2%) patients. TRAEs leading to treatment discontinuation occurred in 1 (0.9%) patient. TRAEs leading to death occurred in 3 (2.8%) patients with squamous histology. The occurrence of grade ≥3 TRAEs and grade ≥3 bleeding events in squamous versus non-squamous histologies were 25.5% vs. 18.9% and 0.0% vs. 1.9%, respectively.Conclusion​​​​​​​​​​​​​​Per the article, ivonescimab monotherapy was well tolerated and demonstrated promising efficacy in patients with advanced or metastatic NSCLC."},{"event_date":"2022-06-05","analysis":"Akeso released clinical details in poster discussion featuring a phase II study from  Ivonescimab (PD-1/VEGF BsAbs, AK112) in combination with chemotherapy for advanced non-small cell lung cancer (NSCLC) at 2022 ASCO Annual Meeting. An abstract entitled \"A phase Ib/II study of AK112, a PD-1/VEGF bispecific antibody, as first- or second-line therapy for advanced non–small cell lung cancer (NSCLC)\" was presented on June 5, 2022.ContextAkeso is conducting a Phase III clinical trial of AK112 plus chemotherapy versus chemotherapy in EGFR mutated advanced non-squamous NSCLC that failed in prior EGFR-TKI therapy. A Phase III head-to-head study of AK112 monotherapy versus Pembrolizumab monotherapy in the first-line treatment of NSCLC is also ongoing.DesignPer the abstract, patients with stage IIIB/IIIC/IV NSCLC, ECOG PS 0-1 and negative oncogenic drivers were enrolled and given AK112 (10 mg/kg Q3W, 20 mg/kg Q2W, 20 mg/kg Q3W or 30 mg/kg Q3W) intravenously.EndpointsPer the abstract, the primary endpoints were ORR per RECIST v1.1 and safety.ResultsAs of March 20, 2022, in this multi-cohort, multi-center phase II study, a total of 83 patients with advanced NSCLC had been treated with AK112 in combination with chemotherapy for up to 12 months and an average dosing time of 7.56 months.AK112 in combination with chemotherapy showed better anti-tumor activity in advanced NSCLC patients in various sub-types compared to PD-1/PD-L1 antibody combined with chemotherapy +/- anti-angiogenic agents combination therapyIn cohort 1(previously untreated advanced NSCLC patients without EGFR/ALK alterations),  efficacy results were encouraging with a more prominent efficacy advantage in squamous NSCLC patients:Among all patients, median progression-free survival (PFS) was not reached, and 6-month PFS rate was 78.8%.In patients with SQ-NSCLC, median follow-up time was 7.9 months, objective response rate (ORR) was 77.8%, disease control rate (DCR) was 100%, and 6-month PFS rate was 83.3%, which are encouraging compared to approved PD-1 combined with chemotherapy therapies.In cohort 2 (advanced NSCLC patients who failed to prior EGFR-TKI therapy):ORR and DCR were 68.4% and 94.7% respectively.Median PFS was 8.2 months, 6-month PFS rate was 69.3%.In cohort 3 (advanced NSCLC patients who failed in prior platinum-based doublet chemo with anti-PD-1/PD-L1 therapy):ORR was 40.0%, DCR was 80%.Median PFS was 6.6 months, 6-month PFS rate was 51.1%.Per the abstract, at data cutoff (January 5, 2022), 94 pts were enrolled: median age 66.0 years (range: 48-75), PS 1 90.4%, male 85.1%, non-squamous 48.9%, PD-L1 positive (TPS ≥1%) 70.2% and treatment-naïve 84.0%. Of 83 pts evaluable for efficacy, ORR (unconfirmed, similarly hereinafter) and DCR were 22.2%/88.9%, 44.0%/92.0%, 37.9%/93.1% and 100%/100% at doses of 10 mg/kg Q3W, 20 mg/kg Q2W, 20 mg/kg Q3W and 30 mg/kg Q3W, respectively. When doses of AK112 > 10mg/kg Q3W, ORR and DCR were 42.9% (24/56) and 92.9% (52/56) in 56 evaluable pts, 56.3% (18/32) and 100% (32/32) in pts with TPS≥1% at 1st line setting, and 23.5% (4/17) and 76.5% (13/17) in pts with PD-L1 TPS < 1%, respectively. Most Common Adverse EventAK112 in combination with chemotherapy for advanced NSCLC showed favourable safety profileNo significant difference in the incidences of TRAEs between the squamous and the non-squamous NSCLC patients (30.1% of enrolled patients had squamous NSCLC (SQ-NSCLC), of which 52% were central type SQ-NSCLC).No serious anti-VEGF-related toxicities such as bleeding and perforation.Per the abstract, grade≥3 treatment-related adverse events (TRAEs) occurred in 10.6% (10/94) pts, in which the most common event (occurring in > 1 pt) was pneumonia (2.1%, 2/94). No TRAEs led to permanent treatment discontinuation. Most frequent TRAEs (incidence ≥10%) were proteinuria (17.0%), hypertension (16.0%), lipase increase (12.8%), alanine aminotransferase increase (12.8%), blood urea increase (10.6%), apolipoprotein E increase (10.6%) and hyperglycaemia (10.6%). No significant difference in the incidences of TRAEs were observed between non-squamous and squamous pts.ConclusionPer the abstract, in advanced NSCLC, AK112 was well-tolerated and presented remarkable anti-tumor efficacy. Further Phase III studies are planned to validate the findings of this study."},{"event_date":"2024-03-22","analysis":"Summit Therapeutics announced data from a Phase II studies of ivonescimab for NSCLC at the 2024 European Lung Cancer Congress (ELCC 2024). The abstract entitled \"Intracranial (IC) activity of ivonescimab (ivo) alone or in combination with platinum doublet chemotherapy (PC) in patients (Pts) with advanced non-small cell lung cancer (aNSCLC) and brain metastases (BMs)\" was presented on March 22, 2024.Data from these studies were last seen in October 2023 and January 2024 respectively.ContextSummit continues its clinical development of ivonescimab in order to establish its efficacy and safety in two NSCLC indications:HARMONi Phase III trial: ivonescimab combined with chemotherapy in patients with EGFR-mutated, locally advanced or metastatic non-squamous NSCLC who have progressed after treatment with a third-generation EGFR TKI.HARMONi-3 Phase III trial: ivonescimab combined with chemotherapy in first-line metastatic squamous NSCLC patients.DesignThese patients were enrolled in either AK112-202, in which ivonescimab is delivered as monotherapy, or AK112-201, in which ivonescimab is delivered in combination with platinum doublet chemotherapy, both of which are Phase II clinical trials for patients with advanced or metastatic NSCLC. This analysis consisted of the 35 patients with advanced or metastatic NSCLC who had asymptomatic brain metastases at baseline; 28 patients were treated with ivonescimab plus chemotherapy in AK112-201, and seven patients were treated with monotherapy ivonescimab in AK112-202.Per the abstract, pts with aNSCLC of any histology, no prior systemic therapy for cancer, and a performance status of 0-1 were eligible for ivo combined with PC or ivo alone on the AK112-201 and AK112-202 trials, respectively, enrolled from 2 centers in China. PC was continued for up to 4 cycles on AK112-201, while ivo continued until progressing disease or up to 2 years in both trials. Initial workup at BL included brain imaging with a brain MRI or head CT with cuts 5mm or smaller to identify BMs; pts with BMs at BL were eligible if without symptoms attributable to BMs. Pts who received pre-study radiotherapy to BMs or who could not undergo follow-up MRI with contrast due to an allergy were not evaluable for IC response. For those with BMs at BL, repeat brain imaging (with a brain MRI every 6 weeks) was pursued while on protocol-based treatment. BMs were evaluated serially by Response Assessment in Neuro-Oncology (RANO) criteria by 2 independent neuroradiologists (US and China) and adjudicated by a third (US-based) as needed.ResultsMedian intracranial progression-free survival was 19.3 months across all patients analyzed. Patients across both cohorts experienced an intracranial response rate of 34%, and eight patients (23%) experienced a complete response by RANO criteria. All patients who did not achieve a response demonstrated stable disease or non-progression; no patients experienced intracranial disease progression at the time of the initial follow-up scan.Per the abstract, a combined group of 35 pts met the criteria for inclusion in this analysis: 28 out of 174 on AK112-201, and 7 out of 108 on AK112-202. These pts had a median age of 60 (range 42-68), 77% male, 74% adenocarcinoma/14% squamous/11% other, 46% with PD-L1 >1%. Review of response of BMs across both studies showed 12 pts (34%) achieved an IC response. Of these, 11 had received PC/ivo, among whom 7 achieved an IC complete response (CR); 1 pt achieved an IC CR among the 7 pts who received ivo alone. Median IC progression-free survival was 19.3 months (mo) across both studies (19.3 mo in AK112-201, 16.6 mo in AK112-202).Most Common Adverse EventsNo cases of intracranial bleeding complications were observed in these patients.Per the abstract, No pts with BMs experienced IC bleeding on or in the 3 mo following ivo +/- PC.ConclusionPer the abstract, Ivo +/- PC led to IC responses in a subset of pts with previously untreated BMs at BL, including CR in pts receiving ivo with chemo and as monotherapy. Ivo was not associated with IC hemorrhage in these studies."}],"url":"https://test.noahai.co/detail/clinical-trial/65500"}],"competing_drug_trial_data":[]},{"title":"Phase III - HARMONi-6 - Top-Line Results","expected_date_start":"2025-05-06","expected_date_end":"2025-12-31","clinical_analysis_phase":"III","expected_catalyst_type":"Trial Data - Top-Line Results","drug_name":"Ivonescimab","indication_name":"Non-Small Cell Lung Cancer (NSCLC)","lead_company_symbol":"","company":["Akeso Inc.","Shanghai Pharmaceutical Group Co., Ltd (601607)","Summit Therapeutics plc (SMMT)"],"id":624709}]""",
            "language": 'CN',
            "model": '',
            "enable_rag": False,
        },
        #"is_hitl": True
    }
    await chat(body=body)

async def test_mindsearchworkflowrefer_clinical():
    body = {
        "user_prompt": "Which drug is considered best-in-class based on the provided data? ",
        #"user_prompt": "Which drug is considered best-in-disease based on the provided data?   ",
        #"user_prompt": "Can you summarize the clinical data for me?   ",
        #"user_prompt": "Please extract and summarize the primary endpoints from the provided clinical trial data.  ",
        "agent": "mindsearchworkflowrefer",
        "history_messages": [],
        "params": {
            "background": """Selected clinical trial result data: [{"id":891,"nct_id":"NCT00090233","primary_id":"NCT00090233","last_updated":"2013-02-01","official_title":"Safety and Efficacy of Pentavalent (G1, G2, G3, G4 , and P1) Human-Bovine Reassortant Rotavirus Vaccine in Healthy Infants","lead_company":"Merck & Co., Inc. (MRK)","partner_companies":["DRI Capital Inc.","Royalty Pharma plc (RPRX)"],"drug_name":["RotaTeq"],"drug_modality":["Vaccine"],"drug_feature":[],"route_of_administration":["Oral (PO)"],"indication_name":["Rotavirus infection"],"target":["Immune System","Rotavirus"],"phase":"III","phase_mapping":["III"],"current_status":"Final Data","gender":"Both","actual_enrollment":69274,"locations":null,"design":"- Study Design : Double-blind, randomized, placebo-controlled study across 11 countries\n- Total Population : 68,038 infants (34,035 vaccine group, 34,003 placebo group)\n- Age Range : 6-12 weeks at enrollment\n- Treatment Schedule : Three doses of vaccine or placebo, given 4-10 weeks apart\n- Study Period : Started in 2001\n- Study Locations : United States, Belgium, Costa Rica, Finland, Germany, Guatemala, Italy, Jamaica, Mexico, Sweden, Taiwan","efficacy":"- Primary Efficacy (Severe Disease) : 98% efficacy against severe rotavirus gastroenteritis (1 case vaccine vs. 51 cases placebo, n=5,673)\n- Overall Efficacy : 74% efficacy against any severity rotavirus gastroenteritis for targeted serotypes (G1-G4)\n- Healthcare Utilization :\n  - 96% reduction in hospitalizations (6 vaccine vs. 138 placebo)\n  - 94% reduction in ER visits (13 vaccine vs. 191 placebo)\n  - 86% reduction in office/clinic visits\n- Total Cases : 397 cases of any severity (82 vaccine vs. 315 placebo) ≥14 days after third dose through first full rotavirus season","safety":"- Adverse Events (n=9,605) :\n  - Fever: 40.9% vaccine vs. 43.0% placebo\n  - Vomiting: 12.8% vaccine vs. 13.4% placebo\n  - Diarrhea: 19.7% vaccine vs. 19.1% placebo\n  - Hematochezia: 0.6% in both groups\n- Overall Safety : ROTATEQ was generally well-tolerated compared to placebo\n- Monitoring : All participants monitored for serious adverse events, including intussusception","key_findings":[{"finding":"ROTATEQ demonstrated 98% efficacy against severe rotavirus gastroenteritis in targeted serotypes (G1-G4)","timestamp":"01/04/2006"},{"finding":"Significant reduction in healthcare utilization: 96% fewer hospitalizations and 94% fewer ER visits","timestamp":"01/04/2006"},{"finding":"74% overall efficacy against rotavirus gastroenteritis of any severity","timestamp":"01/04/2006"},{"finding":"Similar adverse event rates between vaccine and placebo groups, demonstrating favorable safety profile","timestamp":"01/04/2006"},{"finding":"Large-scale trial (n=68,038) demonstrated both safety and efficacy across diverse geographic locations","timestamp":"01/04/2006"}],"sources":[],"label":"positive"},{"id":4373,"nct_id":"NCT00140673","primary_id":"NCT00140673","last_updated":"2013-02-01","official_title":"A Placebo-controlled, Multi-country & Multi-center Study to Assess the Efficacy, Safety & Immunogenicity of 2 Doses of GSK Biologicals' Oral Live Attenuated Human Rotavirus (HRV) Vaccine in Healthy Infants","lead_company":"GSK plc (GSK)","partner_companies":["Celldex Therapeutics, Inc. (CLDX)"],"drug_name":["Rotarix"],"drug_modality":["Vaccine"],"drug_feature":[],"route_of_administration":["Oral (PO)"],"indication_name":["Rotavirus infection"],"target":["Immune System","Rotavirus"],"phase":"III","phase_mapping":["III"],"current_status":"Final Data","gender":"Both","actual_enrollment":63227,"locations":["Argentina","Brazil","Chile","Colombia","Dominican Republic","Finland","Honduras","Mexico","Nicaragua","Panama","Peru","Venezuela"],"design":"- Total study population [[1]](http://content.nejm.org/cgi/content/abstract/354/1/11): 63,225 healthy infants from 11 Latin American countries and Finland\n- Vaccine arm [[1]](http://content.nejm.org/cgi/content/abstract/354/1/11): 31,673 infants received two oral doses of Rotarix at ~2 and 4 months of age\n- Placebo arm [[1]](http://content.nejm.org/cgi/content/abstract/354/1/11): 31,552 infants received two oral doses of placebo at ~2 and 4 months of age\n- Efficacy evaluation subgroup [[1]](http://content.nejm.org/cgi/content/abstract/354/1/11): 20,169 infants (10,159 vaccinees and 10,010 placebo recipients)\n- Disease severity assessment [[1]](http://content.nejm.org/cgi/content/abstract/354/1/11): 20-point Vesikari scale\n- Active surveillance was conducted for severe gastroenteritis episodes","efficacy":"- Primary endpoint - Severe rotavirus gastroenteritis [[1]](http://content.nejm.org/cgi/content/abstract/354/1/11): 85% efficacy vs placebo (P<0.001)\n- Secondary endpoint - More severe rotavirus gastroenteritis [[1]](http://content.nejm.org/cgi/content/abstract/354/1/11): 100% efficacy\n- Secondary endpoint - Rotavirus-associated hospitalization [[1]](http://content.nejm.org/cgi/content/abstract/354/1/11): 85% reduction\n- Secondary endpoint - Hospitalization for diarrhea (any cause) [[1]](http://content.nejm.org/cgi/content/abstract/354/1/11): 42% reduction (95% CI: 29-53%, P<0.001)","safety":"- Intussusception risk (31-day window post-vaccination) [[1]](http://content.nejm.org/cgi/content/abstract/354/1/11):\n  - Vaccine group: 6 cases\n  - Placebo group: 7 cases\n  - Risk difference: -0.32 per 10,000 infants (95% CI: -2.91 to 2.18, P=0.78)\n- No increased risk of intussusception associated with vaccination","key_findings":[{"finding":"Rotarix showed 85% efficacy against severe rotavirus gastroenteritis (P<0.001) and 100% efficacy against more severe cases","timestamp":"01/05/2006"},{"finding":"Hospitalization for diarrhea of any cause was reduced by 42% (95% CI: 29-53%, P<0.001)","timestamp":"01/05/2006"},{"finding":"No increased risk of intussusception was observed (risk difference: -0.32 per 10,000 infants, 95% CI: -2.91 to 2.18, P=0.78)","timestamp":"01/05/2006"}],"sources":[{"id":1,"link":"http://content.nejm.org/cgi/content/abstract/354/1/11","title":"Journal Abstract 01/05/2006","published":"2006-01-05"}],"label":"positive"},{"id":59350,"nct_id":"NCT04505722","primary_id":"NCT04505722","last_updated":"2022-02-01","official_title":"A Randomized, Double-blind, Placebo-controlled Phase 3 Study to Assess the Efficacy and Safety of Ad26.COV2.S for the Prevention of SARS-CoV-2-mediated COVID-19 in Adults Aged 18 Years and Older","lead_company":"Johnson & Johnson (JNJ)","partner_companies":null,"drug_name":["Jcovden/Ad26.COV2.S"],"drug_modality":["Vaccine"],"drug_feature":[],"route_of_administration":["Intramuscular (IM) Injection"],"indication_name":["Coronavirus disease 19 infection"],"target":["Immune System","SARS-CoV-2"],"phase":"III","phase_mapping":["III"],"current_status":"Final Data","gender":"Both","actual_enrollment":44325,"locations":["Argentina","Brazil","Chile","Colombia","Mexico","Peru","South Africa","United States"],"design":"- Single-dose Ad26.COV2.S COVID-19 vaccine trial (5×10¹⁰ viral particles) vs placebo [[1]](https://www.jnj.com/johnson-johnson-announces-single-shot-janssen-covid-19-vaccine-candidate-met-primary-endpoints-in-interim-analysis-of-its-phase-3-ensemble-trial)[[2]](https://www.janssen.com/johnson-johnson-announces-single-shot-janssen-covid-19-vaccine-candidate-met-primary-endpoints)[[3]](https://www.janssen.com/japan/press-release/20210201)\n- Phase III ENSEMBLE study: randomized, double-blind, placebo-controlled [[4]](https://www.nejm.org/doi/full/10.1056/NEJMoa2101544)\n- Total enrollment: 43,783 participants across 8 countries [[4]](https://www.nejm.org/doi/full/10.1056/NEJMoa2101544)\n- Geographic distribution: US (44%), Central/South America (41%), South Africa (15%) [[1]](https://www.jnj.com/johnson-johnson-announces-single-shot-janssen-covid-19-vaccine-candidate-met-primary-endpoints-in-interim-analysis-of-its-phase-3-ensemble-trial)[[2]](https://www.janssen.com/johnson-johnson-announces-single-shot-janssen-covid-19-vaccine-candidate-met-primary-endpoints)[[3]](https://www.janssen.com/japan/press-release/20210201)\n- Demographics: 45% female, 55% male; 34% age >60; 41% with comorbidities [[1]](https://www.jnj.com/johnson-johnson-announces-single-shot-janssen-covid-19-vaccine-candidate-met-primary-endpoints-in-interim-analysis-of-its-phase-3-ensemble-trial)[[2]](https://www.janssen.com/johnson-johnson-announces-single-shot-janssen-covid-19-vaccine-candidate-met-primary-endpoints)[[3]](https://www.janssen.com/japan/press-release/20210201)\n- Median follow-up: 4 months; 8,940 participants with ≥6 months follow-up [[5]](https://www.nejm.org/doi/full/10.1056/NEJMoa2117608)","efficacy":"- Primary endpoint (14-day): 56.3% efficacy (95% CI: 51.3-60.8) against moderate to severe-critical COVID-19 [[5]](https://www.nejm.org/doi/full/10.1056/NEJMoa2117608)\n- Primary endpoint (28-day): 52.9% efficacy (95% CI: 47.1-58.1) against moderate to severe-critical COVID-19 [[5]](https://www.nejm.org/doi/full/10.1056/NEJMoa2117608)\n- Severe-critical COVID-19: 74.6% efficacy (95% CI: 64.7-82.1) [[5]](https://www.nejm.org/doi/full/10.1056/NEJMoa2117608)\n- Medical intervention: 75.6% efficacy (95% CI: 54.3-88.0) [[5]](https://www.nejm.org/doi/full/10.1056/NEJMoa2117608)\n- COVID-19 related death: 82.8% efficacy (95% CI: 40.5-96.8) [[5]](https://www.nejm.org/doi/full/10.1056/NEJMoa2117608)\n- Any SARS-CoV-2 infection: 41.7% efficacy (95% CI: 36.3-46.7) [[5]](https://www.nejm.org/doi/full/10.1056/NEJMoa2117608)\n- US-specific efficacy: 69.7% (95% CI: 60.7-76.9) against reference strain and alpha variant [[5]](https://www.nejm.org/doi/full/10.1056/NEJMoa2117608)\n- Protection maintained for ≥6 months [[5]](https://www.nejm.org/doi/full/10.1056/NEJMoa2117608)","safety":"- Generally mild-to-moderate adverse events profile [[5]](https://www.nejm.org/doi/full/10.1056/NEJMoa2117608)\n- Overall fever rate: 9%, Grade 3 fever: 0.2% [[1]](https://www.jnj.com/johnson-johnson-announces-single-shot-janssen-covid-19-vaccine-candidate-met-primary-endpoints-in-interim-analysis-of-its-phase-3-ensemble-trial)[[2]](https://www.janssen.com/johnson-johnson-announces-single-shot-janssen-covid-19-vaccine-candidate-met-primary-endpoints)[[3]](https://www.janssen.com/japan/press-release/20210201)\n- No anaphylaxis cases reported [[1]](https://www.jnj.com/johnson-johnson-announces-single-shot-janssen-covid-19-vaccine-candidate-met-primary-endpoints-in-interim-analysis-of-its-phase-3-ensemble-trial)[[2]](https://www.janssen.com/johnson-johnson-announces-single-shot-janssen-covid-19-vaccine-candidate-met-primary-endpoints)[[3]](https://www.janssen.com/japan/press-release/20210201)\n- Mortality: 3 deaths in vaccine group (non-COVID-19 related), 16 in placebo group (5 COVID-19 related) [[4]](https://www.nejm.org/doi/full/10.1056/NEJMoa2101544)\n- No new safety concerns identified in final analysis [[5]](https://www.nejm.org/doi/full/10.1056/NEJMoa2117608)\n- Balanced serious adverse events between vaccine and placebo groups [[4]](https://www.nejm.org/doi/full/10.1056/NEJMoa2101544)","key_findings":[{"finding":"Single-dose vaccine demonstrated 52.9% overall efficacy against moderate to severe-critical COVID-19 at 28 days post-vaccination, with higher protection (74.6%) against severe-critical disease","timestamp":"2022-02-09"},{"finding":"Efficacy against COVID-19-related death was 82.8% (95% CI: 40.5-96.8), with protection lasting 6 months or longer","timestamp":"2022-02-09"},{"finding":"Geographic variation in efficacy: 69.7% in US, lower in regions with prevalent variants (P.1, C.37, and B.1.621)","timestamp":"2022-02-09"},{"finding":"Demonstrated neutralizing activity against Delta variant at higher levels than Beta variant","timestamp":"2021-07-01"},{"finding":"Safety profile showed mainly mild-to-moderate adverse events with no significant safety concerns across all analyzed timepoints","timestamp":"2022-02-09"}],"sources":[{"id":1,"link":"https://www.jnj.com/johnson-johnson-announces-single-shot-janssen-covid-19-vaccine-candidate-met-primary-endpoints-in-interim-analysis-of-its-phase-3-ensemble-trial","title":"Press Release 01/29/2021","published":"2021-01-29"},{"id":2,"link":"https://www.janssen.com/johnson-johnson-announces-single-shot-janssen-covid-19-vaccine-candidate-met-primary-endpoints","title":"Press Release 01/29/2021","published":"2021-01-29"},{"id":3,"link":"https://www.janssen.com/japan/press-release/20210201","title":"Press Release 02/01/2021","published":"2021-01-29"},{"id":4,"link":"https://www.nejm.org/doi/full/10.1056/NEJMoa2101544","title":"New England Journal of Medicine 04/21/2021","published":"2021-04-21"},{"id":5,"link":"https://www.nejm.org/doi/full/10.1056/NEJMoa2117608","title":"New England Journal of Medicine 02/09/2022","published":"2022-02-09"}],"label":"positive"},{"id":17262,"nct_id":"NCT00861380","primary_id":"NCT00861380","last_updated":"2012-05-01","official_title":"Evaluation of Effectiveness of GSK Biologicals' Pneumococcal Conjugate Vaccine 1024850A Against Invasive Disease","lead_company":"GSK plc (GSK)","partner_companies":null,"drug_name":["Synflorix"],"drug_modality":["Vaccine"],"drug_feature":[],"route_of_administration":["Intramuscular (IM) Injection"],"indication_name":["Streptococcus pneumoniae infection"],"target":["Immune System","Streptococcus pneumoniae / Pneumococcus"],"phase":"III","phase_mapping":["III"],"current_status":"Final Data","gender":"Both","actual_enrollment":41188,"locations":["Finland"],"design":"- Study Type [[1]](http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html)[[2]](http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract): Cluster-randomised, double-blind trial\n- Total Enrollment [[1]](http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html)[[2]](http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract): 47,369 children\n- Study Period [[1]](http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html)[[2]](http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract): February 2009 to January 31, 2012\n- Treatment Arms [[1]](http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html)[[2]](http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract):\n  - PHiD-CV10 vaccine (52 clusters)\n  - Control: hepatitis vaccines (26 clusters)\n- Dosing Schedules [[1]](http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html)[[2]](http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract):\n  - Infants <7 months: 3+1 or 2+1 schedule\n  - Children 7-11 months: 2+1 schedule\n  - Children 12-18 months: 2-dose schedule","efficacy":"- Primary Analysis Population [[1]](http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html)[[2]](http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract): 30,528 participants\n- 3+1 Schedule Effectiveness [[1]](http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html)[[2]](http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract): 100% (95% CI: 83-100%) against vaccine-type IPD\n- 2+1 Schedule Effectiveness [[1]](http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html)[[2]](http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract): 92% (95% CI: 58-100%) against vaccine-type IPD\n- Overall Effectiveness [[1]](http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html)[[2]](http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract): 93% (95% CI: 75-99%) against any culture-confirmed IPD\n- Catch-up Cohort Effectiveness [[1]](http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html)[[2]](http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract): 100% (95% CI: 79-100%) with no cases in vaccinated groups","safety":"- Serious Adverse Events [[1]](http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html)[[2]](http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract): 18 non-fatal serious adverse events suspected to be vaccine-related\n- Overall Safety Profile [[1]](http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html)[[2]](http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract): No safety concerns noted during the study\n- Safety Monitoring [[1]](http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html)[[2]](http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract): Conducted via routine post-immunisation safety surveillance","key_findings":[{"finding":"PHiD-CV10 showed 100% effectiveness (95% CI: 83-100%) in preventing vaccine-type IPD with 3+1 schedule in infants <7 months","timestamp":"11/16/2012"},{"finding":"First clinical trial confirmation of 2+1 schedule effectiveness (92%) against vaccine-type IPD","timestamp":"11/16/2012"},{"finding":"Overall effectiveness of 93% (95% CI: 75-99%) against any culture-confirmed IPD regardless of serotype","timestamp":"11/16/2012"},{"finding":"100% effectiveness (95% CI: 79-100%) in catch-up vaccination cohorts","timestamp":"11/16/2012"},{"finding":"Favorable safety profile with no significant safety concerns identified during the study","timestamp":"11/16/2012"}],"sources":[{"id":1,"link":"http://www.gsk.com/media/press-releases/2012/data-published-in-the-lancet-show-glaxosmithklines-synflorix-is-highly-effective-at-preventing-invasive-pneumococcal-disease.html","title":"Press Release 11/16/2012","published":"2012-11-16"},{"id":2,"link":"http://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2812%2961854-6/abstract","title":"The Lancet 11/16/2012","published":"2012-11-16"}],"label":"positive"}]""",
            "language": 'CN',
            "model": '',
            "enable_rag": False,
        },
        "is_hitl": True
    }
    await chat(body=body)

async def test_mindsearchclinicalguidance(print_chunk: bool = False):
    body = {
        "user_prompt":"请从该临床指南中提取患者诊疗路径",
        "history_messages":[],
        "agent":"mindsearchclinicalguideline",
        "params":{
            "language":"CN",
            "model":"",
            "enable_rag": False,
            "reference":"9ee74054-c77c-4628-8ba0-c7e020f5fba5",
            "reference_type":"clinical-guideline",
            "background":"{\"guideline_id\": \"9ee74054-c77c-4628-8ba0-c7e020f5fba5\", \"source\": \"nccn\", \"publication_date\": \"July 3, 2024\", \"choosen_subtree\": False, \"source_url\": \"https://www.nccn.org/professionals/physician_gls/pdf/all.pdf\", \"doc_url\": \"https://noahai-online.obs.cn-east-3.myhuaweicloud.com/clinical/9ee74054-c77c-4628-8ba0-c7e020f5fba5.pdf\", \"sub_tree\": [{\"id\": \"9ee74054-c77c-4628-8ba0-c7e020f5fba5-2\", \"name\": \"Paget disease of the breast\", \"description\": \"The clinical pathway focuses on managing patients with suspected Paget disease of the breast, using clinical breast exams, diagnostic mammograms, and ultrasounds to detect lesions. If lesions are present, core biopsies and full-thickness skin biopsies of the nipple-areolar complex (NAC) are performed to confirm diagnosis. If both breast and NAC biopsies are negative, clinical follow-up is recommended, along with re-biopsy if healing is incomplete. If positive for Paget, treatment options include central lumpectomy with WBRT, total mastectomy with or without breast reconstruction, or lumpectomy without radiation, guided by DCIS or invasive breast cancer guidelines and systemic adjuvant therapy as advised by the NCCN. Further imaging with breast MRI and additional tissue sampling may be considered in specific scenarios.\", \"raw_text\": null, \"disease\": [\"Paget disease\", \"Ductal Carcinoma In Situ (DCIS)\", \"Invasive Breast Cancer\"], \"keywords\": [\"Paget disease\", \"breast lesion\", \"NAC biopsy\", \"systemic adjuvant therapy\", \"mammogram\", \"ultrasound\", \"core biopsy\", \"full-thickness skin biopsy\", \"NCCN Guidelines\", \"DCIS\", \"breast MRI\", \"lumpectomy\", \"mastectomy\", \"SLNB\", \"WBRT\"]}, {\"id\": \"9ee74054-c77c-4628-8ba0-c7e020f5fba5-3\", \"name\": \"Inflammatory Breast Cancer\", \"description\": \"The clinical pathway outlines the diagnosis and treatment of Inflammatory Breast Cancer (IBC) involving a multidisciplinary approach. Initial assessments include pathology reviews, imaging studies, and genetic and fertility counseling when applicable. Treatment plans may involve surgery (total mastectomy with axillary dissection), radiotherapy, and systemic therapies, including chemotherapy, endocrine therapy, and HER2-targeted therapy. The response to preoperative therapy dictates subsequent treatments, with personalized care plans developed through shared decision-making, considering patient preferences and performance status.\", \"raw_text\": null, \"disease\": [\"Inflammatory Breast Cancer\"], \"keywords\": [\"IBC\", \"pathologic diagnosis\", \"multidisciplinary team\", \"medical photography\", \"CBC\", \"Comprehensive metabolic panel\", \"LFTs\", \"alkaline phosphatase\", \"Pathology review\", \"tumor ER/PR status\", \"HER2 status\", \"Fertility counseling\", \"Genetic counseling\", \"diagnostic mammogram\", \"ultrasound\", \"Chest CT\", \"Abdomen CT\", \"pelvis diagnostic CT\", \"MRI\", \"Bone scan\", \"FDG-PET/CT\", \"Breast MRI\", \"Preoperative/Adjuvant Therapy Regimens\", \"mastectomy\", \"axillary dissection\", \"radiotherapy\", \"chemotherapy\", \"endocrine treatment\", \"HER2-targeted therapy\", \"shared decision-making\"]}, {\"id\": \"9ee74054-c77c-4628-8ba0-c7e020f5fba5-4\", \"name\": \"Invasive Breast Cancer\", \"description\": \"The clinical pathway discusses the management of invasive breast cancer, specifically invasive, non-inflammatory, and non-metastatic (M0) types. The recommended workup includes a history and physical exam, diagnostic imaging (mammogram, ultrasound, and optional MRI), and pathology review to determine tumor receptor status (ER/PR and HER2). Genetic counseling is advised for patients at risk. Fertility and pregnancy considerations are to be addressed. Treatment strategies include surgery (breast-conserving or mastectomy), potentially followed by radiation therapy. Systemic therapies (endocrine therapy, chemotherapy, trastuzumab, pertuzumab, and olaparib) are recommended based on the receptor status and nodal involvement. Comprehensive management considers patient age, tumor size, node involvement, and additional individual risk factors.\", \"raw_text\": null, \"disease\": [\"Invasive breast cancer\"], \"keywords\": [\"invasive breast cancer\", \"non-inflammatory\", \"non-metastatic\", \"workup\", \"imaging\", \"diagnostic mammogram\", \"ultrasound\", \"breast MRI\", \"pathology review\", \"tumor receptor status\", \"genetic counseling\", \"HER2\", \"ER/PR\", \"triple-negative breast cancer\", \"fertility concerns\", \"pregnancy\", \"distress assessment\", \"additional imaging\", \"locoregional treatment\", \"breast-conserving surgery\", \"mastectomy\", \"radiotherapy\", \"systemic therapy\", \"axillary staging\", \"adjuvant therapy\", \"endocrine therapy\", \"chemotherapy\", \"olaparib\", \"trastuzumab\", \"pertuzumab\"]}, {\"id\": \"9ee74054-c77c-4628-8ba0-c7e020f5fba5-5\", \"name\": \"Ductal Carcinoma In Situ\", \"description\": \"This clinical pathway addresses the treatment and management of Ductal Carcinoma In Situ (DCIS) and Solid Papillary Carcinoma (SPC). Key recommendations include conducting diagnostic mammography, evaluating estrogen receptor status, and offering genetic counseling. Treatment options involve breast-conserving surgery with or without radiation therapy, and mastectomy with sentinel lymph node biopsy. Post-surgical management includes considering endocrine therapy, such as tamoxifen or aromatase inhibitors, particularly in ER-positive DCIS cases. Risk reduction strategies for both the ipsilateral and contralateral breasts are discussed, emphasizing interval surveillance through history and physical exams, and regular mammograms.\", \"raw_text\": null, \"disease\": [\"Ductal Carcinoma In Situ (DCIS)\", \"Solid Papillary Carcinoma (SPC)\"], \"keywords\": [\"DCIS\", \"solid papillary carcinoma\", \"estrogen receptor\", \"breast-conserving surgery\", \"radiation therapy\", \"endocrine therapy\", \"tamoxifen\", \"aromatase inhibitor\", \"risk reduction\", \"mastectomy\"]}, {\"id\": \"9ee74054-c77c-4628-8ba0-c7e020f5fba5-1\", \"name\": \"Metastatic (M1) Invasive Breast Cancer\", \"description\": \"The clinical pathway focuses on the management of Stage IV or recurrent metastatic breast cancer. It includes comprehensive diagnostic workup recommendations, such as imaging (CT, MRI, PET/CT, bone scan) and biomarker assessments (ER/PR, HER2 status, genomic profiling). Treatment strategies emphasize systemic therapy tailored to hormonal receptor status and disease progression, including endocrine therapy and targeted therapy. Supportive care and palliative options are discussed, with treatment goals established through shared decision-making. Management is individualized based on patient performance status, disease progression, and previous treatments, with ongoing reassessment of therapeutic value and adjustment for rebound from toxicity or progression.\", \"raw_text\": null, \"disease\": [\"Metastatic Breast Cancer\", \"Recurrent Breast Cancer\"], \"keywords\": [\"Stage IV\", \"metastatic\", \"recurrent\", \"imaging\", \"systemic therapy\", \"endocrine therapy\", \"HER2\", \"ER/PR\", \"HER2 status\", \"biopsy\", \"bone scan\", \"visceral crisis\", \"shared decision-making\", \"palliative care\"]}]}"
        }
    }
    await chat(body=body, print_chunk=print_chunk) 

async def test_mindsearchclinicalguidance_choose_subtree(print_chunk: bool = False):
    body = {
  "user_prompt": "请从该临床指南中提取患者诊疗路径",
  "history_messages": [],
  "agent": "mindsearchclinicalguideline",
  "params": {
    "language": "CN",
    "model": "",
    "enable_rag": False,
    "reference": "9ee74054-c77c-4628-8ba0-c7e020f5fba5",
    "reference_type": "clinical-guideline",
    "background": "{\"guideline_id\": \"9ee74054-c77c-4628-8ba0-c7e020f5fba5\", \"source\": \"nccn\", \"publication_date\": \"July 3, 2024\", \"choosen_subtree\": True, \"source_url\": \"https://www.nccn.org/professionals/physician_gls/pdf/all.pdf\", \"doc_url\": \"https://noahai-online.obs.cn-east-3.myhuaweicloud.com/clinical/9ee74054-c77c-4628-8ba0-c7e020f5fba5.pdf\", \"sub_tree\": [{\"id\": \"9ee74054-c77c-4628-8ba0-c7e020f5fba5-2\", \"name\": \"Paget disease of the breast\", \"description\": \"The clinical pathway focuses on managing patients with suspected Paget disease of the breast, using clinical breast exams, diagnostic mammograms, and ultrasounds to detect lesions. If lesions are present, core biopsies and full-thickness skin biopsies of the nipple-areolar complex (NAC) are performed to confirm diagnosis. If both breast and NAC biopsies are negative, clinical follow-up is recommended, along with re-biopsy if healing is incomplete. If positive for Paget, treatment options include central lumpectomy with WBRT, total mastectomy with or without breast reconstruction, or lumpectomy without radiation, guided by DCIS or invasive breast cancer guidelines and systemic adjuvant therapy as advised by the NCCN. Further imaging with breast MRI and additional tissue sampling may be considered in specific scenarios.\", \"raw_text\": \"{\\\"tree\\\": {\\\"1\\\": {\\\"id\\\": \\\"1\\\", \\\"text\\\": \\\"Clinical suspicion of Paget disease\\\", \\\"page_num\\\": 99, \\\"children\\\": [\\\"2\\\"]}, \\\"2\\\": {\\\"id\\\": \\\"2\\\", \\\"text\\\": \\\"Clinical breast exam, Diagnostic bilateral mammogram, ultrasound as necessary\\\", \\\"children\\\": [\\\"3\\\", \\\"5\\\"]}, \\\"3\\\": {\\\"id\\\": \\\"3\\\", \\\"text\\\": \\\"Examination or imaging positive for breast lesion\\\", \\\"children\\\": [\\\"4\\\", \\\"6\\\"]}, \\\"4\\\": {\\\"id\\\": \\\"4\\\", \\\"text\\\": \\\"PAGET-2\\\"}, \\\"5\\\": {\\\"id\\\": \\\"5\\\", \\\"text\\\": \\\"Examination and imaging negative for breast lesion\\\", \\\"children\\\": [\\\"4\\\", \\\"3\\\", \\\"17\\\", \\\"5\\\"]}, \\\"6\\\": {\\\"id\\\": \\\"6\\\", \\\"text\\\": \\\"Core biopsy of breast lesion and full-thickness skin biopsy of involved NAC\\\", \\\"children\\\": [\\\"7\\\", \\\"10\\\", \\\"12\\\", \\\"14\\\"]}, \\\"7\\\": {\\\"id\\\": \\\"7\\\", \\\"text\\\": \\\"Breast and NAC biopsy negative\\\", \\\"children\\\": [\\\"8\\\"]}, \\\"8\\\": {\\\"id\\\": \\\"8\\\", \\\"text\\\": \\\"Clinical follow-up Re-biopsy if not healing\\\", \\\"children\\\": [\\\"9\\\"]}, \\\"9\\\": {\\\"id\\\": \\\"9\\\", \\\"text\\\": \\\"Appropriate systemic adjuvant therapy as clinically indicated, See NCCN Guidelines for DCIS or Invasive Breast Cancer\\\"}, \\\"10\\\": {\\\"id\\\": \\\"10\\\", \\\"text\\\": \\\"Breast DCIS and NAC Paget\\\", \\\"children\\\": [\\\"11\\\"]}, \\\"11\\\": {\\\"id\\\": \\\"11\\\", \\\"text\\\": \\\"See NCCN Guidelines for Noninvasive Breast Cancer for DCIS (DCIS-1)\\\", \\\"children\\\": [\\\"9\\\"]}, \\\"12\\\": {\\\"id\\\": \\\"12\\\", \\\"text\\\": \\\"Breast invasive cancer and NAC Paget\\\", \\\"children\\\": [\\\"13\\\"]}, \\\"13\\\": {\\\"id\\\": \\\"13\\\", \\\"text\\\": \\\"See NCCN Guidelines for Invasive Breast Cancer (BINV-1)\\\", \\\"children\\\": [\\\"9\\\"]}, \\\"14\\\": {\\\"id\\\": \\\"14\\\", \\\"text\\\": \\\"Breast negative for cancer and positive NAC Paget\\\", \\\"children\\\": [\\\"15\\\"]}, \\\"15\\\": {\\\"id\\\": \\\"15\\\", \\\"text\\\": \\\"Consider breast MRI and tissue sampling\\\", \\\"attributes\\\": [\\\"BINV-B\\\"], \\\"children\\\": [\\\"16\\\"]}, \\\"16\\\": {\\\"id\\\": \\\"16\\\", \\\"text\\\": \\\"Central lumpectomy including NAC with WBRT or Total mastectomy \\\\u00b1 SLNB with or without breast reconstruction or Central lumpectomy including NAC \\\\u00b1 SLNB without RT (category 2B)\\\", \\\"attributes\\\": [\\\"Discussion\\\"], \\\"children\\\": [\\\"9\\\"]}, \\\"17\\\": {\\\"id\\\": \\\"17\\\", \\\"text\\\": \\\"Full-thickness skin biopsy of involved NAC\\\", \\\"children\\\": [\\\"18\\\", \\\"19\\\"]}, \\\"18\\\": {\\\"id\\\": \\\"18\\\", \\\"text\\\": \\\"NAC biopsy positive for Paget\\\", \\\"children\\\": [\\\"15\\\"]}, \\\"19\\\": {\\\"id\\\": \\\"19\\\", \\\"text\\\": \\\"NAC biopsy negative for Paget\\\", \\\"children\\\": [\\\"8\\\"]}}, \\\"attributes\\\": {\\\"BINV-B\\\": {\\\"header\\\": \\\"Principles of Dedicated Breast MRI Testing\\\", \\\"content\\\": \\\"## PRINCIPLES OF DEDICATED BREAST MRI TESTING\\\\n\\\\nSee NCCN Guidelines for Breast Cancer Screening and Diagnosis for indications for screening MRI in patients at increased breast cancer risk.\\\\n\\\\n### Personnel, Facility, and Equipment\\\\n\\\\n- Breast MRI examinations are performed with IV contrast and should be performed and interpreted by an expert breast imaging team working in concert with the multidisciplinary treatment team.\\\\n- Breast MRI examinations require a dedicated breast coil and breast imaging radiologists familiar with optimal timing sequences and other technical details for image interpretation. The imaging center should have the ability to perform MRI-guided needle sampling and/or image-guided localization of MRI-detected findings.\\\\n\\\\n### Clinical Indications and Applications\\\\n\\\\n- May be used for staging evaluation to define extent of cancer or presence of multifocal or multicentric cancer in the ipsilateral breast, or as screening of the contralateral breast cancer at time of initial diagnosis (category 2B). There are no high-level data to demonstrate that the use of MRI to facilitate local therapy decision-making improves local recurrence or survival.\\\\n- May be helpful for breast cancer evaluation before and after preoperative systemic therapy to define extent of disease, response to treatment, and potential for breast-conservation therapy.\\\\n- May be useful in identifying otherwise clinically occult disease in patients presenting with axillary nodal metastases (cT0, cN+), with Paget disease, or with invasive lobular carcinoma poorly (or inadequately) defined on mammography, ultrasound, or physical examination.\\\\n- False-positive findings on breast MRI are common. Surgical decisions should not be based solely on the MRI findings. Additional tissue sampling of areas of concern identified by breast MRI is recommended.\\\\n- The utility of MRI in follow-up screening of most patients with prior breast cancer is undefined and annual MRI is recommended in patients with personal history of breast cancer who:\\\\n  1. were diagnosed at age \\\\u2264 50 or\\\\n  2. have dense breasts\\\\n\\\\n---\\\\n\\\\n**Note:** All recommendations are category 2A unless otherwise indicated.\\\", \\\"summary\\\": \\\"Details the principles and clinical applications of dedicated breast MRI testing in breast cancer management.\\\", \\\"content_index\\\": \\\"BINV-B\\\", \\\"page_num\\\": 41}}}\", \"disease\": [\"Paget disease\", \"Ductal Carcinoma In Situ (DCIS)\", \"Invasive Breast Cancer\"], \"keywords\": [\"Paget disease\", \"breast lesion\", \"NAC biopsy\", \"systemic adjuvant therapy\", \"mammogram\", \"ultrasound\", \"core biopsy\", \"full-thickness skin biopsy\", \"NCCN Guidelines\", \"DCIS\", \"breast MRI\", \"lumpectomy\", \"mastectomy\", \"SLNB\", \"WBRT\"]}, {\"id\": \"9ee74054-c77c-4628-8ba0-c7e020f5fba5-3\", \"name\": \"Inflammatory Breast Cancer\", \"description\": \"The clinical pathway outlines the diagnosis and treatment of Inflammatory Breast Cancer (IBC) involving a multidisciplinary approach. Initial assessments include pathology reviews, imaging studies, and genetic and fertility counseling when applicable. Treatment plans may involve surgery (total mastectomy with axillary dissection), radiotherapy, and systemic therapies, including chemotherapy, endocrine therapy, and HER2-targeted therapy. The response to preoperative therapy dictates subsequent treatments, with personalized care plans developed through shared decision-making, considering patient preferences and performance status.\", \"raw_text\": null, \"disease\": [\"Inflammatory Breast Cancer\"], \"keywords\": [\"IBC\", \"pathologic diagnosis\", \"multidisciplinary team\", \"medical photography\", \"CBC\", \"Comprehensive metabolic panel\", \"LFTs\", \"alkaline phosphatase\", \"Pathology review\", \"tumor ER/PR status\", \"HER2 status\", \"Fertility counseling\", \"Genetic counseling\", \"diagnostic mammogram\", \"ultrasound\", \"Chest CT\", \"Abdomen CT\", \"pelvis diagnostic CT\", \"MRI\", \"Bone scan\", \"FDG-PET/CT\", \"Breast MRI\", \"Preoperative/Adjuvant Therapy Regimens\", \"mastectomy\", \"axillary dissection\", \"radiotherapy\", \"chemotherapy\", \"endocrine treatment\", \"HER2-targeted therapy\", \"shared decision-making\"]}, {\"id\": \"9ee74054-c77c-4628-8ba0-c7e020f5fba5-4\", \"name\": \"Invasive Breast Cancer\", \"description\": \"The clinical pathway discusses the management of invasive breast cancer, specifically invasive, non-inflammatory, and non-metastatic (M0) types. The recommended workup includes a history and physical exam, diagnostic imaging (mammogram, ultrasound, and optional MRI), and pathology review to determine tumor receptor status (ER/PR and HER2). Genetic counseling is advised for patients at risk. Fertility and pregnancy considerations are to be addressed. Treatment strategies include surgery (breast-conserving or mastectomy), potentially followed by radiation therapy. Systemic therapies (endocrine therapy, chemotherapy, trastuzumab, pertuzumab, and olaparib) are recommended based on the receptor status and nodal involvement. Comprehensive management considers patient age, tumor size, node involvement, and additional individual risk factors.\", \"raw_text\": null, \"disease\": [\"Invasive breast cancer\"], \"keywords\": [\"invasive breast cancer\", \"non-inflammatory\", \"non-metastatic\", \"workup\", \"imaging\", \"diagnostic mammogram\", \"ultrasound\", \"breast MRI\", \"pathology review\", \"tumor receptor status\", \"genetic counseling\", \"HER2\", \"ER/PR\", \"triple-negative breast cancer\", \"fertility concerns\", \"pregnancy\", \"distress assessment\", \"additional imaging\", \"locoregional treatment\", \"breast-conserving surgery\", \"mastectomy\", \"radiotherapy\", \"systemic therapy\", \"axillary staging\", \"adjuvant therapy\", \"endocrine therapy\", \"chemotherapy\", \"olaparib\", \"trastuzumab\", \"pertuzumab\"]}, {\"id\": \"9ee74054-c77c-4628-8ba0-c7e020f5fba5-5\", \"name\": \"Ductal Carcinoma In Situ\", \"description\": \"This clinical pathway addresses the treatment and management of Ductal Carcinoma In Situ (DCIS) and Solid Papillary Carcinoma (SPC). Key recommendations include conducting diagnostic mammography, evaluating estrogen receptor status, and offering genetic counseling. Treatment options involve breast-conserving surgery with or without radiation therapy, and mastectomy with sentinel lymph node biopsy. Post-surgical management includes considering endocrine therapy, such as tamoxifen or aromatase inhibitors, particularly in ER-positive DCIS cases. Risk reduction strategies for both the ipsilateral and contralateral breasts are discussed, emphasizing interval surveillance through history and physical exams, and regular mammograms.\", \"raw_text\": null, \"disease\": [\"Ductal Carcinoma In Situ (DCIS)\", \"Solid Papillary Carcinoma (SPC)\"], \"keywords\": [\"DCIS\", \"solid papillary carcinoma\", \"estrogen receptor\", \"breast-conserving surgery\", \"radiation therapy\", \"endocrine therapy\", \"tamoxifen\", \"aromatase inhibitor\", \"risk reduction\", \"mastectomy\"]}, {\"id\": \"9ee74054-c77c-4628-8ba0-c7e020f5fba5-1\", \"name\": \"Metastatic (M1) Invasive Breast Cancer\", \"description\": \"The clinical pathway focuses on the management of Stage IV or recurrent metastatic breast cancer. It includes comprehensive diagnostic workup recommendations, such as imaging (CT, MRI, PET/CT, bone scan) and biomarker assessments (ER/PR, HER2 status, genomic profiling). Treatment strategies emphasize systemic therapy tailored to hormonal receptor status and disease progression, including endocrine therapy and targeted therapy. Supportive care and palliative options are discussed, with treatment goals established through shared decision-making. Management is individualized based on patient performance status, disease progression, and previous treatments, with ongoing reassessment of therapeutic value and adjustment for rebound from toxicity or progression.\", \"raw_text\": null, \"disease\": [\"Metastatic Breast Cancer\", \"Recurrent Breast Cancer\"], \"keywords\": [\"Stage IV\", \"metastatic\", \"recurrent\", \"imaging\", \"systemic therapy\", \"endocrine therapy\", \"HER2\", \"ER/PR\", \"HER2 status\", \"biopsy\", \"bone scan\", \"visceral crisis\", \"shared decision-making\", \"palliative care\"]}]}"
  }
}
    await chat(body=body, print_chunk=print_chunk) 

async def test_mindsearchpubmed(print_chunk: bool = False):
    body = {
        #"user_prompt": "In the PubMed database, please retrieve the unique article that meets the following conditions:\n- Research topic: “Deep learning-based identification of patients at increased risk of cancer using routine laboratory markers”\n- Journal: “Scientific Reports”\n- Publication date: “2025 Apr 12”\n\nPlease provide the PMID and source URL for this article.",
        "user_prompt": "最近3个月AML领域有什么值得读的文章吗？",
        "agent": "mindsearchpubmed",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearchpubmed_withhistory(print_chunk: bool = False):
    body = {
        "user_prompt": "用表格的形式总结上述结果",
        "agent": "mindsearchpubmed",
        "history_messages": [
            {
                "role": "user",
                "content": "请帮我搜索一下AML治疗的新靶点都有哪些？",
            },
            {
                "role": "assistant",
                "content": """非常感谢您的慷慨提示!我会尽最大努力为您提供一个全面而详细的回答。以下是关于急性髓系白血病(AML)新靶点的分析:

# 1. AML概述

急性髓系白血病(AML)是一种恶性血液系统疾病,主要特征是骨髓中异常髓系祖细胞的快速增殖和分化障碍。

## 1.1 流行病学

- AML是成人中最常见的急性白血病类型 [3](https://pubmed.ncbi.nlm.nih.gov/39798496/)
- 65岁及以上患者预后最差,1年生存率仅为30% [3](https://pubmed.ncbi.nlm.nih.gov/39798496/)

## 1.2 临床表现

- 贫血
- 出血倾向
- 反复感染
- 骨痛
- 肝脾肿大

## 1.3 诊断

- 外周血和骨髓涂片检查
- 流式细胞术
- 细胞遗传学分析
- 分子生物学检测(如FLT3、NPM1、CEBPA等基因突变)

## 1.4 预后分层

| 风险分组 | 遗传学特征 |
|---------|-----------|
| 良好     | t(8;21), inv(16), t(16;16), NPM1突变(无FLT3-ITD) |
| 中等     | 正常核型,+8,t(9;11) |
| 不良     | 复杂核型,单体型,-5/del(5q),-7,11q23异常 |

# 2. AML治疗的新靶点

## 2.1 表观遗传调控相关靶点

### 2.1.1 Menin-MLL1相互作用

- 靶点:Menin蛋白
- 作用机制:Menin是MLL融合蛋白恶性潜能所必需的,抑制Menin-MLL1相互作用可能是治疗AML的新策略 [2](https://pubmed.ncbi.nlm.nih.gov/39843145/)
- 潜在药物:
  - M-525
  - M-808
  - MI-89
- 研究进展:通过高通量筛选发现了上述潜在抑制剂,分子动力学分析和MM-PBSA计算验证了其稳定性和结合机制 [2](https://pubmed.ncbi.nlm.nih.gov/39843145/)

### 2.1.2 HMGCS1

- 靶点:3-羟基-3-甲基戊二酰辅酶A合成酶1(HMGCS1)
- 作用机制:HMGCS1在耐药患者中高表达,与总生存期呈负相关 [7](https://pubmed.ncbi.nlm.nih.gov/38994525/)
- 研究进展:
  - 敲除HMGCS1可减弱AML细胞增殖并增加化疗敏感性
  - HMGCS1通过MAPK通路促进AML耐药
  - Hymeglusin(HMGCS1特异性抑制剂)可降低AML细胞系和原代AML患者骨髓细胞的生长 [7](https://pubmed.ncbi.nlm.nih.gov/38994525/)

## 2.2 信号通路相关靶点

### 2.2.1 FLT3-ITD

- 靶点:FLT3内部串联重复(ITD)突变
- 作用机制:FLT3-ITD是AML中最常见的基因改变,约30%的AML携带此突变 [17](https://pubmed.ncbi.nlm.nih.gov/37391442/)
- 潜在药物:FLT3抑制剂
- 研究进展:
  - FLT3-ITD激活的氧化应激信号通路在耐药中发挥关键作用
  - STAT5、PI3K/AKT和RAS/MAPK是主要的氧化应激信号通路
  - NADPH氧化酶(NOX)介导的ROS产生可能是新的治疗靶点 [17](https://pubmed.ncbi.nlm.nih.gov/37391442/)

### 2.2.2 NOTCH4

- 靶点:NOTCH4受体
- 作用机制:NOTCH4抑制可增强FLT3-ITD AML细胞对FLT3抑制剂的敏感性 [9](https://pubmed.ncbi.nlm.nih.gov/38811818/)
- 研究进展:
  - NOTCH4在FLT3-ITD AML细胞系和原代患者样本中高表达
  - 通过shRNA敲低、CRISPR-Cas9敲除或γ-分泌酶抑制剂抑制NOTCH4可与FLT3抑制剂协同杀伤FLT3-ITD AML细胞
  - NOTCH4抑制可降低磷酸化ERK和AKT水平,影响细胞周期、DNA修复和转录相关基因表达 [9](https://pubmed.ncbi.nlm.nih.gov/38811818/)

## 2.3 免疫相关靶点

### 2.3.1 嗅觉受体(ORs)

- 靶点:特定的嗅觉受体
- 作用机制:某些ORs在AML中异位表达,可能具有诊断和治疗潜力 [18](https://pubmed.ncbi.nlm.nih.gov/37370684/)
- 研究进展:
  - 鉴定出19个在AML中具有独特表达模式的ORs
  - 建立了具有AML预后潜力的OR签名
  - 发现了与这些ORs共表达的癌症相关基因 [18](https://pubmed.ncbi.nlm.nih.gov/37370684/)

### 2.3.2 CAR-T细胞靶点

- 潜在靶点:
  - CD33
  - CD123
  - CLL-1
  - FLT3
  - CD44v6
- 研究进展:
  - 开发双靶点CAR和逻辑电路以提高特异性和降低副作用
  - 基因编辑技术用于修饰肿瘤细胞或正常细胞以产生治疗效果
  - 多药联合策略用于解决CAR-T治疗面临的一些障碍和挑战 [15](https://pubmed.ncbi.nlm.nih.gov/37870695/)

## 2.4 其他新靶点

### 2.4.1 TRPML1

- 靶点:溶酶体阳离子通道TRPML1
- 作用机制:TRPML1抑制可通过抑制自噬增强AML细胞对化疗药物的敏感性 [8](https://pubmed.ncbi.nlm.nih.gov/38951379/)
- 研究进展:
  - TRPML1在AML细胞中高表达
  - 抑制TRPML1可损害自噬,同时增加活性氧(ROS)和ROS介导的脂质过氧化(Lipid-ROS)产生
  - 在人类白血病小鼠模型中,敲低TRPML1显著减少了化疗后OCI-AML3肿瘤生长 [8](https://pubmed.ncbi.nlm.nih.gov/38951379/)

### 2.4.2 HOX基因

- 靶点:HOXB3和HOXB7
- 作用机制:这些基因在正常-MDS-AML转化过程中逐渐上调 [13](https://pubmed.ncbi.nlm.nih.gov/38254070/)
- 研究进展:
  - 在间充质干细胞(MSCs)中阻断HOXB3和HOXB7可增强细胞增殖和分化,抑制细胞凋亡
  - 恢复MSCs支持造血干细胞(HSCs)分化的功能 [13](https://pubmed.ncbi.nlm.nih.gov/38254070/)

# 3. 总结

AML治疗的新靶点研究主要集中在以下几个方面:

1. 表观遗传调控:如Menin-MLL1相互作用和HMGCS1
2. 信号通路:如FLT3-ITD和NOTCH4
3. 免疫相关:如特定嗅觉受体和CAR-T细胞靶点
4. 其他新靶点:如溶酶体通道TRPML1和HOX基因

这些新靶点的发现为AML的精准治疗提供了新的方向,有望改善患者预后。然而,大多数研究仍处于临床前或早期临床阶段,需要进一步的验证和优化。未来,结合多组学数据和人工智能技术,可能会发现更多潜在的治疗靶点,为AML患者带来更好的治疗选择。"""
            }
        ],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearchfinance(print_chunk: bool = False):
    body = {
        #"user_prompt": "Summit Therapeutics 公司近期股价波动的原因，请帮我再检查一下他的财报是否健康",
        #"user_prompt": "迈瑞医疗 财报分析",
        "user_prompt": "I-Mab 最近财报分析",
        "agent": "mindsearchfinance",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearchfinance_with_coder(print_chunk: bool = False):
    """测试带有代码计算能力的金融搜索智能体"""
    
    print("\n" + "="*80)
    print("🔍 开始测试带有代码计算能力的金融搜索智能体")
    print("="*80)
    print("📝 测试问题: 计算苹果公司过去5年的年化收益率，并分析其投资价值")
    print("🎯 预期行为: 应该触发意图识别 → 执行代码计算 → 生成包含计算结果的最终分析")
    print("="*80)
    
    body = {
        # 测试需要复杂计算的问题
        "user_prompt": "计算苹果公司过去5年的年化收益率，并分析其投资价值，注意，不要用Calculate工具",
        "agent": "mindsearchfinance",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    
    # 添加调试信息
    print("🚀 调用 chat 函数...")
    print("📋 请求参数:")
    print(f"   - Agent: {body['agent']}")
    print(f"   - User Prompt: {body['user_prompt']}")
    print(f"   - Enable RAG: {body['params']['enable_rag']}")
    print("="*80)
    
    response_count = 0
    computation_detected = False
    computation_result_found = False
    
    try:
        # 直接调用 agent 进行测试，而不是通过 chat 函数
        from agent.explore.mindsearch_hitl_agent import MindSearchFinanceHitlAgent
        
        print("🔧 创建 MindSearchFinanceHitlAgent 实例...")
        agent = MindSearchFinanceHitlAgent()
        
        print(f"📊 Agent 类型: {type(agent)}")
        print(f"📊 Final Output Agent 类型: {type(agent.final_output_agent)}")
        
        # 检查是否使用了新的 output agent
        if hasattr(agent.final_output_agent, 'coder_agent'):
            print("✅ 检测到使用了 MindSearchWithCoderFinalOutputAgent")
            print("✅ 支持代码计算功能")
        else:
            print("❌ 未检测到代码计算功能")
            return
        
        print("\n" + "="*80)
        print("🔄 开始执行 agent.use_tool...")
        print("="*80)
        
        async for chunk in agent.use_tool(
            user_prompt=body["user_prompt"],
            history_messages=body["history_messages"],
            **body["params"]
        ):
            response_count += 1
            
            if print_chunk:
                print(f"\n📦 响应 #{response_count}:")
                print(f"   类型: {type(chunk)}")
                print(f"   内容: {chunk}")
                # if hasattr(chunk, 'content') and chunk.content:
                #     # print(f"   内容: {str(chunk.content)[:1000]}...")
                    
                #     # 检查是否包含计算相关内容
                #     if "计算" in chunk.content or "收益率" in chunk.content:
                #         computation_detected = True
                #         print("   🧮 检测到计算相关内容")
                    
                #     if "复杂计算结果" in chunk.content:
                #         computation_result_found = True
                #         print("   ✅ 检测到复杂计算结果")
                        
                # elif isinstance(chunk, dict):
                    
                    
                #     # 检查是否是工具调用结果
                #     if 'function' in chunk:
                #         print(f"   🔧 工具调用: {chunk['function']}")
                        
                #         if chunk['function'] == 'CodeGeneration':
                #             print("   💻 检测到代码生成")
                #             computation_detected = True
                #         elif chunk['function'] == 'CodeExecution':
                #             print("   ▶️ 检测到代码执行")
                #             computation_detected = True
                #     print(f"   字典内容: {chunk}")
                # else:
                #     print(f"   其他类型: {chunk}")
        
        print("\n" + "="*80)
        print("📊 测试结果总结:")
        print(f"   总响应数: {response_count}")
        # print(f"   检测到计算内容: {'✅' if computation_detected else '❌'}")
        # print(f"   检测到计算结果: {'✅' if computation_result_found else '❌'}")
        
        # if computation_detected and computation_result_found:
        #     print("🎉 测试成功！代码计算功能正常工作")
        # elif computation_detected:
        #     print("⚠️ 部分成功：检测到计算但未找到结果")
        # else:
        #     print("❌ 测试失败：未检测到代码计算功能")
            
        print("="*80)
        
    except Exception as e:
        print(f"❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
    
    # 同时运行原始的 chat 函数作为对比
    print("\n" + "="*80)
    print("🔄 运行原始 chat 函数作为对比...")
    print("="*80)
    # await chat(body=body, print_chunk=print_chunk)
    

async def test_mindsearchfinance_coder_simple_query(print_chunk: bool = False):
    """测试带有代码计算能力的金融搜索智能体 - 简单查询"""
    body = {
        # 测试不需要复杂计算的简单查询
        "user_prompt": "苹果公司的主要业务是什么？",
        "agent": "mindsearchfinance",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearchfinance_coder_technical_analysis(print_chunk: bool = False):
    """测试带有代码计算能力的金融搜索智能体 - 技术分析"""
    body = {
        # 测试技术分析类问题
        "user_prompt": "分析特斯拉公司的ROE、ROA和资产负债率，并生成可视化图表",
        "agent": "mindsearchfinance",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearchfinance_coder_portfolio_optimization(print_chunk: bool = False):
    """测试带有代码计算能力的金融搜索智能体 - 投资组合优化"""
    body = {
        # 测试投资组合优化问题
        "user_prompt": "基于苹果、微软、谷歌的股价数据，计算最优投资组合权重",
        "agent": "mindsearchfinance",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearchrewrite(print_chunk: bool = False):
    body = {
        "user_prompt": """目前香紫苏醇在微生物合成中的进展，并给出难点和接下来的可行改造方向 """,
        #"user_prompt": "患者NGS检测，TNS1:exon22-ALK：exon12融合，请仅参照这个融合点位给出治疗方案：哪个ALK抑制剂更为合适，有效",
        "agent": "mindsearchrewrite",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)


async def test_mindsearchrewrite_feedback(print_chunk: bool = False):
    body = {
        "user_prompt": "目前香紫苏醇在微生物合成中的进展，并给出难点和接下来的可行改造方向",
        #"user_prompt": "患者NGS检测，TNS1:exon22-ALK：exon12融合，请仅参照这个融合点位给出治疗方案：哪个ALK抑制剂更为合适，有效",
        "agent": "mindsearchrewrite",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
            "rewrites": [
                #"""为确保后续报告精准聚焦，请补充或确认以下信息：1. "香紫苏醇"的具体化学身份：请给出英文名或 CAS 号，以免混淆（如 perillyl alcohol、carvacrol 等）。 2. 进展回顾的时间范围：例如 2015-2025 年，或“最新 3 年”? 3. 微生物底盘范围：是否仅限常用工程菌株（大肠杆菌、酿酒酵母等），还是也纳入放线菌、植物内生菌等？ 4. 关注的生产规模/指标：实验室合成（mg-g/L）还是放大/工业水平（>100 g/L）；是否需要经济性评估？5. 期望的输出格式与深度：综述+难点诊断+未来改造策略即可，还是还需专利/竞争公司分析、路线可行性成本估算等？请一次性回复序号+内容，以便我据此改写为精确的研究任务。""",
                #"""请提供以下信息：1. 患者的肿瘤类型及临床分期（如NSCLC分期）、组织学亚型等；2. 患者既往接受过的治疗（包括化疗、靶向治疗及免疫治疗等）及疗效；3. 是否存在脑转移或其他重要部位转移；若您不熟悉相关细节，可简要说明或由分析者自行假设常见临床情景。""",
                """为便于产出可执行的研究任务，请先帮我确认以下关键点（可按编号回复，未知可写“跳过/由你决定”）：
1) 目标化合物确认：“香紫苏醇”具体指哪一分子？是紫苏醇/过氧？您更可能指的是：
   - 甲基环己烯型单萜“过氧柠檬烯醇/Perillyl alcohol (POH)”；
   - 还是“紫苏醛/Perillaldehyde (PA)”；
   - 或其他（请给中文名/英文名/CAS号）？并且是否指定构型/对映体（如(R)/(S)）？
2) 合成路线偏好：希望综述“葡萄糖等碳源de novo合成（MVA/MEP途径）”还是“以柠檬烯/蒎烯等为底物的生物转化（whole-cell/酶法）”，或两者都要？
3) 宿主范围：重点关注哪些工程底盘？（大肠杆菌 Escherichia coli、酿酒酵母 Saccharomyces cerevisiae、油脂酵母 Yarrowia lipolytica、芽孢杆菌/假单胞菌等；是否要求GRAS/食品级？）
4) 评价指标与边界：更关注哪些指标？（滴度 g/L、产率 g/g-糖、生产强度 g/L/h、对映体纯度、分泌/萃取方式、放大到发酵>10 L的案例、专利/产业化进展等）
5) 时间范围与产出形式：“目前”指过去多长时间？（近2年/5年/10年）以及需要的输出形式？（默认博客式研究综述；或技术路线建议书/路演PPT/对比表）""",
            ],
            "feedbacks": [
                #"""Sclareolide, 最近3年，全部内容""",
                #"""对患者的其他状况不参考，只关注这个融合点位""",
                """skip""",
            ]
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def test_mindsearchcatalystevent(print_chunk: bool = False):
    body = {
        #"user_prompt": "请提供肥胖/体重管理药物作用机制的权威医学信息，包括GLP-1、GLP-1+GIP、GLP-1+胰高糖素、MC4R激动剂、Amylin类似物、FGF21、β3-受体激动剂、胰高糖素受体激动剂及代谢手术替代疗法的机制解析和最新研究进展。",
        # "user_prompt": """catalyst type包括PDUFA Approval、Top-Line Results、Trial Data Update；indication包括central nervous system、neurological disorders、neurodegenerative diseases；data range为2024年7月至2025年12月；drug name包括siRNA、RNA interference相关疗法, 包括1期、2期""",
        # "user_prompt": "1+1-2等于几",
        "user_prompt": "帮我计算小米公司过去3年的年化收益率，并分析其投资价值",
        # "user_prompt": "帮我计算斐波那契数列的第十项",
        "agent": "mindsearchfinance",
        # "agent": "simplecoder",
        "history_messages": [],
        "params": {
            "background": '',
            "language": 'CN',
            "model": '',
            "enable_rag": True,
        }
    }
    await chat(body=body, print_chunk=print_chunk)


async def test_mindsearch_pubmed(print_chunk: bool = False):
    body = {
        "user_prompt": "以 二十年坚守与演进：国产流感疫苗在中国免疫防控体系中的价值回顾与展望 为题目，写一段论文，2000字就够了",
        "agent": "mindsearchpubmed",
        "history_messages": [],
        "params": {
            "background": '',
        },
        "priority_pubmed_ids": ["23896581", "32732142", "33434084", "40821798", "39205645", "40966619"],
    }
    await chat(body=body, print_chunk=print_chunk)


async def test_mindserchhitlweb(print_chunk: bool = False):
    body = {
        #"user_prompt": "请阅读网页 https://m.gdmede.com.cn/announcement/undefined/detail?id=1876194179416068096 和他的附件，然后找到 阿普米司特片 的详细信息",
        "user_prompt": "有哪些正在进展的增肌药靶点",
        "agent": "mindsearchhitlweb",
        "history_messages": [],
        "params": {
            "language": 'CN',
        }
    }
    await chat(body=body, print_chunk=print_chunk)

async def chat(body: dict, write_file: bool = False, print_chunk: bool = False):
    request_scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/chat",
        "raw_path": b"/chat",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("testserver", 80),
    }
    res = await chat_api(body, request=Request(request_scope))
    print("res", res)

    # 创建一个唯一的文件名，包含时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"mindsearch_officalsite_log_{timestamp}.jsonl"

    response = None

    if write_file:
        with open(filename, 'w', encoding='utf-8') as f:
            async for chunk in res.body_iterator:
                if print_chunk:
                    print(chunk)
                response = chunk
                # 将每个 chunk 写入文件
                json.dump({"chunk": chunk}, f, ensure_ascii=False)
                f.write('\n')  # 添加换行符以分隔每个 JSON 对象
        print(f"Chunks have been saved to {filename}")
    else:
        
        async for chunk in res.body_iterator:
            if print_chunk:
                print(chunk)
            response = chunk
            #print("chunk", chunk)2

    # print(f"Chunks have been saved to {filename}")

async def test_save_oss_md():
    content = """
        - 疫苗在全球公共卫生中的战略地位，流感疫苗作为重点免疫产品的特殊性。
        - 中国流感疫苗免疫体系的历史演进与现实挑战。
        - 国产流感疫苗的研发、推广与应用二十年历程。
        - 现有进展与核心矛盾（如疫苗覆盖率、免疫策略、技术创新与国际比较）。
        - 领域缺口：国产疫苗在特殊人群、流感负担、免疫策略等方面的研究不足，局限与不足的篇幅占比不需要太多。
        - 最后一段说明综述目的：系统回顾国产流感疫苗在中国免疫体系中的价值，展望未来发展方向。
        综述目的不应该偏重于技术性问题罗列（如覆盖率、策略优化、证据分级等），应该紧扣题目的核心立意：时间维度（二十年）、主体身份（国产疫苗）、系统嵌入（中国免疫防控体系） 以及 双重任务（回顾 + 展望）。",
        "二、研究方法与综述策略（Methods）
        目标：明确综述文献检索、筛选与分析方法，确保综述的科学性与系统性。
        建议字数：600–700（约 7 %）
        2.1 文献来源与检索策略
        - 数据库： PubMed、WHO、CDC等权威文件，官方新闻以及sinovac提供的资料。
        - 检索时间范围：2005–2025。
        - 关键词：influenza vaccine,  China, immunization, burden, effectiveness。
        - 纳入与排除标准：聚焦国产流感疫苗相关的流行病学、免疫策略、效果评价等。
        2.2 综述分析方法
        - 叙述性综述（Narrative Review）与主题分析（Thematic Analysis）。",
        "三、国产感疫苗在中国免疫体系中的历史演进（Historical Evolution）
        目标：系统梳理国产流感疫苗的研发、审批、推广与政策支持历程，重点介绍科兴疫苗。
        建议字数：1600–1800（约 18 %）
        3.1 研发与技术突破
        - 早期技术路线与关键节点。
        - 主要生产企业（重点描述科兴疫苗）与创新进展。
        3.2 政策推动与审批流程
        - 国家免疫规划与政策演变。
        - 疫苗审批与上市流程优化。
    """
    oss_path = oss_singleton_client.upload_string(content, "kybk/thesis/test1.md", content_type='text/markdown; charset=utf-8')
    print(oss_path)


# 测试带有代码计算能力的金融搜索智能体
asyncio.run(test_mindsearch())
# asyncio.run(test_mindsearch_images())

# asyncio.run(test_mindsearchrewrite_feedback())

# asyncio.run(test_mindsearchchina())
# asyncio.run(test_mindsearch_pubmed(print_chunk=True))
#asyncio.run(test_save_oss_md())
# asyncio.run(test_mindsearchcatalystevent())
# asyncio.run(test_mindsearch_history())
