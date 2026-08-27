"""PostgreSQL-backed WebUI session store.

照 136 (noah-research-agent) 的 hermes/web/app_db.py 模式:整段对话存
chat_sessions.payload (JSONB), 按 owner_id 行级隔离, 每用户 cap 200, upsert。

启用: 环境变量 HERMES_WEBUI_SESSION_STORE=postgres (默认 json = 原 sidecar 行为)。
owner_id = 当前 active profile 名 (由现有 SSO 身份派生, 见 profiles.get_active_profile_name)。
payload 就是 Session.save() 序列化进 sidecar 的同一份 dict, 读回用 Session(**payload) 重建。
"""
from __future__ import annotations

import contextlib
import contextvars
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_DATABASE_URL = "postgresql://noah_app:noah-local-dev-only@127.0.0.1:54322/plm_webui"
CHAT_CAP = 200


def session_store_mode() -> str:
    return (os.environ.get("HERMES_WEBUI_SESSION_STORE") or "json").strip().lower()


def pg_enabled() -> bool:
    return session_store_mode() == "postgres"


def database_url_from_env() -> str:
    return str(os.environ.get("NOAH_DATABASE_URL") or DEFAULT_DATABASE_URL).strip()


_OWNER_OVERRIDE: contextvars.ContextVar = contextvars.ContextVar("pg_owner_override", default=None)


@contextlib.contextmanager
def owner_scope(owner: Any):
    """在一段代码里显式指定 owner, 不依赖"当前活跃 profile"。

    侧栏列表的缓存重建跑在后台线程里, 那里没有请求上下文, get_active_profile_name()
    会退化成 'default' —— PG 于是去查 default 名下的会话, 结果为空还被当成有效结果缓存
    一个 TTL, 用户看到的就是"新建会话后整个列表消失, 十几秒后又回来"。路由已经知道正确
    的 active_profile, 用这个作用域把它传下来。
    """
    name = str(owner or "").strip()
    if not name:
        yield
        return
    token = _OWNER_OVERRIDE.set(name)
    try:
        yield
    finally:
        _OWNER_OVERRIDE.reset(token)


def active_owner_id() -> str:
    """当前请求的 owner = active profile 名 (SSO 身份派生); 拿不到则 'default'。"""
    _override = _OWNER_OVERRIDE.get()
    if _override:
        return _override
    try:
        from api.profiles import get_active_profile_name
        name = str(get_active_profile_name() or "").strip()
        return name or "default"
    except Exception:
        return "default"


def owner_for_profile(profile: Any) -> str:
    """写入时的 owner 必须以会话自己的 profile 为准, 不能用"当前活跃 profile"。

    active_owner_id() 依赖请求上下文; 后台线程/无身份上下文的保存会退化成 'default',
    于是同一个会话被写进两个 owner。后果: 重命名只落在其中一份, 侧栏另一个视图读到旧
    标题; 而错位那份的 payload.profile 与 owner 不符, 加载时 profile 校验不过, 直接
    409 session_profile_mismatch —— 前端据此无限重试, 表现为界面狂闪。
    """
    name = str(profile or "").strip()
    return name or active_owner_id()


def _to_ts(value: Any, fallback: Optional[datetime] = None) -> datetime:
    # Session 的 created_at/updated_at 是 epoch float (time.time()); 也兼容 ISO 字符串。
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    raw = str(value or "").strip()
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except ValueError:
            pass
    return fallback or datetime.now(timezone.utc)


_MIGRATE_LOCK = threading.Lock()
_INSTANCE: "PgSessionDB | None" = None


class PgSessionDbError(RuntimeError):
    pass


class PgSessionDB:
    """短连接仓库, 适配 webui 的 ThreadingHTTPServer (每操作一条连接, 线程安全)。"""

    def __init__(self, dsn: Optional[str] = None):
        self.dsn = str(dsn or database_url_from_env()).strip()
        if not self.dsn.startswith(("postgresql://", "postgres://")):
            raise PgSessionDbError("NOAH_DATABASE_URL must be a PostgreSQL URL")
        self._migrated = False

    @staticmethod
    def _driver():
        try:
            import psycopg
        except ImportError as ex:
            raise PgSessionDbError(
                "PostgreSQL driver missing; pip install 'psycopg[binary]'"
            ) from ex
        return psycopg

    def connect(self):
        return self._driver().connect(self.dsn, connect_timeout=5)

    def migrate(self) -> None:
        if self._migrated:
            return
        with _MIGRATE_LOCK:
            if self._migrated:
                return
            with self.connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_sessions (
                        owner_id        VARCHAR(160) NOT NULL,
                        session_id      VARCHAR(160) NOT NULL,
                        title           VARCHAR(200) NOT NULL DEFAULT 'Conversation',
                        payload         JSONB        NOT NULL DEFAULT '{}'::jsonb,
                        task_status     VARCHAR(20)  NOT NULL DEFAULT '',
                        created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                        updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                        task_updated_at TIMESTAMPTZ,
                        kb_subject      VARCHAR(220) NOT NULL DEFAULT '',
                        PRIMARY KEY (owner_id, session_id)
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS chat_sessions_owner_updated_idx "
                    "ON chat_sessions(owner_id, updated_at DESC)"
                )
                # 备用表 (照 136 建好, 本次暂不接线)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_profiles (
                        owner_id   VARCHAR(160) PRIMARY KEY,
                        payload    JSONB NOT NULL DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS run_ownership (
                        run_id       VARCHAR(80) PRIMARY KEY,
                        owner_id     VARCHAR(160) NOT NULL,
                        session_id   VARCHAR(160) NOT NULL DEFAULT '',
                        status       VARCHAR(30)  NOT NULL DEFAULT 'starting',
                        final_output TEXT        NOT NULL DEFAULT '',
                        artifacts    JSONB       NOT NULL DEFAULT '{}'::jsonb,
                        created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            self._migrated = True

    def health(self) -> bool:
        with self.connect() as conn:
            return bool(conn.execute("SELECT 1").fetchone())

    # ---- chat_sessions (移植 136 app_db.py:333-432) ----

    def write_session(self, owner_id: str, session: dict, cap: int = CHAT_CAP) -> dict:
        from psycopg.types.json import Jsonb

        self.migrate()
        created = _to_ts(session.get("created_at"))
        updated = _to_ts(session.get("updated_at"), created)
        task_updated = _to_ts(session["task_updated_at"]) if session.get("task_updated_at") else None
        session_id = str(session.get("session_id") or session.get("id") or "")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions(
                    owner_id, session_id, title, payload, task_status,
                    created_at, updated_at, task_updated_at, kb_subject
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(owner_id, session_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    payload = EXCLUDED.payload,
                    task_status = EXCLUDED.task_status,
                    updated_at = GREATEST(chat_sessions.updated_at, EXCLUDED.updated_at),
                    task_updated_at = EXCLUDED.task_updated_at,
                    kb_subject = EXCLUDED.kb_subject
                """,
                (
                    owner_id,
                    session_id,
                    str(session.get("title") or "Conversation")[:200],
                    Jsonb(session),
                    str(session.get("task_status") or "")[:20],
                    created,
                    updated,
                    task_updated,
                    str(session.get("kb_subject") or "")[:220],
                ),
            )
            conn.execute(
                """
                DELETE FROM chat_sessions
                WHERE (owner_id, session_id) IN (
                    SELECT owner_id, session_id FROM (
                        SELECT owner_id, session_id,
                               ROW_NUMBER() OVER (PARTITION BY owner_id ORDER BY updated_at DESC) AS rn
                        FROM chat_sessions WHERE owner_id = %s
                    ) ranked WHERE rn > %s
                )
                """,
                (owner_id, max(1, int(cap))),
            )
        return {"ok": True, "id": session_id}

    def read_session(self, owner_id: str, session_id: str) -> Optional[dict]:
        self.migrate()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload FROM chat_sessions WHERE owner_id = %s AND session_id = %s",
                (owner_id, str(session_id or "")),
            ).fetchone()
        return dict(row[0]) if row and isinstance(row[0], dict) else None

    def read_metadata(self, owner_id: str, session_id: str) -> Optional[dict]:
        """返回去掉 messages/tool_calls 的 payload + message_count (给 load_metadata_only)。"""
        self.migrate()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT payload - 'messages' - 'tool_calls',
                       COALESCE(jsonb_array_length(payload->'messages'), 0)
                FROM chat_sessions WHERE owner_id = %s AND session_id = %s
                """,
                (owner_id, str(session_id or "")),
            ).fetchone()
        if not row or not isinstance(row[0], dict):
            return None
        meta = dict(row[0])
        meta["messages"] = []
        meta["tool_calls"] = []
        meta["message_count"] = int(row[1] or 0)
        return meta

    def session_ids(self, owner_id: str) -> frozenset[str]:
        self.migrate()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT session_id FROM chat_sessions WHERE owner_id = %s", (owner_id,)
            ).fetchall()
        return frozenset(str(r[0]) for r in rows)

    def session_ids_ordered(self, owner_id: str, limit: int = CHAT_CAP) -> list[str]:
        self.migrate()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT session_id FROM chat_sessions WHERE owner_id = %s "
                "ORDER BY updated_at DESC LIMIT %s",
                (owner_id, int(limit)),
            ).fetchall()
        return [str(r[0]) for r in rows]

    def has_sessions(self, owner_id: str) -> bool:
        self.migrate()
        with self.connect() as conn:
            return bool(
                conn.execute(
                    "SELECT 1 FROM chat_sessions WHERE owner_id = %s LIMIT 1", (owner_id,)
                ).fetchone()
            )

    def delete_session(self, owner_id: str, session_id: str) -> bool:
        self.migrate()
        with self.connect() as conn:
            row = conn.execute(
                "DELETE FROM chat_sessions WHERE owner_id = %s AND session_id = %s RETURNING session_id",
                (owner_id, str(session_id or "")),
            ).fetchone()
        return bool(row)


def get_db() -> PgSessionDB:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = PgSessionDB()
    return _INSTANCE
