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
from .discovery import discover

_LOGGER = logging.getLogger(__name__)

STEP_USER = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


def _design_text(design: object) -> str:
    """Render a design list (or already-typed string) for the text box."""
    if isinstance(design, str):
        return design
    return json.dumps(design or DEFAULT_DESIGN, indent=2)


def _parse_design(raw: str) -> tuple[list | None, str, str]:
    """Return (validated_design | None, error_key, error_detail)."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as err:
        return None, "invalid_json", str(err)
    try:
        validate_design(parsed)
    except DesignError as err:
        return None, "invalid_design", str(err)
    return parsed, "", ""


class TesiraForteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for host/port, auto-discover the design, then let the user review it."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._port: int = DEFAULT_PORT
        self._serial: str | None = None
        self._design: list[dict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                serial, design = await discover(
                    user_input[CONF_HOST], user_input[CONF_PORT]
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("connect/discover failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                self._host = user_input[CONF_HOST]
                self._port = user_input[CONF_PORT]
                self._serial = serial
                self._design = design or list(DEFAULT_DESIGN)
                return await self.async_step_design()
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER, errors=errors
        )

    async def async_step_design(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Review / edit the auto-discovered block list before creating the entry."""
        errors: dict[str, str] = {}
        placeholders = {
            "error_detail": "",
            "count": str(len(self._design)),
        }
        current: object = self._design

        if user_input is not None:
            current = user_input[CONF_DESIGN]
            parsed, err_key, detail = _parse_design(current)
            if parsed is None:
                errors["base"] = err_key
                placeholders["error_detail"] = detail
            else:
                return self.async_create_entry(
                    title=f"Tesira ({self._serial})",
                    data={CONF_HOST: self._host, CONF_PORT: self._port},
                    options={CONF_DESIGN: parsed},
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DESIGN, default=_design_text(current)
                ): TextSelector(TextSelectorConfig(multiline=True))
            }
        )
        return self.async_show_form(
            step_id="design",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return TesiraForteOptionsFlow()


class TesiraForteOptionsFlow(OptionsFlow):
    """Edit the DSP design as JSON, or re-pull it from the device."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error_detail": ""}
        current: object = self.config_entry.options.get(CONF_DESIGN) or DEFAULT_DESIGN

        if user_input is not None:
            current = user_input[CONF_DESIGN]
            if user_input.get("rediscover"):
                try:
                    _serial, design = await discover(
                        self.config_entry.data[CONF_HOST],
                        self.config_entry.data.get(CONF_PORT, DEFAULT_PORT),
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("re-discover failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    if design:
                        current = design
                        placeholders["error_detail"] = (
                            f"Re-discovered {len(design)} block(s). "
                            "Review and submit to save."
                        )
                    else:
                        errors["base"] = "cannot_discover"
            else:
                parsed, err_key, detail = _parse_design(current)
                if parsed is None:
                    errors["base"] = err_key
                    placeholders["error_detail"] = detail
                else:
                    return self.async_create_entry(
                        title="", data={CONF_DESIGN: parsed}
                    )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DESIGN, default=_design_text(current)
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional("rediscover", default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )
