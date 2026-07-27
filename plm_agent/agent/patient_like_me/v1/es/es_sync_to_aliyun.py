#!/usr/bin/env python3
"""
Sync PLM ES indices from local to Aliyun ES (direct connection, requires VPN).

Usage:
  python es_sync_to_aliyun.py
"""
import sys
import time
from elasticsearch import Elasticsearch, helpers

PLM_INDEX = "plm_guidelines"
PLM_CHUNK_INDEX = "plm_guideline_chunks"

LOCAL = {
    "host": "http://localhost:6002",
    "user": "elastic",
    "password": "elasticnoah",
}

REMOTE = {
    "host": "http://172.188.121.85:6002",
    "user": "elastic",
    "password": "elasticnoah",
}


def make_client(cfg):
    return Elasticsearch(
        hosts=cfg["host"],
        basic_auth=(cfg["user"], cfg["password"]),
        request_timeout=120,
        retry_on_timeout=True,
        max_retries=5,
    )


def check_connection(es, name):
    try:
        info = es.info()
        print(f"  [{name}] connected — version {info['version']['number']}")
        return True
    except Exception as e:
        print(f"  [{name}] FAILED: {e}")
        return False


def sync_index(src, dst, index_name):
    print(f"\n--- Syncing {index_name} ---")

    if not src.indices.exists(index=index_name):
        print(f"  Source index '{index_name}' does not exist, skipping")
        return

    src_count = src.count(index=index_name)["count"]
    print(f"  Source: {src_count} docs")

    batch_size = 50 if index_name == PLM_INDEX else 200
    total = 0
    errors_total = 0
    error_shown = False
    t0 = time.time()

    actions = []
    for hit in helpers.scan(src, index=index_name, scroll="10m", size=batch_size):
        actions.append({
            "_index": index_name,
            "_id": hit["_id"],
            "_source": hit["_source"],
        })

        if len(actions) >= batch_size:
            ok, errs = helpers.bulk(dst, actions, chunk_size=batch_size, raise_on_error=False)
            total += ok
            if isinstance(errs, list):
                errors_total += len(errs)
                if len(errs) > 0 and not error_shown:
                    print(f"\n  First error: {errs[0]}")
                    error_shown = True
            elapsed = time.time() - t0
            print(f"  {total}/{src_count} synced ({elapsed:.0f}s)", end="\r", flush=True)
            actions = []

    if actions:
        ok, errs = helpers.bulk(dst, actions, chunk_size=batch_size, raise_on_error=False)
        total += ok
        if isinstance(errs, list):
            errors_total += len(errs)
            if len(errs) > 0 and not error_shown:
                print(f"\n  First error: {errs[0]}")
                error_shown = True

    elapsed = time.time() - t0
    print(f"  {total}/{src_count} synced, {errors_total} errors ({elapsed:.1f}s)      ")

    try:
        dst.indices.refresh(index=index_name)
        final = dst.count(index=index_name)["count"]
        print(f"  Remote final count: {final}")
    except Exception:
        print(f"  Sync complete (cannot verify remote count — permission limited)")


def main():
    print("Connecting...")
    src = make_client(LOCAL)
    dst = make_client(REMOTE)

    if not check_connection(src, "local"):
        sys.exit(1)
    if not check_connection(dst, "aliyun"):
        print("\n  Make sure VPN is connected!")
        sys.exit(1)

    sync_index(src, dst, PLM_INDEX)
    sync_index(src, dst, PLM_CHUNK_INDEX)

    print("\nAll done.")


if __name__ == "__main__":
    main()
