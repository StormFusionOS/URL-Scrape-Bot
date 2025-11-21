#!/usr/bin/env python3
"""
Configuration Validator - Ensures all required environment variables are set.

This module prevents hardcoded credentials by validating that required
environment variables are present before application startup.

Usage:
    from config_validator import validate_database_config, get_db_url

    # Validate before connecting
    validate_database_config()

    # Get validated connection string
    db_url = get_db_url()
"""

import os
import sys
from typing import Dict, List, Optional
from pathlib import Path


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


def check_env_var(var_name: str, required: bool = True) -> Optional[str]:
    """
    Check if an environment variable is set.

    Args:
        var_name: Name of environment variable
        required: If True, raise error if not set

    Returns:
        Value of environment variable or None

    Raises:
        ConfigurationError: If required=True and variable not set
    """
    value = os.getenv(var_name)

    if required and not value:
        raise ConfigurationError(
            f"Required environment variable '{var_name}' is not set. "
            f"Please add it to your .env file or environment."
        )

    return value


def validate_database_config() -> Dict[str, str]:
    """
    Validate all required database configuration variables are set.

    Required variables:
        - DB_HOST: Database host (default: localhost)
        - DB_PORT: Database port (default: 5432)
        - DB_NAME: Database name (REQUIRED)
        - DB_USER: Database user (REQUIRED)
        - DB_PASSWORD: Database password (REQUIRED)

    Returns:
        Dictionary of validated configuration values

    Raises:
        ConfigurationError: If any required variable is missing
    """
    config = {}

    # Optional with defaults
    config['host'] = os.getenv('DB_HOST', 'localhost')
    config['port'] = os.getenv('DB_PORT', '5432')

    # Required
    config['name'] = check_env_var('DB_NAME', required=True)
    config['user'] = check_env_var('DB_USER', required=True)
    config['password'] = check_env_var('DB_PASSWORD', required=True)

    return config


def get_db_url(
    dialect: str = 'postgresql+psycopg',
    include_port: bool = True
) -> str:
    """
    Get database URL from environment variables.

    Args:
        dialect: SQLAlchemy dialect string (default: postgresql+psycopg)
        include_port: Include port in URL (default: True)

    Returns:
        Database connection string

    Raises:
        ConfigurationError: If required variables are missing
    """
    config = validate_database_config()

    if include_port:
        return (
            f"{dialect}://{config['user']}:{config['password']}"
            f"@{config['host']}:{config['port']}/{config['name']}"
        )
    else:
        return (
            f"{dialect}://{config['user']}:{config['password']}"
            f"@{config['host']}/{config['name']}"
        )


def get_psycopg_params() -> Dict[str, str]:
    """
    Get psycopg connection parameters from environment.

    Returns:
        Dictionary suitable for psycopg.connect(**params)

    Raises:
        ConfigurationError: If required variables are missing
    """
    config = validate_database_config()

    return {
        'host': config['host'],
        'port': int(config['port']),
        'database': config['name'],
        'user': config['user'],
        'password': config['password']
    }


def validate_secret_key(allow_dev_key: bool = False) -> str:
    """
    Validate Flask SECRET_KEY is set properly.

    Args:
        allow_dev_key: If True, allow development key (default: False)

    Returns:
        Validated secret key

    Raises:
        ConfigurationError: If secret key is missing or insecure
    """
    secret_key = os.getenv('SECRET_KEY')

    if not secret_key:
        raise ConfigurationError(
            "SECRET_KEY environment variable is not set. "
            "Generate one with: python3 -c 'import secrets; print(secrets.token_hex(32))'"
        )

    # Check for insecure dev key in production
    if not allow_dev_key:
        insecure_keys = [
            'dev-secret-key-change-in-production',
            'dev',
            'development',
            'test',
            'changeme'
        ]

        if secret_key.lower() in insecure_keys:
            raise ConfigurationError(
                f"Insecure SECRET_KEY detected: '{secret_key}'. "
                "Generate a secure key with: python3 -c 'import secrets; print(secrets.token_hex(32))'"
            )

    return secret_key


def validate_all_config(environment: str = 'development') -> bool:
    """
    Validate all application configuration.

    Args:
        environment: Environment name (development, production)

    Returns:
        True if all validations pass

    Raises:
        ConfigurationError: If any validation fails
    """
    errors = []

    # Validate database config
    try:
        validate_database_config()
    except ConfigurationError as e:
        errors.append(f"Database: {e}")

    # Validate secret key (strict in production)
    try:
        allow_dev = (environment == 'development')
        validate_secret_key(allow_dev_key=allow_dev)
    except ConfigurationError as e:
        errors.append(f"Secret Key: {e}")

    if errors:
        raise ConfigurationError(
            "Configuration validation failed:\n" + "\n".join(f"  - {err}" for err in errors)
        )

    return True


def print_config_status(hide_sensitive: bool = True) -> None:
    """
    Print current configuration status (useful for debugging).

    Args:
        hide_sensitive: If True, mask passwords and keys (default: True)
    """
    print("=" * 60)
    print("Configuration Status")
    print("=" * 60)

    # Database config
    try:
        config = validate_database_config()
        print("\n✅ Database Configuration:")
        print(f"  Host: {config['host']}")
        print(f"  Port: {config['port']}")
        print(f"  Database: {config['name']}")
        print(f"  User: {config['user']}")
        if hide_sensitive:
            print(f"  Password: {'*' * 8}")
        else:
            print(f"  Password: {config['password']}")
    except ConfigurationError as e:
        print(f"\n❌ Database Configuration: {e}")

    # Secret key
    try:
        secret_key = validate_secret_key(allow_dev_key=True)
        if hide_sensitive:
            print(f"\n✅ Secret Key: {'*' * 16}")
        else:
            print(f"\n✅ Secret Key: {secret_key}")
    except ConfigurationError as e:
        print(f"\n❌ Secret Key: {e}")

    print("\n" + "=" * 60)


def load_env_file(env_path: Optional[Path] = None) -> bool:
    """
    Load environment variables from .env file.

    Args:
        env_path: Path to .env file (default: .env in project root)

    Returns:
        True if .env file was loaded successfully
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("WARNING: python-dotenv not installed. Install with: pip install python-dotenv")
        return False

    if env_path is None:
        # Try to find .env in project root
        current = Path(__file__).parent
        env_path = current / '.env'

    if env_path.exists():
        load_dotenv(env_path)
        return True
    else:
        print(f"WARNING: .env file not found at {env_path}")
        return False


if __name__ == '__main__':
    """
    CLI tool to validate configuration.

    Usage:
        python3 config_validator.py               # Validate config
        python3 config_validator.py --status      # Show config status
        python3 config_validator.py --no-hide     # Show sensitive values
    """
    import argparse

    parser = argparse.ArgumentParser(description="Validate application configuration")
    parser.add_argument('--status', action='store_true', help="Print config status")
    parser.add_argument('--no-hide', action='store_true', help="Show sensitive values")
    parser.add_argument('--env', default='development', help="Environment (development/production)")

    args = parser.parse_args()

    # Load .env file
    load_env_file()

    try:
        if args.status:
            print_config_status(hide_sensitive=not args.no_hide)
        else:
            validate_all_config(environment=args.env)
            print("✅ All configuration validation checks passed!")

        sys.exit(0)

    except ConfigurationError as e:
        print(f"\n❌ Configuration Error:\n{e}\n")
        sys.exit(1)
