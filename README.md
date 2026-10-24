# LLM-GateAway

自托管、多 provider 的 OpenAI 兼容 LLM 网关。

当前为 MVP 骨架阶段，完整的使用说明会在工程骨架完成后补全。

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+（仅管理台需要）
- Docker（可选，用于本地 PostgreSQL / Redis）

## 安装

```powershell
uv sync
Copy-Item .env.example .env
```

## 本地开发

```powershell
uv run uvicorn llm_gateway.app:create_app --factory --reload --port 4000
```

## 测试与检查

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

## 数据库

```powershell
docker compose up -d postgres
uv run alembic upgrade head
```
