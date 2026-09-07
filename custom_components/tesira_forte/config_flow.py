"""Config + options flow for the Biamp Tesira integration."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
)

from .const import CONF_DESIGN, DEFAULT_DESIGN, DEFAULT_PORT, DOMAIN
from .coordinator import DesignError, validate_design
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
                    title=f"Tesira ({serial})", data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return TesiraForteOptionsFlow()


class TesiraForteOptionsFlow(OptionsFlow):
    """Edit the DSP design (block list) as JSON."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error_detail": ""}
        current = self.config_entry.options.get(CONF_DESIGN) or DEFAULT_DESIGN

        if user_input is not None:
            raw = user_input[CONF_DESIGN]
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as err:
                errors["base"] = "invalid_json"
                placeholders["error_detail"] = str(err)
            else:
                try:
                    validate_design(parsed)
                except DesignError as err:
                    errors["base"] = "invalid_design"
                    placeholders["error_detail"] = str(err)
                else:
                    return self.async_create_entry(
                        title="", data={CONF_DESIGN: parsed}
                    )
            current = raw  # keep what they typed so they can fix it

        default_text = current if isinstance(current, str) else json.dumps(
            current, indent=2
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_DESIGN, default=default_text): TextSelector(
                    TextSelectorConfig(multiline=True)
                )
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )
