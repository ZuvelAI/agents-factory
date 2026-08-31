from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from agents_factory.modules.usage.models import (
    Measurements,
    PriceCard,
    UnitPrice,
    UsageEvent,
)


NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)


def price():
    # Explicitly fictional test tariff, not a current provider price.
    return PriceCard(
        id=uuid4(),
        provider="fixture",
        product="fixture-model",
        kind="llm",
        currency="USD",
        effective_from=NOW,
        rates={
            "uncached_input_tokens": UnitPrice(
                amount=Decimal(2), per_units=Decimal(1000000)
            ),
            "cached_input_tokens": UnitPrice(
                amount=Decimal("0.5"), per_units=Decimal(1000000)
            ),
            "output_tokens": UnitPrice(amount=Decimal(4), per_units=Decimal(1000000)),
        },
    )


def event(key="runtime:fixture"):
    return UsageEvent(
        source_key=key,
        occurred_at=NOW,
        kind="llm",
        provider="fixture",
        product="fixture-model",
        model="fixture-model",
        currency="USD",
        measurements=Measurements(
            input_tokens=100,
            cached_input_tokens=20,
            output_tokens=50,
            reasoning_tokens=10,
            requests=1,
            latency_ms=Decimal(150),
        ),
    )
