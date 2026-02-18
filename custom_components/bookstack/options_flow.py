import voluptuous as vol
from homeassistant import config_entries
from .const import CONF_SCAN_INTERVAL, CONF_PER_SHELF_ENABLED, DEFAULT_SCAN_INTERVAL


class BookStackOptionsFlow(config_entries.OptionsFlow):
    """Options flow for editing scan interval and per-shelf sensors."""

    async def async_step_init(self, user_input=None):
        """Show the options form."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Use existing options or defaults
        scan_interval = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        per_shelf_enabled = self.config_entry.options.get(CONF_PER_SHELF_ENABLED, True)

        data_schema = vol.Schema({
            vol.Required(CONF_SCAN_INTERVAL, default=scan_interval): int,
            vol.Required(CONF_PER_SHELF_ENABLED, default=per_shelf_enabled): bool,
        })

        return self.async_show_form(step_id="init", data_schema=data_schema)
