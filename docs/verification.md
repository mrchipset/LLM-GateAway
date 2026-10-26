# LLM-GateAway 端到端验证指南

本指南从零验证三件事：

1. 配置 DeepSeek provider（上游 key）；
2. 创建租户与推理用 API key；
3. 通过网关完成非流式、流式与 OpenAI SDK 调用，并核对用量。

命令在 Windows PowerShell 7 下验证；bash 用户把 `Invoke-RestMethod` 改写为等价的 `curl` 即可。

> 使用 Docker Compose 启动完整栈时，先按 [`docs/docker.md`](docker.md) 操作；把下文的 `http://127.0.0.1:4000` 换成 `http://127.0.0.1:8080`（管理台与 API 共用一个入口），其余步骤不变。

> 三类凭据不要混用：
>
> | 凭据 | 用途 | 存放位置 |
> |---|---|---|
> | DeepSeek API key | 网关访问上游 | `.env`，只从环境变量读取 |
> | `GATEWAY_MASTER_KEY` | 管理 API（租户、key、模型、用量） | `.env` / secret manager |
> | `sk-gw-...` 推理 key | 客户端调用 `/v1/*` | 只保存在客户端，服务端只存哈希 |

## 0. 前置条件

- Windows PowerShell 7
- Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)
- 一个 DeepSeek API key（在 DeepSeek 控制台创建）
- 默认端口 `4000`；如被占用，请把全文的 `4000` 替换成其他端口
- PostgreSQL 可选。本指南先用内存模式（最快）；持久化切换见第 7 节

没有 DeepSeek key 也可以先打通链路：见第 2.5 节的 fake provider。

## 1. 准备配置并启动服务

```powershell
uv sync
Copy-Item .env.example .env
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

编辑 `.env`：

```dotenv
GATEWAY_ENVIRONMENT=development
GATEWAY_MASTER_KEY=<粘贴上一步生成的随机值>
GATEWAY_STORAGE_BACKEND=memory
GATEWAY_FAKE_PROVIDER_ENABLED=false
```

说明：

- 占位值（例如 `change-me...`）会被拒绝；master key 至少 16 字符，production 至少 32。
- `GATEWAY_ENVIRONMENT` 必填，没有默认值。
- 内存模式重启后数据丢失，适合验证；生产必须使用 `postgres`。

在终端 A 启动服务：

```powershell
uv run uvicorn llm_gateway.app:create_app --factory --reload --port 4000
```

在终端 B 设置后续命令共用的变量并检查健康状态：

```powershell
$master = "粘贴你的 master key"
$admin = @{ Authorization = "Bearer $master" }

Invoke-RestMethod http://127.0.0.1:4000/healthz
Invoke-RestMethod http://127.0.0.1:4000/readyz
```

预期：

```json
{"status":"ok","version":"0.1.0"}
{"status":"ok","checks":{}}
```

内存模式下 `checks` 为空；PostgreSQL 模式会显示 `"database":"ok"`。

## 2. 增加 DeepSeek key

### 2.1 写入上游凭据

在 `.env` 中加入（不要把真实 key 提交到仓库）：

```dotenv
GATEWAY_DEEPSEEK_API_KEY=sk-...
GATEWAY_DEEPSEEK_BASE_URL=https://api.deepseek.com
```

`GATEWAY_DEEPSEEK_BASE_URL` 默认就是 `https://api.deepseek.com`，通常无需修改。

### 2.2 重启服务

配置在启动时读取。回到终端 A 按 `Ctrl+C`，再次启动：

```powershell
uv run uvicorn llm_gateway.app:create_app --factory --reload --port 4000
```

### 2.3 注册模型

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/models `
  -Headers $admin `
  -ContentType "application/json" `
  -Body '{"id":"deepseek-flash","provider":"deepseek","upstream_model":"deepseek-flash"}'
```

预期返回 201：

```json
{
  "id": "deepseek-flash",
  "provider": "deepseek",
  "upstream_model": "deepseek-flash",
  "enabled": true,
  "created_at": "2026-10-25T12:00:00Z"
}
```

- `id` 是网关对客户端暴露的公共模型名，`upstream_model` 是 DeepSeek 的真实模型 id；两者可以不同。
- 当前 DeepSeek 模型 id 以官方文档为准（例如 `deepseek-flash`、`deepseek-v4-pro`）；旧的 `deepseek-chat` / `deepseek-reasoner` 已停用。
- 如果返回 400 `provider_not_configured`：`.env` 里没有 DeepSeek key，或修改后没有重启。

也可以注册一个别名，验证公共名与上游名解耦：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/models `
  -Headers $admin `
  -ContentType "application/json" `
  -Body '{"id":"deepseek-reasoning","provider":"deepseek","upstream_model":"deepseek-v4-pro"}'
```

### 2.4 可选：同时接入 OpenAI

```dotenv
GATEWAY_OPENAI_API_KEY=sk-...
GATEWAY_OPENAI_BASE_URL=https://api.openai.com/v1
```

重启后注册：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/models `
  -Headers $admin `
  -ContentType "application/json" `
  -Body '{"id":"gpt-4o-mini","provider":"openai","upstream_model":"gpt-4o-mini"}'
```

### 2.5 用 fake provider 先验证链路（可选）

没有上游 key 时，把 `.env` 改为：

```dotenv
GATEWAY_FAKE_PROVIDER_ENABLED=true
```

重启并注册一个确定性模型：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/models `
  -Headers $admin `
  -ContentType "application/json" `
  -Body '{"id":"fake-echo","provider":"fake","upstream_model":"fake-echo"}'
```

后续第 3、4 节把 `deepseek-flash` 换成 `fake-echo` 即可。fake provider 的回复是确定性的，不访问网络。

## 3. 创建租户与推理 key

每个 API key 必须归属一个租户。

### 3.1 创建租户

```powershell
$tenant = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/tenants `
  -Headers $admin `
  -ContentType "application/json" `
  -Body '{"name":"verification"}'

$tenant
```

预期返回 201，包含 `id`、`name`、`created_at`、`monthly_token_quota: null`、`requests_per_minute: null`。

### 3.2 创建推理 key

```powershell
$keyResponse = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/keys `
  -Headers $admin `
  -ContentType "application/json" `
  -Body (@{ name = "verification-key"; tenant_id = $tenant.id } | ConvertTo-Json)

$key = $keyResponse.key
$key
```

预期返回 201：

```json
{
  "id": "…",
  "name": "verification-key",
  "tenant_id": "…",
  "key": "sk-gw-…",
  "key_prefix": "sk-gw-…",
  "created_at": "2026-10-25T12:00:00Z",
  "expires_at": null
}
```

`key` 明文只在这里出现一次；服务端只保存 SHA-256 哈希和展示用前缀。需要过期时间时加 `expires_at`（未来时间，带时区）：

```powershell
$expires = (Get-Date).ToUniversalTime().AddDays(30).ToString("o")
$keyResponse = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/keys `
  -Headers $admin `
  -ContentType "application/json" `
  -Body (@{ name = "verification-30d"; tenant_id = $tenant.id; expires_at = $expires } | ConvertTo-Json)
```

### 3.3 验证 key 列表

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:4000/api/v1/keys?tenant_id=$($tenant.id)" `
  -Headers $admin
```

预期：`items` 包含名称与前缀，`total` 正确；响应中没有明文 `key`，也没有 `key_hash`。

### 3.4 可选：设置配额与限流

```powershell
Invoke-RestMethod -Method Patch `
  -Uri "http://127.0.0.1:4000/api/v1/tenants/$($tenant.id)" `
  -Headers $admin `
  -ContentType "application/json" `
  -Body '{"monthly_token_quota":1000000,"requests_per_minute":60}'
```

- `monthly_token_quota`：UTC 自然月累计 `total_tokens`。
- `requests_per_minute`：固定 60 秒窗口。
- `null` 表示不限；值必须 ≥ 1。

## 4. 通过网关调用

所有推理请求使用 `sk-gw-...` key，而不是 master key。

### 4.1 查看可用模型

```powershell
Invoke-RestMethod http://127.0.0.1:4000/v1/models `
  -Headers @{ Authorization = "Bearer $key" }
```

预期 `data` 中包含 `deepseek-flash`（或 `fake-echo`）；被禁用的模型不会出现。

### 4.2 非流式调用

```powershell
$body = @{
  model = "deepseek-flash"
  messages = @(@{ role = "user"; content = "Explain what an LLM gateway is in one sentence." })
  max_tokens = 128
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/v1/chat/completions `
  -Headers @{ Authorization = "Bearer $key" } `
  -ContentType "application/json" `
  -Body $body

$response.model
$response.choices[0].message.content
$response.usage
```

预期：

- `model` 是公共模型名 `deepseek-flash`（即使上游 id 不同）。
- `choices[0].message.content` 是回答；思考模型可能额外带 `reasoning_content`。
- `usage` 包含 `prompt_tokens`、`completion_tokens`、`total_tokens`；DeepSeek 可能还带缓存字段。

### 4.3 流式调用（SSE）

```powershell
$streamBody = @{
  model = "deepseek-flash"
  messages = @(@{ role = "user"; content = "Count from one to five." })
  stream = $true
  stream_options = @{ include_usage = $true }
} | ConvertTo-Json -Depth 5

$streamBody | Set-Content body.json -Encoding utf8

curl.exe -N -X POST http://127.0.0.1:4000/v1/chat/completions `
  -H "Authorization: Bearer $key" `
  -H "Content-Type: application/json" `
  --data-binary "@body.json"

Remove-Item body.json
```

预期看到多行 `data: {...}`，最后是：

```text
data: [DONE]
```

说明：

- 网关会先拉取上游首个 chunk 再发送响应头，因此上游鉴权失败/超时会以正常 JSON 错误返回。
- 网关始终向上游请求 usage；只有客户端设置 `include_usage=true` 时才把 usage chunk 转发给客户端，但仍会记账。
- 上游在流开始后出错时，会收到 `data: {"error": ...}`，随后是 `data: [DONE]`，此时 HTTP 状态已经是 200。

### 4.4 OpenAI SDK 调用

先安装 SDK（不需要改项目依赖）：

```powershell
uv run --with openai python -c "import openai; print(openai.__version__)"
```

创建 `verify_gateway.py`（模型名按实际注册的替换）：

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:4000/v1", api_key="sk-gw-...")

response = client.chat.completions.create(
    model="deepseek-flash",
    messages=[{"role": "user", "content": "Say hello in five words."}],
    max_tokens=64,
)
print("model:", response.model)
print("content:", response.choices[0].message.content)
print("usage:", response.usage)

stream = client.chat.completions.create(
    model="deepseek-flash",
    messages=[{"role": "user", "content": "Count to three."}],
    stream=True,
)
for chunk in stream:
    delta = chunk.choices[0].delta.content if chunk.choices else None
    if delta:
        print(delta, end="", flush=True)
print()
```

运行后删除脚本：

```powershell
uv run --with openai python verify_gateway.py
Remove-Item verify_gateway.py
```

SDK 会把 `Authorization: Bearer <key>` 发到网关；base URL 必须以 `/v1` 结尾。

### 4.5 查看用量

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:4000/api/v1/usage/summary?tenant_id=$($tenant.id)" `
  -Headers $admin
```

预期 `requests` 至少为 2（非流式 + 流式），token 数大于 0，`by_model` 中包含刚调用的模型。

也可以按 key 或时间序列查看：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:4000/api/v1/usage/by-key?tenant_id=$($tenant.id)&limit=100" `
  -Headers $admin

Invoke-RestMethod `
  -Uri "http://127.0.0.1:4000/api/v1/usage/series?tenant_id=$($tenant.id)&bucket=day" `
  -Headers $admin
```

## 5. 验证清单

| 检查项 | 命令/操作 | 预期 |
|---|---|---|
| 服务存活 | `GET /healthz` | 200，`status=ok` |
| 就绪 | `GET /readyz` | 200；内存模式 `checks={}`，PG 模式 `database=ok` |
| DeepSeek 已配置 | `POST /api/v1/models` | 201；未配置时 400 `provider_not_configured` |
| 租户 | `POST /api/v1/tenants` | 201，返回 `id` |
| 推理 key | `POST /api/v1/keys` | 201，明文 `key` 只出现一次 |
| key 列表 | `GET /api/v1/keys?tenant_id=…` | 无明文、无 hash |
| 模型列表 | `GET /v1/models` | 包含已启用模型 |
| 非流式 | `POST /v1/chat/completions` | 200，`model` 为公共名，`usage` 有 token 数 |
| 流式 | 同上 `stream=true` | SSE 以 `[DONE]` 结束 |
| 用量 | `GET /api/v1/usage/summary` | `requests` 与 token 增加 |
| 吊销 | `DELETE /api/v1/keys/{id}` | 204；再次调用返回 401 `invalid_api_key` |

## 6. 常见错误

| 现象 | 原因 | 处理 |
|---|---|---|
| 400 `provider_not_configured` | 上游 key 未加载 | 检查 `.env` 并重启 |
| 401 `missing_api_key` | 没有 `Authorization` | 加 `Bearer <推理 key>` |
| 401 `invalid_api_key` | key 错误/过期/已吊销 | 重新创建；不要用 master key 调推理 |
| 401 `master_key_not_allowed` | 用 master key 调推理 | 换成 `sk-gw-...` |
| 404 `model_not_found` | 模型未注册/拼写错误 | 用 `POST /api/v1/models` 注册 |
| 403 `model_disabled` | 模型被禁用 | 删除后重新注册 |
| 429 `rate_limited` | 超过每分钟请求数 | 等待 `Retry-After` |
| 429 `tenant_quota_exceeded` | 月度 token 配额用完 | 提高配额或等下个 UTC 月 |
| 502 `upstream_auth_failed` | DeepSeek key 无效 | 检查上游 key 与服务端日志 |
| 502/504 upstream | 上游限流、超时、不可用 | 查看 `x-request-id` 对应日志 |
| 503 `provider_not_configured` | 服务运行中 provider 被移除 | 恢复配置并重启 |
| 503 `/readyz` | 数据库不可用 | 检查 PostgreSQL 与 DSN |

所有错误响应都包含 `error.code`、`error.request_id` 和 `x-request-id`；排查时把 request id 提供给服务端日志。

## 7. 可选：切换到 PostgreSQL

```powershell
docker compose up -d postgres

$env:GATEWAY_DATABASE_URL = "postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway"
uv run alembic upgrade head
```

把 `.env` 改为：

```dotenv
GATEWAY_STORAGE_BACKEND=postgres
GATEWAY_DATABASE_URL=postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway
```

重启服务；`/readyz` 应显示 `"database":"ok"`。迁移不会在启动时自动执行。

## 8. 收尾

```powershell
# 吊销验证用 key
Invoke-RestMethod -Method Delete `
  -Uri "http://127.0.0.1:4000/api/v1/keys/$($keyResponse.id)" `
  -Headers $admin

# 终端 A：Ctrl+C 停止服务
# 如果启动了 PostgreSQL：
docker compose stop postgres
```

确认：

- `.env` 不在 git 中（`.gitignore` 已覆盖）。
- 不要把 DeepSeek key、master key 或 `sk-gw-...` 粘贴到 issue、文档或提交。
- 内存模式下停止服务即清空验证数据；PostgreSQL 模式需要手动清理表或使用专用库。
