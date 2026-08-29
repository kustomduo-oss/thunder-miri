(() => {
  const track = document.getElementById('storyToonTrack');
  const counter = document.getElementById('storyToonCounter');
  const previous = document.getElementById('storyToonPrev');
  const next = document.getElementById('storyToonNext');
  if (!track || !counter || !previous || !next) return;

  const slides = [...track.querySelectorAll('.story-toon-slide')];
  let activeIndex = 0;
  let frame = 0;
  let dragging = false;
  let dragged = false;
  let dragStartX = 0;
  let dragStartScroll = 0;

  const update = () => {
    const trackRect = track.getBoundingClientRect();
    const trackCenter = trackRect.left + trackRect.width / 2;
    let nearest = 0;
    let shortestDistance = Infinity;

    slides.forEach((slide, index) => {
      const slideRect = slide.getBoundingClientRect();
      const slideCenter = slideRect.left + slideRect.width / 2;
      const distance = Math.abs(slideCenter - trackCenter);
      if (distance < shortestDistance) {
        shortestDistance = distance;
        nearest = index;
      }
    });

    activeIndex = nearest;
    counter.innerHTML = `<strong>${activeIndex + 1}</strong> / ${slides.length}`;
    previous.disabled = activeIndex === 0;
    next.disabled = activeIndex === slides.length - 1;
  };

  const moveTo = (index) => {
    const target = slides[Math.max(0, Math.min(index, slides.length - 1))];
    if (!target) return;
    const left = track.scrollLeft + target.getBoundingClientRect().left - track.getBoundingClientRect().left;
    track.scrollTo({ left, behavior: 'smooth' });
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
  track.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowLeft') { event.preventDefault(); moveTo(activeIndex - 1); }
    if (event.key === 'ArrowRight') { event.preventDefault(); moveTo(activeIndex + 1); }
  });
  previous.addEventListener('click', () => moveTo(activeIndex - 1));
  next.addEventListener('click', () => moveTo(activeIndex + 1));
  track.addEventListener('mousedown', (event) => {
    if (event.button !== 0) return;
    dragging = true;
    dragged = false;
    dragStartX = event.clientX;
    dragStartScroll = track.scrollLeft;
    track.classList.add('is-dragging');
    event.preventDefault();
  });
  window.addEventListener('mousemove', (event) => {
    if (!dragging) return;
    const distance = event.clientX - dragStartX;
    if (Math.abs(distance) > 4) dragged = true;
    track.scrollLeft = dragStartScroll - distance;
  });
  window.addEventListener('mouseup', finishDrag);
  window.addEventListener('blur', finishDrag);
  track.addEventListener('click', (event) => {
    if (!dragged) return;
    event.preventDefault();
    event.stopPropagation();
    dragged = false;
  }, true);
  new ResizeObserver(update).observe(track);
  update();
})();
