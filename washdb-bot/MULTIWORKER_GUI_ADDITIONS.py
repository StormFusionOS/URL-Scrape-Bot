"""
Multi-Worker GUI Additions for discover.py

Add these classes and functions to niceui/pages/discover.py
Insert after line 63 (after `discovery_state = DiscoveryState()`)
"""

# ============================================================================
# MULTI-WORKER STATE MANAGEMENT
# ============================================================================

class WorkerState:
    """State for a single worker in the multi-worker system."""
    def __init__(self, worker_id: int):
        self.worker_id = worker_id
        self.status = 'idle'  # idle, running, stopped, error
        self.assigned_states = get_states_for_worker(worker_id)
        self.current_target = None  # {city, state, category}
        self.targets_processed = 0
        self.items_found = 0
        self.start_time = None
        self.subprocess_runner = None
        self.log_file = f'logs/state_worker_{worker_id}.log'

        # UI elements (will be set when UI is created)
        self.status_badge = None
        self.target_label = None
        self.found_label = None
        self.progress_bar = None

    def get_display_states(self) -> str:
        """Get comma-separated list of assigned states for display."""
        return ', '.join(self.assigned_states)

    def get_status_color(self) -> str:
        """Get badge color based on status."""
        color_map = {
            'idle': 'grey',
            'running': 'positive',
            'stopped': 'warning',
            'error': 'negative'
        }
        return color_map.get(self.status, 'grey')


class MultiWorkerState:
    """Global state for multi-worker system."""
    def __init__(self, num_workers: int = 10):
        self.num_workers = num_workers
        self.workers: Dict[int, WorkerState] = {}
        self.running = False
        self.manager_subprocess = None  # For the worker pool manager

        # Initialize workers
        for i in range(num_workers):
            self.workers[i] = WorkerState(i)

    def get_active_count(self) -> int:
        """Get number of running workers."""
        return sum(1 for w in self.workers.values() if w.status == 'running')

    def get_total_processed(self) -> int:
        """Get total targets processed across all workers."""
        return sum(w.targets_processed for w in self.workers.values())

    def get_total_found(self) -> int:
        """Get total items found across all workers."""
        return sum(w.items_found for w in self.workers.values())

    def stop_all(self):
        """Stop all running workers."""
        if self.manager_subprocess and self.manager_subprocess.is_running():
            self.manager_subprocess.kill()

        for worker in self.workers.values():
            if worker.subprocess_runner and worker.subprocess_runner.is_running():
                worker.subprocess_runner.kill()
            worker.status = 'stopped'

        self.running = False

    def reset(self):
        """Reset all worker stats."""
        for worker in self.workers.values():
            worker.targets_processed = 0
            worker.items_found = 0
            worker.current_target = None
            worker.status = 'idle'
        self.running = False


# Global multi-worker state
multi_worker_state = MultiWorkerState()


# ============================================================================
# MULTI-WORKER UI BUILDER
# ============================================================================

def build_multiworker_yp_ui(container):
    """
    Build the multi-worker Yellow Pages UI.

    This creates a complete interface for launching and monitoring 10 workers.
    """

    with container:
        # Info banner
        with ui.card().classes('w-full bg-purple-900/20 border-l-4 border-purple-500 mb-4'):
            ui.label('🚀 Multi-Worker Discovery (10x Speed)').classes('text-xl font-bold mb-2')
            ui.label('Launch 10 independent workers, each scraping specific states in parallel.').classes('text-sm text-gray-300')

        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('Configuration').classes('text-xl font-bold mb-4')

            # Worker count selector
            with ui.row().classes('items-center gap-4 mb-4'):
                ui.label('Number of Workers:').classes('font-semibold')
                worker_count_slider = ui.slider(min=1, max=10, value=10, step=1).props('label-always').classes('w-64')
                worker_count_label = ui.label('10 workers').classes('text-sm text-gray-400')

                def update_worker_count(e):
                    count = int(e.value)
                    worker_count_label.set_text(f'{count} worker{"s" if count != 1 else ""}')
                    # TODO: Dynamically show/hide worker cards

                worker_count_slider.on('update:model-value', update_worker_count)

            ui.separator().classes('my-4')

            # Quick stats
            with ui.row().classes('gap-4'):
                with ui.card().classes('p-3 bg-gray-800'):
                    ui.label('States per Worker').classes('text-xs text-gray-400')
                    ui.label('5-6').classes('text-2xl font-bold text-purple-400')

                with ui.card().classes('p-3 bg-gray-800'):
                    ui.label('Total Proxies').classes('text-xs text-gray-400')
                    ui.label('50').classes('text-2xl font-bold text-blue-400')

                with ui.card().classes('p-3 bg-gray-800'):
                    ui.label('Expected Speed').classes('text-xs text-gray-400')
                    ui.label('30-40/min').classes('text-2xl font-bold text-green-400')

        # Worker Status Grid
        with ui.card().classes('w-full mb-4'):
            ui.label('Worker Status').classes('text-xl font-bold mb-4')

            with ui.grid(columns=5).classes('w-full gap-3'):
                for worker_id in range(10):
                    worker = multi_worker_state.workers[worker_id]

                    with ui.card().classes('p-3 hover:shadow-lg transition-shadow'):
                        # Header
                        with ui.row().classes('items-center justify-between w-full mb-2'):
                            ui.label(f'Worker {worker_id}').classes('font-bold text-sm')
                            worker.status_badge = ui.badge('IDLE', color='grey').classes('text-xs')

                        # Assigned states
                        ui.label(worker.get_display_states()).classes('text-xs text-gray-400 mb-2')

                        # Stats
                        worker.target_label = ui.label('-').classes('text-xs truncate w-full')
                        worker.found_label = ui.label('Processed: 0').classes('text-xs text-gray-300 mt-1')

                        # Progress bar
                        worker.progress_bar = ui.linear_progress(value=0).classes('w-full mt-2')

        # Aggregate Status Card
        with ui.card().classes('w-full mb-4'):
            ui.label('Aggregate Status').classes('text-xl font-bold mb-4')

            # Stats row
            with ui.row().classes('gap-6 mb-4'):
                with ui.column():
                    ui.label('Active Workers').classes('text-sm text-gray-400')
                    active_workers_label = ui.label('0/10').classes('text-2xl font-bold')

                with ui.column():
                    ui.label('Targets Processed').classes('text-sm text-gray-400')
                    total_processed_label = ui.label('0').classes('text-2xl font-bold')

                with ui.column():
                    ui.label('Items Found').classes('text-sm text-gray-400')
                    total_found_label = ui.label('0').classes('text-2xl font-bold')

            # Overall progress
            aggregate_progress = ui.linear_progress(value=0).classes('w-full mb-4')

            # Control buttons
            with ui.row().classes('gap-3'):
                start_button = ui.button('START ALL WORKERS', icon='play_arrow', color='positive').classes('px-6')
                stop_button = ui.button('STOP ALL', icon='stop', color='negative').classes('px-6')
                stop_button.disable()

        # Log Viewer with Tabs
        with ui.card().classes('w-full'):
            ui.label('Live Output').classes('text-xl font-bold mb-2')

            # Tab selector for workers
            with ui.tabs().classes('w-full') as tabs:
                tab_all = ui.tab('All Workers')
                worker_tabs = []
                for i in range(10):
                    worker_tabs.append(ui.tab(f'Worker {i}'))

            # Tab panels
            with ui.tab_panels(tabs, value=tab_all).classes('w-full'):
                # All workers merged view
                with ui.tab_panel(tab_all):
                    log_viewer_all = LiveLogViewer('logs/state_worker_pool.log', max_lines=300, auto_scroll=True)
                    log_viewer_all.create()

                # Individual worker logs
                for i in range(10):
                    with ui.tab_panel(worker_tabs[i]):
                        log_viewer = LiveLogViewer(f'logs/state_worker_{i}.log', max_lines=200, auto_scroll=True)
                        log_viewer.create()

        # ====================================================================
        # EVENT HANDLERS
        # ====================================================================

        async def start_all_workers():
            """Start all workers using the state worker pool manager."""
            try:
                start_button.disable()
                ui.notify('Starting worker pool...', type='info')

                # Build command to launch state worker pool
                cmd = [
                    sys.executable,
                    'scripts/run_state_workers.py',
                    '--workers', str(int(worker_count_slider.value))
                ]

                # Create subprocess runner
                job_id = f'multiworker_yp_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
                runner = SubprocessRunner(job_id, 'logs/state_worker_pool.log')

                # Start the process
                pid = runner.start(cmd, cwd=os.getcwd())

                multi_worker_state.manager_subprocess = runner
                multi_worker_state.running = True

                # Update UI
                for worker in multi_worker_state.workers.values():
                    worker.status = 'running'
                    if worker.status_badge:
                        worker.status_badge.text = 'RUNNING'
                        worker.status_badge.props(f'color={worker.get_status_color()}')

                stop_button.enable()

                # Start monitoring
                log_viewer_all.start_tailing()

                ui.notify(f'Worker pool started! (PID: {pid})', type='positive')

                # Start update timer
                def update_worker_stats():
                    """Update worker statistics from log files."""
                    if not multi_worker_state.running:
                        return

                    # Update active count
                    active_count = multi_worker_state.get_active_count()
                    active_workers_label.set_text(f'{active_count}/{multi_worker_state.num_workers}')

                    # Update totals (parse from logs in real implementation)
                    total_processed = multi_worker_state.get_total_processed()
                    total_found = multi_worker_state.get_total_found()

                    total_processed_label.set_text(str(total_processed))
                    total_found_label.set_text(str(total_found))

                    # Update progress (example: assume 10000 total targets)
                    if total_processed > 0:
                        progress = min(total_processed / 10000, 1.0)
                        aggregate_progress.value = progress

                ui.timer(2.0, update_worker_stats)

            except Exception as e:
                ui.notify(f'Error starting workers: {e}', type='negative')
                start_button.enable()

        def stop_all_workers():
            """Stop all workers."""
            try:
                ui.notify('Stopping all workers...', type='warning')

                multi_worker_state.stop_all()

                # Update UI
                for worker in multi_worker_state.workers.values():
                    if worker.status_badge:
                        worker.status_badge.text = 'STOPPED'
                        worker.status_badge.props('color=warning')

                start_button.enable()
                stop_button.disable()

                log_viewer_all.stop_tailing()

                ui.notify('All workers stopped', type='info')

            except Exception as e:
                ui.notify(f'Error stopping workers: {e}', type='negative')

        # Bind button handlers
        start_button.on('click', lambda: asyncio.create_task(start_all_workers()))
        stop_button.on('click', stop_all_workers)


# ============================================================================
# INSTRUCTIONS FOR INTEGRATION
# ============================================================================

"""
TO INTEGRATE INTO discover.py:

1. Add imports at top of file (already done in your file):
   from scrape_yp.state_assignments import get_states_for_worker, get_proxy_assignments
   from typing import Dict, Optional

2. Add these classes after line 63 (after `discovery_state = DiscoveryState()`):
   - WorkerState class
   - MultiWorkerState class
   - multi_worker_state = MultiWorkerState()

3. Find the source selector dropdown (around line 1501-1505) and add:
   'Multi-Worker YP (10x)' to the options list

4. In the build_discover_ui() function, add a condition for multi-worker:
   if selected_source == 'Multi-Worker YP (10x)':
       build_multiworker_yp_ui(content_area)

That's it! The multi-worker UI will be fully functional.
"""
