CREATE TABLE IF NOT EXISTS subtitle_items (
  id TEXT PRIMARY KEY,
  canonical_code TEXT NOT NULL,
  display_code TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT 'zh',
  format TEXT NOT NULL,
  duration_seconds INTEGER,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL UNIQUE,
  r2_key TEXT NOT NULL,
  uploaded_at INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  removed_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_subtitle_code_status
  ON subtitle_items(canonical_code, status, uploaded_at DESC);

CREATE INDEX IF NOT EXISTS idx_subtitle_sha
  ON subtitle_items(sha256);
