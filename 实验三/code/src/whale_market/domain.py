import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

CATEGORIES = ("书籍", "电子产品", "生活用品", "运动用品", "其他")
CONDITIONS = ("全新", "九成新", "八成新", "七成新", "有明显使用痕迹")
IMAGE_LIMIT = 5 * 1024 * 1024


class Problem(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def payload(self) -> dict:
        return {"detail": {"code": self.code, "message": self.message}}


class ProductStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    OFFLINE = "OFFLINE"
    BANNED = "BANNED"


class ReservationStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


EDITABLE = {ProductStatus.DRAFT, ProductStatus.REJECTED, ProductStatus.OFFLINE}
BANNABLE = {
    ProductStatus.PENDING,
    ProductStatus.REJECTED,
    ProductStatus.PUBLISHED,
    ProductStatus.RESERVED,
    ProductStatus.OFFLINE,
}
ACTIVE = (ReservationStatus.PENDING, ReservationStatus.CONFIRMED)


def utc_now() -> datetime:
    return datetime.now(UTC)


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return sha256(encoded.encode("utf-8", errors="surrogatepass")).hexdigest()


def text_value(value: str, maximum: int) -> str:
    clean = value.strip()
    if len(clean) > maximum or "\0" in clean:
        raise Problem(422, "invalid_input", f"文本须在 {maximum} 字以内，请检查输入。")
    try:
        clean.encode("utf-8")
    except UnicodeEncodeError:
        raise Problem(
            422, "invalid_input", "文本包含无法保存的字符，请检查输入。"
        ) from None
    return clean


def money_value(value: str | None, *, filter_bound: bool = False) -> Decimal | None:
    if value is None or value == "":
        return None
    cleaned = value.strip()
    if re.fullmatch(r"[0-9]{1,6}(?:\.[0-9]{1,2})?", cleaned) is not None:
        amount = Decimal(cleaned).quantize(Decimal("0.01"))
        minimum = Decimal("0") if filter_bound else Decimal("0.01")
        if minimum <= amount <= Decimal("100000.00"):
            return amount
    start = "0" if filter_bound else "0.01"
    raise Problem(
        422, "invalid_price", f"请输入 {start} 至 100000.00 元，最多保留两位小数。"
    )


def needed_reason(reason: str) -> str:
    if not reason:
        raise Problem(422, "reason_required", "请填写处理原因后重试。")
    return reason


def changed_state(message: str = "状态已变化，请刷新后重试。") -> Problem:
    return Problem(409, "state_changed", message)


def missing(kind: str) -> Problem:
    return Problem(404, "not_found", f"{kind}当前不可查看，请返回列表刷新。")


def forbidden() -> Problem:
    return Problem(403, "forbidden", "当前账号没有此操作权限，请返回对应的工作台。")


@dataclass(frozen=True)
class ProductContent:
    title: str = ""
    description: str = ""
    category: str = ""
    condition: str = ""
    price: Decimal | None = None
    image_ids: tuple[UUID, ...] = ()

    def validate_submission(self) -> None:
        if not all(
            (self.title, self.description, self.category, self.condition, self.price)
        ):
            raise Problem(
                422, "incomplete_product", "请补全标题、描述、分类、成色及价格。"
            )

    def snapshot(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "condition": self.condition,
            "price": str(self.price) if self.price is not None else None,
            "image_ids": [str(image_id) for image_id in self.image_ids],
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.snapshot())


@dataclass(frozen=True)
class DeliveryTerms:
    location: str
    meeting_at: datetime

    def validate(self, now: datetime) -> None:
        if len(self.location) < 2 or not now < self.meeting_at <= now + timedelta(
            days=30
        ):
            raise Problem(
                422,
                "invalid_delivery",
                "请填写 2 至 100 字的校园公共地点，选择未来 30 天内的时间。",
            )


@dataclass
class ReviewSubmission:
    product_id: int
    content: dict
    submitted_at: datetime
    id: int | None = None
    status: ReviewStatus = ReviewStatus.PENDING
    resolved_at: datetime | None = None
    resolved_by: int | None = None
    reason: str = ""

    def resolve(
        self, target: ReviewStatus, actor_id: int, now: datetime, reason: str = ""
    ) -> None:
        if self.status != ReviewStatus.PENDING:
            raise changed_state("本次送审已处理，请刷新审核页面。")
        self.status = target
        self.resolved_at = now
        self.resolved_by = actor_id
        self.reason = reason


@dataclass
class Reservation:
    product_id: int
    buyer_id: int
    product_title: str
    price: Decimal
    terms: DeliveryTerms
    created_at: datetime
    updated_at: datetime
    id: int | None = None
    status: ReservationStatus = ReservationStatus.PENDING
    completed_at: datetime | None = None
    reason: str = ""
    platform_cancelled: bool = False

    @property
    def deadline(self) -> datetime:
        return min(self.created_at + timedelta(hours=24), self.terms.meeting_at)

    def is_due(self, now: datetime) -> bool:
        return self.status == ReservationStatus.PENDING and now >= self.deadline

    def transition(
        self, status: ReservationStatus, now: datetime, reason: str = ""
    ) -> None:
        self.status = status
        self.updated_at = now
        self.reason = reason


@dataclass
class Product:
    seller_id: int
    created_at: datetime
    content: ProductContent = field(default_factory=ProductContent)
    id: int | None = None
    status: ProductStatus = ProductStatus.DRAFT
    version: int = 1
    published_at: datetime | None = None
    approved_digest: str | None = None

    def edit(self, content: ProductContent) -> bool:
        if self.status not in EDITABLE:
            raise changed_state("请先撤回审核或下架，再在可编辑状态下修改。")
        changed = content != self.content
        self.content = content
        return changed

    def submit_for_review(self, now: datetime) -> ReviewSubmission:
        if self.status not in EDITABLE:
            raise changed_state("当前商品不能提交审核，请刷新。")
        self.content.validate_submission()
        self.status = ProductStatus.PENDING
        return ReviewSubmission(self.id, self.content.snapshot(), now)

    def withdraw_review(
        self, review: ReviewSubmission, actor_id: int, now: datetime
    ) -> None:
        self._resolve_review(review, ReviewStatus.WITHDRAWN, actor_id, now)
        self.status = ProductStatus.DRAFT

    def approve_review(
        self, review: ReviewSubmission, actor_id: int, now: datetime
    ) -> None:
        self._resolve_review(review, ReviewStatus.APPROVED, actor_id, now)
        digest = canonical_digest(review.content)
        if digest != self.approved_digest:
            self.published_at = now
            self.approved_digest = digest
        self.status = ProductStatus.PUBLISHED

    def reject_review(
        self, review: ReviewSubmission, actor_id: int, now: datetime, reason: str
    ) -> None:
        self._resolve_review(
            review, ReviewStatus.REJECTED, actor_id, now, needed_reason(reason)
        )
        self.status = ProductStatus.REJECTED

    def _resolve_review(
        self,
        review: ReviewSubmission,
        status: ReviewStatus,
        actor_id: int,
        now: datetime,
        reason: str = "",
    ) -> None:
        if self.status != ProductStatus.PENDING or review.product_id != self.id:
            raise changed_state("审核提交已变化，请刷新后查看当前内容。")
        review.resolve(status, actor_id, now, reason)

    def take_down(self) -> None:
        if self.status != ProductStatus.PUBLISHED:
            raise changed_state("只有当前可预约的已发布商品可以下架。")
        self.status = ProductStatus.OFFLINE

    def create_reservation(
        self, buyer_id: int, terms: DeliveryTerms, now: datetime
    ) -> Reservation:
        if buyer_id == self.seller_id:
            raise forbidden()
        if self.status == ProductStatus.RESERVED:
            raise Problem(
                409, "already_reserved", "商品已被预约，请刷新集市选择其他商品。"
            )
        if self.status != ProductStatus.PUBLISHED:
            raise changed_state("商品当前不可预约，请刷新集市。")
        terms.validate(now)
        self.status = ProductStatus.RESERVED
        return Reservation(
            self.id, buyer_id, self.content.title, self.content.price, terms, now, now
        )

    def _require_active(self, reservation: Reservation) -> None:
        if (
            self.status != ProductStatus.RESERVED
            or reservation.product_id != self.id
            or reservation.status not in ACTIVE
        ):
            raise changed_state("这条预约已结束，请刷新查看最新结果。")

    def accept_reservation(self, reservation: Reservation, now: datetime) -> None:
        self._require_active(reservation)
        if reservation.is_due(now):
            raise Problem(
                409, "reservation_expired", "预约已过期，请刷新查看释放结果。"
            )
        if reservation.status != ReservationStatus.PENDING:
            raise changed_state("预约已处理，请刷新。")
        reservation.transition(ReservationStatus.CONFIRMED, now)

    def reject_reservation(
        self, reservation: Reservation, now: datetime, reason: str
    ) -> None:
        self._require_active(reservation)
        if reservation.status != ReservationStatus.PENDING:
            raise changed_state("只有待确认的预约可以拒绝。")
        self._release(
            reservation, ReservationStatus.REJECTED, now, needed_reason(reason)
        )

    def cancel_reservation(
        self, reservation: Reservation, actor_id: int, now: datetime, reason: str
    ) -> None:
        self._require_active(reservation)
        if (
            reservation.status == ReservationStatus.PENDING
            and actor_id == self.seller_id
        ):
            raise changed_state("卖家可填写原因并拒绝待确认的预约。")
        if reservation.status == ReservationStatus.CONFIRMED:
            needed_reason(reason)
        self._release(reservation, ReservationStatus.CANCELLED, now, reason)

    def expire_reservation(self, reservation: Reservation, now: datetime) -> None:
        self._require_active(reservation)
        self._release(
            reservation, ReservationStatus.EXPIRED, now, "超过卖家确认截止时间。"
        )

    def _release(
        self,
        reservation: Reservation,
        target: ReservationStatus,
        now: datetime,
        reason: str,
    ) -> None:
        self.status = ProductStatus.PUBLISHED
        reservation.transition(target, now, reason)

    def complete_reservation(
        self, reservation: Reservation, now: datetime, received: bool
    ) -> None:
        self._require_active(reservation)
        if reservation.status != ReservationStatus.CONFIRMED:
            raise changed_state("待卖家接受后才能确认交付。")
        if not received:
            raise Problem(422, "receipt_required", "请在实际收到物品后勾选确认并提交。")
        reservation.transition(ReservationStatus.COMPLETED, now)
        reservation.completed_at = now
        self.status = ProductStatus.SOLD

    def ban(
        self,
        reservation: Reservation | None,
        review: ReviewSubmission | None,
        actor_id: int,
        now: datetime,
        reason: str,
    ) -> None:
        if self.status not in BANNABLE:
            raise changed_state("当前商品不可封禁，请刷新查看可用操作。")
        needed_reason(reason)
        if reservation is not None:
            self._require_active(reservation)
            reservation.transition(ReservationStatus.CANCELLED, now, reason)
            reservation.platform_cancelled = True
        if review is not None:
            review.resolve(ReviewStatus.WITHDRAWN, actor_id, now, reason)
        self.status = ProductStatus.BANNED

    def mark_violation(self, reason: str) -> None:
        if self.status != ProductStatus.SOLD:
            raise changed_state("只有已售出商品可以追加违规标记。")
        needed_reason(reason)
