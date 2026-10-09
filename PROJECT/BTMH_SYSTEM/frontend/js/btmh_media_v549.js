/* BTMH 5.4.9 - true realtime media transport.
 * Local PC: ACK-paced WebSocket bitmap (no request-per-frame, no backlog).
 * LAN browser: WebRTC when aiortc is available. Fallbacks: WS -> MJPEG -> finite polling.
 * Camera / FaceID / PAD remain independent backend workers.
 */
(() => {
  'use strict';

  const slots = new Map();
  const localHosts = new Set(['127.0.0.1', 'localhost', '::1']);
  let capsCache = null;
  let capsAt = 0;

  const q = (value) => typeof value === 'string' ? document.querySelector(value) : value;
  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  const tokenHeaders = () => {
    const token = localStorage.getItem('campusface_token') || '';
    return token ? {Authorization: `Bearer ${token}`} : {};
  };

  async function fetchJson(url, init = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), Number(init.timeoutMs || 7000));
    try {
      const res = await fetch(url, {
        ...init,
        credentials: 'same-origin',
        cache: 'no-store',
        signal: controller.signal,
        headers: {'Content-Type': 'application/json', ...tokenHeaders(), ...(init.headers || {})},
      });
      let data = {};
      try { data = await res.json(); } catch (_) {}
      if (!res.ok) throw new Error(data.detail || data.message || `HTTP ${res.status}`);
      return data;
    } finally {
      clearTimeout(timeout);
    }
  }

  async function capabilities(force = false) {
    if (!force && capsCache && (Date.now() - capsAt) < 5000) return capsCache;
    try {
      capsCache = await fetchJson('/api/v1/media/capabilities', {method: 'GET', timeoutMs: 3500});
    } catch (_) {
      capsCache = {ok: false, webrtc: {available: false}, fallback: 'WEBSOCKET_ACK_BITMAP'};
    }
    capsAt = Date.now();
    return capsCache;
  }

  function event(name, detail) {
    document.dispatchEvent(new CustomEvent(name, {detail}));
  }

  function setState(slot, state, extra = {}) {
    if (!slot.active) return;
    slot.state = state;
    Object.assign(slot.metrics, extra);
    if (slot.empty) {
      const live = state === 'live';
      slot.empty.classList.toggle('hidden', live);
      slot.empty.style.display = live ? 'none' : '';
      if (!live) {
        const text = slot.empty.querySelector('p,span');
        if (text) text.textContent = state === 'connecting' ? 'Đang kết nối camera...' : 'Đang kết nối lại camera...';
      }
    }
    event('btmh:media-state', {key: slot.key, state, transport: slot.transport || '', ...extra});
  }

  function updateFps(slot) {
    const now = performance.now();
    slot.renderCount += 1;
    if (!slot.renderWindowAt) slot.renderWindowAt = now;
    const elapsed = now - slot.renderWindowAt;
    if (elapsed >= 900) {
      const fps = slot.renderCount * 1000 / Math.max(1, elapsed);
      slot.metrics.renderedFps = Math.round(fps * 10) / 10;
      slot.renderCount = 0;
      slot.renderWindowAt = now;
      event('btmh:media-stats', {key: slot.key, transport: slot.transport || '', ...slot.metrics});
    }
  }

  function fitRect(containerWidth, containerHeight, mediaWidth, mediaHeight) {
    if (!containerWidth || !containerHeight || !mediaWidth || !mediaHeight) return {x: 0, y: 0, w: containerWidth, h: containerHeight};
    const ca = containerWidth / containerHeight;
    const ma = mediaWidth / mediaHeight;
    if (ma > ca) {
      const w = containerWidth;
      const h = w / ma;
      return {x: 0, y: (containerHeight - h) / 2, w, h};
    }
    const h = containerHeight;
    const w = h * ma;
    return {x: (containerWidth - w) / 2, y: 0, w, h};
  }

  function ensureLayers(slot) {
    const wrap = slot.wrap;
    if (!wrap) throw new Error('Thiếu vùng hiển thị camera');
    if (getComputedStyle(wrap).position === 'static') wrap.style.position = 'relative';

    let video = slot.video || wrap.querySelector(`video[data-btmh-media-key="${slot.key}"]`);
    if (!video) {
      video = document.createElement('video');
      video.autoplay = true;
      video.playsInline = true;
      video.muted = true;
      video.className = 'btmh-media-video';
      video.dataset.btmhMediaCreated = '1';
      wrap.prepend(video);
    }
    video.dataset.btmhMediaKey = slot.key;
    slot.video = video;
    video.autoplay = true;
    video.playsInline = true;
    video.muted = true;
    video.classList.add('btmh-media-video');
    video.style.objectFit = slot.fit;
    if (slot.mirror) video.style.transform = 'scaleX(-1)';

    let canvas = wrap.querySelector(`canvas[data-btmh-media-canvas="${slot.key}"]`);
    if (!canvas) {
      canvas = document.createElement('canvas');
      canvas.dataset.btmhMediaCanvas = slot.key;
      canvas.className = 'btmh-media-canvas';
      wrap.prepend(canvas);
    }
    canvas.style.objectFit = slot.fit;
    if (slot.mirror) canvas.style.transform = 'scaleX(-1)';
    slot.canvas = canvas;

    if (slot.image) slot.image.classList.add('btmh-media-legacy');
    if (slot.overlay) slot.overlay.classList.add('btmh-media-overlay');
  }

  function showLayer(slot, mode) {
    if (slot.video) slot.video.classList.toggle('btmh-media-active', mode === 'video');
    if (slot.canvas) slot.canvas.classList.toggle('btmh-media-active', mode === 'canvas');
    if (slot.image) {
      slot.image.classList.toggle('btmh-media-active', mode === 'image');
      slot.image.style.display = mode === 'image' ? '' : 'none';
    }
  }

  function drawBitmap(slot, bitmap) {
    const canvas = slot.canvas;
    const wrap = slot.wrap;
    if (!canvas || !wrap) return;
    const cw = Math.max(1, wrap.clientWidth || bitmap.width);
    const ch = Math.max(1, wrap.clientHeight || bitmap.height);
    const dpr = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
    const pw = Math.max(1, Math.round(cw * dpr));
    const ph = Math.max(1, Math.round(ch * dpr));
    if (canvas.width !== pw || canvas.height !== ph) { canvas.width = pw; canvas.height = ph; }
    const ctx = canvas.getContext('2d', {alpha: false, desynchronized: true});
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#05070a';
    ctx.fillRect(0, 0, cw, ch);
    const rect = fitRect(cw, ch, bitmap.width, bitmap.height);
    ctx.drawImage(bitmap, rect.x, rect.y, rect.w, rect.h);
    slot.mediaWidth = bitmap.width;
    slot.mediaHeight = bitmap.height;
  }

  function imageDecode(blob) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(blob);
      const image = new Image();
      image.onload = () => { URL.revokeObjectURL(url); resolve(image); };
      image.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Không giải mã được frame JPEG')); };
      image.src = url;
    });
  }

  async function waitIce(pc, timeoutMs = 1600) {
    if (pc.iceGatheringState === 'complete') return;
    await new Promise(resolve => {
      const timeout = setTimeout(done, timeoutMs);
      function done() { clearTimeout(timeout); pc.removeEventListener('icegatheringstatechange', change); resolve(); }
      function change() { if (pc.iceGatheringState === 'complete') done(); }
      pc.addEventListener('icegatheringstatechange', change);
    });
  }

  function waitVideo(video, timeoutMs = 6000) {
    return new Promise((resolve, reject) => {
      if (video.readyState >= 2 && video.videoWidth > 0) return resolve();
      const timeout = setTimeout(() => finish(new Error('WebRTC chưa nhận được hình')), timeoutMs);
      const onReady = () => finish();
      function finish(err) {
        clearTimeout(timeout);
        video.removeEventListener('loadeddata', onReady);
        video.removeEventListener('playing', onReady);
        err ? reject(err) : resolve();
      }
      video.addEventListener('loadeddata', onReady, {once: true});
      video.addEventListener('playing', onReady, {once: true});
    });
  }

  function startVideoFrameMeter(slot) {
    const video = slot.video;
    if (!video || typeof video.requestVideoFrameCallback !== 'function') return;
    const generation = slot.generation;
    const tick = () => {
      if (!slot.active || slot.generation !== generation || slot.transport !== 'WEBRTC') return;
      updateFps(slot);
      slot.rvfc = video.requestVideoFrameCallback(tick);
    };
    slot.rvfc = video.requestVideoFrameCallback(tick);
  }

  function startWebrtcStats(slot) {
    const pc = slot.pc;
    if (!pc) return;
    let lastFrames = 0, lastAt = performance.now();
    clearInterval(slot.statsTimer);
    slot.statsTimer = setInterval(async () => {
      if (!slot.active || slot.pc !== pc) return;
      try {
        const stats = await pc.getStats();
        let inbound = null;
        stats.forEach(report => { if (report.type === 'inbound-rtp' && report.kind === 'video') inbound = report; });
        if (!inbound) return;
        const now = performance.now();
        const frames = Number(inbound.framesDecoded || 0);
        const fps = (frames - lastFrames) * 1000 / Math.max(1, now - lastAt);
        lastFrames = frames; lastAt = now;
        slot.metrics.decodedFps = Math.max(0, Math.round(fps * 10) / 10);
        slot.metrics.jitterMs = Math.round(Number(inbound.jitter || 0) * 1000 * 10) / 10;
        slot.metrics.packetsLost = Number(inbound.packetsLost || 0);
        event('btmh:media-stats', {key: slot.key, transport: slot.transport, ...slot.metrics});
      } catch (_) {}
    }, 1000);
  }

  async function startWebRTC(slot, caps) {
    if (!window.RTCPeerConnection || !caps?.webrtc?.available) return false;
    const generation = slot.generation;
    const pc = new RTCPeerConnection({iceServers: []});
    slot.pc = pc;
    slot.transport = 'WEBRTC';
    showLayer(slot, 'video');
    setState(slot, 'connecting');

    let trackSeen = false;
    pc.ontrack = async eventObj => {
      if (!slot.active || slot.generation !== generation) return;
      trackSeen = true;
      const stream = eventObj.streams?.[0] || new MediaStream([eventObj.track]);
      slot.video.srcObject = stream;
      try { await slot.video.play(); } catch (_) {}
    };
    pc.onconnectionstatechange = () => {
      if (!slot.active || slot.pc !== pc) return;
      const s = pc.connectionState;
      if (s === 'connected') setState(slot, 'live', {transport: 'WEBRTC'});
      if (['failed', 'disconnected', 'closed'].includes(s)) recover(slot, 'WEBRTC');
    };

    try {
      pc.addTransceiver('video', {direction: 'recvonly'});
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitIce(pc);
      const answer = await fetchJson('/api/v1/media/webrtc/offer', {
        method: 'POST',
        body: JSON.stringify({sdp: pc.localDescription?.sdp || offer.sdp, type: pc.localDescription?.type || offer.type}),
        timeoutMs: 9000,
      });
      slot.sessionId = answer.session_id || '';
      await pc.setRemoteDescription({type: answer.type || 'answer', sdp: answer.sdp});
      await waitVideo(slot.video, 6500);
      if (!slot.active || slot.generation !== generation || !trackSeen) throw new Error('WebRTC không nhận được video track');
      setState(slot, 'live', {transport: 'WEBRTC'});
      startVideoFrameMeter(slot);
      startWebrtcStats(slot);
      return true;
    } catch (_) {
      await closeWebRTC(slot);
      return false;
    }
  }

  async function closeWebRTC(slot) {
    const sid = slot.sessionId;
    slot.sessionId = '';
    clearInterval(slot.statsTimer); slot.statsTimer = null;
    if (slot.video) {
      try { slot.video.pause(); } catch (_) {}
      slot.video.srcObject = null;
    }
    const pc = slot.pc; slot.pc = null;
    if (pc) { try { pc.ontrack = null; pc.onconnectionstatechange = null; pc.close(); } catch (_) {} }
    if (sid) {
      fetchJson('/api/v1/media/webrtc/close', {method: 'POST', body: JSON.stringify({session_id: sid}), timeoutMs: 2500}).catch(() => {});
    }
  }

  async function startWebSocket(slot) {
    if (!window.WebSocket || !slot.canvas) return false;
    const generation = slot.generation;
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${scheme}://${location.host}/api/v1/media/preview/ws`);
    slot.ws = ws;
    slot.transport = 'WEBSOCKET_ACK_BITMAP';
    ws.binaryType = 'arraybuffer';
    showLayer(slot, 'canvas');
    setState(slot, 'connecting');

    return await new Promise(resolve => {
      let settled = false;
      let frameSeen = false;
      const timeout = setTimeout(() => finish(false), 4500);
      const finish = (ok) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        resolve(ok);
      };
      ws.onopen = () => {};
      ws.onmessage = async e => {
        if (!slot.active || slot.generation !== generation || slot.ws !== ws) return;
        try {
          const blob = e.data instanceof Blob ? e.data : new Blob([e.data], {type: 'image/jpeg'});
          let bitmap = null;
          if ('createImageBitmap' in window) {
            bitmap = await createImageBitmap(blob);
            drawBitmap(slot, bitmap);
            bitmap.close?.();
          } else {
            const image = await imageDecode(blob);
            drawBitmap(slot, image);
          }
          frameSeen = true;
          updateFps(slot);
          setState(slot, 'live', {transport: 'WEBSOCKET_ACK_BITMAP'});
          if (ws.readyState === WebSocket.OPEN) ws.send('ack');
          finish(true);
        } catch (_) {
          if (ws.readyState === WebSocket.OPEN) ws.send('ack');
        }
      };
      ws.onerror = () => { if (!frameSeen) finish(false); };
      ws.onclose = () => {
        const established = frameSeen;
        if (!frameSeen) finish(false);
        if (established && slot.active && slot.generation === generation && slot.ws === ws) recover(slot, 'WEBSOCKET_ACK_BITMAP');
      };
    });
  }

  function startMjpeg(slot) {
    if (!slot.image) return Promise.resolve(false);
    const generation = slot.generation;
    slot.transport = 'MJPEG';
    showLayer(slot, 'image');
    setState(slot, 'connecting');
    return new Promise(resolve => {
      let settled = false;
      const timeout = setTimeout(() => finish(false), 4500);
      const finish = ok => { if (settled) return; settled = true; clearTimeout(timeout); resolve(ok); };
      slot.image.onload = () => {
        if (!slot.active || slot.generation !== generation) return;
        updateFps(slot);
        setState(slot, 'live', {transport: 'MJPEG'});
        finish(true);
      };
      slot.image.onerror = () => finish(false);
      slot.image.src = `${slot.mjpegUrl}${slot.mjpegUrl.includes('?') ? '&' : '?'}t=${Date.now()}`;
    });
  }

  async function startPolling(slot) {
    if (!slot.image || !window.BTMHRuntime?.preview) return false;
    slot.transport = 'HTTP_SNAPSHOT_FALLBACK';
    showLayer(slot, 'image');
    slot.image.onload = () => { updateFps(slot); setState(slot, 'live', {transport: slot.transport}); };
    slot.image.onerror = () => setState(slot, 'reconnecting', {transport: slot.transport});
    BTMHRuntime.preview(slot.image, slot.pollUrl, 140);
    await sleep(250);
    return true;
  }

  async function startMetadata(slot) {
    if (!slot.overlay || !window.WebSocket) return;
    const generation = slot.generation;
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${scheme}://${location.host}/api/v1/media/metadata/ws`);
    slot.metaWs = ws;
    ws.onmessage = e => {
      if (!slot.active || slot.generation !== generation || slot.metaWs !== ws) return;
      try {
        const payload = JSON.parse(e.data || '{}');
        slot.meta = payload;
        drawOverlay(slot);
        if (ws.readyState === WebSocket.OPEN) ws.send('ack');
      } catch (_) { if (ws.readyState === WebSocket.OPEN) ws.send('ack'); }
    };
    ws.onclose = () => {
      if (!slot.active || slot.generation !== generation || slot.metaWs !== ws) return;
      setTimeout(() => { if (slot.active && slot.generation === generation) startMetadata(slot); }, 900);
    };
  }

  function drawOverlay(slot) {
    const canvas = slot.overlay;
    const wrap = slot.wrap;
    const meta = slot.meta;
    if (!canvas || !wrap || !meta) return;
    const cw = Math.max(1, wrap.clientWidth);
    const ch = Math.max(1, wrap.clientHeight);
    const dpr = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
    if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) {
      canvas.width = Math.round(cw * dpr); canvas.height = Math.round(ch * dpr);
    }
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, cw, ch);
    const sw = Number(meta.frame_width || slot.mediaWidth || slot.video?.videoWidth || 0);
    const sh = Number(meta.frame_height || slot.mediaHeight || slot.video?.videoHeight || 0);
    if (!sw || !sh) return;
    const rect = fitRect(cw, ch, sw, sh);
    const sx = rect.w / sw, sy = rect.h / sh;
    for (const tr of (meta.tracks || [])) {
      const raw = Array.isArray(tr.face_bbox) && tr.face_bbox.some(Number) ? tr.face_bbox : tr.bbox;
      if (!Array.isArray(raw) || raw.length < 4) continue;
      let [x1, y1, x2, y2] = raw.map(Number);
      if (x2 <= x1 || y2 <= y1) continue;
      let dx = rect.x + x1 * sx, dy = rect.y + y1 * sy, dw = (x2 - x1) * sx, dh = (y2 - y1) * sy;
      if (slot.mirror) dx = cw - (dx + dw);
      const blocked = !!tr.spoof_blocked;
      const recognized = !!tr.recognized || !!tr.identity_verified;
      ctx.strokeStyle = blocked ? '#ff5d5d' : recognized ? '#2ed4a0' : '#18a9ff';
      ctx.lineWidth = 2;
      ctx.strokeRect(dx, dy, dw, dh);
      const label = blocked ? 'PAD BLOCK' : recognized ? (tr.full_name || tr.student_code || 'FaceID') : 'ANALYZING';
      ctx.font = '600 11px system-ui, sans-serif';
      const tw = Math.ceil(ctx.measureText(label).width) + 12;
      const ty = Math.max(16, dy - 5);
      ctx.fillStyle = 'rgba(4,18,29,.78)'; ctx.fillRect(dx, ty - 15, tw, 18);
      ctx.fillStyle = '#fff'; ctx.fillText(label, dx + 6, ty - 2);
    }
  }

  async function closeTransport(slot) {
    clearInterval(slot.statsTimer); slot.statsTimer = null;
    if (slot.ws) { const ws = slot.ws; slot.ws = null; ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null; try { ws.send('close'); } catch (_) {} try { ws.close(); } catch (_) {} }
    if (slot.metaWs) { const ws = slot.metaWs; slot.metaWs = null; ws.onmessage = ws.onclose = null; try { ws.send('close'); } catch (_) {} try { ws.close(); } catch (_) {} }
    await closeWebRTC(slot);
    if (slot.image && window.BTMHRuntime?.stopPreview) BTMHRuntime.stopPreview(slot.image);
    if (slot.image) { slot.image.onload = null; slot.image.onerror = null; slot.image.removeAttribute('src'); }
    if (slot.overlay) { const ctx = slot.overlay.getContext?.('2d'); ctx?.clearRect(0, 0, slot.overlay.width || 1, slot.overlay.height || 1); }
  }

  async function recover(slot, failedTransport) {
    if (!slot.active || slot.recovering || slot.transport !== failedTransport) return;
    slot.recovering = true;
    slot.recoverySeq = Number(slot.recoverySeq || 0) + 1;
    const seq = slot.recoverySeq;
    setState(slot, 'reconnecting', {failedTransport});
    await closeTransport(slot);
    await sleep(350);
    if (slot.active && seq === slot.recoverySeq) await start(slot, true);
    slot.recovering = false;
  }

  async function start(slot, retry = false) {
    if (!slot.active) return;
    slot.generation += 1;
    const caps = await capabilities(retry);
    const local = localHosts.has(location.hostname.toLowerCase());
    // Same-PC deployment avoids a second video encode: ACK WebSocket is the fastest path.
    // LAN clients prefer WebRTC for bandwidth-efficient browser-native playback.
    const order = local ? ['ws', 'webrtc', 'mjpeg', 'poll'] : ['webrtc', 'ws', 'mjpeg', 'poll'];
    for (const transport of order) {
      if (!slot.active) return;
      let ok = false;
      if (transport === 'webrtc') ok = await startWebRTC(slot, caps);
      else if (transport === 'ws') ok = await startWebSocket(slot);
      else if (transport === 'mjpeg') ok = await startMjpeg(slot);
      else ok = await startPolling(slot);
      if (ok) { startMetadata(slot); return; }
      await closeTransport(slot);
    }
    setState(slot, 'reconnecting', {transport: 'NONE'});
  }

  function mount(key, options = {}) {
    stop(key);
    const wrap = q(options.wrap);
    const slot = {
      key,
      active: true,
      generation: 0,
      recovering: false,
      recoverySeq: 0,
      wrap,
      video: q(options.video),
      image: q(options.image),
      empty: q(options.empty),
      overlay: q(options.overlay),
      mirror: !!options.mirror,
      fit: options.fit || 'contain',
      mjpegUrl: options.mjpegUrl || '/api/v1/camera/stream.mjpg',
      pollUrl: options.pollUrl || '/api/v1/camera/frame.jpg',
      transport: '',
      pc: null, ws: null, metaWs: null, sessionId: '',
      canvas: null, meta: null, mediaWidth: 0, mediaHeight: 0,
      renderCount: 0, renderWindowAt: 0, statsTimer: null, rvfc: null,
      metrics: {renderedFps: 0, decodedFps: 0, jitterMs: 0, packetsLost: 0},
    };
    ensureLayers(slot);
    slots.set(key, slot);
    setState(slot, 'connecting');
    start(slot).catch(() => setState(slot, 'reconnecting'));
    return slot;
  }

  function stop(key) {
    const slot = slots.get(key);
    if (!slot) return;
    slots.delete(key);
    slot.active = false;
    slot.generation += 1;
    closeTransport(slot).catch(() => {});
    showLayer(slot, 'none');
    if (slot.empty) { slot.empty.classList.remove('hidden'); slot.empty.style.display = ''; }
  }

  function stopAll() { [...slots.keys()].forEach(stop); }
  function stats() {
    const out = {};
    slots.forEach((slot, key) => { out[key] = {state: slot.state, transport: slot.transport, ...slot.metrics}; });
    return out;
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopAll();
  });
  window.addEventListener('pagehide', stopAll);
  window.BTMHMedia = {mount, stop, stopAll, stats, capabilities};
})();
