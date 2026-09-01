from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from agents_factory.modules.usage.models import CostQuote, PriceCard, UsageEvent


def quote_usage(
    event: UsageEvent, cards: tuple[PriceCard, ...]
) -> tuple[CostQuote, PriceCard | None]:
    if event.provider_cost is not None:
        return CostQuote(
            currency=event.currency, amount=event.provider_cost.amount, basis="provider"
        ), None
    if (
        event.kind == "whatsapp"
        and event.whatsapp
        and event.whatsapp.billable is False
    ):
        return CostQuote(
            currency=event.currency, amount=Decimal(0), basis="provider"
        ), None
    matches = [
        p
        for p in cards
        if (p.provider, p.product, p.kind, p.currency)
        == (event.provider, event.product, event.kind, event.currency)
        and p.effective_from <= event.occurred_at
        and (p.effective_until is None or event.occurred_at < p.effective_until)
    ]
    if not matches:
        return CostQuote(
            currency=event.currency,
            amount=None,
            basis="unknown",
            reason="price_unavailable",
        ), None
    # New effective-date versions supersede older open-ended versions. Each record
    # retains its exact chosen snapshot; later configuration never reprices it.
    card = max(matches, key=lambda p: p.effective_from)
    with localcontext() as ctx:
        ctx.prec = 60
        total = Decimal(0)
        for meter, price in card.rates.items():
            units = event.measurements.billable(meter)
            if units is None:
                return CostQuote(
                    currency=event.currency,
                    amount=None,
                    basis="unknown",
                    price_version=card.id,
                    reason="measurement_unavailable",
                ), card
            total += units * price.amount / price.per_units
        # Cached input is a subset of input; reasoning a subset of output.
        # Neither is charged on top of its enclosing total a second time.
        amount = total.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN)
    return CostQuote(
        currency=event.currency,
        amount=amount,
        basis="price_card",
        price_version=card.id,
    ), card
