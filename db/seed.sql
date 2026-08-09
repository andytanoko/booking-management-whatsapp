-- Booking Management WhatsApp - default seed data for a fresh install.
-- Run after db/schema.sql. Safe to re-run: all inserts are ON CONFLICT DO NOTHING.
--
-- Usage:
--   psql -U <user> -d <db> -f db/schema.sql
--   psql -U <user> -d <db> -f db/seed.sql

BEGIN;

-- Default first-run accounts (admin/admin123, cs1/cs123, tech1/tech123).
-- Same accounts app/app.py's seed_default_users() creates at every startup
-- (via the ORM, not this file) - keep both in sync if these ever change.
-- app/app.py lets these be overridden via SEED_ADMIN_PASSWORD/SEED_CS_PASSWORD/
-- SEED_TECH_PASSWORD env vars; this file always uses the hardcoded hashes below,
-- so only use it for local/dev setup, not production.
INSERT INTO "user" (username, password_hash, role, active, created_at) VALUES
  ('admin', 'pbkdf2:sha256:1000000$3gYIuAaeWfXXLWWK$b90f744128c62650736ba0d9b71caa98a177d9e65df5690679bd5d5c8d08a968', 'admin', true, CURRENT_TIMESTAMP),
  ('cs1',   'pbkdf2:sha256:1000000$HZw6YjQheumKOKGl$7ada73d77aca89d50014f73d03656ba26c1b6170d28b1d2954656a5243c74a59', 'cs', true, CURRENT_TIMESTAMP),
  ('tech1', 'pbkdf2:sha256:1000000$vD50zW2BvrvTrIr8$cba92e8d1bbe8b8596d0e3aab6048bfdc514650bddc06ab4d70bec876ee017df', 'technician', true, CURRENT_TIMESTAMP)
ON CONFLICT (username) DO NOTHING;

-- Default service catalog. after_service = "Maintenance" means completing that
-- service creates a maintenance_reminder (booking later routes to /maintenance
-- instead of /history). Duration is stored in minutes.
INSERT INTO service_type (name, duration_minutes, active, after_service, created_at) VALUES
  ('Interior Detailing', 480,  true, NULL,          CURRENT_TIMESTAMP),
  ('Polishing',          480,  true, NULL,          CURRENT_TIMESTAMP),
  ('PPF',                7200, true, 'Maintenance', CURRENT_TIMESTAMP),
  ('Coating Premium',    4320, true, 'Maintenance', CURRENT_TIMESTAMP),
  ('Glass Polishing',    120,  true, NULL,          CURRENT_TIMESTAMP),
  ('Cuci Mobil',         15,   true, NULL,          CURRENT_TIMESTAMP),
  ('Lainnya',            120,  true, NULL,          CURRENT_TIMESTAMP),
  ('Maintenance',        90,   true, 'Maintenance', CURRENT_TIMESTAMP)
ON CONFLICT (name) DO NOTHING;

-- Default Google Maps business URL shown in the review-request template.
INSERT INTO app_setting (key, value, updated_at) VALUES
  ('google_maps_business_url', 'https://maps.app.goo.gl/nETWsxQNNUmYjZSE6', CURRENT_TIMESTAMP)
ON CONFLICT (key) DO NOTHING;

COMMIT;
