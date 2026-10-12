CREATE TABLE IF NOT EXISTS alarms (
  device  TEXT    NOT NULL,
  sid     INTEGER NOT NULL,
  topic   TEXT    NOT NULL,
  fire_at INTEGER NOT NULL,          -- 유닉스 시간(초)
  title   TEXT    NOT NULL DEFAULT '',
  message TEXT    NOT NULL DEFAULT '',
  sent    INTEGER NOT NULL DEFAULT 0, -- 0 대기, 1 발송, 2 놓침
  PRIMARY KEY (device, sid)
);
CREATE INDEX IF NOT EXISTS idx_due ON alarms(sent, fire_at);
