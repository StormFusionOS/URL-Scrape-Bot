#!/bin/bash
# Cleanup Script for Nathan SEO Bot Removal
# This script completes the removal of Nathan SEO Bot from the system

echo "============================================================================"
echo "Nathan SEO Bot Cleanup Script"
echo "============================================================================"
echo ""
echo "This script will:"
echo "  1. Drop the 'scraper' database (requires sudo/postgres access)"
echo "  2. Drop the 'scraper_user' database user"
echo "  3. Remove any remaining references"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Step 1: Dropping 'scraper' database..."
sudo -u postgres psql -c "DROP DATABASE IF EXISTS scraper;" && echo "✓ Database dropped" || echo "✗ Failed to drop database (may not exist or need manual removal)"

echo ""
echo "Step 2: Dropping 'scraper_user' database user..."
sudo -u postgres psql -c "DROP USER IF EXISTS scraper_user;" && echo "✓ User dropped" || echo "✗ Failed to drop user (may not exist or need manual removal)"

echo ""
echo "Step 3: Cleaning up any remaining files..."

# Remove backup tar if it exists
if [ -f "/home/rivercityscrape/ai_seo_scraper/seo_intelligence_backup.tar.gz" ]; then
    rm "/home/rivercityscrape/ai_seo_scraper/seo_intelligence_backup.tar.gz" && echo "✓ Removed backup file" || echo "✗ Could not remove backup"
fi

# Remove parent directory if empty
if [ -d "/home/rivercityscrape/ai_seo_scraper" ]; then
    if [ -z "$(ls -A /home/rivercityscrape/ai_seo_scraper)" ]; then
        rmdir "/home/rivercityscrape/ai_seo_scraper" && echo "✓ Removed empty ai_seo_scraper directory" || echo "✗ Could not remove parent directory"
    else
        echo "ℹ ai_seo_scraper directory not empty, keeping it"
    fi
fi

echo ""
echo "============================================================================"
echo "Cleanup Complete"
echo "============================================================================"
echo ""
echo "Summary of what was removed:"
echo "  ✓ /home/rivercityscrape/ai_seo_scraper/Nathan SEO Bot/ directory"
echo "  ✓ /home/rivercityscrape/URL-Scrape-Bot/washdb-bot/url_source_connector.py"
echo "  ✓ 'scraper' PostgreSQL database (if step 1 succeeded)"
echo "  ✓ 'scraper_user' PostgreSQL user (if step 2 succeeded)"
echo ""
echo "What remains active:"
echo "  ✓ washdb-bot with built-in SEO intelligence module"
echo "  ✓ washbot_db database with SEO tables (backlinks, citations, etc.)"
echo "  ✓ All SEO functionality via: python -m seo_intelligence"
echo ""
echo "To run SEO analysis:"
echo "  cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot"
echo "  python -m seo_intelligence --help"
echo ""
