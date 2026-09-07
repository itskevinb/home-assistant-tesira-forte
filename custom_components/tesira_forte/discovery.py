"""Reconstruct a Tesira's controllable design by probing it over TTP.

``SESSION get aliases`` lists every instance tag in the running design; from
there each block is classified by trying a few cheap ``get`` commands and
seeing which attributes it accepts. Blocks that expose none of the attributes
this integration knows how to drive (EQ / filter / generator / AEC-processing
blocks) are skipped. Discovery errs toward *including* a block - the user
reviews and trims the result in the setup step.
"""

from __future__ import annotations

import logging
import re

from .ttp import TesiraTTP, TTPError

_LOGGER = logging.getLogger(__name__)

_ALIAS_RE = re.compile(r'"([^"]+)"')

# Aliases that are always present and never a DSP control block.
_SKIP_TAGS = frozenset({"DEVICE", "SESSION"})


async def _try(client: TesiraTTP, cmd: str) -> str | None:
    """Return the ``get`` payload, or None if the attribute isn't supported."""
    try:
        return await client.get_value(cmd, timeout=5)
    except (TTPError, TimeoutError):
        return None
    except Exception:  # noqa: BLE001
        _LOGGER.debug("probe %r raised", cmd, exc_info=True)
        return None


def _as_int(value: str | None) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _classify(client: TesiraTTP, tag: str) -> dict | None:
    """Best-effort {tag, kind, size...} for one instance tag, or None to skip.

    Only blocks that clearly accept an attribute set this integration can drive
    are returned; a crossover / router (inputs+outputs but no crosspoints) or an
    EQ (a stray ``gain`` but no ``phantomPower``/``level``) is skipped rather
    than mapped to something that would half-work.
    """
    # --- mixer? inputs + outputs AND a real crosspoint attribute --
    n_in = _as_int(await _try(client, f"{tag} get numInputs"))
    n_out = _as_int(await _try(client, f"{tag} get numOutputs"))
    if n_in and n_out:
        if await _try(client, f"{tag} get crosspointLevel 1 1") is not None:
            return {"tag": tag, "kind": "matrixmixer", "inputs": n_in, "outputs": n_out}
        if await _try(client, f"{tag} get crosspoint 1 1") is not None:
            return {"tag": tag, "kind": "standardmixer", "inputs": n_in, "outputs": n_out}
        return None  # crossover, router, etc. - no crosspoints to expose

    # --- channel block? gain+phantom / level+mute / level / mute --
    n_ch = _as_int(await _try(client, f"{tag} get numChannels"))
    if n_ch:
        has_gain = await _try(client, f"{tag} get gain 1") is not None
        has_phantom = await _try(client, f"{tag} get phantomPower 1") is not None
        has_level = await _try(client, f"{tag} get level 1") is not None
        has_mute = await _try(client, f"{tag} get mute 1") is not None
        if has_gain and has_phantom:
            kind = "aecinput"  # also covers a Mic/Line Input block
        elif has_level and has_mute:
            kind = "level"
        elif has_level:
            kind = "meter"
        elif has_mute:
            kind = "mute"
        else:
            return None  # EQ / filter / generator - nothing drivable here
        return {"tag": tag, "kind": kind, "channels": n_ch}

    return None


async def discover_design(client: TesiraTTP) -> list[dict]:
    """Probe a connected client and return a design list (possibly empty)."""
    raw = await _try(client, "SESSION get aliases")
    if not raw:
        _LOGGER.warning("Tesira returned no alias list; cannot auto-discover")
        return []
    tags = [t for t in _ALIAS_RE.findall(raw) if t not in _SKIP_TAGS]
    _LOGGER.debug("aliases: %s", tags)

    design: list[dict] = []
    for tag in tags:
        block = await _classify(client, tag)
        if block:
            design.append(block)
        else:
            _LOGGER.debug("skipping %s (no drivable attributes)", tag)
    _LOGGER.info(
        "discovered %d controllable block(s) of %d aliases",
        len(design),
        len(tags),
    )
    return design


async def discover(host: str, port: int) -> tuple[str, list[dict]]:
    """Open a one-shot session: return (serial number, discovered design)."""
    async with TesiraTTP.oneshot(host, port) as client:
        serial = await client.get_value("DEVICE get serialNumber", timeout=8)
        design = await discover_design(client)
    return serial, design
