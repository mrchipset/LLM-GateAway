# LLM-GateAway

[English](README.md) | **简体中文**

自托管、多 provider 的 OpenAI 兼容 LLM 网关。当前状态：可运行的后端、OpenAI / DeepSeek（OpenAI 兼容）/ Fake provider、租户化 API key、模型注册表、PostgreSQL 持久化、Token 用量统计、租户配额与限流，以及带用量面板的管理台。

## 当前能力

- OpenAI 兼容的 `POST /v1/chat/completions`，支持 `stream=true` 与 `stream=false`
- `GET /v1/models` 返回已启用的模型
- Provider 抽象：OpenAI、DeepSeek（OpenAI 兼容）adapter 与确定性 Fake provider
- API key 认证：只存 SHA-256 哈希，支持过期与吊销，并归属到一个租户
- Token 用量记录与汇总：输入、输出、缓存命中，按租户、key、模型归属
- 租户级月度 token 配额与每分钟请求限流（429 + `Retry-After`）
- 管理 API：`/api/v1/keys`、`/api/v1/models`、`/api/v1/tenants`、`/api/v1/usage/{summary,by-key,series}`，由 master key 保护
- PostgreSQL 持久化（SQLAlchemy 2 async + Alembic），默认也可用内存模式本地开发
- 结构化 JSON 日志、request id、`/healthz` 与 `/readyz`
- React + Vite + TypeScript 管理台：健康状态、模型列表与用量面板

不在本次范围：预算与计费、guardrail、MCP/Agent、租户级权限模型与 SSO/JWT/OAuth、Redis 限流/缓存、高级路由与 fallback、完整 Dashboard。

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

# 先创建租户；每个 API key 必须归属一个租户
$tenant = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/tenants `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"name":"local-dev"}'

# 创建推理用 API key；明文只在这一次响应中返回
$keyResponse = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/keys `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body (@{ name = "local-dev"; tenant_id = $tenant.id } | ConvertTo-Json)

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

## 接入 DeepSeek

DeepSeek 的 Chat Completions 接口与 OpenAI 兼容，复用同一个 adapter，只需要单独的 key 与 base URL：

```dotenv
GATEWAY_DEEPSEEK_API_KEY=sk-...
GATEWAY_DEEPSEEK_BASE_URL=https://api.deepseek.com
```

重启服务后注册模型。模型 id 以 DeepSeek 当前文档为准；旧的 `deepseek-chat` / `deepseek-reasoner` 已停用：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/models `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"id":"deepseek-flash","provider":"deepseek","upstream_model":"deepseek-flash"}'
```

注意事项：

- 思考模式的 `reasoning_content` 会原样透传给客户端（流式 delta 同样保留）。
- 带 `tools` 的多轮对话中，历史 assistant 消息里的 `reasoning_content` 必须回传，否则 DeepSeek 返回 400。
- DeepSeek 在 `stream_options.include_usage=true` 时把 usage 附在最后一个内容 chunk 上，没有独立的 usage-only chunk；网关按原样转发。
- 推理模型首 token 可能较慢，必要时提高 `GATEWAY_REQUEST_TIMEOUT_SECONDS`。

## Token 用量统计

每个成功请求都会记录一条用量（租户、API key、模型、provider），包含输入、输出、总 token 与缓存命中 token。流式请求同样会记录：网关会向上游请求 usage，但只有客户端显式设置 `stream_options.include_usage=true` 时，usage chunk 才会转发给客户端。

查询汇总（master key）：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:4000/api/v1/usage/summary?tenant_id=$($tenant.id)&since=2026-10-01T00:00:00Z" `
  -Headers @{ Authorization = "Bearer $master" }
```

可选参数：`tenant_id`、`model_id`、`since`、`until`。时间必须是带时区的 RFC 3339 字符串，区间为左闭右开 `[since, until)`；未知租户返回 404。

响应示例：

```json
{
  "prompt_tokens": 1200,
  "completion_tokens": 340,
  "cached_tokens": 800,
  "total_tokens": 1540,
  "requests": 12,
  "by_model": [
    {
      "model_id": "deepseek-flash",
      "provider": "deepseek",
      "prompt_tokens": 1200,
      "completion_tokens": 340,
      "cached_tokens": 800,
      "total_tokens": 1540,
      "requests": 12
    }
  ]
}
```

语义说明：

- `cached_tokens` 是 `prompt_tokens` 的子集，不是额外的一档。它来自 OpenAI 的 `prompt_tokens_details.cached_tokens` 或 DeepSeek 的 `prompt_cache_hit_tokens`；不要把它与 `prompt_tokens` 相加。
- `total_tokens` 使用上游上报值，不做重新计算。
- `by_model` 按 `(model_id, provider)` 分组；同一个模型名如果换过 provider，会出现两行。
- 用量写入失败不会影响推理响应，只记录 `usage_record_failed` 告警；客户端在 usage 到达前断开时可能没有记录。

按 key 汇总：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:4000/api/v1/usage/by-key?tenant_id=$($tenant.id)&limit=100" `
  -Headers @{ Authorization = "Bearer $master" }
```

返回按总 token 降序的 `items`（key 名称、前缀、输入/输出/缓存/总 token、请求数）。`limit` 默认 100、最大 500；无法解析的 key 显示 `null`。

时间序列：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:4000/api/v1/usage/series?tenant_id=$($tenant.id)&bucket=day&since=2026-10-01T00:00:00Z" `
  -Headers @{ Authorization = "Bearer $master" }
```

- `since` / `until` 缺省为最近 30 天；只传 `since` 时 `until` 默认为当前时间。
- `bucket` 支持 `hour` 与 `day`，返回按 UTC 对齐且**补零**的 `points`（最多 1000 个桶），适合直接画图。
- 管理台已提供用量面板；没有成本换算。

## 租户配额与限流

为租户设置月度 token 配额与每分钟请求数（`null` 表示不限，值必须 ≥ 1）：

```powershell
Invoke-RestMethod -Method Patch `
  -Uri "http://127.0.0.1:4000/api/v1/tenants/$($tenant.id)" `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"monthly_token_quota":1000000,"requests_per_minute":60}'
```

- `monthly_token_quota`：UTC 自然月内按上游上报的 `total_tokens` 累计。达到配额后，`POST /v1/chat/completions` 返回 429 `tenant_quota_exceeded`。
- `requests_per_minute`：固定 60 秒窗口。超出后返回 429 `rate_limited`，并带 `Retry-After`（秒，1–60）。
- PATCH 只修改请求体里出现的字段；显式传 `null` 清除对应限制。
- 配额是软限制：请求前检查，并发或进行中的请求可能小幅超出；用量写入失败也会造成偏差。
- 被限流或超配额的请求不会产生用量记录。
- 限流只作用于 `POST /v1/chat/completions`；`/v1/models`、健康检查与管理 API 不受租户限流。
- PostgreSQL 后端使用单行原子计数，支持多 worker；内存后端仅用于本地开发与测试。

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
| `GATEWAY_DEEPSEEK_API_KEY` | 为空时不注册 DeepSeek provider |
| `GATEWAY_DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com` |
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

在页面中填入 master key 后即可查看后端健康状态、模型列表与用量面板。用量面板支持：

- `Models / Usage` 标签切换
- 租户筛选（含“全部租户”），选中租户时只读显示其配额与限流；租户列表最多 100 个，超出会显示提示
- 7 / 30 / 90 天滚动范围，`since` 对齐到 UTC 零点；最后一根柱是“今日至今”的部分桶
- 请求数、输入/输出/缓存/总 token 汇总（缓存按上游上报值展示，标记为输入的子集）
- 按 UTC 日对齐、补零的每日总量柱状图
- 按 key 的用量明细（最多 100 个 key）

master key 只保存在当前页面的内存中，不会写入 localStorage、sessionStorage、cookie 或 URL；断开连接会清除所有查询缓存。

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
.opencode/skills/    仓库级 Agent Skills
```

## 安全说明

- 不要把 `.env`、API key 或 master key 提交到仓库。
- 推理 key 只以 SHA-256 哈希存储；明文仅在创建响应中出现一次。
- master key 只从环境变量读取，且不能用于推理端点；推理 key 也不能访问管理 API。
- 日志不记录提示词、补全内容、Authorization 头或完整密钥。
- 上游错误信息对外做通用化处理，避免泄露凭据或内部地址。
- 默认只在本机回环地址暴露 PostgreSQL/Redis；生产环境请放在反向代理与 TLS 之后。

## 已知限制

- 仅实现 OpenAI、DeepSeek（OpenAI 兼容）与 fake provider；Anthropic、Bedrock、Vertex 等非 OpenAI 协议尚未加入。
- 每个模型对应一个上游模型，不支持多 deployment、权重、fallback 或 cooldown。
- 没有计费/账单、按 key 或模型的限额、突发整形（token bucket）；配额是软限制。
- 限流是固定 60 秒窗口，只到租户级；内存后端的计数仅限单进程。
- 创建 key 必须指定 `tenant_id`（对旧调用方是破坏性变更）；没有租户删除或重命名接口。
- `usage_records` 没有保留策略或归档任务，会随请求持续增长；没有成本换算。
- 流式请求在 usage 到达前断开时不会留下用量记录；写入超时或失败也只记录告警。
- 模型配置只有创建、列出、删除，没有更新接口；修改需删除后重建。
- `/v1/models` 最多返回 1000 条；管理 API 使用 offset 分页。
- 每个已认证推理请求都会写一次 `last_used_at`，高并发下需要改为采样或批处理。
- 管理台不提供 key 管理、模型注册或限额编辑；用量面板只读、固定日粒度，按 key 与租户各最多展示 100 条，最后一根柱为今日至今。
- 迁移需要手动执行，未提供服务启动时自动迁移。

## 相关文档

- `architecture.md`：LiteLLM 的组件、请求流与关键文件分析
- `design.md`：本项目的设计原则、技术选型与演进路线
- `notes/`：分阶段设计笔记（英文），记录取舍与风险
- [`docs/verification.md`](docs/verification.md)：DeepSeek、租户 key 与网关调用的逐步验证

## Agent skill

仓库级技能：[`.opencode/skills/llm-gateway/SKILL.md`](.opencode/skills/llm-gateway/SKILL.md)。其中记录了仓库结构、命令、必须保持的约束与验证流程。可以直接在仓库内使用，或复制到 `~/.config/opencode/skills/` 作为全局技能。

## 许可证

MIT——见 [LICENSE](LICENSE)。
