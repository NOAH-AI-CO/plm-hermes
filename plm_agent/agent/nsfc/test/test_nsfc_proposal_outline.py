from pathlib import Path

from agent.nsfc.nsfc_prep_analyzer import (
    llm_call_for_nsfc_proposal_outline,
)


async def test_llm_call_for_nsfc_proposal_outline():
    p = Path(__file__).resolve().parent / "test_nsfc_proposal_outline.txt"
    with open(p, "r") as f:
        prompt = f.read()
    out = await llm_call_for_nsfc_proposal_outline(prompt, temperature=0.3)
    print(out)