"""
Google Business Scraper - Sophisticated Logging Module

Provides comprehensive logging with JSON formatting and separate log files
for different aspects of the scraping process.

Features:
- JSON-formatted structured logging
- Separate log files for scraping, errors, metrics, and operations
- Context-aware logging with metadata
- Performance tracking
- Easy troubleshooting

Author: washdb-bot
Date: 2025-11-10
"""

import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from logging.handlers import RotatingFileHandler


class GoogleScraperLogger:
    """
    Sophisticated logging system for Google Business scraping operations.

    Creates 4 separate log files:
    - google_scrape.log: Main scraping operations
    - google_errors.log: Errors and exceptions only
    - google_metrics.log: Performance and quality metrics
    - google_operations.log: Business logic and operations
    """

    def __init__(self, log_dir: str = "logs"):
        """
        Initialize the logger with separate log files.

        Args:
            log_dir: Directory to store log files (default: logs/)
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Initialize loggers
        self.scrape_logger = self._setup_logger("google_scrape", "google_scrape.log")
        self.error_logger = self._setup_logger("google_errors", "google_errors.log", level=logging.ERROR)
        self.metrics_logger = self._setup_logger("google_metrics", "google_metrics.log")
        self.ops_logger = self._setup_logger("google_operations", "google_operations.log")

        # Track current operation context
        self.current_context: Dict[str, Any] = {}

    def _setup_logger(
        self,
        name: str,
        filename: str,
        level: int = logging.INFO,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5
    ) -> logging.Logger:
        """
        Set up a logger with rotating file handler.

        Args:
            name: Logger name
            filename: Log file name
            level: Logging level
            max_bytes: Max file size before rotation
            backup_count: Number of backup files to keep

        Returns:
            Configured logger instance
        """
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = False

        # Remove existing handlers
        logger.handlers = []

        # Create rotating file handler
        log_path = self.log_dir / filename
        handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count
        )
        handler.setLevel(level)

        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)

        logger.addHandler(handler)

        return logger

    def set_context(self, **kwargs):
        """
        Set context for subsequent log messages.

        Example:
            logger.set_context(company_id=123, search_term="car wash")
        """
        self.current_context.update(kwargs)

    def clear_context(self):
        """Clear the current logging context."""
        self.current_context = {}

    def _format_log_data(self, message: str, extra_data: Optional[Dict] = None) -> str:
        """
        Format log data as JSON with context.

        Args:
            message: Log message
            extra_data: Additional data to include

        Returns:
            JSON-formatted string
        """
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "message": message,
            **self.current_context
        }

        if extra_data:
            log_data.update(extra_data)

        return json.dumps(log_data)

    # Scraping Operations

    def scrape_started(self, search_term: str, location: str = None):
        """Log the start of a scraping operation."""
        data = {"search_term": search_term}
        if location:
            data["location"] = location
        msg = self._format_log_data("Scrape operation started", data)
        self.scrape_logger.info(msg)

    def scrape_completed(self, results_count: int, duration_seconds: float):
        """Log successful completion of scraping."""
        data = {
            "results_count": results_count,
            "duration_seconds": round(duration_seconds, 2),
            "status": "success"
        }
        msg = self._format_log_data("Scrape operation completed", data)
        self.scrape_logger.info(msg)

    def page_loaded(self, url: str, load_time_ms: int):
        """Log successful page load."""
        data = {"url": url, "load_time_ms": load_time_ms}
        msg = self._format_log_data("Page loaded successfully", data)
        self.scrape_logger.info(msg)

    def business_scraped(self, business_name: str, place_id: str, fields_extracted: list):
        """Log successful business data extraction."""
        data = {
            "business_name": business_name,
            "place_id": place_id,
            "fields_extracted": fields_extracted,
            "field_count": len(fields_extracted)
        }
        msg = self._format_log_data("Business data scraped", data)
        self.scrape_logger.info(msg)

    def rate_limit_wait(self, wait_seconds: int, reason: str = "standard"):
        """Log rate limiting wait."""
        data = {"wait_seconds": wait_seconds, "reason": reason}
        msg = self._format_log_data("Rate limiting - waiting", data)
        self.scrape_logger.info(msg)

    # Error Logging

    def error(self, message: str, error: Exception = None, context: Dict = None):
        """
        Log an error with full context.

        Args:
            message: Error description
            error: Exception object (if available)
            context: Additional context data
        """
        data = {"error_type": "general"}
        if error:
            data.update({
                "exception_type": type(error).__name__,
                "exception_message": str(error)
            })
        if context:
            data.update(context)

        msg = self._format_log_data(message, data)
        self.error_logger.error(msg)
        # Also log to scrape logger for complete audit trail
        self.scrape_logger.error(msg)

    def page_load_failed(self, url: str, error: Exception, attempt: int = 1):
        """Log page load failure."""
        data = {
            "url": url,
            "attempt": attempt,
            "error_type": type(error).__name__,
            "error_message": str(error)
        }
        msg = self._format_log_data("Page load failed", data)
        self.error_logger.error(msg)

    def parsing_error(self, field_name: str, error: Exception, html_snippet: str = None):
        """Log parsing/extraction error."""
        data = {
            "field_name": field_name,
            "error_type": type(error).__name__,
            "error_message": str(error)
        }
        if html_snippet:
            data["html_snippet"] = html_snippet[:200]  # First 200 chars
        msg = self._format_log_data("Parsing error", data)
        self.error_logger.error(msg)

    def database_error(self, operation: str, error: Exception, record_data: Dict = None):
        """Log database operation error."""
        data = {
            "operation": operation,
            "error_type": type(error).__name__,
            "error_message": str(error)
        }
        if record_data:
            data["record_data"] = record_data
        msg = self._format_log_data("Database error", data)
        self.error_logger.error(msg)

    def captcha_detected(self, url: str):
        """Log CAPTCHA detection (critical issue)."""
        data = {"url": url, "critical": True}
        msg = self._format_log_data("CAPTCHA DETECTED - Manual intervention required", data)
        self.error_logger.critical(msg)

    def rate_limit_exceeded(self, wait_seconds: int):
        """Log rate limit detection."""
        data = {"wait_seconds": wait_seconds, "critical": True}
        msg = self._format_log_data("Rate limit exceeded", data)
        self.error_logger.warning(msg)

    # Metrics Logging

    def quality_metrics(
        self,
        completeness_score: float,
        confidence_score: float,
        fields_populated: int,
        total_fields: int
    ):
        """Log data quality metrics."""
        data = {
            "completeness_score": round(completeness_score, 3),
            "confidence_score": round(confidence_score, 3),
            "fields_populated": fields_populated,
            "total_fields": total_fields,
            "coverage_pct": round((fields_populated / total_fields) * 100, 1)
        }
        msg = self._format_log_data("Quality metrics recorded", data)
        self.metrics_logger.info(msg)

    def performance_metrics(
        self,
        operation: str,
        duration_seconds: float,
        success: bool,
        items_processed: int = 0
    ):
        """Log performance metrics."""
        data = {
            "operation": operation,
            "duration_seconds": round(duration_seconds, 2),
            "success": success,
            "items_processed": items_processed
        }
        if items_processed > 0 and duration_seconds > 0:
            data["items_per_second"] = round(items_processed / duration_seconds, 2)
        msg = self._format_log_data("Performance metrics", data)
        self.metrics_logger.info(msg)

    def session_summary(
        self,
        total_scraped: int,
        successful: int,
        failed: int,
        duration_minutes: float,
        avg_quality_score: float
    ):
        """Log session summary metrics."""
        data = {
            "total_scraped": total_scraped,
            "successful": successful,
            "failed": failed,
            "success_rate_pct": round((successful / total_scraped) * 100, 1) if total_scraped > 0 else 0,
            "duration_minutes": round(duration_minutes, 2),
            "avg_quality_score": round(avg_quality_score, 3)
        }
        msg = self._format_log_data("Session summary", data)
        self.metrics_logger.info(msg)

    # Operations Logging

    def operation_started(self, operation: str, parameters: Dict = None):
        """Log start of business operation."""
        data = {"operation": operation}
        if parameters:
            data["parameters"] = parameters
        msg = self._format_log_data("Operation started", data)
        self.ops_logger.info(msg)

    def operation_completed(self, operation: str, result: str = "success"):
        """Log completion of business operation."""
        data = {"operation": operation, "result": result}
        msg = self._format_log_data("Operation completed", data)
        self.ops_logger.info(msg)

    def database_update(self, table: str, record_id: int, fields: list):
        """Log database update operation."""
        data = {
            "table": table,
            "record_id": record_id,
            "fields_updated": fields,
            "field_count": len(fields)
        }
        msg = self._format_log_data("Database record updated", data)
        self.ops_logger.info(msg)

    def duplicate_detected(self, identifier: str, identifier_type: str = "place_id"):
        """Log duplicate record detection."""
        data = {
            "identifier": identifier,
            "identifier_type": identifier_type,
            "action": "skip"
        }
        msg = self._format_log_data("Duplicate record detected", data)
        self.ops_logger.info(msg)

    def validation_failed(self, field_name: str, value: Any, reason: str):
        """Log data validation failure."""
        data = {
            "field_name": field_name,
            "value": str(value)[:100],  # Truncate long values
            "reason": reason
        }
        msg = self._format_log_data("Validation failed", data)
        self.ops_logger.warning(msg)

    # Utility methods

    def info(self, message: str, extra_data: Dict = None):
        """General info logging."""
        msg = self._format_log_data(message, extra_data)
        self.scrape_logger.info(msg)

    def warning(self, message: str, extra_data: Dict = None):
        """General warning logging."""
        msg = self._format_log_data(message, extra_data)
        self.scrape_logger.warning(msg)

    def debug(self, message: str, extra_data: Dict = None):
        """Debug logging."""
        msg = self._format_log_data(message, extra_data)
        self.scrape_logger.debug(msg)


# Convenience function for getting a logger instance
def get_logger(log_dir: str = "logs") -> GoogleScraperLogger:
    """
    Get a GoogleScraperLogger instance.

    Args:
        log_dir: Directory for log files

    Returns:
        GoogleScraperLogger instance
    """
    return GoogleScraperLogger(log_dir=log_dir)
