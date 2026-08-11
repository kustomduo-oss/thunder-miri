/* 동탄이네 천둥번개 알림이 — 공유 헤더/푸터 (모든 페이지 공통)
   메뉴를 바꾸려면 이 파일 한 곳만 수정하면 전체 페이지에 반영된다. */
(function () {
  var header =
    '<header class="site-header"><div class="inner">' +
      '<a class="brand" href="index.html"><span class="brand-mark">↯</span><span class="brand-full">동탄이네 천둥번개 알림이</span><span class="brand-short">동탄이네 알림이</span></a>' +
      '<button type="button" class="menu-toggle" aria-expanded="false" aria-controls="siteMenu">메뉴</button>' +
      '<nav class="nav" id="siteMenu" aria-label="주요 메뉴">' +
        '<a href="index.html">홈</a>' +
        '<a href="how.html">작동 방식</a>' +
        '<a href="story.html">동탄이 이야기</a>' +
        '<a href="research.html">참고자료</a>' +
        '<a href="guide.html">도움말</a>' +
        '<a class="cta" href="index.html#sound-check">시작 전 확인</a>' +
      '</nav>' +
    '</div></header>';

  var footer =
    '<footer class="site-footer"><div class="inner">' +
      '<div class="footer-brand">동탄이네 천둥번개 알림이</div>' +
      '<nav class="footer-nav">' +
        '<a href="story.html">동탄이 이야기</a>' +
        '<a href="research.html">참고자료</a>' +
        '<a href="blog.html">블로그</a>' +
        '<a href="about.html">소개</a>' +
        '<a href="contact.html">문의</a>' +
        '<a href="privacy.html">개인정보처리방침</a>' +
        '<a href="terms.html">이용약관</a>' +
        '<a href="disclaimer.html">면책 고지</a>' +
        '<a href="cookies.html">쿠키 고지</a>' +
      '</nav>' +
      '<div class="footer-copy">천둥이 들리기 전에 준비할 시간을 알려주는 무료 웹 알림 · 날씨 데이터: 기상청 API<br/>© 2026 동탄이네 천둥번개 알림이</div>' +
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
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
