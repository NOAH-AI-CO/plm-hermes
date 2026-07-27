"""把本地 plm_guidelines index 中 4 case 涉及的 11 个 doc_id 的图谱数据迁移到 172 ES。

用法:
    cd noah_agent
    python -m agent.patient_like_me.v1.indexing.migrate_graphs_to_remote \
        --target-host http://172.16.x.x:9200 \
        --target-user elastic --target-pass <password>

或者把目标地址写到 settings 后直接 python -m ... migrate_graphs_to_remote 默认值。
"""
import argparse, json, sys
from pathlib import Path

_NOAH_AGENT_ROOT = Path(__file__).resolve().parents[4]
if str(_NOAH_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_NOAH_AGENT_ROOT))

from elasticsearch import Elasticsearch, helpers

INDEX = "plm_guidelines"

# 4 case 召回的 11 个 doc_id(从 retrieval_log 抽取确定)
DOC_IDS = [
    2925939153049541,    # 前列腺癌
    127493598119589873,  # 乳腺癌
    153855033964091107,  # 癌症相关疲劳
    182645303427108355,  # 降低乳腺癌风险
    329857612570476408,  # 姑息治疗
    660856882960341925,  # 结肠癌
    694965419023216527,  # 直肠癌
    741908092607819949,  # 心理痛苦的处理
    865311489722855934,  # 肺癌筛查
    880776039033238948,  # 非小细胞肺癌
    928288519894673125,  # 成人癌痛
]

LOCAL_HOST = "http://localhost:6002"
LOCAL_USER = "elastic"
LOCAL_PASS = "elasticnoah"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--target-host", required=True, help="目标 ES,例如 http://172.16.x.x:9200")
    p.add_argument("--target-user", default="elastic")
    p.add_argument("--target-pass", required=True)
    p.add_argument("--local-host", default=LOCAL_HOST)
    p.add_argument("--local-user", default=LOCAL_USER)
    p.add_argument("--local-pass", default=LOCAL_PASS)
    p.add_argument("--dry-run", action="store_true", help="只读对比,不写远端")
    p.add_argument("--doc-ids", help="自定义 doc_id 列表(逗号分隔),覆盖默认 11 个")
    return p.parse_args()


def get_doc(es: Elasticsearch, doc_id: int) -> dict | None:
    try:
        r = es.search(index=INDEX, body={"query": {"term": {"doc_id": doc_id}}, "size": 1})
        hits = r["hits"]["hits"]
        return hits[0] if hits else None
    except Exception as e:
        print(f"  [error] 获取 doc_id={doc_id} 失败: {e}")
        return None


def main():
    args = parse_args()
    doc_ids = [int(x) for x in args.doc_ids.split(",")] if args.doc_ids else DOC_IDS

    local = Elasticsearch(args.local_host, basic_auth=(args.local_user, args.local_pass))
    target = Elasticsearch(args.target_host, basic_auth=(args.target_user, args.target_pass))

    print(f"== 本地: {args.local_host} ==")
    print(f"  ping: {local.ping()}")
    print(f"== 目标: {args.target_host} ==")
    print(f"  ping: {target.ping()}")
    print(f"== 待迁移 doc 数: {len(doc_ids)} ==\n")

    if not local.ping() or not target.ping():
        print("ES 连接失败,中止")
        sys.exit(1)

    # 确认目标 index 存在(没有就用本地的 mapping 创建)
    if not target.indices.exists(index=INDEX):
        local_mapping = local.indices.get_mapping(index=INDEX)[INDEX]["mappings"]
        local_settings = local.indices.get_settings(index=INDEX)[INDEX]["settings"]["index"]
        # 去掉自动管理字段
        for k in ("creation_date", "uuid", "version", "provided_name", "history"):
            local_settings.pop(k, None)
        print(f"  目标缺 index {INDEX},按本地 mapping 创建...")
        if not args.dry_run:
            target.indices.create(index=INDEX, mappings=local_mapping, settings={"index": local_settings})
            print(f"  ✅ 创建完成")
        else:
            print(f"  [dry-run] 跳过创建")

    actions = []
    for did in doc_ids:
        local_hit = get_doc(local, did)
        target_hit = get_doc(target, did)
        local_has_graph = local_hit and local_hit["_source"].get("has_graph", False)
        target_has_graph = target_hit and target_hit["_source"].get("has_graph", False)

        flag_l = "✅" if local_has_graph else "❌"
        flag_t = "✅" if target_has_graph else "❌"
        fn = (local_hit or {}).get("_source", {}).get("filename", "(N/A)")[:40]
        print(f"  doc_id={did:<22} local={flag_l} target={flag_t}  {fn}")

        if not local_hit:
            print(f"    [skip] 本地不存在")
            continue
        if not local_has_graph:
            print(f"    [skip] 本地无 has_graph=True,跳过")
            continue

        actions.append({
            "_op_type": "index",
            "_index": INDEX,
            "_id": local_hit["_id"],
            "_source": local_hit["_source"],
        })

    print(f"\n== 待写入目标的 docs: {len(actions)} ==")
    if args.dry_run:
        print("[dry-run] 不实际写入")
        return

    if not actions:
        print("无需迁移")
        return

    success, errors = helpers.bulk(target, actions, raise_on_error=False, refresh=True)
    print(f"\n== 迁移完成: success={success} errors={len(errors) if isinstance(errors,list) else errors} ==")
    if isinstance(errors, list):
        for e in errors[:5]:
            print(json.dumps(e, ensure_ascii=False)[:300])


if __name__ == "__main__":
    main()
