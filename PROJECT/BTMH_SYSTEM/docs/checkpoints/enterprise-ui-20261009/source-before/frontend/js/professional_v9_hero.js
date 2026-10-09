(() => {
  'use strict';
  const hero = document.getElementById('cfv9Hero');
  const canvas = document.getElementById('cfv9Canvas');
  if (!hero || !canvas) return;

  const visual = hero.querySelector('.cfv9-visual');
  const ctx = canvas.getContext('2d', { alpha: true, desynchronized: true });
  if (!visual || !ctx) return;

  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
  let w = 1, h = 1, points = [], raf = 0, visible = true, last = 0;
  let pointer = { x: -999, y: -999, active: false };

  function makePoints() {
    const count = Math.max(22, Math.min(52, Math.round((w * h) / 8500)));
    points = Array.from({ length: count }, (_, i) => ({
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - .5) * (.09 + Math.random() * .08),
      vy: (Math.random() - .5) * (.07 + Math.random() * .07),
      r: .75 + Math.random() * 1.35,
      a: .15 + Math.random() * .34,
      p: Math.random() * Math.PI * 2,
      lane: i % 5
    }));
  }

  function resize() {
    const rect = visual.getBoundingClientRect();
    w = Math.max(1, Math.round(rect.width));
    h = Math.max(1, Math.round(rect.height));
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    makePoints();
    render(performance.now(), true);
  }

  function drawGlow() {
    const g = ctx.createRadialGradient(w * .49, h * .5, 18, w * .49, h * .5, Math.max(w, h) * .53);
    g.addColorStop(0, 'rgba(84,255,211,.115)');
    g.addColorStop(.38, 'rgba(84,255,211,.045)');
    g.addColorStop(1, 'rgba(84,255,211,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
  }

  function drawFlow(now) {
    for (let lane = 0; lane < 3; lane++) {
      ctx.beginPath();
      const amp = 13 + lane * 7;
      const base = h * (.25 + lane * .24);
      const phase = now * .00045 + lane * 1.6;
      for (let x = -20; x <= w + 20; x += 12) {
        const y = base + Math.sin(x * .014 + phase) * amp + Math.sin(x * .005 - phase * .7) * 8;
        if (x === -20) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = `rgba(142,255,227,${.055 + lane * .018})`;
      ctx.lineWidth = .8;
      ctx.stroke();
    }
  }

  function render(now, staticFrame = false) {
    ctx.clearRect(0, 0, w, h);
    drawGlow();
    drawFlow(now);

    for (const p of points) {
      if (!staticFrame) {
        p.x += p.vx;
        p.y += p.vy + Math.sin(now * .0007 + p.p) * .004;
        if (pointer.active) {
          const dx = p.x - pointer.x, dy = p.y - pointer.y;
          const d2 = dx * dx + dy * dy;
          if (d2 < 8500 && d2 > 1) {
            const d = Math.sqrt(d2);
            const push = (1 - d / 92) * .012;
            p.vx += (dx / d) * push;
            p.vy += (dy / d) * push;
          }
        }
        p.vx *= .998;
        p.vy *= .998;
        if (p.x < -8) p.x = w + 8;
        else if (p.x > w + 8) p.x = -8;
        if (p.y < -8) p.y = h + 8;
        else if (p.y > h + 8) p.y = -8;
      }
      const pulse = p.a * (.82 + .18 * Math.sin(now * .0012 + p.p));
      ctx.beginPath();
      ctx.fillStyle = `rgba(149,255,230,${Math.max(.06, pulse)})`;
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    }

    for (let i = 0; i < points.length; i++) {
      const a = points[i];
      for (let j = i + 1; j < points.length; j++) {
        const b = points[j];
        const dx = a.x - b.x, dy = a.y - b.y;
        const d2 = dx * dx + dy * dy;
        if (d2 > 7600) continue;
        const alpha = .078 * (1 - d2 / 7600);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = `rgba(139,255,227,${alpha})`;
        ctx.lineWidth = .65;
        ctx.stroke();
      }
    }
  }

  function loop(now) {
    if (!visible || document.hidden || reduceMotion) { raf = 0; return; }
    if (now - last >= 30) {
      render(now, false);
      last = now;
    }
    raf = requestAnimationFrame(loop);
  }
  function start() { if (!raf && visible && !document.hidden && !reduceMotion) raf = requestAnimationFrame(loop); }
  function stop() { if (raf) cancelAnimationFrame(raf); raf = 0; }

  visual.addEventListener('pointermove', (ev) => {
    const r = visual.getBoundingClientRect();
    pointer.x = ev.clientX - r.left;
    pointer.y = ev.clientY - r.top;
    pointer.active = true;
  }, { passive: true });
  visual.addEventListener('pointerleave', () => { pointer.active = false; }, { passive: true });

  if ('ResizeObserver' in window) new ResizeObserver(resize).observe(visual);
  else window.addEventListener('resize', resize, { passive: true });

  if ('IntersectionObserver' in window) {
    new IntersectionObserver((entries) => {
      visible = !!entries[0]?.isIntersecting;
      if (visible) start(); else stop();
    }, { threshold: .04 }).observe(hero);
  }
  document.addEventListener('visibilitychange', () => document.hidden ? stop() : start());

  resize();
  start();
})();
