#!/usr/bin/env python3
"""
SEO Worker Service - Continuous SEO auditing for company websites.

Pulls unaudited URLs from the companies table and runs technical audits,
saving results to page_audits and audit_issues tables.

Features:
- Automatic URL selection from companies DB
- Heartbeat/status broadcasting via Unix socket
- Prefetch buffer for steady throughput
- Rate limiting and error handling
- Live status updates for dashboard

Usage:
    python seo_intelligence/seo_worker_service.py
"""

import os
import sys
import json
import time
import signal
import socket
import threading
import queue
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from runner.logging_setup import get_logger

load_dotenv()

# Configuration
STATUS_SOCKET_PATH = "/tmp/seo_worker.sock"
PID_FILE = "/tmp/seo_worker.pid"
BATCH_SIZE = 10  # Companies to process per batch
RATE_LIMIT_DELAY = 2.0  # Seconds between requests
HEARTBEAT_INTERVAL = 5.0  # Seconds between status updates
PREFETCH_SIZE = 5  # Companies to prefetch

logger = get_logger("seo_worker_service")


def get_verification_where_clause() -> str:
    """
    Get SQL WHERE clause for filtering companies by verification status.

    Returns companies that have been verified as legitimate service providers.
    Uses the standardized 'verified' column (true/false/null).

    Returns:
        SQL WHERE clause string (can be used with AND in queries)
    """
    return "verified = true"

# Global state
shutdown_requested = False
service_stats = {
    'started_at': None,
    'companies_processed': 0,
    'audits_completed': 0,
    'errors': 0,
    'current_company': None,
    'queue_size': 0,
    'last_heartbeat': None,
    'status': 'stopped'
}


@dataclass
class CompanyToAudit:
    """Company data for SEO audit."""
    id: int
    name: str
    website: str
    domain: Optional[str]


@dataclass
class AuditStatus:
    """Current service status for broadcasting."""
    status: str
    companies_processed: int
    audits_completed: int
    errors: int
    queue_size: int
    current_company: Optional[str]
    uptime_seconds: int
    last_update: str


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global shutdown_requested
    shutdown_requested = True
    logger.info("Shutdown signal received")


class SEOWorkerService:
    """
    SEO Worker Service that continuously audits company websites.

    Architecture:
    - Main thread: Processes audit queue
    - Prefetch thread: Loads companies from DB into queue
    - Status thread: Broadcasts heartbeat via Unix socket
    """

    def __init__(self):
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL not set")

        self.engine = create_engine(database_url, echo=False)
        self.Session = sessionmaker(bind=self.engine)

        # Audit queue
        self.audit_queue: queue.Queue[CompanyToAudit] = queue.Queue(maxsize=PREFETCH_SIZE)

        # Status socket
        self.status_socket: Optional[socket.socket] = None
        self.status_connections: List[socket.socket] = []

        # Threads
        self._prefetch_thread: Optional[threading.Thread] = None
        self._status_thread: Optional[threading.Thread] = None
        self._running = False

        # Import auditor lazily to avoid circular imports
        self.auditor = None

    def _init_auditor(self):
        """Initialize the technical auditor (SeleniumBase UC version)."""
        try:
            # Use SeleniumBase version for better anti-detection
            from seo_intelligence.scrapers.technical_auditor_selenium import TechnicalAuditorSelenium
            self.auditor = TechnicalAuditorSelenium()
            logger.info("Technical auditor initialized (SeleniumBase UC)")
        except ImportError as e:
            logger.warning(f"Could not import TechnicalAuditorSelenium: {e}")
            self.auditor = None

    def start(self):
        """Start the SEO worker service."""
        global service_stats, shutdown_requested

        shutdown_requested = False
        self._running = True

        service_stats['started_at'] = datetime.now().isoformat()
        service_stats['status'] = 'starting'

        # Initialize auditor
        self._init_auditor()

        # Setup status socket
        self._setup_status_socket()

        # Save PID
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))

        # Start prefetch thread
        self._prefetch_thread = threading.Thread(
            target=self._prefetch_loop,
            name="SEO-Prefetch",
            daemon=True
        )
        self._prefetch_thread.start()

        # Start status broadcast thread
        self._status_thread = threading.Thread(
            target=self._status_loop,
            name="SEO-Status",
            daemon=True
        )
        self._status_thread.start()

        logger.info("=" * 70)
        logger.info("SEO WORKER SERVICE STARTED")
        logger.info("=" * 70)
        logger.info(f"Status socket: {STATUS_SOCKET_PATH}")
        logger.info(f"Batch size: {BATCH_SIZE}")
        logger.info(f"Rate limit: {RATE_LIMIT_DELAY}s")
        logger.info("-" * 70)

        service_stats['status'] = 'running'

        # Main processing loop
        self._process_loop()

    def _setup_status_socket(self):
        """Setup Unix socket for status broadcasting."""
        try:
            if os.path.exists(STATUS_SOCKET_PATH):
                os.unlink(STATUS_SOCKET_PATH)

            self.status_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.status_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.status_socket.bind(STATUS_SOCKET_PATH)
            self.status_socket.listen(10)
            self.status_socket.settimeout(1.0)
            os.chmod(STATUS_SOCKET_PATH, 0o666)

            logger.info(f"Status socket listening at {STATUS_SOCKET_PATH}")
        except Exception as e:
            logger.error(f"Failed to setup status socket: {e}")
            self.status_socket = None

    def _status_loop(self):
        """Broadcast status updates to connected clients."""
        global service_stats

        while self._running and not shutdown_requested:
            try:
                # Accept new connections
                if self.status_socket:
                    try:
                        conn, _ = self.status_socket.accept()
                        conn.setblocking(False)
                        self.status_connections.append(conn)
                        logger.debug(f"New status client connected (total: {len(self.status_connections)})")
                    except socket.timeout:
                        pass

                # Update and broadcast status
                service_stats['last_heartbeat'] = datetime.now().isoformat()
                service_stats['queue_size'] = self.audit_queue.qsize()

                uptime = 0
                if service_stats['started_at']:
                    start = datetime.fromisoformat(service_stats['started_at'])
                    uptime = int((datetime.now() - start).total_seconds())

                status = AuditStatus(
                    status=service_stats['status'],
                    companies_processed=service_stats['companies_processed'],
                    audits_completed=service_stats['audits_completed'],
                    errors=service_stats['errors'],
                    queue_size=service_stats['queue_size'],
                    current_company=service_stats['current_company'],
                    uptime_seconds=uptime,
                    last_update=datetime.now().isoformat()
                )

                status_json = json.dumps(asdict(status)) + "\n"

                # Broadcast to all connections
                dead_conns = []
                for conn in self.status_connections:
                    try:
                        conn.sendall(status_json.encode('utf-8'))
                    except:
                        dead_conns.append(conn)

                # Remove dead connections
                for conn in dead_conns:
                    self.status_connections.remove(conn)
                    try:
                        conn.close()
                    except:
                        pass

                time.sleep(HEARTBEAT_INTERVAL)

            except Exception as e:
                logger.error(f"Status loop error: {e}")
                time.sleep(1.0)

    def _prefetch_loop(self):
        """Continuously prefetch companies from database."""
        global service_stats

        logger.info("Prefetch loop started")
        empty_count = 0

        while self._running and not shutdown_requested:
            try:
                # Only prefetch if queue has room
                if self.audit_queue.full():
                    time.sleep(0.5)
                    continue

                # Get batch of companies to audit
                companies = self._get_companies_to_audit(BATCH_SIZE)

                if not companies:
                    empty_count += 1
                    if empty_count % 10 == 0:
                        logger.info("No unaudited companies found, waiting...")
                    time.sleep(10.0)
                    continue

                empty_count = 0

                for company in companies:
                    if self.audit_queue.full():
                        break
                    try:
                        self.audit_queue.put(company, timeout=5.0)
                        logger.debug(f"Queued: {company.name} (queue: {self.audit_queue.qsize()})")
                    except queue.Full:
                        break

            except Exception as e:
                logger.error(f"Prefetch error: {e}")
                time.sleep(5.0)

    def _get_companies_to_audit(self, limit: int) -> List[CompanyToAudit]:
        """Get verified companies that haven't been audited recently."""
        session = self.Session()
        try:
            # Get verified companies without recent page audits
            # Only process verified companies (passed verification or human-labeled as provider)
            verification_clause = get_verification_where_clause()
            query = text(f"""
                SELECT c.id, c.name, c.website, c.domain
                FROM companies c
                LEFT JOIN page_audits pa ON c.website = pa.url
                WHERE c.website IS NOT NULL
                  AND c.active = true
                  AND {verification_clause}
                  AND (pa.id IS NULL OR pa.audit_date < NOW() - INTERVAL '7 days')
                ORDER BY pa.audit_date ASC NULLS FIRST, c.last_updated DESC
                LIMIT :limit
            """)

            result = session.execute(query, {'limit': limit})
            companies = []

            for row in result:
                companies.append(CompanyToAudit(
                    id=row.id,
                    name=row.name,
                    website=row.website,
                    domain=row.domain
                ))

            return companies

        except Exception as e:
            logger.error(f"Error getting companies: {e}")
            return []
        finally:
            session.close()

    def _process_loop(self):
        """Main processing loop - audit companies from queue."""
        global service_stats

        logger.info("Processing loop started")

        while self._running and not shutdown_requested:
            try:
                # Get next company from queue
                try:
                    company = self.audit_queue.get(timeout=5.0)
                except queue.Empty:
                    continue

                service_stats['current_company'] = company.name
                logger.info(f"Auditing: {company.name} ({company.website})")

                # Run audit
                try:
                    if self.auditor:
                        result = self._run_audit(company)
                        if result:
                            self._save_audit_result(company, result)
                            service_stats['audits_completed'] += 1
                            logger.info(f"Audit complete: {company.name} - Score: {result.get('overall_score', 'N/A')}")
                    else:
                        # Fallback: simple audit without full auditor
                        result = self._simple_audit(company)
                        if result:
                            self._save_simple_audit(company, result)
                            service_stats['audits_completed'] += 1

                except Exception as e:
                    logger.error(f"Audit error for {company.name}: {e}")
                    service_stats['errors'] += 1

                service_stats['companies_processed'] += 1
                service_stats['current_company'] = None

                # Rate limiting
                time.sleep(RATE_LIMIT_DELAY)

            except Exception as e:
                logger.error(f"Process loop error: {e}")
                time.sleep(1.0)

        self._cleanup()

    def _run_audit(self, company: CompanyToAudit) -> Optional[Dict]:
        """Run full technical audit using TechnicalAuditor."""
        try:
            result = self.auditor.audit_url(company.website)
            return result if result else None
        except Exception as e:
            logger.error(f"Technical audit failed: {e}")
            return None

    def _simple_audit(self, company: CompanyToAudit) -> Optional[Dict]:
        """Simple audit fallback using requests."""
        import requests

        try:
            start_time = time.time()

            response = requests.get(
                company.website,
                timeout=15,
                headers={'User-Agent': 'WashDB SEO Auditor/1.0'},
                allow_redirects=True
            )

            load_time = time.time() - start_time

            # Basic checks
            result = {
                'url': company.website,
                'status_code': response.status_code,
                'load_time_ms': int(load_time * 1000),
                'content_length': len(response.content),
                'is_https': company.website.startswith('https'),
                'has_title': '<title>' in response.text.lower(),
                'has_meta_description': 'meta name="description"' in response.text.lower() or "meta name='description'" in response.text.lower(),
                'has_h1': '<h1' in response.text.lower(),
                'audit_date': datetime.now().isoformat()
            }

            # Calculate simple score
            score = 50  # Base score
            if result['is_https']:
                score += 15
            if result['has_title']:
                score += 10
            if result['has_meta_description']:
                score += 10
            if result['has_h1']:
                score += 5
            if result['load_time_ms'] < 2000:
                score += 10
            elif result['load_time_ms'] < 5000:
                score += 5

            result['overall_score'] = min(100, score)

            return result

        except requests.RequestException as e:
            logger.warning(f"Request failed for {company.website}: {e}")
            return {
                'url': company.website,
                'status_code': 0,
                'error': str(e),
                'overall_score': 0,
                'audit_date': datetime.now().isoformat()
            }

    def _save_audit_result(self, company: CompanyToAudit, result: Dict):
        """Save audit result to database."""
        session = self.Session()
        try:
            # Insert or update page_audits
            query = text("""
                INSERT INTO page_audits (
                    url, company_id, audit_date, overall_score,
                    performance_score, seo_score, accessibility_score,
                    security_score, metrics, passed_checks, created_at
                ) VALUES (
                    :url, :company_id, NOW(), :overall_score,
                    :performance_score, :seo_score, :accessibility_score,
                    :security_score, CAST(:metrics AS jsonb), :passed_checks, NOW()
                )
                ON CONFLICT (url) DO UPDATE SET
                    audit_date = NOW(),
                    overall_score = :overall_score,
                    performance_score = :performance_score,
                    seo_score = :seo_score,
                    accessibility_score = :accessibility_score,
                    security_score = :security_score,
                    metrics = CAST(:metrics AS jsonb),
                    passed_checks = :passed_checks
            """)

            session.execute(query, {
                'url': company.website,
                'company_id': company.id,
                'overall_score': result.get('overall_score', 0),
                'performance_score': result.get('performance_score', 0),
                'seo_score': result.get('seo_score', 0),
                'accessibility_score': result.get('accessibility_score', 0),
                'security_score': result.get('security_score', 0),
                'metrics': json.dumps(result.get('metrics', {})),
                'passed_checks': result.get('passed_checks', [])
            })

            session.commit()

        except Exception as e:
            logger.error(f"Failed to save audit result: {e}")
            session.rollback()
        finally:
            session.close()

    def _save_simple_audit(self, company: CompanyToAudit, result: Dict):
        """Save simple audit result to database."""
        session = self.Session()
        try:
            query = text("""
                INSERT INTO page_audits (
                    url, company_id, audit_date, overall_score,
                    metrics, created_at
                ) VALUES (
                    :url, :company_id, NOW(), :overall_score,
                    CAST(:metrics AS jsonb), NOW()
                )
                ON CONFLICT (url) DO UPDATE SET
                    audit_date = NOW(),
                    overall_score = :overall_score,
                    metrics = CAST(:metrics AS jsonb)
            """)

            session.execute(query, {
                'url': company.website,
                'company_id': company.id,
                'overall_score': result.get('overall_score', 0),
                'metrics': json.dumps(result)
            })

            session.commit()
            logger.debug(f"Saved audit for {company.name}: score={result.get('overall_score', 0)}")

        except Exception as e:
            logger.error(f"Failed to save simple audit: {e}")
            session.rollback()
        finally:
            session.close()

    def _cleanup(self):
        """Cleanup resources on shutdown."""
        global service_stats

        self._running = False
        service_stats['status'] = 'stopped'

        # Close status connections
        for conn in self.status_connections:
            try:
                conn.close()
            except:
                pass

        if self.status_socket:
            try:
                self.status_socket.close()
            except:
                pass

        # Remove socket file
        if os.path.exists(STATUS_SOCKET_PATH):
            try:
                os.unlink(STATUS_SOCKET_PATH)
            except:
                pass

        # Remove PID file
        if os.path.exists(PID_FILE):
            try:
                os.unlink(PID_FILE)
            except:
                pass

        # Final stats
        logger.info("=" * 70)
        logger.info("SEO WORKER SERVICE STOPPED")
        logger.info("=" * 70)
        logger.info(f"Companies processed: {service_stats['companies_processed']}")
        logger.info(f"Audits completed: {service_stats['audits_completed']}")
        logger.info(f"Errors: {service_stats['errors']}")


def get_service_status() -> Optional[Dict]:
    """Get current service status (for external callers)."""
    if not os.path.exists(STATUS_SOCKET_PATH):
        return None

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(STATUS_SOCKET_PATH)

        # Read one status update
        data = b""
        while True:
            chunk = sock.recv(1)
            if not chunk or chunk == b"\n":
                break
            data += chunk

        sock.close()
        return json.loads(data.decode('utf-8'))
    except:
        return None


def is_service_running() -> bool:
    """Check if SEO worker service is running."""
    return os.path.exists(STATUS_SOCKET_PATH)


def main():
    """Main entry point."""
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    service = SEOWorkerService()
    service.start()


if __name__ == '__main__':
    main()
