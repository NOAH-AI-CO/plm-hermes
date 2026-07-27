# -*- coding: utf-8 -*-

import asyncio
import logging
from typing import Any, Dict

from config import api_config
from utils.core.httpx_client import HttpxClientSingleton

logger = logging.getLogger(__name__)


class DitingSensitiveChecker:
    """Client for the Diting sensitive content check service."""

    def __init__(self) -> None:
        self.http_client = HttpxClientSingleton.get_asynclient()
        self.token: str = api_config.DITING_API_KEY
        self.url: str = api_config.DITING_API_URL

    async def simple_check(self, content: str, chunk_size=1000, only_politics=False, min_ratio=0) -> bool:
        """
        Check content sensitivity by splitting it into 2000-character chunks and
        issuing concurrent requests to the Diting service.

        Args:
            content: The text to check.

        Returns:
            boolean: False means contains sensitive content, True means no sensitive content.

        Raises:
            ValueError: If required configuration values are missing.
        """

        if not content:
            return True

        chunk_length = chunk_size
        chunks = [content[i : i + chunk_length] for i in range(0, len(content), chunk_length)]
        
        num_chunks = len(chunks)

        async def _check_chunk(chunk: str, chunk_id: str) -> Dict[str, Any]:
            payload = {
                "token": self.token,
                "context": chunk,
                "context_type": "chat",
                "data_id": chunk_id,
            }
            try:
                response = await self.http_client.post(self.url, json=payload)
                response.raise_for_status()
                data = response.json()
            except Exception as e:  # pylint: disable=broad-except
                data = {"data_id": chunk_id, "code": -1, "msg": str(e)}
            return data

        tasks = [
            asyncio.create_task(_check_chunk(chunk, str(idx + 1)))
            for idx, chunk in enumerate(chunks)
        ]

        results =  await asyncio.gather(*tasks)
        zipped = list(zip(chunks,results))
        chunks_blocked = 0
        for result in results:
            if result.get('code', -1) == 0:
                data = result.get('data', {})
                if data.get('label', '') == 'porn':
                    logger.info(f"Diting check skipping porn result {data}")
                    continue
                if data.get('suggestion', '') != 'pass':
                    logger.info(f"Diting check result {data}")
                    if only_politics:
                        if data.get('label', '') != 'politics':
                            continue
                    print("Results and chunks for Diting check:", zipped)
                    chunks_blocked += 1
        
        if chunks_blocked / num_chunks > min_ratio:
            print("Diting check content", content)
            print(f"Diting check: {chunks_blocked} chunks blocked out of {num_chunks} total chunks.")
            return False
        
        return True

        

async def test_diting():
    diting = DitingSensitiveChecker()

    result = await diting.simple_check("""{'sub_query': '查找DOI为10.1017/S0021911807000617的学术论文', 'keyword': '10.1017/S0021911807000617', 'keyword_en': '10.1017/S0021911807000617', 'region': <WebSearchRegion.GLOBAL: 'global'>, 'search_type': <SearchEngine.MEDICAL: 'medical'>, 'search_result': {0: {'url': 'https://www.cambridge.org/core/journals/journal-of-asian-studies/article/chinese-cultural-revolution-as-history-edited-by-joseph-w-esherick-paul-g-pickowicz-and-andrew-g-walder-stanford-calif-stanford-university-press-2006-x-382-pp-6500-cloth-2495-paper/2DA25477CC286039C38E4E7E6797D221', 'summ': 'The Chinese Cultural Revolution as History. Edited by Joseph W. Esherick, Paul G. Pickowicz, and Andrew G. Walder. Stanford, Calif.', 'title': 'The Chinese Cultural Revolution as History. Edited by Joseph W. ...', 'site_name': 'www.cambridge.org'}, 1: {'url': 'https://read.dukeupress.edu/journal-of-asian-studies/article-abstract/66/2/534/341150/The-Chinese-Cultural-Revolution-as-History', 'summ': 'Through eight diverse case studies, this excellent collection examines how ordinary Chinese were affected by the “Cultural Revolution ...', 'title': 'The Chinese Cultural Revolution as History', 'site_name': 'read.dukeupress.edu'}, 2: {'url': 'https://www.academia.edu/1511763/Book_Review_Cultural_Governance_and_Resistance_in_Pacific_Asia_William_Callahan_', 'summ': 'William Callahan\'s \\"Cultural Governance and Resistance in Pacific Asia\\" delves into the interplay of culture, politics, and power within Asia, ...', 'title': 'Cultural Governance and Resistance in Pacific Asia ...', 'site_name': 'www.academia.edu'}, 3: {'url': 'https://pubmed.ncbi.nlm.nih.gov/40824077/', 'summ': 'Economic gains from hypothetical improvements in the psychosocial work environment: A cohort study of 71 207 workers in Denmark · Authors.', 'title': 'A cohort study of 71 207 workers in Denmark', 'site_name': 'pubmed.ncbi.nlm.nih.gov'}, 4: {'url': 'https://pubmed.ncbi.nlm.nih.gov/26224563/', 'summ': 'by M Esperón-Rodríguez · 2016 · Cited by 49 — Socio-economic vulnerability is exacerbated in areas where temperature increases and precipitation decreases.', 'title': 'Socio-economic vulnerability to climate change in the ...', 'site_name': 'pubmed.ncbi.nlm.nih.gov'}, 5: {'url': 'https://pubmed.ncbi.nlm.nih.gov/41097170/', 'summ': 'by S Dalibalta · 2025 — The objective of this study was to evaluate the diet of two different groups of university students, in the United Arab Emirates (UAE) and ...', 'title': 'A Cross-Cultural Comparison of Dietary Intake in University ...', 'site_name': 'pubmed.ncbi.nlm.nih.gov'}}}""")
    print(result)
    result = await diting.simple_check("Chinese Cultural Revolution")
    print(result)

#     result = await diting.simple_check("""<think>
# 用户要求直接阅读并总结一篇文章：
# 《Global, regional, and national burden of chronic kidney disease in adults, 1990-2023, and its attributable risk factors: a systematic analysis for the Global Burden of Disease Study 2023》

# 我需要根据提供的搜索结果来总结这篇文章。搜索结果包含了多个来源的信息：

# 1. 从PubMed摘要（citation:3）中可以看到：
# - 这是GBD 2023研究的一部分
# - 2023年，全球20岁及以上成年人中估计有7.88亿（95%不确定性区间7.43-8.43亿）患有CKD，而1990年为3.78亿（3.54-4.07亿）
# - 全球年龄标准化患病率为14.2%（13.4-15.2），相对1990年上升了3.5%（2.7-4.1）
# - 北非和中东地区年龄标准化患病率最高（18.0%；16.9-19.4）
# - 大多数患者为1-3期CKD，合并患病率为13.9%（13.1-15.0）
# - 2023年，CKD是全球第九大死因，导致148万（130-165万）人死亡
# - 是第12大DALYs原因，年龄标准化DALY率为每10万人769.2（691.8-857.4）
# - 肾功能受损作为危险因素占心血管死亡的11.5%（8.4-14.5）
# - 高空腹血糖、高BMI和高收缩压是CKD DALYs的主要危险因素

# 2. 从GBD官网（citation:10）可以看到：
# - 该数据集包含1990-2023年20岁及以上成年人CKD死亡率、患病率和DALYs的年龄标准化率
# - 研究覆盖204个国家和地区

# 3. 从其他引文（citation:1,2,4等）确认了：
# - 2023年CKD是全球第九大死因，约148万人死亡
# - 约14%的成年人患有CKD

# 4. 从citation:8可以看到关于肾衰竭的信息：
# - 2023年全球有357万透析病例

# 5. 从citation:6可以看到一篇类似但时间范围不同的研究（1990-2021），这有助于理解研究方法，但用户要求的是1990-2023的研究

# 用户要求"直接阅读这篇文章帮我总结一下"，所以我需要：
# 1. 提供文章的全面总结
# 2. 使用正式报告风格
# 3. 正确添加引用标注
# 4. 使用markdown格式
# 5. 包含详细数据
# 6. 不要猜测，只基于提供的信息

# 我需要组织以下内容：
# - 研究背景和方法
# - 主要发现（患病率、死亡率、DALYs）
# - 区域差异
# - 风险因素
# - 临床分期分布
# - 结论和意义

# 需要注意的是，虽然用户要求"直接阅读这篇文章"，但我实际上是通过搜索结果间接获取信息。不过根据搜索结果，我已经获得了文章的摘要和关键数据，可以提供一个全面的总结。

# 让我开始构建回答结构：

# # 研究概述与方法
# 介绍研究的基本信息和方法学

# # 全球疾病负担核心数据
# - 患病率变化
# - 死亡率排名
# - DALYs

# # 区域差异分析
# 不同地区的患病率差异

# # 疾病分期分布
# CKD 1-3期 vs 4-5期

# # 主要归因风险因素
# 代谢性风险因素

# # 心血管影响
# 肾功能受损对心血管死亡的影响

# # 结论与政策启示

# 我需要确保每个数据点都正确引用，并且使用表格来展示复杂信息。</think>
# # 全球成人慢性肾病疾病负担系统分析报告总结

# ---

# ## 研究概述与方法学框架

# 本研究为全球疾病负担研究（Global Burden of Disease Study, GBD）2023系列的一部分，系统分析了1990年至2023年间204个国家和地区的成人慢性肾病（Chronic Kidney Disease, CKD）流行病学特征及归因风险因素[citation:3][citation:10]。研究聚焦20岁及以上成年人群，整合了已发表文献、生命登记系统、肾脏疾病治疗登记和家庭调查等多源数据[citation:3]。

# 研究采用死因集成模型（Cause of Death Ensemble model）和贝叶斯元回归分析工具，估算CKD的死亡、发病率、患病率和伤残调整生命年（Disability-Adjusted Life Years, DALYs）。通过比较风险评估方法，量化了肾功能受损对心血管死亡的归因比例，并识别了CKD的主要代谢性风险因素[citation:3]。

# ---

# ## 全球疾病负担核心数据

# ### 患病率显著增长
# 2023年全球20岁及以上成年人CKD患病人数达**7.88亿**（95%不确定性区间：7.43-8.43亿），较1990年的3.78亿（3.54-4.07亿）大幅增加[citation:3]。全球年龄标准化患病率为**14.2%**（13.4%-15.2%），相对1990年上升3.5%（2.7%-4.1%）[citation:3]。这意味着全球约**14%的成年人**受CKD影响[citation:16][citation:20]。

# | 指标 | 1990年 | 2023年 | 变化趋势 |
# |------|--------|--------|----------|
# | 患病人数 | 3.78亿 | 7.88亿 | +108% |
# | 年龄标准化患病率 | 13.7% | 14.2% | 相对上升3.5% |
# | 全球成人患病率估算 | - | 约14% | - |

# ### 死亡率与DALYs排名
# 2023年，CKD在全球死因顺位中位列**第九**，导致**148万**（130-165万）人死亡[citation:1][citation:3]。在疾病负担排名中，CKD位列**第12位**，年龄标准化DALY率为每10万人**769.2**（691.8-857.4）[citation:3]。

# ---

# ## 区域差异与地理分布特征

# ### 患病率区域不均衡
# 北非和中东地区年龄标准化患病率最高，达**18.0%**（16.9%-19.4%）[citation:3]。疾病负担在全球范围内分布极不均匀，医疗可及性存在显著差异[citation:7]。

# ### 社会人口学指数（SDI）影响
# 虽然高SDI地区通常表现出较低的CKD负担，但研究数据显示，肾衰竭患者的肾脏替代治疗可及性在全球范围内仍高度不均衡[citation:7]。2023年全球透析病例达357万（95%不确定性区间：311-417万），年龄标准化患病率为每10万人39.3（35.6-44.4）[citation:8]。

# ---

# ## 疾病分期与临床特征

# ### 早期阶段占绝对主导
# 绝大多数CKD患者处于疾病早期阶段。2023年数据显示，**1-3期CKD合并患病率达13.9%**（13.1%-15.0%），占所有CKD病例的绝大多数[citation:3]。这一分布特征对筛查策略和早期干预具有重要公共卫生意义。

# ---

# ## 主要归因风险因素

# ### 代谢性风险因素主导
# 研究识别出三大核心代谢性风险因素对CKD DALYs的贡献尤为突出[citation:3]：

# 1. **高空腹血浆葡萄糖**
# 2. **高体质指数（BMI）**
# 3. **高收缩压**

# 这些因素不仅是CKD的独立风险因素，还通过相互作用加剧疾病进展。值得注意的是，**肾功能受损作为风险因素本身，可解释11.5%（8.4%-14.5%）的心血管死亡**[citation:3]，凸显了CKD与心血管疾病的双向关联。

# ---

# ## 公共卫生意义与政策启示

# ### 疾病负担持续加重
# CKD已成为重大全球健康问题，其患病率持续上升，作为死因和心血管死亡风险因素的重要性日益凸显[citation:3]。研究强调，需要深化对CKD病因学的理解，建立适宜的筛查体系，并推动实施转化项目，将治疗进展切实转化为患者预后改善[citation:3]。

# ### 数据驱动的政策制定
# GBD 2023数据库提供了迄今为止最全面的CKD流行病学证据，覆盖204个国家和地区、660个次国家级区域[citation:10]。这些数据为各国优化医疗资源配置、制定针对性预防策略和建立综合照护体系提供了关键证据支持[citation:6]。

# ---

# **研究资助**：本研究由盖茨基金会（Gates Foundation）、惠康信托（Wellcome）、美国国家肾脏基金会（US National Kidney Foundation）和美国国家糖尿病、消化和肾脏疾病研究所（US National Institute of Diabetes and Digestive and Kidney Diseases）资助[citation:3]。""", chunk_size=300)
#     print(result)

if __name__ == "__main__":
    asyncio.run(test_diting())
