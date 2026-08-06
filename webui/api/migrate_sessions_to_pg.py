"""把某目录下的会话 JSON sidecar 批量导入 Postgres chat_sessions(照 136 claim_legacy_state 思路)。

用法(在 webui 目录, 设好 NOAH_DATABASE_URL):
    python -m api.migrate_sessions_to_pg --owner u_abc --dir ~/.hermes/webui/sessions
    python -m api.migrate_sessions_to_pg --owner default --dir <SESSION_DIR>   # 单 profile
不改动源文件, 仅 upsert 进库(可重复执行, 幂等)。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from api.pg_session_db import get_db


def migrate_dir(owner_id: str, session_dir: Path) -> int:
    db = get_db()
    db.migrate()
    n = 0
    for p in sorted(session_dir.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            print(f"  skip (unreadable): {p.name}", file=sys.stderr)
            continue
        if not str(data.get("session_id") or data.get("id") or "").strip():
            data["session_id"] = p.stem
        db.write_session(owner_id, data, cap=10_000)  # 迁移时不裁剪
        n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True, help="owner_id(= profile 名, 如 u_<hash> 或 default)")
    ap.add_argument("--dir", required=True, help="会话 sidecar 目录(含 <sid>.json)")
    args = ap.parse_args()
    d = Path(args.dir).expanduser().resolve()
    if not d.is_dir():
        print(f"目录不存在: {d}", file=sys.stderr)
        sys.exit(1)
    count = migrate_dir(args.owner, d)
    print(f"已导入 {count} 个会话 → owner_id={args.owner}")


if __name__ == "__main__":
    main()
