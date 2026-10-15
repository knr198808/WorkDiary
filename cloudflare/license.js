/**
 * 라이선스 (키 1개 = PC 1대)
 *
 *  PC 프로그램 → POST /api/lic/activate  {key, device, hwid, pc_name, version} : 키 등록(처음 쓴 PC에 묶임) + 확인
 *              → POST /api/lic/check     {key, device, hwid, version}          : 10분마다 확인 (정지·만료면 프로그램 잠김)
 *  관리 페이지  → /admin  (비밀번호 = ADMIN_PASS)
 *              → /api/admin/list, create, update, unbind, delete, selfkey
 *
 *  키가 정지·만료되면: PC 프로그램 잠김 + 웹앱 데이터 차단 + 폰 알림 발송 중단
 */
const nowSec = () => Math.floor(Date.now() / 1000);
const KEY_RE = /^WD-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}$/;
const ALPHA = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8" } });

// 예전에 만든 표에 새 칸 추가 (서버가 켜질 때 한 번)
let colsChecked = false;
export async function ensureLicenseCols(env) {
  if (colsChecked) return;
  try { await env.DB.prepare("ALTER TABLE licenses ADD COLUMN user_name TEXT NOT NULL DEFAULT ''").run(); } catch (e) { /* 이미 있음 */ }
  colsChecked = true;
}

export function normKey(k) {
  const s = String(k || "").toUpperCase().replace(/[^0-9A-Z]/g, "");
  const body = s.startsWith("WD") ? s.slice(2) : s;
  if (body.length !== 12) return "";
  const key = `WD-${body.slice(0, 4)}-${body.slice(4, 8)}-${body.slice(8)}`;
  return KEY_RE.test(key) ? key : "";
}

function newKey() {
  const a = new Uint8Array(12);
  crypto.getRandomValues(a);
  const s = Array.from(a, (x) => ALPHA[x % 32]).join("");
  return `WD-${s.slice(0, 4)}-${s.slice(4, 8)}-${s.slice(8)}`;
}

/** 라이선스 상태: ok / revoked / expired */
export function licState(r, now = nowSec()) {
  if (!r) return "not_found";
  if (r.revoked) return "revoked";
  if (r.expires && r.expires < now) return "expired";
  return "ok";
}

/** 이 기기(프로그램)가 지금 쓸 수 있는 라이선스를 가졌는지 */
export async function deviceLicensed(env, device) {
  const r = await env.DB.prepare(
    "SELECT * FROM licenses WHERE device = ? ORDER BY revoked, (expires = 0) DESC, expires DESC LIMIT 1"
  ).bind(device).first();
  return licState(r) === "ok" ? r : null;
}

/** SQL 조건: alarms(또는 다른 표)의 device 가 유효한 라이선스를 가졌는지 */
export const LICENSED_SQL = (col, nowParam) =>
  `EXISTS (SELECT 1 FROM licenses l WHERE l.device = ${col} AND l.revoked = 0 AND (l.expires = 0 OR l.expires > ${nowParam}))`;

function info(r) {
  return { ok: true, name: r.name, user_name: r.user_name || "", expires: r.expires, capture: !!r.capture, owner: !!r.owner, key: r.key };
}

const MSG = {
  not_found: "등록되지 않은 라이선스 키예요. 키를 다시 확인해 주세요.",
  revoked: "사용이 중지된 라이선스예요. 판매자에게 문의해 주세요.",
  expired: "라이선스 기간이 끝났어요. 판매자에게 연장을 요청해 주세요.",
  other_pc: "이 키는 이미 다른 PC에서 사용 중이에요. PC를 바꿨다면 판매자에게 'PC 초기화'를 요청해 주세요.",
};
const fail = (code, status = 403) => json({ error: code, message: MSG[code] || code }, status);

/** PC 프로그램용 (APP_KEY 확인 후 호출됨) */
export async function licenseApi(p, body, env, req) {
  const key = normKey(body.key);
  const device = String(body.device || "");
  const hwid = String(body.hwid || "").slice(0, 64);
  if (!key) return fail("not_found", 404);
  if (!/^[a-z0-9]{8,40}$/.test(device) || !/^[a-f0-9]{16,64}$/.test(hwid)) return json({ error: "bad" }, 400);
  await ensureLicenseCols(env);
  const userName = String(body.user_name || "").trim().slice(0, 40);
  const r = await env.DB.prepare("SELECT * FROM licenses WHERE key = ?").bind(key).first();
  const st = licState(r);
  if (st !== "ok") return fail(st, st === "not_found" ? 404 : 403);
  const ip = req.headers.get("CF-Connecting-IP") || "";
  const ver = String(body.version || "").slice(0, 20);
  const now = nowSec();

  if (r.hwid && r.hwid !== hwid) return fail("other_pc");
  if (p === "/api/lic/check" && !r.hwid) return fail("not_found", 404);   // 아직 등록 안 된 키는 activate 로

  const stmts = [];
  if (userName && p === "/api/lic/activate") {
    stmts.push(env.DB.prepare("UPDATE licenses SET user_name = ? WHERE key = ?").bind(userName, key));
  }
  if (!r.hwid || r.device !== device) {
    // 처음 등록(또는 같은 PC에서 프로그램을 새로 깔아 기기 ID가 바뀐 경우) → 이 PC에 묶음
    stmts.push(env.DB.prepare("UPDATE licenses SET device = NULL WHERE device = ? AND key <> ?").bind(device, key));
    stmts.push(env.DB.prepare(
      `UPDATE licenses SET device = ?, hwid = ?, pc_name = ?, bound_at = COALESCE(bound_at, ?), last_seen = ?, version = ?, last_ip = ?
       WHERE key = ?`).bind(device, hwid, String(body.pc_name || "").slice(0, 80), now, now, ver, ip, key));
  } else {
    stmts.push(env.DB.prepare("UPDATE licenses SET last_seen = ?, version = ?, last_ip = ? WHERE key = ?").bind(now, ver, ip, key));
  }
  await env.DB.batch(stmts);
  return json(info(r));
}

// ───────────── 관리 (비밀번호 필요) ─────────────
function isAdmin(req, env) {
  const t = req.headers.get("X-Admin") || "";
  return !!env.ADMIN_PASS && t.length > 0 && t === env.ADMIN_PASS;
}

/** "2026-12-31" → 그날 23:59:59 (한국 시간) */
function endOfDay(d) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d || "")) return null;
  const t = Date.parse(d + "T23:59:59+09:00");
  return Number.isFinite(t) ? Math.floor(t / 1000) : null;
}
function expiresFrom(b) {
  if (b.unlimited || b.expires === 0 || b.expires === "0") return 0;
  if (b.expires_date) return endOfDay(b.expires_date);
  if (b.days) {
    const d = new Date(Date.now() + 9 * 3600 * 1000 + Number(b.days) * 86400 * 1000);
    return endOfDay(d.toISOString().slice(0, 10));
  }
  return undefined;
}

export async function adminApi(p, req, env) {
  if (!env.ADMIN_PASS) return json({ error: "ADMIN_PASS 가 서버에 설정되지 않았어요 (1_서버배포.bat 다시 실행)" }, 503);
  if (!isAdmin(req, env)) return json({ error: "비밀번호가 틀렸어요" }, 401);
  await ensureLicenseCols(env);
  const b = req.method === "POST" ? (await req.json().catch(() => ({}))) : {};
  const now = nowSec();

  if (p === "/api/admin/list") {
    const { results } = await env.DB.prepare(
      `SELECT l.*, (SELECT COUNT(*) FROM records r WHERE r.device = l.device AND r.kind = 'member' AND r.deleted = 0) AS members,
              (SELECT COUNT(*) FROM subscriptions s WHERE s.device = l.device) AS phones,
              (SELECT COUNT(*) FROM tg_links t WHERE t.device = l.device) AS tg
       FROM licenses l ORDER BY l.owner DESC, l.created DESC`).all();
    return json({ ok: true, now, items: results.map((r) => ({ ...r, hwid: r.hwid ? r.hwid.slice(0, 6) : "", state: licState(r, now) })) });
  }
  if (p === "/api/admin/create") {
    const exp = expiresFrom(b);
    let key = newKey();
    for (let i = 0; i < 5 && (await env.DB.prepare("SELECT 1 FROM licenses WHERE key = ?").bind(key).first()); i++) key = newKey();
    await env.DB.prepare(
      "INSERT INTO licenses(key, name, memo, created, expires, capture) VALUES(?,?,?,?,?,?)"
    ).bind(key, String(b.name || "").slice(0, 60), String(b.memo || "").slice(0, 300), now, exp === undefined ? 0 : (exp ?? 0),
           b.capture ? 1 : 0).run();
    return json({ ok: true, key });
  }
  if (p === "/api/admin/selfkey") {
    // 관리자 본인 PC: 키를 따로 입력하지 않아도 되게 '본인 키'를 하나 만들어 돌려줌 (무제한 · 캡처 허용)
    let r = await env.DB.prepare("SELECT key FROM licenses WHERE owner = 1 AND revoked = 0 ORDER BY created LIMIT 1").first();
    if (!r) {
      const key = newKey();
      await env.DB.prepare("INSERT INTO licenses(key, name, memo, created, expires, capture, owner) VALUES(?,?,?,?,0,1,1)")
        .bind(key, "관리자 (나)", "자동 발급", now).run();
      r = { key };
    }
    return json({ ok: true, key: r.key });
  }
  const key = normKey(b.key);
  if (!key) return json({ error: "키가 올바르지 않아요" }, 400);
  if (p === "/api/admin/update") {
    const sets = [], args = [];
    if (b.name !== undefined) { sets.push("name = ?"); args.push(String(b.name).slice(0, 60)); }
    if (b.memo !== undefined) { sets.push("memo = ?"); args.push(String(b.memo).slice(0, 300)); }
    if (b.revoked !== undefined) { sets.push("revoked = ?"); args.push(b.revoked ? 1 : 0); }
    if (b.capture !== undefined) { sets.push("capture = ?"); args.push(b.capture ? 1 : 0); }
    const exp = expiresFrom(b);
    if (exp === null) return json({ error: "날짜가 올바르지 않아요" }, 400);
    if (exp !== undefined) { sets.push("expires = ?"); args.push(exp); }
    if (!sets.length) return json({ error: "바꿀 내용이 없어요" }, 400);
    await env.DB.prepare(`UPDATE licenses SET ${sets.join(", ")} WHERE key = ?`).bind(...args, key).run();
    return json({ ok: true });
  }
  if (p === "/api/admin/unbind") {
    await env.DB.prepare("UPDATE licenses SET device = NULL, hwid = NULL, pc_name = '', bound_at = NULL WHERE key = ?").bind(key).run();
    return json({ ok: true });
  }
  if (p === "/api/admin/delete") {
    await env.DB.prepare("DELETE FROM licenses WHERE key = ?").bind(key).run();
    return json({ ok: true });
  }
  return json({ error: "not found" }, 404);
}
