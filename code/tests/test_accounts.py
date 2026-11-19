from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from os import environ
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from whale_market.accounts import Accounts, AdminAlreadyInitialized, Credentials
from whale_market.api import SESSION_COOKIE, create_app
from whale_market.config import Settings
from whale_market.db import apply_migrations, open_database

TEST_CREDENTIALS = {"username": "Stage3Buyer", "password": "TestPasswordOnly2026"}


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


def test_validation_response_omits_submitted_password():
    app = create_app(Settings("dbname=unused"))
    password = TEST_CREDENTIALS["password"] * 5
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register", json={"username": "Stage3Buyer", "password": password}
        )
        assert response.status_code == 422
        assert password not in response.text
        response = client.post(
            "/api/auth/register", json={**TEST_CREDENTIALS, "is_admin": True}
        )
        assert response.status_code == 422
        assert TEST_CREDENTIALS["password"] not in response.text


def test_migrations_are_repeatable(empty_database_url):
    app = create_app(Settings(empty_database_url))
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 503
        assert apply_migrations(empty_database_url) == ["001_accounts.sql"]
        assert apply_migrations(empty_database_url) == []
        assert client.get("/api/health").json() == {"status": "ok"}


def test_login_and_logout_persist_without_plaintext(database_url):
    app = create_app(Settings(database_url))
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/auth/me").status_code == 401
        registered = client.post("/api/auth/register", json=TEST_CREDENTIALS)
        assert registered.status_code == 201
        assert registered.json()["is_admin"] is False
        assert TEST_CREDENTIALS["password"] not in registered.text

        credentials = {
            **TEST_CREDENTIALS,
            "username": TEST_CREDENTIALS["username"].swapcase(),
        }
        wrong = client.post(
            "/api/auth/login", json={**credentials, "password": "WrongPassword"}
        )
        assert wrong.status_code == 401
        assert SESSION_COOKIE not in wrong.cookies

        signed_in = client.post("/api/auth/login", json=credentials)
        assert signed_in.status_code == 200
        assert signed_in.json() == registered.json()
        cookie = signed_in.headers["set-cookie"]
        assert (
            "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        )
        token = client.cookies[SESSION_COOKIE]
        assert token not in signed_in.text
        assert client.get("/api/auth/me").json() == registered.json()

        with open_database(database_url) as connection:
            row = connection.execute("""
                SELECT a.password_hash, s.token_digest
                FROM account a JOIN account_session s ON a.id = s.account_id
            """).fetchone()
        assert row["password_hash"].startswith("$argon2id$")
        assert row["token_digest"] == sha256(token.encode()).digest()

        assert client.post("/api/auth/logout").status_code == 204
        assert (
            client.get(
                "/api/auth/me", headers={"Cookie": f"{SESSION_COOKIE}={token}"}
            ).status_code
            == 401
        )


def test_expired_session_cannot_identify_account(database_url):
    app = create_app(Settings(database_url))
    with TestClient(app, base_url="https://testserver") as client:
        assert (
            client.post("/api/auth/register", json=TEST_CREDENTIALS).status_code == 201
        )
        assert client.post("/api/auth/login", json=TEST_CREDENTIALS).status_code == 200
        with open_database(database_url) as connection:
            connection.execute("""
                UPDATE account_session
                SET issued_at = CURRENT_TIMESTAMP - INTERVAL '2 minutes',
                    expires_at = CURRENT_TIMESTAMP - INTERVAL '1 minute'
            """)
        assert client.get("/api/auth/me").status_code == 401


def test_concurrent_registration_accepts_only_one_case_variant(database_url):
    app = create_app(Settings(database_url))
    start = Barrier(2, timeout=10)

    def register(username: str) -> int:
        with TestClient(app) as client:
            start.wait()
            response = client.post(
                "/api/auth/register", json={**TEST_CREDENTIALS, "username": username}
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(register, ["WhaleBuyer", "whalebuyer"]))
    assert sorted(statuses) == [201, 409]


def test_first_admin_initialization_is_one_time(database_url):
    accounts = Accounts(database_url)
    credentials = Credentials(**{**TEST_CREDENTIALS, "username": "WhaleAdmin"})
    admin = accounts.initialize_admin(credentials)
    assert admin.is_admin
    with pytest.raises(AdminAlreadyInitialized):
        accounts.initialize_admin(
            Credentials(**{**TEST_CREDENTIALS, "username": "AnotherAdmin"})
        )
