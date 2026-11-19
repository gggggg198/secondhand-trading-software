from dataclasses import dataclass
from datetime import UTC, datetime

from psycopg import Connection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from .domain import (
    DeliveryTerms,
    Problem,
    Product,
    ProductContent,
    ProductStatus,
    Reservation,
    ReservationStatus,
    ReviewStatus,
    ReviewSubmission,
)


@dataclass(frozen=True)
class AuditEntry:
    actor_id: int | None
    action: str
    target_kind: str
    target_id: int | None
    recorded_at: datetime
    product_id: int | None = None
    reservation_id: int | None = None
    before_state: str | None = None
    after_state: str | None = None
    outcome: str = "SUCCESS"
    reason: str = ""


def write_audit(connection: Connection[DictRow], entry: AuditEntry) -> None:
    connection.execute(
        """
        INSERT INTO audit_entry (actor_id, action, target_kind, target_id, product_id,
            reservation_id, before_state, after_state, outcome, reason, recorded_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            entry.actor_id,
            entry.action,
            entry.target_kind,
            entry.target_id,
            entry.product_id,
            entry.reservation_id,
            entry.before_state,
            entry.after_state,
            entry.outcome,
            entry.reason,
            entry.recorded_at,
        ),
    )


class MarketStore:
    def __init__(self, connection: Connection[DictRow]) -> None:
        self.connection = connection

    def product(self, product_id: int, *, lock: bool = False) -> Product | None:
        if (
            lock
            and self.connection.execute(
                "SELECT id FROM product WHERE id = %s FOR UPDATE", (product_id,)
            ).fetchone()
            is None
        ):
            return None
        row = self.connection.execute(
            """
            SELECT p.*, ARRAY(
                SELECT image_id FROM product_image pi WHERE pi.product_id = p.id ORDER BY pi.position
            ) AS image_ids FROM product p WHERE id = %s
            """,
            (product_id,),
        ).fetchone()
        if row is None:
            return None
        return Product(
            id=row["id"],
            seller_id=row["seller_id"],
            status=ProductStatus(row["status"]),
            version=row["version"],
            created_at=row["created_at"],
            published_at=row["published_at"],
            approved_digest=row["approved_digest"],
            content=ProductContent(
                row["title"],
                row["description"],
                row["category"],
                row["condition"],
                row["price"],
                tuple(row["image_ids"]),
            ),
        )

    def verify_owned_images(self, product: Product) -> None:
        image_ids = product.content.image_ids
        if not image_ids:
            return
        row = self.connection.execute(
            "SELECT count(*) AS n FROM uploaded_image WHERE owner_id = %s AND id = ANY(%s)",
            (product.seller_id, list(image_ids)),
        ).fetchone()
        if row["n"] != len(image_ids):
            raise Problem(422, "invalid_image", "请重新选择本人上传的商品图片。")

    def insert_product(self, product: Product) -> None:
        content = product.content
        row = self.connection.execute(
            """
            INSERT INTO product (seller_id, title, description, category, condition, price, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (
                product.seller_id,
                content.title,
                content.description,
                content.category,
                content.condition,
                content.price,
                product.status,
                product.created_at,
            ),
        ).fetchone()
        product.id = row["id"]
        self.save_image_links(product)

    def update_product(self, product: Product, *, images_changed: bool = False) -> None:
        content = product.content
        self.connection.execute(
            """
            UPDATE product SET title = %s, description = %s, category = %s, condition = %s,
                price = %s, status = %s, version = %s, published_at = %s, approved_digest = %s
            WHERE id = %s
            """,
            (
                content.title,
                content.description,
                content.category,
                content.condition,
                content.price,
                product.status,
                product.version,
                product.published_at,
                product.approved_digest,
                product.id,
            ),
        )
        if images_changed:
            self.save_image_links(product)

    def save_image_links(self, product: Product) -> None:
        self.connection.execute(
            "DELETE FROM product_image WHERE product_id = %s", (product.id,)
        )
        if product.content.image_ids:
            self.connection.cursor().executemany(
                "INSERT INTO product_image (product_id, image_id, position) VALUES (%s, %s, %s)",
                [
                    (product.id, image_id, i)
                    for i, image_id in enumerate(product.content.image_ids, 1)
                ],
            )

    def reservation(self, reservation_id: int) -> Reservation | None:
        row = self.connection.execute(
            "SELECT * FROM reservation WHERE id = %s", (reservation_id,)
        ).fetchone()
        return self.reservation_from_row(row) if row else None

    def active_reservation(self, product_id: int) -> Reservation | None:
        row = self.connection.execute(
            "SELECT * FROM reservation WHERE product_id = %s AND status IN ('PENDING', 'CONFIRMED')",
            (product_id,),
        ).fetchone()
        return self.reservation_from_row(row) if row else None

    @staticmethod
    def reservation_from_row(row: DictRow) -> Reservation:
        return Reservation(
            id=row["id"],
            product_id=row["product_id"],
            buyer_id=row["buyer_id"],
            product_title=row["product_title"],
            price=row["price"],
            terms=DeliveryTerms(row["location"], row["meeting_at"].astimezone(UTC)),
            created_at=row["created_at"].astimezone(UTC),
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            status=ReservationStatus(row["status"]),
            reason=row["reason"],
            platform_cancelled=row["platform_cancelled"],
        )

    def save_reservation(self, reservation: Reservation) -> None:
        if reservation.id is None:
            row = self.connection.execute(
                """
                INSERT INTO reservation (product_id, buyer_id, product_title, price, location,
                    meeting_at, created_at, updated_at, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (
                    reservation.product_id,
                    reservation.buyer_id,
                    reservation.product_title,
                    reservation.price,
                    reservation.terms.location,
                    reservation.terms.meeting_at,
                    reservation.created_at,
                    reservation.updated_at,
                    reservation.status,
                ),
            ).fetchone()
            reservation.id = row["id"]
        else:
            self.connection.execute(
                """
                UPDATE reservation SET status = %s, updated_at = %s, completed_at = %s,
                    reason = %s, platform_cancelled = %s WHERE id = %s
                """,
                (
                    reservation.status,
                    reservation.updated_at,
                    reservation.completed_at,
                    reservation.reason,
                    reservation.platform_cancelled,
                    reservation.id,
                ),
            )

    def pending_review(self, product_id: int) -> ReviewSubmission | None:
        row = self.connection.execute(
            "SELECT * FROM review_submission WHERE product_id = %s AND status = 'PENDING'",
            (product_id,),
        ).fetchone()
        return self.review_from_row(row)

    def review(self, review_id: int) -> ReviewSubmission | None:
        row = self.connection.execute(
            "SELECT * FROM review_submission WHERE id = %s",
            (review_id,),
        ).fetchone()
        return self.review_from_row(row)

    @staticmethod
    def review_from_row(row: DictRow | None) -> ReviewSubmission | None:
        if row is None:
            return None
        return ReviewSubmission(
            product_id=row["product_id"],
            id=row["id"],
            content=row["content"],
            status=ReviewStatus(row["status"]),
            submitted_at=row["submitted_at"],
            resolved_at=row["resolved_at"],
            resolved_by=row["resolved_by"],
            reason=row["reason"],
        )

    def save_review(self, review: ReviewSubmission) -> None:
        if review.id is None:
            row = self.connection.execute(
                """
                INSERT INTO review_submission (product_id, content, status, submitted_at)
                VALUES (%s, %s, %s, %s) RETURNING id
                """,
                (
                    review.product_id,
                    Jsonb(review.content),
                    review.status,
                    review.submitted_at,
                ),
            ).fetchone()
            review.id = row["id"]
        else:
            self.connection.execute(
                """
                UPDATE review_submission SET status = %s, resolved_at = %s, resolved_by = %s, reason = %s
                WHERE id = %s
                """,
                (
                    review.status,
                    review.resolved_at,
                    review.resolved_by,
                    review.reason,
                    review.id,
                ),
            )

    def verify_product_links(self, product: Product) -> None:
        row = self.connection.execute(
            """
            SELECT
                EXISTS(SELECT 1 FROM reservation WHERE product_id = p.id
                    AND status IN ('PENDING', 'CONFIRMED')) AS occupied,
                EXISTS(SELECT 1 FROM reservation WHERE product_id = p.id
                    AND status = 'COMPLETED') AS sold,
                EXISTS(SELECT 1 FROM review_submission WHERE product_id = p.id
                    AND status = 'PENDING') AS under_review
            FROM product p WHERE p.id = %s
            """,
            (product.id,),
        ).fetchone()
        if (
            row["occupied"] != (product.status == ProductStatus.RESERVED)
            or row["sold"] != (product.status == ProductStatus.SOLD)
            or row["under_review"] != (product.status == ProductStatus.PENDING)
        ):
            raise RuntimeError("Product and related records have inconsistent states.")
