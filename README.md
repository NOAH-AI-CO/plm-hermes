# plm-hermes

PLM(Patient-Like-Me)临床指南循证系统。医生用自然语言描述病情 → 从指南库检索 TOP-5 指南 → 选一份 → 澄清 → 生成六分区循证诊疗报告(诊断/检查/治疗/药物说明书/次要指南补充/综合)。基于 Hermes(glm-5.2)。

> **本仓库只含 PLM 定制层 + webui,不含 Hermes agent 本体、bizagent 引擎镜像、指南数据。** 启动前请按下方「必备清单」备齐,否则起不来。

---

## 一、启动前必备清单(运维照此备齐)

### 1) Docker 镜像(4 个)
| 镜像 | 来源 | 说明 |
|---|---|---|
| `hermes-agent:pinned` | **Hermes agent 项目**构建(非本仓库) | agent 网关 + dashboard 用,即 **Hermes 本体** |
| `plm-hermes-webui:latest` | **本仓库**:`docker build -t plm-hermes-webui:latest webui/` | 前端 |
| `bizagent:<tag>` | **biz 部署**提供 | PLM 引擎的基础镜像 |
| `nginx:alpine` | Docker Hub 自动拉 | 反代 |

### 2) 外部服务(需运行,且与本服务在同一 docker 网络内可解析)
| 服务 | 用途 |
|---|---|
| **bizbackend** | 鉴权权威(DRF Token):`/api/token/`、`/api/users/`、`/api/access/me/` |
| **Elasticsearch** | 指南库,3 索引:`plm_guidelines`、`plm_guideline_chunks`、`drug_manuals` |
| **Redis** | 报告/会话缓存 |

### 3) 需另外放置的文件/目录(**不在仓库里**,已 gitignore)
| 路径 | 内容 | 来源 |
|---|---|---|
| `deploy/hermes-agent-src/` | Hermes agent 源码(webui 容器挂载后导入) | Hermes agent 项目 |
| `plm_agent/api.json` | ES 地址、LLM key 等引擎配置 | biz 部署 |
| `plm_agent/.env` | 引擎环境变量 | biz 部署 |
| `plm_agent/gcp_key.json` | GCP 凭证(如用到) | biz 部署 |
| `deploy/.env` | 网关共享密钥 `GATEWAY_KEY`(compose 读取) | 复制 `.env.example` 后填 |
| `deploy/secrets/plm.env` | 复制 `plm.env.example` 后填值 | 自填 |
| `deploy/hermes-home/` | 由 `hermes-config/` 拷贝生成(见步骤 3) | 本仓库生成 |

### 4) 数据
- 把 3 个指南索引导入目标 ES(`elasticdump` 或等价工具从现有库迁移)。

---

## 二、组件与端口

`deploy/docker-compose.yml` 起前三个;引擎单独 `docker run`(复用 bizagent 镜像)。

| 容器 | 端口 | 作用 |
|---|---|---|
| `plm-nginx` | `8090→80` | 同源反代:`/plm*`、`/plm_evidence_based`→引擎,其余→webui;**SSE 关缓冲** |
| `plm-hermes-webui` | 8787 | 前端(登录/会话隔离/PLM 扩展) |
| `plm-hermes-agent` | 8642 | Hermes 网关(跑 SOUL + skills) |
| `plm-engine` | `127.0.0.1:8003→8002` | 检索/澄清/报告引擎(`main_plm.py`),镜像 `bizagent`,挂载 `plm_agent/` |

---

## 三、部署步骤

```bash
# 0. 取代码
git clone git@github.com:LzFukua/plm-hermes.git && cd plm-hermes

# 1. 准备镜像(见「必备清单」)
docker build -t plm-hermes-webui:latest webui/          # 前端镜像(本仓库自带 Dockerfile)
#   hermes-agent:pinned  → 从 Hermes agent 项目构建
#   bizagent:<tag>       → 从 biz 部署获取
#   并把 Hermes agent 源码放到 deploy/hermes-agent-src/

# 2. 配密钥
#    - 引擎密钥放 plm_agent/ 下:api.json(含 ES 地址/LLM key)、.env、gcp_key.json
cp deploy/.env.example deploy/.env                 # 填 GATEWAY_KEY(网关共享密钥, compose 自动读)
cp deploy/secrets/plm.env.example deploy/secrets/plm.env   # 按需填

# 3. 同步扩展/SOUL 到容器挂载目录(容器挂的是 deploy/hermes-home, 源是 hermes-config)
mkdir -p deploy/hermes-home/webui/extensions
cp -r hermes-config/webui-extensions/noah deploy/hermes-home/webui/extensions/noah
cp hermes-config/SOUL.md deploy/hermes-home/SOUL.md
cp hermes-config/config.yaml deploy/hermes-home/config.yaml   # 如有

# 4. 起 webui + agent + nginx
cd deploy && docker compose -p plm up -d && cd ..

# 5. 起引擎(复用 bizagent 镜像;先接 plm-net 供 nginx 解析,再接 biz 网络供解析 ES/Redis 别名)
docker run -d --name plm-engine --network plm-net --restart unless-stopped \
  -p 127.0.0.1:8003:8002 --add-host host.docker.internal:host-gateway \
  -v "$(pwd)/plm_agent:/noah_agent" \
  -e PLM_BACKEND_BASE=http://host.docker.internal:8102 \
  -e PLM_REDIS_HOST=<biz-redis 容器名/别名> -e PLM_REDIS_PORT=6379 -e PLM_REDIS_DB=3 \
  -e PLM_DISABLE_PUBMED=1 \
  bizagent:<tag> python -m uvicorn main_plm:app --host 0.0.0.0 --port 8002
docker network connect <biz 网络名> plm-engine    # 让引擎能解析 ES / Redis 别名

# 6. 迁指南数据(把三索引灌进目标 ES;源库→目标库)
#    用 elasticdump 或等价工具迁移: plm_guidelines / plm_guideline_chunks / drug_manuals

# 7. 验证
curl -s http://127.0.0.1:8003/plm/me     # 引擎存活(带 token 返身份)
# 浏览器开 nginx 端口(8090)→ 登录(biz 账号)→ 描述病情 → 出候选卡 → 选 → 澄清 → 报告分区流式
```

---

## 四、换环境必改清单

| 项 | 位置 | 说明 |
|---|---|---|
| **biz-backend 地址** | 引擎 `-e PLM_BACKEND_BASE` + webui `HERMES_DJANGO_URL`(compose) | 逗号分隔可多个(依次校验) |
| **ES 地址/账号** | `plm_agent/api.json`(主索引)+ 引擎能解析 drug ES 别名 | 指向目标 ES |
| **Redis** | 引擎 `-e PLM_REDIS_HOST/PORT/DB` | 指向目标 Redis |
| **网关共享密钥** | `deploy/.env` 的 `GATEWAY_KEY` | 改成自定义随机串(compose 4 处自动取同值) |
| **域名/证书** | 上层反代到 `plm-nginx:8090` | 走 https;webui 已开 `TRUST_FORWARDED_PROTO` |
| **docker 网络** | `docker network connect` | 引擎必须能解析 bizbackend/ES/Redis |

---

## 五、更新已部署的服务

**日常更新一条命令**(拉代码 → 同步扩展/SOUL → 重启 → 健康检查):
```bash
cd ~/plm-hermes && ./deploy/update.sh
```
`update.sh` 只重启容器,不重新 `docker run` 引擎——改扩展/SOUL/`main_plm.py` 都能生效(改扩展记得 bump `manifest.json` 版本号破缓存)。

**例外**:动了引擎 env、compose、镜像时:
- 改引擎 env → `docker rm -f plm-engine` 后按步骤 5 重新 `docker run`。
- 改 `webui/`(镜像内代码)→ `docker build -t plm-hermes-webui:latest webui/` 后 `docker compose -p plm up -d`。

## 目录
| 目录 | 作用 |
|---|---|
| `plm_agent/` | 引擎 `main_plm.py` + RAG workflow |
| `webui/` | 前端 fork(含登录/SSO/会话隔离 + `Dockerfile`) |
| `hermes-config/` | `SOUL.md` + `config.yaml` + `webui-extensions/noah/`(**源**,部署时拷进 `deploy/hermes-home/`) |
| `deploy/` | `docker-compose.yml` + `plm-nginx.conf` + `update.sh` + `.env.example` + `secrets/*.example` |
