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


def _session_dir_for(base: Path) -> Path | None:
    """profile/根目录下找会话 sidecar 目录(优先 webui/sessions, 退回 sessions)。"""
    for cand in (base / "webui" / "sessions", base / "sessions"):
        if cand.is_dir() and any(cand.glob("*.json")):
            return cand
    return None


def migrate_all_profiles(home: Path) -> None:
    """把整套 HERMES_HOME 里 每个 profile(=owner)的会话全量迁进 PG。

    - 根 (default): <home>/webui/sessions → owner=default
    - 每个 profile: <home>/profiles/<name>/{webui/,}sessions → owner=<name>
    """
    total = 0
    root = _session_dir_for(home)
    if root:
        n = migrate_dir("default", root); total += n
        print(f"  default ← {root}  ({n})")
    prof_root = home / "profiles"
    if prof_root.is_dir():
        for pdir in sorted(prof_root.iterdir()):
            if not pdir.is_dir():
                continue
            sd = _session_dir_for(pdir)
            if sd:
                n = migrate_dir(pdir.name, sd); total += n
                print(f"  {pdir.name} ← {sd}  ({n})")
    print(f"全量迁移完成, 共 {total} 个会话")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", help="owner_id(= profile 名, 如 u_<hash> 或 default)")
    ap.add_argument("--dir", help="单目录模式: 会话 sidecar 目录(含 <sid>.json)")
    ap.add_argument("--all-profiles", action="store_true", help="全量模式: 遍历 HERMES_HOME 下所有 profile 迁移")
    ap.add_argument("--home", help="全量模式的 HERMES_HOME(默认取 $HERMES_HOME 或 ~/.hermes)")
    args = ap.parse_args()

    if args.all_profiles:
        import os
        home = Path(args.home or os.getenv("HERMES_HOME") or (Path.home() / ".hermes")).expanduser().resolve()
        if not home.is_dir():
            print(f"HERMES_HOME 不存在: {home}", file=sys.stderr); sys.exit(1)
        migrate_all_profiles(home)
        return

    if not args.owner or not args.dir:
        print("单目录模式需 --owner 和 --dir;或用 --all-profiles [--home ...]", file=sys.stderr); sys.exit(2)
    d = Path(args.dir).expanduser().resolve()
    if not d.is_dir():
        print(f"目录不存在: {d}", file=sys.stderr); sys.exit(1)
    count = migrate_dir(args.owner, d)
    print(f"已导入 {count} 个会话 → owner_id={args.owner}")


if __name__ == "__main__":
    main()
