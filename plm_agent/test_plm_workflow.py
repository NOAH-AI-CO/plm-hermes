"""
Standalone test for PLM-333 淋巴瘤循证诊疗建议 workflow.
Usage: conda run -n noahserver python test_plm_workflow.py
"""
import asyncio
import json
import sys
import os
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from agent.patient_like_me.v1.rag.workflow import run_plm_workflow

PATIENT_INPUT = """【病例描述】 患者，女，35岁，因"反复牙龈出血伴月经量增多2周，突发周身瘀斑2天"就诊于某基层医院。 查体：神志清，重度贫血貌，全身皮肤可见多处散在瘀斑，双下肢为著。 实验室检查：白细胞（WBC）4.5 × 10^9/L，血红蛋白（Hb）72 g/L，血小板（PLT）22 × 10^9/L。凝血功能提示：凝血酶原时间（PT）18秒，部分凝血活酶时间（APTT）45秒，纤维蛋白原（Fib）0.9 g/L，D-二聚体显著升高。 外周血涂片：可见异常早幼粒细胞，部分细胞浆内可见柴捆状Auer小体。 该院首诊医生的治疗计划如下：高度怀疑急性早幼粒细胞白血病（APL），已抽血送检 PML::RARA 融合基因PCR检测（预计4天后出结果）。在等待基因结果期间，给予输注单采血小板维持PLT > 20 × 10^9/L，暂不进行其他特殊干预；同时计划为患者留置中心静脉导管（PICC）以为后续高强度化疗做准备。请判断首诊医生的治疗方案是否正确？若不正确，指出错误处并给出正确方案。"""


async def main():
    events = []

    def on_event(name, payload):
        events.append({"event": name, "payload": payload})
        print(f"  📡 EVENT: {name}")

    print("=" * 80)
    print("PLM-333 淋巴瘤循证诊疗建议 Workflow Test")
    print("=" * 80)
    print(f"\n输入病例 (前100字): {PATIENT_INPUT[:100]}...\n")

    start = time.time()
    try:
        result = await run_plm_workflow(PATIENT_INPUT, on_event=on_event)
        elapsed = time.time() - start

        print("\n" + "=" * 80)
        print(f"WORKFLOW COMPLETED in {elapsed:.1f}s  (path: {result.get('path')})")
        print("=" * 80)

        print("\n--- Patient Info (structured) ---")
        print(json.dumps(result.get("patient_info", {}), ensure_ascii=False, indent=2))

        print("\n--- Output ---")
        output = result.get("output", "")
        print(output)

        print(f"\n--- Stats ---")
        print(f"Output length: {len(output)} chars")
        print(f"Events: {len(events)}")
        print(f"Path: {result.get('path')}")
        print(f"Diagnosis clear: {result.get('diagnosis_clear')}")

    except Exception as e:
        elapsed = time.time() - start
        print(f"\n❌ WORKFLOW FAILED after {elapsed:.1f}s: {e}")
        import traceback
        traceback.print_exc()
        print(f"\nEvents so far: {[e['event'] for e in events]}")


if __name__ == "__main__":
    asyncio.run(main())
