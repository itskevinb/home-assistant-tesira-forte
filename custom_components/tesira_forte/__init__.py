"""The Biamp Tesira Forte integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DEFAULT_PORT
from .coordinator import TesiraForte

_LOGGER = logging.getLogger(__name__)

type TesiraConfigEntry = ConfigEntry[TesiraForte]

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: TesiraConfigEntry) -> bool:
    """Set up Biamp Tesira Forte from a config entry."""
    coordinator = TesiraForte(
        hass, entry.data[CONF_HOST], entry.data.get(CONF_PORT, DEFAULT_PORT)
    )
    try:
        await coordinator.async_setup()
    except Exception as err:  # noqa: BLE001
        await coordinator.async_close()
        raise ConfigEntryNotReady(
            f"Cannot reach Tesira Forte at {entry.data[CONF_HOST]}: {err}"
        ) from err

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TesiraConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_close()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: TesiraConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
