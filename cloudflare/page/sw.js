// 업무 다이어리 - 알림 받기 (서비스 워커)
// 기기 ID는 등록 주소(/sw.js?d=...)에 들어 있음 → 연결이 바뀌거나 끊겨도 스스로 다시 연결
var DEV = new URL(self.location.href).searchParams.get("d") || "";

self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (e) { e.waitUntil(self.clients.claim()); });

function b64(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/"); while (s.length % 4) s += "=";
  var raw = atob(s), out = new Uint8Array(raw.length);
  for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

// 현재 연결을 서버에 다시 알림 (끊겼으면 새로 연결)
function heal() {
  if (!DEV) return Promise.resolve();
  return self.registration.pushManager.getSubscription().then(function (sub) {
    if (sub) return sub;
    return fetch("/api/vapid").then(function (r) { return r.json(); }).then(function (v) {
      return self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(v.key) });
    });
  }).then(function (sub) {
    return fetch("/api/subscribe", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ device: DEV, subscription: sub.toJSON(), auto: true, ua: "sw" }) });
  }).catch(function () {});
}

self.addEventListener("pushsubscriptionchange", function (e) { e.waitUntil(heal()); });

self.addEventListener("push", function (e) {
  var d = {};
  try { d = e.data ? e.data.json() : {}; } catch (x) { d = { title: "업무 다이어리", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(Promise.all([
    self.registration.showNotification(d.title || "업무 다이어리", {
      body: d.body || "",
      icon: "/icon-192.png",
      badge: "/badge.png",
      tag: d.tag || undefined,
      renotify: !!d.tag,
      requireInteraction: true,
      vibrate: [200, 100, 200, 100, 300],
      data: { url: "/app" + (DEV ? "?d=" + DEV : "") }
    }),
    heal()
  ]));
});

self.addEventListener("notificationclick", function (e) {
  e.notification.close();
  var url = (e.notification.data && e.notification.data.url) || "/app";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (list) {
    for (var i = 0; i < list.length; i++) {
      if (list[i].url.indexOf("/app") >= 0 && "focus" in list[i]) return list[i].focus();
    }
    return self.clients.openWindow(url);
  }));
});
