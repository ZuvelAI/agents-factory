"""Channel-owned presentation; the model answers, the server adds the exact greeting."""

import re
import unicodedata
from agents_factory.modules.runtime.contracts import AgentTurnInput


def orientation_only(message: str) -> bool:
    normalized = "".join(
        c
        for c in unicodedata.normalize("NFKD", message.casefold())
        if not unicodedata.combining(c)
    )
    normalized = " ".join(re.sub(r"[^a-z0-9 ]", " ", normalized).split())
    return bool(
        re.fullmatch(
            r"(?:hola|buenos dias|buenas tardes|buenas noches|buenas|hey|hello|hi)"
            r"|(?:hola )?(?:quiero|quisiera|me gustaria) (?:conocer|saber de) (?:la|tu|su) empresa"
            r"|(?:que|cuales) (?:son |son los )?servicios (?:ofrecen|ofrece (?:la|su|tu) empresa|tienen)(?: segun la informacion aprobada)?"
            r"|cuales son (?:sus|tus) servicios|a que se dedican|que hace (?:la|su|tu) empresa",
            normalized,
        )
    )


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


def compose_welcome(
    output: str,
    greeting: str | None,
    *,
    first_contact: bool,
    only_orientation: bool = False,
) -> str:
    if not greeting:
        return output
    body = output.strip()
    # The adapter and persistence boundary may both apply this rule. Keep it idempotent.
    while body.startswith(greeting):
        body = body[len(greeting) :].lstrip()
    if first_contact:
        if only_orientation:
            return greeting
        return greeting + ("\n\n" + body if body else "")
    if not body:
        raise ValueError("model returned only a suppressed welcome")
    return body
