-- Migration 032: Safe schema alignment for city_registry
--
-- This migration aligns the database with SQLAlchemy models as source of truth.
-- It safely drops indexes/constraints that reference non-existent columns from
-- legacy migrations without dropping or recreating tables.
--
-- The SQLAlchemy CityRegistry model (db/models.py) uses:
--   - id (not city_id)
--   - priority (not tier)
--   - city_slug, yp_geo (not in old SQL migration)
--
-- This migration does NOT drop or recreate the table to preserve data.

-- Drop old indexes that may reference legacy column names (if they exist)
DROP INDEX IF EXISTS idx_city_registry_tier;
DROP INDEX IF EXISTS idx_city_registry_city_id;
DROP INDEX IF EXISTS idx_city_tier;

-- Document schema decision
COMMENT ON TABLE city_registry IS
'City registry for city-first crawling. Schema defined by SQLAlchemy models (db/models.py) - uses id, priority, city_slug, yp_geo. Migration 032 aligned schema.';
