from __future__ import annotations

import asyncio
import multiprocessing
import sys
from io import BytesIO
from multiprocessing.connection import Connection

from pypdf import PdfReader

from agents_factory.modules.media.contracts import (
    MediaError,
    NormalizedMediaObservation,
)


def _extract(pipe: Connection, content: bytes) -> None:
    """Disposable process: untrusted PDF work has hard CPU/address-space limits."""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
        # Darwin does not provide Linux's enforceable RLIMIT_AS semantics.
        # Wall-clock/CPU/page/text limits remain active on the laptop.
        if sys.platform == "linux":
            resource.setrlimit(
                resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024)
            )
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted or len(reader.pages) > 100:
            pipe.send((False, "pdf_restricted"))
            return
        parts = []
        total = 0
        for page in reader.pages:
            value = (page.extract_text() or "").strip()
            total += len(value)
            if total > 60000:
                pipe.send((False, "pdf_text_limit"))
                return
            parts.append(value)
        pipe.send((True, "\n".join(parts)))
    except Exception:
        pipe.send((False, "pdf_corrupted"))
    finally:
        pipe.close()


def _bounded_extract(content: bytes) -> str:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_extract, args=(child, content), daemon=True)
    process.start()
    child.close()
    try:
        if not parent.poll(12):
            raise MediaError("pdf_processing_timeout")
        try:
            success, value = parent.recv()
        except EOFError:
            raise MediaError("pdf_corrupted") from None
        if not success:
            raise MediaError(value)
        return str(value)
    finally:
        parent.close()
        process.join(timeout=0.2)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)


async def normalize_pdf(content: bytes) -> NormalizedMediaObservation:
    value = await asyncio.to_thread(_bounded_extract, content)
    return NormalizedMediaObservation(
        kind="document",
        status="READY" if value.strip() else "HUMAN_REVIEW",
        text=value,
        reason_code=None if value.strip() else "pdf_no_extractable_text",
    )
