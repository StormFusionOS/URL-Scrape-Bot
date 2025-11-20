-- Migration: Remove SEO Intelligence Tables
-- Created: 2025-11-20
-- Description: Removes 12 SEO Intelligence tables (system replaced by Nathan SEO Bot)
--
-- This migration removes all tables created by 005_add_seo_intelligence_tables.sql
-- The Nathan SEO Bot uses a separate database and is not affected.

-- Drop tables in reverse dependency order (child tables first)

-- Child tables with foreign keys
DROP TABLE IF EXISTS audit_issues CASCADE;
DROP TABLE IF EXISTS serp_results CASCADE;
DROP TABLE IF EXISTS competitor_pages CASCADE;

-- Parent tables
DROP TABLE IF EXISTS page_audits CASCADE;
DROP TABLE IF EXISTS serp_snapshots CASCADE;
DROP TABLE IF EXISTS search_queries CASCADE;
DROP TABLE IF EXISTS competitors CASCADE;
DROP TABLE IF EXISTS backlinks CASCADE;
DROP TABLE IF EXISTS referring_domains CASCADE;
DROP TABLE IF EXISTS citations CASCADE;
DROP TABLE IF EXISTS task_logs CASCADE;
DROP TABLE IF EXISTS change_log CASCADE;

-- Verification query (should return 0 rows after migration)
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'public'
-- AND table_name IN ('search_queries', 'serp_snapshots', 'serp_results',
--                     'competitors', 'competitor_pages', 'backlinks',
--                     'referring_domains', 'citations', 'page_audits',
--                     'audit_issues', 'task_logs', 'change_log');
