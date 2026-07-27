"""把本地 ES 中 product_scope='yiyong' 的 plm_guidelines 文档及其
plm_guideline_chunks 全量迁移到远端 ES。不重复 OCR/embedding, 直接搬 _source。

用法:
    cd noah_agent
    python -m agent.patient_like_me.v1.indexing.migrate_yiyong_to_remote \
        --target-host http://172.188.121.85:6002 --target-pass elasticnoah
"""
import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elasticsearch import Elasticsearch, helpers

PLM_INDEX = "plm_guidelines"
PLM_CHUNK_INDEX = "plm_guideline_chunks"
LOCAL_HOST = "http://localhost:6002"


def _es(host, user, pw):
    return Elasticsearch(hosts=host, basic_auth=(user, pw), request_timeout=120,
                         max_retries=5, retry_on_timeout=True)


def _scroll(es, index, query):
    for hit in helpers.scan(es, index=index, query={"query": query}, size=200, preserve_order=False):
        yield hit


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--target-host", required=True)
    p.add_argument("--target-user", default="elastic")
    p.add_argument("--target-pass", required=True)
    p.add_argument("--local-host", default=LOCAL_HOST)
    p.add_argument("--local-user", default="elastic")
    p.add_argument("--local-pass", default="elasticnoah")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    local = _es(args.local_host, args.local_user, args.local_pass)
    target = _es(args.target_host, args.target_user, args.target_pass)

    # 1) 文档
    doc_q = {"term": {"product_scope": "yiyong"}}
    docs = list(_scroll(local, PLM_INDEX, doc_q))
    doc_ids = [d["_id"] for d in docs]
    print(f"本地 yiyong 文档 {len(docs)} 个")

    # 2) 这些文档的 chunks
    chunk_q = {"terms": {"doc_id": [int(i) for i in doc_ids]}} if doc_ids else {"match_none": {}}
    chunks = list(_scroll(local, PLM_CHUNK_INDEX, chunk_q))
    print(f"对应 chunks {len(chunks)} 个")

    if args.dry_run:
        print("[dry-run] 不写远端。")
        return

    def _actions(hits, index):
        for h in hits:
            yield {"_op_type": "index", "_index": index, "_id": h["_id"], "_source": h["_source"]}

    ok, err = helpers.bulk(target.options(request_timeout=180), _actions(docs, PLM_INDEX), raise_on_error=False)
    print(f"写远端文档: ok={ok} err={len(err) if isinstance(err, list) else err}")
    ok2, err2 = helpers.bulk(target.options(request_timeout=180), _actions(chunks, PLM_CHUNK_INDEX), raise_on_error=False)
    print(f"写远端 chunks: ok={ok2} err={len(err2) if isinstance(err2, list) else err2}")

    target.indices.refresh(index=PLM_INDEX)
    target.indices.refresh(index=PLM_CHUNK_INDEX)
    cnt = target.count(index=PLM_INDEX, query=doc_q)["count"]
    print(f"远端 yiyong 文档数(校验): {cnt}")


if __name__ == "__main__":
    main()
