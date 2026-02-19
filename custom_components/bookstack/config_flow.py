"""Config flow for BookStack integration.

This module defines the configuration flow for the BookStack integration, which allows users to set up and configure the integration 
through the Home Assistant UI rather than manually editing configuration files. The config flow handles user input, validates API 
credentials, and creates config entries that store the necessary information to connect to the BookStack API.
"""

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
    """Handle the initial config flow for BookStack.
    
    Inherits from config_entries.ConfigFlow, the base class for all Home Assistant config flows, and defines the steps for setting up 
    the integration. The main steps are:

    - async_step_user: The initial step where the user provides the necessary information to connect to the BookStack API, such as the 
        URL and API token credentials. This step also validates the input by making a test API call to ensure the credentials are 
        correct. If validation fails, it shows the form again with error messages. If validation succeeds, it creates a config entry 
        with the provided data and options.
    - async_step_reauth: A step that can be triggered when the user needs to update their credentials. This is useful for handling 
        cases where the API credentials are no longer valid or have changed. 
    - _validate_input: A helper method that performs the actual validation of the API credentials by making a request to the BookStack 
        API. This method is called from both the user step and the reauth step to ensure that the provided credentials are valid before 
        creating or updating a config entry.
    - async_get_options_flow: A static method that returns the options flow handler for this integration, allowing users to configure 
        additional options after the initial setup.
    """

    # Tracks the version of the config flow. This can be used to manage migrations if the config flow changes in future versions of the
    # integration. For example, if we add new required fields in the future, we can increment the version and write migration code to 
    # handle upgrading existing config entries. For now, we start at version 1.
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step where the user provides API credentials and configuration.
        
        HA calls this method when the user initiates the setup of the integration through the UI. We show a form to collect the 
        necessary configuration data from the user, such as the BookStack URL and API token credentials. When the user submits the form, 
        we validate the input by making a test API call to the BookStack instance. If validation fails, we show the form again with 
        error messages. If validation succeeds, we create a config entry with the provided data and options.
        """

        # Errors dictionary to hold any validation errors that occur during form submission. This will be passed to the form to display 
        # error messages to the user. The errors map field names to translation keys defined in the translation files (e.g., 
        # "invalid_auth" or "cannot_connect"). The errors appear at the top of the form and/or next to the relevant fields, depending on 
        # how we set up the form schema and error handling.
        errors = {}

        if user_input is not None:
            # The user submitted the form, so we need to validate the input. We call the _validate_input method, which will attempt to 
            # connect to the BookStack API with the provided credentials.
            try:
                if await self._validate_input(user_input):
                    # Use the normalised URL (without trailing slash) as the unique ID for this config entry. This ensures that if the 
                    # user tries to set up the same instance twice, it will be detected and aborted.
                    await self.async_set_unique_id(user_input[CONF_URL].rstrip("/"))
                    self._abort_if_unique_id_configured()

                    # Define the config into two buckets, data and options. Data contains the required information for connecting to 
                    # the API (URL and credentials), while options contain optional settings like scan interval and per-shelf enabled 
                    # status. Options can be changed later through the options flow without needing to re-authenticate, while data 
                    # changes would require re-authentication.
                    data = {
                        CONF_URL: user_input[CONF_URL].rstrip("/"),
                        CONF_TOKEN_ID: user_input[CONF_TOKEN_ID],
                        CONF_TOKEN_SECRET: user_input[CONF_TOKEN_SECRET],
                    }
                    options = {
                        CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                        CONF_PER_SHELF_ENABLED: user_input.get(CONF_PER_SHELF_ENABLED, True),
                    }

                    # Finalise the config entry creation. This will store the config entry in HA's storage and trigger the setup of the 
                    # integration using this config entry. The title of the config entry is set to "BookStack (URL)" for easy 
                    # identification in the HA UI.
                    return self.async_create_entry(
                        title=f"BookStack ({data[CONF_URL]})",
                        data=data,
                        options=options,
                    )

            except ConfigEntryAuthFailed:
                # The API returned a 401 Unauthorized response, which means the credentials are invalid. We add an error to the errors 
                # dictionary with the translation key "invalid_auth".
                errors["base"] = "invalid_auth"
            except Exception:
                # Any other exception (e.g., network error, timeout) is treated as a connection issue. We add an error with the key
                # "cannot_connect".
                errors["base"] = "cannot_connect"

        # Build the Voluptuous schema that describes the form fields. vol.Required means the user must provide a value. vol.Optional 
        # means the field has a sensible default and can be left alone.
        data_schema = vol.Schema({
            vol.Required(CONF_URL): str,
            vol.Required(CONF_TOKEN_ID): str,
            vol.Required(CONF_TOKEN_SECRET): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            vol.Optional(CONF_PER_SHELF_ENABLED, default=True): bool,
        })

        # Render the form to the user. If there were validation errors, they will be displayed on the form. The data_schema defines the 
        # fields that the user needs to fill out.  
        return self.async_show_form(
            step_id="user", # The step_id "user" indicates that this is the initial step of the config flow.
            data_schema=data_schema,
            errors=errors,
            # The description_placeholders can be used to provide additional context or instructions for the user, which can be helpful 
            # for fields that might be confusing. In this case, we don't have any placeholders, but we could add some in the future if 
            # needed (e.g., explaining how to generate API tokens in BookStack).
            description_placeholders={},
        )

    async def async_step_reauth(self, entry_data):
        """Trigger reauth flow for credential updates.
        
        HA triggers this step when the user needs to update their credentials, such as when the API returns a 401 Unauthorized response. 
        This shows a "Repair required notification in HA and allows the user to update their credentials without needing to delete and 
        re-add the integration. The flow is similar to the user step, but it pre-fills the form with existing data and updates the 
        existing config entry instead of creating a new one.
        """
        # Return the config entry that needs to be re-authenticated.
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        # Immediately advance to the reauth_confirm step, which will show the form to update credentials. 
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Handle the step where the user confirms new credentials for re-authentication.

        We only ask for the API token ID and secret, since the URL is unlikely to change and is needed to validate the credentials.   
        """
        errors = {}

        if user_input is not None:
            new_data = {**self._reauth_entry.data, **user_input}
            try:
                if await self._validate_input(new_data):
                    # If validation is successful, we update the existing config entry with the new credentials.
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry, data=new_data
                    )
                    # Reload the integration to apply changes. This will cause the coordinator to be re-instantiated with the new 
                    # credentials and all entities to be updated accordingly.
                    await self.hass.config_entries.async_reload(
                        self._reauth_entry.entry_id
                    )
                    # We then abort the flow with a reason of "reauth_successful" to indicate that the re-authentication process is 
                    # complete.
                    return self.async_abort(reason="reauth_successful")
            except ConfigEntryAuthFailed:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"

        # The minimal form for re-authentication only includes the token ID and secret, since the URL is needed to validate the 
        # credentials and is not expected to change.
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
        """Validate API credentials by calling the BookStack API
        
        Calls the "/api/system" endpoint which requires authentication and returns system information. If we get a successful response 
        and can parse the expected data, we consider the credentials valid. If we get a 401 response, we raise ConfigEntryAuthFailed to 
        indicate invalid credentials. For any other exceptions (e.g., network issues), we return False to indicate a connection problem.
        """
        session = async_get_clientsession(self.hass)

        # BookStack API uses token-based authentication where the token ID and secret are combined in the Authorization header. 
        headers = {"Authorization": f"Token {data[CONF_TOKEN_ID]}:{data[CONF_TOKEN_SECRET]}"}
        # The URL for the system endpoint, using the configured base URL. We ensure there is no trailing slash on the base URL to avoid 
        # issues with double slashes in the final URL.
        url = f"{data[CONF_URL].rstrip('/')}/api/system"
        # Define a short timeout so the form doesn't hang for too long if there are connection issues. 
        timeout = aiohttp.ClientTimeout(total=10)

        try:
            async with session.get(url, headers=headers, timeout=timeout) as resp: # Make the HTTP GET request to the API
                if resp.status == 401:
                    # The API explicitly rejected the credentials
                    raise ConfigEntryAuthFailed
                if resp.status != 200:
                    # Any other non-success status code is treated as a connection issue
                    return False
                # Get the response JSON and check if it contains the expected "version" field, which indicates we successfully 
                # authenticated and got a valid response from the API.
                json_data = await resp.json()
                return "version" in json_data
        except ConfigEntryAuthFailed:
            raise # Let the caller handle this specific exception to show an "invalid_auth" error message
        except aiohttp.ClientError:
            # Handle any network level errors (e.g., connection refused, DNS failure) as a connection issue
            return False

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow handler.
        
        HA calls this when the user clicks on the "Options" button for the config entry in the HA UI. This should return an instance of 
        BookStackOptionsFlow, which handles the options editing UI defined in options_flow.py. By separating the options flow into its own 
        class, we keep the config flow focused on initial setup and credential validation, while the options flow can handle additional 
        settings that can be changed after setup.
        """
        return BookStackOptionsFlow()