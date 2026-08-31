from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


Amount = Annotated[
    Decimal, Field(ge=0, max_digits=30, decimal_places=12, allow_inf_nan=False)
]
Count = Annotated[int, Field(ge=0, le=10**15, strict=True)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
UsageKind = Literal["llm", "whatsapp", "tool", "storage", "infrastructure"]
Meter = Literal[
    "uncached_input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "requests",
    "messages",
    "tool_calls",
    "storage_byte_hours",
    "infrastructure_units",
]


class UsageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Money(UsageModel):
    amount: Amount
    currency: Currency


class Measurements(UsageModel):
    # None means not reported. Zero is an explicit measurement, never a fallback.
    input_tokens: Count | None = None
    cached_input_tokens: Count | None = None
    reasoning_tokens: Count | None = None
    output_tokens: Count | None = None
    requests: Count | None = None
    messages: Count | None = None
    tool_calls: Count | None = None
    storage_byte_hours: Amount | None = None
    infrastructure_units: Amount | None = None
    latency_ms: Amount | None = None

    @model_validator(mode="after")
    def consistent_tokens(self) -> "Measurements":
        for part, total in (
            (self.cached_input_tokens, self.input_tokens),
            (self.reasoning_tokens, self.output_tokens),
        ):
            if part is not None and total is not None and part > total:
                raise ValueError("token_subset_exceeds_total")
        return self

    def billable(self, meter: Meter) -> Decimal | None:
        if meter == "uncached_input_tokens":
            if self.input_tokens is None or self.cached_input_tokens is None:
                return None
            return Decimal(self.input_tokens - self.cached_input_tokens)
        value = getattr(self, meter)
        return None if value is None else Decimal(value)


class WhatsAppCostMetadata(UsageModel):
    category: Literal["utility", "authentication", "marketing", "service"]
    recipient_market: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    billable: bool | None = None


class UsageEvent(UsageModel):
    source_key: Annotated[
        str, Field(min_length=1, max_length=180, pattern=r"^[a-zA-Z0-9_.:-]+$")
    ]
    occurred_at: AwareDatetime
    kind: UsageKind
    provider: Annotated[
        str, Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    ]
    product: Annotated[
        str, Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.:-]+$")
    ]
    currency: Currency
    model: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    run_id: UUID | None = None
    conversation_id: UUID | None = None
    action_id: UUID | None = None
    case_id: UUID | None = None
    measurements: Measurements
    provider_cost: Money | None = None
    whatsapp: WhatsAppCostMetadata | None = None

    @model_validator(mode="after")
    def consistent_source(self) -> "UsageEvent":
        if (
            self.provider_cost is not None
            and self.provider_cost.currency != self.currency
        ):
            raise ValueError("usage_currency_mismatch")
        if self.whatsapp is not None and self.kind != "whatsapp":
            raise ValueError("invalid_whatsapp_cost_metadata")
        if self.kind == "llm" and self.model != self.product:
            raise ValueError("llm_model_must_match_price_product")
        return self


class UnitPrice(UsageModel):
    amount: Amount
    per_units: Annotated[
        Decimal, Field(gt=0, le=10**15, decimal_places=6, allow_inf_nan=False)
    ] = Decimal(1)


class PriceCard(UsageModel):
    id: UUID
    provider: str = Field(min_length=1, max_length=80)
    product: str = Field(min_length=1, max_length=120)
    kind: UsageKind
    currency: Currency
    effective_from: AwareDatetime
    effective_until: AwareDatetime | None = None
    rates: dict[Meter, UnitPrice] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def valid_price(self) -> "PriceCard":
        if (
            self.effective_until is not None
            and self.effective_until <= self.effective_from
        ):
            raise ValueError("invalid_price_interval")
        if (
            self.kind == "llm"
            and not {"uncached_input_tokens", "cached_input_tokens", "output_tokens"}
            <= self.rates.keys()
        ):
            raise ValueError("llm_token_rates_required")
        return self


class CommercialPolicy(UsageModel):
    messages: Count | None = None
    conversations: Count | None = None
    model_tokens: Count | None = None
    cost: Money | None = None
    storage_bytes: Count | None = None
    concurrent_runs: Count | None = None
    tool_calls: Count | None = None
    alert_percentages: tuple[int, ...] = (70, 85, 100)

    @model_validator(mode="after")
    def valid_thresholds(self) -> "CommercialPolicy":
        values = self.alert_percentages
        if (
            not values
            or len(values) > 10
            or any(isinstance(v, bool) or not 1 <= v <= 100 for v in values)
            or tuple(sorted(set(values))) != values
        ):
            raise ValueError("invalid_alert_thresholds")
        return self


class TechnicalLimits(UsageModel):
    max_tool_calls: int = Field(default=8, ge=0, le=32)
    max_retries: int = Field(default=2, ge=0, le=10)
    max_model_tokens: int = Field(default=32768, ge=1, le=10**7)
    max_concurrent_runs: int = Field(default=4, ge=1, le=1000)
    max_requests_per_minute: int = Field(default=60, ge=1, le=100000)


class QuotaWindow(UsageModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def valid_window(self) -> "QuotaWindow":
        if not timedelta(0) < self.end - self.start <= timedelta(days=366):
            raise ValueError("invalid_quota_window")
        return self


class UsageConfiguration(UsageModel):
    prices: tuple[PriceCard, ...] = Field(default=(), max_length=500)
    commercial: CommercialPolicy = Field(default_factory=CommercialPolicy)
    technical: TechnicalLimits = Field(default_factory=TechnicalLimits)
    quota_window: QuotaWindow | None = None

    @model_validator(mode="after")
    def unique_versions(self) -> "UsageConfiguration":
        ids = [p.id for p in self.prices]
        versions = [
            (p.provider, p.product, p.kind, p.currency, p.effective_from)
            for p in self.prices
        ]
        if len(set(ids)) != len(ids) or len(set(versions)) != len(versions):
            raise ValueError("ambiguous_price_version")
        return self


class CostQuote(UsageModel):
    currency: Currency
    amount: Amount | None
    basis: Literal["provider", "price_card", "unknown"]
    price_version: UUID | None = None
    reason: Literal["price_unavailable", "measurement_unavailable"] | None = None


class UsageRecord(UsageModel):
    id: UUID
    tenant_id: UUID
    event: UsageEvent
    quote: CostQuote
    configuration_revision: int
    recorded_at: datetime
