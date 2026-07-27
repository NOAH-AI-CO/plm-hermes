# -*- coding: utf-8 -*-
import logging
from typing import Optional

import alibabacloud_oss_v2 as oss

from config import api_config
from utils.core.singleton import Singleton

logger = logging.getLogger(__name__)


class AliyunOSSClientSingleton(Singleton):

    _initialized: bool = False

    _client: oss.Client = None

    @classmethod
    def initialize(cls):
        r"""Initialize aliyun oss client."""
        if cls._initialized:
            return True
        credentials_provider = oss.credentials.StaticCredentialsProvider(
            access_key_id=api_config.ALIYUN_ACCESS_KEY,
            access_key_secret=api_config.ALIYUN_ACCESS_SECRET,
        )

        cfg = oss.config.load_default()
        cfg.credentials_provider = credentials_provider

        cfg.region = api_config.ALIYUN_OSS_REGION
        cfg.endpoint = api_config.ALIYUN_OSS_ENDPOINT

        cls._client = oss.Client(cfg)
        cls._initialized = True

    @classmethod
    def get_client(cls) -> oss.Client:
        if not cls._initialized:
            cls.initialize()
        return cls._client


def upload_template_file(
    file_path: str,
    bucket_name: str,
    object_key: str,
    timeout: str = '7days',
    ) -> str:
    r"""Upload a template file to Aliyun OSS and return the signed url."""
    client = AliyunOSSClientSingleton.get_client()
    key = f"temp{timeout}/{object_key}"
    result = client.put_object_from_file(
        oss.PutObjectRequest(
            bucket=bucket_name,
            key=key,
        ),
        filepath=file_path,
    )
    pre_result = client.presign(
        oss.GetObjectRequest(
            bucket=bucket_name,
            key=key
        )
    )
    return pre_result.url


# ----------------------------------------------------------------------
# Workspace helpers — small JSON state + permanent assets, no lifecycle prefix
# ----------------------------------------------------------------------
#
# These bypass the ``temp{timeout}/`` prefix used by ``upload_template_file``
# (which lives under a lifecycle rule that auto-deletes after N days).
# Workspace data must be permanent, so we write at a stable top-level prefix
# and let the bucket's default retention apply.


def put_object_text(bucket_name: str, key: str, content: str,
                    content_type: str = "application/json") -> None:
    """Synchronously write a text payload to ``bucket/key``. Overwrites on conflict."""
    client = AliyunOSSClientSingleton.get_client()
    client.put_object(
        oss.PutObjectRequest(
            bucket=bucket_name,
            key=key,
            body=content,
            content_type=content_type,
        )
    )


def get_object_text(bucket_name: str, key: str) -> Optional[str]:
    """Synchronously fetch ``bucket/key`` as text. Returns None if absent."""
    client = AliyunOSSClientSingleton.get_client()
    try:
        result = client.get_object(
            oss.GetObjectRequest(bucket=bucket_name, key=key)
        )
    except Exception as e:  # SDK raises a typed error; we treat any 404 as missing
        msg = str(e)
        if "NoSuchKey" in msg or "404" in msg:
            return None
        logger.warning("[OSS] get_object_text failed for %s: %s", key, e)
        raise
    body = getattr(result, "body", None)
    if body is None:
        return None
    # The SDK's body is a stream-like object exposing read().
    try:
        raw = body.read()
    except Exception:
        raw = body
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    if isinstance(raw, str):
        return raw
    return str(raw)


def presign_get(bucket_name: str, key: str) -> str:
    """Return a presigned GET url for a permanent OSS object.

    The SDK's default expiry (1h) is shorter than the 7-day links produced by
    ``upload_template_file``. Callers that want a longer-lived link should
    ``client.presign(..., expires=...)`` directly. For now 1h is enough — the
    front-end can call ``/api/workspace/{tid}/asset/{name}/refresh-url`` to
    re-sign on demand.
    """
    client = AliyunOSSClientSingleton.get_client()
    result = client.presign(
        oss.GetObjectRequest(bucket=bucket_name, key=key)
    )
    return result.url