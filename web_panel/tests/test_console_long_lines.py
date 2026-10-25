"""A huge console line must not stop the panel from draining the server output."""

from __future__ import annotations

import asyncio

import pytest

from app.services.server_process import MinecraftServerManager


def _manager_recording(lines: list[str]) -> MinecraftServerManager:
    manager = object.__new__(MinecraftServerManager)

    async def record(stream_name: str, line: str) -> None:
        lines.append(line)

    manager._record_log = record
    return manager


@pytest.mark.asyncio
async def test_line_longer_than_asyncio_limit_is_cut_and_reading_continues() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"antes\r\n" + b"x" * 200_000 + b"\nPreparing level\n" + b"sin salto")
    reader.feed_eof()
    lines: list[str] = []

    await asyncio.wait_for(_manager_recording(lines)._read_stream(reader, "stdout"), timeout=5)

    assert lines[0] == "antes"
    assert lines[1].startswith("x" * 1000) and "recortada" in lines[1]
    assert len(lines[1]) < 20_000
    assert lines[2:] == ["Preparing level", "sin salto"]


@pytest.mark.asyncio
async def test_a_failing_line_does_not_stop_the_reader() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"falla\nsigue\n")
    reader.feed_eof()
    seen: list[str] = []
    manager = object.__new__(MinecraftServerManager)

    async def record(stream_name: str, line: str) -> None:
        if line == "falla":
            raise RuntimeError("boom")
        seen.append(line)

    manager._record_log = record
    await manager._read_stream(reader, "stdout")

    assert seen == ["sigue"]
