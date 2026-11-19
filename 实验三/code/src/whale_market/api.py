import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .accounts import SESSION_AGE, Account, Accounts, Credentials, UsernameTaken
from .config import Settings
from .db import open_database
from .domain import Problem
from .routes import SESSION_COOKIE, SESSION_PATH, SessionToken, market_routes
from .workflow import ProductWorkflow

LOGGER = logging.getLogger(__name__)
WEB = Path(__file__).with_name("web")


async def run_expiry(workflow: ProductWorkflow, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            while await asyncio.to_thread(workflow.expire_batch) == 100:
                await asyncio.sleep(0.1)
        except (psycopg.Error, Problem) as error:
            LOGGER.warning("Expiration check interrupted (%s)", type(error).__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    accounts = Accounts(settings.database_url)
    workflow = ProductWorkflow(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(run_expiry(workflow, settings.expiry_interval))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="小蓝鲸二手集市", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.middleware("http")
    async def browser_request(request: Request, call_next):
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            origin = request.headers.get("origin")
            if origin is not None and origin != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    Problem(403, "origin_denied", "请从本应用页面提交操作。").payload(),
                    status_code=403,
                )
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Problem)
    async def handle_problem(_request: Request, error: Problem) -> JSONResponse:
        return JSONResponse(error.payload(), status_code=error.status)

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
    def index() -> FileResponse:
        return FileResponse(WEB / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        with open_database(settings.database_url) as connection:
            connection.execute(
                "SELECT 1 FROM account, account_session, product, operation_result LIMIT 0"
            )
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

    app.include_router(market_routes(settings.database_url, accounts, workflow))
    return app
