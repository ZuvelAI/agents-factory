import re


def format_whatsapp_ai_text(body: str) -> str:
    """Use WhatsApp bold, retaining text/bullets and dropping orphan markers.

    The source message remains the raw model output. Only the channel payload is
    normalized. This is deliberately not a general-purpose Markdown renderer.
    """
    # Protect literal content before interpreting formatting delimiters. Tokens
    # cannot collide with the source and are all restored before persistence.
    prefix = "\x00whatsapp_literal"
    while prefix in body:
        prefix += "_"
    literals: dict[str, str] = {}
    masked_prefix = ""
    cursor = 0

    def protect(match: re.Match[str]) -> str:
        nonlocal masked_prefix, cursor
        masked_prefix += body[cursor : match.start()]
        literal = match.group()
        suffix = ""
        # A closing bold delimiter next to a URL is not part of the URL. Earlier
        # literal spans are already masked, so their stars do not affect pairing.
        runs = list(re.finditer(r"\*+", masked_prefix.rsplit("\n", 1)[-1]))
        trailing = re.search(r"\*+$", literal)
        if literal.startswith(("http://", "https://")) and trailing and len(runs) % 2:
            size = min(len(runs[-1].group()), len(trailing.group()))
            literal, suffix = literal[:-size], literal[-size:]
        placeholder = f"{prefix}{len(literals)}\x00"
        literals[placeholder] = literal
        replacement = placeholder + suffix
        masked_prefix += replacement
        cursor = match.end()
        return replacement

    protected = re.sub(
        r"https?://[^\s<>]+|`+[^`\r\n]*`+|(?<!\w)\d+(?:[.,]\d+)?[ \t]*\*+[ \t]*\d+(?:[.,]\d+)?(?!\w)",
        protect,
        body,
    )
    output = []
    for line in protected.splitlines(keepends=True):
        line = re.sub(r"^(\s*)\*(?=\s+\S)", r"\1•", line)
        line = re.sub(r"\*+", "*", line)
        parts = []
        start = 0
        for match in re.finditer(r"\*([^*\r\n]+)\*", line):
            parts.append(line[start : match.start()].replace("*", ""))
            label = match.group(1)
            parts.append(f"*{label}*" if label == label.strip() else label)
            start = match.end()
        parts.append(line[start:].replace("*", ""))
        output.append("".join(parts))
    result = "".join(output)
    for placeholder, literal in literals.items():
        result = result.replace(placeholder, literal)
    return result
