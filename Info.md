# BookStack Home Assistant Integration

Integrate your BookStack instance with Home Assistant to monitor content statistics and track updates.

## Features

✨ **Aggregate Statistics**
- **Shelves**: Total number of shelves
- **Books**: Total number of books
- **Chapters**: Total number of chapters
- **Pages**: Total number of pages
- **Users**: Total number of registered users
- **Images**: Total number of images in the gallery
- **Attachments**: Total number of file attachments

📚 **Per-Shelf Monitoring**

For each shelf in your BookStack instance, the following sensors will be created:
- **{Shelf Name} Books**: Number of books on this shelf
- **{Shelf Name} Chapters**: Number of chapters across all books on this shelf
- **{Shelf Name} Pages**: Number of pages across all books on this shelf

⏰ **Additional Sensors**

- **Last Updated Page**: Timestamp of the most recently updated page, with additional attributes:
  - `page_name`: Name of the updated page
  - `page_id`: BookStack page ID of the page
  - `updated_by`: Name of the user who updated it
  - `updated_by_id`: BookStack user ID of the user who updated it
  - `page_url`: URL linking directly to the page
- **Connectivity**: Diagnostic sensor showing BookStack availability

## Quick Start

1. Get your API credentials from BookStack (Profile → API Tokens)
2. Add the integration via Settings → Devices & Services
3. Enter your BookStack URL and API credentials
4. Configure polling interval and per-shelf sensors

## Configuration

All settings are configurable via the UI:
- **Scan interval**: How often to poll (default: 300 seconds)
- **Per-shelf sensors**: Enable/disable individual shelf monitoring

**Note**: Per-shelf sensors can be resource-intensive with many shelves. Consider a longer scan interval or disabling this feature if you have >20 shelves.

## Support

[Documentation](https://github.com/MattFryer/hass-bookstack) | [Issues](https://github.com/MattFryer/hass-bookstack/issues)