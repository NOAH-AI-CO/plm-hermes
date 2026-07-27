#!/usr/bin/env bash
# PLM 更新脚本:拉最新代码 → 同步扩展/SOUL 到容器挂载目录 → 重启容器 → 健康检查。
# 用法: cd ~/plm-hermes && ./deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."          # 切到仓库根目录

echo "[1/4] git pull --ff-only"
git pull --ff-only

echo "[2/5] 同步 hermes-config → deploy/hermes-home(扩展 + SOUL)"
mkdir -p deploy/hermes-home/webui/extensions
rsync -a --delete hermes-config/webui-extensions/noah/ deploy/hermes-home/webui/extensions/noah/
cp hermes-config/SOUL.md deploy/hermes-home/SOUL.md
[ -f hermes-config/config.yaml ] && cp hermes-config/config.yaml deploy/hermes-home/config.yaml || true

echo "[3/5] 同步 PLM 技能 skills/plm → agent 实际读取处(workspace-skills/plm 源 + 各 profile 副本)"
if [ -d skills/plm ]; then
  src=deploy/hermes-home/skills/workspace-skills/plm
  mkdir -p "$src"; rsync -a --delete skills/plm/ "$src/"
  for d in deploy/hermes-home/profiles/*/skills/workspace-skills/plm; do
    [ -d "$d" ] && rsync -a --delete skills/plm/ "$d/"
  done
fi

echo "[4/5] 重启/重建容器(webui/agent/nginx compose;引擎挂载代码, restart 即生效, 没了则重建)"
( cd deploy && docker compose -p plm up -d )
docker restart plm-hermes-agent plm-hermes-webui >/dev/null 2>&1 || true
if docker ps -a --format '{{.Names}}' | grep -qx plm-engine; then
  docker restart plm-engine >/dev/null 2>&1 || ./deploy/run-engine.sh
else
  ./deploy/run-engine.sh
fi

echo "[5/5] 健康检查"
sleep 3
docker ps --filter name=plm --format '  {{.Names}}: {{.Status}}'
curl -s -m6 http://127.0.0.1:8003/plm/me -o /dev/null -w '  engine /plm/me → %{http_code}\n' || true
echo "完成。前端硬刷新查看更新。"
