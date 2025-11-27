"""
SMTP-based email alert service for scraper monitoring.

Sends alerts when scrapers fail repeatedly and recovery notifications
when they resume normal operation.
"""
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import os
import socket
from pathlib import Path

# Load .env file
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)


class EmailAlertService:
    """
    Email alert service using SMTP.

    Configuration via environment variables:
        SMTP_HOST: SMTP server hostname (default: smtp.gmail.com)
        SMTP_PORT: SMTP server port (default: 587)
        SMTP_USER: SMTP username/email
        SMTP_PASSWORD: SMTP password (use app password for Gmail)
        ALERT_EMAIL: Recipient email address for alerts
    """

    def __init__(self):
        self.smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.smtp_user = os.getenv('SMTP_USER')
        self.smtp_password = os.getenv('SMTP_PASSWORD')
        self.alert_to = os.getenv('ALERT_EMAIL')
        self.alert_from = os.getenv('SMTP_USER')
        self.enabled = all([self.smtp_user, self.smtp_password, self.alert_to])

        if not self.enabled:
            print("EmailAlertService: Disabled (missing SMTP_USER, SMTP_PASSWORD, or ALERT_EMAIL)")

    def send_alert(self, subject: str, body: str) -> bool:
        """
        Send email alert.

        Args:
            subject: Email subject (will be prefixed with [WASHBOT ALERT])
            body: Email body text

        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.enabled:
            print(f"EmailAlertService: Would send alert '{subject}' but email is disabled")
            return False

        msg = MIMEMultipart()
        msg['From'] = self.alert_from
        msg['To'] = self.alert_to
        msg['Subject'] = f"[WASHBOT ALERT] {subject}"

        # Add timestamp and server info to body
        hostname = socket.gethostname()
        full_body = f"{body}\n\n---\nTimestamp: {datetime.now().isoformat()}\nServer: {hostname}"
        msg.attach(MIMEText(full_body, 'plain'))

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls(context=context)
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.alert_from, self.alert_to, msg.as_string())
            print(f"EmailAlertService: Alert sent - {subject}")
            return True
        except Exception as e:
            print(f"EmailAlertService: Failed to send alert - {e}")
            return False

    def send_scraper_failure_alert(self, scraper_name: str, consecutive_failures: int, last_error: str) -> bool:
        """
        Send alert for scraper failures.

        Args:
            scraper_name: Name of the scraper (e.g., "YP", "Google")
            consecutive_failures: Number of consecutive failures
            last_error: Last error message (truncated)

        Returns:
            True if email sent successfully
        """
        subject = f"{scraper_name} Scraper - {consecutive_failures} Consecutive Failures"
        body = f"""The {scraper_name} scraper has failed {consecutive_failures} times in a row.

Last Error:
{last_error[:1500]}

Action Required:
- Check the logs at /home/rivercityscrape/URL-Scrape-Bot/washdb-bot/logs/
- Review if the scraper needs manual intervention
- The service will continue attempting restarts automatically

Service Status Commands:
  sudo systemctl status washbot-{scraper_name.lower()}-scraper
  journalctl -u washbot-{scraper_name.lower()}-scraper -n 100
"""
        return self.send_alert(subject, body)

    def send_recovery_alert(self, scraper_name: str) -> bool:
        """
        Send alert when scraper recovers after failures.

        Args:
            scraper_name: Name of the scraper

        Returns:
            True if email sent successfully
        """
        subject = f"{scraper_name} Scraper - Recovered"
        body = f"""The {scraper_name} scraper has recovered and is running normally again.

No action required. This is a notification that the previous failure condition has been resolved.
"""
        return self.send_alert(subject, body)

    def send_cycle_summary(self, scraper_name: str, cycle_num: int,
                           duration_seconds: float, items_processed: int,
                           items_saved: int, errors: int) -> bool:
        """
        Send cycle completion summary (optional, for monitoring).

        Args:
            scraper_name: Name of the scraper
            cycle_num: Cycle number
            duration_seconds: How long the cycle took
            items_processed: Number of items processed
            items_saved: Number of items saved to database
            errors: Number of errors encountered

        Returns:
            True if email sent successfully
        """
        hours = duration_seconds / 3600
        subject = f"{scraper_name} Scraper - Cycle {cycle_num} Complete"
        body = f"""Cycle {cycle_num} completed for {scraper_name} scraper.

Summary:
- Duration: {hours:.1f} hours ({duration_seconds:.0f} seconds)
- Items Processed: {items_processed}
- Items Saved: {items_saved}
- Errors: {errors}

The scraper will now enter cooldown before starting the next cycle.
"""
        return self.send_alert(subject, body)

    def send_startup_notification(self, scraper_name: str) -> bool:
        """
        Send notification when scraper service starts.

        Args:
            scraper_name: Name of the scraper

        Returns:
            True if email sent successfully
        """
        subject = f"{scraper_name} Scraper - Service Started"
        body = f"""The {scraper_name} scraper service has started.

Configuration:
- Cooldown between cycles: 1 hour
- Alert threshold: 10 consecutive failures
- Auto-restart: Enabled (via systemd)

The scraper will now begin its first cycle.
"""
        return self.send_alert(subject, body)
