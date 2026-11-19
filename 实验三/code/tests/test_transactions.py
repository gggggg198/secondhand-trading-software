from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from whale_market.accounts import Account
from whale_market.commands import Command
from whale_market.db import open_database
from whale_market.queries import BEIJING
from whale_market.workflow import ProductWorkflow


def prepare(market, action):
    state = market.publish()
    if action == "reserve":
        return market.buyer, market.payload(
            "reserve", state, delivery=market.delivery()
        )
    reserved = market.reserve(state)
    key = {"reservation_id": reserved["reservation_id"]}
    if action == "accept":
        return market.seller, market.payload(action, reserved, **key)
    if action == "cancel":
        return market.buyer, market.payload(action, reserved, **key)
    if action == "ban":
        return market.admin, market.payload(action, reserved, reason="违规验收")
    confirmed = market.command(market.seller, "accept", reserved, **key)["operation"]
    return market.buyer, market.payload(action, confirmed, received=True, **key)


def read_state(database_url, product_id):
    with open_database(database_url) as connection:
        values = connection.execute(
            """
            SELECT status, version, published_at, approved_digest,
                (SELECT count(*) FROM operation_result WHERE product_id = p.id) AS operation_count,
                (SELECT count(*) FROM audit_entry WHERE product_id = p.id) AS audit_count
            FROM product p WHERE id = %s
            """,
            (product_id,),
        ).fetchone()
        records = connection.execute(
            "SELECT * FROM reservation WHERE product_id = %s ORDER BY id",
            (product_id,),
        ).fetchall()
    return values, records


@pytest.mark.parametrize("action", ["reserve", "cancel", "complete", "ban"])
@pytest.mark.parametrize(
    "point", ["after_reservation", "after_product", "after_audit", "before_commit"]
)
def test_transaction_failure_between_each_write_and_commit(market, action, point):
    actor, payload = prepare(market, action)
    command = Command.model_validate(payload)
    before = read_state(market.database_url, command.product_id)

    def checkpoint(current):
        if current == point:
            raise RuntimeError("injected validation fault")

    workflow = ProductWorkflow(market.database_url, checkpoint=checkpoint)
    with pytest.raises(RuntimeError, match="injected validation fault"):
        workflow.execute(command, actor.account)
    assert read_state(market.database_url, command.product_id) == before

    restarted = ProductWorkflow(market.database_url)
    result = restarted.execute(command, actor.account)
    assert result.status in (200, 201)
    after = read_state(market.database_url, command.product_id)
    assert after[0]["version"] == before[0]["version"] + 1
    replay = ProductWorkflow(market.database_url).execute(command, actor.account)
    assert (
        replay.body["replayed"] and replay.body["operation"] == result.body["operation"]
    )
    assert read_state(market.database_url, command.product_id) == after


@pytest.mark.parametrize("action", ["reserve", "accept", "cancel", "complete"])
def test_concurrent_identical_commands_have_one_effect(market, action):
    actor, payload = prepare(market, action)
    command = Command.model_validate(payload)
    before = read_state(market.database_url, command.product_id)
    start = Barrier(2, timeout=10)
    workflow = ProductWorkflow(market.database_url)

    def execute(_):
        start.wait()
        return workflow.execute(command, actor.account)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(execute, range(2)))
    assert first.status == second.status in (200, 201)
    assert first.body["operation"] == second.body["operation"]
    assert {first.body["replayed"], second.body["replayed"]} == {True, False}
    after = read_state(market.database_url, command.product_id)[0]
    assert (after["version"], after["operation_count"], after["audit_count"]) == (
        before[0]["version"] + 1,
        before[0]["operation_count"] + 1,
        before[0]["audit_count"] + 1,
    )


def test_a_hundred_buyers_share_no_duplicate_occupancy(market):
    offered = market.publish()
    with open_database(market.database_url) as connection:
        names = connection.execute(
            """
            INSERT INTO account (username, password_hash)
            SELECT 'LoadBuyer' || n, 'fixture' FROM generate_series(1, 100) n
            RETURNING id, username, is_admin
            """
        ).fetchall()
    start = Barrier(100, timeout=25)
    workflow = ProductWorkflow(market.database_url)

    def bid(row):
        command = Command.model_validate(
            market.payload("reserve", offered, delivery=market.delivery())
        )
        start.wait()
        return workflow.execute(command, Account(**row))

    with ThreadPoolExecutor(max_workers=100) as pool:
        responses = list(pool.map(bid, names))
    statuses = [item.status for item in responses]
    assert (statuses.count(201), statuses.count(409)) == (1, 99)
    product, reservations = read_state(market.database_url, offered["product_id"])
    assert product["status"] == "RESERVED" and len(reservations) == 1
    assert reservations[0]["status"] == "PENDING"


def test_buyers_and_seller_take_down_share_the_same_product_lock(market):
    offered = market.publish()
    inputs = [
        (market.seller, market.payload("offline", offered)),
        (market.buyer, market.payload("reserve", offered, delivery=market.delivery())),
        (market.other, market.payload("reserve", offered, delivery=market.delivery())),
    ]
    start = Barrier(3, timeout=10)
    workflow = ProductWorkflow(market.database_url)

    def compete(item):
        actor, payload = item
        start.wait()
        return workflow.execute(Command.model_validate(payload), actor.account)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(compete, inputs))
    assert sum(result.status < 300 for result in results) == 1
    product, reservations = read_state(market.database_url, offered["product_id"])
    assert (product["status"], len(reservations)) in {("RESERVED", 1), ("OFFLINE", 0)}


def test_expiry_commits_independently_and_does_not_release_successor(market):
    offered = market.publish()
    base = datetime.now(UTC)
    now = base
    workflow = ProductWorkflow(market.database_url, clock=lambda: now)
    old_request = Command.model_validate(
        market.payload("reserve", offered, delivery=market.delivery(base))
    )
    old = workflow.execute(old_request, market.buyer.account).body["operation"]
    now = base + timedelta(hours=2)
    next_request = Command.model_validate(
        market.payload("reserve", old, delivery=market.delivery(now))
    )
    result = workflow.execute(next_request, market.other.account)
    assert result.status == 409
    product, reservations = read_state(market.database_url, offered["product_id"])
    assert product["status"] == "PUBLISHED" and reservations[0]["status"] == "EXPIRED"
    assert product["published_at"] == datetime.fromisoformat(
        market.product(offered["product_id"])["published_at"]
    )
    assert product["version"] == old["version"] + 1

    stale_accept = Command.model_validate(
        market.payload("accept", old, reservation_id=old["reservation_id"])
    )
    assert (
        workflow.execute(stale_accept, market.seller.account).body["detail"]["code"]
        == "reservation_expired"
    )
    next_request = Command.model_validate(
        market.payload(
            "reserve",
            {**old, "version": product["version"]},
            delivery=market.delivery(now),
        )
    )
    successor = workflow.execute(next_request, market.other.account).body["operation"]
    assert not workflow.expire_if_due(offered["product_id"], old["reservation_id"])
    replay = workflow.execute(old_request, market.buyer.account)
    assert (
        replay.body["replayed"]
        and replay.body["operation"]["reservation_id"] == old["reservation_id"]
    )
    assert replay.body["current"]["reservation_status"] == "EXPIRED"
    assert (
        market.request(
            "GET", f"/reservations/{successor['reservation_id']}", market.other
        ).json()["status"]
        == "PENDING"
    )


def test_exact_24_hour_boundary_and_confirmed_replay(market):
    offered = market.publish()
    base = datetime.now(UTC)
    now = base
    workflow = ProductWorkflow(market.database_url, clock=lambda: now)
    terms = {
        **market.delivery(base),
        "meeting_at": (base + timedelta(hours=48)).isoformat(),
    }
    command = Command.model_validate(market.payload("reserve", offered, delivery=terms))
    reserved = workflow.execute(command, market.buyer.account).body["operation"]
    accept = Command.model_validate(
        market.payload("accept", reserved, reservation_id=reserved["reservation_id"])
    )
    now = base + timedelta(hours=24, microseconds=-1)
    response = workflow.execute(accept, market.seller.account)
    assert response.status == 200
    now = base + timedelta(hours=24)
    assert not workflow.expire_if_due(offered["product_id"], reserved["reservation_id"])
    old = workflow.execute(accept, market.seller.account)
    assert (
        old.body["replayed"]
        and old.body["operation"]["reservation_status"] == "CONFIRMED"
    )


def test_background_worker_releases_pending_soon_after_deadline(market):
    offered = market.publish()
    now = datetime.now(UTC)
    workflow = ProductWorkflow(
        market.database_url, clock=lambda: now - timedelta(minutes=1)
    )
    terms = {
        **market.delivery(now),
        "meeting_at": (now + timedelta(seconds=1)).isoformat(),
    }
    command = Command.model_validate(market.payload("reserve", offered, delivery=terms))
    reserved = workflow.execute(command, market.buyer.account).body["operation"]
    with TestClient(market.app, base_url="https://testserver") as live:
        start = monotonic()
        while monotonic() - start < 15:
            response = live.get(
                f"/api/reservations/{reserved['reservation_id']}",
                headers=market.buyer.headers,
            )
            if response.json()["status"] == "EXPIRED":
                break
            sleep(0.2)
        else:
            pytest.fail(
                "the expiry worker did not release the reservation within 15 seconds"
            )
    assert market.product(offered["product_id"])["status"] == "PUBLISHED"


def test_statistics_beijing_endpoints_and_independent_counts(market):
    booked = market.reserve(market.publish())
    confirmed = market.command(
        market.seller, "accept", booked, reservation_id=booked["reservation_id"]
    )["operation"]
    completed = market.command(
        market.buyer,
        "complete",
        confirmed,
        reservation_id=booked["reservation_id"],
        received=True,
    )["operation"]
    market.publish()
    start = datetime.now(BEIJING).date()
    end = start + timedelta(days=1)
    boundary = datetime.combine(start, datetime.min.time(), BEIJING)
    with open_database(market.database_url) as connection:
        connection.execute(
            "UPDATE reservation SET completed_at = %s WHERE id = %s",
            (boundary, completed["reservation_id"]),
        )
    result = market.request(
        "GET", "/statistics", market.seller, params={"start": start, "end": end}
    ).json()
    assert (result["completed"], result["total_amount"]) == (1, "59.90")
    before = market.request(
        "GET",
        "/statistics",
        market.seller,
        params={"start": start - timedelta(days=1), "end": start},
    ).json()
    assert (before["completed"], before["total_amount"], before["counts"]) == (
        0,
        "0.00",
        result["counts"],
    )
