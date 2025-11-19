"""
Scheduler page for managing cron jobs.

Allows users to create, edit, delete, and monitor scheduled crawl jobs.
"""

from nicegui import ui
from ..theme import COLORS
from ..backend_facade import backend
from typing import Optional
import json


# Job type mappings
JOB_TYPE_MAP = {
    'Yellow Pages Crawl': 'yp_crawl',
    'Google Maps Scrape': 'google_maps',
    'Detail Scrape': 'detail_scrape',
    'Database Maintenance': 'db_maintenance'
}

REVERSE_JOB_TYPE_MAP = {v: k for k, v in JOB_TYPE_MAP.items()}


def scheduler_page():
    """Main scheduler page with job management interface."""

    ui.label('Cron Scheduler').classes('text-3xl font-bold mb-6')

    # Header with create button
    with ui.row().classes('w-full items-center mb-4'):
        ui.label('Manage scheduled crawl jobs').classes('text-lg text-gray-400')
        ui.space()
        ui.button('Create New Job', icon='add', color='positive', on_click=lambda: _show_create_job_dialog()).props('outline')

    # Get stats from backend
    stats = backend.get_scheduler_stats()

    # Stats cards
    with ui.row().classes('w-full gap-4 mb-6'):
        # Total jobs
        with ui.card().classes('flex-1'):
            ui.label('Total Jobs').classes('text-sm text-gray-400')
            ui.label(str(stats['total_jobs'])).classes('text-3xl font-bold')

        # Active jobs
        with ui.card().classes('flex-1'):
            ui.label('Active').classes('text-sm text-gray-400')
            ui.label(str(stats['active_jobs'])).classes('text-3xl font-bold text-green-500')

        # Running now
        with ui.card().classes('flex-1'):
            ui.label('Running Now').classes('text-sm text-gray-400')
            ui.label(str(stats.get('running_jobs', 0))).classes('text-3xl font-bold text-blue-500')

        # Failed (last 24h)
        with ui.card().classes('flex-1'):
            ui.label('Failed (24h)').classes('text-sm text-gray-400')
            ui.label(str(stats['failed_24h'])).classes('text-3xl font-bold text-red-500')

    # Jobs table
    jobs = backend.get_scheduled_jobs()

    with ui.card().classes('w-full'):
        ui.label('Scheduled Jobs').classes('text-xl font-bold mb-4')

        if not jobs:
            # Placeholder when no jobs
            with ui.row().classes('w-full items-center p-4'):
                ui.icon('schedule').classes('text-6xl text-gray-600')
                with ui.column().classes('ml-4'):
                    ui.label('No scheduled jobs yet').classes('text-lg text-gray-400')
                    ui.label('Create your first scheduled job to automate crawls').classes('text-sm text-gray-500')
                    ui.button('Create Job', icon='add', on_click=lambda: _show_create_job_dialog()).props('flat').classes('mt-2')
        else:
            # Display jobs as cards
            for job in jobs:
                _render_job_card(job)

    # Execution history section
    logs = backend.get_job_execution_logs()

    with ui.card().classes('w-full mt-6'):
        ui.label('Recent Executions').classes('text-xl font-bold mb-4')

        if not logs:
            with ui.row().classes('w-full items-center p-4'):
                ui.icon('history').classes('text-6xl text-gray-600')
                with ui.column().classes('ml-4'):
                    ui.label('No execution history').classes('text-lg text-gray-400')
                    ui.label('Job execution logs will appear here').classes('text-sm text-gray-500')
        else:
            # Display execution logs
            for log in logs[:10]:  # Show last 10
                _render_execution_log(log)


def _render_job_card(job: dict):
    """Render a single job as a card."""
    with ui.card().classes('w-full mb-2').style('padding: 1rem;'):
        with ui.row().classes('w-full items-center'):
            # Job status indicator
            status_color = 'positive' if job['enabled'] else 'gray'
            ui.badge('ACTIVE' if job['enabled'] else 'DISABLED', color=status_color).classes('mr-2')

            # Job name and type
            with ui.column().classes('flex-1'):
                ui.label(job['name']).classes('text-lg font-bold')
                job_type_display = REVERSE_JOB_TYPE_MAP.get(job['job_type'], job['job_type'])
                ui.label(f"{job_type_display} | {job['schedule_cron']}").classes('text-sm text-gray-400')

            # Last run info
            if job.get('last_run'):
                last_status = job.get('last_status', 'unknown')
                status_icon = 'check_circle' if last_status == 'success' else 'error' if last_status == 'failed' else 'help'
                status_color = 'text-green-500' if last_status == 'success' else 'text-red-500' if last_status == 'failed' else 'text-gray-500'
                with ui.column().classes('mr-4'):
                    ui.label('Last Run').classes('text-xs text-gray-500')
                    with ui.row().classes('items-center gap-1'):
                        ui.icon(status_icon).classes(f'{status_color} text-sm')
                        ui.label(job['last_run'][:19]).classes('text-sm')

            # Action buttons
            with ui.row().classes('gap-2'):
                # Toggle button
                ui.button(
                    icon='pause' if job['enabled'] else 'play_arrow',
                    on_click=lambda j=job: _toggle_job_with_refresh(j['id'], not j['enabled'])
                ).props('flat round dense').tooltip('Enable/Disable')

                # Run now button
                ui.button(
                    icon='play_arrow',
                    on_click=lambda j=job: _run_job_now(j['id'])
                ).props('flat round dense color=positive').tooltip('Run Now')

                # View details button
                ui.button(
                    icon='visibility',
                    on_click=lambda j=job: _show_job_details(j['id'])
                ).props('flat round dense color=primary').tooltip('View Details')

                # Edit button
                ui.button(
                    icon='edit',
                    on_click=lambda j=job: _show_edit_job_dialog(j['id'])
                ).props('flat round dense').tooltip('Edit')

                # Delete button
                ui.button(
                    icon='delete',
                    on_click=lambda j=job: _confirm_delete_job(j['id'], j['name'])
                ).props('flat round dense color=negative').tooltip('Delete')


def _render_execution_log(log: dict):
    """Render a single execution log entry."""
    with ui.card().classes('w-full mb-2').style('padding: 0.75rem;'):
        with ui.row().classes('w-full items-center'):
            # Status icon
            status = log.get('status', 'unknown')
            if status == 'success':
                ui.icon('check_circle').classes('text-green-500 mr-2')
            elif status == 'failed':
                ui.icon('error').classes('text-red-500 mr-2')
            elif status == 'running':
                ui.icon('pending').classes('text-blue-500 mr-2')
            else:
                ui.icon('help').classes('text-gray-500 mr-2')

            # Job info
            with ui.column().classes('flex-1'):
                ui.label(f"Job #{log['job_id']}").classes('text-sm font-bold')
                started = log.get('started_at', 'N/A')
                if started and started != 'N/A':
                    started = started[:19]
                ui.label(f"Started: {started}").classes('text-xs text-gray-400')

            # Duration
            if log.get('duration_seconds'):
                duration = int(log['duration_seconds'])
                minutes = duration // 60
                seconds = duration % 60
                with ui.column().classes('mr-4'):
                    ui.label('Duration').classes('text-xs text-gray-500')
                    ui.label(f"{minutes}m {seconds}s").classes('text-sm')

            # Items processed
            if log.get('items_found') is not None:
                with ui.column():
                    ui.label('Items').classes('text-xs text-gray-500')
                    ui.label(f"{log.get('items_found', 0)} found").classes('text-sm')


def _show_create_job_dialog():
    """Show dialog for creating a new scheduled job."""

    # Form state variables
    form_data = {}

    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
        ui.label('Create Scheduled Job').classes('text-2xl font-bold mb-4')

        # Job name
        ui.label('Job Name').classes('font-semibold mb-2')
        name_input = ui.input(
            label='Enter job name',
            placeholder='e.g., Daily Pressure Washing Crawl'
        ).props('outlined').classes('w-full mb-4')
        form_data['name'] = name_input

        # Job description
        ui.label('Description (Optional)').classes('font-semibold mb-2')
        description_input = ui.textarea(
            label='Enter job description',
            placeholder='Describe what this job does...'
        ).props('outlined').classes('w-full mb-4')
        form_data['description'] = description_input

        # Job type selector
        ui.label('Job Type').classes('font-semibold mb-2')
        job_type_select = ui.select(
            options=list(JOB_TYPE_MAP.keys()),
            value='Yellow Pages Crawl',
            label='Select job type'
        ).props('outlined').classes('w-full mb-4')
        form_data['job_type'] = job_type_select

        # Schedule section
        ui.label('Schedule').classes('text-xl font-bold mt-6 mb-4')

        # Cron expression
        ui.label('Cron Expression').classes('font-semibold mb-2')
        cron_input = ui.input(
            label='Enter cron expression',
            value='0 2 * * *',
            placeholder='0 2 * * * (daily at 2am)'
        ).props('outlined').classes('w-full mb-2')
        form_data['schedule_cron'] = cron_input

        # Schedule presets
        ui.label('Quick Presets').classes('font-semibold mb-2')
        with ui.row().classes('gap-2 mb-4'):
            ui.button('Hourly', icon='schedule', on_click=lambda: _set_schedule(cron_input, '0 * * * *')).props('outline').classes('flex-1')
            ui.button('Daily at 2am', icon='nightlight', on_click=lambda: _set_schedule(cron_input, '0 2 * * *')).props('outline').classes('flex-1')
            ui.button('Weekly (Mon)', icon='event', on_click=lambda: _set_schedule(cron_input, '0 2 * * 1')).props('outline').classes('flex-1')

        ui.label('Format: minute hour day month day_of_week').classes('text-xs text-gray-500 mb-4')

        # Priority
        ui.label('Priority').classes('font-semibold mb-2')
        priority_select = ui.select(
            options=[
                {'label': 'High', 'value': 1},
                {'label': 'Medium', 'value': 2},
                {'label': 'Low', 'value': 3}
            ],
            value=2,
            label='Select priority'
        ).props('outlined').classes('w-full mb-4')
        form_data['priority'] = priority_select

        # Timeout and retries
        with ui.row().classes('w-full gap-4 mb-4'):
            timeout_input = ui.number(
                label='Timeout (minutes)',
                value=60,
                min=1,
                max=1440
            ).props('outlined').classes('flex-1')
            form_data['timeout'] = timeout_input

            retries_input = ui.number(
                label='Max Retries',
                value=3,
                min=0,
                max=10
            ).props('outlined').classes('flex-1')
            form_data['retries'] = retries_input

        # Configuration section (dynamic based on job type)
        ui.label('Configuration').classes('text-xl font-bold mt-6 mb-4')
        ui.label('Job-specific settings').classes('font-semibold mb-2')

        search_term_input = ui.input(
            label='Search Term',
            placeholder='e.g., pressure washing'
        ).props('outlined').classes('w-full mb-4')
        form_data['search_term'] = search_term_input

        location_input = ui.input(
            label='Location',
            placeholder='e.g., Portland, OR'
        ).props('outlined').classes('w-full mb-4')
        form_data['location'] = location_input

        # Enabled checkbox
        enabled_checkbox = ui.checkbox('Enable job immediately', value=True).classes('mb-4')
        form_data['enabled'] = enabled_checkbox

        # Action buttons
        with ui.row().classes('w-full justify-end gap-2 mt-6'):
            ui.button('Cancel', on_click=dialog.close).props('flat')
            ui.button('Create Job', icon='save', color='positive', on_click=lambda: _create_job(dialog, form_data)).props('outline')

    dialog.open()


def _set_schedule(cron_input, cron_expr: str):
    """Set cron expression in input field."""
    cron_input.value = cron_expr


def _create_job(dialog, form_data: dict):
    """Handle job creation."""
    try:
        # Extract values from form
        job_data = {
            'name': form_data['name'].value,
            'description': form_data['description'].value or None,
            'job_type': JOB_TYPE_MAP[form_data['job_type'].value],
            'schedule_cron': form_data['schedule_cron'].value,
            'enabled': form_data['enabled'].value,
            'priority': form_data['priority'].value,
            'timeout_minutes': int(form_data['timeout'].value),
            'max_retries': int(form_data['retries'].value),
            'config': {
                'search_term': form_data['search_term'].value,
                'location': form_data['location'].value,
            },
            'created_by': 'dashboard'
        }

        # Validate required fields
        if not job_data['name']:
            ui.notify('Job name is required', type='negative')
            return

        if not job_data['schedule_cron']:
            ui.notify('Schedule expression is required', type='negative')
            return

        # Create job via backend
        result = backend.create_scheduled_job(job_data)

        if result.get('success'):
            ui.notify(f"Job '{job_data['name']}' created successfully!", type='positive')
            dialog.close()
            # Refresh page to show new job
            ui.navigate.reload()
        else:
            ui.notify(f"Failed to create job: {result.get('message', 'Unknown error')}", type='negative')

    except Exception as e:
        ui.notify(f'Error creating job: {str(e)}', type='negative')
        print(f"Error in _create_job: {e}")
        import traceback
        traceback.print_exc()


def _show_job_details(job_id: int):
    """Show detailed information about a job."""
    jobs = backend.get_scheduled_jobs()
    job = next((j for j in jobs if j['id'] == job_id), None)

    if not job:
        ui.notify('Job not found', type='negative')
        return

    with ui.dialog() as dialog, ui.card().classes('w-full max-w-3xl'):
        ui.label(f'Job Details - {job["name"]}').classes('text-2xl font-bold mb-4')

        # Tabs for different views
        with ui.tabs().classes('w-full') as tabs:
            ui.tab('Overview', icon='info')
            ui.tab('Configuration', icon='settings')
            ui.tab('History', icon='history')

        with ui.tab_panels(tabs, value='Overview').classes('w-full'):
            # Overview panel
            with ui.tab_panel('Overview'):
                with ui.grid(columns=2).classes('w-full gap-4'):
                    # Left column
                    with ui.column():
                        ui.label('Job Information').classes('text-lg font-bold mb-2')
                        ui.label(f"ID: {job['id']}").classes('mb-1')
                        ui.label(f"Type: {REVERSE_JOB_TYPE_MAP.get(job['job_type'], job['job_type'])}").classes('mb-1')
                        ui.label(f"Schedule: {job['schedule_cron']}").classes('mb-1')
                        ui.label(f"Priority: {job['priority']}").classes('mb-1')
                        ui.label(f"Status: {'Active' if job['enabled'] else 'Disabled'}").classes('mb-1')

                    # Right column
                    with ui.column():
                        ui.label('Execution Stats').classes('text-lg font-bold mb-2')
                        ui.label(f"Total Runs: {job.get('total_runs', 0)}").classes('mb-1')
                        ui.label(f"Success: {job.get('success_runs', 0)}").classes('mb-1')
                        ui.label(f"Failed: {job.get('failed_runs', 0)}").classes('mb-1')
                        if job.get('last_run'):
                            ui.label(f"Last Run: {job['last_run'][:19]}").classes('mb-1')
                        if job.get('next_run'):
                            ui.label(f"Next Run: {job['next_run'][:19]}").classes('mb-1')

                # Description
                if job.get('description'):
                    ui.separator().classes('my-4')
                    ui.label('Description').classes('text-lg font-bold mb-2')
                    ui.label(job['description']).classes('text-gray-400')

            # Configuration panel
            with ui.tab_panel('Configuration'):
                ui.label('Job Configuration').classes('text-lg font-bold mb-2')
                config = job.get('config', {})
                if isinstance(config, str):
                    try:
                        config = json.loads(config)
                    except (json.JSONDecodeError, ValueError) as e:
                        logging.debug(f"Failed to parse job config JSON: {e}")
                        config = {}

                if config:
                    for key, value in config.items():
                        ui.label(f"{key}: {value}").classes('mb-1')
                else:
                    ui.label('No configuration set').classes('text-gray-400')

                ui.separator().classes('my-4')
                ui.label('Advanced Settings').classes('text-lg font-bold mb-2')
                ui.label(f"Timeout: {job.get('timeout_minutes', 60)} minutes").classes('mb-1')
                ui.label(f"Max Retries: {job.get('max_retries', 3)}").classes('mb-1')
                ui.label(f"Created: {job.get('created_at', 'N/A')[:19]}").classes('mb-1')
                ui.label(f"Updated: {job.get('updated_at', 'N/A')[:19]}").classes('mb-1')

            # History panel
            with ui.tab_panel('History'):
                ui.label('Execution History').classes('text-lg font-bold mb-4')
                logs = backend.get_job_execution_logs(job_id=job_id)

                if not logs:
                    ui.label('No execution history yet').classes('text-gray-400')
                else:
                    for log in logs:
                        _render_execution_log(log)

        # Action buttons
        with ui.row().classes('w-full justify-end gap-2 mt-6'):
            ui.button('Close', on_click=dialog.close).props('flat')
            ui.button('Edit', icon='edit', on_click=lambda: (dialog.close(), _show_edit_job_dialog(job_id))).props('outline')
            ui.button('Run Now', icon='play_arrow', color='positive', on_click=lambda: _run_job_now(job_id)).props('outline')

    dialog.open()


def _show_edit_job_dialog(job_id: int):
    """Show dialog for editing an existing job."""
    jobs = backend.get_scheduled_jobs()
    job = next((j for j in jobs if j['id'] == job_id), None)

    if not job:
        ui.notify('Job not found', type='negative')
        return

    # Parse config
    config = job.get('config', {})
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except (json.JSONDecodeError, ValueError) as e:
            logging.debug(f"Failed to parse job config JSON for editing: {e}")
            config = {}

    # Form state variables
    form_data = {}

    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
        ui.label(f'Edit Job - {job["name"]}').classes('text-2xl font-bold mb-4')

        # Job name
        ui.label('Job Name').classes('font-semibold mb-2')
        name_input = ui.input(
            label='Enter job name',
            value=job['name']
        ).props('outlined').classes('w-full mb-4')
        form_data['name'] = name_input

        # Job description
        ui.label('Description (Optional)').classes('font-semibold mb-2')
        description_input = ui.textarea(
            label='Enter job description',
            value=job.get('description', '')
        ).props('outlined').classes('w-full mb-4')
        form_data['description'] = description_input

        # Job type selector
        ui.label('Job Type').classes('font-semibold mb-2')
        current_job_type_display = REVERSE_JOB_TYPE_MAP.get(job['job_type'], 'Yellow Pages Crawl')
        job_type_select = ui.select(
            options=list(JOB_TYPE_MAP.keys()),
            value=current_job_type_display,
            label='Select job type'
        ).props('outlined').classes('w-full mb-4')
        form_data['job_type'] = job_type_select

        # Schedule section
        ui.label('Schedule').classes('text-xl font-bold mt-6 mb-4')

        # Cron expression
        ui.label('Cron Expression').classes('font-semibold mb-2')
        cron_input = ui.input(
            label='Enter cron expression',
            value=job['schedule_cron'],
        ).props('outlined').classes('w-full mb-2')
        form_data['schedule_cron'] = cron_input

        # Schedule presets
        ui.label('Quick Presets').classes('font-semibold mb-2')
        with ui.row().classes('gap-2 mb-4'):
            ui.button('Hourly', icon='schedule', on_click=lambda: _set_schedule(cron_input, '0 * * * *')).props('outline').classes('flex-1')
            ui.button('Daily at 2am', icon='nightlight', on_click=lambda: _set_schedule(cron_input, '0 2 * * *')).props('outline').classes('flex-1')
            ui.button('Weekly (Mon)', icon='event', on_click=lambda: _set_schedule(cron_input, '0 2 * * 1')).props('outline').classes('flex-1')

        ui.label('Format: minute hour day month day_of_week').classes('text-xs text-gray-500 mb-4')

        # Priority
        ui.label('Priority').classes('font-semibold mb-2')
        priority_select = ui.select(
            options=[
                {'label': 'High', 'value': 1},
                {'label': 'Medium', 'value': 2},
                {'label': 'Low', 'value': 3}
            ],
            value=job.get('priority', 2),
            label='Select priority'
        ).props('outlined').classes('w-full mb-4')
        form_data['priority'] = priority_select

        # Timeout and retries
        with ui.row().classes('w-full gap-4 mb-4'):
            timeout_input = ui.number(
                label='Timeout (minutes)',
                value=job.get('timeout_minutes', 60),
                min=1,
                max=1440
            ).props('outlined').classes('flex-1')
            form_data['timeout'] = timeout_input

            retries_input = ui.number(
                label='Max Retries',
                value=job.get('max_retries', 3),
                min=0,
                max=10
            ).props('outlined').classes('flex-1')
            form_data['retries'] = retries_input

        # Configuration section
        ui.label('Configuration').classes('text-xl font-bold mt-6 mb-4')

        search_term_input = ui.input(
            label='Search Term',
            value=config.get('search_term', '')
        ).props('outlined').classes('w-full mb-4')
        form_data['search_term'] = search_term_input

        location_input = ui.input(
            label='Location',
            value=config.get('location', '')
        ).props('outlined').classes('w-full mb-4')
        form_data['location'] = location_input

        # Enabled checkbox
        enabled_checkbox = ui.checkbox('Enable job', value=job.get('enabled', True)).classes('mb-4')
        form_data['enabled'] = enabled_checkbox

        # Action buttons
        with ui.row().classes('w-full justify-end gap-2 mt-6'):
            ui.button('Cancel', on_click=dialog.close).props('flat')
            ui.button('Save Changes', icon='save', color='positive', on_click=lambda: _update_job(dialog, job_id, form_data)).props('outline')

    dialog.open()


def _update_job(dialog, job_id: int, form_data: dict):
    """Update an existing job."""
    try:
        # Extract values from form
        job_data = {
            'name': form_data['name'].value,
            'description': form_data['description'].value or None,
            'job_type': JOB_TYPE_MAP[form_data['job_type'].value],
            'schedule_cron': form_data['schedule_cron'].value,
            'enabled': form_data['enabled'].value,
            'priority': form_data['priority'].value,
            'timeout_minutes': int(form_data['timeout'].value),
            'max_retries': int(form_data['retries'].value),
            'config': {
                'search_term': form_data['search_term'].value,
                'location': form_data['location'].value,
            }
        }

        # Validate required fields
        if not job_data['name']:
            ui.notify('Job name is required', type='negative')
            return

        if not job_data['schedule_cron']:
            ui.notify('Schedule expression is required', type='negative')
            return

        # Update job via backend
        result = backend.update_scheduled_job(job_id, job_data)

        if result.get('success'):
            ui.notify(f"Job updated successfully!", type='positive')
            dialog.close()
            # Refresh page
            ui.navigate.reload()
        else:
            ui.notify(f"Failed to update job: {result.get('message', 'Unknown error')}", type='negative')

    except Exception as e:
        ui.notify(f'Error updating job: {str(e)}', type='negative')
        print(f"Error in _update_job: {e}")
        import traceback
        traceback.print_exc()


def _confirm_delete_job(job_id: int, job_name: str):
    """Show confirmation dialog before deleting a job."""
    with ui.dialog() as dialog, ui.card():
        ui.label('Confirm Delete').classes('text-xl font-bold mb-4')
        ui.label(f'Are you sure you want to delete job "{job_name}"?').classes('mb-4')
        ui.label('This action cannot be undone. All execution history will be deleted.').classes('text-sm text-gray-400 mb-4')

        with ui.row().classes('w-full justify-end gap-2'):
            ui.button('Cancel', on_click=dialog.close).props('flat')
            ui.button('Delete', icon='delete', color='negative', on_click=lambda: _delete_job(dialog, job_id)).props('outline')

    dialog.open()


def _delete_job(dialog, job_id: int):
    """Delete a job."""
    try:
        result = backend.delete_scheduled_job(job_id)

        if result.get('success'):
            ui.notify('Job deleted successfully', type='positive')
            dialog.close()
            # Refresh page
            ui.navigate.reload()
        else:
            ui.notify(f"Failed to delete job: {result.get('message', 'Unknown error')}", type='negative')

    except Exception as e:
        ui.notify(f'Error deleting job: {str(e)}', type='negative')
        print(f"Error in _delete_job: {e}")


def _run_job_now(job_id: int):
    """Manually trigger a job execution."""
    # TODO: Implement manual job execution
    # This would need to integrate with the scheduler service
    ui.notify(f'Manual job execution not yet implemented', type='warning')


def _toggle_job_with_refresh(job_id: int, enabled: bool):
    """Enable or disable a job and refresh the page."""
    try:
        result = backend.toggle_scheduled_job(job_id, enabled)

        if result.get('success'):
            status = 'enabled' if enabled else 'disabled'
            ui.notify(f'Job {status} successfully', type='positive')
            # Refresh page
            ui.navigate.reload()
        else:
            ui.notify(f"Failed to toggle job: {result.get('message', 'Unknown error')}", type='negative')

    except Exception as e:
        ui.notify(f'Error toggling job: {str(e)}', type='negative')
        print(f"Error in _toggle_job: {e}")
