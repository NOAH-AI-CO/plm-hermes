from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class VerifyConfig:
    backend_base_url: str
    noah_base_url: str
    token: str
    owner_id: str
    file_path: str
    poll_interval_seconds: float
    max_wait_seconds: int
    request_timeout_seconds: float
    force_reindex: bool


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Token {token}"}


def _upload_policy_document(config: VerifyConfig) -> tuple[str, str]:
    upload_url = f"{config.backend_base_url.rstrip('/')}/api/ethics-policy/upload/"
    with open(config.file_path, "rb") as file_stream:
        response = requests.post(
            upload_url,
            headers=_auth_headers(config.token),
            files={"files": (os.path.basename(config.file_path), file_stream, "application/octet-stream")},
            timeout=config.request_timeout_seconds,
        )
    response.raise_for_status()
    payload = response.json()
    uploaded = payload.get("uploaded") or []
    if not uploaded:
        raise RuntimeError(f"upload returned no uploaded docs: {json.dumps(payload, ensure_ascii=False)}")
    first = uploaded[0]
    doc_id = str(first.get("id") or "").strip()
    doc_name = str(first.get("name") or "").strip()
    if not doc_id:
        raise RuntimeError(f"upload response missing doc id: {json.dumps(payload, ensure_ascii=False)}")
    return doc_id, doc_name


def _fetch_policy_item(config: VerifyConfig, doc_id: str) -> dict[str, Any]:
    list_url = f"{config.backend_base_url.rstrip('/')}/api/ethics-policy/list/"
    response = requests.get(
        list_url,
        headers=_auth_headers(config.token),
        timeout=config.request_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items") or []
    for item in items:
        if str(item.get("id") or "").strip() == doc_id:
            return item
    raise RuntimeError(f"document {doc_id} not found in policy list")


def _poll_until_ready(config: VerifyConfig, doc_id: str) -> dict[str, Any]:
    deadline = time.time() + config.max_wait_seconds
    last_item: dict[str, Any] | None = None
    while time.time() < deadline:
        item = _fetch_policy_item(config, doc_id)
        last_item = item
        if str(item.get("index_status") or "").strip().lower() == "ready":
            return item
        if str(item.get("index_status") or "").strip().lower() == "failed":
            return item
        time.sleep(config.poll_interval_seconds)
    if last_item is None:
        raise RuntimeError("polling timed out before any policy item was fetched")
    return last_item


def _trigger_noah_reindex(config: VerifyConfig, doc_id: str) -> None:
    reindex_url = f"{config.noah_base_url.rstrip('/')}/ethics/policy/index"
    response = requests.post(
        reindex_url,
        json={
            "owner_id": config.owner_id,
            "attachments": [{"doc_id": doc_id, "scope": "user"}],
        },
        timeout=config.request_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    if str(payload.get("status") or "").strip().lower() != "accepted":
        raise RuntimeError(f"reindex request not accepted: {json.dumps(payload, ensure_ascii=False)}")


def _verify_metadata_fields(item: dict[str, Any]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    issuer = str(item.get("issuer") or "").strip()
    policy_type = str(item.get("policy_type") or "").strip()
    sort_meta = item.get("sort_meta") or {}
    publication_date = str(sort_meta.get("publication_date") or "").strip()

    if not publication_date:
        issues.append("publication_date is empty")
    if not policy_type:
        issues.append("policy_type is empty")
    if not issuer and not publication_date:
        issues.append("both issuer and publication_date are empty")
    return len(issues) == 0, issues


def _verify_noah_search(config: VerifyConfig, query_text: str, expected_doc_id: str) -> tuple[bool, dict[str, Any]]:
    search_url = f"{config.noah_base_url.rstrip('/')}/ethics/policy/search"
    response = requests.post(
        search_url,
        json={
            "owner_id": config.owner_id,
            "query": query_text,
            "top_k": 5,
        },
        timeout=config.request_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    hits = payload.get("hits") or []
    found = False
    for hit in hits:
        if str(hit.get("doc_id") or "").strip() == expected_doc_id:
            found = True
            break
    return found, payload


def run_verify(config: VerifyConfig) -> int:
    doc_id, doc_name = _upload_policy_document(config)
    print(f"[E2E] uploaded doc_id={doc_id} name={doc_name}")
    if config.force_reindex:
        _trigger_noah_reindex(config, doc_id=doc_id)
        print(f"[E2E] reindex requested for doc_id={doc_id}")

    final_item = _poll_until_ready(config, doc_id)
    status_value = str(final_item.get("index_status") or "").strip().lower()
    print(f"[E2E] final index_status={status_value}")
    if status_value != "ready":
        print(json.dumps({"error": "indexing did not reach ready", "item": final_item}, ensure_ascii=False, indent=2))
        return 2

    ok_meta, meta_issues = _verify_metadata_fields(final_item)
    if not ok_meta:
        print(json.dumps({"error": "metadata extraction incomplete", "issues": meta_issues, "item": final_item}, ensure_ascii=False, indent=2))
        return 3

    query_text = os.path.splitext(doc_name)[0][:64] or "ethics policy"
    found, search_payload = _verify_noah_search(config, query_text=query_text, expected_doc_id=doc_id)
    if not found:
        print(json.dumps({"error": "doc not found in noah search hits", "search": search_payload}, ensure_ascii=False, indent=2))
        return 4

    summary = {
        "status": "passed",
        "doc_id": doc_id,
        "doc_name": doc_name,
        "index_status": final_item.get("index_status"),
        "issuer": final_item.get("issuer"),
        "publication_date": (final_item.get("sort_meta") or {}).get("publication_date"),
        "policy_type": final_item.get("policy_type"),
        "search_query": query_text,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str]) -> VerifyConfig:
    parser = argparse.ArgumentParser(description="E2E verify policy metadata extraction + indexing flow.")
    parser.add_argument("--backend-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--noah-base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--token", required=True)
    parser.add_argument("--owner-id", required=True)
    parser.add_argument("--file-path", required=True)
    parser.add_argument("--poll-interval-seconds", type=float, default=3.0)
    parser.add_argument("--max-wait-seconds", type=int, default=180)
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--force-reindex", action="store_true")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.file_path):
        raise FileNotFoundError(f"file not found: {args.file_path}")

    return VerifyConfig(
        backend_base_url=str(args.backend_base_url),
        noah_base_url=str(args.noah_base_url),
        token=str(args.token),
        owner_id=str(args.owner_id),
        file_path=str(args.file_path),
        poll_interval_seconds=float(args.poll_interval_seconds),
        max_wait_seconds=int(args.max_wait_seconds),
        request_timeout_seconds=float(args.request_timeout_seconds),
        force_reindex=bool(args.force_reindex),
    )


if __name__ == "__main__":
    try:
        config = parse_args(sys.argv[1:])
        raise SystemExit(run_verify(config))
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        raise
