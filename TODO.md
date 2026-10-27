# TODO

本文是后续路线与验收标准，不是当前功能状态。已完成能力见 `README.md`；条目按依赖排序，完成一项就勾选一项，并补齐测试、文档与（如涉及）迁移。

## 现状基线

- 后端已具备：租户创建/列表/限额 PATCH、API key 创建/列表/吊销、模型注册、用量汇总/按 key/时间序列、租户配额与限流。
- 管理台已具备：健康状态、模型列表、用量面板、Access 标签（租户创建/列表/限额编辑，API key 创建/列表/吊销）。
- 尚缺：模型注册 UI、租户删除/重命名、P1e 运维项（保留期清理/导出/删除/指标/分区），以及 P2 中的其他项。
- 当前 chat 请求是无状态的，没有 session/终端用户标识；会话审计需要显式 session header 或消息前缀启发式，且默认关闭。
- 安全边界必须保持：master key 只存在于页面内存；推理 key 只在创建时返回一次明文；不把 key 或提示词写入浏览器存储/日志。

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

## 实施顺序与依赖

1. 租户管理 UI（后端已就绪）
2. API key 管理 UI（后端已就绪）
3. 会话审计：ADR → 迁移/采集 → 会话匹配与轮次 diff → API → UI → 保留期/运维

前置：管理台保持 master key 仅内存；新增写操作必须沿用现有错误信封与 request id；任何 schema 变更走新增迁移，不修改已应用迁移。

## 完成定义

- 行为有单元测试；涉及 PostgreSQL 的路径有 `integration` 测试。
- `uv run pytest`、`uv run ruff check/format --check`、`uv run pyright`、UI 的 lint/typecheck/test/format/build 全绿。
- 新增/修改的公共契约与配置写入 README 或 `docs/`；重要取舍写入 `notes/`（英文）。
- 不引入明文 key、提示词日志、浏览器存储或未脱敏的敏感数据。
- 迁移可升级、可回滚（或在 ADR 中说明不可逆原因）。
