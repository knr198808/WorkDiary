/**
 * 업무 다이어리 - 예약 푸시 알림 서버 (Cloudflare Worker + D1)
 *
 *  PC 프로그램 → POST /api/sync  : 이 PC의 "앞으로 울릴 알림 목록" 전체를 올림
 *  PC 프로그램 → POST /api/test  : 바로 테스트 알림 1건 발송
 *  Cron(1분마다)                 : 시간이 된 알림을 ntfy로 발송 → 폰 ntfy 앱에 알림
 *
 *  환경변수
 *    APP_KEY      (secret)  PC 프로그램의 WORKER_KEY 와 같은 값
 *    NTFY_SERVER  (var)     기본 https://ntfy.sh
 */

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8" } });

const nowSec = () => Math.floor(Date.now() / 1000);

async function ntfy(env, topic, title, message) {
  const server = (env.NTFY_SERVER || "https://ntfy.sh").replace(/\/+$/, "");
  const res = await fetch(server, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ topic, title, message, priority: 4, tags: ["alarm_clock"] }),
  });
  if (!res.ok) throw new Error(`ntfy ${res.status}: ${await res.text()}`);
}

const validTopic = (t) => typeof t === "string" && /^[A-Za-z0-9_-]{6,64}$/.test(t);

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname === "/") return json({ ok: true, service: "workdiary-push" });

    if (env.APP_KEY && req.headers.get("X-App-Key") !== env.APP_KEY) return json({ error: "unauthorized" }, 401);
    if (req.method !== "POST") return json({ error: "method" }, 405);

    let body;
    try {
      body = await req.json();
    } catch {
      return json({ error: "bad json" }, 400);
    }

    // ── 테스트 발송 ──
    if (url.pathname === "/api/test") {
      if (!validTopic(body.topic)) return json({ error: "bad topic" }, 400);
      await ntfy(env, body.topic, String(body.title || "업무 다이어리").slice(0, 200),
                 String(body.message || "테스트 알림입니다").slice(0, 2000));
      return json({ ok: true });
    }

    // ── 예약 목록 동기화 ──
    if (url.pathname === "/api/sync") {
      const device = String(body.device || "");
      if (!/^[a-z0-9]{8,40}$/.test(device)) return json({ error: "bad device" }, 400);
      const alarms = Array.isArray(body.alarms) ? body.alarms.slice(0, 500) : [];
      const topic = body.topic;
      if (alarms.length && !validTopic(topic)) return json({ error: "bad topic" }, 400);

      const now = nowSec();
      const stmts = [];
      const keep = [];
      for (const a of alarms) {
        const sid = Number(a.sid), fireAt = Number(a.fire_at);
        if (!Number.isInteger(sid) || !Number.isInteger(fireAt)) continue;
        keep.push(sid);
        stmts.push(env.DB.prepare(
          `INSERT INTO alarms(device, sid, topic, fire_at, title, message, sent)
           VALUES(?1, ?2, ?3, ?4, ?5, ?6, 0)
           ON CONFLICT(device, sid) DO UPDATE SET
             topic = excluded.topic, title = excluded.title, message = excluded.message,
             sent = CASE WHEN alarms.fire_at = excluded.fire_at THEN alarms.sent ELSE 0 END,
             fire_at = excluded.fire_at`
        ).bind(device, sid, topic, fireAt,
               String(a.title || "").slice(0, 200), String(a.message || "").slice(0, 2000)));
      }
      // 목록에서 빠진 '아직 시간이 안 된' 알림은 취소. (이미 시간이 된 건 cron이 보내도록 남겨둠)
      stmts.push(env.DB.prepare(
        `DELETE FROM alarms WHERE device = ?1 AND sent = 0 AND fire_at > ?2
           AND sid NOT IN (SELECT value FROM json_each(?3))`
      ).bind(device, now, JSON.stringify(keep)));
      await env.DB.batch(stmts);
      return json({ ok: true, count: keep.length });
    }

    return json({ error: "not found" }, 404);
  },

  async scheduled(event, env, ctx) {
    const now = nowSec();
    const { results } = await env.DB.prepare(
      // 10분 이상 지난 건 버림 (서버 장애 후 몰아서 울리는 것 방지)
      `SELECT device, sid, topic, title, message FROM alarms
       WHERE sent = 0 AND fire_at <= ? AND fire_at > ? LIMIT 200`
    ).bind(now, now - 600).all();

    for (const r of results) {
      try {
        await ntfy(env, r.topic, r.title, r.message);
        await env.DB.prepare("UPDATE alarms SET sent = 1 WHERE device = ? AND sid = ?").bind(r.device, r.sid).run();
      } catch (e) {
        console.log("push fail", r.device, r.sid, String(e));
      }
    }
    // 정리: 놓친 알림 처리 + 보낸 지 7일 지난 기록 삭제
    await env.DB.batch([
      env.DB.prepare("UPDATE alarms SET sent = 2 WHERE sent = 0 AND fire_at <= ?").bind(now - 600),
      env.DB.prepare("DELETE FROM alarms WHERE sent > 0 AND fire_at < ?").bind(now - 7 * 86400),
    ]);
  },
};
