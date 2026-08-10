-- Booking Management WhatsApp - default seed data for a fresh install.
-- Run after db/schema.sql. Safe to re-run: all inserts are ON CONFLICT DO NOTHING.
--
-- Usage:
--   psql -U <user> -d <db> -f db/schema.sql
--   psql -U <user> -d <db> -f db/seed.sql

BEGIN;

-- Default users are created by app bootstrap (app/app.py) using environment
-- variables (SEED_ADMIN_PASSWORD / SEED_CS_PASSWORD / SEED_TECH_PASSWORD).
-- Keep this SQL seed password-free to avoid hardcoded credentials.

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
