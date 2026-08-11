/* 반려견 천둥번개 알림 — 웹푸시 서비스워커 */
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (error) {
    data = { body: event.data && event.data.text() };
  }

  const title = data.title || "반려견 천둥번개 알림";
  const options = {
    body: data.body || "천둥번개가 가까워지고 있습니다. 우리 동네 레이더를 확인해주세요.",
    icon: data.icon || "icon-192.png",
    badge: "icon-192.png",
    vibrate: [200, 100, 200],
    tag: data.tag || "thunder-alert",
    renotify: true,
    data: { url: data.url || "./index.html#radar" }
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ("focus" in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
