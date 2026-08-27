import re
from collections.abc import Iterable
from ipaddress import ip_address
from typing import Annotated, Literal
from urllib.parse import SplitResult, urlsplit

from pydantic import Field, SecretStr, ValidationError, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


Environment = Literal["development", "test", "staging", "production"]
LogLevel = Literal["debug", "info", "warning", "error", "critical"]
NonEmptySecret = Annotated[SecretStr, Field(min_length=1)]
NonEmptyString = Annotated[str, Field(min_length=1)]
_HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")

REQUIRED_ENVIRONMENT_VARIABLES = (
    "ENVIRONMENT",
    "LOG_LEVEL",
    "DATABASE_URL",
    "REDIS_URL",
    "SUPABASE_URL",
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_JWT_ISSUER",
    "SUPABASE_JWT_AUDIENCE",
    "APP_MASTER_KEY",
    "META_APP_SECRET",
    "META_WEBHOOK_VERIFY_TOKEN",
)


class Settings(BaseSettings):
    """Validated configuration shared by the API and worker processes."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=None,
        extra="ignore",
    )

    environment: Environment
    log_level: LogLevel
    database_url: NonEmptySecret
    redis_url: NonEmptySecret
    supabase_url: NonEmptyString
    supabase_publishable_key: NonEmptySecret
    supabase_jwt_issuer: NonEmptyString
    supabase_jwt_audience: NonEmptyString
    app_master_key: NonEmptySecret
    meta_app_secret: NonEmptySecret
    meta_webhook_verify_token: NonEmptySecret

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        parsed = _split_url(value.get_secret_value())
        if (
            parsed.scheme != "postgresql+asyncpg"
            or not _has_valid_host_and_port(parsed)
            or parsed.path in {"", "/"}
        ):
            raise ValueError("must be a postgresql+asyncpg database URL")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        parsed = _split_url(value.get_secret_value())
        if parsed.scheme not in {"redis", "rediss"} or not _has_valid_host_and_port(
            parsed
        ):
            raise ValueError("must be a Redis URL")
        return value

    @field_validator("supabase_url", "supabase_jwt_issuer")
    @classmethod
    def validate_supabase_https_url(cls, value: str, info: ValidationInfo) -> str:
        parsed = _split_url(value)
        has_valid_endpoint = _has_valid_host_and_port(parsed)
        is_https = parsed.scheme == "https" and has_valid_endpoint
        is_local_environment = info.data.get("environment") in {
            "development",
            "test",
        }
        is_local_http = (
            parsed.scheme == "http"
            and parsed.hostname
            in {
                "127.0.0.1",
                "::1",
                "localhost",
            }
            and has_valid_endpoint
            and is_local_environment
        )
        if not (is_https or is_local_http):
            raise ValueError("must use HTTPS except for a loopback development URL")
        return value


def _split_url(value: str) -> SplitResult:
    if any(character.isspace() for character in value):
        return SplitResult("", "", "", "", "")
    try:
        parsed = urlsplit(value)
        parsed.port
        return parsed
    except ValueError:
        return SplitResult("", "", "", "", "")


def _has_valid_host_and_port(parsed: SplitResult) -> bool:
    hostname = parsed.hostname
    if hostname is None or _has_explicit_empty_port(parsed):
        return False

    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        return False

    try:
        ip_address(hostname)
        return True
    except ValueError:
        pass

    try:
        ascii_hostname = hostname.encode("idna").decode("ascii").rstrip(".")
    except UnicodeError:
        return False
    if not ascii_hostname or len(ascii_hostname) > 253:
        return False
    return all(_HOST_LABEL.fullmatch(label) for label in ascii_hostname.split("."))


def _has_explicit_empty_port(parsed: SplitResult) -> bool:
    authority = parsed.netloc.rsplit("@", maxsplit=1)[-1]
    if authority.startswith("["):
        closing_bracket = authority.find("]")
        return closing_bracket >= 0 and authority[closing_bracket + 1 :] == ":"
    return authority.endswith(":")


def _in_contract_order(names: Iterable[str]) -> tuple[str, ...]:
    present = set(names)
    return tuple(name for name in REQUIRED_ENVIRONMENT_VARIABLES if name in present)


class ConfigurationError(RuntimeError):
    """Sanitized configuration failure containing field names, never values."""

    def __init__(
        self,
        *,
        missing_variables: Iterable[str] = (),
        invalid_variables: Iterable[str] = (),
    ) -> None:
        self.missing_variables = _in_contract_order(missing_variables)
        self.invalid_variables = _in_contract_order(invalid_variables)

        categories: list[str] = []
        if self.missing_variables:
            categories.append(f"missing: {', '.join(self.missing_variables)}")
        if self.invalid_variables:
            categories.append(f"invalid: {', '.join(self.invalid_variables)}")
        super().__init__(f"Invalid application configuration ({'; '.join(categories)})")


def load_settings() -> Settings:
    """Load process configuration while redacting rejected inputs."""

    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as error:
        missing: list[str] = []
        invalid: list[str] = []
        for issue in error.errors(include_input=False, include_url=False):
            variable = str(issue["loc"][0]).upper()
            if issue["type"] == "missing":
                missing.append(variable)
            else:
                invalid.append(variable)
        raise ConfigurationError(
            missing_variables=missing,
            invalid_variables=invalid,
        ) from None
