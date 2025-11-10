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
    """GUI Backend configuration."""

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
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', 'http://localhost:5001').split(',')

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
        """Validate configuration."""
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
