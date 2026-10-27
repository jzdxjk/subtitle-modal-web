CREATE TABLE IF NOT EXISTS public_upload_limits (
  bucket_key TEXT PRIMARY KEY,
  count INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_public_upload_limits_expiry
  ON public_upload_limits(expires_at);
