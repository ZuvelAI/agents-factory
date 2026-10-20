"""Bounded, local-only container inspection; never trust a MIME label."""

import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable, Any

from .models import AudioInspection


class AudioInspectionError(RuntimeError):
    pass


class AudioInspector:
    def __init__(
        self,
        *,
        spawn: Callable[..., Awaitable[Any]] = asyncio.create_subprocess_exec,
        timeout: float = 5.0,
    ) -> None:
        self.spawn = spawn
        self.timeout = min(timeout, 5.0)

    async def inspect(self, path: Path) -> AudioInspection:
        size = path.stat().st_size
        if not 0 < size <= 10_000_000:
            raise AudioInspectionError("audio_size_invalid")
        process = None
        try:
            async with asyncio.timeout(self.timeout):
                process = await self.spawn(
                    "ffprobe",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file",
                    "-format_whitelist",
                    "ogg",
                    "-show_entries",
                    "format=format_name,duration:stream=codec_type,codec_name",
                    "-of",
                    "json",
                    str(path.resolve()),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                output = bytearray()
                while chunk := await process.stdout.read(8192):
                    output.extend(chunk)
                    if len(output) > 65536:
                        raise AudioInspectionError("audio_inspection_output_limit")
                if await process.wait() != 0:
                    raise AudioInspectionError("audio_format_unsupported")
                data = json.loads(output)
                streams = data["streams"]
                if len(streams) != 1 or streams[0]["codec_type"] != "audio":
                    raise AudioInspectionError("audio_format_unsupported")
                return AudioInspection(
                    data["format"]["format_name"],
                    streams[0]["codec_name"],
                    float(data["format"]["duration"]),
                    size,
                )
        except FileNotFoundError:
            raise AudioInspectionError("audio_inspector_unavailable") from None
        except TimeoutError:
            raise AudioInspectionError("audio_inspection_timeout") from None
        except (ValueError, KeyError, TypeError, IndexError):
            raise AudioInspectionError("audio_inspection_invalid") from None
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await asyncio.shield(process.wait())
