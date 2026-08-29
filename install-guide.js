(() => {
  const page = document.getElementById('installGuidePage');
  if (!page) return;
  const tabs = [...page.querySelectorAll('[data-install-platform]')];
  const panels = [...page.querySelectorAll('[data-install-panel]')];

  function createCarousel(panel) {
    const track = panel.querySelector('.install-guide-track');
    const slides = [...track.children];
    const previous = panel.querySelector('[data-carousel-prev]');
    const next = panel.querySelector('[data-carousel-next]');
    const counter = panel.querySelector('[data-carousel-counter]');
    let activeIndex = 0;
    let dragging = false;
    let dragged = false;
    let startX = 0;
    let startScroll = 0;
    let frame = 0;

    const update = () => {
      const trackRect = track.getBoundingClientRect();
      const center = trackRect.left + trackRect.width / 2;
      let nearest = 0;
      let distance = Infinity;
      slides.forEach((slide, index) => {
        const rect = slide.getBoundingClientRect();
        const current = Math.abs(rect.left + rect.width / 2 - center);
        if (current < distance) { distance = current; nearest = index; }
      });
      activeIndex = nearest;
      counter.innerHTML = `<strong>${activeIndex + 1}</strong> / ${slides.length}`;
      previous.disabled = activeIndex === 0;
      next.disabled = activeIndex === slides.length - 1;
    };

    const moveTo = (index, behavior = 'smooth') => {
      const target = slides[Math.max(0, Math.min(index, slides.length - 1))];
      if (!target) return;
      const left = track.scrollLeft + target.getBoundingClientRect().left - track.getBoundingClientRect().left;
      track.scrollTo({ left, behavior });
    };

    const finishDrag = () => {
      if (!dragging) return;
      dragging = false;
      track.classList.remove('is-dragging');
      update();
      moveTo(activeIndex);
    };

    track.addEventListener('scroll', () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    }, { passive: true });
    track.addEventListener('keydown', event => {
      if (event.key === 'ArrowLeft') { event.preventDefault(); moveTo(activeIndex - 1); }
      if (event.key === 'ArrowRight') { event.preventDefault(); moveTo(activeIndex + 1); }
    });
    previous.addEventListener('click', () => moveTo(activeIndex - 1));
    next.addEventListener('click', () => moveTo(activeIndex + 1));
    track.addEventListener('mousedown', event => {
      if (event.button !== 0) return;
      dragging = true;
      dragged = false;
      startX = event.clientX;
      startScroll = track.scrollLeft;
      track.classList.add('is-dragging');
      event.preventDefault();
    });
    window.addEventListener('mousemove', event => {
      if (!dragging) return;
      const delta = event.clientX - startX;
      if (Math.abs(delta) > 4) dragged = true;
      track.scrollLeft = startScroll - delta;
    });
    window.addEventListener('mouseup', finishDrag);
    window.addEventListener('blur', finishDrag);
    track.addEventListener('click', event => {
      if (!dragged) return;
      event.preventDefault();
      event.stopPropagation();
      dragged = false;
    }, true);
    new ResizeObserver(update).observe(track);
    update();
    return { reset: () => { activeIndex = 0; moveTo(0, 'auto'); update(); } };
  }

  const carousels = new Map(panels.map(panel => [panel.dataset.installPanel, createCarousel(panel)]));

  function selectPlatform(platform) {
    const selected = platform === 'android' ? 'android' : 'ios';
    tabs.forEach(tab => tab.setAttribute('aria-selected', String(tab.dataset.installPlatform === selected)));
    panels.forEach(panel => { panel.hidden = panel.dataset.installPanel !== selected; });
    requestAnimationFrame(() => carousels.get(selected)?.reset());
  }

  tabs.forEach(tab => tab.addEventListener('click', () => {
    selectPlatform(tab.dataset.installPlatform);
    history.replaceState(null, '', `install.html?platform=${tab.dataset.installPlatform}`);
  }));

  const requested = new URLSearchParams(location.search).get('platform');
  const detected = /Android/i.test(navigator.userAgent) ? 'android' : 'ios';
  selectPlatform(requested || detected);
})();
