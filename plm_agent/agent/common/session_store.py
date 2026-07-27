"""
PLM / sahzu 追问会话存储（Redis-backed, 可选）。

设计目标
========
1. **可选接入**：前端不传 ``thread_id`` 时，followup 行为完全和现在一样（无状态）；
   只有当前端带上 ``thread_id`` 时，后端才会从 Redis 加载并合并历史。
2. **优雅降级**：Redis 不可达 / 数据损坏 / 解析失败时，全部静默返回 None，不影响主流程。
3. **轻量**：每个 thread 一个 key，value 是一个小 JSON（report_text + history）；
   TTL 7 天自动过期，无需手动清理。
4. **PLM/sahzu 共用**：通过 ``namespace`` 参数区分（``plm`` / ``sahzu``），避免互串。

Key 格式
========
- ``{namespace}:chat:{thread_id}``，例如 ``plm:chat:abc123`` / ``sahzu:chat:xyz789``。

Value 格式（JSON）
==================
{
    "report_text": "完整的循证报告文本（首次写入后稳定不变）",
    "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...],
    "updated_at": 1717225200.123
}

API
===
- ``load_session(namespace, thread_id) -> dict | None``
- ``save_session(namespace, thread_id, *, report_text, history) -> bool``
- ``delete_session(namespace, thread_id) -> bool``  （前端"重新开始"想主动清，可调；否则等 TTL）

实现细节
========
- 同步 Redis 客户端 + ``asyncio.to_thread`` 包裹，避免阻塞事件循环。
- 复用 ``utils/redis_client.py`` 已有的全局 ``engine``。
- 任何异常都被吞掉，记录 warning，不抛出。

NOTE: 此模块由 PLM 和 sahzu 共用。修改时务必跑两端的回归。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from utils.redis_client import engine as _redis_engine

logger = logging.getLogger(__name__)

# ─── Config ───
_SESSION_TTL_SECONDS = 7 * 24 * 3600          # 7 天
_MAX_REPORT_BYTES = 200 * 1024                # 200KB，超过则不存（防止超大报告把 Redis 撑爆）
_MAX_HISTORY_TURNS = 40                       # 40 个 user/assistant 对 = 20 轮，足够
# Redis 未上线时整套 session_store 都未启用，因此 sahzu 已合并到 PLM 后，
# namespace 可直接收敛为 "plm"。如未来要保留 sahzu 历史的 follow-up session
# 兼容（例如灰度切换 / 多租户场景），再把 "sahzu" 加回来。
_ALLOWED_NAMESPACES = {"plm"}


def _key(namespace: str, thread_id: str) -> str:
    return f"{namespace}:chat:{thread_id}"


def _validate(namespace: str, thread_id: str) -> bool:
    if namespace not in _ALLOWED_NAMESPACES:
        logger.warning("[session_store] invalid namespace=%r", namespace)
        return False
    if not thread_id or not isinstance(thread_id, str):
        return False
    # 长度限制 + 限制字符集，防注入和奇怪 key
    if len(thread_id) > 128:
        return False
    return True


# ────────────────────── Sync Redis ops (wrapped in asyncio.to_thread) ──────────────────────

def _sync_load(key: str) -> Optional[dict]:
    if _redis_engine is None:
        return None
    try:
        raw = _redis_engine.get(key)
    except Exception as e:
        logger.warning("[session_store] redis GET failed key=%s: %s", key, e)
        return None
    if not raw:
        return None
    try:
        doc = json.loads(raw)
        if not isinstance(doc, dict):
            return None
        return doc
    except Exception as e:
        logger.warning("[session_store] JSON decode failed key=%s: %s", key, e)
        return None


def _sync_save(key: str, payload: dict, ttl: int) -> bool:
    if _redis_engine is None:
        return False
    try:
        raw = json.dumps(payload, ensure_ascii=False)
        _redis_engine.setex(key, ttl, raw)
        return True
    except Exception as e:
        logger.warning("[session_store] redis SETEX failed key=%s: %s", key, e)
        return False


def _sync_delete(key: str) -> bool:
    if _redis_engine is None:
        return False
    try:
        _redis_engine.delete(key)
        return True
    except Exception as e:
        logger.warning("[session_store] redis DELETE failed key=%s: %s", key, e)
        return False


# ────────────────────── 报告持久化(Redis, 让刷新/重启能重看旧报告) ──────────────────────
_REPORT_TTL_SECONDS = 30 * 24 * 3600            # 报告留 30 天
_MAX_REPORT_STORE_BYTES = 3 * 1024 * 1024       # 3MB(含药物/综合全量, 给足)


def _report_key(report_id: str) -> str:
    return f"plm:report:{report_id}"


async def save_report(report_id: str, data: dict) -> bool:
    """把整份报告 dict 持久化进 Redis。Redis 不可用/超大时静默失败(不影响主流程)。"""
    if not report_id or not isinstance(data, dict):
        return False
    try:
        if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > _MAX_REPORT_STORE_BYTES:
            logger.warning("[session_store] report %s too large, skip persist", report_id)
            return False
    except Exception:
        return False
    return await asyncio.to_thread(_sync_save, _report_key(report_id), data, _REPORT_TTL_SECONDS)


async def load_report(report_id: str) -> Optional[dict]:
    """从 Redis 取回持久化的报告 dict, 没有返回 None。"""
    if not report_id:
        return None
    return await asyncio.to_thread(_sync_load, _report_key(report_id))


# ────────────────────── 指南候选持久化(compact 模式: gid→候选, 刷新/重启后卡片仍可渲染) ──────────────────────
_GUIDELINES_TTL_SECONDS = 30 * 24 * 3600        # 与报告同寿命(同一会话卡片/报告一致)
_MAX_GUIDELINES_STORE_BYTES = 1 * 1024 * 1024   # 候选含 summary/patient_info, 1MB 足够


def _guidelines_key(gid: str) -> str:
    return f"plm:guidelines:{gid}"


async def save_guidelines(gid: str, data: dict) -> bool:
    """把 compact 候选 dict 持久化进 Redis。Redis 不可用/超大时静默失败(不影响主流程)。"""
    if not gid or not isinstance(data, dict):
        return False
    try:
        if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > _MAX_GUIDELINES_STORE_BYTES:
            logger.warning("[session_store] guidelines %s too large, skip persist", gid)
            return False
    except Exception:
        return False
    return await asyncio.to_thread(_sync_save, _guidelines_key(gid), data, _GUIDELINES_TTL_SECONDS)


async def load_guidelines(gid: str) -> Optional[dict]:
    """从 Redis 取回持久化的候选 dict, 没有返回 None。"""
    if not gid:
        return None
    return await asyncio.to_thread(_sync_load, _guidelines_key(gid))


# ────────────────────── Public async API ──────────────────────

async def load_session(namespace: str, thread_id: str) -> Optional[dict]:
    """加载会话。返回 ``{report_text, history, updated_at}`` 或 None。

    优雅降级：thread_id 不合法 / Redis 挂 / 数据损坏 → 全部返回 None。
    """
    if not _validate(namespace, thread_id):
        return None
    return await asyncio.to_thread(_sync_load, _key(namespace, thread_id))


async def save_session(
    namespace: str,
    thread_id: str,
    *,
    report_text: str,
    history: list[dict],
) -> bool:
    """保存会话。返回是否成功。

    报告超过 ``_MAX_REPORT_BYTES`` 时不存（返回 False）；history 截断到最近 _MAX_HISTORY_TURNS 条。
    """
    if not _validate(namespace, thread_id):
        return False

    report_text = (report_text or "")
    if len(report_text.encode("utf-8")) > _MAX_REPORT_BYTES:
        logger.warning(
            "[session_store] report too large (%d bytes), skip save for %s:%s",
            len(report_text.encode("utf-8")), namespace, thread_id,
        )
        return False

    if not isinstance(history, list):
        history = []
    # 保留最近 N 条，预防 Redis value 过大
    history = history[-_MAX_HISTORY_TURNS:]

    payload = {
        "report_text": report_text,
        "history": history,
        "updated_at": time.time(),
    }
    return await asyncio.to_thread(_sync_save, _key(namespace, thread_id), payload, _SESSION_TTL_SECONDS)


async def delete_session(namespace: str, thread_id: str) -> bool:
    """主动删除会话（前端"重新开始"可调，否则等 TTL 自动清理）。"""
    if not _validate(namespace, thread_id):
        return False
    return await asyncio.to_thread(_sync_delete, _key(namespace, thread_id))
