/* 번개 추적기 — 공유 헤더/푸터 (모든 페이지 공통)
   메뉴를 바꾸려면 이 파일 한 곳만 수정하면 전체 페이지에 반영된다. */
(function () {
  var header =
    '<header class="site-header"><div class="inner">' +
      '<a class="brand" href="index.html">⚡ 번개 추적기</a>' +
      '<nav class="nav">' +
        '<a href="index.html">홈</a>' +
        '<a href="how.html">작동 방식</a>' +
        '<a href="story.html">나의 이야기</a>' +
        '<a href="guide.html">천둥 공포 가이드</a>' +
        '<a href="blog.html">블로그</a>' +
        '<a href="about.html">소개</a>' +
        '<a class="cta" href="index.html">알림 받기</a>' +
      '</nav>' +
    '</div></header>';

  var footer =
    '<footer class="site-footer"><div class="inner">' +
      '<div class="footer-brand">⚡ 번개 추적기</div>' +
      '<nav class="footer-nav">' +
        '<a href="contact.html">문의</a>' +
        '<a href="privacy.html">개인정보처리방침</a>' +
        '<a href="terms.html">이용약관</a>' +
        '<a href="disclaimer.html">면책 고지</a>' +
        '<a href="cookies.html">쿠키 고지</a>' +
      '</nav>' +
      '<div class="footer-copy">강아지 천둥 공포 둔감화 알림 서비스 · 날씨 데이터: 기상청 API<br/>© 2026 번개 추적기</div>' +
    '</div></footer>';

  function mount() {
    // 기존 정적 헤더/푸터가 있으면 제거 후 최신 버전으로 교체
    document.querySelectorAll('.site-header, .site-footer, footer[data-managed]').forEach(function (el) { el.remove(); });
    document.body.insertAdjacentHTML('afterbegin', header);
    document.body.insertAdjacentHTML('beforeend', footer);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
