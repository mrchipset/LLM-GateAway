# 请求审计

会话审计记录每次 chat 请求的 messages、参数、响应与用量，把同一对话的请求归为 session，并对相邻轮次做确定性结构 diff。本文是运维与使用说明；设计取舍见 `docs/adr/0001-request-audit.md`。

## 默认关闭

采集需要同时满足两个开关，任一为假时：不读取 session header、不匹配会话、不写库、不记录任何内容。

| 开关 | 默认 | 范围 |
|---|---|---|
| `GATEWAY_AUDIT_ENABLED` | `false` | 全局 kill switch |
| 租户 `audit_enabled` | `false` | 按租户 opt-in，可在管理台 Access 的租户编辑对话框中开启 |

相关环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `GATEWAY_AUDIT_ENABLED` | `false` | 全局开关 |
| `GATEWAY_AUDIT_MAX_CONTENT_BYTES` | `262144` | 单请求/单次响应的内容字节预算 |
| `GATEWAY_AUDIT_WRITE_TIMEOUT_SECONDS` | `2.0` | 审计写入超时，超时不影响推理 |

修改后需要重启后端；租户开关可通过 API/管理台即时生效。

## 会话标识

优先使用请求头 `x-llm-gateway-session-id`：

- 长度 1..64，字符集 `^[A-Za-z0-9._:-]+$`；
- 仅用于分组，不用于鉴权；
- 按租户作用域；不同租户使用相同值仍是不同会话；
- 显式 header 可以跨 API key、跨模型继续同一会话。

没有 header 时，网关在最近 24 小时、最多 200 条同租户同 key 的请求中做消息哈希最长公共前缀匹配。共享 system prompt 不足以合并会话，公共前缀必须越过首条 user 消息；最长前缀优先，平局选最新。只发送最新一条消息且不带 header 的客户端无法被可靠归并，每次都会新建会话。

若审计已开启但 header 非法，推理请求返回 400 `invalid_session_id`。审计关闭时 header 被忽略，不会改变推理行为。

## 记录内容

- 每轮保存 messages、请求参数白名单（model/temperature/top_p/max_tokens/max_completion_tokens/stop/presence_penalty/frequency_penalty/n/seed/user/response_format/tools/tool_choice/stream_options）、响应正文、tool calls、finish_reason、状态与 usage。
- 不记录 Authorization、上游 key 或内部 header。
- 流式请求累积 content 与 tool calls；正常结束 `completed`，上游错误 `upstream_error`，客户端断开 `client_disconnected`（保留已收到的部分），客户端/参数错误 `client_error`。
- 写入失败只记录不含内容的 `audit_record_failed` 日志（request/session/model/错误类型），允许出现审计缺口，不影响推理响应。

### 轮次与 diff

`turn_index = parent.turn_index + 1`。同一 parent 允许多个 child（分支/并发），因此不同分支可能共享同一 `turn_index`；读取顺序为 `(turn_index, created_at, request_id)` 全序。

变更类型：

| change_type | 含义 |
|---|---|
| `new_session` | 没有 parent |
| `continuation` | parent 的全部消息是当前消息的前缀 |
| `regeneration` | 与 parent 完全相同（重试/重新生成） |
| `edit` | 在 parent 中间分叉 |
| `truncation` | 当前消息是 parent 的前缀（客户端删减历史） |

diff 保存公共前缀长度、新增/修改/删除消息的索引、role、hash 与 ≤160 字符预览、参数 from/to、usage 差值、响应变化。参数值过大时改为 `{from_hash,to_hash,truncated:true}`，不重复保存大字段。完整内容从 request 快照读取。

### 截断

messages、响应、参数与 tool calls 共享 `GATEWAY_AUDIT_MAX_CONTENT_BYTES` 预算。超限时按 UTF-8 安全截断，`truncated=true`；消息哈希与 diff 始终基于截断前原文，匹配与变更判定不受影响。

## 管理 API

仅 master key 可访问，路径前缀 `/api/v1/audit`。错误使用统一信封（`message/type/param/code/request_id`）。

### `GET /api/v1/audit/sessions`

| 参数 | 说明 |
|---|---|
| `tenant_id` | 可选；未知租户 404 `tenant_not_found` |
| `api_key_id` | 可选，精确匹配 |
| `model_id` | 可选，精确匹配 |
| `since` | **必填**，带时区；半开窗口起点 |
| `until` | 可选，带时区 |
| `q` | 可选 1..200：session id 前缀、任意 request id 前缀或标题包含 |
| `limit` / `offset` | `1..100`（默认 50）/ `>=0` |

按 `last_seen_at` 倒序。返回 `{items, total, limit, offset}`。零请求的预创建会话不会出现。

### `GET /api/v1/audit/sessions/{id}`

- `include_content` 默认 `false`。
- 默认返回摘要与 diff（含 ≤160 字符预览），不返回完整 messages/params/response/tool calls；参数变化只返回 hash 形态。
- `include_content=true` 返回快照正文。
- 未知 session 404 `audit_session_not_found`；整体响应超过内容预算返回 413 `audit_content_too_large`。

### `GET /api/v1/audit/requests/{request_id}`

返回单请求全文、参数、响应、diff 与存储的 `truncated` 标记；未知 404 `audit_request_not_found`；超预算 413。

## 管理台

Audit 标签与 Models/Usage/Access 同级：

- Sessions 列表：租户、key 前缀（key 名称用于筛选下拉）、模型、请求数、最后活动、标题预览、token；支持租户/key/模型/时间/搜索与分页。
- 会话详情：轮次时间线，显示 change_type、状态、新增/修改/删除消息数、参数变化、usage 差值、响应变化；可展开内容。
- “Show full content” 开关按需请求正文；关闭时仍显示 diff 预览片段与参数 hash。
- 413 时提示响应过大：内容模式可先隐藏全文、改用每轮“Open request”逐条读取；未开启内容时若仍 413，说明该会话本身超出响应预算，本版本不提供分段渲染，可凭 request id 调用 `/api/v1/audit/requests/{request_id}`，或在网关侧调大 `GATEWAY_AUDIT_MAX_CONTENT_BYTES`（需重启）。
- 审计内容不写入 localStorage/sessionStorage/cookie/URL；断开连接会清空审计查询缓存。

## 隐私与保留（必读）

- 审计内容可能包含 PII、业务数据或用户粘贴的密钥。开启前由部署方确认合法依据与告知义务。
- 只有 master key 可见；推理 key 无权访问审计 API。
- diff 预览（≤160 字符）在开关关闭时也会返回；UI 文案使用“预览片段”，不得宣称完全无内容。
- 不内置 PII 正则脱敏。应用层不做额外加密，依赖数据库磁盘加密、备份加密与 TLS；备份同样包含审计内容。
- **自动保留期清理、导出与删除 API 尚未实现**（P1e）。当前需手工管理数据量；示例（请先在备份/测试库验证）：

```sql
DELETE FROM audit_sessions WHERE last_seen_at < now() - interval '30 days';
```

外键级联会删除对应 requests 与 diffs；删除前确认保留期与合规要求。审计访问本身（谁看过哪个 session）也尚未记录。

## 限制与非目标

- 没有终端用户身份，只有 tenant + API key。
- 前缀匹配存在漏合并/误合并；依赖 `match_method` 解释归并原因。
- 不做语义/意图分析、内容安全扫描或模型训练。
- 不按月分区；大表场景需另评估。
- 不改变 OpenAI 推理契约；session header 可选。
