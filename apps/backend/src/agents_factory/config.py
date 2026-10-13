import re
from collections.abc import Iterable
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Annotated, Literal
from urllib.parse import SplitResult, urlsplit
from uuid import UUID

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
_CONFIGURATION_VARIABLE_ORDER = REQUIRED_ENVIRONMENT_VARIABLES + (
    "META_APP_ID",
    "META_CONFIGURATION_ID",
    "META_REDIRECT_URI",
    "META_GRAPH_API_BASE_URL",
    "META_REVIEW_TENANT_ID",
    "META_REVIEW_ACCOUNT_ID",
    "META_REVIEW_WABA_ID",
    "META_REVIEW_PHONE_NUMBER_ID",
    "META_REVIEW_RECIPIENT",
    "COEXISTENCE_PILOT_TENANT_ID",
    "COEXISTENCE_PILOT_PHONE_DIGITS",
)


@dataclass(frozen=True)
class ReviewBinding:
    tenant_id: UUID
    account_id: UUID
    waba_id: str
    phone_number_id: str
    recipient: str


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
    agent_publication_code_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    meta_app_id: NonEmptyString | None = None
    meta_configuration_id: NonEmptyString | None = None
    meta_redirect_uri: NonEmptyString | None = None
    meta_graph_api_base_url: NonEmptyString = "https://graph.facebook.com/v25.0"
    meta_review_tenant_id: UUID | None = None
    meta_review_account_id: UUID | None = None
    meta_review_waba_id: Annotated[str, Field(pattern=r"^[0-9]{1,64}$")] | None = None
    meta_review_phone_number_id: (
        Annotated[str, Field(pattern=r"^[0-9]{1,64}$")] | None
    ) = None
    meta_review_recipient: (
        Annotated[str, Field(pattern=r"^[1-9][0-9]{7,14}$")] | None
    ) = None
    coexistence_pilot_tenant_id: UUID | None = None
    coexistence_pilot_phone_digits: (
        Annotated[str, Field(pattern=r"^[1-9][0-9]{7,14}$")] | None
    ) = None

    def coexistence_pilot_enabled_for(self, tenant_id: UUID | None) -> bool:
        return (
            self.coexistence_pilot_tenant_id is not None
            and self.coexistence_pilot_phone_digits is not None
            and tenant_id == self.coexistence_pilot_tenant_id
        )

    @property
    def review_binding(self) -> ReviewBinding | None:
        tenant = self.meta_review_tenant_id
        account = self.meta_review_account_id
        waba = self.meta_review_waba_id
        phone = self.meta_review_phone_number_id
        recipient = self.meta_review_recipient
        if (
            tenant is None
            or account is None
            or waba is None
            or phone is None
            or recipient is None
        ):
            return None
        return ReviewBinding(tenant, account, waba, phone, recipient)

    @field_validator(
        "meta_app_id",
        "meta_configuration_id",
        "meta_redirect_uri",
        "meta_review_tenant_id",
        "meta_review_account_id",
        "meta_review_waba_id",
        "meta_review_phone_number_id",
        "meta_review_recipient",
        "coexistence_pilot_tenant_id",
        "coexistence_pilot_phone_digits",
        mode="before",
    )
    @classmethod
    def normalize_optional_meta_configuration(cls, value: object) -> object:
        return None if value == "" else value

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

    @field_validator("meta_redirect_uri", "meta_graph_api_base_url")
    @classmethod
    def validate_meta_https_url(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        if value is None:
            return None
        parsed = _split_url(value)
        has_valid_endpoint = _has_valid_host_and_port(parsed)
        if parsed.scheme == "https" and has_valid_endpoint:
            return value.rstrip("/")
        is_local = info.data.get("environment") in {"development", "test"}
        if (
            is_local
            and parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
            and has_valid_endpoint
        ):
            return value.rstrip("/")
        raise ValueError("must use HTTPS except for a loopback development URL")


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
    return tuple(name for name in _CONFIGURATION_VARIABLE_ORDER if name in present)


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
            categories.append(
                f"missing: {', '.join(_safe_variable_name(item) for item in self.missing_variables)}"
            )
        if self.invalid_variables:
            categories.append(
                f"invalid: {', '.join(_safe_variable_name(item) for item in self.invalid_variables)}"
            )
        super().__init__(f"Invalid application configuration ({'; '.join(categories)})")


def _safe_variable_name(name: str) -> str:
    return name.replace("SECRET", "CREDENTIAL")


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
