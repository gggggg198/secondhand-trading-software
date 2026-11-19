# 小蓝鲸二手集市

Python 3.13、FastAPI 和 PostgreSQL 实现的校园二手交易应用。浏览器界面与服务端 API 同源。商品、收藏、预约、审核、统计和审计均从数据库读取。

## 本地运行

准备 Python 3.13、`uv` 和 PostgreSQL。为应用建立专用数据库，并为连接账号授予该数据库的建表权限。在 `code/` 目录复制 `.env.example` 为 `.env`，填写 `WHALE_DATABASE_URL`。连接串内的用户名和密码如含保留字符，应进行 URL 编码。

```powershell
Copy-Item .env.example .env
uv sync --locked
uv run --locked --env-file .env whale-market migrate
uv run --locked --env-file .env whale-market init-admin market_admin
uv run --locked --env-file .env whale-market serve
```

首次运行 `init-admin` 时交互输入管理员密码。启动后打开 `http://127.0.0.1:8000/`，API 文档在 `/docs`，健康检查在 `/api/health`。可以用 `serve --port 8001` 切换本机端口。需要在其他机器访问时，使用 `serve --host 0.0.0.0 --ssl-certfile <证书文件> --ssl-keyfile <私钥文件>`，并通过 HTTPS 地址打开。

用两个普通账号分别担任买家和卖家。卖家保存商品草稿、提交审核，管理员通过送审。买家查询并预约商品，卖家接受后，买家实际收到物品时勾选并确认交付。可在卖家工作台或管理端查看记录和统计。结果恢复入口使用当前浏览器标签页保存的原提交标记。

## 构建与验证

```powershell
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python -m compileall -q src
node --check src/whale_market/web/app.js
node --check src/whale_market/web/views.js
uv run --locked pytest -ra
uv build
```

Node.js 用于 JavaScript 语法检查。`uv build` 在 `dist/` 生成源码包与 wheel，wheel 包含迁移和网页静态资源。在测试终端设置 `WHALE_TEST_DATABASE_URL` 后运行 Pytest，测试账号须有建 schema 权限。测试创建并清理隔离 schema。缺少连接串时数据库用例会跳过。

公开查询压测也使用测试库，运行 `uv run --locked python tests/benchmark_catalog.py --output catalog-1000.jsonl` 可保存 1,000 条正式采样。按课程要求复测时，将应用、PostgreSQL 和客户端放在同一四核环境并记录内存限制。100 买家测试需要允许服务建立足够的 PostgreSQL 测试连接。
