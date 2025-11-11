"""
Dashboard page - main overview with KPIs and charts organized in tabs.
"""

import random
from datetime import datetime, timedelta
from nicegui import ui
from ..backend_facade import backend
from ..widgets.kpi import create_kpi_card
from ..theme import COLORS


def create_sparkline_chart(title: str, data: list, color: str = None):
    """Create a tiny sparkline chart."""
    if color is None:
        color = COLORS['accent']

    options = {
        'backgroundColor': 'transparent',
        'grid': {'left': 0, 'right': 0, 'top': 0, 'bottom': 0},
        'xAxis': {
            'type': 'category',
            'show': False,
            'data': list(range(len(data)))
        },
        'yAxis': {'type': 'value', 'show': False},
        'series': [{
            'type': 'line',
            'data': data,
            'smooth': True,
            'lineStyle': {'width': 2, 'color': color},
            'areaStyle': {'color': f'{color}33'},
            'showSymbol': False
        }]
    }

    with ui.column().classes('flex-1'):
        ui.label(title).classes('text-sm text-gray-400 mb-1')
        ui.echart(options).classes('w-full h-16')


def create_stacked_bar_chart(series_data: list, categories: list):
    """Create a stacked bar chart."""
    options = {
        'backgroundColor': 'transparent',
        'textStyle': {'color': '#ffffff'},
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {'type': 'shadow'},
            'backgroundColor': 'rgba(0, 0, 0, 0.8)',
            'borderColor': COLORS['accent'],
            'textStyle': {'color': '#ffffff'}
        },
        'legend': {
            'data': [s['name'] for s in series_data],
            'textStyle': {'color': '#ffffff'}
        },
        'grid': {
            'left': '3%',
            'right': '4%',
            'bottom': '10%',
            'containLabel': True
        },
        'xAxis': {
            'type': 'category',
            'data': categories,
            'axisLine': {'lineStyle': {'color': COLORS['accent']}},
            'axisLabel': {'color': '#ffffff', 'rotate': 45}
        },
        'yAxis': {
            'type': 'value',
            'axisLine': {'lineStyle': {'color': COLORS['accent']}},
            'axisLabel': {'color': '#ffffff'},
            'splitLine': {'lineStyle': {'color': 'rgba(167, 139, 250, 0.2)'}}
        },
        'series': [
            {
                'name': s['name'],
                'type': 'bar',
                'stack': 'total',
                'data': s['data'],
                'itemStyle': {'color': s.get('color', COLORS['primary'])}
            }
            for s in series_data
        ]
    }

    return ui.echart(options).classes('w-full h-80')


def create_line_chart_custom(series_data: list, categories: list, title: str = ""):
    """Create a custom line chart."""
    options = {
        'backgroundColor': 'transparent',
        'title': {
            'text': title,
            'textStyle': {'color': '#ffffff', 'fontSize': 14}
        } if title else {},
        'textStyle': {'color': '#ffffff'},
        'tooltip': {
            'trigger': 'axis',
            'backgroundColor': 'rgba(0, 0, 0, 0.8)',
            'borderColor': COLORS['accent'],
            'textStyle': {'color': '#ffffff'}
        },
        'legend': {
            'data': [s['name'] for s in series_data],
            'textStyle': {'color': '#ffffff'}
        },
        'grid': {
            'left': '3%',
            'right': '4%',
            'bottom': '10%',
            'containLabel': True
        },
        'xAxis': {
            'type': 'category',
            'boundaryGap': False,
            'data': categories,
            'axisLine': {'lineStyle': {'color': COLORS['accent']}},
            'axisLabel': {'color': '#ffffff', 'rotate': 45}
        },
        'yAxis': {
            'type': 'value',
            'axisLine': {'lineStyle': {'color': COLORS['accent']}},
            'axisLabel': {'color': '#ffffff'},
            'splitLine': {'lineStyle': {'color': 'rgba(167, 139, 250, 0.2)'}}
        },
        'series': [
            {
                'name': s['name'],
                'type': 'line',
                'smooth': True,
                'data': s['data'],
                'lineStyle': {'width': 2, 'color': s.get('color', COLORS['accent'])},
                'itemStyle': {'color': s.get('color', COLORS['accent'])}
            }
            for s in series_data
        ]
    }

    return ui.echart(options).classes('w-full h-80')


def create_bar_chart_custom(categories: list, data: list, title: str = "", color: str = None):
    """Create a horizontal bar chart."""
    if color is None:
        color = COLORS['accent']

    options = {
        'backgroundColor': 'transparent',
        'title': {
            'text': title,
            'textStyle': {'color': '#ffffff', 'fontSize': 14}
        } if title else {},
        'textStyle': {'color': '#ffffff'},
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {'type': 'shadow'},
            'backgroundColor': 'rgba(0, 0, 0, 0.8)',
            'borderColor': COLORS['accent'],
            'textStyle': {'color': '#ffffff'}
        },
        'grid': {
            'left': '3%',
            'right': '4%',
            'bottom': '3%',
            'containLabel': True
        },
        'xAxis': {
            'type': 'value',
            'axisLine': {'lineStyle': {'color': COLORS['accent']}},
            'axisLabel': {'color': '#ffffff'},
            'splitLine': {'lineStyle': {'color': 'rgba(167, 139, 250, 0.2)'}}
        },
        'yAxis': {
            'type': 'category',
            'data': categories,
            'axisLine': {'lineStyle': {'color': COLORS['accent']}},
            'axisLabel': {'color': '#ffffff'}
        },
        'series': [{
            'type': 'bar',
            'data': data,
            'itemStyle': {'color': color}
        }]
    }

    return ui.echart(options).classes('w-full h-96')


def create_donut_chart_custom(name: str, value: float, color: str = None):
    """Create a donut chart showing percentage."""
    if color is None:
        color = COLORS['positive']

    options = {
        'backgroundColor': 'transparent',
        'textStyle': {'color': '#ffffff'},
        'tooltip': {
            'trigger': 'item',
            'backgroundColor': 'rgba(0, 0, 0, 0.8)',
            'borderColor': COLORS['accent'],
            'textStyle': {'color': '#ffffff'}
        },
        'series': [{
            'type': 'pie',
            'radius': ['50%', '70%'],
            'avoidLabelOverlap': False,
            'label': {
                'show': True,
                'position': 'center',
                'formatter': f'{value:.1f}%',
                'fontSize': 24,
                'fontWeight': 'bold',
                'color': color
            },
            'data': [
                {'value': value, 'name': name, 'itemStyle': {'color': color}},
                {'value': 100 - value, 'name': 'Missing', 'itemStyle': {'color': '#333333'}}
            ]
        }]
    }

    return ui.echart(options).classes('w-full h-64')


def dashboard_page():
    """Render dashboard page with tabs."""
    ui.label('Dashboard').classes('text-3xl font-bold mb-4')

    # Get KPIs from backend
    kpis = backend.kpis()

    # Create tabs
    with ui.tabs().classes('w-full') as tabs:
        overview_tab = ui.tab('Overview', icon='dashboard')
        discovery_tab = ui.tab('Discovery', icon='search')
        scrape_tab = ui.tab('Scrape', icon='refresh')
        quality_tab = ui.tab('Data Quality', icon='check_circle')

    with ui.tab_panels(tabs, value=overview_tab).classes('w-full'):
        # OVERVIEW TAB
        with ui.tab_panel(overview_tab):
            # System Status Section - Eye-Catching
            with ui.card().classes('w-full mb-6').style('background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border: none;'):
                ui.label('🖥️ System Status').classes('text-2xl font-bold mb-4 text-white')

                # Import discovery state to show real-time info
                from .discover import discovery_state

                with ui.row().classes('w-full gap-4'):
                    # Active Discovery Status
                    with ui.card().classes('flex-1 p-4').style('background: rgba(255, 255, 255, 0.15); backdrop-filter: blur(10px);'):
                        ui.label('Discovery Status').classes('text-sm text-gray-200 mb-2')
                        if discovery_state.running:
                            with ui.row().classes('items-center gap-2'):
                                ui.spinner(size='sm', color='positive')
                                ui.label('RUNNING').classes('text-2xl font-bold text-green-300')
                        else:
                            ui.badge('IDLE', color='grey').classes('text-xl p-3')

                    # Last Run Time
                    with ui.card().classes('flex-1 p-4').style('background: rgba(255, 255, 255, 0.15); backdrop-filter: blur(10px);'):
                        ui.label('Last Run').classes('text-sm text-gray-200 mb-2')
                        if discovery_state.last_run_summary:
                            timestamp = discovery_state.last_run_summary['timestamp'][:19]
                            ui.label(timestamp).classes('text-lg font-semibold text-white')
                        else:
                            ui.label('No runs yet').classes('text-lg text-gray-300 italic')

                    # Database Status
                    with ui.card().classes('flex-1 p-4').style('background: rgba(255, 255, 255, 0.15); backdrop-filter: blur(10px);'):
                        ui.label('Database').classes('text-sm text-gray-200 mb-2')
                        db_status = backend.check_database_connection()
                        if db_status['connected']:
                            with ui.row().classes('items-center gap-2'):
                                ui.icon('check_circle', size='md', color='positive')
                                ui.label('Connected').classes('text-lg font-semibold text-green-300')
                        else:
                            with ui.row().classes('items-center gap-2'):
                                ui.icon('error', size='md', color='negative')
                                ui.label('Error').classes('text-lg font-semibold text-red-300')

                    # Total Processed
                    with ui.card().classes('flex-1 p-4').style('background: rgba(255, 255, 255, 0.15); backdrop-filter: blur(10px);'):
                        ui.label('Total Companies').classes('text-sm text-gray-200 mb-2')
                        ui.label(str(kpis['total_companies'])).classes('text-2xl font-bold text-white')

            # KPI Cards
            with ui.row().classes('w-full gap-4 mb-6'):
                create_kpi_card('Total Companies', kpis['total_companies'], 'business', 'info')
                create_kpi_card('With Email', kpis['with_email'], 'email', 'positive')
                create_kpi_card('With Phone', kpis['with_phone'], 'phone', 'positive')
                create_kpi_card('Updated (30d)', kpis['updated_30d'], 'update', 'warning')
                create_kpi_card('New (7d)', kpis['new_7d'], 'fiber_new', 'accent')

        # DISCOVERY TAB
        with ui.tab_panel(discovery_tab):
            ui.label('Discovery Metrics').classes('text-2xl font-bold mb-4')

            # Line chart: URLs found per day (30d)
            with ui.card().classes('w-full mb-4'):
                ui.label('URLs Found per Day (30 days)').classes('text-lg font-bold mb-2')

                # TODO: Replace with real data from database queries
                # SELECT DATE(created_at), COUNT(*) FROM companies WHERE created_at >= NOW() - INTERVAL '30 days' GROUP BY DATE(created_at)
                days_30 = [(datetime.now() - timedelta(days=i)).strftime('%m/%d') for i in range(29, -1, -1)]
                urls_per_day = [random.randint(10, 50) for _ in range(30)]

                create_line_chart_custom(
                    [{'name': 'URLs Found', 'data': urls_per_day, 'color': COLORS['accent']}],
                    days_30
                )

            # Bar chart: Top 10 categories/states (7d)
            with ui.row().classes('w-full gap-4'):
                with ui.card().classes('flex-1'):
                    ui.label('Top 10 Categories (7 days)').classes('text-lg font-bold mb-2')

                    # TODO: Replace with real data
                    # SELECT source, COUNT(*) FROM companies WHERE created_at >= NOW() - INTERVAL '7 days' GROUP BY source ORDER BY COUNT(*) DESC LIMIT 10
                    top_categories = [f'Category {i+1}' for i in range(10)]
                    category_counts = sorted([random.randint(5, 30) for _ in range(10)], reverse=True)

                    create_bar_chart_custom(top_categories, category_counts, color=COLORS['primary'])

                with ui.card().classes('flex-1'):
                    ui.label('Top 10 States (7 days)').classes('text-lg font-bold mb-2')

                    # TODO: Replace with real data
                    states = ['CA', 'TX', 'FL', 'NY', 'PA', 'OH', 'IL', 'GA', 'NC', 'MI']
                    state_counts = sorted([random.randint(10, 50) for _ in range(10)], reverse=True)

                    create_bar_chart_custom(states, state_counts, color=COLORS['accent'])

        # SCRAPE TAB
        with ui.tab_panel(scrape_tab):
            ui.label('Scraping Metrics').classes('text-2xl font-bold mb-4')

            # Stacked bar: Successes vs errors by day (14d)
            with ui.card().classes('w-full mb-4'):
                ui.label('Scraping Results (14 days)').classes('text-lg font-bold mb-2')

                # TODO: Replace with real data
                # SELECT DATE(last_updated), SUM(CASE WHEN email IS NOT NULL THEN 1 ELSE 0 END) as success, COUNT(*) - SUM(CASE WHEN email IS NOT NULL THEN 1 ELSE 0 END) as errors FROM companies WHERE last_updated >= NOW() - INTERVAL '14 days' GROUP BY DATE(last_updated)
                days_14 = [(datetime.now() - timedelta(days=i)).strftime('%m/%d') for i in range(13, -1, -1)]
                successes = [random.randint(20, 50) for _ in range(14)]
                errors = [random.randint(2, 10) for _ in range(14)]

                create_stacked_bar_chart(
                    [
                        {'name': 'Successes', 'data': successes, 'color': COLORS['positive']},
                        {'name': 'Errors', 'data': errors, 'color': COLORS['negative']}
                    ],
                    days_14
                )

            # Line: Median scrape time
            with ui.card().classes('w-full'):
                ui.label('Median Scrape Time (14 days)').classes('text-lg font-bold mb-2')

                # TODO: Replace with real data from scraping logs
                # This would require storing scrape duration in the database
                days_14 = [(datetime.now() - timedelta(days=i)).strftime('%m/%d') for i in range(13, -1, -1)]
                median_times = [random.uniform(2.0, 5.0) for _ in range(14)]

                create_line_chart_custom(
                    [{'name': 'Median Time (seconds)', 'data': median_times, 'color': COLORS['warning']}],
                    days_14
                )

        # DATA QUALITY TAB
        with ui.tab_panel(quality_tab):
            ui.label('Data Quality Metrics').classes('text-2xl font-bold mb-4')

            # Donut charts: Presence % for email/phone/service area
            with ui.card().classes('w-full mb-4'):
                ui.label('Field Presence').classes('text-lg font-bold mb-4')

                with ui.row().classes('w-full gap-4'):
                    # Calculate percentages
                    total = kpis['total_companies'] or 1  # Avoid division by zero
                    email_pct = (kpis['with_email'] / total * 100) if total > 0 else 0
                    phone_pct = (kpis['with_phone'] / total * 100) if total > 0 else 0

                    # TODO: Add service_area to KPIs
                    # For now, use a placeholder
                    service_area_pct = random.uniform(30, 70)

                    with ui.card().classes('flex-1 p-4'):
                        ui.label('Email Presence').classes('text-center text-lg font-semibold mb-2')
                        create_donut_chart_custom('Has Email', email_pct, COLORS['positive'])

                    with ui.card().classes('flex-1 p-4'):
                        ui.label('Phone Presence').classes('text-center text-lg font-semibold mb-2')
                        create_donut_chart_custom('Has Phone', phone_pct, COLORS['info'])

                    with ui.card().classes('flex-1 p-4'):
                        ui.label('Service Area Presence').classes('text-center text-lg font-semibold mb-2')
                        create_donut_chart_custom('Has Service Area', service_area_pct, COLORS['warning'])

            # Bar: Invalid email/phone counts
            with ui.card().classes('w-full'):
                ui.label('Data Validation Issues').classes('text-lg font-bold mb-4')

                # TODO: Add validation queries to backend
                # This would require validation functions for emails and phones
                validation_issues = ['Invalid Email Format', 'Invalid Phone Format', 'Missing Website', 'Duplicate Entries']
                issue_counts = [random.randint(1, 20) for _ in range(4)]

                create_bar_chart_custom(
                    validation_issues,
                    issue_counts,
                    'Issues Found',
                    COLORS['negative']
                )

    # Footer note about TODOs
    with ui.card().classes('w-full mt-4').style('background: rgba(139, 92, 246, 0.1)'):
        ui.label('📊 Dashboard Metrics').classes('text-lg font-semibold mb-2')
        ui.label(
            'Note: Some metrics currently use sample data. To enable real-time metrics:'
        ).classes('text-sm text-gray-300 mb-2')
        with ui.column().classes('ml-4 gap-1'):
            ui.label('• Add time-series queries to backend_facade.py for daily/weekly trends').classes('text-xs text-gray-400')
            ui.label('• Store scrape duration in database for performance tracking').classes('text-xs text-gray-400')
            ui.label('• Add validation functions for email/phone quality checks').classes('text-xs text-gray-400')
            ui.label('• Implement category/state tracking for discovery metrics').classes('text-xs text-gray-400')
