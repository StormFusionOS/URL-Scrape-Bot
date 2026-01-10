#!/usr/bin/env python3
"""
Prepare comprehensive code review package for external review.
Includes: code, schema, configs, docs, stats - excludes: data, secrets, binaries.
"""

import os
import sys
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = Path.home() / "Downloads" / "washdb-code-review"

# Directories/files to EXCLUDE
EXCLUDE_PATTERNS = [
    "__pycache__",
    "*.pyc",
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "*.egg-info",
    ".pytest_cache",
    ".mypy_cache",
    "*.log",
    "*.jsonl",  # Training data
    "*.tar.gz",
    "*.zip",
    "*.sqlite",
    "*.db",
    "browser_profiles",
    "browser_sessions",
    "serp_sessions",
    "data/*/train.jsonl",
    "data/*/val.jsonl",
    ".env",
    ".env.*",
    "credentials*",
    "secrets*",
    "*.pem",
    "*.key",
]

# Important directories to include
INCLUDE_DIRS = [
    "src",
    "scripts",
    "db",
    "config",
    "api",
    "services",
    "utils",
    "tests",
    "dashboard",
    "runpod_training",
]

def run_cmd(cmd):
    """Run command and return output."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()
    except:
        return ""

def get_db_schema():
    """Export PostgreSQL schema."""
    schema = run_cmd("cd /mnt/work/projects/URL-Scrape-Bot/washdb-bot && ./venv/bin/python -c \"from db.database_manager import get_db_manager; db = get_db_manager(); print('Schema export would go here')\" 2>/dev/null")

    # Get actual schema via psql
    schema = run_cmd("sudo -u postgres psql -d washdb -c '\\dt' 2>/dev/null")
    schema += "\n\n" + run_cmd("sudo -u postgres psql -d washdb -c \"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = 'public' ORDER BY table_name, ordinal_position;\" 2>/dev/null")

    return schema

def get_db_stats():
    """Get database statistics."""
    stats = {}

    # Table counts
    tables_info = run_cmd("sudo -u postgres psql -d washdb -t -c \"SELECT tablename FROM pg_tables WHERE schemaname = 'public';\" 2>/dev/null")

    for table in tables_info.strip().split('\n'):
        table = table.strip()
        if table:
            count = run_cmd(f"sudo -u postgres psql -d washdb -t -c \"SELECT COUNT(*) FROM {table};\" 2>/dev/null")
            try:
                stats[table] = int(count.strip())
            except:
                stats[table] = "error"

    return stats

def get_service_status():
    """Get systemd service status."""
    services = [
        "washbot-dashboard",
        "washbot-worker",
        "yp-state-workers",
        "google-state-workers",
        "browser-watchdog",
        "ollama",
        "postgresql",
        "qdrant",
    ]

    status = {}
    for svc in services:
        result = run_cmd(f"systemctl is-active {svc} 2>/dev/null")
        status[svc] = result if result else "not found"

    return status

def get_crontab():
    """Get crontab entries."""
    return run_cmd("crontab -l 2>/dev/null")

def get_directory_structure():
    """Get project directory structure."""
    structure = run_cmd(f"cd {PROJECT_ROOT} && find . -type f -name '*.py' | head -200 | sort")
    return structure

def copy_code_files(src_dir, dest_dir):
    """Copy code files, excluding data and secrets."""
    copied = 0
    skipped = 0

    for root, dirs, files in os.walk(src_dir):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if d not in ["__pycache__", ".git", "node_modules", "venv", ".venv", "browser_profiles", "browser_sessions", "serp_sessions", ".pytest_cache"]]

        rel_root = Path(root).relative_to(src_dir)

        for file in files:
            src_file = Path(root) / file

            # Skip excluded files
            skip = False
            for pattern in EXCLUDE_PATTERNS:
                if pattern.startswith("*"):
                    if file.endswith(pattern[1:]):
                        skip = True
                        break
                elif pattern in str(src_file):
                    skip = True
                    break

            # Skip large files (> 1MB)
            try:
                if src_file.stat().st_size > 1024 * 1024:
                    skip = True
            except:
                pass

            if skip:
                skipped += 1
                continue

            # Copy file
            dest_file = dest_dir / rel_root / file
            dest_file.parent.mkdir(parents=True, exist_ok=True)

            try:
                shutil.copy2(src_file, dest_file)
                copied += 1
            except Exception as e:
                skipped += 1

    return copied, skipped

def main():
    print("=" * 60)
    print("PREPARING CODE REVIEW PACKAGE")
    print("=" * 60)
    print(f"Project: {PROJECT_ROOT}")
    print(f"Output: {OUTPUT_DIR}")

    # Clean and create output directory
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    # 1. Copy code files
    print("\n1. Copying code files...")
    code_dir = OUTPUT_DIR / "code"
    copied, skipped = copy_code_files(PROJECT_ROOT, code_dir)
    print(f"   Copied: {copied} files")
    print(f"   Skipped: {skipped} files")

    # 2. Database schema
    print("\n2. Exporting database schema...")
    schema = get_db_schema()
    (OUTPUT_DIR / "database").mkdir(exist_ok=True)
    with open(OUTPUT_DIR / "database" / "schema.txt", 'w') as f:
        f.write(schema)
    print("   Schema exported")

    # 3. Database statistics
    print("\n3. Getting database statistics...")
    db_stats = get_db_stats()
    with open(OUTPUT_DIR / "database" / "table_counts.json", 'w') as f:
        json.dump(db_stats, f, indent=2)
    print(f"   Tables: {len(db_stats)}")
    for table, count in sorted(db_stats.items()):
        print(f"      {table}: {count:,}" if isinstance(count, int) else f"      {table}: {count}")

    # 4. Service status
    print("\n4. Getting service status...")
    services = get_service_status()
    (OUTPUT_DIR / "system").mkdir(exist_ok=True)
    with open(OUTPUT_DIR / "system" / "services.json", 'w') as f:
        json.dump(services, f, indent=2)
    for svc, status in services.items():
        print(f"   {svc}: {status}")

    # 5. Crontab
    print("\n5. Exporting crontab...")
    crontab = get_crontab()
    with open(OUTPUT_DIR / "system" / "crontab.txt", 'w') as f:
        f.write(crontab)
    print("   Crontab exported")

    # 6. Directory structure
    print("\n6. Generating directory structure...")
    structure = get_directory_structure()
    with open(OUTPUT_DIR / "directory_structure.txt", 'w') as f:
        f.write(structure)
    print("   Structure exported")

    # 7. Environment info (sanitized)
    print("\n7. Creating environment summary...")
    env_info = {
        "project": "WashDB Bot",
        "purpose": "Business verification and data collection for exterior cleaning services",
        "python_version": run_cmd("python3 --version"),
        "os": run_cmd("uname -a"),
        "postgres_version": run_cmd("psql --version 2>/dev/null"),
        "storage_tiers": {
            "root": "/dev/sda (930GB SSD) - OS",
            "database": "/mnt/database (1.8TB NVMe) - PostgreSQL, Qdrant, Ollama",
            "work": "/mnt/work (1.8TB NVMe) - Projects, development",
            "scratch": "/mnt/scratch (1.8TB NVMe) - Temporary, browser profiles",
            "backup": "/mnt/backup (9.1TB HDD) - Archives, cold storage",
        },
        "key_components": [
            "PostgreSQL - Main database",
            "Qdrant - Vector search",
            "Ollama - Local LLM inference",
            "Playwright/Camoufox - Web scraping",
            "Claude API - Business verification",
            "Dashboard - Web UI for monitoring",
        ],
        "generated_at": datetime.now().isoformat(),
    }
    with open(OUTPUT_DIR / "environment.json", 'w') as f:
        json.dump(env_info, f, indent=2)

    # 8. README for reviewer
    print("\n8. Creating reviewer README...")
    readme = """# WashDB Bot - Code Review Package

## Overview
This package contains the complete codebase for WashDB Bot, a business verification and data collection system for exterior cleaning service providers.

## Package Contents

### /code/
Complete Python codebase including:
- `src/` - Core application modules
- `scripts/` - Utility and maintenance scripts
- `db/` - Database models and managers
- `api/` - API endpoints
- `services/` - Background services
- `dashboard/` - Web dashboard
- `runpod_training/` - ML fine-tuning scripts

### /database/
- `schema.txt` - PostgreSQL table structure
- `table_counts.json` - Row counts per table

### /system/
- `services.json` - Systemd service status
- `crontab.txt` - Scheduled tasks

### /environment.json
System configuration and architecture overview

### /directory_structure.txt
Complete file listing

## Key Areas for Review

1. **Database Design** (`/database/schema.txt`)
   - Table relationships
   - Index optimization
   - Data integrity

2. **Core Logic** (`/code/src/`)
   - Business verification pipeline
   - Web scraping implementation
   - Data processing workflows

3. **API Security** (`/code/api/`)
   - Authentication
   - Input validation
   - Rate limiting

4. **Background Services** (`/code/services/`)
   - Worker processes
   - Queue management
   - Error handling

5. **ML Pipeline** (`/code/runpod_training/`)
   - Training data preparation
   - Model configuration
   - Fine-tuning approach

## Questions to Consider

1. Are there any security vulnerabilities?
2. Is the database schema optimized?
3. Are there potential memory leaks or performance issues?
4. Is error handling comprehensive?
5. Are there any architectural improvements to suggest?
6. Is the code maintainable and well-structured?

## Notes

- Sensitive data (API keys, passwords) have been excluded
- Training data files (.jsonl) excluded due to size
- Log files excluded
- This is a production system actively running

Generated: """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(OUTPUT_DIR / "README.md", 'w') as f:
        f.write(readme)

    # 9. Create zip
    print("\n9. Creating zip archive...")
    zip_path = Path.home() / "Downloads" / "washdb-code-review.zip"
    if zip_path.exists():
        zip_path.unlink()

    shutil.make_archive(
        str(zip_path).replace('.zip', ''),
        'zip',
        OUTPUT_DIR.parent,
        OUTPUT_DIR.name
    )

    # Get final size
    zip_size = zip_path.stat().st_size / 1024 / 1024

    print("\n" + "=" * 60)
    print("CODE REVIEW PACKAGE READY")
    print("=" * 60)
    print(f"Zip file: {zip_path}")
    print(f"Size: {zip_size:.1f} MB")
    print(f"\nThis package is ready to share with ChatGPT Pro or any reviewer.")

    # Cleanup unzipped directory
    shutil.rmtree(OUTPUT_DIR)

    return str(zip_path)

if __name__ == "__main__":
    main()
