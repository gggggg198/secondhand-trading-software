from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files

from psycopg import Connection, connect
from psycopg.rows import DictRow, dict_row

# The two-integer lock namespace is distinct from the workflow's bigint keys.
LOCK_NAMESPACE = 230_311
MIGRATION_LOCK = 1
ADMIN_PERMISSION_LOCK = 2


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    name: str
    sql: str
    checksum: str


def open_database(database_url: str) -> Connection[DictRow]:
    return connect(database_url, row_factory=dict_row, connect_timeout=5)


def lock_transaction(connection: Connection[DictRow], scope: int) -> None:
    connection.execute("SELECT pg_advisory_xact_lock(%s, %s)", (LOCK_NAMESPACE, scope))


def apply_migrations(database_url: str) -> list[str]:
    migrations = []
    directory = files("whale_market").joinpath("migrations")
    for source in sorted(directory.iterdir(), key=lambda item: item.name):
        if source.is_file() and source.name.endswith(".sql"):
            sql = source.read_text(encoding="utf-8")
            migrations.append(
                Migration(source.name, sql, sha256(sql.encode()).hexdigest())
            )
    if not migrations:
        raise MigrationError("找不到数据库迁移文件。")

    with open_database(database_url) as connection:
        lock_transaction(connection, MIGRATION_LOCK)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS schema_migration (
                name TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        records = connection.execute(
            'SELECT name, checksum FROM schema_migration ORDER BY name COLLATE "C"'
        ).fetchall()
        expected = [
            {"name": migration.name, "checksum": migration.checksum}
            for migration in migrations[: len(records)]
        ]
        if records != expected:
            raise MigrationError("数据库迁移历史与当前发行版不匹配。")

        pending = migrations[len(records) :]
        for migration in pending:
            connection.execute(migration.sql, prepare=False)
            connection.execute(
                "INSERT INTO schema_migration (name, checksum) VALUES (%s, %s)",
                (migration.name, migration.checksum),
            )

    return [migration.name for migration in pending]
