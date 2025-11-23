"""
Configuration for Washdb-Bot GUI Backend

Loads settings from environment variables with sensible defaults.
Separate from Nathan SEO Bot dashboard configuration.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from parent .env file
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)


class Config:
    """
    Base configuration for Flask GUI backend.

    All settings can be overridden via environment variables in .env file.

    Key Configuration:
        - GUI_PORT: Flask backend port (default: 5001)
        - NICEGUI_PORT: NiceGUI dashboard port (default: 8080)
        - CORS_ORIGINS: Allowed CORS origins for API calls
        - DATABASE_URL: PostgreSQL connection string
        - LOG_DIR: Log file directory (default: logs/)

    Port Strategy:
        - Port 5000: Reserved for Nathan SEO Bot dashboard
        - Port 5001: Flask backend (this service)
        - Port 8080: NiceGUI dashboard (primary UI)
    """

    # Flask settings
    ENV = os.getenv('FLASK_ENV', 'development')
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

    # Server settings
    HOST = os.getenv('GUI_HOST', '127.0.0.1')  # Localhost only
    PORT = int(os.getenv('GUI_PORT', '5001'))  # Different from Nathan SEO Bot (5000)

    # Database settings (washdb-bot PostgreSQL only)
    DATABASE_URL = os.getenv(
        'DATABASE_URL',
        'postgresql+psycopg://washbot:ScraperPass123@localhost:5432/washdb'
    )

    # API settings
    API_TITLE = 'Washdb-Bot API'
    API_VERSION = '1.0.0'

    # CORS settings
    # Default allows local NiceGUI (port 8080) and Flask backend (port 5001) to communicate
    CORS_ORIGINS = os.getenv(
        'CORS_ORIGINS',
        'http://127.0.0.1:8080,http://localhost:8080,http://127.0.0.1:5001,http://localhost:5001'
    ).split(',')

    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_DIR = Path(__file__).parent.parent / 'logs'

    # Pagination
    DEFAULT_PAGE_SIZE = int(os.getenv('DEFAULT_PAGE_SIZE', '50'))
    MAX_PAGE_SIZE = int(os.getenv('MAX_PAGE_SIZE', '1000'))

    # Session settings
    SESSION_TIMEOUT = int(os.getenv('SESSION_TIMEOUT', '3600'))  # 1 hour

    @classmethod
    def validate(cls):
        """
        Validate configuration and ensure required resources exist.

        Checks:
            - Log directory exists (creates if missing)
            - DATABASE_URL is set
            - Port 5001 is used (not 5000 which conflicts with Nathan SEO Bot)

        Raises:
            ValueError: If any validation checks fail

        Returns:
            bool: True if all validations pass
        """
        errors = []

        # Ensure log directory exists
        cls.LOG_DIR.mkdir(parents=True, exist_ok=True)

        # Validate database URL
        if not cls.DATABASE_URL:
            errors.append("DATABASE_URL is not set")

        # Validate port is not in use by other services
        if cls.PORT == 5000:
            errors.append("Port 5000 is used by Nathan SEO Bot dashboard. Use a different port.")

        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")

        return True


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    ENV = 'development'


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    ENV = 'production'
    # Override with secure secret key in production
    SECRET_KEY = os.getenv('SECRET_KEY')

    @classmethod
    def validate(cls):
        """Additional production validation."""
        super().validate()

        if cls.SECRET_KEY == 'dev-secret-key-change-in-production':
            raise ValueError("Must set SECRET_KEY in production")


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
