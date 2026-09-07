"""Config flow for Biamp Tesira Forte."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import DEFAULT_PORT, DOMAIN
from .ttp import TesiraTTP

_LOGGER = logging.getLogger(__name__)

STEP_USER = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


class TesiraForteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for host/port, probe the serial number, one entry per device."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                serial = await TesiraTTP.probe(
                    user_input[CONF_HOST], user_input[CONF_PORT]
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("probe failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Tesira Forte ({serial})", data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER, errors=errors
        )
