# SERP Monitor GUI Integration

## Quick Integration

To add the SERP monitor to your SEO dashboard, add these lines to `niceui/pages/seo_dashboard.py`:

```python
# At the top with other imports
from niceui.widgets.serp_monitor import get_serp_monitor

# In the content() function where you want the monitor to appear
@ui.page('/seo')
def seo_dashboard():
    # ... existing code ...

    # Add SERP Monitor section
    with ui.column().classes("w-full gap-4"):
        ui.label("SERP Scraper Monitor").classes("text-2xl font-bold mb-4")
        monitor = get_serp_monitor()
        monitor.render()

    # ... rest of dashboard ...
```

## Standalone Page

Or create a dedicated SERP monitor page in `niceui/pages/serp_monitor_page.py`:

```python
from nicegui import ui
from niceui.widgets.serp_monitor import get_serp_monitor

@ui.page('/serp-monitor')
def serp_monitor_page():
    ui.label("SERP Scraper Real-Time Monitor").classes("text-3xl font-bold mb-6")

    monitor = get_serp_monitor()
    monitor.render()
```

## Features

The SERP monitor widget provides:

- **Real-time service status** with auto-refresh every 5 seconds
- **Progress tracking** (cycle number, companies scraped, CAPTCHAs encountered)
- **Statistics cards** (total snapshots, today's count, our rankings, average position)
- **Recent scrapes table** showing last 10 SERP searches
- **Service controls** (view logs, restart service)

## Auto-Refresh

The widget automatically refreshes every 5 seconds using NiceGUI's `ui.timer()`.
No manual websocket setup needed - it's built-in!

## Database Requirements

The monitor requires these tables (already created by SERP scraper):
- `serp_snapshots`
- `serp_results`
- `search_queries`

## Customization

Adjust the refresh interval in `serp_monitor.py`:

```python
# Change this line:
self.timer = ui.timer(5.0, self.update_display)

# To refresh every 10 seconds:
self.timer = ui.timer(10.0, self.update_display)
```

## Troubleshooting

If the monitor shows "STOPPED":
1. Check service status: `sudo systemctl status washbot-serp-scraper`
2. View logs: `sudo journalctl -u washbot-serp-scraper -f`
3. Restart: `sudo systemctl restart washbot-serp-scraper`

If no data appears:
1. Wait for first scrape (takes 30-60 minutes)
2. Check progress file: `cat .serp_scraper_progress.json`
3. Verify database tables exist
