"""PLM 主报告流式任务的 Redis-backed 缓冲层。

设计目标
========
解耦"workflow 跑"和"前端 SSE 连接"：
  workflow 边跑边把事件 append 到 Redis Stream;
  任意时刻前端发起 GET /plm_evidence_based/stream/{task_id}/, 后端
  先 XRANGE 把已生成的全部 catch-up, 再 XREAD BLOCK 监听后续事件, 直到读到
  sentinel (event=_done) 关流。

这样前端刷新 / 关页面 / 跨设备登录都能"接进来看", 跟 DeepSeek/ChatGPT
的体验一致。

Key 格式
========
  plm:stream:{task_id}            ← Redis Stream, 每条事件一条 entry
  plm:stream:{task_id}:meta       ← Hash, 记录任务的元信息 (started_at, status)

Entry 格式 (Stream)
===================
  XADD plm:stream:{task_id} *  event <event_name>  payload <json_string>

每个 entry 一对 field:
  - event:   字符串, 例如 "section_chunk", "result", "_done"
  - payload: JSON 字符串

TTL
===
  Stream key TTL = 7 天 (跟主报告 task 历史保持一致)

API
===
  write_event(task_id, event_name, payload)        — workflow 写入一条
  read_stream(task_id, last_id="0")                — 异步迭代: catch-up + tail
  cleanup_stream(task_id)                          — 任务彻底结束后主动清 (可选)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator, Optional

from utils.redis_client import engine as _redis_engine

# 单独建一个不带 socket_timeout 的 Redis client 给 XREAD BLOCK 用.
# utils/redis_client.py 默认 socket_timeout=5s, 但我们要 XREAD BLOCK 30s,
# 5s socket timeout 会让 BLOCK 直接抛 "Timeout reading from socket".
# 这里复用同样的连接信息, 但把 socket_timeout 设成 None (无限).
import redis as _redis_lib
from config import settings as _config_settings

_stream_redis_engine = _redis_lib.Redis(
    host=_config_settings.REDIS_HOST,
    port=_config_settings.REDIS_PORT,
    db=_config_settings.REDIS_ACTIVE_TASK_DB,
    decode_responses=True,
    socket_timeout=None,           # XREAD BLOCK 不能受 socket_timeout 限制
    socket_connect_timeout=5,
    socket_keepalive=True,
    health_check_interval=30,
)

logger = logging.getLogger(__name__)

_STREAM_TTL_SECONDS = 7 * 24 * 3600   # 7 天
_SENTINEL_EVENT = "_done"             # 任务结束标记
_BLOCK_MS = 30000                     # XREAD BLOCK 30s, 之后周期性检查 stream 是否还活着

def _stream_key(task_id: str) -> str:
    return f"plm:stream:{task_id}"


# ────────────────────── Write 侧 (workflow → Redis) ──────────────────────

def write_event(task_id: str, event_name: str, payload: dict | None) -> None:
    """同步写一条事件到 Redis Stream.

    workflow 内部 emit 是同步函数, 这里也保持同步 (Redis xadd 调用很轻量, ~0.1ms).
    优雅降级: Redis 不可达时, log warning + 返回, 不抛出, 不影响主流程.
    """
    if _redis_engine is None or not task_id:
        return
    try:
        raw_payload = json.dumps(payload or {}, ensure_ascii=False)
        key = _stream_key(task_id)
        _redis_engine.xadd(
            key,
            {"event": event_name, "payload": raw_payload},
        )
        # 每次 xadd 都 expire 一下, 保证 stream 在最后一条事件后 7 天过期
        _redis_engine.expire(key, _STREAM_TTL_SECONDS)
    except Exception as e:
        logger.warning("[stream_buffer] xadd failed task_id=%s event=%s: %s",
                       task_id, event_name, e)


def write_sentinel(task_id: str) -> None:
    """workflow 跑完 (含 error) 后调一次, 写入 sentinel 让 read_stream 退出 loop."""
    write_event(task_id, _SENTINEL_EVENT, {})


# ────────────────────── Read 侧 (SSE tail → 前端) ──────────────────────

async def read_stream(
    task_id: str,
    last_id: str = "0-0",
    *,
    idle_timeout_seconds: int = 600,
) -> AsyncIterator[dict]:
    """异步迭代器: 从 Redis Stream 读事件, 一直到 sentinel 或 idle_timeout.

    用法:
        async for entry in read_stream(task_id):
            event = entry["event"]   # 字符串, 例如 "section_chunk"
            payload = entry["payload"]  # 已解析的 dict (json.loads 过)
            yield f"data: {...}\n\n"

    参数:
      task_id              — workflow 写入时用的 task_id
      last_id              — 从哪条 entry 之后开始读. "0-0" = 从头读 (catch-up + tail).
                             如果客户端断线后想从断点续接, 可以传上一次最后看到的 entry id.
      idle_timeout_seconds — 没新事件且没 sentinel 时, 这么久没动静就退出 loop.
                             默认 10 分钟; 任务最长 15 分钟, 给点余量.

    优雅降级:
      - Redis 不可达 → 直接 return (空迭代)
      - Stream 不存在 (key 已过期 / 没人写) → 空迭代退出
    """
    if _stream_redis_engine is None or not task_id:
        return

    key = _stream_key(task_id)
    cursor = last_id
    last_activity_at = time.time()

    while True:
        # 1) XRANGE: 一次性把 cursor 之后已经存在的事件全捞 (catch-up)
        #    第一轮迭代用 "(cursor" 排除 cursor 本身; 后续每轮 cursor 已是上次最后一条
        try:
            entries = await asyncio.to_thread(
                _stream_redis_engine.xrange,
                key,
                min=f"({cursor}" if cursor and cursor != "0-0" else cursor,
                max="+",
                count=200,
            )
        except Exception as e:
            logger.warning("[stream_buffer] xrange failed task_id=%s: %s", task_id, e)
            return

        if entries:
            last_activity_at = time.time()
            for entry_id, fields in entries:
                cursor = entry_id
                parsed = _parse_entry(fields)
                if parsed is None:
                    continue
                yield parsed
                if parsed["event"] == _SENTINEL_EVENT:
                    # 任务正常结束, 退出 loop
                    return
            # 还有更多 catch-up 待捞 (上面 count=200 截断), 立即下一轮
            continue

        # 2) 没新 catch-up → XREAD BLOCK 阻塞监听新事件
        try:
            block_result = await asyncio.to_thread(
                _stream_redis_engine.xread,
                {key: cursor or "0-0"},
                count=200,
                block=_BLOCK_MS,
            )
        except Exception as e:
            logger.warning("[stream_buffer] xread failed task_id=%s: %s", task_id, e)
            return

        # block_result: [] (block 超时) 或 [(stream_key, [(entry_id, fields), ...])]
        if not block_result:
            # idle 检查: 如果太久没动静, 主动退出
            if time.time() - last_activity_at > idle_timeout_seconds:
                logger.info("[stream_buffer] idle timeout, exiting task_id=%s", task_id)
                return
            # 周期性循环, 让上层能感知 cancel
            continue

        # 有新事件
        for _stream_key_in_resp, msgs in block_result:
            for entry_id, fields in msgs:
                cursor = entry_id
                last_activity_at = time.time()
                parsed = _parse_entry(fields)
                if parsed is None:
                    continue
                yield parsed
                if parsed["event"] == _SENTINEL_EVENT:
                    return


def _parse_entry(fields: dict) -> Optional[dict]:
    """Redis 返回的 fields 是 {b'event': b'section_chunk', b'payload': b'{...}'},
    decode_responses=True 时已经是 str 了 (见 utils/redis_client.py).
    """
    try:
        event_name = fields.get("event") or fields.get(b"event")
        if isinstance(event_name, bytes):
            event_name = event_name.decode("utf-8")
        raw_payload = fields.get("payload") or fields.get(b"payload") or "{}"
        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode("utf-8")
        try:
            payload = json.loads(raw_payload)
        except Exception:
            payload = {"raw": raw_payload}
        return {"event": event_name, "payload": payload}
    except Exception as e:
        logger.warning("[stream_buffer] parse entry failed: %s", e)
        return None


def cleanup_stream(task_id: str) -> None:
    """主动清理 Stream key. 一般不需要调 (走 TTL); 测试或异常清理时用."""
    if _redis_engine is None or not task_id:
        return
    try:
        _redis_engine.delete(_stream_key(task_id))
    except Exception as e:
        logger.warning("[stream_buffer] delete failed task_id=%s: %s", task_id, e)


# ────────────────────── 已有事件查询 (可选) ──────────────────────

def stream_exists(task_id: str) -> bool:
    """检查 Stream 是否存在 (用于前端连接前判断 task_id 是否有效)."""
    if _redis_engine is None or not task_id:
        return False
    try:
        return bool(_redis_engine.exists(_stream_key(task_id)))
    except Exception:
        return False
