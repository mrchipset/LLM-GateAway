# Docker Compose 部署指南

本指南说明如何用 Docker Compose 启动 LLM-GateAway 的完整栈，以及需要配置哪些环境变量。

## 方案

采用单入口架构：nginx 同时托管管理台静态资源并反向代理后端。浏览器、OpenAI SDK 和 curl 都只访问 `http://<host>:8080`，因此不需要给后端加 CORS。

```text
client / OpenAI SDK / curl
        │
        ▼
┌─────────────────────────────┐
│ ui (nginx :8080)            │
│  /            静态管理台     │
│  /healthz     反代 backend   │
│  /readyz      反代 backend   │
│  /api/*       反代 backend   │
│  /v1/*        反代 backend   │
└──────────────┬──────────────┘
               ▼
      backend (:4000, 仅内网)
               │
               ▼
      postgres (:5432, 数据卷)
               ▲
      migrate (一次性 job，与 backend 同镜像)
```

- `migrate` 在 `backend` 启动前执行 `alembic upgrade head`，成功退出后 `backend` 才启动；失败会阻止后端上线。
- PostgreSQL 数据保存在命名卷 `pgdata`。
- Redis 目前未使用，仍保留 `redis` profile。

## 涉及文件

| 文件 | 作用 |
|---|---|
| `Dockerfile` | 后端多阶段镜像（uv + Python 3.12 slim，非 root） |
| `ui/Dockerfile` | 管理台构建 + nginx 运行镜像 |
| `ui/nginx.conf` | 静态资源、API 反代、SSE 不缓冲 |
| `docker-compose.yml` | postgres / migrate / backend / ui / redis |
| `.env.docker.example` | Compose 配置模板 |

## 快速启动

```powershell
Copy-Item .env.docker.example .env.docker
```

编辑 `.env.docker`，至少填写：

```dotenv
GATEWAY_MASTER_KEY=<至少 32 字符的随机值>
POSTGRES_PASSWORD=<URL 安全的密码>
```

再按需填写 `GATEWAY_DEEPSEEK_API_KEY` / `GATEWAY_OPENAI_API_KEY`。

启动完整栈：

```powershell
docker compose --profile app --env-file .env.docker up -d --build
```

检查：

```powershell
docker compose --env-file .env.docker --profile app ps
docker compose --env-file .env.docker --profile app logs migrate
Invoke-RestMethod http://127.0.0.1:8080/healthz
Invoke-RestMethod http://127.0.0.1:8080/readyz
```

预期：

- `migrate` 状态为 `Exited (0)`；
- `backend`、`ui`、`postgres` 为 `healthy`；
- `/healthz` 返回 `{"status":"ok","version":"0.1.0"}`；
- `/readyz` 返回 `{"status":"ok","checks":{"database":"ok"}}`。

访问入口：

| 用途 | 地址 |
|---|---|
| 管理台 | `http://127.0.0.1:8080` |
| OpenAI 兼容 API base | `http://127.0.0.1:8080/v1` |
| 健康检查 | `http://127.0.0.1:8080/healthz` |
| 就绪检查 | `http://127.0.0.1:8080/readyz` |
| 管理 API | `http://127.0.0.1:8080/api/v1/*` |

首次初始化（创建租户、API key、模型）见 [`docs/verification.md`](verification.md)，把其中的 `4000` 端口换成 `8080` 即可。

## 需要配置什么

`.env.docker.example` 中的变量：

| 变量 | 必填 | 说明 |
|---|---|---|
| `GATEWAY_MASTER_KEY` | 是 | 管理 API 凭据。`GATEWAY_ENVIRONMENT` 默认 `production`，因此至少 32 字符 |
| `POSTGRES_PASSWORD` | 是 | 内置 PostgreSQL 密码；请使用 URL 安全字符（字母、数字、`-`、`_`），因为会拼进 DSN |
| `GATEWAY_ENVIRONMENT` | 否 | 默认 `production`；本地冒烟可设为 `development` |
| `GATEWAY_LOG_LEVEL` | 否 | 默认 `INFO` |
| `GATEWAY_UI_PORT` | 否 | 管理台/统一入口端口，默认 `8080` |
| `POSTGRES_PORT` | 否 | 宿主机调试端口，默认 `5432`，仅绑定 `127.0.0.1` |
| `GATEWAY_OPENAI_API_KEY` | 否 | 为空则不注册 OpenAI provider |
| `GATEWAY_OPENAI_BASE_URL` | 否 | 默认 `https://api.openai.com/v1` |
| `GATEWAY_DEEPSEEK_API_KEY` | 否 | 为空则不注册 DeepSeek provider |
| `GATEWAY_DEEPSEEK_BASE_URL` | 否 | 默认 `https://api.deepseek.com` |
| `GATEWAY_REQUEST_TIMEOUT_SECONDS` | 否 | 上游总超时，默认 60 |
| `GATEWAY_CONNECT_TIMEOUT_SECONDS` | 否 | 连接超时，默认 10 |
| `GATEWAY_MAX_RETRIES` | 否 | 首字节前重试次数，默认 2 |
| `GATEWAY_FAKE_PROVIDER_ENABLED` | 否 | 默认 `false`；仅 development/test 可开启，production 会拒绝 |

`POSTGRES_PASSWORD` 为空时 Compose 会回退到开发默认值 `gateway`；生产部署必须显式设置。没有上游 key 时，可把 `GATEWAY_ENVIRONMENT=development`、`GATEWAY_FAKE_PROVIDER_ENABLED=true`，重启栈后注册 fake 模型完成链路验证；生产环境禁止开启 fake provider。

注意：

- 修改 `.env.docker` 后，执行的仍是同一份 Compose 文件；重建容器才会让环境变量生效：
  `docker compose --env-file .env.docker --profile app up -d --force-recreate`
- 如果密码已经初始化过数据卷，再改 `POSTGRES_PASSWORD` 不会自动修改数据库里的密码。需要进入 `psql` 执行 `ALTER USER`，或删除数据卷重建（会丢数据）。

### 已有数据卷的密码不一致

`POSTGRES_PASSWORD` 只在数据目录**首次初始化**时生效。如果 `pgdata` 卷已经存在且密码不同，`migrate` 会报：

```text
password authentication failed for user "gateway"
```

无损修复（推荐密码只含字母、数字、`-`、`_`）：

```powershell
$line = Get-Content .env.docker | Where-Object { $_ -match '^POSTGRES_PASSWORD=' } | Select-Object -First 1
$pw = $line.Substring('POSTGRES_PASSWORD='.Length)
$sql = "ALTER USER gateway PASSWORD '$pw';"

docker compose --env-file .env.docker --profile app exec -T postgres psql -U gateway -d gateway -c $sql
docker compose --env-file .env.docker --profile app up -d
```

`migrate` 随后应显示 `Exited (0)`，`backend` 才会启动。如果不再需要旧数据，也可以：

```powershell
docker compose --env-file .env.docker --profile app down -v
docker compose --env-file .env.docker --profile app up -d --build
```

`-v` 会删除数据库数据卷，请先确认不需要里面的数据。密码包含单引号等特殊字符时，请改用 `psql` 交互式执行，或直接重建数据卷。
- 只想本地起 PostgreSQL（后端用 `uv`、前端用 Vite）：`docker compose up -d postgres`。不加 `--profile app` 不会启动后端和管理台。

## 迁移与升级

- `migrate` 是 **一次性任务**，每次 `up` 都会执行一次 `alembic upgrade head`；已是最新版本时是空操作。
- 升级镜像后重新执行：

```powershell
git pull
docker compose --env-file .env.docker --profile app up -d --build
```

- 迁移失败时 `backend` 不会启动。查看：

```powershell
docker compose --env-file .env.docker --profile app logs migrate
```

- 不要对同一个数据库同时启动多个 Compose 项目执行迁移。

## 日志、停止与数据

```powershell
# 日志
docker compose --env-file .env.docker --profile app logs -f backend
docker compose --env-file .env.docker --profile app logs -f ui
docker compose --env-file .env.docker --profile app logs migrate

# 停止并移除容器（保留 pgdata 数据卷）
docker compose --env-file .env.docker --profile app down

# 停止并删除数据卷（会丢数据库，谨慎）
docker compose --env-file .env.docker --profile app down -v
```

备份/恢复：

```powershell
# 备份
docker compose --env-file .env.docker --profile app exec -T postgres pg_dump -U gateway gateway > backup.sql

# 恢复
Get-Content backup.sql -Raw | docker compose --env-file .env.docker --profile app exec -T postgres psql -U gateway -d gateway
```

## 生产环境清单

- 在 8080 之前再加一层 TLS 反向代理（Caddy / Traefik / nginx），不要直接把 8080 暴露到公网。
- 删除或覆盖 `postgres` 的宿主机端口映射；只允许内网访问。
- `GATEWAY_MASTER_KEY` 使用密码管理器生成并注入；不要写进镜像或 Git。
- `GATEWAY_ENVIRONMENT=production`（默认），`GATEWAY_FAKE_PROVIDER_ENABLED=false`。
- 使用 URL 安全的 `POSTGRES_PASSWORD`，或直接改用外部 PostgreSQL 并覆盖 `GATEWAY_DATABASE_URL`。
- 配置数据库备份、日志轮转（Compose 已限制日志大小）与磁盘监控。
- 如果前面还有一层代理转发 SSE，确保 `proxy_buffering off`，并把读超时调到大于最长生成时间。

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `backend` 反复重启，日志提示 master key 无效 | `GATEWAY_MASTER_KEY` 为空、过短或仍是占位值 | 填 32+ 随机值后重新 `up -d` |
| `migrate` 失败，`backend` 不启动 | 数据库密码错误、DSN 不可达或迁移冲突 | 看 `logs migrate`；若报 `password authentication failed`，按上文“已有数据卷的密码不一致”修复 |
| 管理台能打开，但 API 502 | `backend` 未 healthy | `ps` + `logs backend`；确认 `migrate` 已成功 |
| 5432 / 8080 被占用 | 本机已有服务 | 改 `POSTGRES_PORT` / `GATEWAY_UI_PORT` |
| 生产环境注册 fake 模型返回 400 | production 禁止 fake provider | 用 development + fake 做本地冒烟；生产配置真实 provider |
| 改了 `.env.docker` 但没生效 | 容器未重建 | 加 `--force-recreate` |
| SSE 被缓冲/延迟 | 前置代理开启了 buffering | 保留本仓库 nginx 配置，或对上游关闭 buffering |

## 已验证

本方案已在当前环境实际验证：

- `docker compose config` 通过；
- `docker compose --profile app up -d --build` 启动成功；
- `migrate` 执行完成后 `backend` 启动，`postgres` / `backend` / `ui` 均 healthy；
- `http://127.0.0.1:8080/healthz`、`/readyz`、管理台首页 200；
- 通过 8080 完成租户、key、模型创建，非流式与 SSE 调用成功，用量汇总正确；
- 验证后已清理测试数据并停止栈（保留数据卷）。
