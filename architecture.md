# LiteLLM 架构分析

> 分析对象: `BerriAI/litellm`，本地快照版本 `1.108.0`
> 分析日期: 2026-10-25
> 目的: 为 `LLM-GateAway` 的设计提供一份可落地的参考架构说明

## 1. 项目定位

LiteLLM 是一个以 Python 为核心的 LLM 网关和 SDK。它解决三个问题:

1. 用统一接口调用 100 多家模型提供商，屏蔽 OpenAI、Anthropic、Bedrock、Vertex AI、Azure、Cohere 等协议的差异
2. 在网关层集中做认证、配额、预算、限流、路由、fallback、缓存、审计和可观测性
3. 给企业提供一个可自托管的 AI Gateway，同时保留 SDK 形态供应用直接嵌入

它不是一个单纯的代理转发器。核心价值在于协议转换、策略执行和统一治理。

## 2. 技术栈与规模

| 层 | 技术 |
|---|---|
| 语言 | Python 3.10 到 3.14 |
| Web 框架 | FastAPI + Starlette |
| ASGI Server | uvicorn、Granian、gunicorn |
| 数据校验 | Pydantic v2 |
| 数据库 | PostgreSQL + Prisma |
| 缓存 | Redis、Redis Cluster、内存、磁盘、S3、GCS、Azure Blob、Qdrant |
| 异步 HTTP | httpx、aiohttp、uvloop |
| 管理后台 | Next.js + TypeScript（详见第 13 节） |
| 原生扩展 | Rust + PyO3（maturin） |
| IaC | Go + Terraform Plugin SDK |
| 部署 | Docker、Helm、docker compose |

仓库规模（本次快照）:

- `litellm/` 下约 2,921 个 Python 文件，约 85 万行
- Proxy 层约 817 个 Python 文件
- `litellm/llms/` 下约 152 个 provider 目录
- `litellm/integrations/` 下约 37 个可观测性和数据集成
- `litellm/proxy/guardrails/guardrail_hooks/` 下约 57 个 guardrail 实现
- Proxy 层约 813 个路由装饰器
- `schema.prisma` 中 100 多个数据模型
- 测试目录中 unit 约 3,258 个 Python 文件，integration 约 1,236 个，e2e 约 439 个

规模说明了一个事实: 这是一个功能广度优先的项目，不是一个小而美的网关。

## 3. 总体架构

```text
+-----------------------------------------------------------------------+
|                          Admin UI (Next.js/TS)                        |
|         models / keys / teams / users / budgets / logs / settings      |
+-----------------------------------+-----------------------------------+
                                    | REST + session/token
+-----------------------------------v-----------------------------------+
|                        LiteLLM Proxy (FastAPI)                        |
|                                                                       |
|  AuthN/AuthZ   Budget/RateLimit   Guardrails   Routing   Cache        |
|  Callbacks     Spend Tracking     MCP         Pass-through            |
|                                                                       |
|  +-------------------+   +-------------------+   +------------------+  |
|  | Proxy API layer   |-->| Router            |-->| Provider adapter |  |
|  | (route handlers)  |   | (deployments,     |   | (transformation, |  |
|  |                   |   |  strategies,      |   |  HTTP, streaming)|  |
|  |                   |   |  retries, cooldown)|  |                  |  |
|  +-------------------+   +-------------------+   +------------------+  |
+------------------+----------------------+-----------------------------+
                   |                      |
        +----------v----------+  +--------v-----------+  +----------------+
        | PostgreSQL (Prisma) |  | Redis / caches     |  | ClickHouse     |
        | keys, teams, spend  |  | rate limits, cache |  | spend logs     |
        +---------------------+  +--------------------+  +----------------+
                   |
        +----------v------------------------------------------+
        | External providers: OpenAI, Anthropic, Bedrock, ... |
        +-----------------------------------------------------+

+-----------------------------------------------------------------------+
| Optional Rust layer                                                   |
|  - PyO3 extension: native inference hot paths                          |
|  - litellm-gateway: standalone axum data-plane binary                 |
+-----------------------------------------------------------------------+
```

## 4. 分层说明

### 4.1 SDK Core

入口在 `litellm/main.py`，对外暴露 `completion`、`embedding`、`text_completion`、`transcription`、`image_generation`、`rerank`、`responses` 等函数。SDK 的核心职责:

- 解析 `model` 字符串，识别 provider，例如 `anthropic/claude-sonnet-4-5`
- 把统一的 OpenAI 风格入参转换成 provider 原生请求
- 通过同步或异步 HTTP handler 发起请求
- 把 provider 响应转换回统一格式
- 计算 token、成本和日志
- 处理流式响应、重试、fallback、超时和异常映射

SDK 不依赖 Proxy，可以单独作为库使用。Proxy 是构建在 SDK 和 Router 之上的服务层。

### 4.2 Router

`litellm/router.py` 是网关的模型路由和可靠性层，约 1.5 万行。它管理 `model_list` 中的 deployment，并负责:

- 公开模型名到多个 deployment 的映射
- 负载均衡策略: `simple-shuffle`、`least-busy`、`usage-based-routing`、`latency-based-routing`、`cost-based-routing`、tag-based、LAR1 等
- 重试、指数退避、fallback、context window fallback、content policy fallback
- deployment cooldown、失败计数、健康检查
- 预算和 TPM/RPM 限流
- 缓存命中与响应缓存
- 部署亲和性、权重、标签过滤

Router 是 LiteLLM 区别于普通反向代理的核心组件。它把一次逻辑请求变成对一个 deployment 的选择和执行。

### 4.3 Proxy 层

`litellm/proxy/proxy_server.py` 是 FastAPI 应用入口，约 1.9 万行。它承担:

- 挂载 800 多个路由，覆盖推理 API、管理 API、健康检查、UI 后端和 pass-through
- 认证、授权、预算、限流、guardrail、审计等横切逻辑
- 配置加载和热更新
- 启动时的数据库迁移、缓存初始化、后台任务和健康检查
- 把 SDK 和 Router 暴露成 OpenAI 兼容的 HTTP API

关键请求入口在 `proxy_server.py` 的 `chat_completion`、`completion`、`embeddings`、`audio_transcriptions` 等函数。它们读取请求体，补充用户、团队、组织、agent 等元数据，然后交给 `litellm/proxy/common_request_processing.py` 的 `ProxyBaseLLMRequestProcessing.base_process_llm_request` 统一处理。

`common_request_processing.py` 是 Proxy 的核心流水线，负责:

- 请求预处理和参数校验
- 路由前的 guardrail、预算和权限检查
- 调用 Router 或 SDK
- 处理同步响应和流式响应
- 首 chunk 错误检测
- 客户端断开、取消和部分计费
- 成功和失败回调
- 响应头、trace id、spend log 和 metadata 注入

### 4.4 配置与状态

配置主要有三种来源:

1. YAML 配置文件，由 `--config` 指定，典型结构是 `model_list`、`router_settings`、`general_settings`、`litellm_settings`、`guardrails`
2. 环境变量，例如 `LITELLM_MASTER_KEY`、`DATABASE_URL`、`STORE_MODEL_IN_DB`
3. 数据库中的动态配置，开启 `store_model_in_db` 后，模型、key、团队、guardrail 等对象可以在 UI 中管理并实时生效

`litellm/proxy/proxy_cli.py` 负责命令注册、配置加载、worker 启动和 server 选择。`ProxyConfig` 在 `proxy_server.py` 中定义。

### 4.5 数据与状态

数据库 schema 在 `schema.prisma`，使用 PostgreSQL 和 Prisma Client。核心数据模型包括:

- 身份与权限: `LiteLLM_UserTable`、`LiteLLM_TeamTable`、`LiteLLM_OrganizationTable`、`LiteLLM_ProjectTable`、`LiteLLM_VerificationToken`
- 预算与配额: `LiteLLM_BudgetTable`、`LiteLLM_BudgetWindowSpend`、`LiteLLM_DailyUserSpend`、`LiteLLM_DailyTeamSpend`、`LiteLLM_DailyTagSpend`
- 模型与凭据: `LiteLLM_ProxyModelTable`、`LiteLLM_CredentialsTable`、`LiteLLM_ModelTable`
- 审计与日志: `LiteLLM_SpendLogs`、`LiteLLM_ErrorLogs`、`LiteLLM_AuditLog`
- Guardrail 与策略: `LiteLLM_GuardrailsTable`、`LiteLLM_PolicyTable`、`LiteLLM_PolicyAttachmentTable`
- MCP 与 Agent: `LiteLLM_MCPServerTable`、`LiteLLM_AgentsTable`
- Prompt 与文件: `LiteLLM_PromptTable`、`LiteLLM_ManagedFileTable`、`LiteLLM_ManagedVectorStoreTable`
- 运维: `LiteLLM_ProxyWorkerHeartbeat`、`LiteLLM_CronJob`、`LiteLLM_HealthCheckTable`

Redis 用于缓存、分布式限流、预算窗口、请求批处理和会话状态。ClickHouse 用于大规模 spend 日志和分析，属于可选路径。

### 4.6 集成与扩展

`litellm/integrations/` 提供 37 个左右的可观测性和数据集成，包括 Langfuse、Datadog、OpenTelemetry、Prometheus、Arize、Weave、Opik、New Relic、Slack 告警、S3/GCS/Azure 存储、ClickHouse 等。

扩展点主要有:

- 自定义 provider: 在 `litellm/llms/` 下实现 transformation 和 handler
- 自定义 callback: 继承 `CustomLogger`，注册 success/failure hook
- 自定义 guardrail: 实现 `CustomGuardrail`
- 自定义 routing strategy: 继承 `CustomRoutingStrategyBase`
- 自定义 auth: `custom_auth` 钩子
- 自定义 secret manager: AWS、GCP、Azure、HashiCorp、CyberArk 等
- pass-through endpoint: 不做协议转换，直接把请求转发给上游

### 4.7 Rust 原生层

Rust 代码在 `litellm-rust/`，有 66 个 crate，约 13.8 万行。它有两个形态:

1. PyO3 扩展 `litellm.rust_bridge._native`，由 maturin 打包进 Python 包，按 `litellm/rust_bridge/catalog.py` 的 rollout 策略选择 Rust 或 Python
2. 独立 `litellm-gateway` axum 二进制，是 Rust 数据面网关的早期实现

当前 Rust 强制接管的路径只有 OCR 和 Bedrock 音频转写，Anthropic Messages 是 opt-in，chat、embeddings、responses、token counter、tokenizer 仍以 Python 为默认。Rust gateway 也还没有 virtual key、预算、限流、guardrail、数据库管理等能力。

### 4.8 Go 组件

`terraform/provider/` 是一个 Terraform Provider，用 Go 实现，把 LiteLLM 的管理 API 包装成 IaC 资源。它覆盖模型、团队、用户、Key、预算、标签、项目、guardrail、prompt、agent、MCP、vector store、fallback 等对象，共 25 个资源和 33 个数据源。

它还包含一个 `endpointaudit` 工具，用 Go AST 静态提取 Provider 调用的所有端点，和 Proxy 的 OpenAPI schema 比对，防止 Provider 与 Proxy API 漂移。

## 5. 目录地图

```text
litellm/
  main.py                     SDK 公开入口
  router.py                   模型路由、重试、fallback、限流
  llms/                       152 个 provider 的转换和 HTTP handler
  router_strategy/            路由策略
  caching/                    多后端缓存
  integrations/               可观测性和数据集成
  litellm_core_utils/         日志、token、流、异常等核心工具
  proxy/
    proxy_server.py           FastAPI 应用和路由入口
    proxy_cli.py              启动命令
    common_request_processing.py  请求处理主流水线
    auth/                     认证和授权
    management_endpoints/     管理 API
    db/                       Prisma、spend log、预算写入
    guardrails/               guardrail 框架和 57 个实现
    hooks/                    限流、预算、缓存等代理钩子
    middleware/               准入、限流、压缩、安全头等中间件
    pass_through_endpoints/   透传端点
    policy_engine/            策略引擎
    ui_crud_endpoints/        Dashboard 后端
  rust_bridge/                Python 与 Rust 的桥接和路由策略
  types/                      Pydantic 类型和协议定义
ui/
  litellm-dashboard/          管理后台
litellm-rust/                 Rust workspace
terraform/provider/           Go Terraform Provider
schema.prisma                 数据库 schema
docker/, helm/                部署
tests/                        unit、integration、e2e
```

## 6. 请求流

### 6.1 SDK 调用流

```text
litellm.completion(model, messages, **kwargs)
  -> 解析 provider 和 model
  -> 选择 provider transformation
  -> 转换请求
  -> 选择同步或异步 HTTP handler
  -> 发起上游请求
  -> 转换响应
  -> 计算 token 和 cost
  -> 触发 logging / callbacks
  -> 返回 ModelResponse 或 CustomStreamWrapper
```

### 6.2 Proxy 调用流

```text
POST /v1/chat/completions
  -> FastAPI 路由
  -> user_api_key_auth 认证
  -> 读取请求体，注入 user/team/org/agent metadata
  -> ProxyBaseLLMRequestProcessing.base_process_llm_request
       -> 参数校验和预处理
       -> guardrail 前置检查
       -> 预算、限流、模型权限检查
       -> Router.acompletion
            -> 选择 deployment
            -> 调用 SDK provider handler
       -> 成功或失败回调
       -> spend log / audit log / tracing
  -> 返回 JSON 或 SSE
```

### 6.3 流式响应

流式路径比非流式复杂得多。`common_request_processing.create_response` 会先缓冲第一个 chunk，判断它是不是错误帧。如果是错误，就返回标准 JSON 错误响应；如果不是，再构造 `StreamingResponse`。它还处理:

- 客户端在首 token 前断开，返回 499
- 流式过程中的 guardrail
- 部分流量的计费
- 首 chunk 超时和 keepalive
- SSE 错误帧格式
- 上游连接关闭和资源释放

这是 LiteLLM 工程质量较高的部分，也是纯 Python 网关最容易出错的地方。

## 7. 功能地图

### 7.1 API 兼容层

- OpenAI: chat completions、completions、embeddings、images、audio、files、batches、fine-tuning、evals、responses
- Anthropic: `/v1/messages`
- Google: Gemini、Vertex AI
- Cohere、Mistral、DeepSeek、OpenRouter 等
- Realtime WebSocket
- Rerank、OCR、video、containers、search、RAG
- Pass-through: 原样转发到上游
- MCP: Model Context Protocol 服务端和客户端能力
- A2A: agent-to-agent 协议

### 7.2 路由与可靠性

- 多 deployment 负载均衡
- 重试、退避、fallback、cooldown
- 健康检查和 deployment 可用性
- 按 tag、成本、延迟、TPM/RPM、最少连接数路由
- 模型别名、模型组、access group
- 路由策略插件

### 7.3 认证、授权、预算、限流

- Master key、virtual key、JWT、OAuth2、SSO
- 用户、团队、组织、项目、agent 多级身份
- RBAC 和 route-level 权限
- 模型访问控制
- 全局、团队、用户、Key、模型、tag 多级预算
- TPM/RPM、并发请求、session 预算、动态限流
- 审计日志和登录节流

### 7.4 Guardrails

57 个 guardrail 实现，覆盖内容安全、PII、prompt injection、代码执行、工具权限、模型审核、企业安全厂商集成等。Guardrail 可以挂在请求前、响应后、流式过程中，也可以作为独立策略引擎执行。

### 7.5 缓存

- 精确缓存: 内存、Redis、Redis Cluster、磁盘、S3、GCS、Azure Blob
- 语义缓存: Redis、Valkey、Qdrant
- 双层缓存: 内存 + Redis
- 响应缓存、prompt caching、cache control

### 7.6 可观测性与回调

- 成功/失败回调
- spend log、audit log、error log
- OpenTelemetry、Prometheus、Datadog、Langfuse、Arize 等
- 自定义 callback 和 logger
- 请求级 metadata、trace id、cost、token 统计

### 7.7 Prompt、Agent、MCP、Vector Store

- Prompt management 和 prompt caching
- Agent 注册、身份和权限
- MCP server 管理、工具调用、OAuth、session
- Vector store、file、batch、fine-tuning 等对象管理

### 7.8 管理 API

`litellm/proxy/management_endpoints/` 下有 47 个模块，覆盖 key、team、user、organization、budget、model、guardrail、prompt、agent、MCP、tag、project、access group、fallback、router settings、cache settings、SSO、audit、analytics 等。

## 8. 配置系统

典型配置:

```yaml
model_list:
  - model_name: gpt-5-mini
    litellm_params:
      model: gpt-5-mini
      api_key: os.environ/OPENAI_API_KEY

  - model_name: claude-sonnet
    litellm_params:
      model: anthropic/claude-sonnet-4-5
      api_key: os.environ/ANTHROPIC_API_KEY

router_settings:
  routing_strategy: simple-shuffle
  num_retries: 2
  fallbacks:
    - gpt-5-mini: claude-sonnet

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  store_model_in_db: true
```

配置系统支持环境变量引用、数据库动态配置、配置热加载和多 pod 收敛。代价是配置项极多，`ConfigGeneralSettings` 本身就是一个很大的模型，理解和排错成本高。

## 9. 数据模型

数据库是网关的控制面状态存储，不是请求转发路径上的强依赖。关键设计:

- Key 只存 hash，不存明文
- 预算按窗口和维度拆分，便于聚合和并发扣减
- Spend log 同时支持明细和日聚合
- 模型、凭据、guardrail 支持从数据库动态加载
- 多租户模型贯穿 user、team、organization、project、agent
- 审计、错误、健康检查、worker heartbeat 都是独立表

这套模型适合中大型部署，但对 MVP 来说明显过重。

## 10. 部署形态

- SDK: `pip install litellm`，嵌入应用
- Proxy: `litellm --config config.yaml --port 4000`
- Docker: `docker/Dockerfile.non_root`，支持多阶段构建 UI 和 Python 运行时
- Compose: `docker/docker-compose.quickstart.yml`，网关 + PostgreSQL
- Helm: `helm/litellm`，支持 ingress、migration job、Redis、UI、Lens 等
- Rust gateway: `litellm-rust/crates/gateway/Dockerfile`，单二进制，早期形态

## 11. 扩展点

| 扩展点 | 方式 | 适用场景 |
|---|---|---|
| Provider | 实现 transformation + handler | 接入新模型厂商 |
| Routing | 继承 `CustomRoutingStrategyBase` | 自定义选路 |
| Callback | 继承 `CustomLogger` | 日志、计费、告警 |
| Guardrail | 实现 `CustomGuardrail` | 内容安全、合规 |
| Auth | custom auth hook | 企业身份系统 |
| Secret Manager | 实现 secret manager 接口 | Vault、KMS |
| Pass-through | 注册透传端点 | 未支持的厂商 API |
| Dashboard | 调用管理 API | 自定义控制台 |

## 12. 工程质量

- 测试规模大，unit、integration、e2e 分层
- CI 有 ruff、pyright、类型纪律、测试质量、OpenAPI 文档等多个 gate
- 有 mutation testing 和性能基准
- Rust 侧有 fmt、clippy、nextest、doc test、feature matrix、wheel 集成测试
- 代码规范强调不可变、类型完整、依赖注入、组合优于继承

主要质量问题是关键文件过大。`proxy_server.py` 约 1.9 万行，`router.py` 约 1.5 万行，`main.py` 约 8 千行，`litellm_logging.py` 约 7 千行，`common_request_processing.py` 约 216 KB。这些文件让新人理解成本很高，也让并发修改容易冲突。

## 13. Dashboard

### 13.1 技术栈

LiteLLM 的管理后台位于 `ui/litellm-dashboard`，是一个独立的 TypeScript 前端，不是 Flask 或 Django 模板，也不是纯 Python。

- 框架: Next.js 16.4.1，React 19.2.8
- 语言: TypeScript 5.9.3，严格模式
- 路由: App Router，页面在 `src/app`
- 包管理: npm，Node `>=24.14.1`
- 组件: shadcn 风格的本地组件，底层是 Base UI，图标用 lucide
- 样式: Tailwind CSS v4，`class-variance-authority`、`tailwind-merge`、`next-themes`
- 数据: TanStack Query 5，TanStack Table，TanStack Virtual
- 图表: Recharts 3
- 表单: react-hook-form + zod
- URL 状态: nuqs

它没有使用 Ant Design 或 Tremor，Tremor 在 ESLint 里被显式标记为 legacy 并禁止新代码使用。

### 13.2 构建与挂载

生产构建是静态导出。`next.config.mjs` 中:

- `output: devProxyUrl ? undefined : "export"`，没有配置 Lens dev proxy 时固定为静态导出
- `basePath: ""`
- `assetPrefix: "/litellm-asset-prefix"`
- `trailingSlash: true`

`build_ui.sh` 执行 `next build` 后，把 `out/` 复制到 `litellm/proxy/_experimental/out`。`build_release_ui.sh` 还会把构建产物提交进 Git，所以仓库里直接带着一份可用的静态包。Docker 构建会重新生成并覆盖这份产物。

Python Proxy 在 `proxy_server.py` 中挂载:

- `/_next` 和 `/litellm-asset-prefix/_next` 用 `StaticFiles`
- `/ui` 用 `StaticFiles(directory=ui_path, html=True)`

启动时它还会把导出的 `<route>.html` 重排成 `<route>/index.html`，让 `/ui/login` 这类无扩展名路径可用。如果打包目录只读，会尝试复制到可写目录，失败则告警。

除了 Python Proxy，还有两种服务方式:

- `ui/Dockerfile` 加 `ui/nginx.conf`，用 nginx 直接服务静态导出，并生成运行时配置
- Rust gateway 的 `gateway-ui` crate，用 `ServeDir` 把静态导出挂到 `/ui`，并补上 `_next` 别名和 dashboard 资源路由

Rust gateway 目前只负责静态资源和本地管理员登录，不实现完整管理 API，所以完整 Dashboard 仍然需要 Python Proxy 或反向代理。

### 13.3 认证流

Python 路径:

1. 用户在 `/ui/login` 输入用户名和密码
2. 前端调用 `POST /v2/login`，带 `credentials: "include"`
3. 服务端校验后签发 JWT，JWT 的 `key` claim 是一个真实的 virtual key，权限是 proxy admin
4. 响应返回 `redirect_url` 和 `token`，服务端同时设置 `token` cookie
5. 前端把 JWT 解码，取出 `key`，之后所有 API 调用都用 `Authorization: Bearer <virtual key>`
6. 退出时调用 `POST /session/logout`，然后清 cookie 和 sessionStorage

这个 `token` cookie 是 `HttpOnly=false`，`SameSite=Lax`，HTTPS 下才加 `Secure`。它故意让 JavaScript 可读，因为前端需要解码。Python 路径没有额外的 CSRF token，主要依赖 JSON-only 登录和 `SameSite=Lax`。

Rust gateway 的 UI 认证更严格:

- `litellm_session` 是 `HttpOnly`
- `SameSite=Strict`
- 登录时在 session 里存 CSRF 值，并额外下发一个 JS 可读的 `token` cookie，里面带 CSRF token
- 登录有令牌桶限流
- `/session/info` 和 `/session/logout` 需要 session cookie 加 Bearer key

两套实现的 cookie 和 CSRF 行为不一致，这是阅读代码时需要特别注意的地方。

### 13.4 页面范围

Dashboard 是功能非常完整的管理控制台，主要有:

- 核心管理: 首页、API Keys、Teams、Users、Organizations、Projects、Budgets、Access Groups、Admin Panel
- 模型管理: Models and Endpoints、Model Hub、Model Insights、Router Settings、Routing、Cost Optimization、Caching
- 可观测性: Logs、Usage、Cost Tracking、Guardrails Monitor、Telemetry、Tag Management
- 治理: Guardrails、Policies、Tool Policies、Skills、Transform Request
- AI 功能: Playground（chat、compare、compliance、system-one、image、audio、embeddings、messages）、Prompts、Agents、MCP Servers、Search Tools、Memory、Vector Stores、Workflows
- 其他: Public Model Hub、Chat、Connect、Onboarding、Login、Lens

`src` 下约有 55 个 `page.tsx` 和 2,405 个 TS/TSX 文件。

### 13.5 评价

优点:

- 前后端彻底分离，UI 可以独立构建和部署
- 静态导出，生产环境不需要 Node 运行时
- API-first，管理能力和 UI 解耦
- 组件和数据层现代，TanStack Query、Tailwind v4、Recharts 都是合理选择
- 同一份静态包可以被 Python、nginx、Rust 三种后端服务

问题:

- 仓库里提交了构建产物，`litellm/proxy/_experimental/out` 有 812 个文件、约 18.75 MB，其中 JS 约 11.11 MB
- `src/components/networking.tsx` 有 7,141 行手写 fetch 和接口定义，和新的 `src/lib/http/client.ts`、`openapi-fetch` 客户端并存，形成两套 API 客户端
- `/ui`、`/litellm-asset-prefix`、`/get_favicon` 等路径硬编码在前端、cookie、nginx 和 Python 挂载逻辑里
- Python Proxy 启动时可能修改静态文件或复制目录，对只读文件系统不友好
- Python 路径的 token cookie JS 可读且没有 CSRF token，安全性弱于 Rust 路径
- Rust gateway 能服务 UI，但管理 API 不完整，完整功能仍依赖 Python

结论: LiteLLM 的 Dashboard 是 Next.js + TypeScript 的静态 SPA，由 Python Proxy 在 `/ui` 下挂载。它不是纯 Python，也不是 Flask 或 Django。这个方案适合复杂管理控制台，但 LiteLLM 的实现有构建产物入库、双 API 客户端和认证硬化不足等明显问题，新项目不应照搬这些细节。

## 14. 架构评价

### 优点

- 功能覆盖极广，几乎覆盖 LLM 网关的全部治理需求
- Provider 抽象成熟，新增厂商的成本相对可控
- Router 的可靠性设计完整，重试、fallback、cooldown、预算、限流都有
- 流式响应处理细致，考虑了断开、首 chunk 错误、部分计费和资源释放
- 配置、数据库、UI 三者打通，适合企业自托管
- 有 Rust 原生加速和独立网关的演进路径

### 风险

- 单体文件过大，模块边界在关键路径上不清晰
- 功能广度高，配置和行为组合复杂，排错成本高
- Python 单进程的 CPU 和内存效率有限，高并发需要多 worker 或 Rust 数据面
- Rust 和 Python 双实现带来一致性和维护成本
- OSS 核心与企业功能混合，部分能力依赖 license
- 数据库 schema 和迁移复杂，升级和回滚需要谨慎

## 15. 关键文件索引

| 主题 | 文件 |
|---|---|
| SDK 入口 | `litellm/main.py` |
| 路由与可靠性 | `litellm/router.py` |
| Proxy 入口 | `litellm/proxy/proxy_server.py` |
| 请求流水线 | `litellm/proxy/common_request_processing.py` |
| 认证 | `litellm/proxy/auth/user_api_key_auth.py` |
| 认证检查 | `litellm/proxy/auth/auth_checks.py` |
| 管理 API | `litellm/proxy/management_endpoints/` |
| Guardrail | `litellm/proxy/guardrails/` |
| 缓存 | `litellm/caching/` |
| 路由策略 | `litellm/router_strategy/` |
| 集成 | `litellm/integrations/` |
| Provider | `litellm/llms/` |
| Rust 桥接 | `litellm/rust_bridge/` |
| Rust workspace | `litellm-rust/` |
| 数据库 schema | `schema.prisma` |
| Dashboard | `ui/litellm-dashboard/` |
| Terraform Provider | `terraform/provider/` |
