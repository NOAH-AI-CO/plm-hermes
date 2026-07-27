#!/usr/bin/env bash
# 重建/更新 plm-engine 容器(代码=plm_agent 挂载, 配置=deploy/secrets)。可反复执行(幂等)。
# 用法: cd ~/plm-hermes && ./deploy/run-engine.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"; SECRETS="$REPO/deploy/secrets"

# 可按环境覆盖(默认=当前 Azure 部署)
: "${ENGINE_IMAGE:=biz-agent:0.0.1}"      # 复用 biz-agent 依赖镜像
: "${PLM_NET:=plm-net}"                    # nginx 反代所在网络
: "${BIZ_NET:=biz_stack}"                  # biz-elastic/redis 别名所在网络
: "${PLM_BACKEND_BASE:=http://host.docker.internal:8101,http://host.docker.internal:8102}"
: "${PLM_REDIS_HOST:=noah-redis-persistent}"

for f in api.json setting_test.json plm.env gcp_key.json; do
  [ -s "$SECRETS/$f" ] || { echo "缺少 $SECRETS/$f(引擎配置),请先放好真配置"; exit 1; }
done

docker rm -f plm-engine 2>/dev/null || true
# ⚠️ biz-agent 镜像烤死了 compose 标签 project=biz → 不覆盖的话, biz 项目 `compose up --remove-orphans`
# 会把本容器当孤儿删掉(engine 反复消失的根因)。改标签为独立 project, 谁的 --remove-orphans 都不认它。
docker run -d --name plm-engine --network "$PLM_NET" --restart unless-stopped \
  --label com.docker.compose.project=plm-engine \
  --label com.docker.compose.service=plm-engine \
  -p 127.0.0.1:8003:8002 --add-host host.docker.internal:host-gateway \
  -v "$REPO/plm_agent:/noah_agent" \
  -v "$SECRETS/api.json:/noah_agent/api.json:ro" \
  -v "$SECRETS/setting_test.json:/noah_agent/setting_test.json:ro" \
  -v "$SECRETS/plm.env:/noah_agent/.env:ro" \
  -v "$SECRETS/gcp_key.json:/noah_agent/gcp_key.json:ro" \
  -e GOOGLE_APPLICATION_CREDENTIALS=/noah_agent/gcp_key.json \
  -e PLM_BACKEND_BASE="$PLM_BACKEND_BASE" \
  -e PLM_REDIS_HOST="$PLM_REDIS_HOST" -e PLM_REDIS_PORT=6379 -e PLM_REDIS_DB=3 \
  -e PLM_DISABLE_PUBMED=1 -e NOAH_LENIENT_CONFIG=1 \
  "$ENGINE_IMAGE" python -m uvicorn main_plm:app --host 0.0.0.0 --port 8002

docker network connect "$BIZ_NET" plm-engine 2>/dev/null || true
sleep 6
docker ps --filter name=plm-engine --format '  {{.Names}}: {{.Status}}'
curl -s -m6 http://127.0.0.1:8003/plm/me -o /dev/null -w '  /plm/me → %{http_code}\n' || true
echo "plm-engine 就绪。"
