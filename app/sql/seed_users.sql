-- Default first-run accounts for a fresh install.
-- Passwords are stored as pbkdf2:sha256 hashes only (never plaintext) and are
-- generated with: generate_password_hash(raw_password, method="pbkdf2:sha256").
-- Change/remove these before deploying to a shared or production environment.
--
--   username | password
--   ---------|----------
--   admin    | admin123
--   cs1      | cs123
--   tech1    | tech123
--
-- Safe to re-run: existing usernames are left untouched.
INSERT INTO "user" (username, password_hash, role, active, created_at) VALUES
  ('admin', 'pbkdf2:sha256:1000000$3gYIuAaeWfXXLWWK$b90f744128c62650736ba0d9b71caa98a177d9e65df5690679bd5d5c8d08a968', 'admin', true, CURRENT_TIMESTAMP),
  ('cs1',   'pbkdf2:sha256:1000000$HZw6YjQheumKOKGl$7ada73d77aca89d50014f73d03656ba26c1b6170d28b1d2954656a5243c74a59', 'cs', true, CURRENT_TIMESTAMP),
  ('tech1', 'pbkdf2:sha256:1000000$vD50zW2BvrvTrIr8$cba92e8d1bbe8b8596d0e3aab6048bfdc514650bddc06ab4d70bec876ee017df', 'technician', true, CURRENT_TIMESTAMP)
ON CONFLICT(username) DO NOTHING;
