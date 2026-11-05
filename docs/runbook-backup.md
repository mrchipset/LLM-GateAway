# 备份与恢复演练手册

本手册面向部署方运维人员。它描述**流程与校验点**，不绑定具体主机、路径或版本；具体命令以当前 `docker-compose.yml` 与 `README.md` 为准。

## 1. 前提与边界

- **PostgreSQL 是唯一权威数据源**：租户、key、用量、计费、审计、管理员与审计事件都在这里。
- **Redis 不是权威数据**：限流桶、并发租约、部署 cooldown 都是可重建的临时状态；Redis 丢失只会短暂放宽/重置限制，不会丢账单或审计。恢复时不需要恢复 Redis。
- **密钥不在备份里**：上游 provider key、master key、管理员密码哈希在数据库中的只有密码哈希；master key 与 provider key 来自环境变量或 secret manager。备份恢复后必须确保这些环境变量仍然可用。
- **备份包含审计正文**：按保留期与合规要求加密、限权、限地域保存。
- **RPO/RTO 由部署方设定**：本手册不替业务决定保留多久、允许多久停机；演练时记录实际 RTO。

## 2. 备份

### 2.1 数据库逻辑备份

使用 PostgreSQL 官方工具的自定义格式（可并行恢复、可选择性恢复）：

```bash
# 在能访问数据库的机器上执行；密码从环境变量读取，不要写进命令行历史
export PGPASSWORD="$POSTGRES_PASSWORD"
pg_dump -h "$PGHOST" -U "$PGUSER" -d "$PGDATABASE" \
  --format=custom --compress=9 --no-owner --no-privileges \
  --file="gateway-$(date -u +%Y%m%dT%H%M%SZ).dump"
```

- `--no-owner --no-privileges`：恢复到不同账号/环境时不带原属主。
- 如果角色本身也需要重建，另做一次 `pg_dumpall --globals-only`，并与主备份一起加密保存。
- 用 compose 部署时，把 `pg_dump` 放进同一网络的一次性容器执行，避免把数据库端口暴露到备份机。

### 2.2 备份校验（每次备份后）

1. **可读性**：`pg_restore --list <dump>` 必须成功列出对象。
2. **大小与校验和**：记录字节数与 `sha256sum`；异常小或为 0 直接告警。
3. **加密**：使用部署方的加密工具（age/KMS/磁盘加密）后再离开主机；密钥与备份分开保存。
4. **异地**：至少一份不在同一故障域；对象存储开启版本控制与生命周期策略。

### 2.3 保留策略（建议起点）

| 频率 | 保留 |
|---|---|
| 每日 | 14 天 |
| 每周 | 8 周 |
| 每月 | 12 个月 |

按合规要求调整；审计保留期与备份保留期是两件事，备份不得比审计保留期活得更久，除非合规明确要求。

## 3. 恢复演练（至少每季度一次）

在隔离的 scratch 数据库/实例上执行，不要直接覆盖生产。

1. **准备**：创建空数据库 `gateway_restore_check`，准备与生产一致的角色（或使用 `--no-owner` 恢复）。
2. **恢复**：
   ```bash
   pg_restore -h "$PGHOST" -U "$PGUSER" -d gateway_restore_check \
     --no-owner --no-privileges --exit-on-error gateway-<timestamp>.dump
   ```
3. **结构版本**：`GATEWAY_DATABASE_URL=<scratch> uv run alembic current` 必须等于仓库的 head。若低于 head，按发布流程升级；若高于 head，说明备份来自更新版本，停止并调查。
4. **数据完整性**：
   - 行数抽查：`tenants`、`api_keys`、`usage_records`、`tenant_month_usage`、`audit_requests`、`audit_sessions`、`admin_users`。
   - 计费一致性：明细月聚合与预聚合必须相等：
     ```sql
     SELECT tenant_id, date_trunc('month', created_at)::date AS period,
            sum(total_tokens) AS detail_tokens
     FROM usage_records GROUP BY 1, 2
     ORDER BY 1, 2;
     SELECT tenant_id, period_start, total_tokens AS rollup_tokens
     FROM tenant_month_usage ORDER BY 1, 2;
     ```
     两边逐行比对；任何差异都说明备份不完整或存在未回填的写入路径。
   - 审计外键：`SELECT count(*) FROM audit_requests r LEFT JOIN audit_sessions s ON s.id = r.session_id WHERE s.id IS NULL;` 必须为 0。
5. **应用冒烟**（指向 scratch 数据库，使用 fake provider）：
   - `/healthz`、`/readyz` 正常；
   - 用 master key 或管理员会话列出模型与租户；
   - 发起一次 fake provider 的 `/v1/chat/completions`，确认 usage 与预聚合同时增加；
   - 打开 `/api/v1/audit/sessions`（若备份含审计），确认可读且访问被记入管理审计。
6. **记录**：备份文件校验和、恢复耗时（RTO）、行数对比结果、演练人与日期。
7. **清理**：删除 scratch 数据库与临时解密文件；确认没有明文备份残留在临时目录。

## 4. 生产恢复

1. 停止网关进程/容器，停止写入。
2. 保留当前数据库的一份快照（即使已损坏，便于事后分析）。
3. 按第 3 节恢复到目标数据库；确认 `alembic current` 与 head 一致。
4. 启动网关，观察 `/readyz`、错误率与 usage 写入。
5. 若恢复点早于故障点，账单与限流会回退到该时间点；Redis 状态自动重建，无需人工处理。
6. 恢复后立即执行一次备份，避免“刚恢复又无备份”的窗口。

## 5. 已知限制

- 没有 PITR（WAL 归档）配置；当前是逻辑备份，RPO 等于最近一次成功备份。需要更低 RPO 时，开启 WAL 归档与基础备份。
- 审计表按 `created_at` 月度分区；恢复时父表与其分区会一起还原，行数核对直接查父表即可。分区轮转见 `scripts/audit_partitions.py`。
- 本手册不包含对象存储与密钥管理系统的具体命令，按部署方选型执行。
