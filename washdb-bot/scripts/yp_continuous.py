#!/usr/bin/env python3
"""
Continuous YP scraper runner with auto-restart and alerting.

This script runs the YP scraper in an infinite loop with:
- 1-hour cooldown between successful cycles
- Email alerts after 10 consecutive failures
- Recovery notifications when scraper resumes normal operation
- Graceful signal handling for clean shutdown

Usage:
    python scripts/yp_continuous.py

Configuration via environment variables:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL
"""
import subprocess
import sys
import time
import os
import signal
from pathlib import Path
from datetime import datetime
from typing import Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

from services.email_alerts import EmailAlertService
from runner.logging_setup import get_logger

logger = get_logger("YPContinuous")

# Configuration
SCRAPER_NAME = "YP"
COOLDOWN_SECONDS = 3600  # 1 hour between cycles
FAILURE_ALERT_THRESHOLD = 10  # Alert after this many consecutive failures
SHORT_RETRY_DELAY = 60  # 1 minute delay on failure before retry

# All 50 US states (comma-separated for YP CLI)
ALL_STATES = "AL,AK,AZ,AR,CA,CO,CT,DE,FL,GA,HI,ID,IL,IN,IA,KS,KY,LA,ME,MD,MA,MI,MN,MS,MO,MT,NE,NV,NH,NJ,NM,NY,NC,ND,OH,OK,OR,PA,RI,SC,SD,TN,TX,UT,VT,VA,WA,WV,WI,WY"

# Graceful shutdown flag
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, requesting graceful shutdown...")
    shutdown_requested = True


def run_scraper() -> Tuple[int, str, float]:
    """
    Run the YP scraper.

    Returns:
        Tuple of (exit_code, error_message, duration_seconds)
    """
    start_time = time.time()

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / 'cli_crawl_yp.py'),
        '--states', ALL_STATES
    ]

    logger.info(f"Executing: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=None  # No timeout - let it run to completion
        )

        duration = time.time() - start_time
        error_msg = result.stderr[-2000:] if result.stderr else ""

        if result.returncode != 0:
            # Log the error output
            logger.error(f"Scraper stderr: {error_msg}")
            if result.stdout:
                logger.error(f"Scraper stdout (last 1000 chars): {result.stdout[-1000:]}")

        return result.returncode, error_msg, duration

    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        return -2, "Process timeout", duration

    except Exception as e:
        duration = time.time() - start_time
        return -1, str(e), duration


def main():
    """Main entry point for continuous YP scraper."""
    global shutdown_requested

    # Setup signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    email_service = EmailAlertService()
    consecutive_failures = 0
    total_cycles = 0
    alert_sent = False

    logger.info("=" * 60)
    logger.info(f"Starting {SCRAPER_NAME} Continuous Scraper Service")
    logger.info("=" * 60)
    logger.info(f"Cooldown between cycles: {COOLDOWN_SECONDS}s ({COOLDOWN_SECONDS/3600:.1f} hours)")
    logger.info(f"Failure alert threshold: {FAILURE_ALERT_THRESHOLD}")
    logger.info(f"Email alerts enabled: {email_service.enabled}")
    logger.info("=" * 60)

    # Optional: Send startup notification
    # email_service.send_startup_notification(SCRAPER_NAME)

    while not shutdown_requested:
        total_cycles += 1
        cycle_start = datetime.now()

        logger.info("")
        logger.info("=" * 60)
        logger.info(f"CYCLE {total_cycles} - Started at {cycle_start.isoformat()}")
        logger.info("=" * 60)

        exit_code, error_msg, duration = run_scraper()

        hours = duration / 3600
        logger.info(f"Cycle {total_cycles} completed in {hours:.2f} hours ({duration:.0f}s)")

        if exit_code == 0:
            logger.info(f"Cycle {total_cycles} completed SUCCESSFULLY")

            # Recovery notification if we had failures
            if consecutive_failures >= FAILURE_ALERT_THRESHOLD and alert_sent:
                logger.info("Sending recovery notification...")
                email_service.send_recovery_alert(SCRAPER_NAME)
                alert_sent = False

            consecutive_failures = 0

            # Full cooldown on success
            if not shutdown_requested:
                logger.info(f"Cooldown: waiting {COOLDOWN_SECONDS}s ({COOLDOWN_SECONDS/3600:.1f} hours) before next cycle...")
                for _ in range(COOLDOWN_SECONDS):
                    if shutdown_requested:
                        break
                    time.sleep(1)

        else:
            consecutive_failures += 1
            logger.error(f"Cycle {total_cycles} FAILED (exit={exit_code})")
            logger.error(f"Consecutive failures: {consecutive_failures}")
            logger.error(f"Error: {error_msg[:500] if error_msg else 'No error message'}")

            # Send alert if threshold reached
            if consecutive_failures >= FAILURE_ALERT_THRESHOLD and not alert_sent:
                logger.warning(f"Sending failure alert (threshold {FAILURE_ALERT_THRESHOLD} reached)...")
                email_service.send_scraper_failure_alert(SCRAPER_NAME, consecutive_failures, error_msg)
                alert_sent = True
                logger.warning("Alert email sent")

            # Short delay on failure before retry
            if not shutdown_requested:
                logger.info(f"Short retry delay: waiting {SHORT_RETRY_DELAY}s before retry...")
                for _ in range(SHORT_RETRY_DELAY):
                    if shutdown_requested:
                        break
                    time.sleep(1)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Graceful shutdown complete")
    logger.info(f"Total cycles run: {total_cycles}")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
