/* 썬더미리 — 웹푸시 서비스워커 */

/* 배포할 때마다 올린다. 이 파일의 내용이 바뀌어야 브라우저가 새 워커를 설치한다. */
const SW_VERSION = "2026.08.24e";

self.addEventListener("install", () => self.skipWaiting());

/* 홈 화면 앱은 종료 뒤에도 옛 문서를 그대로 복원한다. 그 문서 안의 스크립트는
   이미 옛날 것이라, 페이지 쪽 코드로는 스스로를 갱신할 방법이 없다(닭·달걀).
   서비스워커는 페이지와 별개로 살아 있고 스스로 갱신되므로, 새 워커가 활성화되는
   순간 열려 있는 창을 우리가 직접 다시 불러온다. 페이지의 협조가 필요 없다. */
/* claim 전에 이 서비스워커 등록에 이미 연결된 창만 모은다.
   최초 알림 등록 때의 미제어 창은 제외되어 가입 도중 새로고침되지 않는다. */
self.addEventListener("activate", (event) => event.waitUntil((async () => {
  const windows = await self.clients.matchAll({ type: "window" });
  await self.clients.claim();
  for (const client of windows) {
    if (!("navigate" in client)) continue;
    try {
      const url = new URL(client.url);
      url.searchParams.set("appv", SW_VERSION);   // 10분짜리 HTTP 캐시를 피한다
      await client.navigate(url.href);
    } catch (error) { /* 창을 못 옮기면 다음 새로고침 때 최신 화면을 받는다 */ }
  }
})()));

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
  const requestedHash = target.hash;
  // 같은 화면이 이미 열려 있어도 새 탐색이 일어나도록 푸시마다 고유 값을 붙인다.
  target.searchParams.set("push", String(Date.now()));
  // 관리 토큰이 든 fragment는 유지한다. index가 토큰을 꺼낸 뒤 #radar로 정리한다.
  target.hash = requestedHash.includes("&manage=") ? requestedHash : "radar";
  const targetUrl = target.href;
  event.waitUntil((async () => {
    const list = await clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of list) {
      try {
        /* WindowClient.navigate는 같은 출처만 허용된다. 예전 GitHub 주소로
           설치된 앱처럼 출처가 다르면 아래 openWindow 경로로 보낸다. */
        if ("navigate" in client && new URL(client.url).origin === target.origin) {
          const windowClient = await client.navigate(targetUrl);
          if (windowClient && "focus" in windowClient) await windowClient.focus();
          return;
        }
      } catch (error) { /* 이동 실패 시 새 창 열기로 재시도 */ }
    }
    if (clients.openWindow) {
      await clients.openWindow(targetUrl);
      return;
    }
    if (list[0] && "focus" in list[0]) await list[0].focus();
  })());
});
