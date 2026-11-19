from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from psycopg import Connection, IsolationLevel
from psycopg.rows import DictRow

from .accounts import Account
from .db import ADMIN_PERMISSION_LOCK, lock_transaction, open_database
from .domain import (
    CATEGORIES,
    Problem,
    ProductStatus,
    forbidden,
    missing,
    money_value,
    text_value,
    utc_now,
)
from .store import AuditEntry, write_audit

PAGE_SIZE = 20
BEIJING = ZoneInfo("Asia/Shanghai")
ProductScope = Literal["public", "mine", "all"]
ReservationScope = Literal["buy", "sell", "all"]

PRODUCT_COLUMNS = """
    p.id, p.seller_id, a.username AS seller_name, p.title, p.description,
    p.category, p.condition, p.price, p.status, p.version, p.created_at, p.published_at,
    ARRAY(SELECT image_id FROM product_image pi WHERE pi.product_id = p.id ORDER BY pi.position) AS image_ids,
    (SELECT count(*) FROM favorite f WHERE f.product_id = p.id) AS followers,
    EXISTS(SELECT 1 FROM favorite f WHERE f.product_id = p.id AND f.account_id = %s) AS is_favorite
"""
PRODUCT_FROM = "product p JOIN account a ON a.id = p.seller_id"
BOOKING_COLUMNS = """
    r.id, r.product_id, r.product_title, r.buyer_id, p.seller_id, buyer.username AS buyer_name,
    seller.username AS seller_name, r.price, r.status, r.created_at, r.updated_at, r.completed_at,
    LEAST(r.created_at + INTERVAL '24 hours', r.meeting_at) AS deadline,
    p.status AS product_status, p.version AS product_version, r.reason, r.platform_cancelled
"""
BOOKING_FROM = """
    reservation r JOIN product p ON p.id = r.product_id
    JOIN account buyer ON buyer.id = r.buyer_id JOIN account seller ON seller.id = p.seller_id
"""


def actor_id(actor: Account | None) -> int | None:
    return actor.id if actor else None


def has_admin_access(connection: Connection[DictRow], actor: Account | None) -> bool:
    if actor is None or not actor.is_admin:
        return False
    row = connection.execute(
        "SELECT is_admin FROM account WHERE id = %s", (actor.id,)
    ).fetchone()
    return bool(row and row["is_admin"])


def require_admin(connection: Connection[DictRow], actor: Account) -> None:
    if not has_admin_access(connection, actor):
        raise forbidden()


def page_result(items: list[dict], total: int, page: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": PAGE_SIZE}


def page_rows(
    connection: Connection[DictRow],
    columns: str,
    source: str,
    clauses: list[str],
    values: list,
    order: str,
    page: int,
    select_values: tuple = (),
) -> dict:
    # All SQL fragments are fixed by callers. Filters are PostgreSQL parameters.
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    total = connection.execute(
        f"SELECT count(*) AS n FROM {source}{where}", values
    ).fetchone()["n"]
    rows = connection.execute(
        f"SELECT {columns} FROM {source}{where} ORDER BY {order} LIMIT %s OFFSET %s",
        (*select_values, *values, PAGE_SIZE, (page - 1) * PAGE_SIZE),
    ).fetchall()
    return page_result(rows, total, page)


def money_strings(record: dict) -> dict:
    for key in ("price", "total_amount"):
        if record.get(key) is not None:
            record[key] = format(record[key], ".2f")
    return record


def format_products(result: dict) -> dict:
    result["items"] = [money_strings(product) for product in result["items"]]
    return result


def day_start(value: date) -> datetime:
    try:
        return datetime.combine(value, time.min, tzinfo=BEIJING).astimezone(UTC)
    except OverflowError:
        raise Problem(
            422, "invalid_date_range", "日期超出可换算范围，请重新选择。"
        ) from None


def read_auth() -> Problem:
    return Problem(401, "login_required", "请登录后继续。")


class MarketQueries:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def read_connection(self) -> Connection[DictRow]:
        connection = open_database(self.database_url)
        connection.isolation_level = IsolationLevel.REPEATABLE_READ
        return connection

    def products(
        self,
        actor: Account | None,
        scope: ProductScope,
        state: ProductStatus | None,
        keyword: str,
        category: str,
        minimum: str | None,
        maximum: str | None,
        page: int,
    ) -> dict:
        if scope != "public" and actor is None:
            raise read_auth()
        if scope == "public" and state not in (None, ProductStatus.PUBLISHED):
            raise forbidden()
        lower = money_value(minimum, filter_bound=True)
        upper = money_value(maximum, filter_bound=True)
        if lower is not None and upper is not None and lower > upper:
            raise Problem(
                422, "invalid_price", "最低价不能高于最高价，请修改筛选区间。"
            )
        keyword = text_value(keyword, 60)
        if category and category not in CATEGORIES:
            raise Problem(422, "invalid_category", "请选择有效分类。")

        clauses, values = [], []
        if scope == "public":
            clauses.append("p.status = 'PUBLISHED'")
        elif scope == "mine":
            clauses.append("p.seller_id = %s")
            values.append(actor.id)
        if state is not None and scope != "public":
            clauses.append("p.status = %s")
            values.append(str(state))
        if keyword:
            clauses.append(
                "(strpos(lower(p.title), lower(%s)) > 0 OR strpos(lower(p.description), lower(%s)) > 0)"
            )
            values.extend((keyword, keyword))
        if category:
            clauses.append("p.category = %s")
            values.append(category)
        if lower is not None:
            clauses.append("p.price >= %s")
            values.append(lower)
        if upper is not None:
            clauses.append("p.price <= %s")
            values.append(upper)
        with self.read_connection() as connection:
            if scope == "all":
                require_admin(connection, actor)
            return format_products(
                page_rows(
                    connection,
                    PRODUCT_COLUMNS,
                    PRODUCT_FROM,
                    clauses,
                    values,
                    "p.published_at DESC NULLS LAST, p.id",
                    page,
                    (actor_id(actor),),
                )
            )

    def product(self, product_id: int, actor: Account | None) -> dict:
        with self.read_connection() as connection:
            is_admin = has_admin_access(connection, actor)
            row = connection.execute(
                f"""
                SELECT {PRODUCT_COLUMNS} FROM {PRODUCT_FROM}
                WHERE p.id = %s AND (p.status = 'PUBLISHED' OR p.seller_id = %s OR %s)
                """,
                (actor_id(actor), product_id, actor_id(actor), is_admin),
            ).fetchone()
            if row is None:
                raise missing("商品")
            if row["seller_id"] == actor_id(actor) or is_admin:
                row["review"] = connection.execute(
                    """
                    SELECT id, content, status, submitted_at, resolved_at, reason
                    FROM review_submission WHERE product_id = %s ORDER BY id DESC LIMIT 1
                    """,
                    (product_id,),
                ).fetchone()
                row["violations"] = connection.execute(
                    """
                    SELECT reason, recorded_at FROM product_violation
                    WHERE product_id = %s ORDER BY id DESC
                    """,
                    (product_id,),
                ).fetchall()
                if row["status"] == ProductStatus.BANNED:
                    ban = connection.execute(
                        """
                        SELECT reason FROM audit_entry WHERE product_id = %s
                        AND action = 'ban' AND outcome = 'SUCCESS' ORDER BY id DESC LIMIT 1
                        """,
                        (product_id,),
                    ).fetchone()
                    row["ban_reason"] = ban["reason"] if ban else ""
        return money_strings(row)

    def favorites(self, actor: Account, page: int) -> dict:
        with self.read_connection() as connection:
            total = connection.execute(
                "SELECT count(*) AS n FROM favorite WHERE account_id = %s",
                (actor.id,),
            ).fetchone()["n"]
            rows = connection.execute(
                f"""
                SELECT f.product_id AS saved_id, {PRODUCT_COLUMNS}
                FROM favorite f LEFT JOIN product p ON p.id = f.product_id AND p.status = 'PUBLISHED'
                LEFT JOIN account a ON a.id = p.seller_id
                WHERE f.account_id = %s ORDER BY f.created_at DESC, f.product_id
                LIMIT %s OFFSET %s
                """,
                (actor.id, actor.id, PAGE_SIZE, (page - 1) * PAGE_SIZE),
            ).fetchall()
        entries = []
        for row in rows:
            saved_id = row.pop("saved_id")
            entries.append(
                {
                    "product_id": saved_id,
                    "product": money_strings(row) if row["id"] else None,
                }
            )
        return page_result(entries, total, page)

    def set_favorite(self, actor: Account, product_id: int, saved: bool) -> dict:
        with open_database(self.database_url) as connection:
            if saved:
                row = connection.execute(
                    "SELECT seller_id, status FROM product WHERE id = %s FOR UPDATE",
                    (product_id,),
                ).fetchone()
                if row is None or row["status"] != ProductStatus.PUBLISHED:
                    raise missing("商品")
                if row["seller_id"] == actor.id:
                    raise Problem(403, "own_product", "只能收藏其他卖家的可预约商品。")
                connection.execute(
                    "INSERT INTO favorite (account_id, product_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (actor.id, product_id),
                )
            else:
                connection.execute(
                    "DELETE FROM favorite WHERE account_id = %s AND product_id = %s",
                    (actor.id, product_id),
                )
        return {"saved": saved}

    def reservations(
        self, actor: Account, scope: ReservationScope, status: str, page: int
    ) -> dict:
        clauses, values = [], []
        if scope == "buy":
            clauses.append("r.buyer_id = %s")
            values.append(actor.id)
        elif scope == "sell":
            clauses.append("p.seller_id = %s")
            values.append(actor.id)
        if status:
            clauses.append("r.status = %s")
            values.append(status)
        with self.read_connection() as connection:
            if scope == "all":
                require_admin(connection, actor)
            result = page_rows(
                connection,
                BOOKING_COLUMNS,
                BOOKING_FROM,
                clauses,
                values,
                "r.id DESC",
                page,
            )
        if scope == "all":
            for row in result["items"]:
                row.pop("deadline")
        return format_products(result)

    def reservation(
        self, actor: Account, booking_id: int, *, audited_access: bool = False
    ) -> dict:
        with self.read_connection() as connection:
            row = connection.execute(
                f"""
                SELECT {BOOKING_COLUMNS}, r.location, r.meeting_at
                FROM {BOOKING_FROM} WHERE r.id = %s
                """,
                (booking_id,),
            ).fetchone()
            if row is None:
                raise missing("预约")
            party = actor.id in (row["buyer_id"], row["seller_id"])
            if audited_access or not party:
                require_admin(connection, actor)
            if audited_access or (party and has_admin_access(connection, actor)):
                write_audit(
                    connection,
                    AuditEntry(
                        actor.id,
                        "read_delivery",
                        "reservation",
                        booking_id,
                        utc_now(),
                        product_id=row["product_id"],
                        reservation_id=booking_id,
                        outcome="ACCESS",
                        before_state=row["status"],
                        after_state=row["status"],
                        reason="管理员查看交付信息。",
                    ),
                )
            if not (party or audited_access):
                for key in ("location", "meeting_at", "deadline"):
                    row.pop(key)
            row["delivery_visible"] = party or audited_access
            return money_strings(row)

    def statistics(
        self, actor: Account, all_accounts: bool, start: date, end: date
    ) -> dict:
        if start >= end:
            raise Problem(422, "invalid_date_range", "结束日期须晚于开始日期。")
        with self.read_connection() as connection:
            if all_accounts:
                require_admin(connection, actor)
            seller = actor.id if not all_accounts else None
            counts = connection.execute(
                "SELECT status, count(*) AS total FROM product WHERE (%s::bigint IS NULL OR seller_id = %s) GROUP BY status",
                (seller, seller),
            ).fetchall()
            total = connection.execute(
                """
                SELECT count(*) AS completed, COALESCE(sum(r.price), 0) AS total_amount
                FROM reservation r JOIN product p ON p.id = r.product_id
                WHERE r.status = 'COMPLETED' AND r.completed_at >= %s AND r.completed_at < %s
                AND (%s::bigint IS NULL OR p.seller_id = %s)
                """,
                (day_start(start), day_start(end), seller, seller),
            ).fetchone()
        states = dict.fromkeys((state.value for state in ProductStatus), 0)
        states.update((row["status"], row["total"]) for row in counts)
        return {"start": start, "end": end, "counts": states, **money_strings(total)}

    def audit(
        self,
        actor: Account,
        all_accounts: bool,
        page: int,
        product_id: int | None,
        reservation_id: int | None,
        target_kind: str,
        target_id: int | None,
        operator_id: int | None,
        action: str,
        outcome: str,
        start: date | None,
        end: date | None,
    ) -> dict:
        if start and end and start > end:
            raise Problem(422, "invalid_date_range", "结束日期不能早于开始日期。")
        clauses, values = [], []
        filters = (
            ("e.product_id", product_id),
            ("e.reservation_id", reservation_id),
            ("e.target_kind", target_kind),
            ("e.target_id", target_id),
            ("e.actor_id", operator_id),
            ("e.action", action),
            ("e.outcome", outcome),
        )
        for column, value in filters:
            if value is not None and value != "":
                clauses.append(f"{column} = %s")
                values.append(value)
        if start is not None:
            clauses.append("e.recorded_at >= %s")
            values.append(day_start(start))
        if end is not None and end != date.max:
            clauses.append("e.recorded_at < %s")
            values.append(day_start(end + timedelta(days=1)))
        with self.read_connection() as connection:
            if all_accounts:
                require_admin(connection, actor)
            else:
                self._check_audit_target(
                    connection,
                    actor,
                    product_id,
                    reservation_id,
                    target_kind,
                    target_id,
                )
                clauses.append("(p.seller_id = %s OR r.buyer_id = %s)")
                values.extend((actor.id, actor.id))
            return page_rows(
                connection,
                "e.*, a.username AS actor_name",
                """
                audit_entry e LEFT JOIN account a ON a.id = e.actor_id
                LEFT JOIN product p ON p.id = e.product_id
                LEFT JOIN reservation r ON r.id = e.reservation_id
                """,
                clauses,
                values,
                "e.recorded_at DESC, e.id DESC",
                page,
            )

    @staticmethod
    def _check_audit_target(
        connection: Connection[DictRow],
        actor: Account,
        product_id: int | None,
        reservation_id: int | None,
        target_kind: str,
        target_id: int | None,
    ) -> None:
        booking = reservation_id or (
            target_id if target_kind == "reservation" else None
        )
        product = product_id or (target_id if target_kind == "product" else None)
        if booking is not None:
            row = connection.execute(
                """
                SELECT 1 FROM reservation r JOIN product p ON p.id = r.product_id
                WHERE r.id = %s AND (r.buyer_id = %s OR p.seller_id = %s)
                """,
                (booking, actor.id, actor.id),
            ).fetchone()
            if row is None:
                raise forbidden()
        if product is not None:
            row = connection.execute(
                """
                SELECT 1 FROM product p WHERE p.id = %s AND (p.seller_id = %s OR
                    EXISTS(SELECT 1 FROM reservation r WHERE r.product_id = p.id AND r.buyer_id = %s))
                """,
                (product, actor.id, actor.id),
            ).fetchone()
            if row is None:
                raise forbidden()

    def accounts(self, actor: Account, keyword: str, page: int) -> dict:
        with self.read_connection() as connection:
            require_admin(connection, actor)
            result = page_rows(
                connection,
                "id, username, is_admin",
                "account",
                ["strpos(username_key, lower(%s)) > 0"] if keyword else [],
                [text_value(keyword, 20)] if keyword else [],
                "id",
                page,
            )
            result["administrator_count"] = connection.execute(
                "SELECT count(*) AS n FROM account WHERE is_admin"
            ).fetchone()["n"]
        return result

    def set_admin(self, actor: Account, target_id: int, is_admin: bool) -> dict:
        action = "grant_admin" if is_admin else "revoke_admin"
        blocked = None
        with open_database(self.database_url) as connection:
            lock_transaction(connection, ADMIN_PERMISSION_LOCK)
            require_admin(connection, actor)
            target = connection.execute(
                "SELECT id, username, is_admin FROM account WHERE id = %s FOR UPDATE",
                (target_id,),
            ).fetchone()
            if target is None:
                raise missing("账号")
            before = target["is_admin"]
            if before == is_admin:
                return target
            only_admin = (
                before
                and connection.execute(
                    "SELECT count(*) AS n FROM account WHERE is_admin"
                ).fetchone()["n"]
                == 1
            )
            if only_admin:
                blocked = Problem(
                    409,
                    "last_admin",
                    "请先授予另一账号管理权限，再撤销最后一名管理员。",
                )
            else:
                connection.execute(
                    "UPDATE account SET is_admin = %s WHERE id = %s",
                    (is_admin, target_id),
                )
                target["is_admin"] = is_admin
            write_audit(
                connection,
                AuditEntry(
                    actor.id,
                    action,
                    "account",
                    target_id,
                    utc_now(),
                    before_state="ADMIN" if before else "USER",
                    after_state="ADMIN" if target["is_admin"] else "USER",
                    outcome="FAILURE" if blocked else "SUCCESS",
                    reason=blocked.message if blocked else "",
                ),
            )
        if blocked:
            raise blocked
        return target
