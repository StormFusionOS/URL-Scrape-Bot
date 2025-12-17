#!/usr/bin/env python3
"""
Standardization Dashboard - Live WebSocket UI for company data standardization

Features:
- Real-time statistics with auto-refresh
- Live batch processing with progress updates
- Manual company editing
- Activity log with websocket updates
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from datetime import datetime
from nicegui import ui, app
from dotenv import load_dotenv

load_dotenv()

from dashboard.standardization_service import (
    StandardizationService,
    StandardizationWorker
)

# Global state
worker = None
stats_container = None
pending_container = None
activity_container = None
log_container = None
progress_container = None


def format_number(n: int) -> str:
    """Format number with commas"""
    return f"{n:,}"


def get_quality_color(score: int) -> str:
    """Get color based on quality score"""
    if score < 30:
        return 'red'
    elif score < 60:
        return 'orange'
    elif score < 80:
        return 'blue'
    return 'green'


@ui.refreshable
def stats_cards():
    """Display statistics cards"""
    stats = StandardizationService.get_statistics()

    with ui.row().classes('w-full gap-4 flex-wrap'):
        # Total
        with ui.card().classes('flex-1 min-w-[180px]'):
            with ui.column().classes('items-center'):
                ui.icon('business', size='xl').classes('text-blue-500')
                ui.label(format_number(stats.get('total', 0))).classes('text-3xl font-bold')
                ui.label('Total Companies').classes('text-gray-500')

        # Completed
        with ui.card().classes('flex-1 min-w-[180px]'):
            with ui.column().classes('items-center'):
                ui.icon('check_circle', size='xl').classes('text-green-500')
                ui.label(format_number(stats.get('completed', 0))).classes('text-3xl font-bold text-green-600')
                ui.label('Completed').classes('text-gray-500')

        # Pending
        with ui.card().classes('flex-1 min-w-[180px]'):
            with ui.column().classes('items-center'):
                ui.icon('pending', size='xl').classes('text-orange-500')
                ui.label(format_number(stats.get('pending', 0))).classes('text-3xl font-bold text-orange-600')
                ui.label('Pending').classes('text-gray-500')

        # Failed
        with ui.card().classes('flex-1 min-w-[180px]'):
            with ui.column().classes('items-center'):
                ui.icon('error', size='xl').classes('text-red-500')
                ui.label(format_number(stats.get('failed', 0))).classes('text-3xl font-bold text-red-600')
                ui.label('Failed').classes('text-gray-500')

    # Progress bar
    with ui.card().classes('w-full mt-4'):
        ui.label('Standardization Progress').classes('font-bold text-lg mb-2')

        total = stats.get('total', 0)
        completed = stats.get('completed', 0)
        pending = stats.get('pending', 0)
        failed = stats.get('failed', 0)

        if total > 0:
            with ui.row().classes('w-full h-8 rounded-lg overflow-hidden bg-gray-200'):
                if completed > 0:
                    pct = (completed / total) * 100
                    ui.element('div').classes('bg-green-500 h-full').style(f'width: {pct}%')
                if failed > 0:
                    pct = (failed / total) * 100
                    ui.element('div').classes('bg-red-500 h-full').style(f'width: {pct}%')
                if pending > 0:
                    pct = (pending / total) * 100
                    ui.element('div').classes('bg-gray-400 h-full').style(f'width: {pct}%')

            with ui.row().classes('gap-6 mt-3 text-sm'):
                with ui.row().classes('items-center gap-1'):
                    ui.element('div').classes('w-4 h-4 bg-green-500 rounded')
                    ui.label(f'Completed: {format_number(completed)}')
                with ui.row().classes('items-center gap-1'):
                    ui.element('div').classes('w-4 h-4 bg-red-500 rounded')
                    ui.label(f'Failed: {format_number(failed)}')
                with ui.row().classes('items-center gap-1'):
                    ui.element('div').classes('w-4 h-4 bg-gray-400 rounded')
                    ui.label(f'Pending: {format_number(pending)}')

            ui.label(f"{stats.get('completion_percent', 0)}% Complete").classes('text-2xl font-bold mt-2 text-green-600')


@ui.refreshable
def pending_companies_list():
    """Display pending companies"""
    companies = StandardizationService.get_pending_companies(limit=15, priority='poor_names')

    if not companies:
        with ui.card().classes('w-full p-8 text-center'):
            ui.icon('check_circle', size='3xl').classes('text-green-500')
            ui.label('All companies standardized!').classes('text-xl mt-2')
        return

    for company in companies:
        with ui.card().classes('w-full mb-2'):
            with ui.row().classes('items-center gap-4 w-full'):
                # Quality score badge
                score = company.get('name_quality_score', 50)
                color = get_quality_color(score)
                ui.badge(str(score), color=color).classes('text-lg px-3 py-1')

                # Company info
                with ui.column().classes('flex-1'):
                    with ui.row().classes('items-center gap-2'):
                        ui.label(company.get('name', 'Unknown')).classes('font-bold text-lg')
                        if company.get('domain'):
                            ui.link(
                                company['domain'],
                                f"https://{company['domain']}",
                                new_tab=True
                            ).classes('text-blue-500 text-sm')

                    with ui.row().classes('text-sm text-gray-500 gap-4'):
                        if company.get('address'):
                            addr = company['address']
                            ui.label(addr[:40] + '...' if len(addr) > 40 else addr)
                        if company.get('phone'):
                            ui.label(company['phone'])

                # Actions
                with ui.row().classes('gap-2'):
                    ui.button(icon='edit', on_click=lambda c=company: open_edit_dialog(c)).props('flat round')
                    ui.button(icon='check', on_click=lambda c=company: mark_complete(c)).props('flat round color=green')
                    ui.button(icon='skip_next', on_click=lambda c=company: skip_company(c)).props('flat round color=orange')


@ui.refreshable
def activity_feed():
    """Display recent activity"""
    activities = StandardizationService.get_recent_activity(limit=10)

    if not activities:
        ui.label('No recent activity').classes('text-gray-500')
        return

    for act in activities:
        with ui.row().classes('w-full items-center gap-2 py-1 border-b'):
            # Status icon
            status = act.get('standardization_status', 'pending')
            if status == 'completed':
                ui.icon('check_circle', size='sm').classes('text-green-500')
            elif status == 'failed':
                ui.icon('error', size='sm').classes('text-red-500')
            else:
                ui.icon('pending', size='sm').classes('text-orange-500')

            # Company name
            name = act.get('standardized_name') or act.get('name', 'Unknown')
            ui.label(name[:30] + '...' if len(name) > 30 else name).classes('flex-1')

            # Source
            source = act.get('standardized_name_source', '')
            if source:
                ui.badge(source, color='blue').classes('text-xs')

            # Time
            if act.get('standardized_at'):
                time_str = act['standardized_at'].strftime('%H:%M:%S') if hasattr(act['standardized_at'], 'strftime') else str(act['standardized_at'])[-8:]
                ui.label(time_str).classes('text-xs text-gray-400')


@ui.refreshable
def worker_log():
    """Display worker log messages"""
    global worker

    if not worker or not worker.log_messages:
        ui.label('No log messages yet...').classes('text-gray-500 text-sm')
        return

    with ui.column().classes('w-full font-mono text-xs'):
        for msg in worker.log_messages[-15:]:
            ui.label(msg).classes('text-gray-700')


def open_edit_dialog(company: dict):
    """Open dialog to edit company"""
    details = StandardizationService.get_company_details(company['id'])
    if not details:
        ui.notify('Company not found', type='negative')
        return

    with ui.dialog() as dialog, ui.card().classes('w-[500px]'):
        ui.label(f"Edit: {details.get('name')}").classes('font-bold text-xl mb-4')

        std_name = ui.input(
            'Standardized Name',
            value=details.get('standardized_name', '')
        ).classes('w-full')

        with ui.row().classes('gap-2 w-full'):
            city = ui.input('City', value=details.get('city', '')).classes('flex-1')
            state = ui.input('State', value=details.get('state', '')).classes('w-20')
            zip_code = ui.input('Zip', value=details.get('zip_code', '')).classes('w-28')

        ui.separator().classes('my-4')

        with ui.row().classes('gap-2 justify-end'):
            ui.button('Cancel', on_click=dialog.close).props('flat')
            ui.button('Save', on_click=lambda: save_edit(
                dialog, details['id'],
                std_name.value, city.value, state.value, zip_code.value
            )).props('color=primary')

    dialog.open()


def save_edit(dialog, company_id, std_name, city, state, zip_code):
    """Save company edits"""
    StandardizationService.update_standardization(
        company_id,
        standardized_name=std_name if std_name else None,
        source='manual',
        confidence=1.0,
        city=city if city else None,
        state=state if state else None,
        zip_code=zip_code if zip_code else None
    )
    ui.notify('Saved!', type='positive')
    dialog.close()
    stats_cards.refresh()
    pending_companies_list.refresh()
    activity_feed.refresh()


def mark_complete(company: dict):
    """Mark company as complete"""
    StandardizationService.mark_status(company['id'], 'completed')
    ui.notify(f"Marked '{company.get('name')}' as complete", type='positive')
    stats_cards.refresh()
    pending_companies_list.refresh()


def skip_company(company: dict):
    """Skip company"""
    StandardizationService.mark_status(company['id'], 'skipped')
    ui.notify(f"Skipped '{company.get('name')}'", type='info')
    stats_cards.refresh()
    pending_companies_list.refresh()


async def run_batch_processing(batch_size: int, progress_label, progress_bar, run_btn, stop_btn):
    """Run batch processing with live updates"""
    global worker

    worker = StandardizationWorker(batch_size=batch_size, headless=True)

    run_btn.disable()
    stop_btn.enable()

    async def update_progress(data):
        processed = data['processed']
        total = data['total']
        current = data['current']

        progress_label.set_text(f"Processing: {current or '...'} ({processed}/{total})")
        progress_bar.set_value(processed / total if total > 0 else 0)

        # Refresh UI components
        worker_log.refresh()
        await asyncio.sleep(0.1)

    try:
        stats = await worker.run_batch(limit=batch_size, progress_callback=update_progress)
        ui.notify(
            f"Batch complete! Processed: {stats['processed']}, Success: {stats['success']}, Failed: {stats['failed']}",
            type='positive'
        )
    except Exception as e:
        ui.notify(f"Error: {str(e)}", type='negative')
    finally:
        run_btn.enable()
        stop_btn.disable()
        progress_label.set_text('Ready')
        progress_bar.set_value(0)

        # Final refresh
        stats_cards.refresh()
        pending_companies_list.refresh()
        activity_feed.refresh()
        worker_log.refresh()


def stop_batch():
    """Stop current batch processing"""
    global worker
    if worker:
        worker.stop()
        ui.notify('Stopping batch...', type='warning')


async def mark_good_names():
    """Mark all good names as complete"""
    count = StandardizationService.bulk_mark_good_names(min_score=80)
    ui.notify(f"Marked {count} companies with good names as complete", type='positive')
    stats_cards.refresh()
    pending_companies_list.refresh()


def refresh_all():
    """Refresh all UI components"""
    stats_cards.refresh()
    pending_companies_list.refresh()
    activity_feed.refresh()
    ui.notify('Refreshed!', type='info')


@ui.page('/')
def main_page():
    """Main dashboard page"""
    # Dark mode
    dark = ui.dark_mode(value=True)

    # Header
    with ui.header().classes('items-center justify-between px-6 bg-blue-800'):
        with ui.row().classes('items-center gap-3'):
            ui.icon('auto_fix_high', size='lg').classes('text-yellow-400')
            ui.label('Standardization Dashboard').classes('text-xl font-bold text-white')

        with ui.row().classes('items-center gap-4'):
            ui.button(icon='refresh', on_click=refresh_all).props('flat round').classes('text-white')
            with ui.row().classes('items-center gap-2'):
                ui.icon('light_mode', size='sm').classes('text-white')
                ui.switch().bind_value(dark, 'value').props('dark')
                ui.icon('dark_mode', size='sm').classes('text-white')

    # Main content
    with ui.column().classes('w-full p-6 gap-6'):
        # Stats section
        with ui.card().classes('w-full'):
            ui.label('Statistics').classes('text-2xl font-bold mb-4')
            stats_cards()

        # Two column layout
        with ui.row().classes('w-full gap-6'):
            # Left column - Batch processing + Pending
            with ui.column().classes('flex-1 gap-4'):
                # Batch processing card
                with ui.card().classes('w-full'):
                    ui.label('Batch Processing').classes('text-xl font-bold mb-4')

                    with ui.row().classes('items-center gap-4 mb-4'):
                        batch_size = ui.number('Batch Size', value=50, min=10, max=200).classes('w-32')
                        run_btn = ui.button('Run Batch', icon='play_arrow')
                        stop_btn = ui.button('Stop', icon='stop').props('color=red')
                        stop_btn.disable()

                    progress_label = ui.label('Ready').classes('text-sm text-gray-500')
                    progress_bar = ui.linear_progress(value=0).classes('w-full')

                    run_btn.on('click', lambda: asyncio.create_task(
                        run_batch_processing(
                            int(batch_size.value),
                            progress_label,
                            progress_bar,
                            run_btn,
                            stop_btn
                        )
                    ))
                    stop_btn.on('click', stop_batch)

                    ui.separator().classes('my-4')

                    # Quick actions
                    ui.label('Quick Actions').classes('font-bold mb-2')
                    with ui.row().classes('gap-2'):
                        ui.button(
                            'Mark Good Names Complete (80+)',
                            icon='done_all',
                            on_click=lambda: asyncio.create_task(mark_good_names())
                        ).props('color=secondary')

                    ui.separator().classes('my-4')

                    # Worker log
                    ui.label('Processing Log').classes('font-bold mb-2')
                    with ui.scroll_area().classes('w-full h-48 bg-gray-100 rounded p-2'):
                        worker_log()

                # Pending companies card
                with ui.card().classes('w-full'):
                    with ui.row().classes('items-center justify-between mb-4'):
                        ui.label('Pending Companies').classes('text-xl font-bold')
                        ui.badge('Worst names first', color='orange')

                    with ui.scroll_area().classes('w-full max-h-[500px]'):
                        pending_companies_list()

            # Right column - Activity feed
            with ui.column().classes('w-80'):
                with ui.card().classes('w-full'):
                    ui.label('Recent Activity').classes('text-xl font-bold mb-4')
                    activity_feed()

    # Footer
    with ui.footer().classes('items-center justify-center px-6 py-2 bg-gray-800'):
        ui.label('Standardization Dashboard v1.0').classes('text-gray-400 text-sm')

    # Auto-refresh timer (every 30 seconds)
    ui.timer(30.0, lambda: [stats_cards.refresh(), activity_feed.refresh()])


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title='Standardization Dashboard',
        host='0.0.0.0',
        port=8082,
        reload=False,
        show=False
    )
