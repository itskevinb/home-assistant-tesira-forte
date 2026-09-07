"""Runtime coordinator: owns the TTP session and the mirrored control state."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.core import HomeAssistant, callback

from .const import (
    BLOCK_KINDS,
    FAULT_POLL_INTERVAL,
    GAIN_MAX,
    GAIN_MIN,
    GAIN_STEP,
    LEVEL_MAX,
    LEVEL_MIN,
    LEVEL_STEP,
    METER_RATE_MS,
)
from .ttp import TesiraTTP

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ControlSpec:
    """One HA entity mapped to a Tesira (block, attribute, index-tuple)."""

    platform: str  # number | switch | sensor
    block: str
    attr: str
    idx: tuple[int, ...]
    name: str
    icon: str | None = None
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    mode: str | None = None
    state_class: str | None = None
    rate_ms: int | None = None
    subscribable: bool = True  # AEC/Mic-Line input `gain` is the one that isn't

    @property
    def token(self) -> str:
        return f"{self.block}|{self.attr}|{'_'.join(str(i) for i in self.idx)}"

    @property
    def key(self) -> str:
        return f"{self.block}_{self.attr}_{'_'.join(str(i) for i in self.idx)}"


def _level(block: str, attr: str, idx: tuple[int, ...], name: str) -> ControlSpec:
    return ControlSpec(
        "number", block, attr, idx, name,
        icon="mdi:tune-vertical", unit="dB",
        minimum=LEVEL_MIN, maximum=LEVEL_MAX, step=LEVEL_STEP, mode="slider",
    )


def _switch(block: str, attr: str, idx: tuple[int, ...], name: str,
            icon: str = "mdi:volume-mute") -> ControlSpec:
    return ControlSpec("switch", block, attr, idx, name, icon=icon)


class DesignError(Exception):
    """The configured design list is malformed."""


def validate_design(design: object) -> list[dict]:
    """Type/shape-check a user-supplied design list; raise DesignError if bad."""
    if not isinstance(design, list) or not design:
        raise DesignError("design must be a non-empty list of block objects")
    seen: set[str] = set()
    out: list[dict] = []
    for i, blk in enumerate(design):
        if not isinstance(blk, dict):
            raise DesignError(f"block {i} is not an object")
        tag, kind = blk.get("tag"), blk.get("kind")
        if not isinstance(tag, str) or not tag:
            raise DesignError(f"block {i} is missing a string 'tag'")
        if tag in seen:
            raise DesignError(f"duplicate tag {tag!r}")
        seen.add(tag)
        if kind not in BLOCK_KINDS:
            raise DesignError(
                f"block {tag!r}: kind must be one of {sorted(BLOCK_KINDS)}"
            )
        if kind in ("aecinput", "input", "meter", "level", "mute"):
            n = blk.get("channels")
            if not isinstance(n, int) or not 1 <= n <= 64:
                raise DesignError(f"block {tag!r}: 'channels' must be 1..64")
        else:  # mixers
            for f in ("inputs", "outputs"):
                v = blk.get(f)
                if not isinstance(v, int) or not 1 <= v <= 64:
                    raise DesignError(f"block {tag!r}: '{f}' must be 1..64")
        out.append(blk)
    return out


def build_specs(design: list[dict]) -> list[ControlSpec]:
    """Expand a validated design list into the full entity list."""
    specs: list[ControlSpec] = []
    for blk in design:
        tag, kind = blk["tag"], blk["kind"]
        if kind in ("aecinput", "input"):
            for ch in range(1, blk["channels"] + 1):
                specs.append(ControlSpec(
                    "number", tag, "gain", (ch,), f"{tag} ch{ch} gain",
                    icon="mdi:microphone-settings", unit="dB",
                    minimum=GAIN_MIN, maximum=GAIN_MAX, step=GAIN_STEP, mode="box",
                    subscribable=False,  # AEC/Mic-Line input gain isn't subscribable
                ))
                specs.append(_switch(
                    tag, "phantomPower", (ch,), f"{tag} ch{ch} phantom power",
                    icon="mdi:flash",
                ))
        elif kind == "meter":
            for ch in range(1, blk["channels"] + 1):
                specs.append(ControlSpec(
                    "sensor", tag, "level", (ch,), f"{tag} ch{ch} level",
                    icon="mdi:sine-wave", unit="dB", state_class="measurement",
                    rate_ms=METER_RATE_MS,
                ))
        elif kind == "level":
            for ch in range(1, blk["channels"] + 1):
                specs.append(_level(tag, "level", (ch,), f"{tag} ch{ch} level"))
                specs.append(_switch(tag, "mute", (ch,), f"{tag} ch{ch} mute"))
        elif kind == "mute":
            for ch in range(1, blk["channels"] + 1):
                specs.append(_switch(tag, "mute", (ch,), f"{tag} ch{ch} mute"))
        else:  # standardmixer | matrixmixer
            n_in, n_out = blk["inputs"], blk["outputs"]
            for i in range(1, n_in + 1):
                specs.append(_level(tag, "inputLevel", (i,), f"{tag} in{i} level"))
                specs.append(_switch(tag, "inputMute", (i,), f"{tag} in{i} mute"))
            for o in range(1, n_out + 1):
                lbl = f"{tag} out{o} level" if n_out > 1 else f"{tag} output level"
                specs.append(_level(tag, "outputLevel", (o,), lbl))
                mlbl = f"{tag} out{o} mute" if n_out > 1 else f"{tag} output mute"
                specs.append(_switch(tag, "outputMute", (o,), mlbl))
            for i in range(1, n_in + 1):
                for o in range(1, n_out + 1):
                    if kind == "standardmixer":
                        specs.append(_switch(
                            tag, "crosspoint", (i, o), f"{tag} route {i}→{o}",
                            icon="mdi:call-split",
                        ))
                    else:
                        specs.append(_level(
                            tag, "crosspointLevel", (i, o),
                            f"{tag} crosspoint {i}→{o} level",
                        ))
                        specs.append(_switch(
                            tag, "crosspointLevelState", (i, o),
                            f"{tag} crosspoint {i}→{o} on", icon="mdi:call-split",
                        ))
    return specs


class TesiraForte:
    """Holds the live TTP connection and the current value of every control."""

    def __init__(
        self, hass: HomeAssistant, host: str, port: int, design: list[dict]
    ) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        self.specs = build_specs(design)
        self.serial: str | None = None
        self.firmware: str | None = None
        self.available = False
        self.fault_active = False
        self.fault_detail = "OK"
        self.data: dict[str, str] = {}
        self._listeners: set[Callable[[], None]] = set()
        self._fault_task: asyncio.Task | None = None
        self._reconcile_task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._polled = [s for s in self.specs if not s.subscribable]
        self.ttp = TesiraTTP(
            host, port,
            on_connect=self._on_ttp_connect,
            on_disconnect=self._on_ttp_disconnect,
            publish_cb=self._on_publish,
            fault_cb=self._on_fault,
        )

    # -- setup / teardown --------------------------------------------
    async def async_setup(self) -> None:
        await self.ttp.start()
        # _on_ttp_connect fetches serial/firmware then flips _ready.
        await asyncio.wait_for(self._ready.wait(), timeout=20)
        _LOGGER.info("Tesira Forte SN=%s firmware=%s", self.serial, self.firmware)

    async def async_close(self) -> None:
        for task in (self._fault_task, self._reconcile_task):
            if task:
                task.cancel()
        await self.ttp.stop()

    # -- listeners --------------------------------------------------
    @callback
    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(cb)
        return lambda: self._listeners.discard(cb)

    @callback
    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    # -- TTP callbacks -------------------------------------------
    async def _on_ttp_connect(self) -> None:
        # Nothing else is writing yet, so these replies are unambiguous.
        self.serial = await self.ttp.get_value("DEVICE get serialNumber")
        self.firmware = await self.ttp.get_value("DEVICE get version")
        self._ready.set()
        # 1) Pull the current value of everything with plain gets. These are
        #    serialised request/response and dead reliable; do them before any
        #    subscription so there's no async publish traffic to race with.
        for spec in self.specs:
            await self._get_spec(spec)
            await asyncio.sleep(0.01)
        # 2) Subscribe the attributes that support it, for ongoing changes.
        for spec in self.specs:
            if spec.subscribable:
                await self.ttp.subscribe(
                    spec.block, spec.attr, spec.idx, spec.token, spec.rate_ms
                )
                await asyncio.sleep(0.01)
        self.available = True
        self._notify()
        if self._fault_task is None or self._fault_task.done():
            self._fault_task = self.hass.async_create_background_task(
                self._fault_loop(), name="tesira-fault-poll"
            )
        if self._reconcile_task is None or self._reconcile_task.done():
            self._reconcile_task = self.hass.async_create_background_task(
                self._reconcile_loop(), name="tesira-reconcile"
            )

    async def _get_spec(self, spec: ControlSpec) -> None:
        idx = " ".join(str(i) for i in spec.idx)
        for attempt in (1, 2, 3):
            try:
                value = await self.ttp.get_value(
                    f"{spec.block} get {spec.attr} {idx}", timeout=12
                )
                self.data[spec.token] = value
                _LOGGER.debug("get %s -> %r", spec.token, value)
                return
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("get %s (try %d): %s", spec.token, attempt, err)
                await asyncio.sleep(0.2)

    async def _reconcile_loop(self) -> None:
        """Re-read non-subscribable gain, and backfill any value still missing
        (a get that lost a race with a busy event loop during startup)."""
        while True:
            await asyncio.sleep(30)
            targets = list(self._polled)
            targets += [s for s in self.specs if s.token not in self.data]
            for spec in targets:
                await self._get_spec(spec)
                await asyncio.sleep(0.05)
            self._notify()

    @callback
    def _on_ttp_disconnect(self) -> None:
        self.available = False
        self._notify()

    @callback
    def _on_publish(self, token: str, value: str) -> None:
        self.data[token] = value
        self._notify()

    @callback
    def _on_fault(self, entries: list[tuple[int, str]]) -> None:
        bad = [txt for _fid, txt in entries if txt and "no fault" not in txt.lower()]
        self.fault_active = bool(bad)
        self.fault_detail = "; ".join(bad) if bad else "OK"
        self._notify()

    async def _fault_loop(self) -> None:
        while True:
            try:
                await self.ttp.send("DEVICE get activeFaultList")
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("fault poll send failed: %s", err)
            await asyncio.sleep(FAULT_POLL_INTERVAL)

    # -- writes ------------------------------------------------
    async def async_set(self, spec: ControlSpec, value: str) -> None:
        await self.ttp.set_value(spec.block, spec.attr, spec.idx, value)
        if not spec.subscribable:
            # No publish will come back for gain; read it and push.
            await asyncio.sleep(0.15)
            idx = " ".join(str(i) for i in spec.idx)
            try:
                self.data[spec.token] = await self.ttp.get_value(
                    f"{spec.block} get {spec.attr} {idx}"
                )
                self._notify()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("gain read-back failed: %s", err)
