"""The Biamp Tesira integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType

from .const import CONF_DESIGN, DEFAULT_DESIGN, DEFAULT_PORT, DOMAIN
from .coordinator import DesignError, TesiraForte, validate_design

_LOGGER = logging.getLogger(__name__)

type TesiraConfigEntry = ConfigEntry[TesiraForte]

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

# Optional YAML fallback used as the default design when a config entry has no
# design set in its options. Handy for a single-Forte install / packages.
CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Optional(CONF_DESIGN): list})},
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    yaml_design = (config.get(DOMAIN) or {}).get(CONF_DESIGN)
    if yaml_design is not None:
        try:
            yaml_design = validate_design(yaml_design)
        except DesignError as err:
            _LOGGER.error("Invalid tesira_forte: design in configuration.yaml: %s", err)
            yaml_design = None
    hass.data.setdefault(DOMAIN, {})["yaml_design"] = yaml_design
    return True


def _resolve_design(hass: HomeAssistant, entry: TesiraConfigEntry) -> list[dict]:
    """Options flow wins, then configuration.yaml, then the shipped default."""
    if raw := entry.options.get(CONF_DESIGN):
        try:
            return validate_design(raw)
        except DesignError as err:
            _LOGGER.error("Invalid design in options, falling back: %s", err)
    if yaml_design := hass.data.get(DOMAIN, {}).get("yaml_design"):
        return yaml_design
    return list(DEFAULT_DESIGN)


async def async_setup_entry(hass: HomeAssistant, entry: TesiraConfigEntry) -> bool:
    """Set up Biamp Tesira from a config entry."""
    coordinator = TesiraForte(
        hass,
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        _resolve_design(hass, entry),
    )
    try:
        await coordinator.async_setup()
    except Exception as err:  # noqa: BLE001
        await coordinator.async_close()
        raise ConfigEntryNotReady(
            f"Cannot reach Tesira at {entry.data[CONF_HOST]}: {err}"
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
