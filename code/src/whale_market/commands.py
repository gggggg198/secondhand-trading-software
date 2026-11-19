from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain import (
    CATEGORIES,
    CONDITIONS,
    DeliveryTerms,
    Problem,
    ProductContent,
    canonical_digest,
    money_value,
    text_value,
)

Identifier = Annotated[int, Field(gt=0, le=9223372036854775807)]


class Action(StrEnum):
    DRAFT = "draft"
    EDIT = "edit"
    SUBMIT = "submit"
    WITHDRAW = "withdraw"
    APPROVE = "approve"
    REJECT_REVIEW = "reject_review"
    OFFLINE = "offline"
    RESERVE = "reserve"
    ACCEPT = "accept"
    REJECT_RESERVATION = "reject_reservation"
    CANCEL = "cancel"
    COMPLETE = "complete"
    BAN = "ban"
    MARK_VIOLATION = "mark_violation"
    EXPIRE = "expire"


REVIEW_ACTIONS = {Action.WITHDRAW, Action.APPROVE, Action.REJECT_REVIEW}
RESERVATION_ACTIONS = {
    Action.ACCEPT,
    Action.REJECT_RESERVATION,
    Action.CANCEL,
    Action.COMPLETE,
}
SELLER_ACTIONS = {Action.EDIT, Action.SUBMIT, Action.WITHDRAW, Action.OFFLINE}
ADMIN_ACTIONS = {
    Action.APPROVE,
    Action.REJECT_REVIEW,
    Action.BAN,
    Action.MARK_VIOLATION,
}
REASON_ACTIONS = {
    Action.REJECT_REVIEW,
    Action.REJECT_RESERVATION,
    Action.CANCEL,
    Action.BAN,
    Action.MARK_VIOLATION,
}


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    description: str = ""
    category: str = ""
    condition: str = ""
    price: str | None = None
    image_ids: list[UUID] = Field(default_factory=list, max_length=5)

    def to_domain(self) -> ProductContent:
        if self.category and self.category not in CATEGORIES:
            raise Problem(422, "invalid_category", "请选择有效分类。")
        if self.condition and self.condition not in CONDITIONS:
            raise Problem(422, "invalid_condition", "请选择有效成色。")
        if len(self.image_ids) != len(set(self.image_ids)):
            raise Problem(422, "duplicate_image", "每张上传图片只能添加一次。")
        return ProductContent(
            title=text_value(self.title, 60),
            description=text_value(self.description, 2000),
            category=self.category,
            condition=self.condition,
            price=money_value(self.price),
            image_ids=tuple(self.image_ids),
        )


class DeliveryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str
    meeting_at: datetime

    def to_domain(self) -> DeliveryTerms:
        if self.meeting_at.tzinfo is None:
            raise Problem(422, "invalid_delivery", "请按北京时间选择交付日期和时间。")
        return DeliveryTerms(
            text_value(self.location, 100), self.meeting_at.astimezone(UTC)
        )


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Action
    submission_key: UUID
    product_id: Identifier | None = None
    version: Identifier | None = None
    reservation_id: Identifier | None = None
    review_id: Identifier | None = None
    content: ProductInput | None = None
    delivery: DeliveryInput | None = None
    reason: str = ""
    received: bool | None = None

    @model_validator(mode="after")
    def match_action(self) -> Self:
        if self.action == Action.EXPIRE:
            raise ValueError("expiry is performed by the service")
        expected = {"action", "submission_key"}
        if self.action != Action.DRAFT:
            expected.update(("product_id", "version"))
        if self.action in {Action.DRAFT, Action.EDIT}:
            expected.add("content")
        if self.action in REVIEW_ACTIONS:
            expected.add("review_id")
        if self.action in RESERVATION_ACTIONS:
            expected.add("reservation_id")
        if self.action == Action.RESERVE:
            expected.add("delivery")
        if self.action == Action.COMPLETE:
            expected.add("received")
        if any(getattr(self, field) is None for field in expected):
            raise ValueError("command fields are missing")
        allowed = expected | ({"reason"} if self.action in REASON_ACTIONS else set())
        if self.model_fields_set - allowed:
            raise ValueError("irrelevant command fields")
        return self

    @property
    def digest(self) -> str:
        payload = self.model_dump(mode="json", exclude={"submission_key"})
        if self.delivery is not None and self.delivery.meeting_at.tzinfo is not None:
            payload["delivery"]["meeting_at"] = self.delivery.meeting_at.astimezone(
                UTC
            ).isoformat()
        return canonical_digest(payload)
