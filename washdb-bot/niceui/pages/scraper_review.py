"""
Scraper Review Dashboard - Inspect SEO scraper results run-by-run.

Provides run-based review interface for all 5 scraper modules:
- SERP: Position tracking, query results, PAA questions
- Competitor: Page crawls, content changes, schema updates
- Citation: NAP consistency, directory status
- Backlink: New backlinks, referring domains
- Technical Audit: Page scores, critical issues

Reuses patterns from seo_intelligence.py for consistency.
"""

from nicegui import ui
from sqlalchemy import text, create_engine
from datetime import datetime, timedelta
import os
from typing import List, Dict, Optional

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL')


class ScraperReviewDashboard:
    """Dashboard for reviewing scraper run results."""

    def __init__(self):
        self.selected_module = 'serp'
        self.selected_run = None
        self.date_range = '7d'

        # UI elements
        self.module_selector = None
        self.date_filter = None
        self.run_history_table = None
        self.detail_container = None

    def get_db_connection(self):
        """Get database connection."""
        if not DATABASE_URL:
            return None
        engine = create_engine(DATABASE_URL)
        return engine.connect()

    # ========== Run History Queries ==========

    def get_recent_runs(self, task_name: str, days: int = 7) -> List[Dict]:
        """Get recent runs for a scraper module."""
        conn = self.get_db_connection()
        if not conn:
            return []

        query = text("""
            SELECT
                task_id,
                task_name,
                status,
                started_at,
                completed_at,
                duration_seconds,
                records_processed,
                records_created,
                records_updated,
                error_message
            FROM task_logs
            WHERE task_name = :task_name
                AND started_at >= NOW() - INTERVAL ':days days'
            ORDER BY started_at DESC
            LIMIT 50
        """)

        result = conn.execute(query, {"task_name": task_name, "days": days})
        runs = []
        for row in result:
            runs.append({
                'task_id': row[0],
                'task_name': row[1],
                'status': row[2],
                'started_at': row[3],
                'completed_at': row[4],
                'duration_seconds': row[5],
                'records_processed': row[6],
                'records_created': row[7],
                'records_updated': row[8],
                'error_message': row[9]
            })

        # Fallback: If no task_logs, query scraper tables directly
        if not runs:
            runs = self._get_runs_from_scraper_tables(task_name, days, conn)

        conn.close()
        return runs

    def _get_runs_from_scraper_tables(self, task_name: str, days: int, conn) -> List[Dict]:
        """Fallback: Get runs by querying scraper tables directly when task_logs is empty."""
        runs = []

        # Map task names to their tables
        if task_name == 'technical_audit' or task_name == 'technical_auditor':
            # Query page_audits for audit runs (group by day)
            query = text("""
                SELECT
                    DATE_TRUNC('minute', audited_at) as run_time,
                    COUNT(*) as pages_audited,
                    SUM(CASE WHEN overall_score < 70 THEN 1 ELSE 0 END) as critical_count
                FROM page_audits
                WHERE audited_at >= NOW() - :days * INTERVAL '1 day'
                GROUP BY DATE_TRUNC('minute', audited_at)
                ORDER BY run_time DESC
                LIMIT 50
            """)
            result = conn.execute(query, {"days": days})
            for row in result:
                runs.append({
                    'task_id': None,
                    'task_name': 'technical_audit',
                    'status': 'success',
                    'started_at': row[0],
                    'completed_at': row[0],  # Same as started_at (no duration data)
                    'duration_seconds': None,
                    'records_processed': row[1],
                    'records_created': row[1],
                    'records_updated': 0,
                    'error_message': f'{row[2]} critical issues' if row[2] > 0 else None
                })

        return runs

    # ========== SERP Module Queries ==========

    def get_serp_run_details(self, started_at: datetime, completed_at: datetime) -> Dict:
        """Get SERP scraper run details."""
        conn = self.get_db_connection()
        if not conn:
            return {}

        # Get queries executed in this run
        query = text("""
            SELECT DISTINCT
                sq.query_id,
                sq.query_text,
                sq.location,
                COUNT(ss.snapshot_id) as snapshot_count
            FROM search_queries sq
            JOIN serp_snapshots ss ON sq.query_id = ss.query_id
            WHERE ss.captured_at BETWEEN :start AND :end
            GROUP BY sq.query_id, sq.query_text, sq.location
            ORDER BY sq.query_text
        """)

        result = conn.execute(query, {"start": started_at, "end": completed_at})
        queries = []
        for row in result:
            queries.append({
                'query_id': row[0],
                'query_text': row[1],
                'location': row[2],
                'snapshot_count': row[3]
            })

        # Get position changes for each query
        position_changes = []
        for q in queries:
            changes = self.get_serp_position_changes(q['query_id'], completed_at)
            if changes:
                position_changes.extend(changes)

        conn.close()
        return {
            'queries': queries,
            'position_changes': position_changes,
            'total_queries': len(queries)
        }

    def get_serp_position_changes(self, query_id: int, run_time: datetime) -> List[Dict]:
        """Get position changes for a query."""
        conn = self.get_db_connection()
        if not conn:
            return []

        query = text("""
            WITH current_run AS (
                SELECT ss.snapshot_id, ss.captured_at
                FROM serp_snapshots ss
                WHERE ss.query_id = :query_id
                    AND ss.captured_at <= :run_time
                ORDER BY ss.captured_at DESC
                LIMIT 1
            ),
            previous_run AS (
                SELECT ss.snapshot_id, ss.captured_at
                FROM serp_snapshots ss
                WHERE ss.query_id = :query_id
                    AND ss.captured_at < (SELECT captured_at FROM current_run)
                ORDER BY ss.captured_at DESC
                LIMIT 1
            )
            SELECT
                sr_curr.domain,
                sr_curr.title,
                sr_curr.position as current_position,
                sr_prev.position as previous_position,
                sr_curr.position - sr_prev.position as position_change,
                sr_curr.is_our_company,
                sr_curr.is_competitor
            FROM serp_results sr_curr
            LEFT JOIN serp_results sr_prev
                ON sr_prev.snapshot_id = (SELECT snapshot_id FROM previous_run)
                AND sr_prev.domain = sr_curr.domain
            WHERE sr_curr.snapshot_id = (SELECT snapshot_id FROM current_run)
            ORDER BY sr_curr.position
        """)

        result = conn.execute(query, {"query_id": query_id, "run_time": run_time})
        changes = []
        for row in result:
            changes.append({
                'domain': row[0],
                'title': row[1],
                'current_position': row[2],
                'previous_position': row[3],
                'position_change': row[4],
                'is_our_company': row[5],
                'is_competitor': row[6]
            })

        conn.close()
        return changes

    # ========== Competitor Module Queries ==========

    def get_competitor_run_details(self, started_at: datetime, completed_at: datetime) -> Dict:
        """Get competitor crawler run details."""
        conn = self.get_db_connection()
        if not conn:
            return {}

        # Get competitors crawled
        query = text("""
            SELECT
                c.competitor_id,
                c.name,
                c.domain,
                COUNT(cp.page_id) as pages_crawled,
                MAX(cp.crawled_at) as last_crawled
            FROM competitors c
            JOIN competitor_pages cp ON c.competitor_id = cp.competitor_id
            WHERE cp.crawled_at BETWEEN :start AND :end
            GROUP BY c.competitor_id, c.name, c.domain
            ORDER BY c.name
        """)

        result = conn.execute(query, {"start": started_at, "end": completed_at})
        competitors = []
        for row in result:
            competitors.append({
                'competitor_id': row[0],
                'name': row[1],
                'domain': row[2],
                'pages_crawled': row[3],
                'last_crawled': row[4]
            })

        # Get page changes (new or updated)
        changes_query = text("""
            SELECT
                cp.url,
                cp.page_type,
                cp.title,
                cp.word_count,
                cp.crawled_at,
                c.name as competitor_name
            FROM competitor_pages cp
            JOIN competitors c ON cp.competitor_id = c.competitor_id
            WHERE cp.crawled_at BETWEEN :start AND :end
            ORDER BY cp.crawled_at DESC
            LIMIT 100
        """)

        result = conn.execute(changes_query, {"start": started_at, "end": completed_at})
        page_changes = []
        for row in result:
            page_changes.append({
                'url': row[0],
                'page_type': row[1],
                'title': row[2],
                'word_count': row[3],
                'crawled_at': row[4],
                'competitor_name': row[5]
            })

        conn.close()
        return {
            'competitors': competitors,
            'page_changes': page_changes,
            'total_competitors': len(competitors),
            'total_pages': sum(c['pages_crawled'] for c in competitors)
        }

    # ========== Citation Module Queries ==========

    def get_citation_run_details(self, started_at: datetime, completed_at: datetime) -> Dict:
        """Get citation crawler run details."""
        conn = self.get_db_connection()
        if not conn:
            return {}

        query = text("""
            SELECT
                citation_id,
                directory_name,
                listing_url,
                business_name,
                address,
                phone,
                nap_match_score,
                is_claimed,
                rating,
                review_count,
                last_verified_at
            FROM citations
            WHERE last_verified_at BETWEEN :start AND :end
            ORDER BY nap_match_score ASC
        """)

        result = conn.execute(query, {"start": started_at, "end": completed_at})
        citations = []
        for row in result:
            citations.append({
                'citation_id': row[0],
                'directory_name': row[1],
                'listing_url': row[2],
                'business_name': row[3],
                'address': row[4],
                'phone': row[5],
                'nap_match_score': row[6],
                'is_claimed': row[7],
                'rating': row[8],
                'review_count': row[9],
                'last_verified_at': row[10]
            })

        conn.close()

        # Calculate statistics
        total = len(citations)
        critical_mismatches = len([c for c in citations if c['nap_match_score'] < 0.5])
        warnings = len([c for c in citations if 0.5 <= c['nap_match_score'] < 0.7])
        good = len([c for c in citations if c['nap_match_score'] >= 0.7])

        return {
            'citations': citations,
            'total': total,
            'critical_mismatches': critical_mismatches,
            'warnings': warnings,
            'good': good,
            'avg_score': sum(c['nap_match_score'] for c in citations) / total if total > 0 else 0
        }

    # ========== Backlink Module Queries ==========

    def get_backlink_run_details(self, started_at: datetime, completed_at: datetime) -> Dict:
        """Get backlink crawler run details."""
        conn = self.get_db_connection()
        if not conn:
            return {}

        # New backlinks discovered in this run
        query = text("""
            SELECT
                backlink_id,
                target_domain,
                target_url,
                source_domain,
                source_url,
                anchor_text,
                link_type,
                discovered_at
            FROM backlinks
            WHERE discovered_at BETWEEN :start AND :end
            ORDER BY discovered_at DESC
            LIMIT 100
        """)

        result = conn.execute(query, {"start": started_at, "end": completed_at})
        backlinks = []
        for row in result:
            backlinks.append({
                'backlink_id': row[0],
                'target_domain': row[1],
                'target_url': row[2],
                'source_domain': row[3],
                'source_url': row[4],
                'anchor_text': row[5],
                'link_type': row[6],
                'discovered_at': row[7]
            })

        # New referring domains
        domains_query = text("""
            SELECT
                domain,
                total_backlinks,
                dofollow_count,
                nofollow_count,
                local_authority_score,
                first_seen_at
            FROM referring_domains
            WHERE first_seen_at BETWEEN :start AND :end
            ORDER BY total_backlinks DESC
        """)

        result = conn.execute(domains_query, {"start": started_at, "end": completed_at})
        new_domains = []
        for row in result:
            new_domains.append({
                'domain': row[0],
                'total_backlinks': row[1],
                'dofollow_count': row[2],
                'nofollow_count': row[3],
                'local_authority_score': row[4],
                'first_seen_at': row[5]
            })

        conn.close()

        return {
            'backlinks': backlinks,
            'new_domains': new_domains,
            'total_backlinks': len(backlinks),
            'total_new_domains': len(new_domains),
            'dofollow_count': len([b for b in backlinks if b['link_type'] == 'dofollow']),
            'nofollow_count': len([b for b in backlinks if b['link_type'] == 'nofollow'])
        }

    # ========== Technical Audit Module Queries ==========

    def get_audit_run_details(self, started_at: datetime, completed_at: datetime) -> Dict:
        """Get technical auditor run details."""
        conn = self.get_db_connection()
        if not conn:
            return {}

        # Get audited pages
        query = text("""
            SELECT
                audit_id,
                url,
                overall_score,
                audited_at,
                page_load_time_ms,
                page_size_kb
            FROM page_audits
            WHERE audited_at BETWEEN :start AND :end
            ORDER BY overall_score ASC
        """)

        result = conn.execute(query, {"start": started_at, "end": completed_at})
        audits = []
        for row in result:
            audits.append({
                'audit_id': row[0],
                'url': row[1],
                'overall_score': row[2],
                'audited_at': row[3],
                'page_load_time_ms': row[4],
                'page_size_kb': row[5]
            })

        # Get critical/high severity issues
        issues_query = text("""
            SELECT
                ai.severity,
                ai.category,
                ai.issue_type,
                ai.description,
                ai.element,
                ai.recommendation,
                pa.url
            FROM audit_issues ai
            JOIN page_audits pa ON ai.audit_id = pa.audit_id
            WHERE pa.audited_at BETWEEN :start AND :end
                AND ai.severity IN ('critical', 'high')
            ORDER BY
                CASE ai.severity
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                END,
                ai.category
        """)

        result = conn.execute(issues_query, {"start": started_at, "end": completed_at})
        critical_issues = []
        for row in result:
            critical_issues.append({
                'severity': row[0],
                'category': row[1],
                'issue_type': row[2],
                'description': row[3],
                'element': row[4],
                'recommendation': row[5],
                'url': row[6]
            })

        conn.close()

        return {
            'audits': audits,
            'critical_issues': critical_issues,
            'total_pages': len(audits),
            'avg_score': sum(a['overall_score'] for a in audits) / len(audits) if audits else 0,
            'critical_count': len([i for i in critical_issues if i['severity'] == 'critical']),
            'high_count': len([i for i in critical_issues if i['severity'] == 'high'])
        }

    # ========== UI Rendering ==========

    def render_run_history_table(self, runs: List[Dict]):
        """Render the run history table."""
        if not runs:
            ui.label('No runs found for the selected time period.').classes('text-gray-400')
            return

        columns = [
            {'name': 'started_at', 'label': 'Started', 'field': 'started_at', 'align': 'left'},
            {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'left'},
            {'name': 'duration', 'label': 'Duration', 'field': 'duration_seconds', 'align': 'right'},
            {'name': 'processed', 'label': 'Processed', 'field': 'records_processed', 'align': 'right'},
            {'name': 'created', 'label': 'Created', 'field': 'records_created', 'align': 'right'},
            {'name': 'updated', 'label': 'Updated', 'field': 'records_updated', 'align': 'right'},
        ]

        # Format rows
        rows = []
        for run in runs:
            status_color = {
                'success': 'positive',
                'failed': 'negative',
                'running': 'info',
                'cancelled': 'warning'
            }.get(run['status'], 'grey')

            rows.append({
                'task_id': run['task_id'],
                'started_at': run['started_at'].strftime('%Y-%m-%d %H:%M:%S') if run['started_at'] else '-',
                'status': run['status'],
                'status_color': status_color,
                'duration_seconds': f"{run['duration_seconds']:.1f}s" if run['duration_seconds'] else '-',
                'records_processed': run['records_processed'] or 0,
                'records_created': run['records_created'] or 0,
                'records_updated': run['records_updated'] or 0,
                'run_data': run  # Store full run data for detail view
            })

        self.run_history_table = ui.table(
            columns=columns,
            rows=rows,
            row_key='task_id',
            pagination=10
        ).classes('w-full')

        # Make rows clickable
        self.run_history_table.on('rowClick', lambda e: self.load_run_details(e.args[1]['run_data']))

    def load_run_details(self, run: Dict):
        """Load and display details for a selected run."""
        self.selected_run = run
        self.detail_container.clear()

        with self.detail_container:
            ui.label(f"Run Details: {run['started_at'].strftime('%Y-%m-%d %H:%M:%S')}").classes('text-xl font-bold mb-4')

            if run['status'] == 'failed':
                ui.label(f"Error: {run['error_message']}").classes('text-red-500 mb-4')

            # Load module-specific details
            if self.selected_module == 'serp':
                self.render_serp_details(run)
            elif self.selected_module == 'competitor':
                self.render_competitor_details(run)
            elif self.selected_module == 'citation':
                self.render_citation_details(run)
            elif self.selected_module == 'backlink':
                self.render_backlink_details(run)
            elif self.selected_module == 'technical_audit':
                self.render_audit_details(run)

    def render_serp_details(self, run: Dict):
        """Render SERP scraper run details."""
        details = self.get_serp_run_details(run['started_at'], run['completed_at'])

        ui.label(f"Queries Executed: {details['total_queries']}").classes('text-lg mb-2')

        if details['position_changes']:
            ui.label('Position Changes:').classes('text-md font-bold mt-4 mb-2')

            for change in details['position_changes'][:20]:  # Limit to 20
                change_icon = '↑' if change['position_change'] < 0 else '↓' if change['position_change'] > 0 else '→'
                change_color = 'text-green-500' if change['position_change'] < 0 else 'text-red-500' if change['position_change'] > 0 else 'text-gray-500'

                with ui.row().classes('items-center'):
                    ui.label(f"#{change['current_position']}").classes('font-bold')
                    ui.label(change_icon).classes(f'{change_color} text-xl font-bold')
                    ui.label(change['domain']).classes('text-blue-500')
                    if change['is_our_company']:
                        ui.badge('OUR COMPANY', color='positive')
                    elif change['is_competitor']:
                        ui.badge('COMPETITOR', color='warning')

    def render_competitor_details(self, run: Dict):
        """Render competitor crawler run details."""
        details = self.get_competitor_run_details(run['started_at'], run['completed_at'])

        ui.label(f"Competitors Crawled: {details['total_competitors']}").classes('text-lg mb-2')
        ui.label(f"Total Pages: {details['total_pages']}").classes('text-lg mb-4')

        if details['page_changes']:
            ui.label('Recent Page Updates:').classes('text-md font-bold mt-4 mb-2')

            for page in details['page_changes'][:15]:
                with ui.card().classes('w-full mb-2'):
                    ui.label(page['competitor_name']).classes('font-bold')
                    ui.link(page['url'], page['url'], new_tab=True).classes('text-blue-500 text-sm')
                    ui.label(f"{page['page_type']} | {page['word_count']} words").classes('text-gray-400 text-sm')

    def render_citation_details(self, run: Dict):
        """Render citation crawler run details."""
        details = self.get_citation_run_details(run['started_at'], run['completed_at'])

        # Summary stats
        with ui.row().classes('gap-4 mb-4'):
            with ui.card():
                ui.label('Critical Mismatches').classes('text-sm text-gray-400')
                ui.label(str(details['critical_mismatches'])).classes('text-2xl font-bold text-red-500')

            with ui.card():
                ui.label('Warnings').classes('text-sm text-gray-400')
                ui.label(str(details['warnings'])).classes('text-2xl font-bold text-yellow-500')

            with ui.card():
                ui.label('Good').classes('text-sm text-gray-400')
                ui.label(str(details['good'])).classes('text-2xl font-bold text-green-500')

            with ui.card():
                ui.label('Avg NAP Score').classes('text-sm text-gray-400')
                ui.label(f"{details['avg_score']:.2f}").classes('text-2xl font-bold')

        # Citations list
        if details['citations']:
            ui.label('Citations Checked:').classes('text-md font-bold mt-4 mb-2')

            for citation in details['citations']:
                score_color = 'text-red-500' if citation['nap_match_score'] < 0.5 else 'text-yellow-500' if citation['nap_match_score'] < 0.7 else 'text-green-500'

                with ui.card().classes('w-full mb-2'):
                    with ui.row().classes('items-center justify-between w-full'):
                        with ui.column():
                            ui.label(citation['directory_name']).classes('font-bold')
                            ui.label(citation['business_name']).classes('text-sm')
                        ui.label(f"{citation['nap_match_score']:.2f}").classes(f'text-xl font-bold {score_color}')

    def render_backlink_details(self, run: Dict):
        """Render backlink crawler run details."""
        details = self.get_backlink_run_details(run['started_at'], run['completed_at'])

        ui.label(f"New Backlinks: {details['total_backlinks']}").classes('text-lg mb-2')
        ui.label(f"New Referring Domains: {details['total_new_domains']}").classes('text-lg mb-2')
        ui.label(f"Dofollow: {details['dofollow_count']} | Nofollow: {details['nofollow_count']}").classes('text-md mb-4')

        if details['backlinks']:
            ui.label('Recent Backlinks:').classes('text-md font-bold mt-4 mb-2')

            for backlink in details['backlinks'][:15]:
                with ui.card().classes('w-full mb-2'):
                    ui.link(backlink['source_url'], backlink['source_domain'], new_tab=True).classes('text-blue-500 font-bold')
                    ui.label(f"→ {backlink['target_domain']}").classes('text-sm')
                    ui.label(f'Anchor: "{backlink['anchor_text']}"').classes('text-sm text-gray-400')
                    ui.badge(backlink['link_type'], color='positive' if backlink['link_type'] == 'dofollow' else 'grey')

    def render_audit_details(self, run: Dict):
        """Render technical audit run details."""
        details = self.get_audit_run_details(run['started_at'], run['completed_at'])

        ui.label(f"Pages Audited: {details['total_pages']}").classes('text-lg mb-2')
        ui.label(f"Average Score: {details['avg_score']:.1f}/100").classes('text-lg mb-2')
        ui.label(f"Critical Issues: {details['critical_count']} | High: {details['high_count']}").classes('text-md mb-4')

        if details['critical_issues']:
            ui.label('Critical/High Severity Issues:').classes('text-md font-bold mt-4 mb-2')

            for issue in details['critical_issues']:
                severity_color = 'text-red-500' if issue['severity'] == 'critical' else 'text-orange-500'

                with ui.card().classes('w-full mb-2'):
                    with ui.row().classes('items-center gap-2'):
                        ui.badge(issue['severity'].upper(), color='negative' if issue['severity'] == 'critical' else 'warning')
                        ui.label(issue['category']).classes('font-bold')
                    ui.label(issue['description']).classes('text-sm')
                    ui.label(f"Recommendation: {issue['recommendation']}").classes('text-sm text-gray-400')
                    ui.label(f"Page: {issue['url']}").classes('text-xs text-blue-500')


def scraper_review_page():
    """Render the scraper review dashboard page."""
    dashboard = ScraperReviewDashboard()

    ui.label('Scraper Review Dashboard').classes('text-3xl font-bold mb-6')

    with ui.row().classes('items-center gap-4 mb-6'):
        # Module selector
        dashboard.module_selector = ui.select(
            label='Scraper Module',
            options={
                'serp': 'SERP Tracker',
                'competitor': 'Competitor Crawler',
                'citation': 'Citation Checker',
                'backlink': 'Backlink Crawler',
                'technical_audit': 'Technical Auditor'
            },
            value='serp',
            on_change=lambda e: load_runs(e.value)
        ).classes('w-64')

        # Date range filter
        dashboard.date_filter = ui.select(
            label='Time Period',
            options={
                '24h': 'Last 24 Hours',
                '7d': 'Last 7 Days',
                '30d': 'Last 30 Days'
            },
            value='7d',
            on_change=lambda e: load_runs(dashboard.module_selector.value, e.value)
        ).classes('w-48')

    # Run history section
    ui.label('Recent Runs').classes('text-xl font-bold mb-4')
    run_history_container = ui.column().classes('w-full mb-6')

    # Detail section
    ui.separator().classes('my-6')
    ui.label('Run Details').classes('text-xl font-bold mb-4')
    dashboard.detail_container = ui.column().classes('w-full')

    def load_runs(module: str, date_range: str = '7d'):
        """Load runs for the selected module."""
        dashboard.selected_module = module
        dashboard.date_range = date_range

        # Map module to task_name
        task_name_map = {
            'serp': 'serp_scraper',
            'competitor': 'competitor_crawler',
            'citation': 'citation_crawler',
            'backlink': 'backlink_crawler',
            'technical_audit': 'technical_auditor'
        }

        task_name = task_name_map.get(module, 'serp_scraper')
        days = {'24h': 1, '7d': 7, '30d': 30}.get(date_range, 7)

        runs = dashboard.get_recent_runs(task_name, days)

        run_history_container.clear()
        with run_history_container:
            dashboard.render_run_history_table(runs)

    # Initial load
    load_runs('serp')
