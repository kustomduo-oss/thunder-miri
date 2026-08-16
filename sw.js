/* 썬더미리 — 웹푸시 서비스워커 */
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (error) {
    data = { body: event.data && event.data.text() };
  }

  const title = data.title || "썬더미리";
  const options = {
    body: data.body || "천둥번개가 가까워지고 있습니다. 우리 동네 레이더를 확인해주세요.",
    icon: data.icon || "thundermiri-icon-192.png",
    badge: "thundermiri-icon-192.png",
    vibrate: [200, 100, 200],
    tag: data.tag || "thunder-alert",
    renotify: true,
    data: { url: data.url || "./index.html#radar" }
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "./index.html#radar";
  const target = new URL(url, self.location.origin);
  // 같은 화면이 이미 열려 있어도 새 탐색이 일어나도록 푸시마다 고유 값을 붙인다.
  target.searchParams.set("push", String(Date.now()));
  target.hash = "radar";
  const targetUrl = target.href;
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ("navigate" in client) {
          return client.navigate(targetUrl).then((windowClient) => {
            if (windowClient && "focus" in windowClient) return windowClient.focus();
            return windowClient;
          });
        }
        if ("focus" in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});
