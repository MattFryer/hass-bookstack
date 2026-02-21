"""Constants for BookStack integration.

This file contains constants used across the BookStack integration, such as configuration keys, default values, and other fixed data. 
By centralizing these constants, we can avoid hardcoding values throughout the codebase, making it easier to maintain and update the 
integration in the future.
"""

# The domain of the integration. Must be equal to the name of the integration folder.
DOMAIN = "bookstack"

# The HA platforms that this integration uses.
PLATFORMS = ["sensor", "binary_sensor"]

# Configuration keys
# These are the authentication keys that users will use in their configuration.yaml or through the UI when setting up the integration.
# They can only be set at setup time and cannot be changed through options, as changing them would require re-authentication.
CONF_URL = "url" # Base URL of the BookStack instance, e.g., "https://bookstack.mydomain.com"
CONF_TOKEN_ID = "token_id" # BookStack API token ID (acts like a username)
CONF_TOKEN_SECRET = "token_secret" # BookStack API token secret (acts like a password)

# Options keys
# These are the keys for optional settings that users can configure through the options flow after the integration is set up.
# They can be changed at any time without needing to re-authenticate, as they do not affect the connection to the BookStack API.
CONF_SCAN_INTERVAL = "scan_interval" # How often to update the data from BookStack, in seconds.
CONF_PER_SHELF_ENABLED = "per_shelf_enabled" # Whether to create individual sensors for each shelf in BookStack.

# Default values for options
# These are the default values for the options if the user does not specify them during setup or through the options flow.
DEFAULT_SCAN_INTERVAL = 300

# Action (service) constants
# These constants represent the names of the services (actions) that this integration provides. They should match the top-level keys 
# in services.yaml and the names used in async_register() in __init__.
ACTION_CREATE_BOOK = "create_book"
ACTION_CREATE_PAGE = "create_page"
ACTION_APPEND_PAGE = "append_page"