"""把 owner_id 与 payload.profile 错位的 chat_sessions 行归位。

同一 session_id 可能因旧 bug 被写到两个 owner 下(内容还各自演化过, 比如重命名只落在
其中一份)。策略: 以 payload.profile 为正确 owner, 保留 updated_at 最新的那份 payload,
写到正确 owner 下, 再删掉错位的行。--apply 才真正执行, 默认只报告。
"""
import sys
from api.pg_session_db import get_db

apply = "--apply" in sys.argv
db = get_db(); db.migrate()
with db.connect() as conn:
    rows = conn.execute(
        "SELECT owner_id, session_id, payload->>'profile', updated_at, title "
        "FROM chat_sessions ORDER BY session_id, updated_at DESC"
    ).fetchall()

by_sid = {}
for owner, sid, prof, upd, title in rows:
    by_sid.setdefault(sid, []).append({"owner": owner, "prof": prof, "upd": upd, "title": title})

moves, deletes = [], []
for sid, entries in by_sid.items():
    correct = next((e["prof"] for e in entries if e["prof"]), None)
    if not correct:
        continue
    newest = max(entries, key=lambda e: e["upd"])
    wrong = [e for e in entries if e["owner"] != correct]
    if not wrong:
        continue
    if newest["owner"] != correct:
        moves.append((sid, newest["owner"], correct, newest["title"]))
    for e in wrong:
        deletes.append((sid, e["owner"]))

print(f"需要归位(最新那份在错误 owner 下): {len(moves)}")
for sid, frm, to, t in moves:
    print(f"   {sid}  {frm} -> {to}   title={str(t)[:34]}")
print(f"需要删除的错位行: {len(deletes)}")

if not apply:
    print("\n(演练模式, 未改动。加 --apply 才执行)")
    sys.exit(0)

with db.connect() as conn:
    for sid, frm, to, _t in moves:
        conn.execute(
            "INSERT INTO chat_sessions(owner_id,session_id,title,payload,task_status,"
            "created_at,updated_at,task_updated_at,kb_subject) "
            "SELECT %s,session_id,title,payload,task_status,created_at,updated_at,task_updated_at,kb_subject "
            "FROM chat_sessions WHERE owner_id=%s AND session_id=%s "
            "ON CONFLICT(owner_id,session_id) DO UPDATE SET "
            "title=EXCLUDED.title, payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
            (to, frm, sid))
    for sid, owner in deletes:
        conn.execute("DELETE FROM chat_sessions WHERE owner_id=%s AND session_id=%s", (owner, sid))
print(f"已归位 {len(moves)} 条, 删除错位行 {len(deletes)} 条")
