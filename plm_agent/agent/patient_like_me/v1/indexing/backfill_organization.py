"""一次性 backfill: 按 filename 推断给每份 plm_guidelines 补 organization 字段。

规则 (跟 evidence.infer_organization_from_filename 一致):
  - 文件名含 NCCN → "NCCN"
  - 文件名含 CSCO / 中国临床肿瘤学会 → "CSCO"
  - 文件名含 ESMO → "ESMO"
  - 文件名含 CACA / 中国抗癌协会 → "CACA"
  - 其他 → "OTHER" (只作补充指南)

跑法:
  cd noah_agent
  python -m agent.patient_like_me.v1.indexing.backfill_organization
"""
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_NOAH_AGENT_ROOT = _SCRIPT_DIR.parents[3]
if str(_NOAH_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_NOAH_AGENT_ROOT))


def main():
    from agent.patient_like_me.v1.es.plm_index import get_es_client, PLM_INDEX
    from agent.patient_like_me.v1.rag.evidence import infer_organization_from_filename
    es = get_es_client()

    # 扫全部 doc 拿 filename + 现有 organization
    resp = es.search(index=PLM_INDEX, body={
        "query": {"match_all": {}},
        "size": 500,
        "_source": ["filename", "organization", "product_scope"],
    })
    hits = resp.get("hits", {}).get("hits", [])
    print(f"total docs: {len(hits)}")

    dist_before = {}
    dist_after = {}
    updates = []
    for h in hits:
        s = h.get("_source", {})
        fname = s.get("filename", "")
        current_org = s.get("organization", "")
        inferred = infer_organization_from_filename(fname)
        dist_before[current_org or "(空)"] = dist_before.get(current_org or "(空)", 0) + 1
        dist_after[inferred] = dist_after.get(inferred, 0) + 1
        if current_org != inferred:
            updates.append((h["_id"], current_org, inferred, fname))

    print("\n=== 分布对比 ===")
    print(f"BEFORE: {dist_before}")
    print(f"AFTER : {dist_after}")
    print(f"\n需更新: {len(updates)}")
    for _id, before, after, fname in updates[:10]:
        print(f"  {_id}  {before or '(空)':6s} -> {after:6s}  {fname[:70]}")
    if len(updates) > 10:
        print(f"  ... 共 {len(updates)} 条")

    if not updates:
        print("\n无需更新")
        return

    ans = input("\n执行更新? (yes/no): ").strip().lower()
    if ans != "yes":
        print("已取消")
        return

    # bulk update
    from elasticsearch.helpers import bulk
    actions = [
        {"_op_type": "update", "_index": PLM_INDEX, "_id": _id,
         "doc": {"organization": after}}
        for _id, _, after, _ in updates
    ]
    ok, errors = bulk(es, actions, refresh=True, raise_on_error=False)
    print(f"\n✅ 更新完成: ok={ok} errors={len(errors) if isinstance(errors, list) else errors}")


if __name__ == "__main__":
    main()
