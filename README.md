# LLM-GateAway

自托管、多 provider 的 OpenAI 兼容 LLM 网关。当前为 MVP 骨架：可运行的后端、真实与测试 provider、API key 认证、模型注册表、PostgreSQL 持久化，以及一个只读的管理台骨架。

## 当前能力

- OpenAI 兼容的 `POST /v1/chat/completions`，支持 `stream=true` 与 `stream=false`
- `GET /v1/models` 返回已启用的模型
- Provider 抽象：OpenAI adapter 与确定性 Fake provider
- API key 认证：只存 SHA-256 哈希，支持过期与吊销
- 管理 API：`/api/v1/keys`、`/api/v1/models`，由 master key 保护
- PostgreSQL 持久化（SQLAlchemy 2 async + Alembic），默认也可用内存模式本地开发
- 结构化 JSON 日志、request id、`/healthz` 与 `/readyz`
- React + Vite + TypeScript 管理台骨架：健康状态与模型列表

不在本次范围：预算与计费、guardrail、MCP/Agent、多租户与 SSO、Redis 限流/缓存、高级路由与 fallback、完整 Dashboard。

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+（仅管理台需要）
- Docker（可选，用于本地 PostgreSQL / Redis）

以下命令示例使用 PowerShell 7；bash 用户可将 `Invoke-RestMethod` 示例改写为等价的 `curl` 调用。

## 快速开始

### 1. 安装依赖

```powershell
uv sync
```

### 2. 准备配置

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，替换 `GATEWAY_MASTER_KEY`。示例里的占位值会被拒绝，请使用足够长的随机字符串：

```powershell
# 生成本地 master key
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

内存模式（默认）适合本地试用，重启后 API key 与模型会丢失。下面的配置同时启用了 fake provider；如果只替换 master key 而保留 `.env.example` 中的 `GATEWAY_FAKE_PROVIDER_ENABLED=false`，第 4 步注册 fake 模型会返回 400 `provider_not_configured`。

```dotenv
GATEWAY_ENVIRONMENT=development
GATEWAY_MASTER_KEY=<替换为真实随机值>
GATEWAY_STORAGE_BACKEND=memory
GATEWAY_FAKE_PROVIDER_ENABLED=true
```

### 3. 启动开发服务

在仓库根目录执行（`.env` 相对于当前工作目录读取）：

```powershell
uv run uvicorn llm_gateway.app:create_app --factory --reload --port 4000
```

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:4000/healthz
Invoke-RestMethod http://127.0.0.1:4000/readyz
```

### 4. 创建 API key 并注册模型

管理 API 使用 master key 认证。

```powershell
$master = "你的 master key"

# 创建推理用 API key；明文只在这一次响应中返回
$keyResponse = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/keys `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"name":"local-dev"}'

$key = $keyResponse.key
$key

# 注册一个 fake 模型（需要 GATEWAY_FAKE_PROVIDER_ENABLED=true）
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/models `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"id":"fake-echo","provider":"fake","upstream_model":"fake-echo"}'
```

### 5. 调用推理 API

非流式：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/v1/chat/completions `
  -Headers @{ Authorization = "Bearer $key" } `
  -ContentType "application/json" `
  -Body '{"model":"fake-echo","messages":[{"role":"user","content":"hello"}]}'
```

流式（PowerShell 下显式调用 `curl.exe`，避免 `curl` 别名差异）：

```powershell
'{"model":"fake-echo","messages":[{"role":"user","content":"hello"}],"stream":true}' |
  Set-Content body.json -Encoding utf8

curl.exe -N -X POST http://127.0.0.1:4000/v1/chat/completions `
  -H "Authorization: Bearer $key" `
  -H "Content-Type: application/json" `
  --data-binary "@body.json"

Remove-Item body.json
```

流式响应为 SSE：每个事件是 `data: <json>`，以 `data: [DONE]` 结束。

查看模型列表：

```powershell
Invoke-RestMethod http://127.0.0.1:4000/v1/models `
  -Headers @{ Authorization = "Bearer $key" }
```

吊销 key（`id` 来自创建响应）：

```powershell
Invoke-RestMethod -Method Delete `
  -Uri "http://127.0.0.1:4000/api/v1/keys/$($keyResponse.id)" `
  -Headers @{ Authorization = "Bearer $master" }
```

## 接入真实 OpenAI

在 `.env` 中设置：

```dotenv
GATEWAY_OPENAI_API_KEY=sk-...
GATEWAY_OPENAI_BASE_URL=https://api.openai.com/v1
```

重启服务后，用管理 API 注册模型：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/models `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"id":"gpt-4o-mini","provider":"openai","upstream_model":"gpt-4o-mini"}'
```

客户端只使用网关返回的 `gpt-4o-mini`，上游模型名变化时无需改客户端。

## 配置项

| 变量 | 说明 |
|---|---|
| `GATEWAY_ENVIRONMENT` | 必填。`development` / `test` / `production` |
| `GATEWAY_MASTER_KEY` | 必填。管理 API 凭据；至少 16 字符，production 至少 32 |
| `GATEWAY_LOG_LEVEL` | 默认 `INFO` |
| `GATEWAY_STORAGE_BACKEND` | `memory` 或 `postgres` |
| `GATEWAY_DATABASE_URL` | postgres 模式必填，例如 `postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway` |
| `GATEWAY_REDIS_URL` | 预留，当前未使用 |
| `GATEWAY_OPENAI_API_KEY` | 为空时不注册 OpenAI provider |
| `GATEWAY_OPENAI_BASE_URL` | 默认 `https://api.openai.com/v1` |
| `GATEWAY_FAKE_PROVIDER_ENABLED` | 仅开发/测试使用，production 禁止开启 |
| `GATEWAY_REQUEST_TIMEOUT_SECONDS` | 上游请求总超时，默认 60 |
| `GATEWAY_CONNECT_TIMEOUT_SECONDS` | 连接超时，默认 10 |
| `GATEWAY_MAX_RETRIES` | 首个字节前的最大重试次数，默认 2（上限 5） |

`production` 会强制要求 `postgres` 后端、禁用 fake provider，并拒绝占位或过短的 master key，避免误用示例配置上线。

## 数据库与迁移

启动 PostgreSQL（仅监听本地回环）：

```powershell
docker compose up -d postgres
```

执行迁移：

```powershell
$env:GATEWAY_DATABASE_URL = "postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway"
uv run alembic upgrade head
```

然后把 `.env` 改为：

```dotenv
GATEWAY_STORAGE_BACKEND=postgres
GATEWAY_DATABASE_URL=postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway
```

迁移只读取 `GATEWAY_DATABASE_URL`，不需要 master key。服务启动时不会自动迁移，部署时必须单独执行迁移步骤。

Redis 为后续限流与缓存预留，可用 profile 启动：

```powershell
docker compose --profile redis up -d
```

## 测试与代码检查

```powershell
# 单元测试（默认不访问数据库）
uv run pytest

# 代码检查
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

PostgreSQL 集成测试默认跳过，显式提供测试库后运行：

```powershell
$env:GATEWAY_TEST_DATABASE_URL = "postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway"
uv run pytest -m integration
```

集成测试会执行 `alembic upgrade head` 并清空表，请使用专用测试数据库。

## 管理台

```powershell
cd ui
npm install
npm run dev
```

默认打开 `http://localhost:5173`。开发服务器把 `/healthz`、`/readyz`、`/api`、`/v1` 代理到 `http://127.0.0.1:4000`；如需修改：

```powershell
$env:VITE_PROXY_TARGET = "http://127.0.0.1:4000"
npm run dev
```

在页面中填入 master key 后即可查看后端健康状态与模型列表。master key 只保存在当前页面的内存中，不会写入 localStorage、sessionStorage、cookie 或 URL。

前端检查：

```powershell
npm run lint
npm run typecheck
npm test
npm run format:check
npm run build
```

构建产物在 `ui/dist`，应由与 API 同源的静态服务器托管；MVP 不提供 CORS 放宽，前端通过同源或开发代理访问后端。

## 错误格式

所有错误返回 OpenAI 兼容结构，并带 `x-request-id` 响应头：

```json
{
  "error": {
    "message": "Invalid API key",
    "type": "authentication_error",
    "param": null,
    "code": "invalid_api_key",
    "request_id": "3f6c1d0e9a5b4c7e8f2a1b3c4d5e6f70"
  }
}
```

流式请求在返回响应头之前就完成首个 chunk 的拉取，因此上游的认证失败、超时、限流会以正常 JSON 错误返回。若错误发生在流开始之后，网关会发送一条 `data: {"error": ...}` 事件，再发送 `data: [DONE]`，此时 HTTP 状态码已经是 200。

## 项目结构

```text
src/llm_gateway/     后端应用（api、auth、providers、services、storage、schemas）
alembic/             数据库迁移
tests/               pytest 单元与集成测试
ui/                  React + Vite 管理台
notes/               英文设计笔记
architecture.md      LiteLLM 架构分析
design.md            LLM-GateAway 设计建议
```

## 安全说明

- 不要把 `.env`、API key 或 master key 提交到仓库。
- 推理 key 只以 SHA-256 哈希存储；明文仅在创建响应中出现一次。
- master key 只从环境变量读取，且不能用于推理端点；推理 key 也不能访问管理 API。
- 日志不记录提示词、补全内容、Authorization 头或完整密钥。
- 上游错误信息对外做通用化处理，避免泄露凭据或内部地址。
- 默认只在本机回环地址暴露 PostgreSQL/Redis；生产环境请放在反向代理与 TLS 之后。

## 已知限制

- 仅实现 OpenAI provider 与 fake provider；其他厂商适配器尚未加入。
- 每个模型对应一个上游模型，不支持多 deployment、权重、fallback 或 cooldown。
- 没有预算、计费、限流、guardrail、缓存、审计日志与多租户。
- 模型配置只有创建、列出、删除，没有更新接口；修改需删除后重建。
- `/v1/models` 最多返回 1000 条；管理 API 使用 offset 分页。
- 每个已认证推理请求都会写一次 `last_used_at`，高并发下需要改为采样或批处理。
- 管理台为只读骨架，不提供 key 管理与模型注册表单。
- 迁移需要手动执行，未提供服务启动时自动迁移。

## 相关文档

- `architecture.md`：LiteLLM 的组件、请求流与关键文件分析
- `design.md`：本项目的设计原则、技术选型与演进路线
- `notes/`：分阶段设计笔记（英文），记录取舍与风险
