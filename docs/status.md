# 交付状态与上生产清单

本文是**当前验收状态**的快照：做了什么、证据是什么、明确没做什么、上线前运维必须配好什么。
配置项与命令的单一事实来源是 `README.md`，路线与未完成项是 `TODO.md`，架构与决策见
`architecture.md`、`design.md` 与 `notes/`。本文只做汇总和索引，不重复细节。

快照时间：2026-11-05；代码基线 `0f7ce30`（CI run `42051350662` 全绿）。

## 1. 能力地图

| 域 | 已交付 | 关键边界 |
|---|---|---|
| 推理协议 | OpenAI 兼容 `/v1/chat/completions`、`/v1/models`；流式含 usage 结算与客户端断开处理 | 流式中途错误转 SSE 错误帧 + `[DONE]`，已交付部分照常计费 |
| Provider | OpenAI、DeepSeek、Azure OpenAI、Anthropic Messages、fake | Azure 走 deployment 路径与 `api-key`；Anthropic 全量转换 tools/usage/SSE |
| 路由 | 每模型多 deployment、权重、故障切换、共享 cooldown、按 deployment 凭证名 | 凭证只存环境变量名；provider/upstream 变更受部署保护（409） |
| 身份与权限 | 本地管理员 + `owner/operator/auditor`、opaque session、CSRF、master key break-glass、OIDC SSO | OIDC 按 `sub` 绑定、角色来自 claim 映射、JIT 可选 |
| 租户隔离 | 租户/key、模型访问策略、软删除（隐藏 + 撤销 key，历史保留） | 无按 key 的模型范围；无硬删除 |
| 计费 | 版本化价格、月套餐、结算后 TPM 扣减、成本预算、O(1) 月聚合 | 不做预扣；并发最多超支一个请求 |
| 限流 | 令牌桶（tenant/key/model）、三层 TPM、并发租约、Redis 共享、显式 fail-open/closed | `storage` 后端的新增 scope 仍是进程内 |
| 审计 | 双开关、会话与轮次 diff、写入前脱敏、保留期、CLI 清理、JSONL/CSV 导出、按租户删除、读取/导出留痕、按月分区 | 硬删除；无对象存储；读取操作只记元数据 |
| 可观测 | 结构化日志、Prometheus 指标、W3C trace 透传与 OTLP | 指标无内置告警规则与面板 |
| 控制台 | 租户/key/模型/部署/价格/用量/审计全量管理，SSO 登录，按天用量下钻与 CSV | 模型能力与限额可编辑；不支持按 key 的模型范围 |
| 运行时 | 连接池/语句超时可配、优雅停机、流空闲超时、worker 开关 | `GATEWAY_WORKERS>1` 仅在 Redis 限流后端下安全 |

## 2. 验收证据

- **测试**：后端 `578 passed`（单元）；PostgreSQL 16 + Redis 7 集成 `91 passed`；前端 `196 passed`（19 个文件）。
  静态检查 `ruff check`、`ruff format --check`、`pyright` 全绿。
- **CI**：`.github/workflows/ci.yml` 四个 job（Backend checks / Integration tests / Frontend checks /
  Docker builds）。红灯演练已证明类型错误、失败单测、格式问题会各自在对应步骤失败，其余 job 保持绿
  （run `41849170218`、`41849544183`、`41849926543`）。
- **容量**（8 vCPU，k6 与 PostgreSQL 同机，含完整限流/计费路径）：
  - 单 worker：60 RPS，p95 48 ms（215k 行月用量）；
  - 4 worker + Redis：100 RPS p95 35 ms、200 RPS p95 58 ms，0 错误；
  - 8 worker：248 RPS 触顶，p95 3.1 s，瓶颈是测试机 8 核而非数据库。
  方法与原始数据见 `notes/load-baseline.md` 第 7、8 节。
- **迁移**：`0001`–`0018` 全部在真实 PostgreSQL 上验证；`0018`（审计分区）额外验证了升级、
  分区路由、DEFAULT 兜底、跨分区级联删除、降级保数据与再升级。
- **备份**：恢复演练流程、一致性核对 SQL 与生产恢复步骤见 `docs/runbook-backup.md`；本轮未在真实
  生产备份上执行演练，首次演练仍待部署方完成。

## 3. 明确没做（决定或延期）

| 项 | 状态 | 原因 |
|---|---|---|
| Bedrock / Vertex | 未实现 | 需要 SigV4 / OAuth 与多字段凭证，现有"一个环境变量名"的凭证模型装不下；需先定方案 |
| G2.2 端点广度（embeddings/responses/images…） | 未实现 | 每个端点都要先定义流式、错误与计费语义，不做"能转发就算支持" |
| G2.3 Guardrails | 未实现 | 需要先稳定 pre/post/stream 钩子接口，再谈实现数量 |
| G2.4 Secret manager | 未实现 | 当前凭证只从环境变量读取，未接 Vault/KMS |
| G2.5 Helm / K8s manifests | 未实现 | 现有 Compose 与 Dockerfile 可运行；缺 PDB/HPA/NetworkPolicy 参考配置 |
| G2.6 自有架构文档 | 未完成 | `architecture.md` 当前是对 LiteLLM 的分析，不是本项目架构 |
| G2.7 API 版本化 | 未实现 | `/v1` 与 `/api/v1` 目前是唯一版本，无弃用流程 |
| G1.6 缓存 | 不做（当前） | 压测证明瓶颈是月聚合而非单行查询；缓存会推迟价格生效与 key 吊销 |
| G0.8 上下文窗口精确校验 | 部分完成 | 已记录 `context_window` 并校验 `max_output_tokens`，但无按模型 tokenizer；prompt 仍是字符预算 |
| 分支保护 | 已决定暂缓 | 四个检查的红/绿能力已验证；开启步骤记录在 `notes/session-2026-11-04.md` |
| OIDC 登出/角色同步/多 IdP | 未做 | 会话只在本地下线；角色变更需重新登录且不改写既有 OIDC 管理员 |

## 4. 上生产前运维清单

按顺序执行；每项完成后打勾。

1. **配置**：设置 `GATEWAY_ENVIRONMENT=production`、`GATEWAY_MASTER_KEY`、PostgreSQL DSN、
   各 provider key；OIDC 若启用，四个必填项齐全。生产环境会拒绝占位/过短的 master key 与 fake provider。
2. **迁移**：用一次性 `migrate` 服务或 `uv run alembic upgrade head` 升级；应用进程从不自行迁移。
3. **Redis**：需要多 worker 或跨副本限流时，启动 Redis 并设
   `GATEWAY_RATE_LIMIT_BACKEND=redis`；否则保持 `GATEWAY_WORKERS=1`。
4. **Worker 数**：Redis 后端下从 4 开始（本机实测 200 RPS），观察 CPU 与 p95 后再加。
5. **审计轮转与清理**：cron 每天跑 `scripts/audit_cleanup.py`；每月跑
   `scripts/audit_partitions.py --months-ahead 3`。两者都以非零退出码告警。
6. **备份**：按 `docs/runbook-backup.md` 配置每日备份、校验和、加密与异地；每季度在 scratch 库做
   一次恢复演练，记录 RTO。
7. **健康检查**：`/healthz`（存活）与 `/readyz`（数据库，fail-closed 时含 Redis）。指标端口默认
   `9464`，仅监听回环。
8. **网络与 TLS**：PostgreSQL/Redis 默认只绑回环；对外只暴露反向代理，TLS 在代理层终止。管理面与
   推理面路径前缀不同，建议在代理层分别限源。
9. **告警基线**：至少对 `gateway_requests_total{status_code=~"5.."}`、`gateway_rate_limit_degraded`、
   `gateway_cooldown_degraded`、`gateway_audit_cleanup_failures`、`gateway_forced_shutdowns` 与
   `/readyz` 失败告警；面板与规则需自行搭建，仓库只提供指标。
10. **密钥轮换**：master key 与 provider key 只在环境/secret manager 中；轮换后重启进程。租户推理 key
    走创建/吊销与 per-key 限额，不落库明文。

## 5. 已知的运营注意事项

- **删除是软删除**：`DELETE /api/v1/tenants/{id}` 隐藏租户并撤销 key，但用量与审计行保留；这是为了让
  账单与合规记录可追溯。硬删除没有接口。
- **上限是软约束**：配额/预算在请求前读取，在途请求可造成最多其自身用量的超支；TPM 是结算后扣减。
  需要严格不超支时必须做预扣，这是明确拒绝的方向。
- **审计内容敏感**：正则脱敏是尽力而为，不替代数据分级、磁盘/备份加密与访问授权。备份同样含正文。
- **多 worker 的指标**：Prometheus 端口是进程独占，多 worker 下只抓到一个进程；端到端延迟以网关
  访问日志或压测为准。
- **分区轮转是外部职责**：忘记轮转不会丢写（DEFAULT 兜底），但之后建该月分区前必须先把 DEFAULT 行
  迁走；脚本会报 `blocked` 而不是静默跳过。
