"""Shared entity base for Tesira Forte entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import ControlSpec, TesiraForte


class TesiraEntity(Entity):
    """Base: wires an entity to the coordinator's push updates."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: TesiraForte, spec: ControlSpec | None = None) -> None:
        self.coordinator = coordinator
        self.spec = spec
        if spec is not None:
            self._attr_unique_id = f"{coordinator.serial}_{spec.key}"
            self._attr_name = spec.name
            if spec.icon:
                self._attr_icon = spec.icon

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.serial or self.coordinator.host)},
            manufacturer="Biamp",
            model="Tesira FORTE",
            name="Tesira Forte",
            sw_version=self.coordinator.firmware,
            configuration_url=f"http://{self.coordinator.host}",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.available

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.add_listener(self.async_write_ha_state))
        # Paint whatever the coordinator already knows (values that arrived
        # before this entity was registered).
        self.async_write_ha_state()
