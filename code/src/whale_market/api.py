import logging
from typing import Annotated

import psycopg
from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse

from .accounts import SESSION_AGE, Account, Accounts, Credentials, UsernameTaken
from .config import Settings
from .db import open_database

LOGGER = logging.getLogger(__name__)
SESSION_COOKIE = "whale_session"
SESSION_PATH = "/api"
SessionToken = Annotated[str | None, Cookie(alias=SESSION_COOKIE)]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    accounts = Accounts(settings.database_url)
    app = FastAPI(title="小蓝鲸二手集市")

    @app.exception_handler(RequestValidationError)
    async def invalid_input(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        # FastAPI's default validation response can contain the submitted password.
        return JSONResponse(
            status_code=422,
            content={
                "detail": {"code": "invalid_input", "message": "请检查提交字段及格式。"}
            },
        )

    @app.exception_handler(psycopg.Error)
    async def storage_error(_request: Request, error: psycopg.Error) -> JSONResponse:
        LOGGER.error("PostgreSQL operation failed (%s)", type(error).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "detail": {"code": "storage_unavailable", "message": "数据库暂不可用。"}
            },
        )

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/docs")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        with open_database(settings.database_url) as connection:
            connection.execute("SELECT 1 FROM account, account_session LIMIT 0")
        return {"status": "ok"}

    @app.post("/api/auth/register", status_code=201)
    def register(credentials: Credentials) -> Account:
        try:
            return accounts.register(credentials)
        except UsernameTaken as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "username_taken", "message": str(error)},
            ) from None

    @app.post("/api/auth/login")
    def login(
        credentials: Credentials, response: Response, token: SessionToken = None
    ) -> Account:
        result = accounts.login(credentials, token)
        if result is None:
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_credentials", "message": "用户名或密码错误。"},
            )
        account, new_token = result
        response.headers["Cache-Control"] = "no-store"
        response.set_cookie(
            SESSION_COOKIE,
            new_token,
            max_age=int(SESSION_AGE.total_seconds()),
            path=SESSION_PATH,
            secure=settings.secure_cookie,
            httponly=True,
            samesite="strict",
        )
        return account

    @app.get("/api/auth/me")
    def current(response: Response, token: SessionToken = None) -> Account:
        account = accounts.current(token)
        if account is None:
            raise HTTPException(
                status_code=401,
                detail={"code": "login_required", "message": "请先登录。"},
            )
        response.headers["Cache-Control"] = "no-store"
        return account

    @app.post("/api/auth/logout", status_code=204)
    def logout(token: SessionToken = None) -> Response:
        accounts.logout(token)
        response = Response(status_code=204)
        response.delete_cookie(
            SESSION_COOKIE,
            path=SESSION_PATH,
            secure=settings.secure_cookie,
            httponly=True,
            samesite="strict",
        )
        return response

    return app
