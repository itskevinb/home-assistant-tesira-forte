"""Tests for TTP reply correlation (no Home Assistant or device needed)."""
import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "tesira_ttp",
    Path(__file__).parents[1] / "custom_components" / "tesira_forte" / "ttp.py",
)
ttp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ttp)


def _client(monkeypatch, grace=0.2):
    monkeypatch.setattr(ttp, "_LATE_REPLY_GRACE", grace)
    client = ttp.TesiraTTP("127.0.0.1")
    client._writer = MagicMock()
    client._writer.drain = AsyncMock()
    return client


async def _reply_soon(client, line, delay=0.02):
    await asyncio.sleep(delay)
    client._dispatch(line)


@pytest.mark.asyncio
async def test_late_reply_not_taken_by_next_get(monkeypatch):
    client = _client(monkeypatch)
    with pytest.raises(asyncio.TimeoutError):
        await client.get_value("A get level 1", timeout=0.05)
    # A's reply turns up late, then B's own reply.
    asyncio.get_running_loop().call_later(0.05, client._dispatch, '+OK "-10.0"')
    asyncio.get_running_loop().call_later(0.1, client._dispatch, '+OK "true"')
    assert await client.get_value("B get mute 1", timeout=1) == "true"


@pytest.mark.asyncio
async def test_missing_late_reply_does_not_eat_next_reply(monkeypatch):
    client = _client(monkeypatch, grace=0.05)
    with pytest.raises(asyncio.TimeoutError):
        await client.get_value("A get level 1", timeout=0.05)
    # A's reply never comes; after the grace period B's reply must be kept.
    task = asyncio.create_task(client.get_value("B get mute 1", timeout=1))
    await asyncio.sleep(0.1)
    client._dispatch('+OK "false"')
    assert await task == "false"


@pytest.mark.asyncio
async def test_normal_get_unaffected(monkeypatch):
    client = _client(monkeypatch)
    asyncio.get_running_loop().call_later(0.02, client._dispatch, '+OK "1.5"')
    assert await client.get_value("A get level 1", timeout=1) == "1.5"
