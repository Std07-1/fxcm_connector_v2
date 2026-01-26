PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS bars_1m_final (
  symbol TEXT NOT NULL,
  open_time_ms INTEGER NOT NULL,
  close_time_ms INTEGER NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL NOT NULL,
  complete INTEGER NOT NULL,
  synthetic INTEGER NOT NULL,
  source TEXT NOT NULL,
  event_ts_ms INTEGER NOT NULL,
  ingest_ts_ms INTEGER NOT NULL,
  PRIMARY KEY (symbol, open_time_ms),
  CHECK (close_time_ms = open_time_ms + 60000 - 1),
  CHECK (complete = 1),
  CHECK (synthetic = 0),
  CHECK (event_ts_ms = close_time_ms),
  CHECK (source = 'history')
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tail_audit_marks (
  symbol TEXT NOT NULL,
  tf TEXT NOT NULL,
  window_hours INTEGER NOT NULL,
  checked_at_ms INTEGER NOT NULL,
  status TEXT NOT NULL,
  missing_bars INTEGER NOT NULL,
  next_allowed_check_ms INTEGER NOT NULL,
  PRIMARY KEY (symbol, tf, window_hours)
);

CREATE TABLE IF NOT EXISTS tail_audit_state (
  symbol TEXT NOT NULL,
  tf TEXT NOT NULL,
  verified_from_ms INTEGER NOT NULL,
  verified_until_ms INTEGER NOT NULL,
  checked_until_close_ms INTEGER NOT NULL,
  etag_last_complete_bar_ms INTEGER NOT NULL,
  last_audit_ts_ms INTEGER NOT NULL,
  updated_ts_ms INTEGER NOT NULL,
  PRIMARY KEY (symbol, tf)
);

CREATE INDEX IF NOT EXISTS idx_tail_audit_state_symbol_tf
  ON tail_audit_state (symbol, tf);

CREATE TABLE IF NOT EXISTS bars_htf_final (
  symbol TEXT NOT NULL,
  tf TEXT NOT NULL,
  open_time_ms INTEGER NOT NULL,
  close_time_ms INTEGER NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL NOT NULL,
  complete INTEGER NOT NULL,
  synthetic INTEGER NOT NULL,
  source TEXT NOT NULL,
  event_ts_ms INTEGER NOT NULL,
  ingest_ts_ms INTEGER NOT NULL,
  PRIMARY KEY (symbol, tf, open_time_ms),
  CHECK (complete = 1),
  CHECK (synthetic = 0),
  CHECK (source = 'history_agg'),
  CHECK (event_ts_ms = close_time_ms)
);

CREATE INDEX IF NOT EXISTS idx_bars_htf_symbol_tf_open_time
  ON bars_htf_final (symbol, tf, open_time_ms);

CREATE TABLE IF NOT EXISTS republish_marks (
  symbol TEXT NOT NULL,
  tf TEXT NOT NULL,
  window_hours INTEGER NOT NULL,
  last_republish_ts_ms INTEGER NOT NULL,
  next_allowed_republish_ms INTEGER NOT NULL,
  forced INTEGER NOT NULL,
  PRIMARY KEY (symbol, tf, window_hours)
);
