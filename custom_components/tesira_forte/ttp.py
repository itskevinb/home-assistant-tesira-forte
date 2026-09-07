"""Async client for the Biamp Tesira Text Protocol (TTP) over telnet.

TTP is a line-oriented ASCII protocol on TCP/23. This client keeps one
persistent session open, refuses all telnet option negotiation, and exposes:

* ``get_value(cmd)``  - send a ``... get ...`` and await the ``+OK`` payload
* ``send(cmd)``       - fire-and-forget (used for ``set`` / ``subscribe`` and
  the fault-list poll)
* ``subscribe(...)``  - register a publish token; the Forte then pushes
  ``! "token" <value>`` immediately and on every change

Reconnect with exponential backoff is automatic. ``on_connect`` /
``on_disconnect`` callbacks let the coordinator re-subscribe and flip
availability.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from contextlib import asynccontextmanager
import logging
import re

_LOGGER = logging.getLogger(__name__)

_IAC = 255
_WILL, _WONT, _DO, _DONT = 251, 252, 253, 254

_PUBLISH_RE = re.compile(r'^!\s+"([^"]+)"\s+(.*)$')
_FAULT_RE = re.compile(r'\[(\d+)\s+"([^"]*)"')

PublishCb = Callable[[str, str], None]
FaultCb = Callable[[list[tuple[int, str]]], None]


class TTPError(Exception):
    """A TTP command returned -ERR or the session failed."""


class TesiraTTP:
    """Persistent TTP session with auto-reconnect."""

    def __init__(
        self,
        host: str,
        port: int = 23,
        *,
        on_connect: Callable[[], Awaitable[None]] | None = None,
        on_disconnect: Callable[[], None] | None = None,
        publish_cb: PublishCb | None = None,
        fault_cb: FaultCb | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._publish_cb = publish_cb
        self._fault_cb = fault_cb

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._run_task: asyncio.Task | None = None
        self._connect_task: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()
        self._cmd_lock = asyncio.Lock()
        self._reply: asyncio.Future[str] | None = None
        self._reply_wants_value = False
        self._connected = asyncio.Event()
        self._closing = False

    # -- lifecycle ------------------------------------------------------
    async def start(self) -> None:
        self._closing = False
        self._run_task = asyncio.create_task(self._run(), name="tesira-ttp")

    async def stop(self) -> None:
        self._closing = True
        for task in (self._run_task, self._connect_task):
            if task:
                task.cancel()
        if self._writer:
            self._writer.close()
        self._connected.clear()

    async def wait_connected(self, timeout: float) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout)

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    # -- main loop ----------------------------------------------------
    async def _run(self) -> None:
        backoff = 2
        while not self._closing:
            try:
                await self._serve()
                backoff = 2
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Tesira TTP session ended: %s", err)
            self._connected.clear()
            if self._on_disconnect:
                self._on_disconnect()
            if self._writer:
                self._writer.close()
                self._writer = None
            if self._closing:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def _serve(self) -> None:
        _LOGGER.debug("Connecting to Tesira %s:%s", self.host, self.port)
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=10
        )
        await self._telnet_prologue()
        await self._send_raw("SESSION set verbose false")
        # Consume the banner + the ack for the line above so the first real
        # get_value() cannot latch onto a stray "+OK".
        await self._drain(0.7)
        self._connected.set()
        if self._on_connect:
            self._connect_task = asyncio.create_task(self._guarded_on_connect())

        while not self._closing:
            try:
                line = await asyncio.wait_for(self._reader.readline(), timeout=60)
            except asyncio.TimeoutError as err:
                # Fault poll replies land every ~15 s; 60 s of total silence
                # means the session is wedged. Bail so _run reconnects.
                raise TTPError("no data for 60s") from err
            if line == b"":
                raise TTPError("connection closed by device")
            self._dispatch(self._clean(line))

    async def _guarded_on_connect(self) -> None:
        try:
            await self._on_connect()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.exception("on_connect handler failed; forcing reconnect")
            if self._writer is not None:
                self._writer.close()

    async def _drain(self, quiet: float) -> None:
        """Read and discard buffered lines until the link goes quiet."""
        assert self._reader
        for _ in range(6):
            try:
                data = await asyncio.wait_for(self._reader.readline(), timeout=quiet)
            except asyncio.TimeoutError:
                return
            if data == b"":
                raise TTPError("connection closed by device")

    # -- telnet / framing -------------------------------------------
    async def _telnet_prologue(self) -> None:
        """Answer the Forte's option negotiation until it goes quiet.

        The Forte gates the TTP layer behind telnet negotiation and sends it in
        several rounds (DO TTYPE/TSPEED/..., then WILL SGA / DO ECHO / ...), so
        one pass is not enough. ``_clean`` sends the refusals.
        """
        assert self._reader
        for _ in range(8):
            try:
                data = await asyncio.wait_for(self._reader.read(1024), timeout=0.6)
            except asyncio.TimeoutError:
                return
            if data == b"":
                raise TTPError("connection closed during negotiation")
            self._clean(data)

    def _clean(self, raw: bytes) -> str:
        """Strip telnet control bytes; refuse every WILL/DO we are asked."""
        out = bytearray()
        refuse = bytearray()
        i = 0
        while i < len(raw):
            b = raw[i]
            if b == _IAC and i + 1 < len(raw):
                cmd = raw[i + 1]
                if cmd in (_WILL, _WONT, _DO, _DONT) and i + 2 < len(raw):
                    opt = raw[i + 2]
                    if cmd == _DO:
                        refuse += bytes([_IAC, _WONT, opt])
                    elif cmd == _WILL:
                        refuse += bytes([_IAC, _DONT, opt])
                    i += 3
                    continue
                i += 2
                continue
            out.append(b)
            i += 1
        if refuse and self._writer is not None:
            self._writer.write(bytes(refuse))
        return out.decode("utf-8", "replace").strip("\r\n ")

    # -- dispatch ---------------------------------------------------
    def _dispatch(self, line: str) -> None:
        if not line:
            return
        match = _PUBLISH_RE.match(line)
        if match:
            if self._publish_cb:
                self._publish_cb(match.group(1), match.group(2).strip())
            return
        if line.startswith("+OK [[") and '"' in line:
            if self._fault_cb:
                self._fault_cb(
                    [(int(fid), txt) for fid, txt in _FAULT_RE.findall(line)]
                )
            return
        if line.startswith("+OK"):
            payload = line[3:].strip()
            if payload.startswith('"') and payload.endswith('"'):
                payload = payload[1:-1]
            if self._reply and not self._reply.done():
                # A bare "+OK" is an ack for set/subscribe/session; only a
                # get is allowed to consume it when it carries no value.
                if payload or not self._reply_wants_value:
                    self._reply.set_result(payload)
            return
        if line.startswith("-ERR"):
            if self._reply and not self._reply.done():
                self._reply.set_exception(TTPError(line))

    # -- outbound -------------------------------------------------
    async def _send_raw(self, line: str) -> None:
        if not self._writer:
            raise TTPError("not connected")
        async with self._write_lock:
            self._writer.write((line + "\r\n").encode())
            await self._writer.drain()

    async def send(self, line: str) -> None:
        """Fire-and-forget command not correlated to a reply (fault poll)."""
        await self._send_raw(line)

    async def get_value(self, cmd: str, timeout: float = 5.0) -> str:
        """Send a get command and return the +OK payload (quotes stripped).

        Serialised with every other correlated command so a stray "+OK" from a
        concurrent set can't satisfy this future.
        """
        async with self._cmd_lock:
            loop = asyncio.get_running_loop()
            self._reply = loop.create_future()
            self._reply_wants_value = True
            try:
                await self._send_raw(cmd)
                return await asyncio.wait_for(self._reply, timeout)
            finally:
                self._reply = None

    async def subscribe(
        self, block: str, attr: str, idx: tuple[int, ...], token: str,
        rate_ms: int | None = None,
    ) -> None:
        idx_str = " ".join(str(i) for i in idx)
        rate = f" {rate_ms}" if rate_ms else ""
        await self._send_raw(f'{block} subscribe {attr} {idx_str} "{token}"{rate}')

    async def set_value(
        self, block: str, attr: str, idx: tuple[int, ...], value: str
    ) -> None:
        idx_str = " ".join(str(i) for i in idx)
        async with self._cmd_lock:
            loop = asyncio.get_running_loop()
            self._reply = loop.create_future()
            self._reply_wants_value = False
            try:
                await self._send_raw(f"{block} set {attr} {idx_str} {value}")
                await asyncio.wait_for(self._reply, 3.0)
            except (asyncio.TimeoutError, TTPError) as err:
                _LOGGER.debug("set %s %s %s: %s", block, attr, idx_str, err)
            finally:
                self._reply = None

    # -- one-shot session for the config flow --------------------
    @classmethod
    @asynccontextmanager
    async def oneshot(cls, host: str, port: int, *, timeout: float = 10):
        """Yield a short-lived connected client for the config/options flow.

        Handles telnet negotiation + ``SESSION set verbose false`` and runs a
        background reader so ``get_value()`` works normally; tears everything
        down on exit. Not for long-running use - the main integration uses the
        full ``start()`` loop with auto-reconnect.
        """
        client = cls(host, port)
        client._reader, client._writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        await client._telnet_prologue()
        await client._send_raw("SESSION set verbose false")
        await client._drain(0.7)

        async def _pump() -> None:
            try:
                while True:
                    data = await client._reader.readline()
                    if not data:
                        return
                    client._dispatch(client._clean(data))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _LOGGER.debug("oneshot reader ended", exc_info=True)

        pump = asyncio.create_task(_pump(), name="tesira-oneshot")
        try:
            yield client
        finally:
            pump.cancel()
            with contextlib.suppress(BaseException):
                await pump
            client._writer.close()

    @classmethod
    async def probe(cls, host: str, port: int) -> str:
        """Open a short session and return the device serial number."""
        async with cls.oneshot(host, port) as client:
            return await client.get_value("DEVICE get serialNumber", timeout=8)
