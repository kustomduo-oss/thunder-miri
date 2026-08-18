/* 썬더미리 — 공유 헤더/푸터 (모든 페이지 공통)
   메뉴를 바꾸려면 이 파일 한 곳만 수정하면 전체 페이지에 반영된다. */
(function () {
  var header =
    '<header class="site-header"><div class="inner">' +
      '<a class="brand" href="index.html"><span class="brand-mark"><img src="thundermiri-icon-192.png" alt="" /></span><span class="brand-full">동탄이네 썬더미리</span><span class="brand-short">동탄이네 썬더미리</span></a>' +
      '<button type="button" class="menu-toggle" aria-expanded="false" aria-controls="siteMenu">메뉴</button>' +
      '<nav class="nav" id="siteMenu" aria-label="주요 메뉴">' +
        '<a href="index.html#radar">우리 동네 레이더</a>' +
        '<a href="index.html#signup">알림 받기</a>' +
        '<a href="story.html">만든 이야기</a>' +
        '<a href="guide-training.html">동탄이의 소리 적응</a>' +
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
      '<div class="footer-copy">기상청 관측 정보를 바탕으로 제공하는 참고용 천둥번개 알림<br/>문의: <a href="mailto:kustomduo@gmail.com">kustomduo@gmail.com</a><br/>© 2026 썬더미리</div>' +
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
      if (locationText) locationText.textContent = (profile.dong ? profile.dong + '에서 ' : '현재 기기에서 ') + '천둥번개 알림을 받고 있습니다.';
      manageOverlay.hidden = false;
      document.body.style.overflow = 'hidden';
      if (alertOffButton) alertOffButton.focus();
    }

    async function refreshSubscriptionStatus() {
      if (!statusBar || !('serviceWorker' in navigator)) return;
      try {
        var registration = await navigator.serviceWorker.getRegistration();
        var subscription = registration && await registration.pushManager.getSubscription();
        statusBar.hidden = !subscription;
        if (subscription) {
          var profile = readProfile();
          var statusText = document.getElementById('alertStatusText');
          if (statusText) statusText.textContent = '알림 켜짐' + (profile.dong ? ' · ' + profile.dong : '');
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
        var registration = await navigator.serviceWorker.getRegistration();
        var subscription = registration && await registration.pushManager.getSubscription();
        if (subscription) await subscription.unsubscribe();
        try {
          localStorage.removeItem('thunder_grid');
          localStorage.removeItem('thunder_alert_profile');
          localStorage.removeItem('thunder_returning');   // 다시 첫 방문 화면으로
        } catch (error) {}
        closeManage();
        statusBar.hidden = true;
        window.dispatchEvent(new CustomEvent('thunder-subscription-changed'));
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

  function boot() {
    mount();
    mountMakerNote();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
