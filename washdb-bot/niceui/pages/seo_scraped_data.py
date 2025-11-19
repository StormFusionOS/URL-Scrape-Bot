"""
Scraped Data Viewer Page
Comprehensive dashboard to view all SEO data collected by the scraper
"""

from nicegui import ui
from niceui.components.glass_card import glass_card, section_title, divider
from niceui.components.data_tables import (
    metric_card, competitors_table, url_queue_table,
    job_history_table, backlinks_table, changes_table, format_datetime
)
from niceui.layout import page_layout
from niceui.services.scraper_db_service import (
    get_overview_stats, get_competitors_list, get_url_queue_status,
    get_crawl_jobs_summary, get_recent_changes, get_backlinks_summary,
    get_backlink_stats, check_seo_analytics_data, reset_crawling_urls_to_pending
)


def create_page():
    """Create the scraped data viewer page"""

    # State management
    state = {
        'active_tab': 'overview',
        'url_status_filter': None,
        'url_node_filter': None,
    }

    # UI references for refresh
    ui_refs = {
        'overview_container': None,
        'competitors_container': None,
        'urls_container': None,
        'jobs_container': None,
        'backlinks_container': None,
    }

    def load_overview():
        """Load overview tab data"""
        if ui_refs['overview_container']:
            ui_refs['overview_container'].clear()

        with ui_refs['overview_container']:
            stats = get_overview_stats()

            if not stats:
                ui.label('Unable to load overview statistics').classes('text-negative p-4')
                return

            # Stats grid
            with ui.grid(columns=4).classes('w-full gap-4'):
                metric_card(
                    'Total Competitors',
                    stats.get('total_competitors', 0),
                    'Tracked domains',
                    'business'
                )
                metric_card(
                    'Total URLs',
                    stats.get('total_urls', 0),
                    'In queue',
                    'link'
                )
                metric_card(
                    'Backlinks',
                    stats.get('total_backlinks', 0),
                    'Discovered',
                    'trending_up'
                )
                metric_card(
                    'Last Crawl',
                    format_datetime(stats.get('last_crawl_time')),
                    'Most recent',
                    'schedule'
                )

            # URL Status Breakdown
            if stats.get('url_status'):
                section_title('URL Status Distribution', icon='pie_chart', classes='mt-6')
                with glass_card():
                    with ui.row().classes('w-full gap-6 items-center'):
                        # Stats list
                        with ui.column().classes('flex-1'):
                            for status, count in stats['url_status'].items():
                                with ui.row().classes('items-center justify-between w-full'):
                                    ui.label(status.upper()).classes('text-sm glass-text-secondary')
                                    ui.badge(str(count)).props(f'color={get_status_color(status)}')

                        # Pie chart (if we had charting library)
                        with ui.column().classes('flex-1'):
                            total_urls = sum(stats['url_status'].values())
                            for status, count in stats['url_status'].items():
                                pct = (count / total_urls * 100) if total_urls > 0 else 0
                                ui.label(f"{status}: {pct:.1f}%").classes('text-xs glass-text-secondary')

            # Crawl Job Status
            if stats.get('job_status'):
                section_title('Crawl Job Status', icon='work', classes='mt-6')
                with glass_card():
                    with ui.row().classes('w-full gap-4'):
                        for status, count in stats['job_status'].items():
                            with ui.column().classes('items-center p-3 flex-1'):
                                ui.label(str(count)).classes('text-3xl font-bold glass-text-primary')
                                ui.label(status.upper()).classes('text-xs glass-text-secondary')

    def load_competitors():
        """Load competitors tab data"""
        if ui_refs['competitors_container']:
            ui_refs['competitors_container'].clear()

        with ui_refs['competitors_container']:
            competitors = get_competitors_list(limit=100)

            if not competitors:
                ui.label('No competitors found in the database').classes('text-sm glass-text-secondary p-4')
                return

            section_title(f'Competitors ({len(competitors)})', icon='business')

            with glass_card():
                competitors_table(competitors)

            # Recent changes section
            changes = get_recent_changes(limit=20)
            if changes:
                section_title('Recent Content Changes', icon='change_circle', classes='mt-6')
                with glass_card():
                    changes_table(changes)

    def load_urls():
        """Load URL queue tab data"""
        if ui_refs['urls_container']:
            ui_refs['urls_container'].clear()

        with ui_refs['urls_container']:
            # Filters
            section_title('URL Queue', icon='list')

            with glass_card():
                with ui.row().classes('w-full gap-4 items-end mb-4'):
                    with ui.column().classes('flex-1'):
                        ui.label('Filter by Status').classes('text-sm glass-text-secondary mb-1')
                        status_filter = ui.select(
                            options=['All', 'pending', 'crawling', 'completed', 'failed'],
                            value='All'
                        ).classes('w-full').props('outlined dense')

                    with ui.column().classes('flex-1'):
                        ui.label('Filter by Node Type').classes('text-sm glass-text-secondary mb-1')
                        node_filter = ui.select(
                            options=['All', 'local', 'national'],
                            value='All'
                        ).classes('w-full').props('outlined dense')

                    def apply_filters():
                        status = None if status_filter.value == 'All' else status_filter.value
                        node = None if node_filter.value == 'All' else node_filter.value
                        state['url_status_filter'] = status
                        state['url_node_filter'] = node
                        load_urls()

                    ui.button('Apply Filters', icon='filter_list', on_click=apply_filters).props('color=primary')

            # Reset button section
            section_title('URL Management', icon='settings', classes='mt-6')
            with glass_card():
                with ui.row().classes('w-full gap-4 items-center justify-between'):
                    with ui.column():
                        ui.label('Reset Stuck URLs').classes('text-sm font-bold glass-text-primary')
                        ui.label('Reset URLs from "crawling" status back to "pending" to allow the scraper to process them again').classes('text-xs glass-text-secondary')

                    with ui.row().classes('gap-2 items-center'):
                        reset_count = ui.number(value=100, min=1, max=1000, step=10).props('outlined dense suffix="URLs"').classes('w-32')

                        def reset_urls():
                            count = int(reset_count.value)
                            result = reset_crawling_urls_to_pending(limit=count)

                            if result.get('success'):
                                ui.notify(result['message'], type='positive', position='top')
                            else:
                                ui.notify(result['message'], type='negative', position='top')

                            # Refresh the URL list after reset
                            load_urls()

                        ui.button('Reset Crawling URLs', icon='refresh', on_click=reset_urls).props('color=warning')

            # URL table
            section_title('URLs', icon='link', classes='mt-4')
            with glass_card():
                urls = get_url_queue_status(
                    status_filter=state['url_status_filter'],
                    node_type_filter=state['url_node_filter'],
                    limit=100
                )
                url_queue_table(urls)

                if urls:
                    ui.label(f'Showing {len(urls)} URLs').classes('text-xs glass-text-secondary mt-2')

    def load_jobs():
        """Load crawl jobs tab data"""
        if ui_refs['jobs_container']:
            ui_refs['jobs_container'].clear()

        with ui_refs['jobs_container']:
            section_title('Recent Crawl Jobs', icon='work_history')

            jobs = get_crawl_jobs_summary(limit=50)

            with glass_card():
                job_history_table(jobs)

                if jobs:
                    ui.label(f'Showing {len(jobs)} most recent jobs').classes('text-xs glass-text-secondary mt-2')

    def load_backlinks():
        """Load backlinks tab data"""
        if ui_refs['backlinks_container']:
            ui_refs['backlinks_container'].clear()

        with ui_refs['backlinks_container']:
            # Backlink stats
            stats = get_backlink_stats()

            if stats:
                with ui.grid(columns=4).classes('w-full gap-4 mb-6'):
                    metric_card(
                        'Total Backlinks',
                        stats.get('total_backlinks', 0),
                        'All links',
                        'link'
                    )
                    metric_card(
                        'Unique Domains',
                        stats.get('unique_domains', 0),
                        'Referring domains',
                        'language'
                    )
                    metric_card(
                        'Alive Links',
                        stats.get('alive_count', 0),
                        f"{stats.get('dead_count', 0)} dead",
                        'check_circle'
                    )
                    dofollow_count = stats.get('rel_breakdown', {}).get('dofollow', 0)
                    total = stats.get('total_backlinks', 1)
                    ratio = (dofollow_count / total * 100) if total > 0 else 0
                    metric_card(
                        'Dofollow Ratio',
                        f"{ratio:.1f}%",
                        f"{dofollow_count} dofollow",
                        'trending_up'
                    )

            # Backlinks table
            section_title('Backlinks', icon='link', classes='mt-6')
            backlinks = get_backlinks_summary(limit=100)

            with glass_card():
                backlinks_table(backlinks)

                if backlinks:
                    ui.label(f'Showing {len(backlinks)} backlinks').classes('text-xs glass-text-secondary mt-2')

    def get_status_color(status: str) -> str:
        """Get color for status"""
        colors = {
            'completed': 'positive',
            'running': 'info',
            'pending': 'warning',
            'failed': 'negative',
            'crawling': 'info'
        }
        return colors.get(status.lower(), 'grey')

    def refresh_data():
        """Refresh current tab data"""
        if state['active_tab'] == 'overview':
            load_overview()
        elif state['active_tab'] == 'competitors':
            load_competitors()
        elif state['active_tab'] == 'urls':
            load_urls()
        elif state['active_tab'] == 'jobs':
            load_jobs()
        elif state['active_tab'] == 'backlinks':
            load_backlinks()

    with page_layout('Scraped Data Viewer', 'View SEO data collected by the scraper', show_refresh=True, refresh_callback=refresh_data):

        # Tab navigation
        with glass_card():
            with ui.tabs().classes('w-full') as tabs:
                overview_tab = ui.tab('overview', label='Overview', icon='dashboard')
                competitors_tab = ui.tab('competitors', label='Competitors', icon='business')
                urls_tab = ui.tab('urls', label='URL Queue', icon='list')
                jobs_tab = ui.tab('jobs', label='Crawl Jobs', icon='work')
                backlinks_tab = ui.tab('backlinks', label='Backlinks', icon='link')

        # Tab panels
        with ui.tab_panels(tabs, value='overview').classes('w-full mt-4'):
            # Overview panel
            with ui.tab_panel('overview'):
                ui_refs['overview_container'] = ui.column().classes('w-full gap-4')
                load_overview()

            # Competitors panel
            with ui.tab_panel('competitors'):
                ui_refs['competitors_container'] = ui.column().classes('w-full gap-4')
                load_competitors()

            # URLs panel
            with ui.tab_panel('urls'):
                ui_refs['urls_container'] = ui.column().classes('w-full gap-4')
                load_urls()

            # Jobs panel
            with ui.tab_panel('jobs'):
                ui_refs['jobs_container'] = ui.column().classes('w-full gap-4')
                load_jobs()

            # Backlinks panel
            with ui.tab_panel('backlinks'):
                ui_refs['backlinks_container'] = ui.column().classes('w-full gap-4')
                load_backlinks()

        # Auto-refresh timer (every 30 seconds for live updates)
        ui.timer(30.0, refresh_data)
