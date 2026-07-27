"""Authenticated same-origin bridge for the cloud PLM report endpoints."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


_REPORT_PATH = re.compile(r"^/plm/report/[A-Za-z0-9_-]{1,128}(?:/download)?$")
_STREAM_PATH = re.compile(r"^/plm/report_stream/[A-Za-z0-9_-]{1,128}$")
_MAX_BODY_BYTES = 2 * 1024 * 1024


def _send_json(handler, payload: dict, status: int) -> bool:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _browser_token(handler, parsed, method: str) -> str:
    from api.auth import _get_django_token_from_request, verify_django_token

    token = _get_django_token_from_request(handler)
    if not token and method == "GET":
        token = str(urllib.parse.parse_qs(parsed.query or "").get("token", [""])[0]).strip()
    if not token or not verify_django_token(token):
        return ""
    return token


def _service_token() -> str:
    token_file = os.getenv("HERMES_WEBUI_GATEWAY_API_KEY_FILE", "").strip()
    if not token_file:
        return ""
    try:
        return Path(token_file).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _allowed_path(path: str, method: str) -> bool:
    if method == "POST":
        return path == "/plm_evidence_based"
    return bool(_REPORT_PATH.fullmatch(path) or _STREAM_PATH.fullmatch(path))


def _upstream_url(parsed) -> str:
    base_url = os.getenv("PLM_DIRECT_SERVICE_BASE_URL", "").rstrip("/")
    if not base_url:
        raise RuntimeError("PLM direct gateway is unavailable")
    query = urllib.parse.parse_qsl(parsed.query or "", keep_blank_values=True)
    allowed_query = [(key, value) for key, value in query if key in {"fmt", "title"}]
    suffix = f"?{urllib.parse.urlencode(allowed_query)}" if allowed_query else ""
    return f"{base_url}/plm-query{parsed.path}{suffix}"


def _request_body(handler, method: str) -> bytes:
    if method != "POST":
        return b""
    try:
        size = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise ValueError("Invalid request body") from exc
    if size < 0 or size > _MAX_BODY_BYTES:
        raise ValueError("Request body is too large")
    return handler.rfile.read(size)


def handle_plm_direct_request(handler, parsed, method: str) -> bool:
    """Forward an allowed, user-authenticated PLM report request to the cloud."""
    if not _allowed_path(parsed.path, method):
        return _send_json(handler, {"error": "PLM endpoint not found"}, 404)
    token = _browser_token(handler, parsed, method)
    if not token:
        return _send_json(handler, {"error": "Authentication required"}, 401)
    service_token = _service_token()
    if not service_token:
        return _send_json(handler, {"error": "PLM service is unavailable"}, 503)
    try:
        body = _request_body(handler, method)
        request = urllib.request.Request(
            _upstream_url(parsed),
            data=body if method == "POST" else None,
            headers={
                "Authorization": f"Bearer {service_token}",
                "X-Noah-User-Token": token,
                "Accept": handler.headers.get("Accept", "application/json"),
                **({"Content-Type": handler.headers["Content-Type"]} if method == "POST" and handler.headers.get("Content-Type") else {}),
            },
            method=method,
        )
        response = urllib.request.urlopen(request, timeout=900)
    except ValueError as exc:
        return _send_json(handler, {"error": str(exc)}, 400)
    except urllib.error.HTTPError as exc:
        response = exc
    except (OSError, urllib.error.URLError):
        return _send_json(handler, {"error": "PLM service is unavailable"}, 503)

    handler.send_response(response.status)
    for name in ("Content-Type", "Cache-Control", "Content-Disposition", "X-Accel-Buffering"):
        if value := response.headers.get(name):
            handler.send_header(name, value)
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    while chunk := response.read(16 * 1024):
        handler.wfile.write(chunk)
        handler.wfile.flush()
    response.close()
    return True