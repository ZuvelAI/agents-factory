"""Channel-owned presentation; the model answers, the server adds the exact greeting."""

from agents_factory.modules.runtime.contracts import AgentTurnInput


def turn_instructions(turn: AgentTurnInput) -> str:
    base = turn.agent_spec.instructions
    if not turn.agent_spec.first_contact_greeting:
        return base
    return base + (
        "\n\n[SERVER-OWNED PRESENTATION]\n"
        "Do not greet, introduce the business, repeat its complete service list, or copy "
        "the configured welcome. The server decides from persisted contact history "
        "whether to prepend that welcome. Answer the customer's specific question "
        "directly, respecting scope and safety. For a bare greeting, briefly invite "
        "the customer to describe their business need. This rule overrides tenant "
        "instructions to repeat the welcome; it does not override platform safety."
    )


def compose_welcome(output: str, greeting: str | None, *, first_contact: bool) -> str:
    if not greeting:
        return output
    body = output.strip()
    # The adapter and persistence boundary may both apply this rule. Keep it idempotent.
    while body.startswith(greeting):
        body = body[len(greeting) :].lstrip()
    if first_contact:
        return greeting + ("\n\n" + body if body else "")
    if not body:
        raise ValueError("model returned only a suppressed welcome")
    return body
