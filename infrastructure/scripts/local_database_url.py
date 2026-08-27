from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy.dialects.postgresql.asyncpg import dialect as asyncpg_dialect
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


LOOPBACK_TCP_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class LocalDatabaseUrlError(ValueError):
    pass


def _canonicalize_database_url(
    raw_url: str,
    *,
    expected_scheme: str,
    target_scheme: str,
    expected_port: int,
    expected_database: str,
) -> str:
    if not raw_url or raw_url != raw_url.strip():
        raise LocalDatabaseUrlError("local database URL is not canonical")
    if expected_port < 1 or expected_port > 65535:
        raise LocalDatabaseUrlError("expected local database port is invalid")
    if not expected_database or "/" in expected_database:
        raise LocalDatabaseUrlError("expected local database name is invalid")

    try:
        split = urlsplit(raw_url)
        split_hostname = split.hostname
        split_port = split.port
        parsed = make_url(raw_url)
    except (ArgumentError, TypeError, ValueError) as error:
        raise LocalDatabaseUrlError("local database URL is invalid") from error

    if split.scheme != expected_scheme or parsed.drivername != expected_scheme:
        raise LocalDatabaseUrlError("local database URL scheme is invalid")
    if split.query or split.fragment or parsed.query:
        raise LocalDatabaseUrlError("local database URL options are forbidden")
    if split.netloc.count("@") != 1:
        raise LocalDatabaseUrlError("local database URL authority is ambiguous")
    if split_hostname not in LOOPBACK_TCP_HOSTS:
        raise LocalDatabaseUrlError("local database URL must use loopback TCP")
    if split_port != expected_port:
        raise LocalDatabaseUrlError("local database URL port is unexpected")
    if split.path != f"/{expected_database}":
        raise LocalDatabaseUrlError("local database name is unexpected")

    effective = parsed.translate_connect_args()
    if effective.get("host") != split_hostname:
        raise LocalDatabaseUrlError("effective database host is ambiguous")
    if effective.get("port") != expected_port:
        raise LocalDatabaseUrlError("effective database port is unexpected")
    if effective.get("database") != expected_database:
        raise LocalDatabaseUrlError("effective database name is unexpected")
    username = effective.get("username")
    auth_value = effective.get("password")
    if not isinstance(username, str) or not username:
        raise LocalDatabaseUrlError("local database username is missing")
    if auth_value is not None and not isinstance(auth_value, str):
        raise LocalDatabaseUrlError("local database password is invalid")

    normalized = URL.create(
        target_scheme,
        username,
        auth_value,
        split_hostname,
        expected_port,
        expected_database,
    )
    positional, asyncpg_arguments = asyncpg_dialect().create_connect_args(  # type: ignore[no-untyped-call]
        normalized
    )
    if positional:
        raise LocalDatabaseUrlError("effective database target is positional")
    if asyncpg_arguments != {
        "host": split_hostname,
        "database": expected_database,
        "user": username,
        "password": auth_value,
        "port": expected_port,
    }:
        raise LocalDatabaseUrlError("effective asyncpg target is unexpected")
    return normalized.render_as_string(hide_password=False)


def normalize_status_database_url(
    raw_url: str,
    *,
    expected_port: int,
    expected_database: str,
) -> str:
    return _canonicalize_database_url(
        raw_url,
        expected_scheme="postgresql",
        target_scheme="postgresql+asyncpg",
        expected_port=expected_port,
        expected_database=expected_database,
    )


def validate_test_database_url(
    raw_url: str,
    *,
    expected_port: int,
    expected_database: str,
) -> str:
    return _canonicalize_database_url(
        raw_url,
        expected_scheme="postgresql+asyncpg",
        target_scheme="postgresql+asyncpg",
        expected_port=expected_port,
        expected_database=expected_database,
    )
