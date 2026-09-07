"""Number entities: AEC input gain and every mixer fader / crosspoint level."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
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
    async_add_entities(
        TesiraNumber(coordinator, spec)
        for spec in coordinator.specs
        if spec.platform == "number"
    )


class TesiraNumber(TesiraEntity, NumberEntity):
    """A Tesira level / gain, as an HA number."""

    def __init__(self, coordinator: TesiraForte, spec: ControlSpec) -> None:
        super().__init__(coordinator, spec)
        self._attr_native_min_value = spec.minimum
        self._attr_native_max_value = spec.maximum
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_mode = NumberMode(spec.mode) if spec.mode else NumberMode.AUTO

    @property
    def native_value(self) -> float | None:
        raw = self.coordinator.data.get(self.spec.token)
        if raw is None:
            return None
        try:
            value = float(raw.strip('"'))
        except ValueError:
            return None
        return round(value) if self.spec.attr == "gain" else round(value, 1)

    async def async_set_native_value(self, value: float) -> None:
        if self.spec.attr == "gain":
            payload = str(int(round(value)))
        else:
            payload = f"{value:.2f}"
        await self.coordinator.async_set(self.spec, payload)
