"""
Run Scraper Page
Real-time SEO scraper execution with live CLI output
"""

from nicegui import ui
from datetime import datetime
from niceui.services.scraper_process import get_scraper_manager
from niceui.components.glass_card import glass_card, section_title, divider, status_badge
from niceui.layout import page_layout


def create_page():
    """Create the run scraper page"""

    # Get scraper manager
    try:
        scraper_manager = get_scraper_manager()
    except RuntimeError:
        ui.label("Scraper manager not initialized").classes('text-negative')
        return

    # State
    state = {
        'node_type': 'all',
        'limit': None,
        'auto_scroll': True
    }

    # UI References
    ui_refs = {
        'status_badge': None,
        'pid_label': None,
        'runtime_label': None,
        'start_button': None,
        'stop_button': None,
        'output_log': None,
        'output_container': None
    }

    def update_status_display():
        """Update status display elements"""
        status = scraper_manager.get_status()

        # Update status badge
        if ui_refs['status_badge']:
            status_value = status['status']
            status_map = {
                'idle': ('Idle', 'grey'),
                'starting': ('Starting', 'info'),
                'running': ('Running', 'positive'),
                'stopping': ('Stopping', 'warning'),
                'stopped': ('Stopped', 'grey'),
                'completed': ('Completed', 'positive'),
                'failed': ('Failed', 'negative')
            }
            label, color = status_map.get(status_value, ('Unknown', 'grey'))
            ui_refs['status_badge'].set_text(label.upper())
            ui_refs['status_badge'].props(f'color={color}')

        # Update PID
        if ui_refs['pid_label']:
            pid_text = str(status['pid']) if status['pid'] else 'N/A'
            ui_refs['pid_label'].set_text(pid_text)

        # Update runtime
        if ui_refs['runtime_label']:
            if status['runtime_seconds']:
                minutes, seconds = divmod(int(status['runtime_seconds']), 60)
                hours, minutes = divmod(minutes, 60)
                runtime_text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                runtime_text = "00:00:00"
            ui_refs['runtime_label'].set_text(runtime_text)

        # Update button states
        if ui_refs['start_button'] and ui_refs['stop_button']:
            is_running = status['is_running']

            # Always enable STOP button (it will kill any external processes too)
            # Only disable START when GUI knows a process is running
            ui_refs['start_button'].set_enabled(not is_running)
            ui_refs['stop_button'].set_enabled(True)  # Always enabled

    def start_scraper():
        """Start the scraper process"""
        result = scraper_manager.start_scraper(
            node_type=state['node_type'] if state['node_type'] != 'all' else None,
            limit=state['limit']
        )

        if result['success']:
            ui.notify('Scraper started successfully', type='positive')
            update_status_display()
        else:
            ui.notify(f"Failed to start scraper: {result.get('error', 'Unknown error')}", type='negative')

    def stop_scraper():
        """Stop the scraper process (instant kill)"""
        result = scraper_manager.stop_scraper(force=True)

        if result['success']:
            ui.notify('Scraper stopped', type='positive')
            update_status_display()
        else:
            ui.notify(f"Failed to stop scraper: {result.get('error', 'Unknown error')}", type='negative')

    def clear_output():
        """Clear the output display"""
        scraper_manager.clear_output()
        if ui_refs['output_log']:
            ui_refs['output_log'].clear()
        ui.notify('Output cleared', type='info')

    def download_output():
        """Download output as text file"""
        output_lines = scraper_manager.get_output(last_n_lines=None)
        output_text = '\n'.join(output_lines)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'scraper_output_{timestamp}.txt'

        # Create download using JavaScript
        ui.run_javascript(f'''
            const blob = new Blob([`{output_text}`], {{ type: 'text/plain' }});
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = '{filename}';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        ''')

        ui.notify(f'Downloading {filename}', type='positive')

    with page_layout('SEO Scraper', 'Execute SEO scraper with real-time output'):

        # Configuration and Controls (no separate title)
        with glass_card():
            with ui.row().classes('w-full gap-4 items-end'):
                # Node type selector
                with ui.column().classes('flex-1'):
                    ui.label('Node Type').classes('text-sm glass-text-secondary mb-1')
                    node_select = ui.select(
                        options=['all', 'local', 'national'],
                        value='all',
                        on_change=lambda e: state.update({'node_type': e.value})
                    ).classes('w-full').props('outlined dense')

                # Limit input
                with ui.column().classes('flex-1'):
                    ui.label('Limit (URLs)').classes('text-sm glass-text-secondary mb-1')
                    limit_input = ui.number(
                        label='Optional',
                        value=None,
                        min=1,
                        max=1000,
                        on_change=lambda e: state.update({'limit': int(e.value) if e.value else None})
                    ).classes('w-full').props('outlined dense')

            divider(classes='my-4')

            # Control buttons
            with ui.row().classes('gap-2'):
                ui_refs['start_button'] = ui.button(
                    'START',
                    icon='play_arrow',
                    on_click=start_scraper
                ).props('color=positive size=md')

                ui_refs['stop_button'] = ui.button(
                    'STOP',
                    icon='stop',
                    on_click=stop_scraper
                ).props('color=negative size=md')  # Always enabled

        # Status Section
        section_title('Status', icon='info', classes='mt-8')

        with glass_card():
            with ui.row().classes('w-full items-center justify-between'):
                # Status badge
                with ui.row().classes('items-center gap-4'):
                    ui.icon('circle', size='sm').classes('text-grey')
                    ui_refs['status_badge'] = ui.badge('IDLE', color='grey').classes('text-sm')

                # PID display
                with ui.column().classes('items-end'):
                    ui.label('Process ID').classes('text-xs glass-text-secondary')
                    ui_refs['pid_label'] = ui.label('N/A').classes('text-lg font-mono glass-text-primary')

                # Runtime display
                with ui.column().classes('items-end'):
                    ui.label('Runtime').classes('text-xs glass-text-secondary')
                    ui_refs['runtime_label'] = ui.label('00:00:00').classes('text-lg font-mono glass-text-primary')

        # CLI Output Section
        section_title('Live Output', icon='terminal', classes='mt-8')

        with glass_card():
            # Output controls
            with ui.row().classes('w-full justify-between items-center mb-4'):
                with ui.row().classes('gap-2'):
                    ui.button('Clear', icon='delete', on_click=clear_output).props('flat size=sm')
                    ui.button('Download', icon='download', on_click=download_output).props('flat size=sm')

                ui.switch(
                    text='Auto-scroll',
                    value=True,
                    on_change=lambda e: state.update({'auto_scroll': e.value})
                ).classes('glass-text-primary')

            divider(classes='mb-4')

            # Output log with proper scrolling
            ui_refs['output_container'] = ui.column().classes('w-full')

            with ui_refs['output_container']:
                ui_refs['output_log'] = ui.log(max_lines=1000).classes(
                    'w-full bg-black/50 text-green-400 font-mono text-xs p-4 rounded overflow-auto'
                ).style('font-family: "Courier New", monospace; height: 600px; max-height: 70vh;')

        # Track last line count for polling
        last_line_count = {'count': 0}

        def update_output():
            """Poll for new output lines"""
            if not ui_refs['output_log']:
                return

            # Get latest output
            all_output = scraper_manager.get_output(last_n_lines=None)
            current_count = len(all_output)

            # Only add new lines
            if current_count > last_line_count['count']:
                new_lines = all_output[last_line_count['count']:]
                for line in new_lines:
                    ui_refs['output_log'].push(line)
                last_line_count['count'] = current_count

        # Initial status update
        update_status_display()

        # Load existing output if any
        existing_output = scraper_manager.get_output(last_n_lines=100)
        if existing_output and ui_refs['output_log']:
            for line in existing_output:
                ui_refs['output_log'].push(line)
            last_line_count['count'] = len(scraper_manager.get_output(last_n_lines=None))

        # Auto-refresh timers
        ui.timer(1.0, update_status_display)
        ui.timer(0.5, update_output)  # Poll for new output every 500ms
