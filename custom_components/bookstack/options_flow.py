""" Options flow for the BookStack integration.

The options flow lets users edit optional settings for the integration after it has been set up. In this case, we allow users to change 
the scan interval (how often the integration polls the BookStack API) and whether to enable the creation of per-shelf sensors. These 
options can be updated without needing to re-authenticate or change the connection settings, so we handle them separately from the main 
config flow.
"""
import voluptuous as vol
from homeassistant import config_entries
from .const import CONF_SCAN_INTERVAL, CONF_PER_SHELF_ENABLED, DEFAULT_SCAN_INTERVAL


class BookStackOptionsFlow(config_entries.OptionsFlow):
    """Options flow for editing scan interval and per-shelf sensors.
    
    Inherrits OptionsFlow, the HA base class for handling options editing. We implement the async_step_init method to show a form with 
    the options we want to allow the user to edit. The form is pre-filled with the current options values (or defaults if not set).
    """

    async def async_step_init(self, user_input=None):
        """Show the options form and handle user input
        
        Like the config flow, this method is called twice: once with user_input=None to show the form, and then again with user_input 
        containing the submitted options when the user submits the form. We don't bother validating the input currently as the options 
        are basic.
        """
        if user_input is not None:
            # The user has submitted the form, so we save the options. We create a new data dictionary that merges the existing config 
            # entry data with the new user input options.
            return self.async_create_entry(title="", data=user_input)

        # Read the current options to pre-fill the form. We use the options from the config entry, falling back to defaults if not set.
        scan_interval = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        per_shelf_enabled = self.config_entry.options.get(CONF_PER_SHELF_ENABLED, True)

        # Build the form schema using voluptuous. We require both options and set their default values to the current settings, so the 
        # form is pre-filled.
        data_schema = vol.Schema({
            vol.Required(CONF_SCAN_INTERVAL, default=scan_interval): int,
            vol.Required(CONF_PER_SHELF_ENABLED, default=per_shelf_enabled): bool,
        })

        return self.async_show_form(step_id="init", data_schema=data_schema)
