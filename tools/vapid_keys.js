// 웹앱 푸시용 서버 키(VAPID) 한 쌍 만들기 — 처음 한 번만 사용 (서버정보.txt 에 저장됨)
const c = require("crypto");
const { privateKey } = c.generateKeyPairSync("ec", { namedCurve: "P-256" });
const j = privateKey.export({ format: "jwk" });
const raw = Buffer.concat([Buffer.from([4]), Buffer.from(j.x, "base64url"), Buffer.from(j.y, "base64url")]);
console.log("VAPID_PUBLIC=" + raw.toString("base64url"));
console.log("VAPID_PRIVATE_JWK=" + JSON.stringify({ kty: "EC", crv: "P-256", d: j.d, x: j.x, y: j.y }));
