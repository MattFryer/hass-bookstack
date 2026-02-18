# BookStack Home Assistant Integration

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Integration-Blue?logo=homeassistant&logoColor=%23fff&color=%2303a9f4)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom-Blue?logo=homeassistantcommunitystore&logoColor=%23fff&color=%2303a9f4)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/v/release/MattFryer/hass-bookstack)](https://github.com/MattFryer/hass-bookstack/releases/latest)
[![GitHub license](https://img.shields.io/github/license/MattFryer/hass-bookstack.svg?logo=gnu&logoColor=ffffff)](https://github.com/MattFryer/hass-bookstack/blob/master/LICENSE)
![GitHub commit activity](https://img.shields.io/github/commit-activity/t/MattFryer/hass-bookstack)
![GitHub last commit](https://img.shields.io/github/last-commit/MattFryer/hass-bookstack)
![GitHub contributors](https://img.shields.io/github/contributors/MattFryer/hass-bookstack)
![GitHub Issues or Pull Requests](https://img.shields.io/github/issues-pr/MattFryer/hass-bookstack)
![GitHub Issues or Pull Requests](https://img.shields.io/github/issues/MattFryer/hass-bookstack)
![GitHub Repo stars](https://img.shields.io/github/stars/MattFryer/hass-bookstack)
![GitHub forks](https://img.shields.io/github/forks/MattFryer/hass-bookstack)
![GitHub watchers](https://img.shields.io/github/watchers/MattFryer/hass-bookstack)

Integrate your BookStack instance with Home Assistant to monitor content statistics and track updates.

If you just want to show your appreciation, you can sponsor the project or send a one off donation using the links below:

[<img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" height="37px" style="margin: 5px"/>](https://buymeacoffee.com/mattfryer)
[<img src="assets/readme/github-sponsors-button.svg" height="37px" style="margin: 5px"/>](https://github.com/sponsors/MattFryer)

## Features

The integration provides the following sensors in Home Assistant:

### Aggregate Sensors

- **Shelves**: Total number of shelves
- **Books**: Total number of books
- **Chapters**: Total number of chapters
- **Pages**: Total number of pages
- **Users**: Total number of registered users
- **Images**: Total number of images in the gallery
- **Attachments**: Total number of file attachments

### Per-Shelf Sensors (when enabled)

For each shelf in your BookStack instance, the following sensors will be created:
- **{Shelf Name} Books**: Number of books on this shelf
- **{Shelf Name} Chapters**: Number of chapters across all books on this shelf
- **{Shelf Name} Pages**: Number of pages across all books on this shelf

### Additional Sensors

- **Last Updated Page**: Timestamp of the most recently updated page, with additional attributes:
  - `page_name`: Name of the updated page
  - `page_id`: BookStack page ID of the page
  - `updated_by`: Name of the user who updated it
  - `updated_by_id`: BookStack user ID of the user who updated it
  - `page_url`: URL linking directly to the page
- **Connectivity**: Diagnostic sensor showing BookStack availability

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the 3 dots in the top right corner
3. Select "Custom repositories"
4. Add the URL: `https://github.com/MattFryer/hass-bookstack`
5. Select category: "Integration"
6. Click "Add"
7. Click "Download" on the BookStack integration
8. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/bookstack` folder to your `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration via **Settings → Devices & Services → Add Integration → BookStack**

## Configuration

### Initial Setup

1. Navigate to **Settings → Devices & Services → Add Integration**
2. Search for "BookStack"
3. Enter your BookStack details:
   - **BookStack URL**: The base URL of your BookStack instance (e.g., `https://bookstack.example.com`)
   - **API Token ID**: Found under your BookStack profile → API Tokens
   - **API Token Secret**: Found under your BookStack profile → API Tokens
   - **Scan Interval**: How often to check BookStack for updates (default: 300 seconds)
   - **Enable per-shelf sensors**: Creates individual sensors for each shelf (default: enabled)

## Automation Examples
The following are example Home Assistant automations which you can use:

### Notify when content is updated
Notify when someone updates a page in BookStack:
```yaml
automation:
  - alias: "BookStack Page Updated"
    trigger:
      - platform: state
        entity_id: sensor.bookstack_last_updated_page
    action:
      - service: notify.mobile_app
        data:
          title: "BookStack Updated"
          message: >
            {{ trigger.to_state.attributes.page_name }} 
            was updated by {{ trigger.to_state.attributes.updated_by }}
```

### Alert when BookStack goes offline
Send an alert when BookStack goes offline:
```yaml
automation:
  - alias: "BookStack Offline Alert"
    trigger:
      - platform: state
        entity_id: binary_sensor.bookstack_connectivity
        to: "off"
        for:
          minutes: 5
    action:
      - service: notify.mobile_app
        data:
          title: "BookStack Offline"
          message: "BookStack server is unreachable"
```

### Track content growth
Send a weekly report on Monday with stats about BookStack:
```yaml
automation:
  - alias: "BookStack Weekly Report"
    trigger:
      - platform: time
        at: "09:00:00"
    condition:
      - condition: time
        weekday:
          - mon
    action:
      - service: notify.mobile_app
        data:
          title: "BookStack Weekly Stats"
          message: >
            Total Content:
            {{ states('sensor.bookstack_pages') }} pages
            {{ states('sensor.bookstack_books') }} books
            {{ states('sensor.bookstack_shelves') }} shelves
```

## Troubleshooting

### Integration won't load

- Verify your BookStack URL is correct and includes the protocol (`https://` or `http://`)
- Ensure your API token has sufficient permissions and hasn't expired
- Check Home Assistant logs for detailed error messages

### Sensors show "Unavailable"

- BookStack instance may be offline or unreachable
- Check the **Connectivity** diagnostic sensor
- Verify network connectivity from Home Assistant to BookStack
- Check Home Assistant logs for connection errors

### Per-shelf sensors not appearing

- Ensure "Enable per-shelf sensors" is checked in the integration options
- Check that you have at least one shelf created in BookStack
- Reload the integration after creating new shelves

### Slow updates or timeouts

- Increase the scan interval if you have many shelves (each shelf requires multiple API calls)
- Per-shelf sensors with many books can be resource-intensive
- Consider disabling per-shelf sensors if you have >20 shelves

## API Rate Limiting

Per-shelf sensors can be resource-intensive if you have lots of shelves in your BookStack instance. The integration makes the following API calls per update:

- **Base stats**: 5 calls (system, shelves, books, chapters, pages, users, images, attachments)
- **Last updated page**: 2 calls (list + detail)
- **Per shelf** (if enabled): 2-3 calls per shelf (list + detail + book details)

Consider a longer scan interval or disabling this feature if you have more than 20 shelves.

## Support

- [Report an issue](https://github.com/MattFryer/hass-bookstack/issues)
- [BookStack Documentation](https://www.bookstackapp.com/docs/)
- [Home Assistant Community](https://community.home-assistant.io/)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Credits

- [BookStack](https://www.bookstackapp.com/) - The awesome knowledge base platform
- [Home Assistant](https://www.home-assistant.io/) - Open source home automation