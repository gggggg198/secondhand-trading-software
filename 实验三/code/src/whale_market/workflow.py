import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import NAMESPACE_OID, UUID, uuid5

import psycopg
from psycopg.types.json import Jsonb

from .accounts import Account
from .commands import (
    ADMIN_ACTIONS,
    RESERVATION_ACTIONS,
    SELLER_ACTIONS,
    Action,
    Command,
)
from .db import open_database
from .domain import (
    Problem,
    Product,
    ProductStatus,
    Reservation,
    ReservationStatus,
    ReviewSubmission,
    changed_state,
    forbidden,
    missing,
    text_value,
    utc_now,
)
from .store import AuditEntry, MarketStore, write_audit

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Submission:
    actor_ref: str
    action: Action
    key: UUID
    digest: str

    def lock(self, store: MarketStore) -> None:
        material = f"whale-market/command/1:{self.actor_ref}:{self.action}:{self.key}"
        number = int.from_bytes(sha256(material.encode()).digest()[:8], signed=True)
        store.connection.execute("SELECT pg_advisory_xact_lock(%s::bigint)", (number,))

    def read(self, store: MarketStore) -> dict | None:
        return store.connection.execute(
            """
            SELECT request_digest, product_id, reservation_id, review_id, http_status, body
            FROM operation_result WHERE actor_ref = %s AND action = %s AND submission_key = %s
            """,
            (self.actor_ref, self.action, self.key),
        ).fetchone()

    def save(
        self, store: MarketStore, change: "Change", outcome: "Outcome", now: datetime
    ) -> None:
        store.connection.execute(
            """
            INSERT INTO operation_result (actor_ref, action, submission_key, request_digest,
                product_id, reservation_id, review_id, http_status, body, recorded_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                self.actor_ref,
                self.action,
                self.key,
                self.digest,
                change.product_id,
                change.reservation_id,
                change.review_id,
                outcome.status,
                Jsonb(outcome.body),
                now,
            ),
        )


@dataclass(frozen=True)
class Outcome:
    status: int
    body: dict


@dataclass(frozen=True)
class ExpireFirst:
    product_id: int
    reservation_id: int


@dataclass
class Change:
    product: Product | None = None
    reservation: Reservation | None = None
    review: ReviewSubmission | None = None
    changed: bool = True
    reason: str = ""

    @property
    def product_id(self) -> int | None:
        return self.product.id if self.product else None

    @property
    def reservation_id(self) -> int | None:
        return self.reservation.id if self.reservation else None

    @property
    def review_id(self) -> int | None:
        return self.review.id if self.review else None

    def public_state(self) -> dict:
        return {
            "product_id": self.product_id,
            "product_status": self.product.status if self.product else None,
            "version": self.product.version if self.product else None,
            "reservation_id": self.reservation_id,
            "reservation_status": self.reservation.status if self.reservation else None,
            "review_id": self.review_id,
            "review_status": self.review.status if self.review else None,
        }

    def audit_state(self) -> str | None:
        records = (self.product, self.reservation, self.review)
        states = [record.status for record in records if record is not None]
        return " / ".join(states) if states else None

    def audit_target(self) -> tuple[str, int | None]:
        if self.reservation is not None:
            return "reservation", self.reservation_id
        if self.review is not None:
            return "review", self.review_id
        return "product", self.product_id


class ProductWorkflow:
    def __init__(
        self,
        database_url: str,
        clock: Callable[[], datetime] = utc_now,
        checkpoint: Callable[[str], None] | None = None,
    ) -> None:
        self.database_url = database_url
        self.clock = clock
        self.checkpoint = checkpoint

    def execute(self, command: Command, actor: Account) -> Outcome:
        submission = Submission(
            str(actor.id), command.action, command.submission_key, command.digest
        )
        try:
            for _ in range(3):
                response = self._attempt(command, actor, submission)
                if isinstance(response, Outcome):
                    return response
                self.expire_if_due(response.product_id, response.reservation_id)
        except Problem as problem:
            if problem.code != "outcome_unknown":
                self._audit_rejected_request(command, actor.id, problem)
            raise
        raise Problem(503, "retry_original", "占用状态正在变化，请用原提交标记重试。")

    def _attempt(
        self,
        command: Command,
        actor: Account,
        submission: Submission,
    ) -> Outcome | ExpireFirst:
        committing = False
        try:
            with open_database(self.database_url) as connection:
                store = MarketStore(connection)
                self._set_timeouts(store)
                submission.lock(store)
                previous = submission.read(store)
                if previous is not None:
                    return self._replay(store, actor, submission, previous)

                change = self._load_target(store, command, actor)
                product = change.product
                now = self.clock()
                active = (
                    store.active_reservation(product.id)
                    if product is not None
                    and command.action in {Action.RESERVE, Action.ACCEPT, Action.BAN}
                    else None
                )
                if self._needs_expiry(command, active, now):
                    connection.rollback()
                    return ExpireFirst(product.id, active.id)
                if command.action == Action.BAN:
                    change.reservation = active
                    change.review = store.pending_review(product.id)

                before = change.audit_state()
                try:
                    with connection.transaction():
                        self._check_version(command, change)
                        self._apply(store, command, change, actor.id, now)
                        if change.changed:
                            store.verify_product_links(change.product)
                except Problem as problem:
                    change = self._load_target(store, command, actor, lock=False)
                    outcome = Outcome(problem.status, problem.payload())
                    self._save_result(
                        store,
                        submission,
                        change,
                        outcome,
                        now,
                        actor.id,
                        before,
                        problem.message,
                    )
                else:
                    status = (
                        201 if command.action in {Action.DRAFT, Action.RESERVE} else 200
                    )
                    outcome = self._success(change, status)
                    self._save_result(
                        store, submission, change, outcome, now, actor.id, before
                    )

                self._checkpoint("before_commit")
                committing = True
            return outcome
        except psycopg.Error as error:
            raise self._storage_problem(error, committing) from None

    @staticmethod
    def _set_timeouts(store: MarketStore) -> None:
        store.connection.execute("SET LOCAL lock_timeout = '5s'")
        store.connection.execute("SET LOCAL statement_timeout = '10s'")
        store.connection.execute(
            "SET LOCAL idle_in_transaction_session_timeout = '15s'"
        )

    @staticmethod
    def _check_admin(store: MarketStore, actor: Account) -> None:
        row = store.connection.execute(
            "SELECT is_admin FROM account WHERE id = %s FOR SHARE", (actor.id,)
        ).fetchone()
        if not row or not row["is_admin"]:
            raise forbidden()

    def _load_target(
        self,
        store: MarketStore,
        command: Command,
        actor: Account,
        *,
        lock: bool = True,
    ) -> Change:
        if command.action in ADMIN_ACTIONS and not actor.is_admin:
            raise forbidden()
        if command.action == Action.DRAFT:
            return Change()
        product = store.product(command.product_id, lock=lock)
        if product is None:
            raise missing("商品")

        if command.action in ADMIN_ACTIONS:
            self._check_admin(store, actor)
        if command.action in SELLER_ACTIONS and product.seller_id != actor.id:
            raise forbidden()
        if command.action == Action.RESERVE:
            if product.seller_id == actor.id:
                raise forbidden()
            if product.published_at is None:
                raise missing("商品")

        reservation = None
        if command.action in RESERVATION_ACTIONS:
            reservation = store.reservation(command.reservation_id)
            if reservation is None or reservation.product_id != product.id:
                raise missing("预约")
            buyer = reservation.buyer_id == actor.id
            seller = product.seller_id == actor.id
            if command.action == Action.COMPLETE and not buyer:
                raise forbidden()
            if (
                command.action in {Action.ACCEPT, Action.REJECT_RESERVATION}
                and not seller
            ):
                raise forbidden()
            if command.action == Action.CANCEL and not (seller or buyer):
                raise forbidden()

        review = (
            store.review(command.review_id) if command.review_id is not None else None
        )
        if review is not None and review.product_id != product.id:
            raise missing("审核提交")
        return Change(product, reservation, review)

    @staticmethod
    def _needs_expiry(
        command: Command, active: Reservation | None, now: datetime
    ) -> bool:
        if active is None or not active.is_due(now):
            return False
        return command.action == Action.RESERVE or (
            command.action == Action.ACCEPT and active.id == command.reservation_id
        )

    @staticmethod
    def _check_version(command: Command, change: Change) -> None:
        if (
            command.action == Action.ACCEPT
            and change.reservation.status == ReservationStatus.EXPIRED
        ):
            raise Problem(
                409, "reservation_expired", "预约已过期，请刷新查看释放结果。"
            )
        if change.product is not None and command.version != change.product.version:
            if (
                command.action == Action.RESERVE
                and change.product.status == ProductStatus.RESERVED
            ):
                raise Problem(
                    409, "already_reserved", "商品已被预约，请刷新集市选择其他商品。"
                )
            raise changed_state("商品或预约已被其他操作更新，请刷新后重新提交。")

    def _apply(
        self,
        store: MarketStore,
        command: Command,
        change: Change,
        actor_id: int,
        now: datetime,
    ) -> None:
        action = command.action
        reason = text_value(command.reason, 200)
        change.reason = reason
        if action == Action.DRAFT:
            product = Product(actor_id, now, command.content.to_domain())
            store.verify_owned_images(product)
            store.insert_product(product)
            change.product = product
            self._checkpoint("after_product")
            return

        product = change.product
        current_reservation = change.reservation
        current_review = change.review
        match action:
            case Action.EDIT:
                change.changed = product.edit(command.content.to_domain())
                if change.changed:
                    store.verify_owned_images(product)
            case Action.SUBMIT:
                change.review = product.submit_for_review(now)
            case Action.WITHDRAW | Action.APPROVE | Action.REJECT_REVIEW:
                if current_review is None:
                    raise changed_state("原送审记录已变化，请刷新审核页面。")
                if action == Action.WITHDRAW:
                    product.withdraw_review(current_review, actor_id, now)
                elif action == Action.APPROVE:
                    product.approve_review(current_review, actor_id, now)
                else:
                    product.reject_review(current_review, actor_id, now, reason)
            case Action.OFFLINE:
                product.take_down()
            case Action.RESERVE:
                change.reservation = product.create_reservation(
                    actor_id, command.delivery.to_domain(), now
                )
            case Action.ACCEPT:
                product.accept_reservation(current_reservation, now)
            case Action.REJECT_RESERVATION:
                product.reject_reservation(current_reservation, now, reason)
            case Action.CANCEL:
                product.cancel_reservation(current_reservation, actor_id, now, reason)
            case Action.COMPLETE:
                product.complete_reservation(current_reservation, now, command.received)
            case Action.BAN:
                product.ban(current_reservation, current_review, actor_id, now, reason)
            case Action.MARK_VIOLATION:
                product.mark_violation(reason)
                store.connection.execute(
                    """
                    INSERT INTO product_violation (product_id, administrator_id, reason, recorded_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (product.id, actor_id, reason, now),
                )
            case _:
                raise RuntimeError("Unhandled product command")

        if change.changed:
            self._persist(store, change, images_changed=action == Action.EDIT)

    def _persist(
        self, store: MarketStore, change: Change, *, images_changed: bool = False
    ) -> None:
        if change.reservation is not None:
            store.save_reservation(change.reservation)
            self._checkpoint("after_reservation")
        if change.review is not None:
            store.save_review(change.review)
        change.product.version += 1
        store.update_product(change.product, images_changed=images_changed)
        self._checkpoint("after_product")

    @staticmethod
    def _success(change: Change, status: int) -> Outcome:
        state = change.public_state()
        return Outcome(
            status,
            {
                "operation": {**state, "changed": change.changed},
                "current": state,
                "replayed": False,
            },
        )

    def _save_result(
        self,
        store: MarketStore,
        submission: Submission,
        change: Change,
        outcome: Outcome,
        now: datetime,
        actor_id: int | None,
        before: str | None,
        failure: str = "",
    ) -> None:
        submission.save(store, change, outcome, now)
        if failure or change.changed:
            kind, identifier = change.audit_target()
            write_audit(
                store.connection,
                AuditEntry(
                    actor_id,
                    submission.action,
                    kind,
                    identifier,
                    now,
                    product_id=change.product_id,
                    reservation_id=change.reservation_id,
                    before_state=before,
                    after_state=before if failure else change.audit_state(),
                    outcome="FAILURE" if failure else "SUCCESS",
                    reason=failure or change.reason,
                ),
            )
            self._checkpoint("after_audit")

    def _replay(
        self,
        store: MarketStore,
        actor: Account,
        submission: Submission,
        previous: dict,
    ) -> Outcome:
        product = (
            store.product(previous["product_id"], lock=True)
            if previous["product_id"]
            else None
        )
        reservation = (
            store.reservation(previous["reservation_id"])
            if previous["reservation_id"]
            else None
        )
        review = store.review(previous["review_id"]) if previous["review_id"] else None
        if submission.action in ADMIN_ACTIONS:
            self._check_admin(store, actor)
        elif (
            submission.action in SELLER_ACTIONS | {Action.DRAFT}
            and product
            and product.seller_id != actor.id
        ):
            raise forbidden()
        if reservation and product and submission.action not in ADMIN_ACTIONS:
            if actor.id not in {product.seller_id, reservation.buyer_id}:
                raise forbidden()
        if previous["request_digest"] != submission.digest:
            raise Problem(
                409,
                "submission_conflict",
                "此提交标记已经用于其他内容，请刷新后新建提交。",
            )
        body = dict(previous["body"])
        if previous["http_status"] < 300:
            body["current"] = Change(product, reservation, review).public_state()
        body["replayed"] = True
        return Outcome(previous["http_status"], body)

    def expire_if_due(self, product_id: int, reservation_id: int) -> bool:
        submission = Submission(
            "system",
            Action.EXPIRE,
            uuid5(NAMESPACE_OID, f"whale-market/expire/{reservation_id}"),
            str(reservation_id),
        )
        committing = False
        try:
            with open_database(self.database_url) as connection:
                store = MarketStore(connection)
                self._set_timeouts(store)
                submission.lock(store)
                if submission.read(store) is not None:
                    return False
                product = store.product(product_id, lock=True)
                if product is None or product.status != ProductStatus.RESERVED:
                    return False
                reservation = store.active_reservation(product_id)
                now = self.clock()
                if (
                    reservation is None
                    or reservation.id != reservation_id
                    or not reservation.is_due(now)
                ):
                    return False
                change = Change(product, reservation)
                before = change.audit_state()
                product.expire_reservation(reservation, now)
                change.reason = reservation.reason
                self._persist(store, change)
                store.verify_product_links(product)
                self._save_result(
                    store,
                    submission,
                    change,
                    self._success(change, 200),
                    now,
                    None,
                    before,
                )
                self._checkpoint("before_commit")
                committing = True
        except psycopg.Error as error:
            raise self._storage_problem(error, committing) from None
        return True

    def expire_batch(self, limit: int = 100) -> int:
        with open_database(self.database_url) as connection:
            due = connection.execute(
                """
                SELECT product_id, id FROM reservation
                WHERE status = 'PENDING' AND LEAST(created_at + INTERVAL '24 hours', meeting_at) <= %s
                ORDER BY LEAST(created_at + INTERVAL '24 hours', meeting_at), id LIMIT %s
                """,
                (self.clock(), limit),
            ).fetchall()
        for row in due:
            try:
                self.expire_if_due(row["product_id"], row["id"])
            except Problem as error:
                LOGGER.warning("Reservation expiration postponed (%s)", error.code)
        return len(due)

    def _audit_rejected_request(
        self, command: Command, actor_id: int, problem: Problem
    ) -> None:
        identifier = command.reservation_id or command.review_id or command.product_id
        kind = (
            "reservation"
            if command.reservation_id
            else "review"
            if command.review_id
            else "product"
        )
        try:
            with open_database(self.database_url) as connection:
                write_audit(
                    connection,
                    AuditEntry(
                        actor_id,
                        command.action,
                        kind,
                        identifier,
                        self.clock(),
                        outcome="FAILURE",
                        reason=problem.message,
                    ),
                )
        except psycopg.Error as error:
            LOGGER.warning("Failure audit unavailable (%s)", type(error).__name__)

    def _checkpoint(self, name: str) -> None:
        if self.checkpoint is not None:
            self.checkpoint(name)

    @staticmethod
    def _storage_problem(error: psycopg.Error, committing: bool) -> Problem:
        LOGGER.warning("Trade transaction interrupted (%s)", type(error).__name__)
        if committing and (error.sqlstate is None or error.sqlstate.startswith("08")):
            return Problem(
                503,
                "outcome_unknown",
                "连接中断，提交结果尚未确认。请用原提交标记查询结果。",
            )
        return Problem(
            503, "retry_original", "数据库操作暂未完成，请稍后使用原提交标记重试。"
        )
