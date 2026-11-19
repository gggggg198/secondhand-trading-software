import asyncio
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from .accounts import Account, Accounts
from .commands import Command, Identifier
from .domain import IMAGE_LIMIT, Problem, ProductStatus, ReservationStatus
from .images import FORMATS, get_upload, save_upload
from .queries import MarketQueries, ProductScope, ReservationScope, read_auth
from .workflow import ProductWorkflow

SESSION_COOKIE = "whale_session"
SESSION_PATH = "/api"
SessionToken = Annotated[str | None, Cookie(alias=SESSION_COOKIE)]
Page = Annotated[int, Query(ge=1, le=1000000)]
OutcomeFilter = Literal["", "SUCCESS", "FAILURE", "ACCESS"]
TargetKind = Literal["", "product", "review", "reservation", "account"]


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_admin: bool


def market_routes(
    database_url: str, accounts: Accounts, workflow: ProductWorkflow
) -> APIRouter:
    router = APIRouter(prefix="/api")
    queries = MarketQueries(database_url)

    def find_actor(token: SessionToken = None) -> Account | None:
        return accounts.current(token)

    def require_actor(actor: Annotated[Account | None, Depends(find_actor)]) -> Account:
        if actor is None:
            raise read_auth()
        return actor

    Actor = Annotated[Account, Depends(require_actor)]
    Visitor = Annotated[Account | None, Depends(find_actor)]

    @router.get("/products")
    def products(
        actor: Visitor,
        scope: ProductScope = "public",
        state: ProductStatus | None = None,
        q: str = "",
        category: str = "",
        minimum: str | None = None,
        maximum: str | None = None,
        page: Page = 1,
    ) -> dict:
        return queries.products(
            actor, scope, state, q, category, minimum, maximum, page
        )

    @router.get("/products/{product_id}")
    def product(product_id: Identifier, actor: Visitor) -> dict:
        return queries.product(product_id, actor)

    @router.post("/commands")
    def execute(command: Command, actor: Actor) -> JSONResponse:
        outcome = workflow.execute(command, actor)
        return JSONResponse(outcome.body, status_code=outcome.status)

    @router.get("/reservations")
    def reservations(
        actor: Actor,
        scope: ReservationScope = "buy",
        status: ReservationStatus | None = None,
        page: Page = 1,
    ) -> dict:
        return queries.reservations(actor, scope, str(status) if status else "", page)

    @router.get("/reservations/{reservation_id}")
    def reservation(reservation_id: Identifier, actor: Actor) -> dict:
        return queries.reservation(actor, reservation_id)

    @router.post("/reservations/{reservation_id}/delivery")
    def read_delivery(reservation_id: Identifier, actor: Actor) -> dict:
        return queries.reservation(actor, reservation_id, audited_access=True)

    @router.get("/favorites")
    def favorites(actor: Actor, page: Page = 1) -> dict:
        return queries.favorites(actor, page)

    @router.put("/favorites/{product_id}")
    def add_favorite(product_id: Identifier, actor: Actor) -> dict:
        return queries.set_favorite(actor, product_id, True)

    @router.delete("/favorites/{product_id}")
    def remove_favorite(product_id: Identifier, actor: Actor) -> dict:
        return queries.set_favorite(actor, product_id, False)

    @router.get("/audit")
    def audit(
        actor: Actor,
        scope: Literal["mine", "all"] = "mine",
        page: Page = 1,
        product_id: Identifier | None = None,
        reservation_id: Identifier | None = None,
        target_kind: TargetKind = "",
        target_id: Identifier | None = None,
        operator_id: Identifier | None = None,
        action: str = "",
        outcome: OutcomeFilter = "",
        start: date | None = None,
        end: date | None = None,
    ) -> dict:
        return queries.audit(
            actor,
            scope == "all",
            page,
            product_id,
            reservation_id,
            target_kind,
            target_id,
            operator_id,
            action,
            outcome,
            start,
            end,
        )

    @router.get("/statistics")
    def statistics(
        actor: Actor,
        start: date,
        end: date,
        scope: Literal["mine", "all"] = "mine",
    ) -> dict:
        return queries.statistics(actor, scope == "all", start, end)

    @router.get("/admin/accounts")
    def admin_accounts(actor: Actor, q: str = "", page: Page = 1) -> dict:
        return queries.accounts(actor, q, page)

    @router.put("/admin/accounts/{target_id}/role")
    def update_admin(target_id: Identifier, change: RoleUpdate, actor: Actor) -> dict:
        return queries.set_admin(actor, target_id, change.is_admin)

    @router.post("/images", status_code=201)
    async def upload_image(request: Request, actor: Actor) -> dict:
        media_type = (
            request.headers.get("content-type", "").partition(";")[0].strip().lower()
        )
        if media_type not in FORMATS:
            raise Problem(415, "image_type", "请选择 JPEG 或 PNG 图片。")
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > IMAGE_LIMIT:
                raise Problem(
                    413, "image_size", "图片须在 5 MiB 以内，请缩小后重新上传。"
                )
            content.extend(chunk)
        image_id = await asyncio.to_thread(
            save_upload, database_url, actor, media_type, bytes(content)
        )
        return {"id": image_id}

    @router.get("/images/{image_id}")
    def image(image_id: UUID, actor: Visitor) -> Response:
        media_type, content = get_upload(database_url, actor, image_id)
        return Response(
            content,
            media_type=media_type,
            headers={"X-Content-Type-Options": "nosniff"},
        )

    return router
