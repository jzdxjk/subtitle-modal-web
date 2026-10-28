CREATE TABLE IF NOT EXISTS pool_stats (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  subtitle_count INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO pool_stats (id, subtitle_count, updated_at)
SELECT 1, COUNT(*), CAST(strftime('%s', 'now') AS INTEGER) * 1000
FROM subtitle_items
WHERE status = 'active';

CREATE TRIGGER IF NOT EXISTS trg_pool_stats_insert
AFTER INSERT ON subtitle_items
WHEN NEW.status = 'active'
BEGIN
  UPDATE pool_stats
  SET subtitle_count = subtitle_count + 1,
      updated_at = CAST(strftime('%s', 'now') AS INTEGER) * 1000
  WHERE id = 1;
END;

CREATE TRIGGER IF NOT EXISTS trg_pool_stats_remove
AFTER UPDATE OF status ON subtitle_items
WHEN OLD.status = 'active' AND NEW.status <> 'active'
BEGIN
  UPDATE pool_stats
  SET subtitle_count = MAX(subtitle_count - 1, 0),
      updated_at = CAST(strftime('%s', 'now') AS INTEGER) * 1000
  WHERE id = 1;
END;

CREATE TRIGGER IF NOT EXISTS trg_pool_stats_delete
AFTER DELETE ON subtitle_items
WHEN OLD.status = 'active'
BEGIN
  UPDATE pool_stats
  SET subtitle_count = MAX(subtitle_count - 1, 0),
      updated_at = CAST(strftime('%s', 'now') AS INTEGER) * 1000
  WHERE id = 1;
END;
