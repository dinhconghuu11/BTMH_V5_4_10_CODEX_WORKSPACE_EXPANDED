(() => {
  'use strict';
  const canvas = document.getElementById('v8HeroCanvas');
  const hero = document.getElementById('v8Hero');
  if (!canvas || !hero) return;

  const visual = canvas.parentElement;
  const ctx = canvas.getContext('2d', { alpha: true });
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let particles = [];
  let width = 0;
  let height = 0;
  let raf = 0;
  let visible = true;
  let last = 0;
  const dpr = Math.min(window.devicePixelRatio || 1, 1.5);

  function seed() {
    const target = Math.max(18, Math.min(42, Math.round((width * height) / 11500)));
    particles = Array.from({ length: target }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - .5) * .14,
      vy: (Math.random() - .5) * .12,
      r: .7 + Math.random() * 1.35,
      a: .15 + Math.random() * .38,
      phase: Math.random() * Math.PI * 2
    }));
  }

  function resize() {
    const rect = visual.getBoundingClientRect();
    width = Math.max(1, Math.round(rect.width));
    height = Math.max(1, Math.round(rect.height));
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    seed();
    if (reduced) draw(performance.now(), true);
  }

  function draw(now, staticFrame = false) {
    ctx.clearRect(0, 0, width, height);
    const glow = ctx.createRadialGradient(width * .47, height * .5, 20, width * .47, height * .5, Math.max(width, height) * .58);
    glow.addColorStop(0, 'rgba(74,245,202,.105)');
    glow.addColorStop(1, 'rgba(74,245,202,0)');
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, width, height);

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      if (!staticFrame) {
        p.x += p.vx;
        p.y += p.vy + Math.sin(now * .00045 + p.phase) * .006;
        if (p.x < -8) p.x = width + 8;
        else if (p.x > width + 8) p.x = -8;
        if (p.y < -8) p.y = height + 8;
        else if (p.y > height + 8) p.y = -8;
      }
      const pulse = p.a * (.8 + .2 * Math.sin(now * .001 + p.phase));
      ctx.beginPath();
      ctx.fillStyle = `rgba(137,255,225,${Math.max(.06, pulse)})`;
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    }

    for (let i = 0; i < particles.length; i++) {
      const a = particles[i];
      for (let j = i + 1; j < particles.length; j++) {
        const b = particles[j];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const d2 = dx * dx + dy * dy;
        if (d2 > 6800) continue;
        const alpha = .09 * (1 - d2 / 6800);
        ctx.beginPath();
        ctx.strokeStyle = `rgba(130,255,225,${alpha})`;
        ctx.lineWidth = .6;
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
    }
  }

  function loop(now) {
    if (!visible || document.hidden || reduced) { raf = 0; return; }
    if (now - last > 32) {
      draw(now);
      last = now;
    }
    raf = requestAnimationFrame(loop);
  }

  function start() {
    if (reduced || raf || !visible || document.hidden) return;
    raf = requestAnimationFrame(loop);
  }

  function stop() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  const ro = new ResizeObserver(resize);
  ro.observe(visual);
  const io = new IntersectionObserver(entries => {
    visible = !!entries[0]?.isIntersecting;
    if (visible) start(); else stop();
  }, { threshold: .05 });
  io.observe(hero);
  document.addEventListener('visibilitychange', () => document.hidden ? stop() : start());
  resize();
  if (!reduced) start();
})();
