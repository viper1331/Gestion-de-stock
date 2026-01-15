-- Ajout des colonnes 2FA et des tables de confiance (SQLite)
ALTER TABLE users ADD COLUMN two_factor_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN two_factor_secret_enc TEXT;
ALTER TABLE users ADD COLUMN two_factor_confirmed_at TEXT;
ALTER TABLE users ADD COLUMN two_factor_recovery_hashes TEXT;
ALTER TABLE users ADD COLUMN two_factor_last_used_at TEXT;
ALTER TABLE users ADD COLUMN two_factor_required INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS user_trusted_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    device_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT,
    UNIQUE(username, device_id)
);

CREATE INDEX IF NOT EXISTS idx_user_trusted_devices_lookup
ON user_trusted_devices(username, device_id);

CREATE TABLE IF NOT EXISTS two_factor_rate_limits (
    username TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    window_start_ts INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (username, ip_address)
);
