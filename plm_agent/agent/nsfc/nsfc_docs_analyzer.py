from typing import Any, Dict, List
import io
import os
import re
from abc import ABC
import asyncio
from utils.docs.parsing import batch_convert_documents_async
from i18n.languages import normalize as _norm

class NSFCDocsAnalyzer(ABC):

    def __init__(self, model, **kwargs):
        self.model = model
        self.language = _norm(kwargs.get('language', ''))
        self.input_dir = './inputs'

        self.max_files = kwargs.get('max_files', 10)
        self.max_concurrent = kwargs.get('max_concurrent', 10)

        # {"name": str, "path": str, "content_bytes": bytes}
        self.raw_files: List[Dict[str, Any]] = []
        # {"name": str, "content": str, "error": Optional[str]}
        self.converted_docs: List[Dict[str, Any]] = []
        # {"name": str, "summary": str}
        self.summarized_docs: List[Dict[str, Any]] = []

    def set_input_dir(self, input_dir: str):
        self.input_dir = input_dir

    def load_raw_files(self):
        base = str(self.input_dir)
        self.raw_files = []

        try:
            entries = sorted(os.listdir(base))
        except FileNotFoundError:
            raise FileNotFoundError(f"input_dir 不存在：{base}")

        for filename in entries:
            filepath = os.path.join(base, filename)
            if not os.path.isfile(filepath):
                continue
            # if not filename.lower().endswith((".pdf", ".txt", ".md")):
            #     continue
            try:
                with open(filepath, "rb") as f:
                    content_bytes = f.read()
            except Exception as e:
                print(f"[NSFCUserDocPipeline] 读取文件失败: {filepath} ({e})")
                continue

            self.raw_files.append({
                "name": filename,
                "path": filepath,
                "content_bytes": content_bytes,
            })
            if len(self.raw_files) >= self.max_files:
                break
        return self.raw_files
    
    def load_raw_files_from_request(self, django_files):
        """从 Django request.FILES 或文件路径元组列表初始化 raw_files.
        
        支持两种输入格式：
        1. Django文件对象列表（有.read()方法）
        2. (filename, filepath) 元组列表
        """
        self.raw_files = []

        for f in django_files[: getattr(self, "max_files", len(django_files))]:
            # 检查是否为元组格式 (filename, filepath)
            if isinstance(f, tuple) and len(f) == 2:
                name, filepath = f
                try:
                    with open(filepath, "rb") as file:
                        content_bytes = file.read()
                    
                    self.raw_files.append({
                        "name": name,
                        "path": filepath, 
                        "content_bytes": content_bytes,
                    })
                except Exception as e:
                    print(f"[NSFCUserDocAnalyzer] 读取文件失败: {filepath} ({e})")
                    continue
            # Django文件对象格式
            else:
                content_bytes = f.read()
                f.seek(0)

                self.raw_files.append({
                    "name": f.name,
                    "path": "", 
                    "content_bytes": content_bytes,
                })

        print(f"[NSFCUserDocAnalyzer] 从 request 收到 {len(self.raw_files)} 个文件")
        return self.raw_files

    async def convert_documents(self):
        if not getattr(self, "raw_files", None):
            print("[NSFCUserDocPipeline] raw_files 为空，请先调用 load_raw_files()")
            self.converted_docs = []
            return self.converted_docs

        self.converted_docs = await batch_convert_documents_async(self.raw_files, max_concurrent=self.max_concurrent)
        # 释放原始文件内存
        self.raw_files = []
        print("[NSFCUserDocPipeline] raw_files 已清空（转换完成后释放原始文件内存）")

        return self.converted_docs

    def build_research_prompt(self, content_for_llm: str) -> str:
        return (
            "你是一名长期参与国家自然科学基金项目评审与申请辅导的科研顾问，"
            "当前任务不是简单总结文献内容，而是："
            "从申请人过往的一篇论文或项目材料中，"
            "反向提炼其【研究方向定位】【研究主线连续性】以及【可支撑国自然申请的研究基础】。\n\n"

            "【核心任务目标】\n"
            "请站在“国自然评审专家”的视角回答：\n"
            "1）申请人主要在什么研究方向上持续开展工作？\n"
            "2）这项工作在其整体研究体系中处于什么位置？\n"
            "3）它具体证明了申请人具备哪些可迁移、可延续的研究能力？\n\n"

            "请严格按照以下 Markdown 结构输出，内容需体现分析与抽象，而非简单复述：\n\n"

            "### 一、研究方向与学术定位判断\n"
            "- 所属一级/二级学科或交叉领域（从评审视角概括）：\n"
            "- 申请人长期聚焦的核心研究方向或机制问题（1–2 条，强调“持续性”）：\n"
            "- 该文献/项目在申请人研究体系中的角色（如：方向奠基 / 方法建立 / 机制深化 / 应用扩展）：\n\n"

            "### 二、研究问题拆解与科学逻辑\n"
            "- 本工作试图解决的核心科学问题是什么（用“为什么重要”而非“做了什么”表述）：\n"
            "- 该问题在领域中的位置（机制层面 / 方法层面 / 应用层面）：\n"
            "- 研究思路或假设的科学合理性：\n\n"

            "### 三、研究设计与关键技术路径（能力导向）\n"
            "- 关键研究设计（模型/人群/实验体系/分析框架）：\n"
            "- 申请人已系统掌握的关键技术或方法组合：\n"
            "- 是否体现跨技术或跨学科整合能力（如实验 + 数据分析、医学 + 计算）：\n\n"

            "### 四、已取得的阶段性认识或方法学积累\n"
            "- 已形成的核心认识、规律性结论或方法学经验（不要求具体数据）：\n"
            "- 相比领域常规研究的增量价值或特色：\n\n"

            "### 五、可直接用于“研究基础”章节的论证要点\n"
            "- 申请人在该方向上已建立的研究基础（偏“能力与体系”，非结果罗列）：\n"
            "- 已形成的研究技术路线或分析范式：\n"
            "- 对本次拟申请国自然项目的直接支撑关系（明确“从这里到拟申请课题”的逻辑衔接）：\n\n"

            "【写作要求】\n"
            "- 严禁虚构原文未涉及的实验或结论；\n"
            "- 允许在原文基础上进行学术抽象与评审视角下的合理归纳；\n"
            "- 避免论文式语言，优先使用“前期研究表明……”“已建立……研究体系”等国自然常用表述；\n"
            "- 语言正式、克制，突出研究主线与延续性。\n\n"

            "【文档内容】\n"
            f"{content_for_llm}\n"
        )

    def build_compliance_prompt(self, content_for_llm: str) -> str:
        return (
            "你是一名熟悉国家自然科学基金申请书形式审查与合规表述的科研助理。\n"
            "请仅依据下方文档内容，抽取并生成可用于申请书以下栏目内容。"
            "严禁虚构不存在的国家级/国自然项目；如材料未给出，必须明确写“无/未提及”。\n\n"

            "请按 Markdown 输出，结构严格如下：\n\n"
            "### 3. 正在承担的与本项目相关的科研项目情况\n"
            "- 是否存在国家级在研项目：是/否/材料未提及\n"
            "- 若是：逐项列出：资助机构、项目类别、批准号、项目名称、金额、起止年月、与本项目关系、本人负责内容\n"
            "- 若否或未提及：给出规范化一句话说明（不超过80字）\n\n"

            "### 4. 完成国家自然科学基金项目情况\n"
            "- 是否存在已结题基金项目：是/否/材料未提及\n"
            "- 若是：项目名称及批准号、完成情况、后续进展、与本申请关系（尽量精炼）\n"
            "- 若否或未提及：给出规范化一句话说明\n\n"

            "### （三）其他需要说明的情况\n"
            "1) 同年申请不同类型基金项目：有/无/材料未提及（如有列项目类型+名称+与本项目关系）\n"
            "2) 高级职称同年申请或参与项目单位不一致：有/无/材料未提及（如有：人名、项目、单位、原因）\n"
            "3) 承担基金项目单位不一致：有/无/材料未提及（如有：批准号、项目类型、单位、起止年月、原因）\n"
            "4) 同年以不同职称申请/参与：有/无/材料未提及（如有：原因）\n"
            "5) 其他：无/材料未提及/补充说明\n\n"

            "【文档内容】\n"
            f"{content_for_llm}\n"
        )

    async def run_prompt_stream(self, prompt: str) -> str:
        summary_gen = self.model.generate_stream(prompt)
        buf = io.StringIO()
        async for chunk in summary_gen:
            if chunk:
                buf.write(chunk)
        text = buf.getvalue()
        buf.close()
        return self.clean_llm_think_output(text)
    
    async def summarize_single_doc(self, doc: Dict[str, Any]):
        max_chars = 15000
        raw = doc.get("content", "") or ""
        truncated = len(raw) > max_chars
        content_for_llm = raw[:max_chars] + ("\n\n（后文已截断，仅供概要分析）" if truncated else "")

        research_prompt = self.build_research_prompt(content_for_llm)
        compliance_prompt = self.build_compliance_prompt(content_for_llm)

        research_md = await self.run_prompt_stream(research_prompt)
        compliance_md = await self.run_prompt_stream(compliance_prompt)

        merged_md = (
            f"## 文档：{doc.get('name','')}\n\n"
            f"### A. 研究内容与申请价值综述\n\n{research_md}\n\n"
            f"---\n\n"
            f"### B. 合规栏目所需信息（项目情况/其他说明）\n\n{compliance_md}\n"
        )

        return {
            "name": doc.get("name", ""),
            "summary_md": merged_md,
            "sections": {
                "research": research_md,
                "compliance": compliance_md,
            },
            "meta": {
                "truncated": truncated,
                "chars_used": min(len(raw), max_chars),
            }
        }

    async def summarize_single_doc(self, doc: Dict[str, Any]):
        max_chars = 15000
        if len(doc.get("content", "")) > max_chars:
            content_for_llm = doc.get("content", "")[:max_chars] + "\n\n（后文已截断，仅供概要分析）"
        else:
            content_for_llm = doc.get("content", "")

        prompt = (
            "你是一名科研助理，正在帮助申请人梳理自己以往的论文/项目资料，"
            "为后续撰写国家自然科学基金标书做准备。\n\n"
            "【任务说明】\n"
            "请阅读下面这篇文档的内容（可能是论文、项目总结或报告片段），"
            "提炼出与科研课题相关的关键信息，并用 Markdown 格式输出，结构严格按照下面模板：\n\n"
            "### 一、文献/项目基本信息（根据内容推断即可）\n"
            "- 研究对象/疾病领域：\n"
            "- 主要研究问题：\n"
            "- 研究类型（可多选）：临床研究 / 动物实验 / 体外实验 / 方法学 / 数据库分析 / 综述 / 其他（请说明）\n\n"
            "### 二、研究设计与关键方法\n"
            "- 研究设计要点（样本/模型/对照等）：\n"
            "- 关键技术与方法（如组学、单细胞、多参数流式、代谢组、成像、机器学习等）：\n\n"
            "### 三、核心发现与结论\n"
            "- 关键结果 1：\n"
            "- 关键结果 2：\n"
            "- 如有更多重要结果，请继续补充：\n\n"
            "### 四、局限性与改进空间（如原文提及或可合理推断）\n"
            "- 局限性/不足：\n"
            "- 可改进方向：\n\n"
            "### 五、对当前国自然申请的价值\n"
            "- 可作为“研究基础”或“前期工作支撑”的要点：\n"
            "- 对拟申请课题的启发（可延续的机制链条、可拓展的疾病模型/人群、可借鉴的方法组合等）：\n\n"
            "要求：\n"
            "- 尽量基于原文内容，不要凭空捏造具体数据或完全不存在的结论；\n"
            "- 可以做适度概括和合理推断，但不要过度脑补；\n"
            "- 语言保持正式、简洁的科研中文。\n\n"
            "【文档内容】\n"
            f"{content_for_llm}\n")

        model = self.model
        summary_gen = model.generate_stream(prompt)

        buf = io.StringIO()
        async for chunk in summary_gen:
            if chunk:
                buf.write(chunk)
        summary_md = buf.getvalue()
        summary_md = self.clean_llm_think_output(summary_md)
        buf.close()
        
        # 打印日志，显示文档总结
        doc_name = doc.get("name", "")
        print(f"\n[NSFCUserDocAnalyzer] 文档总结完成: {doc_name}")
        print(f"[NSFCUserDocAnalyzer] 总结内容预览（前500字）:\n{summary_md[:500]}...")
        print(f"[NSFCUserDocAnalyzer] 总结全文长度: {len(summary_md)} 字符\n")

        return {
            "name": doc_name,
            "summary": summary_md,
        }

    async def batch_summarize_docs(self):
        if not getattr(self, "converted_docs", None):
            print("[NSFCUserDocPipeline] converted_docs 为空，请先调用 convert_documents()")
            self.summarized_docs = []
            return self.summarized_docs

        docs_for_summary = [
            doc for doc in self.converted_docs
            if not doc.get("error")
        ]
        if not docs_for_summary:
            print("[NSFCUserDocPipeline] 没有可总结的文档（全部转换失败）")
            self.summarized_docs = []
            return self.summarized_docs

        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def summarize_with_limit(doc):
            async with semaphore:
                try:
                    return await self.summarize_single_doc(doc)
                except Exception as e:
                    print(f"[NSFCUserDocPipeline] 总结文档失败: {doc.get('name')}: {e}")
                    # 返回一个带错误信息的占位结果，避免整个 batch 掉链子
                    return {
                        "name": doc.get("name", ""),
                        "summary": "",
                        "error": str(e),
                    }

        tasks = [summarize_with_limit(doc) for doc in docs_for_summary]
        self.summarized_docs = await asyncio.gather(*tasks)
        # 清理中间大文本字段，降低内存占用
        self.drop_heavy_fields()
        return self.summarized_docs
    
    def drop_heavy_fields(self):
        for d in getattr(self, "converted_docs", []):
            d["content"] = ""
        if hasattr(self, "raw_files"):
            self.raw_files = []
        print("[NSFCUserDocPipeline] 已清理中间大文本字段，降低内存占用。")
    

    def clean_llm_think_output(self, text: str) -> str:
        if not text:
            return text
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        if "<think>" in text:
            text = text.split("<think>", 1)[0]
        return text.strip().strip("。．，、；; \n")


# test
if __name__ == "__main__":
    from llm.composite_models import SiliconflowQwen3Models

    async def main():
        model = SiliconflowQwen3Models()
        analyzer = NSFCDocsAnalyzer(model=model)

        input_dir = "./inputs"
        analyzer.set_input_dir(input_dir)

        analyzer.load_raw_files()

        await analyzer.convert_documents()

        await analyzer.batch_summarize_docs()

        print(f"总共总结到 {len(getattr(analyzer, 'summarized_docs', []))} 篇文档")
        if getattr(analyzer, "summarized_docs", None):
            first = analyzer.summarized_docs[0]
            print("第一个文档:", first.get("name"))
            print("summary 预览:\n", (first.get("summary") or "")[:500])

    asyncio.run(main())
    