/**
 * PC ↔ 웹앱 데이터 동기화 (일정·회원·메모·다이어리)
 *
 *  - 모든 데이터는 records 표에 기기별로 저장 (kind + uid)
 *  - 바뀔 때마다 기기의 rev(번호)가 올라가고, 각 기록에 그 번호가 붙음 → "since 이후 바뀐 것"만 주고받음
 *  - 일정이 바뀌면 그 일정의 폰 알림(alarms 표)을 서버가 직접 다시 계산 → PC가 꺼져 있어도 폰에서 등록한 일정 알림이 감
 */
export const KINDS = ["schedule", "member", "note", "diary"];
const nowSec = () => Math.floor(Date.now() / 1000);
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const TIME_RE = /^\d{2}:\d{2}$/;
const AT_RE = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/;
const STAMP_RE = /^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}(:\d{2})?)?$/;
export const validToken = (t) => typeof t === "string" && /^[A-Za-z0-9_-]{16,64}$/.test(t);

export function validUid(kind, uid) {
  if (typeof uid !== "string") return false;
  return kind === "diary" ? DATE_RE.test(uid) : /^[a-z0-9]{6,40}$/.test(uid);
}

const str = (v, n) => String(v == null ? "" : v).slice(0, n);
const stampOr = (v) => (typeof v === "string" && STAMP_RE.test(v) ? v : "");

/** 들어온 데이터 정리 (모양이 이상하면 null) */
export function cleanData(kind, d) {
  if (!d || typeof d !== "object") return null;
  if (kind === "schedule") {
    if (!DATE_RE.test(d.date || "") || !TIME_RE.test(d.time || "")) return null;
    const alarms = [];
    for (const a of Array.isArray(d.alarms) ? d.alarms.slice(0, 60) : []) {
      if (!a || !AT_RE.test(a.at || "")) continue;
      const off = a.offset === null || a.offset === undefined || a.offset === "" ? null : Math.trunc(Number(a.offset));
      let ts = Math.trunc(Number(a.ts));
      if (!Number.isFinite(ts) || ts <= 0) ts = Math.floor(Date.parse(a.at.replace(" ", "T") + ":00+09:00") / 1000);
      if (!Number.isFinite(ts)) continue;
      alarms.push({ offset: Number.isFinite(off) ? off : null, at: a.at, ts, notified: a.notified ? 1 : 0 });
    }
    return {
      date: d.date, time: d.time, title: str(d.title, 300), content: str(d.content, 20000),
      member: typeof d.member === "string" && /^[a-z0-9]{6,40}$/.test(d.member) ? d.member : null,
      done: d.done ? 1 : 0, alarms,
    };
  }
  if (kind === "member") {
    const sort = Number(d.sort);
    return {
      name: str(d.name, 100), phone: str(d.phone, 40), keyword: str(d.keyword, 1000), memo: str(d.memo, 300000),
      color: typeof d.color === "string" && /^#[0-9A-Fa-f]{6}$/.test(d.color) ? d.color : "",
      sort: Number.isFinite(sort) ? sort : 0, created: stampOr(d.created), updated: stampOr(d.updated),
    };
  }
  if (kind === "note") return { title: str(d.title, 300), content: str(d.content, 200000), updated: stampOr(d.updated) };
  if (kind === "diary") return { content: str(d.content, 100000) };
  return null;
}

/** 기록 여러 개 저장 (쿼리 수가 데이터 개수와 상관없이 일정하도록 json_each 사용). 반환: 새 rev */
export async function writeRecords(env, device, items, src) {
  const map = new Map();
  for (const it of items) map.set(it.kind + "|" + it.uid, it);   // 같은 것이 여러 번 오면 마지막 것
  const list = [...map.values()].map((it) => ({
    k: it.kind, u: it.uid, x: it.deleted ? 1 : 0, d: it.deleted ? "{}" : JSON.stringify(it.data),
  }));
  if (!list.length) return null;
  const n = list.length;
  const res = await env.DB.batch([
    env.DB.prepare("INSERT OR IGNORE INTO devices(device, created) VALUES(?, ?)").bind(device, nowSec()),
    env.DB.prepare("UPDATE devices SET rev = rev + ? WHERE device = ?").bind(n, device),
    env.DB.prepare(
      `INSERT INTO records(device, kind, uid, data, deleted, rev, src, updated)
       SELECT ?1, json_extract(value, '$.k'), json_extract(value, '$.u'), json_extract(value, '$.d'),
              json_extract(value, '$.x'), (SELECT rev FROM devices WHERE device = ?1) - ?2 + key + 1, ?3, ?4
       FROM json_each(?5) WHERE 1
       ON CONFLICT(device, kind, uid) DO UPDATE SET
         data = excluded.data, deleted = excluded.deleted, rev = excluded.rev, src = excluded.src, updated = excluded.updated`
    ).bind(device, n, src, nowSec(), JSON.stringify(list)),
    env.DB.prepare("SELECT rev FROM devices WHERE device = ?").bind(device),
  ]);
  return res[3].results[0]?.rev ?? null;
}

/** 받은 변경 목록 → 검사해서 저장용 목록으로 */
export function parseChanges(changes) {
  const out = [];
  for (const c of Array.isArray(changes) ? changes : []) {
    if (!c || !KINDS.includes(c.kind) || !validUid(c.kind, c.uid)) continue;
    if (c.deleted) { out.push({ kind: c.kind, uid: c.uid, deleted: true }); continue; }
    const data = cleanData(c.kind, c.data);
    if (data) out.push({ kind: c.kind, uid: c.uid, data });
  }
  return out;
}

// ───────────── 폰 알림 계산 ─────────────
const WEEK = ["일", "월", "화", "수", "목", "금", "토"];
export function offsetLabel(m) {
  if (m === 0) return "정시";
  if (m === 1440) return "하루 전";
  if (m % 1440 === 0) return `${m / 1440}일 전`;
  if (m % 60 === 0) return `${m / 60}시간 전`;
  if (m > 60) return `${Math.floor(m / 60)}시간 ${m % 60}분 전`;
  return `${m}분 전`;
}

/** 일정 → 폰 알림 목록 (PC 프로그램과 같은 문구) */
export function alarmsFor(uid, s, member) {
  const out = [];
  if (!s || s.done) return out;
  const wd = WEEK[new Date(s.date + "T00:00:00Z").getUTCDay()];
  const now = nowSec();
  const seen = new Set();
  for (const a of s.alarms || []) {
    if (!(a.ts > now) || seen.has(a.ts)) continue;
    seen.add(a.ts);
    let msg = `일정 ${s.date} (${wd}) ${s.time}`;
    if (a.offset) msg += `  ·  ${offsetLabel(a.offset)} 알림`;
    if (member && (member.name || member.phone)) msg += `\n${member.name || ""}  ${member.phone || ""}`;
    if ((s.content || "").trim()) msg += `\n${s.content.trim()}`;
    out.push({ s: `${uid}:${a.ts}`, f: a.ts, t: `⏰ ${s.title}`.slice(0, 200), m: msg.slice(0, 2000) });
  }
  return out;
}

/**
 * 일정들의 폰 알림을 다시 계산. uids=null 이면 이 기기의 모든 일정.
 * (이미 보낸 알림은 그대로 두고, 아직 안 울린 것만 바꿈)
 */
export async function deriveAlarms(env, device, uids) {
  const dv = await env.DB.prepare("SELECT phone, topic FROM devices WHERE device = ?").bind(device).first();
  const phoneOn = dv ? !!dv.phone : true;
  const topic = dv?.topic || "";
  let rows;
  if (uids === null) {
    rows = (await env.DB.prepare("SELECT uid, data, deleted FROM records WHERE device = ? AND kind = 'schedule'")
      .bind(device).all()).results;
  } else {
    if (!uids.length) return;
    rows = (await env.DB.prepare(
      `SELECT uid, data, deleted FROM records WHERE device = ? AND kind = 'schedule'
       AND uid IN (SELECT value FROM json_each(?))`).bind(device, JSON.stringify(uids)).all()).results;
    const found = new Set(rows.map((r) => r.uid));
    for (const u of uids) if (!found.has(u)) rows.push({ uid: u, data: "{}", deleted: 1 });
  }
  const scheds = rows.map((r) => ({ uid: r.uid, deleted: !!r.deleted, s: r.deleted ? null : safeParse(r.data) }));
  const mids = [...new Set(scheds.map((x) => x.s?.member).filter(Boolean))];
  const members = new Map();
  if (mids.length) {
    const { results } = await env.DB.prepare(
      `SELECT uid, data FROM records WHERE device = ? AND kind = 'member' AND deleted = 0
       AND uid IN (SELECT value FROM json_each(?))`).bind(device, JSON.stringify(mids)).all();
    for (const r of results) members.set(r.uid, safeParse(r.data));
  }
  const want = [];
  if (phoneOn) for (const x of scheds) if (!x.deleted) want.push(...alarmsFor(x.uid, x.s, members.get(x.s?.member)));
  const now = nowSec();
  const stmts = [];
  if (uids === null) {
    stmts.push(env.DB.prepare(
      `DELETE FROM alarms WHERE device = ?1 AND sent = 0 AND fire_at > ?2 AND typeof(sid) = 'text'
       AND sid NOT IN (SELECT json_extract(value, '$.s') FROM json_each(?3))`).bind(device, now, JSON.stringify(want)));
  } else {
    stmts.push(env.DB.prepare(
      `DELETE FROM alarms WHERE device = ?1 AND sent = 0 AND fire_at > ?2 AND typeof(sid) = 'text'
       AND substr(sid, 1, instr(sid, ':') - 1) IN (SELECT value FROM json_each(?3))
       AND sid NOT IN (SELECT json_extract(value, '$.s') FROM json_each(?4))`)
      .bind(device, now, JSON.stringify(scheds.map((x) => x.uid)), JSON.stringify(want)));
  }
  if (want.length) {
    stmts.push(env.DB.prepare(
      `INSERT INTO alarms(device, sid, topic, fire_at, title, message, sent)
       SELECT ?1, json_extract(value, '$.s'), ?2, json_extract(value, '$.f'), json_extract(value, '$.t'),
              json_extract(value, '$.m'), 0
       FROM json_each(?3) WHERE 1
       ON CONFLICT(device, sid) DO UPDATE SET topic = excluded.topic, title = excluded.title, message = excluded.message`
    ).bind(device, topic, JSON.stringify(want)));
  }
  await env.DB.batch(stmts);
}

/** 바뀐 기록들 중 알림을 다시 계산해야 하는 일정 uid 목록 (회원 이름·번호가 바뀌면 그 회원 일정도) */
export async function affectedSchedules(env, device, items) {
  const set = new Set(items.filter((i) => i.kind === "schedule").map((i) => i.uid));
  const mids = items.filter((i) => i.kind === "member").map((i) => i.uid);
  if (mids.length) {
    const { results } = await env.DB.prepare(
      `SELECT uid FROM records WHERE device = ? AND kind = 'schedule' AND deleted = 0
       AND json_extract(data, '$.member') IN (SELECT value FROM json_each(?))`).bind(device, JSON.stringify(mids)).all();
    for (const r of results) set.add(r.uid);
  }
  return [...set];
}

/** since 이후 바뀐 기록 (exceptSrc 가 쓴 것은 제외) */
export async function changesSince(env, device, since, exceptSrc, limit, upto) {
  const q = since > 0
    ? env.DB.prepare(`SELECT kind, uid, data, deleted, rev FROM records WHERE device = ? AND rev > ? AND rev <= ? AND src <> ?
                      ORDER BY rev LIMIT ?`).bind(device, since, upto, exceptSrc || "-", limit)
    : env.DB.prepare(`SELECT kind, uid, data, deleted, rev FROM records WHERE device = ? AND deleted = 0 AND rev <= ? AND src <> ?
                      ORDER BY rev LIMIT ?`).bind(device, upto, exceptSrc || "-", limit);
  const { results } = await q.all();
  return results.map((r) => ({ kind: r.kind, uid: r.uid, rev: r.rev, deleted: !!r.deleted,
                               data: r.deleted ? null : safeParse(r.data) }));
}

export async function deviceRev(env, device) {
  const r = await env.DB.prepare("SELECT rev FROM devices WHERE device = ?").bind(device).first();
  return r?.rev || 0;
}

function safeParse(t) {
  try { return JSON.parse(t); } catch (e) { return {}; }
}
