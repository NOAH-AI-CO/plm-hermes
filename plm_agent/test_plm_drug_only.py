"""Quick test: only run the drug manual branch of PLM workflow."""
import asyncio
import json
import sys
import os
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

async def main():
    from agent.patient_like_me.v1.rag.workflow import (
        step_extract_drugs_from_treatment,
        step_search_drug_manuals,
        step_generate_drug_cards,
        step_drug_interaction_analysis,
        _expand_drug_name,
    )

    treatment_text = """
    根据NCCN指南，该APL低危患者推荐采用全反式维甲酸(ATRA)+三氧化二砷(ATO)方案进行诱导治疗。
    需立即启动ATRA，同时积极输注血小板和冷沉淀/新鲜冰冻血浆纠正凝血功能障碍。
    巩固治疗阶段可考虑加用阿糖胞苷或蒽环类药物（如去甲氧柔红霉素/柔红霉素）。
    若出现分化综合征，需给予地塞米松治疗。
    """
    patient_info_text = "35岁女性，高度怀疑APL，WBC 4.5x10^9/L，PLT 22x10^9/L，Fib 0.9g/L"

    print("=" * 60)
    print("  Step 1: 提取药物")
    print("=" * 60)
    t0 = time.time()
    drug_data = await step_extract_drugs_from_treatment(treatment_text, patient_info_text)
    print(f"  耗时: {time.time()-t0:.1f}s")
    print(f"  推荐药物: {drug_data.get('recommended_drugs', [])}")
    print(f"  现有用药: {drug_data.get('current_medications', [])}")

    all_drugs = drug_data.get("recommended_drugs", [])
    if not all_drugs:
        all_drugs = ["全反式维甲酸", "三氧化二砷", "地塞米松", "阿糖胞苷"]
        print(f"  (提取失败，使用兜底列表: {all_drugs})")

    print("\n" + "=" * 60)
    print("  Step 2: 别名展开 (测试单个)")
    print("=" * 60)
    t0 = time.time()
    aliases = await _expand_drug_name("全反式维甲酸")
    print(f"  耗时: {time.time()-t0:.1f}s")
    print(f"  全反式维甲酸 → {aliases}")

    print("\n" + "=" * 60)
    print("  Step 3: 搜索药物说明书")
    print("=" * 60)
    t0 = time.time()
    manuals = await step_search_drug_manuals(all_drugs[:5])
    print(f"  耗时: {time.time()-t0:.1f}s")
    print(f"  找到 {len(manuals)} 个说明书")
    for m in manuals:
        name = m.get("common_name") or m.get("show_name") or m.get("matched_drug", "?")
        text_len = len(m.get("text", ""))
        print(f"    - {name} ({m.get('match_type', '?')}, {text_len} 字)")

    if manuals:
        print("\n" + "=" * 60)
        print("  Step 4: 生成药物卡片 + 相互作用分析")
        print("=" * 60)
        t0 = time.time()
        cards, interaction = await asyncio.gather(
            step_generate_drug_cards(manuals[:3], treatment_text, patient_info_text),
            step_drug_interaction_analysis(manuals[:3], [], patient_info_text),
        )
        print(f"  耗时: {time.time()-t0:.1f}s")
        print(f"\n  --- 药物卡片 ({len(cards)} 字) ---")
        print(cards[:1500] if cards else "  (空)")
        print(f"\n  --- 相互作用分析 ({len(interaction)} 字) ---")
        print(interaction[:1000] if interaction else "  (空)")
    else:
        print("\n  ❌ 无说明书，跳过卡片和相互作用分析")

if __name__ == "__main__":
    asyncio.run(main())
