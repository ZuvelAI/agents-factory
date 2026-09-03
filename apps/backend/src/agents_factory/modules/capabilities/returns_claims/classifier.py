from typing import cast

from agents_factory.modules.capabilities.returns_claims.models import (
    ISSUE_CLASSES,
    IssueClass,
)


def classify_issue(value: str | None) -> IssueClass | None:
    """Validate an explicit class; ambiguous/unknown input must be clarified.

    This does not guess a class from prose or trust an LLM's business decision.
    Product and service nonconformity share the one approved v1 class.
    """
    return cast(IssueClass, value) if value in ISSUE_CLASSES else None
