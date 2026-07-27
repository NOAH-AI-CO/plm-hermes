#!/usr/bin/env python3
"""Copy the remote Noah ``guidelines`` index into local Elasticsearch.

The target index must not already exist unless ``--replace`` is provided.
Credentials are read from environment variables to keep secrets out of source.
"""

import argparse
import os
import sys
import time
from typing import Any

from elasticsearch import Elasticsearch, helpers


INDEX_NAME = "guidelines"
DEFAULT_SOURCE_URL = "http://es-cn-28x4g9gay00015rad.elasticsearch.aliyuncs.com:9200"
DEFAULT_TARGET_URL = "http://localhost:6002"


def make_client(url: str, username: str, password: str) -> Elasticsearch:
    return Elasticsearch(
        hosts=[url],
        basic_auth=(username, password),
        request_timeout=120,
        retry_on_timeout=True,
        max_retries=3,
    )


def index_definition(source: Elasticsearch) -> dict[str, Any]:
    source_index = source.indices.get(index=INDEX_NAME)[INDEX_NAME]
    settings = source_index.get("settings", {}).get("index", {})
    allowed_settings = {
        key: value
        for key, value in settings.items()
        if key in {"number_of_shards", "number_of_replicas", "analysis"}
    }
    return {
        "settings": allowed_settings,
        "mappings": source_index.get("mappings", {}),
    }


def source_index_settings(source: Elasticsearch) -> dict[str, str]:
    settings = source.indices.get(index=INDEX_NAME)[INDEX_NAME].get("settings", {}).get("index", {})
    return {
        "number_of_replicas": settings.get("number_of_replicas", "1"),
        "refresh_interval": settings.get("refresh_interval", "1s"),
    }


def document_actions(source: Elasticsearch, batch_size: int):
    for hit in helpers.scan(
        source,
        index=INDEX_NAME,
        query={"query": {"match_all": {}}},
        scroll="10m",
        size=batch_size,
        preserve_order=False,
    ):
        yield {
            "_op_type": "index",
            "_index": INDEX_NAME,
            "_id": hit["_id"],
            "_source": hit["_source"],
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", default=os.getenv("GUIDELINES_SOURCE_URL", DEFAULT_SOURCE_URL))
    parser.add_argument("--target-url", default=os.getenv("GUIDELINES_TARGET_URL", DEFAULT_TARGET_URL))
    parser.add_argument("--source-user", default=os.getenv("GUIDELINES_SOURCE_USER", "noah_rag"))
    parser.add_argument("--source-password", default=os.getenv("GUIDELINES_SOURCE_PASSWORD"))
    parser.add_argument("--target-user", default=os.getenv("GUIDELINES_TARGET_USER", "elastic"))
    parser.add_argument("--target-password", default=os.getenv("GUIDELINES_TARGET_PASSWORD"))
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--replace", action="store_true", help="delete an existing local guidelines index")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.source_password or not args.target_password:
        print("Set GUIDELINES_SOURCE_PASSWORD and GUIDELINES_TARGET_PASSWORD before running.", file=sys.stderr)
        return 2

    source = make_client(args.source_url, args.source_user, args.source_password)
    target = make_client(args.target_url, args.target_user, args.target_password)

    if not source.indices.exists(index=INDEX_NAME):
        print(f"Source index {INDEX_NAME!r} does not exist.", file=sys.stderr)
        return 1

    if target.indices.exists(index=INDEX_NAME):
        if not args.replace:
            print(f"Target index {INDEX_NAME!r} already exists; rerun with --replace to overwrite it.", file=sys.stderr)
            return 1
        target.indices.delete(index=INDEX_NAME)

    source_count = source.count(index=INDEX_NAME)["count"]
    restore_settings = source_index_settings(source)
    target.indices.create(index=INDEX_NAME, **index_definition(source))
    target.indices.put_settings(
        index=INDEX_NAME,
        settings={"index": {"number_of_replicas": "0", "refresh_interval": "-1"}},
    )
    print(f"Created local {INDEX_NAME!r}; copying {source_count} documents.")

    started = time.monotonic()
    copied = 0
    for ok, item in helpers.streaming_bulk(
        target,
        document_actions(source, args.batch_size),
        chunk_size=args.batch_size,
        raise_on_error=False,
        raise_on_exception=False,
    ):
        if not ok:
            print(f"Bulk indexing failed: {item}", file=sys.stderr)
            return 1
        copied += 1
        if copied % args.batch_size == 0 or copied == source_count:
            print(f"Copied {copied}/{source_count} documents", end="\r", flush=True)

    target.indices.put_settings(index=INDEX_NAME, settings={"index": restore_settings})
    target.indices.refresh(index=INDEX_NAME)
    target_count = target.count(index=INDEX_NAME)["count"]
    elapsed = time.monotonic() - started
    print(f"Copied {copied}/{source_count} documents in {elapsed:.1f}s")
    if target_count != source_count:
        print(f"Count mismatch: source={source_count}, local={target_count}", file=sys.stderr)
        return 1

    print(f"Verified local {INDEX_NAME!r}: {target_count} documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())