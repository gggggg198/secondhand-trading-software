import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from getpass import getpass

import psycopg
import uvicorn
from pydantic import ValidationError

from .accounts import Accounts, AdminAlreadyInitialized, Credentials, UsernameTaken
from .api import create_app
from .config import ConfigError, Settings
from .db import MigrationError, apply_migrations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="whale-market")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="应用数据库迁移")
    administrator = commands.add_parser("init-admin", help="初始化首名管理员")
    administrator.add_argument("username")
    serve = commands.add_parser("serve", help="启动本机 HTTP 或配置证书后的 HTTPS 服务")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--ssl-certfile")
    serve.add_argument("--ssl-keyfile")
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_environment()
        if args.command == "migrate":
            applied = apply_migrations(settings.database_url)
            print(
                "已应用迁移 " + ", ".join(applied)
                if applied
                else "数据库迁移已到最新版本。"
            )
        elif args.command == "init-admin":
            password = getpass("管理员密码  ")
            if getpass("确认密码  ") != password:
                parser.error("两次输入的密码不一致。")
            credentials = Credentials(username=args.username, password=password)
            administrator = Accounts(settings.database_url).initialize_admin(
                credentials
            )
            print(f"首名管理员已初始化，账号编号 {administrator.id}。")
        elif args.command == "serve":
            tls = bool(args.ssl_certfile and args.ssl_keyfile)
            if bool(args.ssl_certfile) != bool(args.ssl_keyfile):
                parser.error("请同时提供 HTTPS 证书和私钥。")
            if args.host not in {"127.0.0.1", "::1", "localhost"} and not tls:
                parser.error("监听非回环地址时请配置 HTTPS 证书和私钥。")
            app = create_app(replace(settings, secure_cookie=tls))
            uvicorn.run(
                app,
                host=args.host,
                port=args.port,
                ssl_certfile=args.ssl_certfile,
                ssl_keyfile=args.ssl_keyfile,
            )
    except (
        ConfigError,
        MigrationError,
        UsernameTaken,
        AdminAlreadyInitialized,
    ) as error:
        print(error, file=sys.stderr)
        return 1
    except ValidationError:
        print(
            "用户名须为 4 至 20 位字母、数字或下划线，密码须为 10 至 64 字符。",
            file=sys.stderr,
        )
        return 1
    except psycopg.Error as error:
        print(f"数据库操作失败（{type(error).__name__}）。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
