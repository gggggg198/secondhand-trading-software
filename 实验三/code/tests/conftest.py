from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from os import environ
from secrets import token_urlsafe
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from whale_market.accounts import Account, token_digest
from whale_market.api import SESSION_COOKIE, create_app
from whale_market.config import Settings
from whale_market.db import apply_migrations, open_database

DEFAULT_CONTENT = {
    "title": "二手机械键盘",
    "description": "教学楼见面，功能正常。",
    "category": "电子产品",
    "condition": "九成新",
    "price": "59.90",
}


@pytest.fixture
def empty_database_url():
    database_url = environ.get("WHALE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("需要设置 WHALE_TEST_DATABASE_URL")
    schema = f"test_whale_{uuid4().hex}"
    with open_database(database_url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield make_conninfo(database_url, options=f"-c search_path={schema}")
    finally:
        with open_database(database_url) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@pytest.fixture
def database_url(empty_database_url):
    apply_migrations(empty_database_url)
    return empty_database_url


@dataclass(frozen=True)
class Actor:
    account: Account
    token: str

    @property
    def headers(self):
        return {"Cookie": f"{SESSION_COOKIE}={self.token}"}


class Market:
    def __init__(self, database_url):
        self.database_url = database_url
        self.app = create_app(Settings(database_url))
        self.client = TestClient(self.app, base_url="https://testserver")
        self.seller = self.user("Seller")
        self.buyer = self.user("Buyer")
        self.other = self.user("OtherBuyer")
        self.admin = self.user("Admin", admin=True)

    def user(self, username, admin=False):
        token = token_urlsafe(32)
        with open_database(self.database_url) as conn:
            account = conn.execute(
                """
                INSERT INTO account (username, password_hash, is_admin)
                VALUES (%s, 'unused-fixture', %s) RETURNING id, username, is_admin
                """,
                (username, admin),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO account_session(token_digest, account_id, expires_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL '1 day')
                """,
                (token_digest(token), account["id"]),
            )
        return Actor(Account(**account), token)

    def request(self, method, path, actor=None, **kwargs):
        headers = kwargs.pop("headers", {})
        if actor is not None:
            headers.update(actor.headers)
        return self.client.request(method, "/api" + path, headers=headers, **kwargs)

    def payload(self, action, state=None, **fields):
        body = {"action": action, "submission_key": str(uuid4())}
        if state is not None:
            body.update(product_id=state["product_id"], version=state["version"])
        body.update(fields)
        return body

    def command(self, actor, action, state=None, status=None, **fields):
        response = self.request(
            "POST", "/commands", actor, json=self.payload(action, state, **fields)
        )
        expected = (
            status
            if status is not None
            else (201 if action in ("draft", "reserve") else 200)
        )
        assert response.status_code == expected, response.text
        return response.json()

    def publish(self, content=None):
        draft = self.command(
            self.seller,
            "draft",
            content=dict(DEFAULT_CONTENT) if content is None else content,
        )["operation"]
        review = self.command(self.seller, "submit", draft)["operation"]
        result = self.command(
            self.admin, "approve", review, review_id=review["review_id"]
        )
        return result["operation"]

    @staticmethod
    def delivery(base=None):
        return {
            "location": "鼓楼校区图书馆门口",
            "meeting_at": (
                (base or datetime.now(UTC)) + timedelta(hours=2)
            ).isoformat(),
        }

    def reserve(self, published, actor=None):
        return self.command(
            actor or self.buyer, "reserve", published, delivery=self.delivery()
        )["operation"]

    def product(self, product_id, actor=None):
        response = self.request("GET", f"/products/{product_id}", actor)
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture
def market(database_url):
    market = Market(database_url)
    try:
        yield market
    finally:
        market.client.close()
