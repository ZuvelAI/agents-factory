from agents_factory.modules.cases.models import CasePolicy, CasePriority


def assign_priority(issue_type: str, policy: CasePolicy) -> CasePriority:
    # No invented text/LLM urgency or customer-provided priority can override this.
    return policy.priority_by_issue.get(issue_type, "NORMAL")
