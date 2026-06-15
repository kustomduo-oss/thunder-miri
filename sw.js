/* 천둥미리 — 웹푸시 service worker
   서버가 보낸 푸시를 받아 알림으로 표시합니다.
   (VAPID 키 연결은 3단계에서) */

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }

  const title = data.title || "⛈️ 천둥미리";
  const options = {
    body: data.body || "천둥이 다가오고 있어요. 천둥소리를 미리 틀어주세요.",
    icon: data.icon || "icon.svg",
    badge: "icon.svg",
    vibrate: [200, 100, 200],
    tag: data.tag || "thunder-alert",
    renotify: true,
    data: { url: data.url || "https://youtu.be/lpi6gd1H0Ok" }
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const c of list) { if ("focus" in c) return c.focus(); }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
