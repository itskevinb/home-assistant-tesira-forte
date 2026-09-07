"""Sensor entities: audio meters, firmware, and fault detail text."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TesiraConfigEntry
from .coordinator import ControlSpec, TesiraForte
from .entity import TesiraEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TesiraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        TesiraMeterSensor(coordinator, spec)
        for spec in coordinator.specs
        if spec.platform == "sensor"
    ]
    entities.append(TesiraFirmwareSensor(coordinator))
    entities.append(TesiraFaultDetailSensor(coordinator))
    async_add_entities(entities)


class TesiraMeterSensor(TesiraEntity, SensorEntity):
    """A Tesira AudioMeter channel level (dB)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: TesiraForte, spec: ControlSpec) -> None:
        super().__init__(coordinator, spec)
        self._attr_native_unit_of_measurement = spec.unit

    @property
    def native_value(self) -> float | None:
        raw = self.coordinator.data.get(self.spec.token)
        if raw is None:
            return None
        try:
            return round(float(raw.strip('"')), 1)
        except ValueError:
            return None


class TesiraFirmwareSensor(TesiraEntity, SensorEntity):
    """Reports the Forte firmware version."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"
    _attr_name = "Firmware"

    def __init__(self, coordinator: TesiraForte) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_firmware"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.firmware

    @property
    def available(self) -> bool:
        return self.coordinator.firmware is not None


class TesiraFaultDetailSensor(TesiraEntity, SensorEntity):
    """Human-readable text of the current device fault list."""

    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Fault detail"

    def __init__(self, coordinator: TesiraForte) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_fault_detail"

    @property
    def native_value(self) -> str:
        return self.coordinator.fault_detail
