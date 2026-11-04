# TODO

本文是后续路线与验收标准，不是当前功能状态。已完成能力见 `README.md`；条目按依赖排序，完成一项就勾选一项，并补齐测试、文档与（如涉及）迁移。

## 现状基线

- 后端已具备：租户创建/列表/限额 PATCH、API key 创建/列表/吊销、模型注册与版本化价格、用量汇总/按 key/时间序列、租户配额与限流、租户模型授权、token 套餐与成本预算、单请求输入边界护栏、多 deployment 路由与 fallback。
- 管理台已具备：健康状态、模型列表与注册/删除、用量面板、Access 标签（租户创建/列表/限额编辑、租户模型授权、API key 创建/列表/吊销）。
- 尚缺：租户删除/重命名、P1e 运维项（保留期清理/导出/删除/指标/分区），以及 P2 中的其他项。
- 当前 chat 请求是无状态的，没有 session/终端用户标识；会话审计需要显式 session header 或消息前缀启发式，且默认关闭。
- 安全边界必须保持：master key 只存在于页面内存；推理 key 只在创建时返回一次明文；不把 key 或提示词写入浏览器存储/日志。
- 企业级差距（身份与授权、可观测性、数据面可靠性、发布与合规）单独成节，见「企业级路线」，不与上面的功能项混排。

## P0：管理台租户管理

目标：在管理台完成租户的创建、查看与限额编辑，不再依赖 curl。

- [x] 租户列表：名称、ID、创建时间、`monthly_token_quota`、`requests_per_minute`；空/加载/错误状态。
- [x] 创建租户表单：名称必填、长度与空白校验；409 `duplicate_tenant` 有明确提示；成功后刷新列表。
- [x] 编辑限额：分别编辑月度 token 配额与每分钟请求数；支持 `null`（不限）与 ≥1 校验；保存后回显。
- [x] 交互与安全：操作需要已连接的 master key；请求失败展示 `code` 与 `request_id`；不缓存敏感响应。
- [x] 测试：创建、重复名、非法名称、限额设置/清除、错误提示；复用现有 fetch mock 风格。
- [x] 验收：从空库创建租户 → 列表可见 → 修改限额 → 刷新后仍生效；重复创建返回 409 且有提示。

说明：当前后端没有租户删除/重命名接口。删除涉及 key 与用量的归属，暂不在 P0；如需要，放到 P2 并先写设计（软删除、key 处理、历史保留）。

## P0：管理台 API key 管理

目标：按租户创建、查看与吊销推理 key；明文只显示一次。

- [x] 按租户筛选 key 列表：名称、前缀、创建时间、过期时间、是否吊销、最后使用时间。
- [x] 创建 key：选择租户、填写名称、可选过期时间；创建成功后用一次性弹层展示明文，提供复制与“关闭后无法再查看”的提示。
- [x] 明文安全：不写入 localStorage/sessionStorage/cookie/URL；关闭弹层或断开连接立即清除；查询缓存不保存明文。
- [x] 吊销 key：二次确认；204 后刷新列表；已吊销/不存在显示明确错误。
- [x] 分页与状态：`limit`/`offset`、空状态、加载骨架、错误状态（含 request id）。
- [x] 测试：一次性明文展示、复制、关闭后不可见、无浏览器存储、吊销、租户筛选、错误处理。
- [x] 验收：创建 → 复制 → 关闭 → 列表中只见前缀 → 吊销 → 再次调用推理返回 401；全程浏览器存储为空。

后端只需要现有 `/api/v1/keys`；如列表需要按 key 统计用量，另开条目，不在本项范围。

## P1：会话审计与轮次变更分析（提示词审计扩展）

> 已实现 P1a–P1d（ADR、采集、diff、API、UI），默认关闭。P1e 运维项尚未实现。

目标：按租户/API key 审计每次 chat 请求的 messages、参数与响应；把同一对话的连续请求归为一个 session；对相邻轮次做确定性的结构 diff，支持回答“这一轮追加/修改/删除了什么、模型或参数变了什么、响应与用量差多少”。

非目标（初期）：终端用户登录/SSO 身份、内容安全扫描、语义/意图总结、模型训练、跨租户分析、实时流式审计 UI。

### 1. 术语与关键假设

- **用户会话**：一次 conversation，不是登录 session。
- **调用方**：tenant + API key；当前没有终端用户身份。
- **轮次**：同一 session 内的一次请求/响应。
- **变更**：相邻请求的 messages/params/response 结构差异，不是语义总结。
- OpenAI chat 是无状态的；客户端通常重发完整 messages，但也可以只发最新消息。后者无法可靠推断会话，必须显式 header。
- 审计内容可能含 PII、密钥或业务数据；默认关闭、按租户 opt-in、可脱敏、有保留期。
- 现有“日志不记录提示词/补全”的约束不变；审计内容只进数据库，且只对 master key 可见。

### 2. 会话识别（session identity）

- [x] **方案 A（优先）显式 session header**：客户端传 `x-llm-gateway-session-id`（或 `x-session-id`），限制 1..64 字符、`^[A-Za-z0-9._:-]+$`；按 tenant 作用域存储；**只用于分组，不用于鉴权**。优点：确定、支持跨 key/model、编辑与分支；缺点：需要客户端配合。
- [x] **方案 B（fallback）消息前缀链**：同一 tenant 最近窗口（如 24h、最多 200 条）内，按 message hash 计算最长公共前缀；要求前缀包含首条 user 消息，避免把所有共享 system prompt 的对话合并；选最长前缀，平局选最新。
- [x] 关系判定：候选 messages 是当前的前缀 → `continuation`；完全相同 → `regeneration`；在候选中间分叉 → `edit`；当前是候选的前缀 → `truncation`；无候选 → 新 session。
- [x] 方案 C（不推荐）：首条消息 hash 或纯时间窗口；碰撞/合并风险高，只作为最后的降级。
- [x] 记录 `session_match_method`（`explicit` / `prefix` / `new`）、`parent_request_id`、`turn_index`，让 UI 能解释“为什么归到同一会话”。
- [x] 同一 external session id 在不同 tenant 下必须是不同 session；header 是分组建议，不是身份。
- [x] 只发最新消息且没有 header：每次新建 session，并在文档中说明限制。
- [x] 并发/分支：同一 parent 可以有多个 child；session id 稳定；`turn_index = parent.turn_index + 1`；不要用时间排序推断轮次。

### 3. 数据模型与迁移

- [x] `audit_sessions`：`id` UUID PK、`tenant_id`、`external_session_id`（可空）、`root_request_id`、`model_id`、`provider`、`title_preview`（首条 user 内容截断/脱敏）、`created_at`、`last_seen_at`、`request_count`、`total_tokens`。唯一约束仅对非空 external id：`(tenant_id, external_session_id)`。
- [x] `audit_requests`：`request_id` String(64) PK（复用中间件 request id）、`session_id`、`parent_request_id`（可空）、`turn_index`、`match_method`、`change_type`、`request_messages` JSONB、`request_params` JSONB（model/temperature/top_p/max_tokens/tools/response_format 等）、`response_content`、`response_tool_calls` JSONB、`finish_reason`、`status`、`is_stream`、`prompt_tokens`/`completion_tokens`/`cached_tokens`/`total_tokens`、`content_hash`、`truncated`、`created_at`。
- [x] `audit_turn_diffs`：`request_id` PK/FK、`previous_request_id`、`change_type`、`common_prefix`、`added_messages`/`modified_messages`/`removed_messages`（索引 + role + hash + 可选短 preview，不重复完整内容）、`parameter_changes`、`usage_delta`、`response_change`（content hash、finish reason、tool calls 变化）、`created_at`。
- [x] 通过 `request_id` 关联 `usage_records`；审计保留独立副本，避免 usage 清理后无法复盘。
- [x] 消息规范化：`role + content + tool_calls + name` 的 canonical JSON 计算 SHA-256；文本内容按配置截断，必须写 `truncated=true`，不允许静默截断。
- [x] 索引：`(tenant_id, created_at)`、`(session_id, turn_index)`、`request_id`、`parent_request_id`、`(tenant_id, external_session_id)`；大表后续按 `created_at` 月分区。
- [x] 迁移（建议 `0005` 起，必要时拆分）：tenant 增加 `audit_enabled` 默认 false；审计表与索引；`audit_turn_diffs` 可后置一张迁移。

### 4. 轮次变更分析（确定性 diff）

- [x] 归一化并 hash 每条 message；与 parent 逐条比较，得到公共前缀长度。
- [x] `change_type` 规则：
  - `new_session`：无 parent；
  - `continuation`：parent 的所有 messages 是当前前缀，且当前更长（记录 appended）；
  - `regeneration`/`retry`：messages 与 parent 完全一致；比较 response hash、finish_reason、usage；
  - `edit`：在 parent 中间分叉（记录修改的 message index 与 before/after hash，删除的尾部，新增的尾部）；
  - `truncation`/`rollback`：当前 messages 是 parent 的前缀（客户端删减历史）。
- [x] 参数字段变化单独记录：model、temperature、top_p、max_tokens、tools、tool_choice、response_format、stream_options；只存 from/to，不存密钥。
- [x] 响应变化：content hash、finish_reason、tool calls 增删、usage 差值；可选记录时延，但不作为审计必需。
- [x] 分支：session 详情按 parent/turn 展示；首版 UI 可以线性时间线 + branch 标记，不要求树形编辑器。
- [x] **明确不做语义分析**：不判断“用户意图是否改变”“话题是否漂移”；如以后要做，需单独的 opt-in、成本与隐私评估，不能混入基础审计。
- [x] diff 只存索引/hash/短 preview；完整内容从 request 快照读取，避免重复存储和漂移。

### 5. 采集流程

- [x] 请求开始时读取 tenant 的 `audit_enabled`；关闭时零写入、零内容记录。
- [x] 在调用 provider 前解析 session（显式 header 或前缀匹配）并捕获 request messages/params；响应结束后写 response/usage；审计写入不得影响推理响应。
- [x] 流式：累计 delta（content/tool_calls）与最终 usage；客户端断开写 `status=client_disconnected` 与已收到部分；上游错误写状态/错误码，不写无意义的空响应。
- [ ] 写入失败：bounded timeout、warning（只含 request id/tenant/model，不含内容）、指标；允许出现审计缺口，但必须可观测。
- [x] 不记录 Authorization、上游 key、内部 header；request/response 内容只进审计表，不进 stdout 日志。
- [x] 前缀匹配的查询有上限（时间窗 + 条数 + 索引）；显式 header 路径应避免额外匹配查询。
- [x] 并发和重复请求：同一 parent 允许分支；相同 messages/params 的重复调用记为 `regeneration`/`retry`，不合并成一轮。

### 5.1 实现说明

- 写入失败通过结构化日志 `audit_record_failed` 可观测；未引入独立 metrics。

### 6. 管理 API

- [x] `GET /api/v1/audit/sessions`：`tenant_id`、`api_key_id`、`model_id`、`since`、`until`、`q`（session/request id/标题前缀）过滤，分页，按 `last_seen_at` 倒序。
- [x] `GET /api/v1/audit/sessions/{id}`：session 摘要 + 轮次列表（默认不含完整内容）；`include_content` 或单独详情接口返回内容与 diff。
- [x] `GET /api/v1/audit/requests/{request_id}`：请求/响应全文、参数、diff、usage；支持按 request id 从日志直接跳转。
- [x] 仅 master key；未知 tenant 404；时间窗与 usage API 一致；内容大小上限，超限返回明确错误。
- [ ] 可选：JSONL/CSV 导出、按租户/时间手动删除；需 ADR 确认。
- [x] 测试：权限、过滤、分页、空结果、404、时间校验、内容上限、session/diff 形状。

### 7. 管理台 Audit 面板

- [x] 新增 `Audit` 标签（与 Models/Usage/Access 同级）；不与 Access 混在一起，避免内容型操作干扰凭证管理。
- [x] Sessions 列表：租户、key 前缀、模型、请求数、最后活动、标题预览；筛选与分页。
- [x] Session 详情：轮次时间线；每轮显示 change_type、追加/修改/删除的消息数、参数变化、token 差值、状态；可展开完整 messages/response。
- [x] Diff 视图：高亮 added/modified/removed；before/after 内容来自相邻 request 快照；不把完整内容写进 diff 表。
- [x] 内容安全：仅 master key；不写 localStorage/sessionStorage/cookie/URL；断开清空审计查询缓存；明确脱敏/保留期提示。
- [x] 空/加载/错误状态（含 request id）、长文本折叠/复制、移动端布局、减少动效。
- [x] 测试：筛选参数、列表、时间线、diff、内容开关、空/错误、无存储、权限门槛。

### 8. 隐私、保留与运维

- [x] ADR 必须先回答：用途与合法依据、谁能看、默认开关、租户 opt-in、保留期、删除/导出、加密（静态/备份）、脱敏规则、PII/密钥处理、是否记录访问审计。
- [x] 全局 kill switch：`GATEWAY_AUDIT_ENABLED=false` 默认；租户 `audit_enabled=false` 默认；两者同时为真才采集。
- [ ] 保留期默认 30 或 90 天；清理任务（CLI + Compose 一次性任务/定时任务）；清理失败告警；必要时按月分区。
- [x] 内容大小限制：单条 messages/response 上限、总字节预算；超限显式截断并记录。
- [ ] 脱敏：可配置正则；默认不记录 Authorization/上游 key；记录脱敏字段数量，不记录原文。
- [ ] 指标：写入失败、审计行数与字节增长、清理失败、查询延迟；不要用 tenant/model 之外的高基数字段做标签。
- [ ] 备份/恢复演练；确认备份中的审计内容也受加密与访问控制。
- [x] 文档：如何开启、保留期、访问、删除、导出与法律边界。

### 9. 分期与依赖

- [x] **P1a 策略与骨架**：ADR、tenant `audit_enabled`、审计表、显式 session header、非流式/流式快照采集、基础测试。
- [x] **P1b 会话与 diff**：前缀匹配、parent/turn、change_type 与参数变化、diff 表、集成测试。
- [x] **P1c API**：sessions/session/request 三个只读端点、过滤分页、内容上限、权限测试。
- [x] **P1d UI**：Audit 标签、sessions 列表、时间线、diff 详情、隐私提示、前端测试。
- [ ] **P1e 运维**：保留期清理、导出/删除、指标、分区评估、文档。
- 依赖：现有 `request_id`、usage 记录、tenant/key 数据；不改变 OpenAI 推理契约（session header 可选）。

### 10. 验收标准

- [x] 审计关闭：不产生 session/request/diff 行，不写任何内容。
- [x] 三段对话：一个 session、3 个 request、parent/turn 正确；继续、重新生成、编辑、截断四类变化各有一个可断言用例。
- [x] 流式、断连、上游错误：分别记录完整/部分/错误状态与 usage，不阻塞推理。
- [x] 模型或参数在轮次间变化：diff 明确显示 from/to；工具调用变化可见。
- [x] API/UI：按租户/key/模型/时间/request id 过滤；session 详情能展开 diff；未知租户 404；内容超限有明确错误。
- [x] 安全：仅 master key；页面存储/URL/日志无内容；断开清空内容查询；审计访问本身可选记录。（审计访问日志未实现，留待 P1e。）
- [ ] 保留期：到期数据被清理，清理失败可观测；备份策略已文档化。
- [x] 测试：显式/前缀/新建/平局匹配、diff 规则、截断、并发分支、写入失败隔离、权限与 UI。（PII 正则脱敏未实现。）

### 11. 开放问题（实现前必须定）

- [x] “用户会话”是否需要真实终端用户身份？当前只有 tenant/key；若需要，引入经认证的 end-user id，而不是信任客户端字段。（已定：不引入，tenant + key 即调用方。）
- [x] 客户端能否统一发送显式 session header？不能时，前缀匹配的误合并/漏合并是否可接受？（已定：显式 header 优先；缺失时用同租户同 key 的前缀回退，限制见 `docs/audit.md`。）
- [x] 保存完整内容还是脱敏/截断内容？保留期与静态加密的具体要求？（已定：保存截断后的内容；依赖数据库/备份加密；保留期清理待 P1e。）
- [x] 是否需要语义/意图分析？若需要，是否接受把内容发给另一个 LLM，以及成本与合规影响？（已定：不做语义分析。）
- [x] key 轮换、跨 key、跨模型的会话是否合并？建议 session 以 tenant 为界，变更记录为 diff，显式 header 可跨 key。（已定：session 以 tenant 为界；显式 header 可跨 key，前缀回退按 key 隔离。）
- [x] 分支/树形时间线是否首版就需要，还是线性 + branch 标记足够？（已定：线性时间线 + parent/turn 标记。）
- [ ] 审计访问本身是否要记录（谁在何时看了哪个 session）？（未实现，留待 P1e。）
- [ ] 数据量与分区策略：预计请求量、内容大小、保留期下的表规模。（未实现分区，留待 P1e。）

### 实现说明（2026-10-27）

- P1a–P1d 已完成并通过单元、PostgreSQL 集成、UI 与真实浏览器验证。
- 已知未实现（P1e）：保留期清理任务、导出/删除 API、metrics、按月分区、审计访问日志、PII 正则脱敏、备份恢复演练。
- 完整启用/隐私/限制说明见 `docs/audit.md`；设计取舍见 `docs/adr/0001-request-audit.md` 与 `notes/audit.md`。

## P2：可选后续

- [ ] 租户删除/停用（软删除；先定义 key、usage、审计数据的处理）。
- [ ] 用量面板：配额使用率、80%/100% 提示、按小时序列。
- [ ] 按 key 的配额/限流（目前仅租户级）。
- [ ] 审计导出与保留策略的可配置化。
- [ ] 管理台操作审计（谁在何时创建/吊销了 key）。

## 企业级路线（2026-11-03 评审）

> 本节回答“要成为企业级 LLM Gateway 还缺什么”，与上面的功能项分开维护，不混入 P0–P2。
> 分级：**G0** 不完成则过不了采购与上生产评审；**G1** 上量后必炸的可靠性缺口；**G2** 规模化与生态。
> 每条都给出可断言的验收标准。只写“已支持”不算完成。

现状判断：内核质量不错（分层清晰、错误契约统一、流式生命周期处理正确、测试与设计笔记齐全），但形态仍是“单管理员 + 单上游模型 + 单进程状态”，缺四类方向性能力：身份与授权、可观测性、数据面可靠性、发布与合规闭环。

### G0 门槛级

- [x] **G0.1 管理面身份与授权（RBAC + 可选 OIDC）**
  - 现状：管理 API 只认单一 master key，权限等同超级管理员；控制台把 master key 存在页面内存。
  - 范围：管理员主体（本地账号，后续可接 OIDC）、角色（owner/operator/auditor/read-only）、路由级权限表、服务端校验（前端只做展示）。
  - 验收：只读角色调用写接口返回 403 且错误码稳定；master key 保留为 break-glass 路径，可显式关闭，使用时写告警日志；角色变更即时生效，无需重启。
  - 进度（2026-11-04）：本地管理员 + `owner/operator/auditor` 三角色（迁移 `0009`）；scrypt 密码、opaque session（库内只存哈希）、`HttpOnly` cookie + double-submit CSRF；`POST /auth/login|logout`、`GET /auth/me`、`GET/POST/PATCH /admins`；master key 映射 owner 且可用 `GATEWAY_MASTER_KEY_ENABLED=false` 关闭；首个 owner 支持 `bootstrap_admin_*`；最后一名 owner 不可降级/停用；改密撤销会话；登录按用户名 5 次/15 分钟限流。
  - 未做：OIDC/SSO、按资源的细粒度权限、控制台登录/会话 UI 已完成（2026-11-04：登录页、CSRF、角色化导航、Admins 与 Admin audit 面板）。

- [x] **G0.2 租户级模型访问控制**
  - 现状：模型解析只校验“存在且启用”，不校验调用方是否有权使用；任意租户都能调用最贵的模型。
  - 范围：租户 → 允许模型列表（或允许 provider 列表）；未授权返回 403 + 稳定错误码；列表接口按权限过滤。同时提供“默认允许/默认拒绝”策略开关。
  - 验收：未授权模型返回 403，不产生 usage 记录；`/v1/models` 与用量报表口径一致；策略变更后下一次请求即生效。
  - 进度（2026-11-04）：`tenants.model_access_mode`（`all` 默认 / `allowlist`）+ `tenant_model_access` 表（迁移 `0007`，双 FK CASCADE）；`GET/PUT /api/v1/tenants/{id}/model-access` 原子替换；推理返回 403 `model_not_allowed` 且不写 usage；`/v1/models` 按租户过滤；空 allowlist 等于封禁全部模型。
  - 未做：按 key 的模型授权、访问策略的管理操作审计（依赖 G0.3）。设计说明见 `notes/model-access.md`。
  - 管理台（2026-11-04）：Models 标签支持注册/删除模型；Access 标签每个租户提供「Model access」对话框（all/allowlist 切换、可搜索勾选、空选封禁警告），保存后失效租户与策略缓存。

- [x] **G0.3 管理操作审计**
  - 现状：只有推理请求审计；谁在何时创建/吊销 key、改配额、注册/删除模型无记录。
  - 范围：独立表（actor、action、target_type、target_id、before/after、request_id、时间），只记录可审计的元数据，不记录密钥明文。
  - 验收：写接口全覆盖并有单元测试；审计写入失败不阻断业务但必须可观测；只读角色可查询但不能修改。
  - 进度（2026-11-04）：`admin_audit_events`（迁移 `0009`）；覆盖 admin 创建/修改、租户创建/修改、租户模型授权替换、API key 创建/吊销、模型创建/删除、价格版本创建、bootstrap；快照只含业务字段；写入失败计数 `gateway_admin_audit_write_failures` 并告警日志；`GET /api/v1/admin-audit` 支持 actor/action/target/时间过滤，仅 owner/auditor 可读。
  - 未做：审计导出与保留期（归 G0.7）、登录成功/失败事件是否入库（当前只写结构化日志与指标）。

- [x] **G0.4 指标与告警最小集**
  - 现状：只有 JSON 日志与 health/ready，无任何 metrics 端点，无法做 SLO、告警与自动扩缩。
  - 范围：`/metrics`（Prometheus 格式，独立端口或仅内网）；低基数标签限定在 provider、model、status、error_code、route；不把 tenant/key/request_id 作为标签。
  - 必测指标：请求量、错误率、P50/P95/P99 延迟、上游首 token 延迟、限流/配额拒绝数、usage/audit 写入失败数、连接池占用。
  - 验收：压测时能通过指标定位“是限流拒了、上游慢、还是 DB 慢”；标签基数可估算且有上限；指标端点不暴露在公网入口。
  - 进度（2026-11-03）：Prometheus `/metrics` 已落地（独立端口、默认关闭、绑定失败不阻断流量）；已覆盖 `gateway_requests`、`gateway_request_duration_seconds`、`gateway_upstream_requests`、`gateway_upstream_duration_seconds`、`gateway_upstream_ttft_seconds`、`gateway_rejections`、`gateway_usage_write_failures`、`gateway_audit_write_failures`。`route` 使用路由模板而非具体路径。
  - 未做：告警规则与看板、连接池占用、OTLP metrics 导出；验收中的“压测定位”依赖 G1.7 压测基线。

- [x] **G0.5 分布式追踪与 traceparent 透传**
  - 现状：无 tracing，不解析也不透传 W3C Trace Context；provider 调用无 span。
  - 范围：FastAPI / httpx / SQLAlchemy 自动埋点；入站沿用合法 `traceparent` 的 trace-id，出站生成新的 parent-id；采样率可配且决策在入口统一完成；`trace_id` 作为字段进入访问日志，并写入 usage/audit 记录（需迁移）。
  - 关键判断：一次逻辑请求内的重试与 fallback 必须落在同一个 trace 下，否则无法解释“这次请求为什么贵/为什么慢”。
  - 验收：跨进程调用链可见（客户端 → 网关 → 上游）；重试在 trace 中表现为多个 span；日志、usage、audit 能用 trace_id 关联到同一条链路；未采样请求仍有本地 request_id 可查。
  - 落地步骤（设计已定，见 `notes/observability.md`）：
    - [x] 配置项：`GATEWAY_TRACING_ENABLED`（默认 false）、`GATEWAY_TRACING_ENDPOINT`（启用时必填，OTLP/HTTP）、`GATEWAY_TRACING_SAMPLE_RATIO`（0–1）、`GATEWAY_TRACING_SERVICE_NAME`；启用但缺 endpoint 必须启动失败。
    - [x] 服务端 span：在现有 `RequestContextMiddleware` 内解析/校验 `traceparent`（仅 version `00`、小写十六进制、非全零），否则新建 trace；遵守入站 sampled 标志；记录 method/path/status/tenant/key/model，不记录内容。
    - [x] 客户端 span：provider 每次尝试一个 span，属性含 provider/model/upstream_model/attempt/stream/status，流式记录 `llm.ttft_ms`；重试为兄弟 span。
    - [x] 出站透传：每次尝试生成新的 `parent-id`，不原样转发入站头；关闭时不发头。
    - [x] 日志：`JsonFormatter` 输出 `trace_id`/`span_id`（无 span 时不输出），保留 `request_id` 且两者不互相替代。
    - [x] 持久化：`usage_records`、`audit_requests` 增加可空 `trace_id` 列（新迁移），写入时从当前 span 取。
    - [x] 关闭态验证：默认配置下不产生 span、不发 `traceparent`、日志无 `trace_id`，现有测试零改动通过。
  - 设计说明：`notes/observability.md`（含为何不用自动埋点、采样与关闭策略、`trace_id` 与 `request_id` 的分工）。
  - 已落地范围（2026-11-03）：手动 span（服务端 + 每次上游尝试）、OTLP/HTTP 导出、`trace_id`/`span_id` 日志字段、usage/audit 迁移 `0006`。未做：DB 查询 span、tail sampling、metrics（归 G0.4）。

- [ ] **G0.6 CI 门禁**
  - 现状：仓库无 CI，ruff/pyright/pytest 与前端 lint/typecheck/test/build 全靠自觉。
  - 范围：PR 流水线跑后端静态检查 + 单测、前端四项、Docker 构建；PostgreSQL 集成测试用 service 容器；锁文件冻结安装。
  - 验收：故意引入 pyright 错误、失败测试、格式问题各一次，流水线必须红；合并保护开启。
  - 进度（2026-11-03）：`.github/workflows/ci.yml` 已落地（backend / integration / frontend / docker 四个 job），本地等价命令全绿（417 passed，52 个集成用例另跑全绿）。剩余：首次推送后验证流水线为红的能力，并开启分支保护。

- [x] **G0.7 审计数据合规闭环（原 P1e）**
  - 现状：存了内容但无保留期清理、无导出/删除、无分区、无 PII 脱敏。
  - 范围：保留期（默认 30/90 天，按租户可配）、清理任务（CLI + 一次性任务）、导出（JSONL/CSV）、按租户/时间删除、可配置正则脱敏、清理失败告警；大表按月分区评估。
  - 验收：到期数据被清理且有指标；删除可证明（行数与对象存储均无残留）；脱敏只记录命中数量不记录原文；导出受权限控制且不落浏览器存储。
  - 进度（2026-11-04）：保留期 `GATEWAY_AUDIT_RETENTION_DAYS`（默认 90，0 关闭）+ 租户级 `audit_retention_days`（`null` 继承、`0` legal hold，迁移 `0011`）；`scripts/audit_cleanup.py` 分批清理（requests → orphan sessions），单租户失败隔离、退出码非零；`GET /api/v1/audit/export`（JSONL/CSV，keyset 流式，owner/auditor）与 `DELETE /api/v1/audit`（owner，dry-run + 计数复核 + `audit.deleted` 事件）；`GATEWAY_AUDIT_REDACT_PATTERNS` 在写入前脱敏（哈希/diff 基于脱敏后内容，只记录规则名与命中数）；指标 `gateway_audit_cleanup_rows|cleanup_failures|redactions|export_rows`。设计说明见 `notes/audit-retention.md`。
  - 剩余：管理台没有导出/删除入口（API + CLI 为当前界面）；按月分区未做，触发条件写入设计说明；审计读取行为本身尚未入库。

- [ ] **G0.8 输入边界与成本护栏**
  - 现状：请求体、messages 长度、`max_tokens` 均无上限；未知字段全量透传上游。
  - 范围：请求体大小上限、单请求 token 估算上限、`max_tokens` 上限、并发上限、按模型的上下文窗口校验、参数白名单（区分“允许透传”和“拒绝”的字段）。
  - 验收：超限请求返回 4xx 且错误码稳定，不触达上游；单客户端无法通过超长 prompt 或无限 `max_tokens` 打穿内存与成本。
  - 进度（2026-11-04）：已落地单请求边界——`GATEWAY_MAX_REQUEST_BYTES`（Content-Length + 流式计数）超限 413 `request_too_large`；`GATEWAY_MAX_MESSAGES` / `GATEWAY_MAX_PROMPT_CHARS` / `GATEWAY_MAX_TOOLS` / `GATEWAY_MAX_TOKENS_LIMIT` 超限 400 `request_limit_exceeded` 并带 `param`；护栏在认证/配额/限流之后、计费与上游调用之前执行，超限不写 usage、不触达上游。
  - 剩余：并发（in-flight）上限归 G1.2；按模型的上下文窗口需要先有模型能力表（归 G2.1）；参数白名单暂不做（`extra="allow"` 是为兼容 provider 专有字段），保持现状并在 README 说明。

### G1 生产可靠性

- [x] **G1.1 多 deployment 路由与可靠性**
  - 现状：一个公共模型对应一个上游模型，无权重、无 fallback、无 cooldown、无上游 key 池。
  - 范围：公共模型 → 多个 deployment（provider + 凭证引用 + 权重 + 状态）；重试（仅首字节前）、fallback 链、失败计数与 cooldown、健康探测；路由策略先做加权 + 最少失败，不做算法堆叠。
  - 验收：注入上游 429/5xx，客户端成功率高且响应头标明是否 fallback；连续失败的 deployment 进入 cooldown 并自动恢复；fallback 与重试均有指标与 trace span。
  - 设计说明落到 `notes/routing.md`。
  - 进度（2026-11-04）：`model_deployments`（迁移 `0010`，无 deployment 的模型隐式单路由，零迁移）；凭证只存环境变量名 + 可选 `base_url`，密钥不落库；权重无放回抽样、失败转移（可重试/5xx/429/401/403/坏响应）、进程内 cooldown（阈值 3、30s，永不排除最后一个候选）；响应头 `x-llm-gateway-deployment` / `x-llm-gateway-fallback`；指标 `gateway_route_attempts|fallbacks|cooldowns` 与 `route.attempt` span；管理 API 增删改查 + 审计。
  - 未做：跨进程共享健康（归 G1.2，与 Redis 一起）、按延迟/成本动态路由、per-deployment 用量归因（当前 provider 维度 + `deployment` 指标标签）。

- [ ] **G1.2 限流与配额离开请求热路径**
  - 现状：固定 60 秒窗口、仅租户级；计数落在 PostgreSQL 单行，同租户请求互相争抢；Redis 仍是 Reserved。
  - 范围：Redis 令牌桶（per-key / per-tenant / per-model）、TPM 与并发上限、RPM 与 TPM 同时生效、`Retry-After` 语义明确；限流不可用时降级策略显式（fail-open 必须告警）。
  - 验收：多副本下限流口径一致；边界不出现 2 倍突发；Redis 不可用时行为符合配置且可观测。

- [ ] **G1.3 热路径读写放大治理**（压测已确认整月用量聚合是第一瓶颈，优先做）
  - 现状：每请求包含 key 查询、`last_used_at` 写入、租户查询、整月用量聚合、限流单行 upsert、usage 插入，全部同步打 PostgreSQL，无缓存。
  - 范围：key/tenant 短期缓存（含显式失效）、`last_used_at` 采样或批量、usage 异步批量写入、日/月预聚合表、聚合查询走预聚合而非明细扫描。
  - 验收：单请求 DB 往返次数有明确预算并可测；P95 延迟在目标 QPS 下不随月内累计用量增长而退化。
  - 进度（2026-11-04）：压测已确认整月聚合是首要瓶颈（见 G1.7）。按决定暂缓本体实现，先提供逃生开关 `GATEWAY_BILLING_ENABLED`（默认 `true`）；关闭后跳过套餐/预算校验与成本结算，热路径不再做月聚合与价格查询，usage 仍记录 token 但成本字段留空，`/tenants/{id}/billing` 返回 `enabled:false`。语义与风险见 `notes/billing.md` 2.8。恢复计费前需按版本化价格回填该窗口的未结算记录。

- [x] **G1.4 成本与预算**
  - 现状：只有 token，无价格表、无货币、无成本聚合。
  - 范围：model → 价格（输入/输出/缓存命中，按币种与生效时间版本化）、请求级成本、按 tenant/key/model/时间聚合、预算窗口与超额策略（拒绝或告警）、价格变更不影响历史记录。
  - 验收：同一请求的 token 与成本可复算一致；历史账单不受调价影响；预算超额返回稳定错误码并有指标。
  - 注意：不要硬编码第三方当前价格，价格来自配置或数据库。
  - 进度（2026-11-04）：`model_prices` 生效时间版本化（迁移 `0008`，唯一 `(model_id, effective_from)`）；`usage_records` 记录 `covered_tokens`/`billable_tokens`/`list_cost`/`billed_cost`（Decimal，6 位）；租户级 `plan_tokens`（月度 token 套餐、不结转）+ `plan_allow_overage` + `monthly_cost_budget`；429 `plan_allowance_exhausted` / `budget_exceeded`，无价时 503 `model_price_missing`；用量 API 与 `GET /tenants/{id}/billing` 暴露成本；指标 `gateway_rejections{reason}`。
  - 未做：开票/多币种/per-key 预算、充值包与结转。管理台已提供价格版本、租户套餐/预算与成本展示（2026-11-04）。
  - 明确不做：并发预扣。产品决定接受"请求级超支窗口"（并发在途请求最多按自身用量超支），理由与复评条件见 `notes/billing.md` 第 2.6 节。设计说明见 `notes/billing.md`。

- [x] **G1.5 运行时与生命周期参数化**
  - 现状：连接池大小硬编码、无语句超时、启动未配 workers、无优雅停机排空、流式无 keepalive/空闲超时。
  - 验收：连接池与并发参数可配且有上限校验；滚动发布会等待 in-flight 流结束（或按超时截断并记账）；长时间无数据的流按空闲超时关闭并释放上游。
  - 进度（2026-11-04）：`GATEWAY_DATABASE_POOL_SIZE|MAX_OVERFLOW|POOL_TIMEOUT_SECONDS|STATEMENT_TIMEOUT_MS`（服务端 `statement_timeout`，默认 30s，0 关闭）；`InFlightTracker` + 纯 ASGI 中间件统计活跃请求，lifespan 按 `GATEWAY_SHUTDOWN_GRACE_SECONDS` 排空，超时记 `shutdown_grace_exceeded` 并累加 `gateway_forced_shutdowns`；容器命令加 `--timeout-graceful-shutdown` 与 `stop_grace_period: 45s`；`GATEWAY_STREAM_IDLE_TIMEOUT_SECONDS`（默认 60，0 关闭）按"等待下一块字节"计时，超时抛 `ProviderTimeoutError`，走既有 SSE 错误帧并结算已交付用量。`GATEWAY_WORKERS` 已接通但默认 1，**必须等 G1.2 共享限流后才能 >1**。设计说明见 `notes/runtime.md`。
  - 未做：连接池不会自适应；排空只等自然结束，没有"提前关闭流"的协议；非流式请求由总超时覆盖，不叠加空闲超时。

- [ ] **G1.6 缓存**
  - 范围：先做精确缓存（内存 + Redis，键含 model/tenant/参数归一化哈希），再评估语义缓存；明确哪些请求可缓存（含 `temperature>0`、工具调用、流式的规则）；缓存命中/写入/绕过均有指标；prompt cache 相关字段透传语义写清楚。
  - 验收：缓存命中不产生上游计费但产生可区分的 usage 记录；租户隔离不串缓存；失效策略可解释。

- [ ] **G1.7 容量与 SLO 基线**
  - 范围：压测脚本（非流式 + 流式 + 断连 + 上游慢/错），容量模型（连接数、内存、DB 写入放大），SLO（可用性、P95、错误率预算），告警阈值。
  - 验收：给定 QPS 与并发能给出资源需求与瓶颈结论；每次性能相关改动有前后对比数据。
  - 进度（2026-11-04）：工装已就绪，见 `scripts/loadtest/`（可控上游 stub、seed、用量预热、k6 脚本、一键编排）。冒烟验证通过：非流式 50 请求 0 错误；流式 25 请求 0 错误且 `gateway_upstream_ttft_seconds` 正常；开启套餐/预算/价格后 50 请求 0 错误。
  - 已完成（2026-11-04，8 vCPU / 31 GiB Linux 主机，单 worker + 内嵌 PostgreSQL 16.2 + 同机 k6）：
    - [x] 预热用量：`uv run python scripts/loadtest/warm_usage.py --rows 200000`
    - [x] 基线：快上游 100 RPS 与 60 RPS 两档，p95 分别为 30ms / 53ms，0 错误
    - [x] 计费对照：50k 行 100 RPS p95 9.94s（78 RPS）；50k 行 60 RPS p95 83ms；215k 行 60 RPS 仅 39.6 RPS、p95 15.3s
    - [x] 流式：30 RPS p95 245ms，TTFT 均值 22.4ms（stub 20ms）
    - [x] 故障注入：5% 500 → 317/6318 上游失败、客户端失败 1 个（0.01%）、重试放大 1.053
    - [x] 结果表已填入 `notes/load-baseline.md` 第 7 节，环境限制同时记录
  - 决策规则（已写在 `notes/load-baseline.md`）：同 RPS 下计费开启使 p95 增长 >30%，或连接数先于 CPU 饱和，则 G1.3 先做当月计数器 + 价格缓存；<10% 则暂缓。
  - 结论（2026-11-04）：**规则命中且严重**——50k 行时 p95 +57%，100 RPS 直接崩到 9.94s，215k 行时 60 RPS 无法维持。单 worker 约 100 RPS 饱和（单核 81%），8 核闲置。G1.3 顺序：月用量计数器/缓存聚合 → 价格缓存 → key/tenant 缓存 → usage 批量写；多 worker 需等 G1.2 的共享限流与共享健康。

### G2 规模化与生态

- [ ] **G2.1 Provider 广度**：Azure OpenAI、Anthropic Messages、Bedrock、Vertex，以及模型能力表（上下文窗口、模态、工具调用、流式 usage 语义）；provider 差异只允许存在于 adapter 内。
- [ ] **G2.2 端点广度**：embeddings、responses、messages、images、audio、rerank；每个端点都要有流式/错误/计费语义，不允许“能转发就算支持”。
- [ ] **G2.3 Guardrails**：内容安全、PII、prompt injection，pre/post/stream 三阶段钩子；先做 2–3 个实现并稳定接口，不复制生态式堆量。
- [ ] **G2.4 凭证管理**：secret manager（Vault/KMS/云厂商）、上游凭证轮换与双活、按租户 BYOK；应用内不落明文，轮换过程可观测且不中断流量。
- [ ] **G2.5 交付形态**：Helm/K8s manifests、迁移 Job、PDB/HPA、NetworkPolicy、TLS/ingress 参考配置、备份与恢复演练、升级与回滚手册。
- [ ] **G2.6 文档与生态**：本项目自己的架构文档（当前 `architecture.md` 是 LiteLLM 分析）、SLO/runbook/on-call 手册、威胁模型、OpenAPI 生成的管理客户端、可选 SDK 与 Terraform Provider。
- [ ] **G2.7 兼容性策略**：`/v1` 与 `/api/v1` 的变更、弃用、版本化流程；错误码只增不改语义；破坏性变更需迁移窗口。

## 实施顺序与依赖

1. 租户管理 UI（后端已就绪）
2. API key 管理 UI（后端已就绪）
3. 会话审计：ADR → 迁移/采集 → 会话匹配与轮次 diff → API → UI → 保留期/运维
4. 企业级 G0：授权与模型 ACL → 指标/追踪 → CI → 合规闭环 → 输入护栏
5. 企业级 G1 → G2：按目标形态决定，内部平台优先 G1.1/G1.3/G1.4，对外多租户优先 G1.2/G0.7/G0.8

前置：管理台保持 master key 仅内存；新增写操作必须沿用现有错误信封与 request id；任何 schema 变更走新增迁移，不修改已应用迁移。

G0 的取舍必须先定：目标形态是“内部多团队平台”（优先 RBAC、配额、成本）还是“对外多租户 SaaS”（优先隔离、合规、滥用防护）。两者 G0 内部排序不同，不要同时开工。

## 完成定义

- 行为有单元测试；涉及 PostgreSQL 的路径有 `integration` 测试。
- `uv run pytest`、`uv run ruff check/format --check`、`uv run pyright`、UI 的 lint/typecheck/test/format/build 全绿。
- 新增/修改的公共契约与配置写入 README 或 `docs/`；重要取舍写入 `notes/`（英文）。
- 不引入明文 key、提示词日志、浏览器存储或未脱敏的敏感数据。
- 迁移可升级、可回滚（或在 ADR 中说明不可逆原因）。
