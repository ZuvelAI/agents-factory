from __future__ import annotations

from io import BytesIO
import base64
import hashlib
import hmac
import wave

from agents_factory.modules.media.contracts import MAX_BYTES, MediaError


def matches_provider_digest(content: bytes, digest: object) -> bool:
    if not isinstance(digest, str):
        return False
    actual = hashlib.sha256(content).digest()
    return hmac.compare_digest(actual.hex(), digest) or hmac.compare_digest(
        base64.b64encode(actual).decode(), digest
    )


def sniff(content: bytes, *, claimed: str, kind: str) -> str:
    """Bounded container checks; this does not replace the mandatory malware hook."""
    if not content or len(content) > MAX_BYTES:
        raise MediaError("media_size_invalid")
    actual = ""
    if content.startswith(b"%PDF-") and b"%%EOF" in content[-1024:]:
        actual = "application/pdf"
    elif content.startswith(b"\x89PNG\r\n\x1a\n") and content.endswith(
        b"IEND\xaeB`\x82"
    ):
        actual = "image/png"
    elif content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9"):
        actual = "image/jpeg"
    elif content.startswith(b"RIFF") and content[8:12] == b"WAVE":
        try:
            with wave.open(BytesIO(content)) as audio:
                if (
                    audio.getnframes() < 1
                    or len(audio.readframes(audio.getnframes()))
                    != audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
                ):
                    raise MediaError("media_corrupted")
            actual = "audio/wav"
        except (wave.Error, EOFError):
            raise MediaError("media_corrupted") from None
    elif (
        content.startswith(b"OggS")
        and len(content) > 40
        and (b"OpusHead" in content[:256] or b"vorbis" in content[:256])
    ):
        actual = "audio/ogg"
    elif len(content) > 128 and (
        content.startswith(b"ID3")
        or content[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}
    ):
        actual = "audio/mpeg"
    elif len(content) > 24 and content[4:8] == b"ftyp":
        cursor = 0
        boxes = set()
        while cursor < len(content):
            size = int.from_bytes(content[cursor : cursor + 4], "big")
            if size < 8 or cursor + size > len(content):
                raise MediaError("media_corrupted")
            boxes.add(content[cursor + 4 : cursor + 8])
            cursor += size
        if not {b"moov", b"mdat"}.issubset(boxes):
            raise MediaError("media_corrupted")
        actual = "audio/mp4" if kind == "audio" else "video/mp4"
    allowed = {
        "audio": {"audio/wav", "audio/ogg", "audio/mpeg", "audio/mp4"},
        "image": {"image/png", "image/jpeg"},
        "document": {"application/pdf"},
        "video": {"video/mp4"},
    }
    normalized = claimed.partition(";")[0].strip().lower()
    normalized = {"audio/x-wav": "audio/wav", "audio/mp3": "audio/mpeg"}.get(
        normalized, normalized
    )
    if not actual or actual != normalized or actual not in allowed.get(kind, set()):
        raise MediaError("media_type_mismatch")
    if kind == "image" and len(content) > 5 * 1024 * 1024:
        raise MediaError("media_size_invalid")
    return actual
