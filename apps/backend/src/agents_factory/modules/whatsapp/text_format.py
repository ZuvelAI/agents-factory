import re


def format_whatsapp_ai_text(body: str) -> str:
    """Use WhatsApp bold, retaining text/bullets and dropping orphan markers.

    The source message remains the raw model output. Only the channel payload is
    normalized. This is deliberately not a general-purpose Markdown renderer.
    """
    output = []
    for line in body.splitlines(keepends=True):
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
    return "".join(output)
