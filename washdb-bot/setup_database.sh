#!/bin/bash
# Database setup script for washdb-bot
# This script creates the PostgreSQL database and user

set -e

echo "============================================================"
echo "washdb-bot Database Setup"
echo "============================================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Database configuration from .env
DB_USER="washbot"
DB_PASSWORD="change_me_strong"
DB_NAME="washdb"

echo "This script will create:"
echo "  - PostgreSQL user: $DB_USER"
echo "  - PostgreSQL database: $DB_NAME"
echo "  - Grant necessary permissions"
echo ""
echo -e "${YELLOW}Note: This requires sudo access${NC}"
echo ""

# Check if PostgreSQL is running
if ! systemctl is-active --quiet postgresql; then
    echo -e "${RED}ERROR: PostgreSQL service is not running${NC}"
    echo "Start it with: sudo systemctl start postgresql"
    exit 1
fi

echo -e "${GREEN}✓${NC} PostgreSQL service is running"
echo ""

# Create user and database
echo "Creating database and user..."
echo ""

sudo -u postgres psql << EOF
-- Create user if not exists
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_user WHERE usename = '$DB_USER') THEN
        CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
        RAISE NOTICE 'User $DB_USER created';
    ELSE
        RAISE NOTICE 'User $DB_USER already exists';
    END IF;
END
\$\$;

-- Create database if not exists
SELECT 'CREATE DATABASE $DB_NAME OWNER $DB_USER'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\gexec

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;

-- Connect to washdb and grant schema permissions
\c $DB_NAME
GRANT ALL ON SCHEMA public TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $DB_USER;

-- Show result
\l $DB_NAME
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "============================================================"
    echo -e "${GREEN}Database setup complete!${NC}"
    echo "============================================================"
    echo ""
    echo "Next steps:"
    echo "  1. Initialize database tables:"
    echo "     source .venv/bin/activate"
    echo "     python -m db.init_db"
    echo ""
    echo "  2. Run the application:"
    echo "     python -m niceui.main"
    echo ""
else
    echo ""
    echo -e "${RED}ERROR: Database setup failed${NC}"
    exit 1
fi
