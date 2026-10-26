# 租户、API Key 与模型注册验证记录

本文记录在 Docker Compose 部署（8080 单入口）下，从空数据库完成 **租户创建 → 模型注册 → API key 生成 → 真实 DeepSeek 调用 → 用量查询 → key 吊销** 的完整过程。

- 环境：`GATEWAY_ENVIRONMENT=production`，DeepSeek provider 已配置，fake provider 关闭
- 入口：管理台/API 均为 `http://127.0.0.1:8080`
- master key 从 `.env.docker` 读取，不打印
- API key 明文只在创建响应中出现一次，本文不记录明文
- 管理台是只读的：模型、租户、key 都通过管理 API 创建

本地开发（非 Docker）把下文所有 `8080` 换成 `4000` 即可。

## 1. 前置检查

```powershell
docker compose --env-file .env.docker --profile app ps -a
Invoke-RestMethod http://127.0.0.1:8080/healthz
Invoke-RestMethod http://127.0.0.1:8080/readyz
```

本次实测状态：

```text
migrate   Exited (0)
postgres  healthy
backend   healthy
ui        healthy
/healthz  {"status":"ok","version":"0.1.0"}
/readyz   {"status":"ok","checks":{"database":"ok"}}
alembic   0004 (head)
```

## 2. 读取 master key（不打印）

```powershell
$master = (Get-Content .env.docker |
  Where-Object { $_ -match '^GATEWAY_MASTER_KEY=' } |
  Select-Object -First 1).Substring('GATEWAY_MASTER_KEY='.Length)

$admin = @{ Authorization = "Bearer $master" }
$base = "http://127.0.0.1:8080"
```

后续所有管理 API 都使用 `$admin`；推理 API 使用 `sk-gw-...` key，不能混用。

## 3. 创建租户

```powershell
$tenants = (Invoke-RestMethod "$base/api/v1/tenants?limit=100" -Headers $admin).items
$tenant = $tenants | Where-Object { $_.name -eq 'local-dev' } | Select-Object -First 1

if (-not $tenant) {
  $tenant = Invoke-RestMethod -Method Post `
    -Uri "$base/api/v1/tenants" `
    -Headers $admin `
    -ContentType "application/json" `
    -Body '{"name":"local-dev"}'
}

$tenant
```

实测结果：创建成功，返回 201。

```text
name: local-dev
id:   96b52fdf-7c6e-4933-bf77-f9b0ac820f42
limits: monthly_token_quota=null, requests_per_minute=null
```

`POST /api/v1/tenants` 的 `name` 唯一；已存在时不要重复创建，先按名称查询。

## 4. 注册模型

```powershell
Invoke-RestMethod -Method Post `
  -Uri "$base/api/v1/models" `
  -Headers $admin `
  -ContentType "application/json" `
  -Body '{"id":"deepseek-flash","provider":"deepseek","upstream_model":"deepseek-flash"}'
```

实测结果：

```json
{
  "id": "deepseek-flash",
  "provider": "deepseek",
  "upstream_model": "deepseek-flash",
  "enabled": true
}
```

说明：

- `id` 是网关暴露给客户端的公共模型名；`upstream_model` 是 DeepSeek 的真实模型 id。两者可以不同。
- 模型 id 以 DeepSeek 当前文档为准（例如 `deepseek-flash`、`deepseek-v4-pro`）；旧的 `deepseek-chat` / `deepseek-reasoner` 已停用。
- provider 必须在 backend 启动时已配置，否则返回 400 `provider_not_configured`。
- 重复注册返回 409 `duplicate_model`。

## 5. 生成 API key

```powershell
$keyName = "local-dev-key-$(Get-Date -Format 'yyyyMMddHHmmss')"
$k = Invoke-RestMethod -Method Post `
  -Uri "$base/api/v1/keys" `
  -Headers $admin `
  -ContentType "application/json" `
  -Body (@{ name = $keyName; tenant_id = $tenant.id } | ConvertTo-Json)

$key = $k.key
$key   # 明文只在这里出现一次，保存到安全位置
```

实测结果：

```text
name: local-dev-key-...
prefix: sk-gw-xxxxxx
tenant_id: 96b52fdf-7c6e-4933-bf77-f9b0ac820f42
```

- 服务端只保存 SHA-256 哈希和展示前缀；关闭终端后无法再取回明文。
- 列出 key 时只看得到名称、前缀和状态，没有明文或 hash：

```powershell
Invoke-RestMethod "$base/api/v1/keys?tenant_id=$($tenant.id)" -Headers $admin
```

## 6. 用 key 验证模型与真实调用

```powershell
$auth = @{ Authorization = "Bearer $key" }

# 可用模型
Invoke-RestMethod "$base/v1/models" -Headers $auth

# 真实 DeepSeek 调用
$body = @{
  model = "deepseek-flash"
  messages = @(@{ role = "user"; content = "Reply with exactly: gateway ok" })
  max_tokens = 32
} | ConvertTo-Json -Depth 5

$r = Invoke-RestMethod -Method Post `
  -Uri "$base/v1/chat/completions" `
  -Headers $auth `
  -ContentType "application/json" `
  -Body $body

$r.model
$r.choices[0].message.content
$r.usage
```

本次实测结果：

```text
/v1/models  -> data 包含 deepseek-flash
chat status -> 200
model       -> deepseek-flash
content     -> gateway ok
usage       -> prompt_tokens=36, completion_tokens=32, total_tokens=68
```

## 7. 查看用量

```powershell
Invoke-RestMethod `
  -Uri "$base/api/v1/usage/summary?tenant_id=$($tenant.id)" `
  -Headers $admin
```

本次快照：

```text
requests=2
prompt_tokens=74
completion_tokens=148
cached_tokens=0
total_tokens=222
```

其中本次验证的调用为 `36 / 32 / 68`；快照里另有一次 154-token 调用（同一租户的历史调用）。用量按租户、key、模型归属，流式调用同样会记录。

## 8. 吊销 key 并验证

```powershell
Invoke-RestMethod -Method Delete `
  -Uri "$base/api/v1/keys/$($k.id)" `
  -Headers $admin
```

再调用一次推理接口：

```powershell
try {
  Invoke-RestMethod "$base/v1/models" -Headers $auth
} catch {
  $_.Exception.Response.StatusCode.value__
  ($_.ErrorDetails.Message | ConvertFrom-Json).error.code
}
```

实测结果：

```text
DELETE /api/v1/keys/{id} -> 204
再次请求                 -> 401
error.code               -> invalid_api_key
```

## 9. 可复用脚本

以下脚本会：读取 master key → 确保租户存在 → 注册模型（容忍 409）→ 新建 key → 调用一次 → 打印用量与吊销命令。**运行后会得到一个新的有效 key，测试完请按输出的命令吊销。**

```powershell
$master = (Get-Content .env.docker |
  Where-Object { $_ -match '^GATEWAY_MASTER_KEY=' } |
  Select-Object -First 1).Substring('GATEWAY_MASTER_KEY='.Length)
$admin = @{ Authorization = "Bearer $master" }
$base = "http://127.0.0.1:8080"

$tenant = (Invoke-RestMethod "$base/api/v1/tenants?limit=100" -Headers $admin).items |
  Where-Object { $_.name -eq 'local-dev' } | Select-Object -First 1
if (-not $tenant) {
  $tenant = Invoke-RestMethod -Method Post -Uri "$base/api/v1/tenants" `
    -Headers $admin -ContentType "application/json" -Body '{"name":"local-dev"}'
}

try {
  Invoke-RestMethod -Method Post -Uri "$base/api/v1/models" -Headers $admin `
    -ContentType "application/json" `
    -Body '{"id":"deepseek-flash","provider":"deepseek","upstream_model":"deepseek-flash"}' |
    Out-Null
} catch {
  if ($_.Exception.Response.StatusCode.value__ -ne 409) { throw }
}

$k = Invoke-RestMethod -Method Post -Uri "$base/api/v1/keys" -Headers $admin `
  -ContentType "application/json" `
  -Body (@{ name = "local-dev-key-$(Get-Date -Format 'yyyyMMddHHmmss')"; tenant_id = $tenant.id } | ConvertTo-Json)

$key = $k.key
"API key (save it now): $key"

$body = @{
  model = "deepseek-flash"
  messages = @(@{ role = "user"; content = "Reply with exactly: gateway ok" })
  max_tokens = 32
} | ConvertTo-Json -Depth 5

$r = Invoke-RestMethod -Method Post -Uri "$base/v1/chat/completions" `
  -Headers @{ Authorization = "Bearer $key" } `
  -ContentType "application/json" -Body $body
"content: $($r.choices[0].message.content)"
"usage: $($r.usage | ConvertTo-Json -Compress)"

# 测试完成后吊销
"Revoke with:"
"Invoke-RestMethod -Method Delete -Uri $base/api/v1/keys/$($k.id) -Headers @{ Authorization = 'Bearer 你的 master key' }"
```

## 10. 检查清单

| 检查项 | 预期 |
|---|---|
| `/healthz` | 200，`status=ok` |
| `/readyz` | 200，`database=ok` |
| 创建租户 | 201，返回唯一 `id` |
| 注册模型 | 201；重复为 409；provider 未配置为 400 |
| 创建 key | 201，明文只出现一次 |
| key 列表 | 只有名称/前缀/状态，无明文/hash |
| `/v1/models` | 包含已启用模型 |
| 真实调用 | 200，返回内容与 usage |
| 用量汇总 | requests/token 增加 |
| 吊销 key | 204；再次请求 401 `invalid_api_key` |

## 11. 常见错误

| 现象 | 原因 | 处理 |
|---|---|---|
| 400 `provider_not_configured` | backend 启动时没有对应 provider key | 在 `.env.docker` 填 key，重建 backend |
| 401 `missing_api_key` | 没带 `Authorization` | 加 `Bearer <推理 key>` |
| 401 `invalid_api_key` | key 错误、过期或已吊销 | 重新创建；不要用 master key 调推理 |
| 401 `master_key_not_allowed` | 用 master key 调推理 | 换成 `sk-gw-...` |
| 404 `model_not_found` | 模型未注册或拼写错误 | 先 `POST /api/v1/models` |
| 409 `duplicate_model` | 同名模型已存在 | 直接使用，或删除后重建 |
| 502 `upstream_auth_failed` | DeepSeek key 无效 | 检查上游 key 与 backend 日志 |
| 502/504 upstream | 模型不存在、限流或超时 | 换模型 id；看 `x-request-id` 日志 |

## 12. 安全与清理

- 本文不包含任何真实 key；`.env.docker` 已被 `.gitignore` 忽略。
- 验证用临时 key 已吊销；不要提交 API key 明文。
- 管理台不提供 key 管理或模型注册表单，这是有意的只读设计。
- 用量记录属于审计数据，没有删除 API；需要清空测试库时可用 `docker compose --env-file .env.docker --profile app down -v`（会删除数据库，谨慎）。

## 相关文档

- [`docs/verification.md`](verification.md)：完整的端到端验证指南（DeepSeek 配置、流式、SDK）
- [`docs/docker.md`](docker.md)：Docker Compose 部署、配置、迁移与排错
- [`README.md`](../README.md)：项目能力与快速开始
