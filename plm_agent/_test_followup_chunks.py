"""直接调用 stream_followup_qa,记录每个 yield 的时间戳和字数。
不经 HTTP / 不经 SSE / 不经任何前端 — 完全暴露后端流的真实节奏。
"""
import os, sys, asyncio, time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(_ROOT / "gcp_claude.json"))
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "noah-ai-claude")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")

from config import api_config as _ac
_ac.VERTEX_PROJECT_ID = "noah-ai-claude"

from agent.patient_like_me.v1.rag.followup_qa import stream_followup_qa


# 假报告 + 假问题
REPORT = """# 病例核心摘要
患者 65 岁男性,确诊弥漫大 B 细胞淋巴瘤 (DLBCL),Ann Arbor IIIB 期。

## 1. 诊断建议
依据 NCCN 指南[citation:1],DLBCL 诊断需淋巴结活检 + 免疫组化 + 流式细胞 + FISH 检测。

## 2. 进一步检查
- PET-CT 分期评估
- 骨髓活检
- HBV 筛查

## 3. 治疗方案
R-CHOP × 6 周期一线治疗。

参考文献:
[citation:1] 2025 NCCN B细胞淋巴瘤指南 | 第 12 页"""

QUESTION = "请详细介绍 R-CHOP 方案的每个药物,以及为什么这是 DLBCL 的标准一线?"


async def main():
    print("=" * 80)
    print("直接调用 stream_followup_qa,记录每个 chunk 的时间戳和字数")
    print("=" * 80)
    print(f"问题: {QUESTION}")
    print()

    t0 = time.perf_counter()
    last_t = t0
    chunk_idx = 0
    answer_chunks = []
    other_events = []

    async for event_name, payload in stream_followup_qa(
        report_text=REPORT,
        question=QUESTION,
        history=[],
        model="gemini-3.5-flash",
        enable_thinking=False,
    ):
        now = time.perf_counter()
        elapsed_total = (now - t0) * 1000
        elapsed_since_last = (now - last_t) * 1000
        last_t = now

        if event_name == "answer_chunk":
            chunk_idx += 1
            text = payload.get("text", "")
            preview = text.replace("\n", "\\n")[:40]
            print(f"[{elapsed_total:>6.0f}ms +{elapsed_since_last:>5.0f}ms] #{chunk_idx:>3d} len={len(text):>3d}  {preview!r}")
            answer_chunks.append({"idx": chunk_idx, "ts_ms": elapsed_total, "delta_ms": elapsed_since_last, "len": len(text), "text": text})
        else:
            other_events.append({"event": event_name, "ts_ms": elapsed_total})
            print(f"[{elapsed_total:>6.0f}ms +{elapsed_since_last:>5.0f}ms] [{event_name}] {str(payload)[:80]}")

    print()
    print("=" * 80)
    print("流统计")
    print("=" * 80)
    if answer_chunks:
        total_chars = sum(c["len"] for c in answer_chunks)
        total_time = answer_chunks[-1]["ts_ms"] - answer_chunks[0]["ts_ms"]
        deltas = [c["delta_ms"] for c in answer_chunks[1:]]  # 第一个 chunk 的 delta 是从开始
        print(f"answer_chunk 总数:        {len(answer_chunks)}")
        print(f"总字数:                   {total_chars}")
        print(f"chunk 间隔时间(ms):       min={min(deltas):.0f}  max={max(deltas):.0f}  avg={sum(deltas)/len(deltas):.0f}")
        print(f"chunk 字数分布:           min={min(c['len'] for c in answer_chunks)}  max={max(c['len'] for c in answer_chunks)}  avg={total_chars/len(answer_chunks):.1f}")
        print(f"首字 chunk 出现时间:      {answer_chunks[0]['ts_ms']:.0f}ms")
        print(f"末字 chunk 出现时间:      {answer_chunks[-1]['ts_ms']:.0f}ms")
        print(f"answer 流持续:            {total_time:.0f}ms")
        print()
        # 判定
        if len(answer_chunks) >= 10 and max(deltas) > 50:
            print("✅ 真流式: 多个 chunk 间隔明显,后端确实是一个 chunk 一 yield")
        elif len(answer_chunks) < 5:
            print(f"⚠️  chunk 数太少({len(answer_chunks)}),可能 Gemini 一次吐很大段,看着像一次性")
        else:
            print(f"🤔 chunk 数={len(answer_chunks)}, 大部分间隔很短(<50ms), 视觉上接近一次性")


if __name__ == "__main__":
    asyncio.run(main())
