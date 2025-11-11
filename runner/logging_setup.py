"""
Logging setup for washdb-bot.

This module provides:
- Centralized logging configuration
- Console and file handlers
- Log rotation
"""

import logging
import os
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv


# Load environment
load_dotenv()


def setup_logging(
    name: str = "washdb-bot",
    log_level: str = None,
    log_file: str = None,
) -> logging.Logger:
    """
    Setup logging with console and file handlers.

    Args:
        name: Logger name (default: "washdb-bot")
        log_level: Log level (default: from LOG_LEVEL env var or INFO)
        log_file: Log file path (default: logs/{name}.log)

    Returns:
        Configured logger instance
    """
    # Get log level from environment if not specified
    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    # Convert string to logging level
    numeric_level = getattr(logging, log_level, logging.INFO)

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create formatters
    console_formatter = logging.Formatter(
        "%(levelname)s - %(message)s"
    )

    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler (with rotation)
    if log_file is None:
        # Default to /opt/ai-seo/logs/url-scrape-bot/{name}.log
        logs_dir = Path("/opt/ai-seo/logs/url-scrape-bot")
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / f"{name}.log"

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    logger.info(f"Logging initialized: level={log_level}, file={log_file}")

    return logger


def get_logger(name: str = "washdb-bot") -> logging.Logger:
    """
    Get or create a logger instance.

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)

    # If logger hasn't been setup, initialize it
    if not logger.handlers:
        setup_logging(name)

    return logger
