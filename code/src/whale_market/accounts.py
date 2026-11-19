from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from psycopg import Connection
from psycopg.rows import DictRow
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .db import ADMIN_PERMISSION_LOCK, lock_transaction, open_database

SESSION_AGE = timedelta(hours=12)


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Annotated[str, Field(pattern=r"^[A-Za-z0-9_]{4,20}$")]
    password: Annotated[SecretStr, Field(min_length=10, max_length=64)]


@dataclass(frozen=True)
class Account:
    id: int
    username: str
    is_admin: bool


class UsernameTaken(Exception):
    pass


class AdminAlreadyInitialized(Exception):
    pass


class Accounts:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._passwords = PasswordHasher()
        # Absent usernames take the same password verification path as existing ones.
        self._unknown_password_hash = self._passwords.hash(token_urlsafe(32))

    def register(self, credentials: Credentials) -> Account:
        password_hash = self._passwords.hash(credentials.password.get_secret_value())
        with open_database(self._database_url) as connection:
            return insert_account(
                connection, credentials.username, password_hash, is_admin=False
            )

    def initialize_admin(self, credentials: Credentials) -> Account:
        password_hash = self._passwords.hash(credentials.password.get_secret_value())
        with open_database(self._database_url) as connection:
            lock_transaction(connection, ADMIN_PERMISSION_LOCK)
            if connection.execute(
                "SELECT 1 FROM account WHERE is_admin LIMIT 1"
            ).fetchone():
                raise AdminAlreadyInitialized("首名管理员已初始化。")
            return insert_account(
                connection, credentials.username, password_hash, is_admin=True
            )

    def login(
        self, credentials: Credentials, old_token: str | None
    ) -> tuple[Account, str] | None:
        password = credentials.password.get_secret_value()
        with open_database(self._database_url) as connection:
            row = connection.execute(
                "SELECT id, username, is_admin, password_hash FROM account WHERE username_key = %s",
                (credentials.username.lower(),),
            ).fetchone()
            password_hash = row["password_hash"] if row else self._unknown_password_hash
            try:
                self._passwords.verify(password_hash, password)
            except VerifyMismatchError:
                return None
            if row is None:
                return None

            token = token_urlsafe(32)
            if old_token:
                delete_session(connection, old_token)
            connection.execute(
                """
                INSERT INTO account_session (token_digest, account_id, expires_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP + %s)
                """,
                (token_digest(token), row["id"], SESSION_AGE),
            )
            return account_from_row(row), token

    def current(self, token: str | None) -> Account | None:
        if not token:
            return None
        with open_database(self._database_url) as connection:
            row = connection.execute(
                """
                SELECT a.id, a.username, a.is_admin
                FROM account_session AS s JOIN account AS a ON a.id = s.account_id
                WHERE s.token_digest = %s AND s.expires_at > CURRENT_TIMESTAMP
                """,
                (token_digest(token),),
            ).fetchone()
        return account_from_row(row) if row else None

    def logout(self, token: str | None) -> None:
        if token:
            with open_database(self._database_url) as connection:
                delete_session(connection, token)


def insert_account(
    connection: Connection[DictRow],
    username: str,
    password_hash: str,
    *,
    is_admin: bool,
) -> Account:
    row = connection.execute(
        """
        INSERT INTO account (username, password_hash, is_admin) VALUES (%s, %s, %s)
        ON CONFLICT (username_key) DO NOTHING
        RETURNING id, username, is_admin
        """,
        (username, password_hash, is_admin),
    ).fetchone()
    if row is None:
        raise UsernameTaken("此用户名已注册。")
    return account_from_row(row)


def account_from_row(row: DictRow) -> Account:
    return Account(id=row["id"], username=row["username"], is_admin=row["is_admin"])


def token_digest(token: str) -> bytes:
    return sha256(token.encode("utf-8")).digest()


def delete_session(connection: Connection[DictRow], token: str) -> None:
    connection.execute(
        "DELETE FROM account_session WHERE token_digest = %s", (token_digest(token),)
    )
