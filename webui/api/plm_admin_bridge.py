"""Client-side authorization helpers for brokered PLM administration."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
import uuid
from typing import Any

_GRANT_VERSION = 1
_GRANT_TTL_SECONDS = 30
_ACTIONS = {"guidelines", "unlock"}


class PLMAdminBridgeError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def _read_secret() -> bytes:
    value = os.getenv("PLM_ADMIN_CLIENT_GRANT_KEY", "").strip()
    path = os.getenv("PLM_ADMIN_CLIENT_GRANT_KEY_FILE", "").strip()
    if value and path:
        raise PLMAdminBridgeError("PLM admin bridge key is misconfigured", 503)
    if path:
        try:
            value = open(path, encoding="utf-8").read().strip()
        except OSError as exc:
            raise PLMAdminBridgeError("PLM admin bridge is unavailable", 503) from exc
    if len(value) < 32:
        raise PLMAdminBridgeError("PLM admin bridge is unavailable", 503)
    return value.encode("utf-8")


def _is_admin_for_token(token: str) -> bool:
    from api.auth import get_django_base_urls

    for base in get_django_base_urls():
        request = urllib.request.Request(
            f"{base}/api/access/me/",
            headers={"Authorization": f"Token {token}", "Host": "localhost"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status != 200:
                    continue
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            continue
        access = payload.get("access", {}) if isinstance(payload, dict) else {}
        admin = access.get("access_admin", {}) if isinstance(access, dict) else {}
        if isinstance(admin, dict) and any(
            admin.get(key)
            for key in ("visible", "is_group_admin", "is_company_admin", "is_superuser")
        ):
            return True
        if isinstance(access, dict) and access.get("is_group_admin"):
            return True
        return False
    return False


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encode_grant(payload: dict[str, Any], key: bytes) -> str:
    raw = _canonical(payload)
    signature = hmac.new(key, raw, hashlib.sha256).digest()
    return "{}.{}".format(
        base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii"),
        base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
    )


def build_admin_grant(handler, action: str) -> dict[str, str]:
    """Verify the caller against BizBackend and mint an action-bound grant."""
    if action not in _ACTIONS:
        raise PLMAdminBridgeError("Unsupported PLM admin operation", 400)
    from api.auth import (
        _get_django_token_from_request,
        resolve_django_user_identity,
        verify_django_token,
    )

    token = _get_django_token_from_request(handler)
    if not token or not verify_django_token(token):
        raise PLMAdminBridgeError("Authentication required", 401)
    identity = resolve_django_user_identity(token)
    if not identity:
        raise PLMAdminBridgeError("Authentication required", 401)
    if not _is_admin_for_token(token):
        raise PLMAdminBridgeError("Administrator access is required", 403)
    now = int(time.time())
    payload = {
        "version": _GRANT_VERSION,
        "action": action,
        "identity": identity,
        "scope": "yiyong",
        "issued_at": now,
        "expires_at": now + _GRANT_TTL_SECONDS,
        "request_id": uuid.uuid4().hex,
    }
    return {"request_id": payload["request_id"], "grant": _encode_grant(payload, _read_secret())}