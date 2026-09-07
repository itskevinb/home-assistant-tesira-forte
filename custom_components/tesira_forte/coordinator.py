"""Runtime coordinator: owns the TTP session and the mirrored control state."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.core import HomeAssistant, callback

from .const import (
    DESIGN,
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
    subscribable: bool = True  # AecInput `gain` is the one attribute that isn't

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


def build_specs() -> list[ControlSpec]:
    """Expand DESIGN into the full entity list."""
    specs: list[ControlSpec] = []
    for block, spec in DESIGN.items():
        kind = spec["kind"]
        if kind == "aecinput":
            for ch in range(1, spec["channels"] + 1):
                specs.append(ControlSpec(
                    "number", block, "gain", (ch,), f"AEC input {ch} gain",
                    icon="mdi:microphone-settings", unit="dB",
                    minimum=GAIN_MIN, maximum=GAIN_MAX, step=GAIN_STEP, mode="box",
                    subscribable=False,
                ))
                specs.append(_switch(
                    block, "phantomPower", (ch,), f"AEC input {ch} phantom power",
                    icon="mdi:flash",
                ))
        elif kind == "meter":
            for ch in range(1, spec["channels"] + 1):
                specs.append(ControlSpec(
                    "sensor", block, "level", (ch,), f"Meter {ch} level",
                    icon="mdi:sine-wave", unit="dB", state_class="measurement",
                    rate_ms=METER_RATE_MS,
                ))
        elif kind in ("standardmixer", "matrixmixer"):
            n_in, n_out = spec["inputs"], spec["outputs"]
            mix = "Mixer 1" if block == "Mixer1" else "Mixer 2"
            for i in range(1, n_in + 1):
                specs.append(_level(block, "inputLevel", (i,), f"{mix} input {i} level"))
                specs.append(_switch(block, "inputMute", (i,), f"{mix} input {i} mute"))
            for o in range(1, n_out + 1):
                label = f"{mix} output {o} level" if n_out > 1 else f"{mix} output level"
                specs.append(_level(block, "outputLevel", (o,), label))
                mlabel = f"{mix} output {o} mute" if n_out > 1 else f"{mix} output mute"
                specs.append(_switch(block, "outputMute", (o,), mlabel))
            for i in range(1, n_in + 1):
                for o in range(1, n_out + 1):
                    if kind == "standardmixer":
                        specs.append(_switch(
                            block, "crosspoint", (i, o), f"{mix} route {i}→{o}",
                            icon="mdi:call-split",
                        ))
                    else:
                        specs.append(_level(
                            block, "crosspointLevel", (i, o),
                            f"{mix} crosspoint {i}→{o} level",
                        ))
                        specs.append(_switch(
                            block, "crosspointLevelState", (i, o),
                            f"{mix} crosspoint {i}→{o} on", icon="mdi:call-split",
                        ))
    return specs


class TesiraForte:
    """Holds the live TTP connection and the current value of every control."""

    def __init__(self, hass: HomeAssistant, host: str, port: int) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        self.specs = build_specs()
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
