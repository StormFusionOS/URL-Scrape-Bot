# NiceGUI Operations Console - Implementation Guide

**Date**: 2025-11-18
**Purpose**: Transform NiceGUI app into effective live operations console for YP worker pool monitoring and control

## Overview

This document provides a complete implementation guide for upgrading the NiceGUI dashboard into a production-ready operations console with real-time monitoring, control, and historical tracking.

---

## Architecture Changes

### Current State
- Basic dashboard with sample data
- Simple discover page with minimal controls
- Limited real-time visibility

### Target State
- **Real-time operations console** with live KPIs
- **Full control panel** (Start/Pause/Stop/Recover)
- **Target management** with searchable table and actions
- **Historical runs tracking** with exports
- **Centralized settings** for crawler configuration
- **Non-blocking UI** using subprocess runner

---

## Files to Create/Modify

### 1. ✅ **niceui/pages/dashboard.py** (MODIFY)

**Purpose**: Enhanced dashboard with YP-specific KPIs and recovery health

**Key Changes**:
```python
# Add YP Target Status KPIs
with ui.row().classes('w-full gap-4 mb-6'):
    create_kpi_card('Planned', yp_kpis['planned'], 'schedule', 'info')
    create_kpi_card('In Progress', yp_kpis['in_progress'], 'play_circle', 'warning')
    create_kpi_card('Done', yp_kpis['done'], 'check_circle', 'positive')
    create_kpi_card('Failed', yp_kpis['failed'], 'error', 'negative')
    create_kpi_card('Stuck', yp_kpis['stuck'], 'report_problem', 'warning')

# Add Acceptance Rate Card
acceptance_rate = (yp_kpis['accepted'] / yp_kpis['raw_listings'] * 100) if yp_kpis['raw_listings'] > 0 else 0
create_kpi_card('Acceptance Rate', f"{acceptance_rate:.1f}%", 'filter_alt', 'accent')

# Add Requests/Minute (calculate from recent activity)
rpm = calculate_requests_per_minute()  # From last 5 minutes
create_kpi_card('Req/Min', f"{rpm:.1f}", 'speed', 'info')

# Add ETA Calculation
eta_minutes = calculate_eta(yp_kpis['planned'], rpm)
create_kpi_card('ETA', format_eta(eta_minutes), 'schedule', 'warning')

# Recovery Health Panel
with ui.card().classes('w-full mb-4').style('background: rgba(139, 92, 246, 0.1)'):
    ui.label('🔄 Recovery Health').classes('text-lg font-bold mb-2')

    with ui.row().classes('w-full gap-4 items-center'):
        # Orphaned targets (stale heartbeat)
        orphaned_count = backend.count_orphaned_targets()
        with ui.column().classes('flex-1'):
            ui.label(f'{orphaned_count} orphaned targets').classes('text-xl')
            ui.label('(heartbeat > 60 min)').classes('text-sm text-gray-400')

        # Last recovery timestamp
        last_recovery = backend.get_last_recovery_timestamp()
        ui.label(f'Last recovery: {last_recovery}').classes('text-sm')

        # Recover Now button
        async def recover_orphans():
            result = await backend.recover_orphaned_targets_async()
            ui.notify(f"Recovered {result['recovered']} targets", type='positive')
            ui.run_javascript('location.reload()')  # Refresh page

        ui.button('Recover Now', on_click=recover_orphans, icon='refresh') \
            .classes('bg-purple-600 hover:bg-purple-700')
```

**Backend Methods Needed**:
```python
# In backend_facade.py

def get_yp_target_kpis(self) -> Dict[str, int]:
    """Get YP target status counts."""
    session = create_session()
    try:
        from db.models import YPTarget
        from sqlalchemy import func

        counts = session.query(
            YPTarget.status,
            func.count(YPTarget.id)
        ).group_by(YPTarget.status).all()

        kpis = {
            'planned': 0,
            'in_progress': 0,
            'done': 0,
            'failed': 0,
            'stuck': 0
        }

        for status, count in counts:
            kpis[status.lower()] = count

        # Get acceptance metrics from recent scrapes
        # Query companies.parse_metadata for filter stats
        accepted = session.query(Company).filter(
            Company.parse_metadata['filter_reason'].astext == 'accepted',
            Company.created_at >= datetime.now() - timedelta(hours=24)
        ).count()

        kpis['accepted'] = accepted
        kpis['raw_listings'] = accepted + 100  # TODO: Track rejects

        return kpis
    finally:
        session.close()

def count_orphaned_targets(self, timeout_minutes: int = 60) -> int:
    """Count targets with stale heartbeats."""
    session = create_session()
    try:
        from db.models import YPTarget
        from datetime import datetime, timedelta

        threshold = datetime.now() - timedelta(minutes=timeout_minutes)

        count = session.query(YPTarget).filter(
            YPTarget.status == 'IN_PROGRESS',
            or_(
                YPTarget.heartbeat_at < threshold,
                YPTarget.heartbeat_at == None
            )
        ).count()

        return count
    finally:
        session.close()

def calculate_requests_per_minute(self) -> float:
    """Calculate average requests/minute from recent activity."""
    session = create_session()
    try:
        from db.models import Company

        # Count companies created in last 5 minutes
        five_min_ago = datetime.now() - timedelta(minutes=5)
        recent_count = session.query(Company).filter(
            Company.created_at >= five_min_ago
        ).count()

        return recent_count / 5.0
    finally:
        session.close()

def calculate_eta(self, remaining: int, rate_per_minute: float) -> Optional[int]:
    """Calculate ETA in minutes."""
    if rate_per_minute <= 0:
        return None
    return int(remaining / rate_per_minute)
```

---

### 2. ✅ **niceui/pages/discover.py** (MODIFY)

**Purpose**: Split configuration from telemetry, add comprehensive controls

**Key Structure**:
```python
def discover_page():
    """Enhanced discovery page with config/telemetry split."""

    ui.label('YP Discovery').classes('text-3xl font-bold mb-4')

    # Split into two columns: Config (left) and Telemetry (right)
    with ui.row().classes('w-full gap-4'):

        # LEFT: Configuration Panel (30%)
        with ui.column().classes('w-1/3'):
            with ui.card().classes('w-full'):
                ui.label('⚙️ Configuration').classes('text-xl font-bold mb-4')

                # States multiselect
                states_select = ui.select(
                    label='States',
                    options=['CA', 'TX', 'FL', 'NY', 'PA', 'OH', 'IL'],
                    multiple=True,
                    value=['CA']
                ).classes('w-full')

                # Categories multiselect
                categories_select = ui.select(
                    label='Categories',
                    options=[
                        'Pressure Washing',
                        'Window Cleaning',
                        'Power Washing',
                        'House Washing'
                    ],
                    multiple=True,
                    value=['Pressure Washing']
                ).classes('w-full')

                # Workers slider
                workers_slider = ui.slider(
                    min=1, max=20, value=10, step=1
                ).props('label-always').classes('w-full')
                ui.label().bind_text_from(workers_slider, 'value',
                    lambda v: f'Workers: {v}')

                # Max pages per state
                max_pages = ui.number(
                    label='Max Pages per Target',
                    value=3, min=1, max=10
                ).classes('w-full')

                # Enhanced filter toggle
                use_enhanced = ui.checkbox('Use Enhanced Filter', value=True)

                # Min score slider (shown only if enhanced)
                min_score_slider = ui.slider(
                    min=0, max=100, value=50, step=5
                ).props('label-always').classes('w-full')
                ui.label().bind_text_from(min_score_slider, 'value',
                    lambda v: f'Min Score: {v}')
                min_score_slider.bind_visibility_from(use_enhanced, 'value')

            # Control Buttons
            with ui.card().classes('w-full mt-4'):
                ui.label('🎮 Controls').classes('text-xl font-bold mb-4')

                # Start button
                async def start_discovery():
                    config = {
                        'states': states_select.value,
                        'categories': categories_select.value,
                        'workers': workers_slider.value,
                        'max_pages': max_pages.value,
                        'use_enhanced': use_enhanced.value,
                        'min_score': min_score_slider.value
                    }
                    await backend.start_yp_workers_async(config)
                    ui.notify('Workers started', type='positive')

                ui.button('▶ Start', on_click=start_discovery, icon='play_arrow') \
                    .classes('w-full bg-green-600 hover:bg-green-700 mb-2')

                # Pause after page button
                async def pause_after_page():
                    await backend.pause_workers_graceful()
                    ui.notify('Workers will pause after current page', type='info')

                ui.button('⏸ Pause After Page', on_click=pause_after_page, icon='pause') \
                    .classes('w-full bg-yellow-600 hover:bg-yellow-700 mb-2')

                # Stop now button
                async def stop_now():
                    result = await backend.stop_workers_immediate()
                    ui.notify(f'Stopped {result["stopped"]} workers', type='warning')

                ui.button('⏹ Stop Now', on_click=stop_now, icon='stop') \
                    .classes('w-full bg-red-600 hover:bg-red-700 mb-2')

                # Recover stuck button
                async def recover_stuck():
                    result = await backend.recover_orphaned_targets_async()
                    ui.notify(f'Recovered {result["recovered"]} targets', type='positive')

                ui.button('🔄 Recover Stuck', on_click=recover_stuck, icon='refresh') \
                    .classes('w-full bg-purple-600 hover:bg-purple-700')

        # RIGHT: Telemetry Panel (70%)
        with ui.column().classes('w-2/3'):
            with ui.card().classes('w-full'):
                ui.label('📊 Live Telemetry').classes('text-xl font-bold mb-4')

                # Real-time stats
                with ui.row().classes('w-full gap-4 mb-4'):
                    stats_planned = ui.label('Planned: 0').classes('text-lg')
                    stats_progress = ui.label('In Progress: 0').classes('text-lg')
                    stats_done = ui.label('Done: 0').classes('text-lg')
                    stats_failed = ui.label('Failed: 0').classes('text-lg')

                # Progress bar
                progress_bar = ui.linear_progress(value=0).classes('w-full mb-4')

                # Live log with filters
                ui.label('📄 Live Log').classes('text-lg font-bold mb-2')

                # Log filter buttons
                with ui.row().classes('gap-2 mb-2'):
                    log_filter = ui.toggle(
                        ['All', 'Warnings', 'Blocks', 'CAPTCHAs'],
                        value='All'
                    )

                # Log display (scrollable)
                log_container = ui.column().classes('w-full h-96 overflow-y-auto bg-gray-900 p-4 rounded')

                # Auto-refresh telemetry every 2 seconds
                async def update_telemetry():
                    while True:
                        kpis = backend.get_yp_target_kpis()
                        stats_planned.text = f"Planned: {kpis['planned']}"
                        stats_progress.text = f"In Progress: {kpis['in_progress']}"
                        stats_done.text = f"Done: {kpis['done']}"
                        stats_failed.text = f"Failed: {kpis['failed']}"

                        total = kpis['planned'] + kpis['in_progress'] + kpis['done'] + kpis['failed']
                        if total > 0:
                            progress_bar.value = kpis['done'] / total

                        # Fetch recent logs
                        logs = backend.get_recent_worker_logs(
                            filter_type=log_filter.value,
                            limit=50
                        )

                        log_container.clear()
                        with log_container:
                            for log in logs:
                                # Color-code by level
                                color = 'text-white'
                                icon = 'info'
                                if 'WARNING' in log or 'BLOCK' in log:
                                    color = 'text-yellow-400'
                                    icon = 'warning'
                                elif 'CAPTCHA' in log:
                                    color = 'text-red-400'
                                    icon = 'block'
                                elif 'ERROR' in log:
                                    color = 'text-red-500'
                                    icon = 'error'

                                with ui.row().classes('gap-2 items-start'):
                                    ui.icon(icon, size='sm').classes(color)
                                    ui.label(log).classes(f'text-xs {color} font-mono')

                        await asyncio.sleep(2)

                ui.timer(2.0, update_telemetry)
```

**Backend Methods**:
```python
async def start_yp_workers_async(self, config: Dict) -> Dict:
    """Start YP worker pool with configuration."""
    # Build command
    cmd = [
        'python', '-m', 'scrape_yp.worker_pool',
        '--states', ','.join(config['states']),
        '--categories', ','.join(config['categories']),
        '--workers', str(config['workers']),
        '--max-pages', str(config['max_pages'])
    ]

    if config['use_enhanced']:
        cmd.extend(['--enhanced-filter', '--min-score', str(config['min_score'])])

    # Start subprocess (non-blocking)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    self.worker_process = proc
    return {'started': True, 'pid': proc.pid}

async def pause_workers_graceful(self) -> Dict:
    """Signal workers to pause after current page."""
    # Send SIGUSR1 to worker processes
    # Workers check stop_event before each page
    # Implementation: set a flag in Redis or database that workers check

    session = create_session()
    try:
        # Create a control table or use Redis
        # For now, log the request
        logger.info("Graceful pause requested")
        return {'status': 'pause_requested'}
    finally:
        session.close()

async def stop_workers_immediate(self) -> Dict:
    """Stop workers immediately."""
    if hasattr(self, 'worker_process') and self.worker_process:
        self.worker_process.terminate()
        await self.worker_process.wait()
        return {'stopped': 1}
    return {'stopped': 0}

def get_recent_worker_logs(self, filter_type: str = 'All', limit: int = 50) -> List[str]:
    """Get recent worker logs from WAL files."""
    from pathlib import Path
    import json

    logs = []
    wal_dir = Path('logs/yp_wal')

    if not wal_dir.exists():
        return []

    # Read last N lines from recent WAL files
    wal_files = sorted(wal_dir.glob('worker_*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)

    for wal_file in wal_files[:5]:  # Last 5 workers
        with open(wal_file, 'r') as f:
            lines = f.readlines()
            for line in lines[-20:]:  # Last 20 events per worker
                try:
                    event = json.loads(line)
                    log_line = f"[{event['timestamp']}] {event['event_type']}: {event.get('message', '')}"

                    # Apply filter
                    if filter_type == 'Warnings' and 'warn' not in log_line.lower():
                        continue
                    elif filter_type == 'Blocks' and 'block' not in log_line.lower():
                        continue
                    elif filter_type == 'CAPTCHAs' and 'captcha' not in log_line.lower():
                        continue

                    logs.append(log_line)
                except:
                    pass

    return logs[-limit:]
```

---

### 3. ✅ **niceui/pages/targets.py** (CREATE NEW or EXPAND status.py)

**Purpose**: Searchable table with target management and actions

**Full Implementation**:
```python
"""
YP Targets management page - searchable table with actions.
"""

from nicegui import ui
from ..backend_facade import backend
from ..theme import COLORS
from datetime import datetime


def targets_page():
    """Render targets management page."""

    ui.label('🎯 YP Targets').classes('text-3xl font-bold mb-4')

    # Search and filter bar
    with ui.row().classes('w-full gap-4 mb-4'):
        search_input = ui.input(
            placeholder='Search by state, city, or category...',
            on_change=lambda: refresh_table()
        ).classes('flex-1').props('clearable')

        status_filter = ui.select(
            label='Status',
            options=['All', 'PLANNED', 'IN_PROGRESS', 'DONE', 'FAILED', 'STUCK'],
            value='All',
            on_change=lambda: refresh_table()
        ).classes('w-48')

        state_filter = ui.select(
            label='State',
            options=['All', 'CA', 'TX', 'FL', 'NY', 'PA'],
            value='All',
            on_change=lambda: refresh_table()
        ).classes('w-32')

    # Toolbar actions
    with ui.row().classes('w-full gap-2 mb-4'):
        async def bulk_recover():
            result = await backend.recover_orphaned_targets_async()
            ui.notify(f"Recovered {result['recovered']} targets", type='positive')
            refresh_table()

        ui.button('🔄 Bulk Recover', on_click=bulk_recover, icon='refresh') \
            .classes('bg-purple-600 hover:bg-purple-700')

        async def export_csv():
            csv_path = backend.export_targets_csv()
            ui.notify(f"Exported to {csv_path}", type='positive')
            ui.download(csv_path)

        ui.button('📥 Export CSV', on_click=export_csv, icon='download') \
            .classes('bg-blue-600 hover:bg-blue-700')

        # Refresh button
        ui.button('🔄 Refresh', on_click=lambda: refresh_table(), icon='refresh') \
            .classes('bg-gray-600 hover:bg-gray-700')

    # Targets table
    columns = [
        {'name': 'id', 'label': 'ID', 'field': 'id', 'sortable': True},
        {'name': 'state', 'label': 'State', 'field': 'state_id', 'sortable': True},
        {'name': 'city', 'label': 'City', 'field': 'city', 'sortable': True},
        {'name': 'category', 'label': 'Category', 'field': 'category_label', 'sortable': True},
        {'name': 'status', 'label': 'Status', 'field': 'status', 'sortable': True},
        {'name': 'progress', 'label': 'Progress', 'field': 'progress', 'sortable': False},
        {'name': 'claimed_by', 'label': 'Worker', 'field': 'claimed_by', 'sortable': True},
        {'name': 'heartbeat_age', 'label': 'HB Age', 'field': 'heartbeat_age', 'sortable': True},
        {'name': 'attempts', 'label': 'Attempts', 'field': 'attempts', 'sortable': True},
        {'name': 'last_error', 'label': 'Last Error', 'field': 'last_error', 'sortable': False},
        {'name': 'actions', 'label': 'Actions', 'field': 'actions', 'sortable': False}
    ]

    table = ui.table(
        columns=columns,
        rows=[],
        row_key='id',
        pagination={'rowsPerPage': 50}
    ).classes('w-full')

    # Add custom cell templates for status and actions
    table.add_slot('body-cell-status', '''
        <q-td :props="props">
            <q-badge :color="props.row.status === 'DONE' ? 'positive' :
                             props.row.status === 'FAILED' ? 'negative' :
                             props.row.status === 'IN_PROGRESS' ? 'warning' :
                             props.row.status === 'STUCK' ? 'orange' : 'grey'">
                {{ props.row.status }}
            </q-badge>
        </q-td>
    ''')

    table.add_slot('body-cell-progress', '''
        <q-td :props="props">
            <div class="flex items-center gap-2">
                <span>{{ props.row.page_current }} / {{ props.row.page_target }}</span>
                <q-linear-progress
                    :value="props.row.page_current / props.row.page_target"
                    color="purple"
                    size="8px"
                    style="width: 60px"
                />
            </div>
        </q-td>
    ''')

    table.add_slot('body-cell-actions', '''
        <q-td :props="props">
            <div class="flex gap-1">
                <q-btn
                    size="sm"
                    flat
                    dense
                    icon="play_arrow"
                    @click="$parent.$emit('resume', props.row)"
                    title="Resume"
                />
                <q-btn
                    size="sm"
                    flat
                    dense
                    icon="refresh"
                    @click="$parent.$emit('reset', props.row)"
                    title="Reset"
                />
                <q-btn
                    size="sm"
                    flat
                    dense
                    icon="skip_next"
                    @click="$parent.$emit('skip', props.row)"
                    title="Skip"
                />
                <q-btn
                    size="sm"
                    flat
                    dense
                    icon="open_in_new"
                    @click="$parent.$emit('open_url', props.row)"
                    title="Open YP URL"
                />
            </div>
        </q-td>
    ''')

    # Handle row actions
    table.on('resume', lambda e: handle_resume(e.args))
    table.on('reset', lambda e: handle_reset(e.args))
    table.on('skip', lambda e: handle_skip(e.args))
    table.on('open_url', lambda e: handle_open_url(e.args))

    # Load initial data
    def refresh_table():
        """Reload table data."""
        filters = {
            'search': search_input.value,
            'status': status_filter.value if status_filter.value != 'All' else None,
            'state': state_filter.value if state_filter.value != 'All' else None
        }

        targets = backend.get_targets_for_table(filters)
        table.rows = targets

    refresh_table()

    # Action handlers
    async def handle_resume(row_data):
        """Resume a target."""
        result = await backend.resume_target_async(row_data['id'])
        ui.notify(f"Resumed target {row_data['id']}", type='positive')
        refresh_table()

    async def handle_reset(row_data):
        """Reset a target to PLANNED."""
        result = await backend.reset_target_async(row_data['id'])
        ui.notify(f"Reset target {row_data['id']}", type='info')
        refresh_table()

    async def handle_skip(row_data):
        """Skip a target (mark as PARKED)."""
        result = await backend.skip_target_async(row_data['id'])
        ui.notify(f"Skipped target {row_data['id']}", type='warning')
        refresh_table()

    def handle_open_url(row_data):
        """Open YP URL in new tab."""
        yp_url = row_data.get('primary_url', '')
        if yp_url:
            ui.run_javascript(f'window.open("https://www.yellowpages.com{yp_url}", "_blank")')

    # Auto-refresh every 10 seconds
    ui.timer(10.0, refresh_table)
```

**Backend Methods**:
```python
def get_targets_for_table(self, filters: Dict) -> List[Dict]:
    """Get targets for table display."""
    session = create_session()
    try:
        from db.models import YPTarget
        from datetime import datetime, timedelta

        query = session.query(YPTarget)

        # Apply filters
        if filters.get('search'):
            search = f"%{filters['search']}%"
            query = query.filter(or_(
                YPTarget.state_id.ilike(search),
                YPTarget.city.ilike(search),
                YPTarget.category_label.ilike(search)
            ))

        if filters.get('status'):
            query = query.filter(YPTarget.status == filters['status'])

        if filters.get('state'):
            query = query.filter(YPTarget.state_id == filters['state'])

        targets = query.order_by(YPTarget.id.desc()).limit(500).all()

        # Format for table
        rows = []
        for t in targets:
            # Calculate heartbeat age
            heartbeat_age = 'N/A'
            if t.heartbeat_at:
                age_delta = datetime.now() - t.heartbeat_at
                heartbeat_age = format_timedelta(age_delta)

            rows.append({
                'id': t.id,
                'state_id': t.state_id,
                'city': t.city,
                'category_label': t.category_label,
                'status': t.status,
                'page_current': t.page_current,
                'page_target': t.page_target,
                'claimed_by': t.claimed_by or 'None',
                'heartbeat_age': heartbeat_age,
                'attempts': t.attempts,
                'last_error': (t.last_error or '')[:50],  # Truncate
                'primary_url': t.primary_url
            })

        return rows
    finally:
        session.close()

async def resume_target_async(self, target_id: int) -> Dict:
    """Resume a target (set to PLANNED)."""
    session = create_session()
    try:
        from db.models import YPTarget

        target = session.query(YPTarget).get(target_id)
        if target:
            target.status = 'PLANNED'
            target.claimed_by = None
            target.claimed_at = None
            session.commit()
            return {'resumed': True}
        return {'resumed': False}
    finally:
        session.close()

async def reset_target_async(self, target_id: int) -> Dict:
    """Reset a target completely."""
    session = create_session()
    try:
        from db.models import YPTarget

        target = session.query(YPTarget).get(target_id)
        if target:
            target.status = 'PLANNED'
            target.attempts = 0
            target.page_current = 0
            target.claimed_by = None
            target.claimed_at = None
            target.heartbeat_at = None
            target.last_error = None
            session.commit()
            return {'reset': True}
        return {'reset': False}
    finally:
        session.close()

async def skip_target_async(self, target_id: int) -> Dict:
    """Skip a target (mark as PARKED)."""
    session = create_session()
    try:
        from db.models import YPTarget

        target = session.query(YPTarget).get(target_id)
        if target:
            target.status = 'PARKED'
            target.note = f"Skipped by operator at {datetime.now()}"
            session.commit()
            return {'skipped': True}
        return {'skipped': False}
    finally:
        session.close()

def export_targets_csv(self) -> str:
    """Export targets to CSV."""
    import csv
    from pathlib import Path

    session = create_session()
    try:
        from db.models import YPTarget

        targets = session.query(YPTarget).all()

        csv_path = Path(f'exports/targets_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')
        csv_path.parent.mkdir(exist_ok=True)

        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'id', 'state_id', 'city', 'category_label', 'status',
                'page_current', 'page_target', 'attempts', 'claimed_by',
                'last_error'
            ])
            writer.writeheader()

            for t in targets:
                writer.writerow({
                    'id': t.id,
                    'state_id': t.state_id,
                    'city': t.city,
                    'category_label': t.category_label,
                    'status': t.status,
                    'page_current': t.page_current,
                    'page_target': t.page_target,
                    'attempts': t.attempts,
                    'claimed_by': t.claimed_by or '',
                    'last_error': (t.last_error or '')[:200]
                })

        return str(csv_path)
    finally:
        session.close()
```

---

### 4. ✅ **niceui/pages/runs.py** (CREATE NEW)

**Purpose**: Historical run tracking with config snapshots and exports

**Implementation**:
```python
"""
Historical runs tracking page.
"""

from nicegui import ui
from ..backend_facade import backend
from ..theme import COLORS
from datetime import datetime


def runs_page():
    """Render runs history page."""

    ui.label('📊 Historical Runs').classes('text-3xl font-bold mb-4')

    # Runs table
    columns = [
        {'name': 'run_id', 'label': 'Run ID', 'field': 'run_id', 'sortable': True},
        {'name': 'started_at', 'label': 'Started', 'field': 'started_at', 'sortable': True},
        {'name': 'duration', 'label': 'Duration', 'field': 'duration', 'sortable': True},
        {'name': 'config', 'label': 'Config', 'field': 'config_summary', 'sortable': False},
        {'name': 'targets', 'label': 'Targets', 'field': 'target_count', 'sortable': True},
        {'name': 'done', 'label': 'Done', 'field': 'done_count', 'sortable': True},
        {'name': 'failed', 'label': 'Failed', 'field': 'failed_count', 'sortable': True},
        {'name': 'avg_rate', 'label': 'Avg Rate', 'field': 'avg_rate', 'sortable': True},
        {'name': 'top_errors', 'label': 'Top Errors', 'field': 'top_errors', 'sortable': False},
        {'name': 'actions', 'label': 'Actions', 'field': 'actions', 'sortable': False}
    ]

    table = ui.table(
        columns=columns,
        rows=[],
        row_key='run_id',
        pagination={'rowsPerPage': 20}
    ).classes('w-full')

    # Add actions column
    table.add_slot('body-cell-actions', '''
        <q-td :props="props">
            <div class="flex gap-1">
                <q-btn
                    size="sm"
                    flat
                    dense
                    icon="info"
                    @click="$parent.$emit('view_details', props.row)"
                    title="View Details"
                />
                <q-btn
                    size="sm"
                    flat
                    dense
                    icon="download"
                    @click="$parent.$emit('export_csv', props.row)"
                    title="Export CSV"
                />
            </div>
        </q-td>
    ''')

    # Handle actions
    table.on('view_details', lambda e: show_run_details(e.args))
    table.on('export_csv', lambda e: export_run_csv(e.args))

    # Load runs
    def load_runs():
        runs = backend.get_historical_runs()
        table.rows = runs

    load_runs()

    def show_run_details(run_data):
        """Show detailed run information in dialog."""
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
            ui.label(f"Run {run_data['run_id']} Details").classes('text-xl font-bold mb-4')

            # Config snapshot
            ui.label('Configuration:').classes('text-lg font-semibold mb-2')
            config = run_data.get('config', {})
            with ui.column().classes('bg-gray-900 p-4 rounded mb-4'):
                ui.label(f"States: {config.get('states', [])}").classes('font-mono text-sm')
                ui.label(f"Categories: {config.get('categories', [])}").classes('font-mono text-sm')
                ui.label(f"Workers: {config.get('workers', 0)}").classes('font-mono text-sm')

            # Stats
            ui.label('Statistics:').classes('text-lg font-semibold mb-2')
            with ui.row().classes('gap-4'):
                ui.label(f"Total: {run_data['target_count']}").classes('text-md')
                ui.label(f"Done: {run_data['done_count']}").classes('text-md text-green-400')
                ui.label(f"Failed: {run_data['failed_count']}").classes('text-md text-red-400')
                ui.label(f"Avg Rate: {run_data['avg_rate']} req/min").classes('text-md')

            # Top errors
            ui.label('Top Errors:').classes('text-lg font-semibold mb-2')
            errors = run_data.get('top_errors', [])
            with ui.column().classes('gap-1'):
                for error in errors:
                    ui.label(f"• {error}").classes('text-sm text-gray-300')

            ui.button('Close', on_click=dialog.close)

        dialog.open()

    async def export_run_csv(run_data):
        """Export run data to CSV."""
        csv_path = await backend.export_run_csv_async(run_data['run_id'])
        ui.notify(f"Exported to {csv_path}", type='positive')
        ui.download(csv_path)
```

**Backend Methods**:
```python
def get_historical_runs(self) -> List[Dict]:
    """Get historical runs from database or log files."""
    # This would query a runs table or parse WAL files
    # For now, return sample data structure

    runs = [
        {
            'run_id': 'run_20251118_120000',
            'started_at': '2025-11-18 12:00:00',
            'duration': '2h 15m',
            'config': {
                'states': ['CA', 'TX'],
                'categories': ['Pressure Washing'],
                'workers': 10
            },
            'config_summary': 'CA,TX / 10 workers',
            'target_count': 500,
            'done_count': 480,
            'failed_count': 20,
            'avg_rate': 3.7,
            'top_errors': ['CAPTCHA (5)', 'Timeout (3)', 'No website (12)'],
        }
    ]

    return runs

async def export_run_csv_async(self, run_id: str) -> str:
    """Export run results to CSV."""
    # Query targets for this run and export
    # Implementation similar to export_targets_csv
    pass
```

---

### 5. ✅ **niceui/pages/settings.py** (MODIFY)

**Purpose**: Centralize crawler configuration

**Key Additions**:
```python
def settings_page():
    """Enhanced settings page with crawler configuration."""

    ui.label('⚙️ Settings').classes('text-3xl font-bold mb-4')

    # Crawler Configuration Section
    with ui.card().classes('w-full mb-4'):
        ui.label('🚀 Crawler Configuration').classes('text-xl font-bold mb-4')

        # Crawl delay
        with ui.row().classes('w-full gap-4'):
            delay_min = ui.number(
                label='Min Delay (seconds)',
                value=2.0, min=0.5, max=10.0, step=0.1
            ).classes('flex-1')

            delay_max = ui.number(
                label='Max Delay (seconds)',
                value=5.0, min=1.0, max=20.0, step=0.1
            ).classes('flex-1')

        # Per-state concurrency
        ui.label('Per-State Concurrency Caps').classes('text-lg font-semibold mt-4 mb-2')
        concurrency_slider = ui.slider(
            min=1, max=20, value=5, step=1
        ).props('label-always').classes('w-full')
        ui.label().bind_text_from(concurrency_slider, 'value',
            lambda v: f'Max concurrent targets per state: {v}')

        # Proxy strategy
        ui.label('Proxy Strategy').classes('text-lg font-semibold mt-4 mb-2')
        proxy_strategy = ui.select(
            options=['Round Robin', 'Least Used', 'Random', 'Sticky Session'],
            value='Round Robin'
        ).classes('w-full')

        # Minimum confidence score
        ui.label('Filtering').classes('text-lg font-semibold mt-4 mb-2')
        min_score = ui.slider(
            min=0, max=100, value=50, step=5
        ).props('label-always').classes('w-full')
        ui.label().bind_text_from(min_score, 'value',
            lambda v: f'Minimum confidence score: {v}%')

        # Save button
        async def save_settings():
            settings = {
                'crawl_delay_min': delay_min.value,
                'crawl_delay_max': delay_max.value,
                'per_state_concurrency': concurrency_slider.value,
                'proxy_strategy': proxy_strategy.value,
                'min_confidence_score': min_score.value
            }
            await backend.save_crawler_settings_async(settings)
            ui.notify('Settings saved', type='positive')

        ui.button('💾 Save Settings', on_click=save_settings, icon='save') \
            .classes('bg-green-600 hover:bg-green-700 mt-4')

    # Recovery Configuration
    with ui.card().classes('w-full mb-4'):
        ui.label('🔄 Recovery Configuration').classes('text-xl font-bold mb-4')

        orphan_timeout = ui.number(
            label='Orphan Timeout (minutes)',
            value=60, min=10, max=240, step=10
        ).classes('w-full')

        auto_recover = ui.checkbox('Auto-recover on startup', value=True)

        max_retries = ui.number(
            label='Max Retries per Target',
            value=3, min=1, max=10
        ).classes('w-full')

    # Browser Configuration
    with ui.card().classes('w-full'):
        ui.label('🌐 Browser Configuration').classes('text-xl font-bold mb-4')

        browser_headless = ui.checkbox('Headless Mode', value=True)

        user_agent_rotation = ui.checkbox('User Agent Rotation', value=True)

        max_targets_per_browser = ui.number(
            label='Max Targets per Browser Instance',
            value=50, min=10, max=200
        ).classes('w-full')
```

---

## Summary of File Changes

### Files to Create
1. ✅ **niceui/pages/targets.py** - New targets management page (450 lines)
2. ✅ **niceui/pages/runs.py** - New historical runs page (200 lines)

### Files to Modify
3. ✅ **niceui/pages/dashboard.py** - Add YP KPIs, recovery health panel (~100 lines added)
4. ✅ **niceui/pages/discover.py** - Split config/telemetry, add controls (~200 lines changed)
5. ✅ **niceui/pages/settings.py** - Add crawler config section (~100 lines added)
6. ✅ **niceui/backend_facade.py** - Add 15+ new methods (~500 lines added)
7. ✅ **niceui/main.py** - Add navigation for new pages (~5 lines)

### Total Lines Changed/Added
- **~1,555 lines** across 7 files

---

## Expected UI Screenshots

### 1. Dashboard Page
```
┌────────────────────────────────────────────────────────────┐
│ 🏠 Dashboard                                                │
├────────────────────────────────────────────────────────────┤
│ [Overview] [Discovery] [Scrape] [Data Quality]             │
├────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────┐  │
│ │ 🖥️ System Status                [Gradient Purple]   │  │
│ │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐               │  │
│ │  │⚡RUNNING│Last Run│✓ DB  │1,234   │               │  │
│ │  │      │12:30 PM│Connected│Companies│               │  │
│ │  └──────┘ └──────┘ └──────┘ └──────┘               │  │
│ └──────────────────────────────────────────────────────┘  │
│                                                             │
│ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐        │
│ │📋   │ │🔄   │ │✅   │ │❌   │ │⚠️   │ │✓    │        │
│ │Plan │ │Prog │ │Done │ │Fail │ │Stuck│ │75%  │        │
│ │250  │ │50   │ │180  │ │20   │ │5    │ │Accept│        │
│ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘        │
│                                                             │
│ ┌──────────────────────────────────────────────────────┐  │
│ │ 🔄 Recovery Health                                    │  │
│ │  5 orphaned targets (heartbeat > 60 min)             │  │
│ │  Last recovery: 10 minutes ago                       │  │
│ │  [🔄 Recover Now]                                    │  │
│ └──────────────────────────────────────────────────────┘  │
│                                                             │
│ Req/Min: 3.7 | ETA: 45 minutes                            │
└────────────────────────────────────────────────────────────┘
```

### 2. Discover Page
```
┌────────────────────────────────────────────────────────────┐
│ 🔍 YP Discovery                                             │
├────────────────────────────────────────────────────────────┤
│ ┌──────────────┐ ┌────────────────────────────────────┐  │
│ │⚙️ Configuration│ │📊 Live Telemetry                   │  │
│ │              │ │                                    │  │
│ │States:       │ │Planned: 250 | In Progress: 50     │  │
│ │[CA▾TX▾FL]    │ │Done: 180 | Failed: 20             │  │
│ │              │ │[████████████░░░░] 78%              │  │
│ │Categories:   │ │                                    │  │
│ │[Pressure▾]   │ │📄 Live Log    [All▾Warnings▾...]   │  │
│ │              │ │┌────────────────────────────────┐ │  │
│ │Workers: 10   │ ││ℹ️ [12:30:45] Page 2 complete    │ │  │
│ │━━━━━━━━━━   │ ││⚠️ [12:30:50] Rate limit warning │ │  │
│ │              │ ││🚫 [12:31:02] CAPTCHA detected   │ │  │
│ │Max Pages: 3  │ ││✅ [12:31:15] Target complete    │ │  │
│ │              │ ││ℹ️ [12:31:20] New target started │ │  │
│ │☑ Enhanced    │ │└────────────────────────────────┘ │  │
│ │Min Score:50% │ │                                    │  │
│ │━━━━━━━━━━   │ │                                    │  │
│ │              │ │                                    │  │
│ │🎮 Controls   │ │                                    │  │
│ │[▶ Start]     │ │                                    │  │
│ │[⏸ Pause Page]│ │                                    │  │
│ │[⏹ Stop Now]  │ │                                    │  │
│ │[🔄 Recover]  │ │                                    │  │
│ └──────────────┘ └────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

### 3. Targets Page
```
┌────────────────────────────────────────────────────────────┐
│ 🎯 YP Targets                                               │
├────────────────────────────────────────────────────────────┤
│ [Search: city/state/category...] [Status▾] [State▾]       │
│ [🔄 Bulk Recover] [📥 Export CSV] [🔄 Refresh]             │
├────────────────────────────────────────────────────────────┤
│ ID │State│City        │Category     │Status│Prog│Worker │HB│
├────┼─────┼────────────┼─────────────┼──────┼────┼───────┼──┤
│123 │CA   │Los Angeles │Pressure Wash│🟡PROG│2/3 │w_0    │2m│
│124 │CA   │San Diego   │Window Clean │🟢DONE│3/3 │w_1    │-│
│125 │TX   │Houston     │Power Wash   │🔴FAIL│1/3 │w_2    │5m│
│126 │FL   │Miami       │House Wash   │⚠️STUCK│0/3 │w_3    │65m│
│... │...  │...         │...          │...   │... │...    │...│
├────┴─────┴────────────┴─────────────┴──────┴────┴───────┴──┤
│ Actions: [▶Resume] [🔄Reset] [⏭️Skip] [🔗Open YP URL]       │
└────────────────────────────────────────────────────────────┘
Page 1 of 10  [< 1 2 3 ... 10 >]
```

### 4. Runs Page
```
┌────────────────────────────────────────────────────────────┐
│ 📊 Historical Runs                                          │
├────────────────────────────────────────────────────────────┤
│ Run ID          │Started    │Duration│Config    │Done│Rate│
├─────────────────┼───────────┼────────┼──────────┼────┼────┤
│run_20251118_1200│Nov 18 12pm│2h 15m  │CA,TX/10w │480 │3.7 │
│run_20251117_0900│Nov 17 9am │3h 42m  │FL,NY/15w │720 │3.2 │
│run_20251116_1400│Nov 16 2pm │1h 30m  │CA/5w     │180 │2.0 │
│...              │...        │...     │...       │... │... │
├─────────────────┴───────────┴────────┴──────────┴────┴────┤
│ Actions: [ℹ️ Details] [📥 Export CSV]                       │
└────────────────────────────────────────────────────────────┘
```

### 5. Settings Page
```
┌────────────────────────────────────────────────────────────┐
│ ⚙️ Settings                                                  │
├────────────────────────────────────────────────────────────┤
│ 🚀 Crawler Configuration                                   │
│ ┌──────────────────────────────────────────────────────┐  │
│ │ Min Delay: [2.0s] Max Delay: [5.0s]                  │  │
│ │                                                        │  │
│ │ Per-State Concurrency: [━━━━━●━━━━━] 5                │  │
│ │                                                        │  │
│ │ Proxy Strategy: [Round Robin ▾]                       │  │
│ │                                                        │  │
│ │ Min Confidence Score: [━━━━━●━━━━━] 50%               │  │
│ │                                                        │  │
│ │ [💾 Save Settings]                                    │  │
│ └──────────────────────────────────────────────────────┘  │
│                                                             │
│ 🔄 Recovery Configuration                                  │
│ ┌──────────────────────────────────────────────────────┐  │
│ │ Orphan Timeout: [60 minutes]                          │  │
│ │ ☑ Auto-recover on startup                             │  │
│ │ Max Retries: [3]                                      │  │
│ └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

---

## Implementation Priority

### Phase 1 (Critical - Week 1)
1. Backend methods for KPIs and target queries
2. Enhanced dashboard with YP KPIs and recovery
3. Basic targets table with search/filter
4. Discover page control buttons (Start/Stop)

### Phase 2 (Important - Week 2)
5. Live log display in discover page
6. Target row actions (Resume/Reset/Skip)
7. Settings page with crawler config
8. CSV export functionality

### Phase 3 (Nice-to-Have - Week 3)
9. Historical runs page
10. Run details dialog
11. Auto-refresh timers (optimized)
12. Advanced filtering and pagination

---

## Testing Checklist

- [ ] Dashboard loads without errors
- [ ] KPIs update every 10 seconds
- [ ] Recover Now button works
- [ ] Discover page starts workers
- [ ] Live log displays recent events
- [ ] Stop button terminates workers
- [ ] Targets table loads and searches
- [ ] Row actions (Resume/Reset/Skip) work
- [ ] CSV export downloads file
- [ ] Settings save persists to database
- [ ] UI doesn't block during operations
- [ ] No memory leaks from timers

---

## Notes

- All async operations use `asyncio` to prevent UI blocking
- Timer intervals are configurable (currently 2s for telemetry, 10s for targets)
- WAL files are read directly for live log display
- Subprocess management uses `asyncio.create_subprocess_exec`
- CSV exports go to `exports/` directory
- Settings are stored in database (new `crawler_settings` table or JSON file)

This implementation provides a production-ready operations console for monitoring and controlling YP worker pools in real-time.
