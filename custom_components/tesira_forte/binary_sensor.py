"""Binary sensor: device fault state."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TesiraConfigEntry
from .coordinator import TesiraForte
from .entity import TesiraEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TesiraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([TesiraFaultSensor(entry.runtime_data)])


class TesiraFaultSensor(TesiraEntity, BinarySensorEntity):
    """On when the Forte reports one or more active faults."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Fault"

    def __init__(self, coordinator: TesiraForte) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_fault"

    @property
    def is_on(self) -> bool:
        return self.coordinator.fault_active
