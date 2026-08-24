/* 썬더미리 — 공유 헤더/푸터 (모든 페이지 공통)
   메뉴를 바꾸려면 이 파일 한 곳만 수정하면 전체 페이지에 반영된다. */
(function () {
  /* 배포한 판을 폰에서 바로 확인하려고 푸터에 찍는다.
     화면이 안 바뀐 것 같을 때 캐시 문제인지 여기서 판별한다. 배포 시 이 값만 고칠 것. */
  var SITE_VERSION = '2026.08.24d';
  var VERSION_STORAGE_KEY = 'thunder_site_version';
  var lastVersionCheckAt = 0;
  var SUPABASE_URL = 'https://pdlohzenslwbiyoxwjom.supabase.co';
  var SUPABASE_ANON_KEY = 'sb_publishable_5GA_EH7mqRbkWe-UEWEL2Q_xf5cn3kF';
  var header =
    '<header class="site-header"><div class="inner">' +
      '<a class="brand" href="index.html" aria-label="동탄이네 썬더미리 홈"><span class="brand-logo"><img src="thundermiri-retro-logo-transparent.png?v=1" alt="동탄이네 썬더미리" /></span></a>' +
      '<button type="button" class="menu-toggle" aria-expanded="false" aria-controls="siteMenu">메뉴</button>' +
      '<nav class="nav" id="siteMenu" aria-label="주요 메뉴">' +
        '<a href="index.html#radar">우리 동네 레이더</a>' +
        '<a href="index.html#signup">알림 받기</a>' +
        '<a href="how.html">작동 방식</a>' +
        '<a href="blog.html">동탄이네 이야기</a>' +
      '</nav>' +
    '</div></header>' +
    '<div class="alert-status-bar" id="alertStatusBar" hidden>' +
      '<span><i></i><b id="alertStatusText">알림 켜짐</b></span>' +
      '<button type="button" id="alertManageButton">알림 관리</button>' +
    '</div>' +
    '<div class="alert-manage-overlay" id="alertManageOverlay" hidden>' +
      '<button type="button" class="alert-manage-backdrop" id="alertManageBackdrop" aria-label="알림 관리 닫기"></button>' +
      '<section class="alert-manage-card" role="dialog" aria-modal="true" aria-labelledby="alertManageTitle">' +
        '<button type="button" class="alert-manage-close" id="alertManageClose" aria-label="닫기">×</button>' +
        '<h2 id="alertManageTitle">알림 관리</h2>' +
        '<p id="alertManageLocation">현재 기기에서 천둥번개 알림을 받고 있습니다.</p>' +
        '<button type="button" class="alert-off-button" id="alertOffButton">알림 끄기</button>' +
      '</section>' +
    '</div>';

  var footer =
    '<footer class="site-footer"><div class="inner">' +
      '<div class="footer-brand">썬더미리</div>' +
      '<nav class="footer-nav">' +
        '<a href="about.html">소개</a>' +
        '<a href="contact.html">문의</a>' +
        '<a href="privacy.html">개인정보<span class="fn-long">처리방침</span></a>' +
        '<a href="cookies.html">쿠키<span class="fn-long"> 고지</span></a>' +
        '<a href="terms.html"><span class="fn-long">이용</span>약관</a>' +
        '<a href="disclaimer.html">면책<span class="fn-long"> 고지</span></a>' +
      '</nav>' +
      '<div class="footer-copy">기상청 관측 정보를 바탕으로 제공하는 참고용 천둥번개 알림<br/>문의: <a href="https://ig.me/m/dongtan2ne" target="_blank" rel="noopener">인스타그램 DM</a> · <a href="mailto:kustomduo@gmail.com">kustomduo@gmail.com</a><br/>© 2026 썬더미리 · <span class="footer-version">v' + SITE_VERSION + '</span></div>' +
    '</div></footer>';

  function mount() {
    // 기존 정적 헤더/푸터가 있으면 제거 후 최신 버전으로 교체
    document.querySelectorAll('.site-header, .site-footer, footer[data-managed]').forEach(function (el) { el.remove(); });
    document.body.insertAdjacentHTML('afterbegin', header);
    document.body.insertAdjacentHTML('beforeend', footer);

    var siteHeader = document.querySelector('.site-header');
    var menuToggle = document.querySelector('.menu-toggle');
    var menu = document.getElementById('siteMenu');

    function closeMenu() {
      if (!menuToggle || !menu) return;
      menuToggle.setAttribute('aria-expanded', 'false');
      menu.classList.remove('nav-open');
    }

    if (menuToggle && menu) {
      menuToggle.addEventListener('click', function () {
        var isOpen = menuToggle.getAttribute('aria-expanded') === 'true';
        menuToggle.setAttribute('aria-expanded', String(!isOpen));
        menu.classList.toggle('nav-open', !isOpen);
      });
      menu.addEventListener('click', function (event) {
        if (event.target.closest('a')) closeMenu();
      });
      document.addEventListener('click', function (event) {
        if (siteHeader && !siteHeader.contains(event.target)) closeMenu();
      });
      document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') closeMenu();
      });
    }

    var statusBar = document.getElementById('alertStatusBar');
    var manageOverlay = document.getElementById('alertManageOverlay');
    var manageButton = document.getElementById('alertManageButton');
    var manageClose = document.getElementById('alertManageClose');
    var manageBackdrop = document.getElementById('alertManageBackdrop');
    var alertOffButton = document.getElementById('alertOffButton');
    var pushManageToken = readPushManageToken();

    function readPushManageToken() {
      var match = String(window.location.hash || '').match(/(?:^|&)manage=([^&]+)/);
      var token = match ? decodeURIComponent(match[1]) : '';
      if (token) {
        try { sessionStorage.setItem('thunder_push_manage_token', token); } catch (error) {}
        // 토큰은 주소창·공유 링크에 계속 남기지 않는다.
        history.replaceState(null, '', window.location.pathname + window.location.search + '#radar');
        return token;
      }
      try { return sessionStorage.getItem('thunder_push_manage_token') || ''; }
      catch (error) { return ''; }
    }

    function readProfile() {
      try { return JSON.parse(localStorage.getItem('thunder_alert_profile') || '{}'); }
      catch (error) { return {}; }
    }

    function closeManage() {
      if (!manageOverlay) return;
      manageOverlay.hidden = true;
      document.body.style.overflow = '';
    }

    function openManage() {
      if (!manageOverlay) return;
      var profile = readProfile();
      var locationText = document.getElementById('alertManageLocation');
      if (locationText) locationText.textContent = pushManageToken
        ? '방금 받은 알림의 구독을 이 기기에서 바로 해지할 수 있습니다.'
        : (profile.dong ? profile.dong + '에서 ' : '현재 기기에서 ') + '천둥번개 알림을 받고 있습니다.';
      manageOverlay.hidden = false;
      document.body.style.overflow = 'hidden';
      if (alertOffButton) alertOffButton.focus();
    }

    async function refreshSubscriptionStatus() {
      if (!statusBar || !('serviceWorker' in navigator)) return;
      try {
        var registration = await navigator.serviceWorker.getRegistration();
        var subscription = registration && await registration.pushManager.getSubscription();
        statusBar.hidden = !subscription && !pushManageToken;
        if (subscription || pushManageToken) {
          var profile = readProfile();
          var statusText = document.getElementById('alertStatusText');
          if (statusText) statusText.textContent = pushManageToken
            ? '방금 받은 알림 관리'
            : '알림 켜짐' + (profile.dong ? ' · ' + profile.dong : '');
        }
      } catch (error) {
        statusBar.hidden = true;
      }
    }

    if (manageButton) manageButton.addEventListener('click', openManage);
    if (manageClose) manageClose.addEventListener('click', closeManage);
    if (manageBackdrop) manageBackdrop.addEventListener('click', closeManage);
    if (alertOffButton) alertOffButton.addEventListener('click', async function () {
      if (!window.confirm('이 기기에서 천둥번개 알림을 끌까요?')) return;
      alertOffButton.disabled = true;
      alertOffButton.textContent = '알림 끄는 중…';
      try {
        if (pushManageToken) {
          var response = await fetch(SUPABASE_URL + '/rest/v1/rpc/unsubscribe_with_token', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'apikey': SUPABASE_ANON_KEY,
              'Authorization': 'Bearer ' + SUPABASE_ANON_KEY
            },
            body: JSON.stringify({ p_token: pushManageToken })
          });
          var removed = response.ok && await response.json();
          if (!removed) throw new Error('invalid management token');
          pushManageToken = '';
          try { sessionStorage.removeItem('thunder_push_manage_token'); } catch (error) {}
        }
        if ('serviceWorker' in navigator) {
          var registration = await navigator.serviceWorker.getRegistration();
          var subscription = registration && await registration.pushManager.getSubscription();
          if (subscription) await subscription.unsubscribe();
        }
        try {
          localStorage.removeItem('thunder_grid');
          localStorage.removeItem('thunder_alert_profile');
          localStorage.removeItem('thunder_returning');   // 다시 첫 방문 화면으로
        } catch (error) {}
        closeManage();
        statusBar.hidden = true;
        window.dispatchEvent(new CustomEvent('thunder-subscription-changed'));
        window.alert('천둥번개 알림을 해지했습니다.');
      } catch (error) {
        window.alert('알림을 끄지 못했습니다. 브라우저의 사이트 설정에서 알림을 차단해주세요.');
      } finally {
        alertOffButton.disabled = false;
        alertOffButton.textContent = '알림 끄기';
      }
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && manageOverlay && !manageOverlay.hidden) closeManage();
    });
    window.addEventListener('thunder-subscription-changed', refreshSubscriptionStatus);
    refreshSubscriptionStatus();
    // 푸시에서 들어온 경우 앱 설치 여부와 관계없이 상단 알림 관리 버튼을 남긴다.
    // 레이더 확인이 주목적이므로 관리 창을 자동으로 덮어씌우지는 않는다.
    if (pushManageToken && statusBar) statusBar.hidden = false;
  }

  // ── 하단 고정 광고 배너 ──────────────────────────────────
  // 레이더를 보러 온 사람을 가리지 않도록, 글 영역에 닿았을 때만 올라온다.
  // 닫으면 그 탭을 닫을 때까지 다시 뜨지 않는다(sessionStorage).
  function mountMakerNote() {
    var note = document.getElementById('makerNote');
    if (!note) return;

    var DISMISS_KEY = 'thunder_maker_note_dismissed';
    try {
      if (sessionStorage.getItem(DISMISS_KEY)) { note.remove(); return; }
    } catch (e) { /* 프라이빗 모드 등 — 무시하고 계속 */ }

    // 이 요소가 화면에 들어오면 "읽기 시작했다"고 본다.
    // index=콘텐츠 섹션, 하위 페이지=본문 카드 (문서 순서상 먼저 오는 것이 잡힘)
    var trigger = document.querySelector('.content-discovery, .story-card, .sound-story-card');
    if (!trigger) return;

    note.hidden = false;

    function show() {
      note.classList.add('is-shown');
      // 고정 배너가 푸터를 가리지 않도록 문서 아래에 자리를 만든다
      document.body.style.paddingBottom = note.offsetHeight + 'px';
    }

    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (entries) {
        if (entries.some(function (en) { return en.isIntersecting; })) {
          show();
          io.disconnect();
        }
      }, { rootMargin: '0px 0px -15% 0px' });
      io.observe(trigger);
    } else {
      show();   // 구형 브라우저는 그냥 보여준다
    }

    var closeBtn = document.getElementById('makerNoteClose');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        note.classList.remove('is-shown');
        document.body.style.paddingBottom = '';
        try { sessionStorage.setItem(DISMISS_KEY, '1'); } catch (e) {}
        window.setTimeout(function () { note.remove(); }, 320);   // 사라지는 동작이 끝난 뒤 제거
      });
    }
  }

  /* ---------------- 방문 분석 (GA4 · Microsoft Clarity) ----------------
     여기 한 곳에 두면 nav.js를 부르는 전 페이지에 한 번에 적용된다.
     ID는 브라우저에 노출되는 값이라 공개돼도 문제없다.
     ⚠️ 개인정보처리방침·쿠키 고지에 두 도구가 명시돼 있어야 한다(privacy.html, cookies.html). */
  var GA4_ID = 'G-MN7NNJ3B7H';
  var CLARITY_ID = 'y4jh2weiie';   // Clarity 프로젝트 ID (비어 있으면 로드 안 함)

  /* 실제 서비스 주소에서만 수집한다.
     로컬(file://·localhost)에서 테스트한 것까지 통계에 섞이면 숫자를 믿을 수 없게 된다. */
  var LIVE_HOSTS = ['thundermiri.com', 'www.thundermiri.com', 'kustomduo-oss.github.io'];

  function isLive() {
    return LIVE_HOSTS.indexOf(location.hostname) !== -1;
  }

  /* 홈 화면 웹 앱은 종료 뒤에도 이전 문서를 그대로 복원할 수 있다.
     서버의 작은 버전 파일을 직접 확인하고, 버전이 바뀐 경우에만 주소에 새 버전을 붙여
     HTML까지 한 번 새로 받는다. 저장값을 먼저 바꾸므로 새로고침 반복은 생기지 않는다. */
  function checkForAppUpdate(force) {
    if (!isLive() || !window.fetch) return;
    var now = Date.now();
    if (!force && now - lastVersionCheckAt < 60000) return;
    lastVersionCheckAt = now;

    fetch('version.json?cb=' + now, { cache: 'no-store' })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        var remoteVersion = data && String(data.version || '').trim();
        if (!remoteVersion) return;

        var knownVersion = '';
        try { knownVersion = localStorage.getItem(VERSION_STORAGE_KEY) || ''; }
        catch (error) {}

        if (!knownVersion) {
          try { localStorage.setItem(VERSION_STORAGE_KEY, remoteVersion); }
          catch (error) {}
          return;
        }
        if (knownVersion === remoteVersion) return;

        try { localStorage.setItem(VERSION_STORAGE_KEY, remoteVersion); }
        catch (error) {}
        var next = new URL(window.location.href);
        next.searchParams.set('appv', remoteVersion);
        window.location.replace(next.pathname + next.search + next.hash);
      })
      .catch(function () { /* 오프라인·일시 오류는 다음 화면 복귀 때 다시 확인 */ });
  }

  /* 알림 설정 화면을 다시 누르지 않아도 서비스워커 자체가 새 판을 확인한다.
     updateViaCache:none으로 GitHub Pages의 10분 캐시를 서비스워커 검사에는 쓰지 않는다. */
  function refreshServiceWorker() {
    if (!isLive() || !('serviceWorker' in navigator)) return;
    navigator.serviceWorker.register('sw.js?v=2026.08.24d', { updateViaCache: 'none' })
      .then(function (registration) { return registration.update(); })
      .catch(function () { /* 미지원·오프라인이면 다음 실행 때 다시 확인 */ });
  }

  function loadGA4() {
    if (!GA4_ID) return;
    var s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + GA4_ID;
    document.head.appendChild(s);
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', GA4_ID);
  }

  function loadClarity() {
    if (!CLARITY_ID) return;
    (function (c, l, a, r, i, t, y) {
      c[a] = c[a] || function () { (c[a].q = c[a].q || []).push(arguments); };
      t = l.createElement(r); t.async = 1;
      t.src = 'https://www.clarity.ms/tag/' + i;
      y = l.getElementsByTagName(r)[0]; y.parentNode.insertBefore(t, y);
    })(window, document, 'clarity', 'script', CLARITY_ID);
  }

  function loadAnalytics() {
    if (!isLive()) return;
    loadGA4();
    loadClarity();
  }

  function boot() {
    mount();
    mountMakerNote();
    loadAnalytics();
    refreshServiceWorker();
    checkForAppUpdate(true);
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') checkForAppUpdate(false);
  });
  window.addEventListener('pageshow', function () { checkForAppUpdate(false); });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
