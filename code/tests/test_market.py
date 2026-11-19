from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from threading import Barrier

import pytest
from PIL import Image

from whale_market.db import open_database
from whale_market.domain import IMAGE_LIMIT


def content(**fields):
    return {
        "title": "书籍验收样品",
        "description": "保存完善，校园交付",
        "category": "书籍",
        "condition": "八成新",
        "price": "0.10",
        **fields,
    }


def test_full_purchase_preserves_history_favorites_and_audits(market):
    offered = market.publish(content())
    product_id = offered["product_id"]
    public = market.product(product_id)
    assert public["price"] == "0.10" and public["followers"] == 0
    assert "review" not in public
    for _ in range(2):
        assert (
            market.request("PUT", f"/favorites/{product_id}", market.buyer).status_code
            == 200
        )
    assert market.product(product_id)["followers"] == 1
    assert market.product(product_id, market.buyer)["is_favorite"]
    assert market.request("GET", "/favorites", market.other).json()["total"] == 0
    reserved = market.reserve(offered)
    booking_id = reserved["reservation_id"]
    entry = market.request("GET", "/favorites", market.buyer).json()["items"][0]
    assert entry == {"product_id": product_id, "product": None}
    assert (
        market.request("DELETE", f"/favorites/{product_id}", market.buyer).status_code
        == 200
    )
    assert market.request("GET", f"/products/{product_id}").status_code == 404

    detail_url = f"/reservations/{booking_id}"
    private = market.request("GET", detail_url, market.buyer).json()
    assert private["location"] == market.delivery()["location"]
    assert private["price"] == "0.10"
    assert market.request("GET", detail_url, market.other).status_code == 403
    admin_detail = market.request("GET", detail_url, market.admin).json()
    assert "location" not in admin_detail and "deadline" not in admin_detail
    assert market.request("POST", detail_url + "/delivery", market.admin).json()[
        "delivery_visible"
    ]

    confirmed = market.command(
        market.seller, "accept", reserved, reservation_id=booking_id
    )["operation"]
    done_payload = market.payload(
        "complete", confirmed, reservation_id=booking_id, received=True
    )
    original = market.request("POST", "/commands", market.buyer, json=done_payload)
    assert original.json()["operation"]["product_status"] == "SOLD"
    done_at = market.request("GET", detail_url, market.buyer).json()["completed_at"]
    replay = market.request("POST", "/commands", market.buyer, json=done_payload)
    assert (
        replay.json()["replayed"]
        and replay.json()["operation"] == original.json()["operation"]
    )
    assert (
        market.request("GET", detail_url, market.buyer).json()["completed_at"]
        == done_at
    )
    changed = market.request(
        "POST", "/commands", market.buyer, json={**done_payload, "received": False}
    )
    assert changed.json()["detail"]["code"] == "submission_conflict"

    marked = market.command(
        market.admin, "mark_violation", original.json()["operation"], reason="保留历史"
    )
    assert marked["operation"]["product_status"] == "SOLD"
    staff_product = market.product(product_id, market.admin)
    assert staff_product["violations"][0]["reason"] == "保留历史"
    now = datetime.now(UTC)
    params = {
        "start": (now - timedelta(days=1)).date(),
        "end": (now + timedelta(days=2)).date(),
    }
    stats = market.request("GET", "/statistics", market.seller, params=params).json()
    assert (stats["completed"], stats["total_amount"], stats["counts"]["SOLD"]) == (
        1,
        "0.10",
        1,
    )
    logs = market.request(
        "GET",
        "/audit",
        market.admin,
        params={"reservation_id": booking_id, "scope": "all", "product_id": product_id},
    ).json()["items"]
    assert (
        sum(row["action"] == "complete" and row["outcome"] == "SUCCESS" for row in logs)
        == 1
    )
    assert any(
        row["action"] == "read_delivery" and row["outcome"] == "ACCESS" for row in logs
    )


def test_draft_review_and_publication_timestamps(market):
    initial = market.command(market.seller, "draft", content={})["operation"]
    market.command(market.seller, "submit", initial, status=422)
    edited = market.command(market.seller, "edit", initial, content=content())[
        "operation"
    ]
    pending = market.command(market.seller, "submit", edited)["operation"]
    market.command(market.seller, "edit", pending, content=content(), status=409)
    withdrawn = market.command(
        market.seller, "withdraw", pending, review_id=pending["review_id"]
    )["operation"]
    new_review = market.command(market.seller, "submit", withdrawn)["operation"]
    market.command(
        market.admin, "approve", new_review, review_id=pending["review_id"], status=409
    )
    rejected = market.command(
        market.admin,
        "reject_review",
        new_review,
        review_id=new_review["review_id"],
        reason="补充使用情况",
    )["operation"]
    assert (
        market.product(initial["product_id"], market.seller)["review"]["reason"]
        == "补充使用情况"
    )
    resubmitted = market.command(market.seller, "submit", rejected)["operation"]
    approved = market.command(
        market.admin, "approve", resubmitted, review_id=resubmitted["review_id"]
    )["operation"]
    original_stamp = market.product(initial["product_id"])["published_at"]
    off = market.command(market.seller, "offline", approved)["operation"]
    unchanged = market.command(market.seller, "submit", off)["operation"]
    republished = market.command(
        market.admin, "approve", unchanged, review_id=unchanged["review_id"]
    )["operation"]
    assert original_stamp == market.product(initial["product_id"])["published_at"]
    off_again = market.command(market.seller, "offline", republished)["operation"]
    edited = market.command(
        market.seller, "edit", off_again, content=content(price="0.20")
    )["operation"]
    revised = market.command(market.seller, "submit", edited)["operation"]
    market.command(market.admin, "approve", revised, review_id=revised["review_id"])
    assert original_stamp < market.product(initial["product_id"])["published_at"]
    assert market.product(initial["product_id"])["price"] == "0.20"


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"title": "字" * 60, "description": "字" * 2000, "price": "100000.00"}, 201),
        ({"title": "字" * 61}, 422),
        ({"description": "字" * 2001}, 422),
        ({"price": "0"}, 422),
        ({"price": "0.01"}, 201),
        ({"price": "100000.01"}, 422),
        ({"price": "1.001"}, 422),
        ({"category": "越界分类"}, 422),
        ({"condition": "未知成色"}, 422),
    ],
)
def test_draft_constraints(market, fields, expected):
    market.command(market.seller, "draft", content=content(**fields), status=expected)


def test_images_are_validated_and_scoped(market):
    stream = BytesIO()
    Image.new("RGB", (8, 8), "navy").save(stream, format="PNG")
    sample = stream.getvalue()
    image_ids = []
    for _ in range(5):
        response = market.request(
            "POST",
            "/images",
            market.seller,
            content=sample,
            headers={"Content-Type": "image/png"},
        )
        assert response.status_code == 201
        image_ids.append(response.json()["id"])
    hidden_image = f"/images/{image_ids[0]}"
    assert market.request("GET", hidden_image).status_code == 404
    assert market.request("GET", hidden_image, market.seller).content == sample
    assert (
        market.request(
            "POST",
            "/images",
            market.seller,
            content=sample,
            headers={"Content-Type": "image/jpeg"},
        ).status_code
        == 422
    )
    assert (
        market.request(
            "POST",
            "/images",
            market.seller,
            content=b"x" * (IMAGE_LIMIT + 1),
            headers={"Content-Type": "image/png"},
        ).status_code
        == 413
    )
    market.command(
        market.other, "draft", content=content(image_ids=image_ids[:1]), status=422
    )
    market.command(
        market.seller,
        "draft",
        content=content(image_ids=image_ids + image_ids[:1]),
        status=422,
    )
    market.publish(content(image_ids=image_ids))
    assert market.request("GET", hidden_image).content == sample


def test_public_combination_filters_and_stable_pagination(market):
    with open_database(market.database_url) as connection:
        connection.execute(
            """
            INSERT INTO product (seller_id, title, description, category, condition, price, status,
                created_at, published_at, approved_digest)
            SELECT %s, '光盘 ' || i, '图一 独有词', '书籍', '八成新', 10.00, 'PUBLISHED',
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'fixture' FROM generate_series(1, 21) i
            """,
            (market.seller.account.id,),
        )
    market.publish(content(title="描述匹配", description="独有词", price="9.99"))
    market.publish(content(title="独有词 标题匹配", category="电子产品", price="10"))
    params = {"q": "独有词", "category": "书籍", "minimum": "10.00", "maximum": "10"}
    first = market.request("GET", "/products", params=params).json()
    second = market.request("GET", "/products", params={**params, "page": 2}).json()
    assert (first["total"], len(first["items"]), len(second["items"])) == (21, 20, 1)
    ids = [row["id"] for row in first["items"] + second["items"]]
    assert ids == sorted(set(ids))
    assert (
        market.request("GET", "/products", params={**params, "q": "%"}).json()["total"]
        == 0
    )
    assert (
        market.request("GET", "/products", params={**params, "minimum": "15"}).json()[
            "detail"
        ]["code"]
        == "invalid_price"
    )


def test_conflicts_and_permissions_include_stale_reservation_accounts(market):
    hidden = market.command(market.seller, "draft", content=content())["operation"]
    start = market.publish(content())
    before = market.reserve(start)
    booking = before["reservation_id"]
    after_cancel = market.command(
        market.buyer, "cancel", before, reservation_id=booking
    )["operation"]
    later = market.reserve(after_cancel, market.other)
    later_id = later["reservation_id"]
    confirmed = market.command(market.seller, "accept", later, reservation_id=later_id)[
        "operation"
    ]
    cases = [
        (
            "POST",
            "/commands",
            None,
            market.payload("reserve", start, delivery=market.delivery()),
            401,
        ),
        ("POST", "/commands", None, market.payload("draft", content={}), 401),
        (
            "POST",
            "/commands",
            None,
            market.payload("approve", hidden, review_id=1),
            401,
        ),
        (
            "PUT",
            f"/admin/accounts/{market.buyer.account.id}/role",
            market.buyer,
            {"is_admin": True},
            403,
        ),
        (
            "POST",
            "/commands",
            market.buyer,
            market.payload("edit", hidden, content=content()),
            403,
        ),
        (
            "POST",
            "/commands",
            market.buyer,
            market.payload("cancel", confirmed, reservation_id=later_id, reason="无关"),
            403,
        ),
        (
            "POST",
            "/commands",
            market.seller,
            market.payload(
                "complete", confirmed, reservation_id=later_id, received=True
            ),
            403,
        ),
        (
            "POST",
            "/commands",
            market.admin,
            market.payload(
                "complete", confirmed, reservation_id=later_id, received=True
            ),
            403,
        ),
        ("GET", f"/reservations/{later_id}", market.buyer, None, 403),
        ("GET", f"/audit?reservation_id={later_id}", market.buyer, None, 403),
        ("GET", "/products?state=DRAFT", None, None, 403),
        ("GET", f"/products/{hidden['product_id']}", market.other, None, 404),
        ("POST", f"/reservations/{later_id}/delivery", market.buyer, None, 403),
        ("GET", "/products?scope=all", market.other, None, 403),
    ]
    for method, path, actor, data, status in cases:
        response = market.request(
            method, path, actor, **({"json": data} if data is not None else {})
        )
        assert response.status_code == status, (method, path, response.text)
    assert market.request("GET", "/products").status_code == 200
    assert (
        market.request("GET", f"/reservations/{booking}", market.buyer).json()["status"]
        == "CANCELLED"
    )
    assert (
        market.request("GET", f"/reservations/{later_id}", market.other).json()[
            "status"
        ]
        == "CONFIRMED"
    )
    assert all(
        row["reservation_id"] != later_id
        for row in market.request(
            "GET",
            f"/audit?product_id={start['product_id']}",
            market.buyer,
        ).json()["items"]
    )


def test_platform_cancels_trade_without_republishing(market):
    product = market.publish(content())
    reserved = market.reserve(product)
    banned = market.command(market.admin, "ban", reserved, reason="平台违规处置")[
        "operation"
    ]
    assert (
        banned["product_status"] == "BANNED"
        and banned["reservation_status"] == "CANCELLED"
    )
    for actor in (market.seller, market.buyer):
        booking = market.request(
            "GET", f"/reservations/{reserved['reservation_id']}", actor
        ).json()
        assert booking["platform_cancelled"] and booking["reason"] == "平台违规处置"
    market.command(
        market.buyer, "reserve", banned, delivery=market.delivery(), status=409
    )


def test_concurrent_admin_revocations_protect_last_administrator(market):
    other_id = market.other.account.id
    admin_id = market.admin.account.id
    promoted = market.request(
        "PUT", f"/admin/accounts/{other_id}/role", market.admin, json={"is_admin": True}
    )
    assert promoted.json()["is_admin"]
    start = Barrier(2)

    def revoke(pair):
        actor, target = pair
        start.wait(timeout=10)
        response = market.request(
            "PUT", f"/admin/accounts/{target}/role", actor, json={"is_admin": False}
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(
            pool.map(revoke, [(market.admin, admin_id), (market.other, other_id)])
        )
    assert statuses == [200, 409]
    with open_database(market.database_url) as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM account WHERE is_admin"
            ).fetchone()["n"]
            == 1
        )


@pytest.mark.parametrize("canceller", ["buyer", "seller"])
def test_confirmed_cancellation_and_repricing_keep_old_delivery(market, canceller):
    offered = market.publish(content(price="0.10"))
    original = market.reserve(offered)
    reservation_id = original["reservation_id"]
    endpoint = f"/reservations/{reservation_id}"
    before = market.request("GET", endpoint, market.buyer).json()
    accepted = market.command(
        market.seller, "accept", original, reservation_id=reservation_id
    )["operation"]
    actor = getattr(market, canceller)
    market.command(actor, "cancel", accepted, reservation_id=reservation_id, status=422)
    cancelled = market.command(
        actor,
        "cancel",
        accepted,
        reservation_id=reservation_id,
        reason="交付时间不合适",
    )["operation"]
    off = market.command(market.seller, "offline", cancelled)["operation"]
    changed = market.command(market.seller, "edit", off, content=content(price="0.20"))[
        "operation"
    ]
    pending = market.command(market.seller, "submit", changed)["operation"]
    revived = market.command(
        market.admin, "approve", pending, review_id=pending["review_id"]
    )["operation"]
    next_reservation = market.reserve(revived, market.other)
    after = market.request("GET", endpoint, market.buyer).json()
    assert after["status"] == "CANCELLED"
    assert (after["price"], after["location"], after["meeting_at"]) == (
        before["price"],
        before["location"],
        before["meeting_at"],
    )
    assert (
        market.request(
            "GET",
            f"/reservations/{next_reservation['reservation_id']}",
            market.other,
        ).json()["price"]
        == "0.20"
    )


def test_pending_reservation_rejection_keeps_release_publication(market):
    offered = market.publish(content())
    published_at = market.product(offered["product_id"])["published_at"]
    reserved = market.reserve(offered)
    reservation_id = reserved["reservation_id"]
    market.command(
        market.seller,
        "cancel",
        reserved,
        reservation_id=reservation_id,
        reason="尝试取消",
        status=409,
    )
    market.command(
        market.seller,
        "reject_reservation",
        reserved,
        reservation_id=reservation_id,
        status=422,
    )
    result = market.command(
        market.seller,
        "reject_reservation",
        reserved,
        reservation_id=reservation_id,
        reason="时间不便",
    )["operation"]
    assert (result["product_status"], result["reservation_status"]) == (
        "PUBLISHED",
        "REJECTED",
    )
    assert market.product(offered["product_id"])["published_at"] == published_at
