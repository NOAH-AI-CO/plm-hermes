#!/usr/bin/env python3
"""
Export / Import PLM ES indices between environments.

Usage:
  # Export from local ES to JSON files:
  python es_migrate.py export --host http://localhost:6002 --user elastic --password elasticnoah

  # Import into target ES from JSON files:
  python es_migrate.py import --host http://TARGET_ES:9200 --user USER --password PASS

Files produced: plm_guidelines.json, plm_guideline_chunks.json (in current directory)
"""
import argparse
import json
import sys
from elasticsearch import Elasticsearch, helpers

PLM_INDEX = "plm_guidelines"
PLM_CHUNK_INDEX = "plm_guideline_chunks"


def get_client(host, user, password):
    return Elasticsearch(
        hosts=host,
        basic_auth=(user, password),
        request_timeout=60,
        retry_on_timeout=True,
        max_retries=3,
    )


def export_index(es, index_name, output_file):
    if not es.indices.exists(index=index_name):
        print(f"  SKIP: index '{index_name}' does not exist")
        return 0

    docs = []
    for hit in helpers.scan(es, index=index_name, scroll="5m", size=200):
        docs.append({
            "_id": hit["_id"],
            "_source": hit["_source"],
        })

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False)

    print(f"  {index_name} -> {output_file} ({len(docs)} docs, {len(open(output_file,'rb').read()) / 1024 / 1024:.1f} MB)")
    return len(docs)


def import_index(es, index_name, input_file):
    with open(input_file, "r", encoding="utf-8") as f:
        docs = json.load(f)

    if not docs:
        print(f"  SKIP: {input_file} is empty")
        return 0

    # Ensure index exists with correct mappings
    if not es.indices.exists(index=index_name):
        from plm_index import ensure_plm_index, ensure_plm_chunk_index
        if index_name == PLM_INDEX:
            ensure_plm_index()
        else:
            ensure_plm_chunk_index()
        print(f"  Created index '{index_name}'")

    actions = []
    for doc in docs:
        actions.append({
            "_index": index_name,
            "_id": doc["_id"],
            "_source": doc["_source"],
        })

    success, errors = helpers.bulk(es, actions, chunk_size=100, raise_on_error=False)
    failed = len(errors) if isinstance(errors, list) else 0
    print(f"  {input_file} -> {index_name} ({success} ok, {failed} failed)")
    if failed:
        for e in (errors[:5] if isinstance(errors, list) else []):
            print(f"    ERROR: {e}")
    return success


def cmd_export(args):
    es = get_client(args.host, args.user, args.password)
    print(f"Exporting from {args.host}")
    export_index(es, PLM_INDEX, "plm_guidelines.json")
    export_index(es, PLM_CHUNK_INDEX, "plm_guideline_chunks.json")
    print("Done. Transfer these files to the target server, then run: python es_migrate.py import ...")


def cmd_import(args):
    es = get_client(args.host, args.user, args.password)
    print(f"Importing to {args.host}")
    import_index(es, PLM_INDEX, "plm_guidelines.json")
    import_index(es, PLM_CHUNK_INDEX, "plm_guideline_chunks.json")
    print("Done.")


def main():
    parser = argparse.ArgumentParser(description="PLM ES index migration tool")
    sub = parser.add_subparsers(dest="cmd")

    for name, fn in [("export", cmd_export), ("import", cmd_import)]:
        p = sub.add_parser(name)
        p.add_argument("--host", required=True)
        p.add_argument("--user", default="elastic")
        p.add_argument("--password", required=True)
        p.set_defaults(func=fn)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
