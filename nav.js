/* 반려견 천둥번개 알림 — 공유 헤더/푸터 (모든 페이지 공통)
   메뉴를 바꾸려면 이 파일 한 곳만 수정하면 전체 페이지에 반영된다. */
(function () {
  var header =
    '<header class="site-header"><div class="inner">' +
      '<a class="brand" href="index.html"><span class="brand-mark">↯</span><span class="brand-full">반려견 천둥번개 알림</span><span class="brand-short">반려견 천둥번개 알림</span></a>' +
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
      '<div class="footer-brand">반려견 천둥번개 알림</div>' +
      '<nav class="footer-nav">' +
        '<a href="about.html">소개</a>' +
        '<a href="contact.html">문의</a>' +
        '<a href="privacy.html">개인정보처리방침</a>' +
        '<a href="cookies.html">쿠키 고지</a>' +
        '<a href="terms.html">이용약관</a>' +
        '<a href="disclaimer.html">면책 고지</a>' +
      '</nav>' +
      '<div class="footer-copy">기상청 관측 정보를 바탕으로 제공하는 참고용 천둥번개 알림<br/>문의: <a href="mailto:kustomduo@gmail.com">kustomduo@gmail.com</a><br/>© 2026 반려견 천둥번개 알림</div>' +
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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
