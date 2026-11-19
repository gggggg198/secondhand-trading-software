# 小蓝鲸二手集市

实验三开发起点。当前提供 PostgreSQL 迁移、普通账号注册、登录、会话查询、退出，以及命令行初始化首名管理员。商品、审核、预约和网页接入见[开发设计](../开发设计.md)。

## 本地启动

准备 Python 3.13、`uv` 和 PostgreSQL。创建专用空数据库，并使用拥有该数据库内建表权限的开发账号。在 `code/` 目录执行 `Copy-Item .env.example .env`，将 `.env` 中的 `WHALE_DATABASE_URL` 替换为本地连接配置。

```powershell
uv sync --locked
uv run --locked --env-file .env whale-market migrate
uv run --locked --env-file .env whale-market init-admin market_admin
uv run --locked --env-file .env whale-market serve
```

仅首次配置管理员时运行 `init-admin`。命令交互读取密码。启动后打开 `http://127.0.0.1:8000/docs` 可调用接口，`/api/health` 用于检查数据库和账号表。`serve --port 8001` 可以切换本地端口。通过此命令启动的 HTTP 服务监听回环地址。

## 构建与检查

```powershell
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python -m compileall -q src
uv run --locked pytest -ra
uv build
```

在当前终端把 `WHALE_TEST_DATABASE_URL` 设置为测试库连接配置，即可运行数据库集成测试。测试在测试库中为每个用例创建并清理独立 schema，需要该账号有建 schema 权限。缺少这个变量时，`pytest -ra` 会列出跳过的数据库用例。构建产物在 `dist/`。
