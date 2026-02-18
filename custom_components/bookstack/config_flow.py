from __future__ import annotations

import voluptuous as vol
import aiohttp

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import (
    DOMAIN,
    CONF_URL,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    CONF_SCAN_INTERVAL,
    CONF_PER_SHELF_ENABLED,
    DEFAULT_SCAN_INTERVAL,
)
from .options_flow import BookStackOptionsFlow


class BookStackConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BookStack."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            try:
                if await self._validate_input(user_input):
                    await self.async_set_unique_id(user_input[CONF_URL].rstrip("/"))
                    self._abort_if_unique_id_configured()

                    data = {
                        CONF_URL: user_input[CONF_URL].rstrip("/"),
                        CONF_TOKEN_ID: user_input[CONF_TOKEN_ID],
                        CONF_TOKEN_SECRET: user_input[CONF_TOKEN_SECRET],
                    }
                    options = {
                        CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                        CONF_PER_SHELF_ENABLED: user_input.get(CONF_PER_SHELF_ENABLED, True),
                    }

                    return self.async_create_entry(
                        title=f"BookStack ({data[CONF_URL]})",
                        data=data,
                        options=options,
                    )

            except ConfigEntryAuthFailed:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"

        data_schema = vol.Schema({
            vol.Required(CONF_URL): str,
            vol.Required(CONF_TOKEN_ID): str,
            vol.Required(CONF_TOKEN_SECRET): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            vol.Optional(CONF_PER_SHELF_ENABLED, default=True): bool,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            # Bronze: data_description — give users context for each field.
            description_placeholders={},
        )

    async def async_step_reauth(self, entry_data):
        """Trigger reauth flow for credential updates."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}

        if user_input is not None:
            new_data = {**self._reauth_entry.data, **user_input}
            try:
                if await self._validate_input(new_data):
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry, data=new_data
                    )
                    await self.hass.config_entries.async_reload(
                        self._reauth_entry.entry_id
                    )
                    return self.async_abort(reason="reauth_successful")
            except ConfigEntryAuthFailed:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"

        data_schema = vol.Schema({
            vol.Required(CONF_TOKEN_ID): str,
            vol.Required(CONF_TOKEN_SECRET): str,
        })

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=data_schema,
            errors=errors,
        )

    async def _validate_input(self, data):
        """Validate API credentials by calling /api/system."""
        session = async_get_clientsession(self.hass)
        headers = {"Authorization": f"Token {data[CONF_TOKEN_ID]}:{data[CONF_TOKEN_SECRET]}"}
        url = f"{data[CONF_URL].rstrip('/')}/api/system"
        timeout = aiohttp.ClientTimeout(total=10)

        try:
            async with session.get(url, headers=headers, timeout=timeout) as resp:
                if resp.status == 401:
                    raise ConfigEntryAuthFailed
                if resp.status != 200:
                    return False
                json_data = await resp.json()
                return "version" in json_data
        except ConfigEntryAuthFailed:
            raise
        except aiohttp.ClientError:
            return False

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return BookStackOptionsFlow()