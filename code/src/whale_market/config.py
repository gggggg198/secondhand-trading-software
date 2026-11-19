from dataclasses import dataclass, field
from os import environ
from typing import Self

from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    secure_cookie: bool = True

    @classmethod
    def from_environment(cls) -> Self:
        database_url = environ.get("WHALE_DATABASE_URL", "").strip()
        if not database_url:
            raise ConfigError("请配置 WHALE_DATABASE_URL。")
        try:
            conninfo_to_dict(database_url)
        except ProgrammingError:
            raise ConfigError("WHALE_DATABASE_URL 格式无效。") from None
        return cls(database_url)
