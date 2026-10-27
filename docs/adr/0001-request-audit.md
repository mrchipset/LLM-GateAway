# ADR 0001：LLM 请求审计（会话与轮次变更）

- 状态：已接受（实现中）
- 日期：2026-10-27
- 关联：`TODO.md` P1、`docs/audit.md`

## 背景

网关目前只记录用量元数据（token、租户、key、模型、状态），不保存 messages、参数与响应。排障和合规场景需要回答：某次请求实际发送了什么、与上一轮相比追加/修改/删除了哪些消息、模型与参数如何变化、响应与用量差多少。

OpenAI chat 协议是无状态的，客户端通常重发完整 messages，也可能只发最新一条。没有显式会话标识时，只能在有限窗口内做前缀启发式归并，必然存在误判。

审计内容可能包含 PII、业务数据和用户粘贴的密钥，因此默认关闭，且必须与推理日志隔离。

## 决策

1. **双开关，默认关闭**：`GATEWAY_AUDIT_ENABLED=false`（全局 kill switch）且租户 `audit_enabled=false`，两者同时为真才采集。任一为假时不读取 session header、不匹配、不写库、不记录任何内容。
2. **会话标识**：优先使用客户端 header `x-llm-gateway-session-id`（1..64 字符，`^[A-Za-z0-9._:-]+$`）。它只是分组建议，不参与鉴权，按 tenant 作用域隔离。无 header 时回退到 24 小时内、最多 200 条请求的消息哈希最长公共前缀匹配；共享 system prompt 不足以合并会话，公共前缀必须越过首条 user 消息。仍无候选则新建会话。只发最新消息且无 header 的客户端无法被可靠归并，每次都会新建会话，此限制写入运营文档。
3. **确定性 diff，不做语义分析**：逐条消息规范化（role、content、name、tool_calls、tool_call_id）后做 SHA-256，与 parent 求公共前缀，得到 `new_session` / `continuation` / `regeneration` / `edit` / `truncation`。参数变化只记录白名单字段的 from/to；响应只记录 hash、finish_reason、tool calls 数量与 usage 差值。完整内容保留在 request 快照中，diff 表不复制全文。
4. **独立存储副本**：新增 `audit_sessions`、`audit_requests`、`audit_turn_diffs` 三张表；审计数据不依赖 `usage_records`，后者清理后仍可复盘。以中间件 `request_id` 作为请求主键，便于从日志跳转。
5. **主键与索引**：session id 为 UUID；session 以 tenant 为界，`(tenant_id, external_session_id)` 仅在 external id 非空时唯一；请求按 `(session_id, turn_index)`、`(tenant_id, created_at)` 索引。
6. **访问控制**：仅 master key 可访问 `/api/v1/audit/*`。推理 key 无权访问；审计内容不进入 stdout 日志、浏览器存储、cookie 或 URL。
7. **写入隔离**：审计写入是 best-effort，单独事务、超时（默认 2s），失败只记录不含内容的 `audit_record_failed` 结构化日志（request id、tenant id、session id、model、异常类型），不影响推理响应。允许出现审计缺口，但必须可观测。
8. **流式语义**：在 SSE 循环中累积 content 与 tool_calls（按 index 合并）、finish_reason 与最终 usage；正常结束记 `completed`，上游错误记 `upstream_error`，客户端断开记 `client_disconnected` 并保存已收到的部分内容。
9. **截断**：单请求内容总预算默认 256 KiB，超限显式截断并写入 `truncated=true`；消息哈希在截断前基于原文计算，保证 matching/diff 不受截断策略影响。
10. **内容读取预算**：`GET /api/v1/audit/requests/{id}` 与会话内容详情同样受预算限制，超限返回 413 `audit_content_too_large`，不做静默截断。
11. **diff 预览与参数可见性**：diff 中的消息预览固定为每条 ≤160 字符，并在 `include_content=false` 时照常返回——这是 diff 的价值所在，也与 `title_preview` 的既有边界一致。但同一模式下不返回任何完整 messages/params/response/tool calls，参数变化统一降级为 `{from_hash,to_hash,truncated:true}`。只有 `include_content=true` 才返回快照正文。UI 文案必须使用“预览片段”，不得声称未开启开关时完全无内容。预算按实际序列化响应（含 diff）计算，两种模式都生效。

## 隐私与合规答案（TODO 要求）

- **用途与合法依据**：故障排查、用量与行为复盘、合规审计；由部署方在开启前自行确认合法依据。
- **谁能看**：只有持有 master key 的运维/管理员；没有终端用户视图。
- **默认开关**：全局与租户均默认关闭，需显式双重开启。
- **租户 opt-in**：tenant PATCH 设置 `audit_enabled`；关闭后新请求零写入，历史数据按保留策略处理。
- **保留期**：默认 30 天（运营文档要求部署方配置）。自动清理任务、导出与删除接口不在本次范围，属于 P1e，尚未实现；在此之前必须手工管理数据量。
- **删除/导出**：未提供 API；直接数据库操作，需遵循备份与访问控制。
- **加密**：应用层不额外加密；依赖数据库磁盘加密、备份加密与网络 TLS。备份中同样包含审计内容，访问控制与生产库一致。
- **脱敏**：不记录 Authorization、上游 key、内部 header；不内置 PII 正则脱敏（未实现），部署方需在数据库层/网关外处理。长度截断会记录 `truncated=true`。
- **访问审计**：记录“谁在何时看了哪个 session”尚未实现（P1e），属于已知缺口。
- **内容安全边界**：不写日志、不写浏览器存储、不进入 URL；断开连接清除前端查询缓存。

## 备选方案

- **只保存 hash、不保存内容**：无法排障，也无法展示 diff 细节，放弃。
- **首条消息 hash 或纯时间窗归并**：碰撞与误合并风险高，仅作最后降级，未采用。
- **复用 `usage_records` 扩展列**：会破坏用量表职责与清理策略，放弃。
- **同步阻塞写入并让失败影响推理**：违反网关可用性目标，放弃。
- **引入外部日志/OLAP 系统**：超出当前规模，先使用 PostgreSQL；大表后续按月分区。

## 后果

- 存储增长与 PII 暴露面增加，必须默认关闭并明确保留期。
- 前缀启发式存在漏合并/误合并；UI 显示 `match_method` 让用户理解归并原因。
- 审计写入增加少量请求延迟（上限为写入超时）；失败可观测但不阻断推理。
- 不支持语义/意图分析；以后若引入，需单独的 opt-in、成本与隐私评估。
