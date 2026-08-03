#!/bin/sh
# 一键把 yiyong-prod 最新的 noah webui 扩展部署到生产并重启 webui。
# 在客户端宿主机(YY-Hospital, 47.98.57.93)以 root 运行:  sh /root/deploy-plm-ext.sh
# 生产的扩展目录不在任何 CI/CD 流水线里(是交付包一次性铺进去的), 故用此脚本手动拉取+同步+重启。
set -eu

REPO_URL="https://github.com/NOAH-AI-CO/plm-hermes.git"
BRANCH="yiyong-prod"
SRC_DIR="/root/plm-hermes-src"                                  # 脚本自维护的检出(首次自动 clone)
EXT_SRC="$SRC_DIR/hermes-config/webui-extensions/noah"
EXT_DST="/root/noah-client/app/plm-webui-extension/noah"
WEBUI_CONTAINER="noah-client-hermes-webui-1"

echo "[1/4] 拉取最新代码 ($BRANCH) ..."
if [ -d "$SRC_DIR/.git" ]; then
  git -C "$SRC_DIR" fetch --depth 1 origin "$BRANCH"
  git -C "$SRC_DIR" reset --hard "origin/$BRANCH"
else
  git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$SRC_DIR"
fi
echo "    当前提交: $(git -C "$SRC_DIR" rev-parse --short HEAD)"

[ -d "$EXT_SRC" ] || { echo "错误: 源扩展目录不存在: $EXT_SRC" >&2; exit 1; }
[ -d "$EXT_DST" ] || { echo "错误: 生产扩展目录不存在: $EXT_DST" >&2; exit 1; }

echo "[2/4] 备份现网扩展目录 ..."
BAK="${EXT_DST}.bak.$(date +%Y%m%d-%H%M%S)"
cp -a "$EXT_DST" "$BAK"
echo "    备份: $BAK"

echo "[3/4] 同步扩展文件 (仅覆盖, 不删除生产独有文件) ..."
rsync -a "$EXT_SRC/" "$EXT_DST/"

echo "[4/4] 重启 webui 容器 ..."
docker restart "$WEBUI_CONTAINER" >/dev/null
echo "完成。扩展已更新并重启。若页面无变化, 浏览器硬刷新(Cmd/Ctrl+Shift+R)。"
echo "如需回滚:  rm -rf $EXT_DST && mv $BAK $EXT_DST && docker restart $WEBUI_CONTAINER"
