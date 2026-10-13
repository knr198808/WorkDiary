/**
 * 업무 다이어리 - 예약 푸시 알림 서버 (Cloudflare Worker + D1)
 *
 *  PC 프로그램 → POST /api/sync   : 이 PC의 "앞으로 울릴 알림 목록" 전체를 올림
 *  PC 프로그램 → POST /api/test   : 바로 테스트 알림 발송
 *  PC 프로그램 → POST /api/phones : 연결된 폰 수 확인
 *  폰           → GET  /app?d=…    : 알림 받는 페이지 (홈 화면에 추가하는 웹앱)
 *  폰           → POST /api/subscribe, /api/unsubscribe, GET /api/list
 *  Cron(1분마다)                   : 시간이 된 알림을 폰으로 발송 (웹앱 푸시 + 기존 ntfy)
 *
 *  텔레그램       → POST /tg/hook     : 공용 봇 웹훅 (/start <기기ID> 로 연결)
 *
 *  데이터 동기화 (일정·회원·메모·다이어리)
 *  PC 프로그램 → POST /api/sync2      : 바뀐 것 올리고, 웹앱에서 바뀐 것 받아감 (알림도 서버가 계산)
 *  웹앱        → GET  /api/data?d=&k=&since= / POST /api/data   (k = PC QR코드에 든 비밀 열쇠)
 *
 *  비밀값(Secrets): APP_KEY, VAPID_PUBLIC, VAPID_PRIVATE_JWK, TG_BOT_TOKEN, TG_BOT_USERNAME, TG_WEBHOOK_SECRET
 *  변수: NTFY_SERVER, VAPID_SUBJECT
 */
import { sendWebPush } from "./webpush.js";
import { ICON192, ICON512, BADGE } from "./icons.js";
import { APP_HTML, SW_JS } from "./app_page.js";
import { validToken, parseChanges, writeRecords, deriveAlarms, affectedSchedules, changesSince, deviceRev } from "./sync.js";

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*" },
  });

const nowSec = () => Math.floor(Date.now() / 1000);
const validTopic = (t) => typeof t === "string" && /^[A-Za-z0-9_-]{6,64}$/.test(t);
const validDevice = (d) => typeof d === "string" && /^[a-z0-9]{8,40}$/.test(d);

function png(b64) {
  const bin = atob(b64);
  const u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return new Response(u, { headers: { "content-type": "image/png", "cache-control": "public, max-age=604800" } });
}

async function ntfy(env, topic, title, message) {
  const server = (env.NTFY_SERVER || "https://ntfy.sh").replace(/\/+$/, "");
  const res = await fetch(server, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ topic, title, message, priority: 4, tags: ["alarm_clock"] }),
  });
  if (!res.ok) throw new Error(`ntfy ${res.status} ${(await res.text()).slice(0, 120)}`);
}

// ───────────── 텔레그램 (공용 봇) ─────────────
async function tgApi(env, method, payload) {
  const res = await fetch(`https://api.telegram.org/bot${env.TG_BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
  });
  let j = {};
  try { j = await res.json(); } catch (e) { /* */ }
  return { status: res.status, ok: !!j.ok, desc: j.description || "" };
}

/** 기기에 연결된 모든 텔레그램 채팅으로 보내기. 봇을 차단한 채팅은 자동 정리 */
async function tgDevice(env, device, text) {
  if (!env.TG_BOT_TOKEN) return 0;
  const { results } = await env.DB.prepare("SELECT chat_id, name FROM tg_links WHERE device = ?").bind(device).all();
  let ok = 0;
  for (const c of results) {
    try {
      const r = await tgApi(env, "sendMessage", { chat_id: c.chat_id, text, disable_web_page_preview: true });
      if (r.ok) {
        ok++;
        await logPush(env, device, "텔레그램", 200, `보냄 (${c.name || c.chat_id})`);
      } else {
        if (r.status === 403 || /chat not found|blocked/i.test(r.desc)) {
          await env.DB.prepare("DELETE FROM tg_links WHERE device = ? AND chat_id = ?").bind(device, c.chat_id).run();
        }
        await logPush(env, device, "텔레그램", r.status, r.desc || "실패");
      }
    } catch (e) {
      await logPush(env, device, "텔레그램", -1, String(e));
    }
  }
  return ok;
}

/** 기기별 알림 채널 설정 (PC 프로그램에서 고름). 기본: 둘 다 켜짐 */
async function getPrefs(env, device) {
  const r = await env.DB.prepare("SELECT web, tg FROM prefs WHERE device = ?").bind(device).first();
  return { web: r ? !!r.web : true, tg: r ? !!r.tg : true };
}

/** 선택된 채널로 알림 1건 보내기. 반환: 받은 곳 수 */
async function deliver(env, device, title, body, tag) {
  const pf = await getPrefs(env, device);
  let n = 0;
  if (pf.web) n += await pushDevice(env, device, { title, body, tag });
  if (pf.tg) n += await tgDevice(env, device, `${title}\n${body}`);
  return n;
}

async function handleTelegram(req, env) {
  if (!env.TG_BOT_TOKEN || req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TG_WEBHOOK_SECRET) {
    return new Response("forbidden", { status: 403 });
  }
  const up = await req.json().catch(() => ({}));
  const msg = up.message || up.edited_message;
  if (!msg || !msg.chat) return new Response("ok");
  const chat = String(msg.chat.id);
  const name = [msg.from?.first_name, msg.from?.last_name].filter(Boolean).join(" ") || msg.from?.username || "";
  const text = String(msg.text || "").trim();
  const reply = (t) => tgApi(env, "sendMessage", { chat_id: chat, text: t, disable_web_page_preview: true });

  const m = text.match(/^\/start(?:@\w+)?\s+([a-z0-9]{8,40})$/);
  if (m) {
    await env.DB.prepare(
      `INSERT INTO tg_links(device, chat_id, name, created) VALUES(?,?,?,?)
       ON CONFLICT(device, chat_id) DO UPDATE SET name = excluded.name`
    ).bind(m[1], chat, name.slice(0, 60), nowSec()).run();
    await logPush(env, m[1], "텔레그램", 200, `연결됨 (${name})`);
    await reply("✅ 업무 다이어리와 연결됐어요!\n이제 예약한 시간이 되면 이 채팅으로 알림이 와요.\n\n/list 예정된 알림 보기\n/stop 알림 끄기");
  } else if (/^\/stop/.test(text)) {
    await env.DB.prepare("DELETE FROM tg_links WHERE chat_id = ?").bind(chat).run();
    await reply("🔕 알림을 껐어요. 다시 받으려면 PC의 업무 다이어리 → 📱 폰 연결 · 웹앱에서 텔레그램 연결을 눌러주세요.");
  } else if (/^\/list/.test(text)) {
    const { results } = await env.DB.prepare(
      `SELECT a.fire_at, a.title FROM alarms a JOIN tg_links t ON t.device = a.device
       WHERE t.chat_id = ? AND a.sent = 0 AND a.fire_at > ? ORDER BY a.fire_at LIMIT 15`
    ).bind(chat, nowSec()).all();
    const fmt = (sec) => new Date((sec + 9 * 3600) * 1000).toISOString().slice(5, 16).replace("-", "/").replace("T", " ");
    await reply(results.length ? "📅 예정된 알림\n" + results.map((r) => `${fmt(r.fire_at)}  ${r.title.replace(/^⏰\s*/, "")}`).join("\n")
                               : "예정된 알림이 없어요.");
  } else {
    const linked = await env.DB.prepare("SELECT COUNT(*) AS n FROM tg_links WHERE chat_id = ?").bind(chat).first();
    await reply(linked?.n ? "✅ 연결돼 있어요. 예약 시간이 되면 알림이 와요.\n/list 예정된 알림 · /stop 알림 끄기"
                          : "PC의 업무 다이어리 → 📱 폰 연결 · 웹앱 → 텔레그램 탭에서 [텔레그램으로 연결]을 눌러 연결해 주세요.");
  }
  return new Response("ok");
}

/** 발송 기록 (문제 원인 확인용, 기기별 최근 30건만 보관) */
async function logPush(env, device, target, status, info) {
  try {
    await env.DB.prepare("INSERT INTO push_log(device, at, target, status, info) VALUES(?,?,?,?,?)")
      .bind(device, nowSec(), target, status, String(info || "").slice(0, 300)).run();
  } catch (e) {
    console.log("log fail", String(e));
  }
}

function pushTarget(endpoint) {
  const h = new URL(endpoint).hostname;
  return h.includes("apple") ? "아이폰" : h.includes("google") ? "안드로이드(크롬)" : h.includes("mozilla") ? "파이어폭스"
    : h.includes("windows") || h.includes("microsoft") ? "엣지" : h;
}

/** 기기(PC)에 연결된 모든 폰으로 웹앱 푸시. 해지된 폰은 자동 정리 */
async function pushDevice(env, device, data) {
  if (!env.VAPID_PRIVATE_JWK || !env.VAPID_PUBLIC) {
    await logPush(env, device, "server", 0, "VAPID 키 없음");
    return 0;
  }
  const { results } = await env.DB.prepare("SELECT * FROM subscriptions WHERE device = ?").bind(device).all();
  if (!results.length) await logPush(env, device, "-", 0, "연결된 폰 없음");
  let ok = 0;
  for (const s of results) {
    const tgt = pushTarget(s.endpoint);
    try {
      const st = await sendWebPush(s, data, env);
      if (st === 404 || st === 410) {
        await env.DB.prepare("DELETE FROM subscriptions WHERE endpoint = ?").bind(s.endpoint).run();
        await logPush(env, device, tgt, st, "폰에서 알림이 해지돼 연결 삭제");
      } else if (st >= 200 && st < 300) {
        ok++;
        await logPush(env, device, tgt, st, "보냄");
      } else {
        await logPush(env, device, tgt, st, "푸시 서버 거절");
      }
    } catch (e) {
      await logPush(env, device, tgt, -1, String(e));
    }
  }
  return ok;
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const p = url.pathname;

    // ── 폰 웹앱 (누구나 열 수 있음. 기기 ID가 곧 열쇠) ──
    if (p === "/") return json({ ok: true, service: "workdiary-push", webpush: !!env.VAPID_PUBLIC });
    if (p === "/app") return new Response(APP_HTML, { headers: { "content-type": "text/html; charset=utf-8" } });
    if (p === "/sw.js") return new Response(SW_JS, { headers: { "content-type": "text/javascript; charset=utf-8" } });
    if (p === "/icon-192.png") return png(ICON192);
    if (p === "/icon-512.png") return png(ICON512);
    if (p === "/badge.png") return png(BADGE);
    if (p === "/manifest.json") {
      const d = url.searchParams.get("d") || "";
      const k = url.searchParams.get("k") || "";
      return new Response(JSON.stringify({
        name: "업무 다이어리", short_name: "업무다이어리", lang: "ko",
        start_url: `/app?d=${encodeURIComponent(d)}` + (k ? `&k=${encodeURIComponent(k)}` : ""), scope: "/", display: "standalone",
        background_color: "#1F1B16", theme_color: "#1F1B16",
        icons: [{ src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any maskable" },
                { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" }],
      }), { headers: { "content-type": "application/manifest+json; charset=utf-8" } });
    }
    if (p === "/api/vapid") return json({ key: env.VAPID_PUBLIC || "" });
    if (p === "/tg/hook" && req.method === "POST") return handleTelegram(req, env);

    if (p === "/api/subscribe" && req.method === "POST") {
      const b = await req.json().catch(() => ({}));
      const s = b.subscription || {};
      if (!validDevice(b.device) || !s.endpoint || !s.keys?.p256dh || !s.keys?.auth) return json({ error: "bad" }, 400);
      if (!/^https:\/\//.test(s.endpoint)) return json({ error: "bad endpoint" }, 400);
      const known = await env.DB.prepare("SELECT device FROM subscriptions WHERE endpoint = ?").bind(s.endpoint).first();
      await env.DB.prepare(
        `INSERT INTO subscriptions(endpoint, device, p256dh, auth, ua, created) VALUES(?1,?2,?3,?4,?5,?6)
         ON CONFLICT(endpoint) DO UPDATE SET device=excluded.device, p256dh=excluded.p256dh, auth=excluded.auth, ua=excluded.ua`
      ).bind(s.endpoint, b.device, s.keys.p256dh, s.keys.auth, String(b.ua || "").slice(0, 120), nowSec()).run();
      if (known && known.device === b.device) return json({ ok: true, renewed: true });   // 이미 연결됨 (자동 확인)
      if (b.auto) await logPush(env, b.device, pushTarget(s.endpoint), 201, "끊겼던 연결을 자동으로 다시 연결");
      const n = await pushDevice(env, b.device, { title: "✅ 업무 다이어리 연결 완료", body: "이제 예약 알림이 이 폰으로 와요.", tag: "welcome" });
      return json({ ok: true, sent: n });
    }
    if (p === "/api/unsubscribe" && req.method === "POST") {
      const b = await req.json().catch(() => ({}));
      if (b.endpoint) await env.DB.prepare("DELETE FROM subscriptions WHERE endpoint = ?").bind(b.endpoint).run();
      return json({ ok: true });
    }
    if (p === "/api/list") {
      const d = url.searchParams.get("d");
      if (!validDevice(d)) return json({ error: "bad" }, 400);
      const { results } = await env.DB.prepare(
        `SELECT fire_at, title, message, sent FROM alarms WHERE device = ? AND fire_at > ? ORDER BY fire_at LIMIT 60`
      ).bind(d, nowSec() - 12 * 3600).all();
      const ph = await env.DB.prepare("SELECT endpoint, created FROM subscriptions WHERE device = ?").bind(d).all();
      const lg = await env.DB.prepare("SELECT at, target, status, info FROM push_log WHERE device = ? ORDER BY at DESC LIMIT 15")
        .bind(d).all();
      return json({ ok: true, now: nowSec(), items: results,
        phones: ph.results.map((x) => ({ type: pushTarget(x.endpoint), since: x.created })), log: lg.results });
    }

    // ── 웹앱 데이터 (기기 ID + 비밀 열쇠 필요) ──
    if (p === "/api/data") {
      const isGet = req.method === "GET";
      const b = isGet ? null : await req.json().catch(() => null);
      const d = isGet ? url.searchParams.get("d") : b?.d;
      const k = isGet ? url.searchParams.get("k") : b?.k;
      if (!validDevice(d) || !validToken(k)) return json({ error: "bad" }, 400);
      const dv = await env.DB.prepare("SELECT token, rev FROM devices WHERE device = ?").bind(d).first();
      if (!dv || !dv.token || dv.token !== k) return json({ error: "auth" }, 403);
      if (isGet) {
        const since = Math.max(0, parseInt(url.searchParams.get("since") || "0", 10) || 0);
        const rev = await deviceRev(env, d);       // 먼저 번호를 정해두고 그때까지의 것만 (사이에 바뀐 건 다음에)
        const records = await changesSince(env, d, since, "", 100000, rev);
        return json({ ok: true, rev, records });
      }
      const items = parseChanges(b?.ops);
      if (!items.length) return json({ error: "nothing" }, 400);
      // 회원을 지우면 그 회원 예약도 같이 지움 (PC와 같은 동작)
      const delMembers = items.filter((i) => i.kind === "member" && i.deleted).map((i) => i.uid);
      if (delMembers.length) {
        const { results } = await env.DB.prepare(
          `SELECT uid FROM records WHERE device = ? AND kind = 'schedule' AND deleted = 0
           AND json_extract(data, '$.member') IN (SELECT value FROM json_each(?))`).bind(d, JSON.stringify(delMembers)).all();
        for (const r of results) items.push({ kind: "schedule", uid: r.uid, deleted: true });
      }
      const rev = await writeRecords(env, d, items, "web");
      await deriveAlarms(env, d, await affectedSchedules(env, d, items));
      return json({ ok: true, rev, saved: items.length });
    }

    // ── 여기부터는 PC 프로그램 전용 (APP_KEY 필요) ──
    if (env.APP_KEY && req.headers.get("X-App-Key") !== env.APP_KEY) return json({ error: "unauthorized" }, 401);
    if (req.method !== "POST") return json({ error: "method" }, 405);
    const body = await req.json().catch(() => null);
    if (!body) return json({ error: "bad json" }, 400);

    if (p === "/api/phones") {
      if (!validDevice(body.device)) return json({ error: "bad device" }, 400);
      const r = await env.DB.prepare("SELECT COUNT(*) AS n FROM subscriptions WHERE device = ?").bind(body.device).first();
      const t = await env.DB.prepare("SELECT name FROM tg_links WHERE device = ?").bind(body.device).all();
      return json({ ok: true, phones: r?.n || 0, webpush: !!env.VAPID_PUBLIC,
        telegram: t.results.map((x) => x.name || "연결됨"), tg_bot: env.TG_BOT_TOKEN ? (env.TG_BOT_USERNAME || "") : "" });
    }

    if (p === "/api/tg/unlink") {
      if (!validDevice(body.device)) return json({ error: "bad device" }, 400);
      await env.DB.prepare("DELETE FROM tg_links WHERE device = ?").bind(body.device).run();
      return json({ ok: true });
    }

    if (p === "/api/test") {
      const title = String(body.title || "업무 다이어리").slice(0, 200);
      const message = String(body.message || "테스트 알림입니다").slice(0, 2000);
      let phones = 0, ntfyOk = false, tg = 0;
      if (validDevice(body.device)) {
        const ch = body.channels || {};
        if (ch.web !== false) phones = await pushDevice(env, body.device, { title, body: message, tag: "test" });
        if (ch.tg !== false) tg = await tgDevice(env, body.device, `${title}\n${message}`);
      }
      if (validTopic(body.topic)) {
        try {
          await ntfy(env, body.topic, title, message);
          ntfyOk = true;
          await logPush(env, body.device || "-", "ntfy", 200, "테스트 보냄");
        } catch (e) {
          await logPush(env, body.device || "-", "ntfy", -1, String(e));
        }
      }
      return json({ ok: true, phones, telegram: tg, ntfy: ntfyOk });
    }

    if (p === "/api/sync2") {
      const device = String(body.device || "");
      if (!validDevice(device)) return json({ error: "bad device" }, 400);
      const old = await env.DB.prepare("SELECT phone, topic, token FROM devices WHERE device = ?").bind(device).first();
      const phone = body.phone === false ? 0 : 1;
      const topic = validTopic(body.topic) ? body.topic : "";
      const token = validToken(body.token) ? body.token : (old?.token || "");
      const stmts = [
        env.DB.prepare(`INSERT INTO devices(device, token, phone, topic, created) VALUES(?1, ?2, ?3, ?4, ?5)
          ON CONFLICT(device) DO UPDATE SET token = ?2, phone = ?3, topic = ?4`).bind(device, token, phone, topic, nowSec()),
        // 예전 방식(/api/sync)으로 올렸던 알림은 정리 → 이제 서버가 일정에서 직접 계산
        env.DB.prepare("DELETE FROM alarms WHERE device = ? AND sent = 0 AND typeof(sid) = 'integer'").bind(device),
      ];
      if (body.channels) {
        stmts.push(env.DB.prepare(`INSERT INTO prefs(device, web, tg) VALUES(?,?,?)
          ON CONFLICT(device) DO UPDATE SET web = excluded.web, tg = excluded.tg`)
          .bind(device, body.channels.web === false ? 0 : 1, body.channels.tg === false ? 0 : 1));
      }
      await env.DB.batch(stmts);
      const items = parseChanges(body.changes);
      if (items.length) await writeRecords(env, device, items, "pc");
      if (!old || old.phone !== phone || old.topic !== topic || body.rederive) {
        await deriveAlarms(env, device, null);
      } else if (items.length) {
        await deriveAlarms(env, device, await affectedSchedules(env, device, items));
      }
      const since = Math.max(0, parseInt(body.since || 0, 10) || 0);
      const LIMIT = 300;
      const upto = await deviceRev(env, device);
      const changes = await changesSince(env, device, since, "pc", LIMIT, upto);
      const more = changes.length >= LIMIT;
      const rev = more ? changes[changes.length - 1].rev : upto;
      return json({ ok: true, rev, changes, more, accepted: items.length });
    }

    if (p === "/api/sync") {
      const device = String(body.device || "");
      if (!validDevice(device)) return json({ error: "bad device" }, 400);
      const alarms = Array.isArray(body.alarms) ? body.alarms.slice(0, 500) : [];
      const topic = validTopic(body.topic) ? body.topic : "";
      if (body.channels) {
        await env.DB.prepare(`INSERT INTO prefs(device, web, tg) VALUES(?,?,?)
          ON CONFLICT(device) DO UPDATE SET web = excluded.web, tg = excluded.tg`)
          .bind(device, body.channels.web === false ? 0 : 1, body.channels.tg === false ? 0 : 1).run();
      }

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
      let delivered = false;
      try {
        const n = await deliver(env, r.device, r.title, r.message, `a${r.sid}`);
        if (n > 0) delivered = true;
      } catch (e) {
        console.log("webpush fail", String(e));
      }
      if (validTopic(r.topic)) {
        try {
          await ntfy(env, r.topic, r.title, r.message);
          delivered = true;
          await logPush(env, r.device, "ntfy", 200, "보냄");
        } catch (e) {
          await logPush(env, r.device, "ntfy", -1, String(e));
        }
      }
      // 보냈으면 완료. 못 보냈으면 그대로 두어 1분 뒤 다시 시도 (10분 지나면 '놓침' 처리)
      if (delivered) await env.DB.prepare("UPDATE alarms SET sent = 1 WHERE device = ? AND sid = ?").bind(r.device, r.sid).run();
    }
    // 정리: 놓친 알림 처리 + 보낸 지 7일 지난 기록 삭제
    await env.DB.batch([
      env.DB.prepare("UPDATE alarms SET sent = 2 WHERE sent = 0 AND fire_at <= ?").bind(now - 600),
      env.DB.prepare("DELETE FROM alarms WHERE sent > 0 AND fire_at < ?").bind(now - 7 * 86400),
      env.DB.prepare("DELETE FROM push_log WHERE at < ?").bind(now - 3 * 86400),
    ]);
  },
};
