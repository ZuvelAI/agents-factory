from __future__ import annotations

import struct
import wave
import zlib
from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject


def png():
    def chunk(name, payload):
        return (
            struct.pack(">I", len(payload))
            + name
            + payload
            + struct.pack(">I", zlib.crc32(name + payload))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


def wav():
    value = BytesIO()
    with wave.open(value, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\x00\x00" * 800)
    return value.getvalue()


def pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 10 100 Td (Order evidence 27) Tj ET")
    page[NameObject("/Contents")] = content
    value = BytesIO()
    writer.write(value)
    return value.getvalue()


def mp4():
    def box(name, payload):
        return struct.pack(">I", len(payload) + 8) + name + payload

    return (
        box(b"ftyp", b"mp42\x00\x00\x00\x00mp42")
        + box(b"moov", b"")
        + box(b"mdat", b"fixture")
    )


class Scanner:
    result = "CLEAN"

    async def scan(self, content, *, media_type):
        return self.result


class MediaProvider:
    def __init__(self):
        self.files = {
            "1": (png(), "image/png"),
            "2": (wav(), "audio/wav"),
            "3": (pdf(), "application/pdf"),
            "4": (mp4(), "video/mp4"),
        }
        self.calls = []
        self.error = None

    async def download_media(
        self, *, context, whatsapp_account_id, phone_number_id, media_id, max_bytes
    ):
        self.calls.append(media_id)
        if self.error:
            raise self.error
        return self.files[media_id]
