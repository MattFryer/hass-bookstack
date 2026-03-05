# Changelog

## [1.4.0] - 2026-03-03
### Added 
- Option to ignore TLS certificate errors when connecting to a BookStack instance using a self-signed or local SSL/TLS certificate.
- Update entity to track if a newer version of BookStack is available. Note that updating BookStack from Home Assistant is not possible and thus is not supported.
- Added the BookStack shelf ID as an attribute to the per shelf sensors (if enabled).
- Added new services:
  - To list all books (optionally filtered by shelf ID). Makes finding BookStack book IDs easier.
  - To list all chapters within a specified book. Makes finding BookStack chapter IDs easier.

## [1.3.2] - 2026-03-01
### Added
- Added support for configuring multiple BookStack instances.
- Added French and German translations.
- Added local brand icons to support changes in Home Assistant 2026.3.0 [https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/).

### Fixed
- Fixed incorrect manifest.json key order.
- Fixed missing CONFIG_SCHEMA definition.

## [1.3.1] - 2026-02-22
### Added
- Added sensor name translations (current only English).

### Fixed
- Fixed connection sensor showing in Home Assistant as sensor instead of binary_sensor.
- Fixed error messages not showing in Home Assistant config dialog.

### Changed
- Validated code against Home Assistant Integration Quality Scale and made multiple changes to codebase to support Gold and Platinum levels.

## [1.3.0] - 2026-02-20
### Added
- Added a Home Assistant action (formerly service) to create a new book in BookStack.
- Added a Home Assistant action (formerly service) to create a new page in BookStack.
- Added a Home Assistant action (formerly service) to append content to an existing page in BookStack.

### Changed
- Updates all code with detailed comments for better maintainability.
## [1.2.1] - 2026-02-19
### Fixed

- Fixed missing icons on some Home Assistant sensors.

## [1.2.0] - 2026-02-18
### Added
- Added users, images, and attachments sensors.
- Added connectivity diagnostic sensor.

### Fixed
- Improved error handling and logging.

### Changed
The integration is now HACS compliant and supports the Home Assistant Silver quality scale.

## [1.0.0] - Not released
### Added
- Initial release providing the following functionality:
  - Basic aggregate sensors.
  - Per-shelf sensors.
  - Last updated page tracking.
  - Config flow with re-authentication.