"""Switch entities: phantom power, mixer mutes, and mixer routing crosspoints."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TesiraConfigEntry
from .entity import TesiraEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TesiraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        TesiraSwitch(coordinator, spec)
        for spec in coordinator.specs
        if spec.platform == "switch"
    )


class TesiraSwitch(TesiraEntity, SwitchEntity):
    """A boolean Tesira attribute, as an HA switch."""

    @property
    def is_on(self) -> bool | None:
        raw = self.coordinator.data.get(self.spec.token)
        if raw is None:
            return None
        return raw.strip().lower() == "true"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set(self.spec, "true")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set(self.spec, "false")
