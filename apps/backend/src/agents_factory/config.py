from collections.abc import Iterable
from typing import Annotated, Literal
from urllib.parse import SplitResult, urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


Environment = Literal["development", "test", "staging", "production"]
LogLevel = Literal["debug", "info", "warning", "error", "critical"]
NonEmptySecret = Annotated[SecretStr, Field(min_length=1)]
NonEmptyString = Annotated[str, Field(min_length=1)]

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

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        parsed = _split_url(value.get_secret_value())
        if (
            parsed.scheme != "postgresql+asyncpg"
            or parsed.hostname is None
            or parsed.path in {"", "/"}
        ):
            raise ValueError("must be a postgresql+asyncpg database URL")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        parsed = _split_url(value.get_secret_value())
        if parsed.scheme not in {"redis", "rediss"} or parsed.hostname is None:
            raise ValueError("must be a Redis URL")
        return value

    @field_validator("supabase_url", "supabase_jwt_issuer")
    @classmethod
    def validate_supabase_https_url(cls, value: str) -> str:
        parsed = _split_url(value)
        is_https = parsed.scheme == "https" and parsed.hostname is not None
        is_local_http = parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "::1",
            "localhost",
        }
        if not (is_https or is_local_http):
            raise ValueError("must use HTTPS except for a loopback development URL")
        return value


def _split_url(value: str) -> SplitResult:
    try:
        parsed = urlsplit(value)
        parsed.port
        return parsed
    except ValueError:
        return SplitResult("", "", "", "", "")


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
