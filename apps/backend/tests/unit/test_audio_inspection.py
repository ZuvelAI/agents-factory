import asyncio
import json

import pytest

from agents_factory.modules.audio_ingestion.inspection import (
    AudioInspector,
    AudioInspectionError,
)


def report(*, duration="300", codec="opus", container="ogg"):
    return json.dumps(
        {
            "streams": [{"codec_type": "audio", "codec_name": codec}],
            "format": {"format_name": container, "duration": duration},
        }
    ).encode()


class Process:
    def __init__(self, output):
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(output)
        self.stdout.feed_eof()
        self.returncode = 0

    async def wait(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


@pytest.mark.parametrize(
    "output,valid",
    [
        (report(), True),
        (report(duration="300.001"), False),
        (report(duration=None), False),
        (report(duration="NaN"), False),
        (report(codec="aac"), False),
        (report(container="mov"), False),
        (b"x" * 65537, False),
        (b"bad", False),
    ],
)
async def test_inspector_requires_ogg_opus_finite_duration_and_available_binary(
    tmp_path, output, valid
):
    path = tmp_path / "voice.ogg"
    path.write_bytes(b"synthetic")
    calls = []

    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return Process(output)

    inspector = AudioInspector(spawn=spawn)
    if valid:
        result = await inspector.inspect(path)
        assert result.duration_seconds == 300
        args, _ = calls[0]
        assert args[args.index("-protocol_whitelist") + 1] == "file"
        assert args[args.index("-format_whitelist") + 1] == "ogg"
        assert args[-1] == str(path.resolve())
    else:
        with pytest.raises(AudioInspectionError):
            await inspector.inspect(path)


async def test_inspector_missing_and_hanging_binary_fail_closed(tmp_path):
    path = tmp_path / "voice.ogg"
    path.write_bytes(b"synthetic")

    async def missing(*args, **kwargs):
        raise FileNotFoundError("private executable path")

    with pytest.raises(AudioInspectionError, match="audio_inspector_unavailable"):
        await AudioInspector(spawn=missing).inspect(path)
    process = Process(b"")
    process.stdout = asyncio.StreamReader()
    process.returncode = None

    async def hanging(*args, **kwargs):
        return process

    with pytest.raises(AudioInspectionError, match="audio_inspection_timeout"):
        await AudioInspector(spawn=hanging, timeout=0.01).inspect(path)
    assert process.returncode == -9


@pytest.mark.parametrize("size,valid", [(10000000, True), (10000001, False)])
async def test_inspector_file_size_boundary(tmp_path, size, valid):
    path = tmp_path / "voice.ogg"
    with path.open("wb") as target:
        target.truncate(size)

    async def spawn(*args, **kwargs):
        return Process(report())

    if valid:
        assert (await AudioInspector(spawn=spawn).inspect(path)).size_bytes == size
    else:
        with pytest.raises(AudioInspectionError, match="audio_size_invalid"):
            await AudioInspector(spawn=spawn).inspect(path)
