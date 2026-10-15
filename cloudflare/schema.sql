CREATE TABLE IF NOT EXISTS alarms (
  device  TEXT    NOT NULL,
  sid     INTEGER NOT NULL,
  topic   TEXT    NOT NULL DEFAULT '',
  fire_at INTEGER NOT NULL,          -- 유닉스 시간(초)
  title   TEXT    NOT NULL DEFAULT '',
  message TEXT    NOT NULL DEFAULT '',
  sent    INTEGER NOT NULL DEFAULT 0, -- 0 대기, 1 발송, 2 놓침, 3 받을 폰 없음
  PRIMARY KEY (device, sid)
);
CREATE INDEX IF NOT EXISTS idx_due ON alarms(sent, fire_at);

-- 웹앱 푸시를 받는 폰 목록
CREATE TABLE IF NOT EXISTS subscriptions (
  endpoint TEXT PRIMARY KEY,
  device   TEXT NOT NULL,
  p256dh   TEXT NOT NULL,
  auth     TEXT NOT NULL,
  ua       TEXT DEFAULT '',
  created  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sub_device ON subscriptions(device);

-- 발송 기록 (문제 원인 확인용)
CREATE TABLE IF NOT EXISTS push_log (
  device TEXT, at INTEGER, target TEXT, status INTEGER, info TEXT
);
CREATE INDEX IF NOT EXISTS idx_log_device ON push_log(device, at);

-- 텔레그램 공용 봇 연결 (기기 ↔ 채팅)
CREATE TABLE IF NOT EXISTS tg_links (
  device  TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  name    TEXT DEFAULT '',
  created INTEGER,
  PRIMARY KEY (device, chat_id)
);
CREATE INDEX IF NOT EXISTS idx_tg_chat ON tg_links(chat_id);

-- 기기별 알림 채널 선택 (웹앱 / 텔레그램)
CREATE TABLE IF NOT EXISTS prefs (
  device TEXT PRIMARY KEY,
  web    INTEGER DEFAULT 1,
  tg     INTEGER DEFAULT 1
);

-- PC ↔ 웹앱 데이터 동기화 (일정·회원·메모·다이어리)
CREATE TABLE IF NOT EXISTS devices (
  device  TEXT PRIMARY KEY,
  token   TEXT NOT NULL DEFAULT '',   -- 웹앱에서 보고 고칠 때 필요한 비밀 열쇠 (PC QR코드에 들어 있음)
  rev     INTEGER NOT NULL DEFAULT 0, -- 바뀔 때마다 1씩 증가
  phone   INTEGER NOT NULL DEFAULT 1, -- 폰 알림 켜짐
  topic   TEXT NOT NULL DEFAULT '',   -- ntfy 토픽 (예전 방식)
  created INTEGER
);
CREATE TABLE IF NOT EXISTS records (
  device  TEXT NOT NULL,
  kind    TEXT NOT NULL,              -- schedule / member / note / diary
  uid     TEXT NOT NULL,
  data    TEXT NOT NULL DEFAULT '{}', -- JSON
  deleted INTEGER NOT NULL DEFAULT 0,
  rev     INTEGER NOT NULL,
  src     TEXT NOT NULL DEFAULT '',   -- pc / web
  updated INTEGER,
  PRIMARY KEY (device, kind, uid)
);
CREATE INDEX IF NOT EXISTS idx_rec_rev ON records(device, rev);

-- 라이선스 (키 1개 = PC 1대)
CREATE TABLE IF NOT EXISTS licenses (
  key       TEXT PRIMARY KEY,           -- WD-XXXX-XXXX-XXXX
  name      TEXT NOT NULL DEFAULT '',   -- 사용자 이름 (관리자가 적은 것)
  user_name TEXT NOT NULL DEFAULT '',   -- 사용자가 키 입력할 때 직접 적은 이름
  memo      TEXT NOT NULL DEFAULT '',
  created   INTEGER,
  expires   INTEGER NOT NULL DEFAULT 0, -- 만료(유닉스 시간), 0 = 무제한
  revoked   INTEGER NOT NULL DEFAULT 0, -- 1 = 정지
  capture   INTEGER NOT NULL DEFAULT 0, -- 1 = 화면 캡처 허용
  owner     INTEGER NOT NULL DEFAULT 0, -- 1 = 관리자 본인 키
  device    TEXT,                       -- 연결된 프로그램(기기 ID)
  hwid      TEXT,                       -- 연결된 PC 고유값
  pc_name   TEXT NOT NULL DEFAULT '',
  bound_at  INTEGER,
  last_seen INTEGER,
  version   TEXT NOT NULL DEFAULT '',
  last_ip   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_lic_device ON licenses(device);
