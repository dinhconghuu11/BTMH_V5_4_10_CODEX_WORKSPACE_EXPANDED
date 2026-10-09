/* BTMH 5.4.10: RTSP H.264 -> MediaMTX -> authenticated WHEP -> native video.
 * Python WebRTC / WEBSOCKET_ACK_BITMAP / MJPEG / polling are explicit fallbacks.
 * Each negotiation owns its resources; AI metadata never gates video playback.
 */
(() => {
  'use strict';
  const slots = new Map(), capsCache = new Map();
  let presentationAllowed = true;
  const q = value => typeof value === 'string' ? document.querySelector(value) : value;
  const abortError = () => new DOMException('Media request cancelled', 'AbortError');
  const safeReason = value => String(value?.message || value || 'UNKNOWN_ERROR').replace(/rtsps?:\/\/[^\s'"<>]+/gi, '[RTSP_SOURCE_REDACTED]').slice(0, 350);
  const qualityReasons = new Set(['SMALL_NOT_VALIDATED', 'SMALL_UNAVAILABLE', 'SMALL_DISABLED', 'SMALL_SOURCE_REJECTED', 'SMALL_GATEWAY_UNAVAILABLE', 'SMALL_CONFIG_FAILED', 'SMALL_NEGOTIATION_FAILED', 'SMALL_AND_MAIN_UNAVAILABLE', 'ADAPTIVE_DISABLED', 'NON_PRIMARY_CAMERA']);
  const qualityReason = (value, fallback = 'SMALL_UNAVAILABLE') => qualityReasons.has(value) ? value : fallback;
  const tokenHeaders = () => { const token = localStorage.getItem('campusface_token') || ''; return token ? {Authorization: `Bearer ${token}`} : {}; };
  const cameraQuery = slot => slot.cameraId == null ? '' : `?camera_id=${encodeURIComponent(slot.cameraId)}`;
  const alive = slot => slot.active && slots.get(slot.key) === slot;
  const owns = (slot, attempt) => alive(slot) && slot.attempt === attempt && slot.generation === attempt.generation && !attempt.disposed && !slot.controller?.signal.aborted;
  function check(slot, attempt) { if (!owns(slot, attempt)) throw abortError(); if (attempt.failure) throw attempt.failure; if (attempt.controller.signal.aborted) throw abortError(); }
  function event(name, detail) { document.dispatchEvent(new CustomEvent(name, {detail})); }

  async function fetchBody(url, init = {}) {
    const {timeoutMs = 7000, signal, onResponse, ...options} = init;
    const controller = new AbortController(), abort = () => controller.abort();
    if (signal?.aborted) throw abortError();
    signal?.addEventListener('abort', abort, {once: true}); const timer = setTimeout(abort, timeoutMs);
    try {
      const response = await fetch(url, {...options, credentials: 'same-origin', cache: 'no-store', signal: controller.signal, headers: {...tokenHeaders(), ...(options.headers || {})}});
      onResponse?.(response);
      const body = await response.text(); if (controller.signal.aborted) throw abortError();
      if (!response.ok) {
        let detail = '', code = ''; try { const data = JSON.parse(body); detail = [data.code,data.detail||data.message].filter(Boolean).join(': '); if (qualityReasons.has(data.code)) code = data.code; } catch (_) {}
        const error = new Error(safeReason(detail || `HTTP_${response.status}`)); error.code = code; throw error;
      }
      return {response, body};
    } catch (error) { if (controller.signal.aborted && !signal?.aborted) throw new Error('REQUEST_TIMEOUT'); throw error; }
    finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
  }
  async function fetchJson(url, init = {}) {
    const result = await fetchBody(url, {...init, headers: {'Content-Type': 'application/json', ...(init.headers || {})}});
    return JSON.parse(result.body || '{}');
  }
  async function capabilities(force = false, cameraId = null, signal) {
    const key = cameraId == null ? 'active' : String(cameraId), cached = capsCache.get(key);
    if (!force && cached && Date.now() - cached.at < 5000) return cached.data;
    const data = await fetchJson('/api/v1/media/capabilities' + (cameraId == null ? '' : `?camera_id=${encodeURIComponent(cameraId)}`), {method: 'GET', timeoutMs: 4000, signal});
    if (signal?.aborted) throw abortError(); capsCache.set(key, {at: Date.now(), data}); return data;
  }
  function invalidate() { capsCache.clear(); }
  function currentTransport(slot) { return slot.state === 'live' ? slot.metrics.legacyTransport || slot.transport || 'NONE' : 'NONE'; }
  function snapshot(slot) { return {key: slot.key, cameraId: slot.cameraId, state: slot.state, transport: slot.transport, ...slot.metrics, currentTransport: currentTransport(slot)}; }
  function gatewayReason(gateway = {}) {
    const value = gateway.reason_code || gateway.reason || gateway.error_code;
    return typeof value === 'string' && /^[A-Z][A-Z0-9_]{1,79}$/.test(value) ? value : gateway.available ? null : 'NATIVE_GATEWAY_UNAVAILABLE';
  }
  function updateGateway(slot, gateway = {}) {
    const state = ['UNAVAILABLE', 'BLOCKED', 'STARTING', 'STOPPED', 'DISABLED', 'ERROR', 'READY', 'RUNNING', 'AVAILABLE'].includes(gateway.state) ? gateway.state : gateway.available ? 'READY' : 'UNAVAILABLE';
    Object.assign(slot.metrics, {nativeGatewayAvailable: gateway.available === true, nativeGatewayState: state, nativeGatewayReason: gatewayReason(gateway),
      nativeGatewayRunning: gateway.running ?? gateway.process_alive ?? null, rtspSourceHealthy: gateway.source_healthy ?? null});
  }
  function publish(slot) {
    if (!alive(slot)) return;
    slot.wrap.dataset.btmhTransport = slot.transport || 'NONE'; slot.wrap.dataset.btmhMediaState = slot.state || 'connecting';
    slot.wrap.dataset.btmhCurrentTransport = currentTransport(slot); slot.wrap.dataset.btmhNativeGateway = slot.metrics.nativeGatewayState;
    slot.wrap.dataset.btmhRequestedQuality = slot.requestedQuality; slot.wrap.dataset.btmhQuality = slot.metrics.quality || 'main';
    slot.wrap.dataset.btmhQualityFallback = slot.metrics.qualityFallbackReason || '';
    if (slot.status) {
      const fallback = slot.state === 'live' && slot.transport !== 'NATIVE_GATEWAY_WEBRTC';
      slot.status.classList.toggle('btmh-media-fallback', fallback || slot.metrics.nativeGatewayAvailable === false);
      const text = [`Native Gateway: ${slot.metrics.nativeGatewayState}`, slot.metrics.nativeGatewayReason ? `Reason: ${slot.metrics.nativeGatewayReason}` : '',
        `Current transport: ${currentTransport(slot)}${fallback ? ' (fallback)' : ''}`,
        slot.state !== 'live' ? `Video: ${slot.state}${slot.transport ? ' / ' + slot.transport : ''}` : '',
        fallback && !slot.metrics.nativeGatewayReason && slot.metrics.fallbackReason ? `Fallback: ${safeReason(slot.metrics.fallbackReason)}` : ''].filter(Boolean).join('\n');
      if (slot.status.textContent !== text) slot.status.textContent = text;
    }
    event('btmh:media-stats', snapshot(slot));
  }
  function setState(slot, state, extra = {}) {
    if (!alive(slot)) return; slot.state = state; Object.assign(slot.metrics, extra);
    if (slot.empty) {
      const live = state === 'live'; slot.empty.classList.toggle('hidden', live); slot.empty.style.display = live ? 'none' : '';
      const text = slot.empty.querySelector('p,span'); if (text && !live) text.textContent = state === 'connecting' ? 'Đang kết nối camera...' : 'Đang kết nối lại camera...';
    }
    event('btmh:media-state', snapshot(slot)); publish(slot);
  }
  function recordFallback(slot, transport, error) {
    const reason = safeReason(error); slot.chainFailures.push(`${transport}: ${reason}`);
    slot.metrics.fallbackReason = slot.chainFailures.join('; ');
    slot.metrics.fallbackHistory = [...slot.metrics.fallbackHistory, {transport, reason, at: new Date().toISOString()}].slice(-10);
    console.warn('[BTMH media fallback]', {key: slot.key, cameraId: slot.cameraId, transport, reason});
    event('btmh:media-fallback', {key: slot.key, cameraId: slot.cameraId, transport, reason}); publish(slot);
  }
  function recordQualityFallback(slot, reason) {
    reason = qualityReason(reason);
    if (reason === 'SMALL_NEGOTIATION_FAILED') slot.smallRetryBlocked = true;
    if (slot.metrics.qualityFallbackReason === reason && slot.metrics.quality === 'main') return;
    slot.metrics.quality = 'main'; slot.metrics.qualityFallbackReason = reason;
    event('btmh:media-quality-fallback', {key: slot.key, cameraId: slot.cameraId, requestedQuality: slot.requestedQuality, quality: 'main', reason}); publish(slot);
  }
  function fitRect(cw, ch, mw, mh) {
    if (!cw || !ch || !mw || !mh) return {x: 0, y: 0, w: cw, h: ch};
    const scale = Math.min(cw / mw, ch / mh), w = mw * scale, h = mh * scale; return {x: (cw - w) / 2, y: (ch - h) / 2, w, h};
  }
  function ensureLayers(slot) {
    if (!slot.wrap) throw new Error('Thiếu vùng hiển thị camera');
    if (getComputedStyle(slot.wrap).position === 'static') slot.wrap.style.position = 'relative';
    if (!slot.video) slot.video = slot.wrap.querySelector(`video[data-btmh-media-key="${slot.key}"]`);
    if (!slot.video) { slot.video = document.createElement('video'); slot.video.dataset.btmhMediaCreated = '1'; slot.wrap.prepend(slot.video); }
    const video = slot.video; video.dataset.btmhMediaKey = slot.key; video.autoplay = true; video.playsInline = true; video.muted = true;
    video.classList.add('btmh-media-video'); video.style.objectFit = slot.fit; video.style.transform = slot.mirror ? 'scaleX(-1)' : '';
    slot.canvas = slot.wrap.querySelector(`canvas[data-btmh-media-canvas="${slot.key}"]`);
    if (!slot.canvas) { slot.canvas = document.createElement('canvas'); slot.canvas.dataset.btmhMediaCanvas = slot.key; slot.canvas.className = 'btmh-media-canvas'; slot.wrap.prepend(slot.canvas); }
    slot.canvas.style.transform = slot.mirror ? 'scaleX(-1)' : '';
    slot.image?.classList.add('btmh-media-legacy'); slot.overlay?.classList.add('btmh-media-overlay');
    slot.status = document.createElement('div'); slot.status.className = 'btmh-media-transport-status'; slot.status.role = 'status'; slot.status.ariaLive = 'polite'; slot.wrap.prepend(slot.status);
  }
  function showLayer(slot, mode) {
    slot.video?.classList.toggle('btmh-media-active', mode === 'video'); slot.canvas?.classList.toggle('btmh-media-active', mode === 'canvas');
    if (slot.image) { slot.image.classList.toggle('btmh-media-active', mode === 'image'); slot.image.style.display = mode === 'image' ? '' : 'none'; }
  }
  function drawBitmap(slot, bitmap) {
    const cw = Math.max(1, slot.wrap.clientWidth || bitmap.width), ch = Math.max(1, slot.wrap.clientHeight || bitmap.height), dpr = Math.min(2, Math.max(1, window.devicePixelRatio || 1)), canvas = slot.canvas;
    if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) { canvas.width = Math.round(cw * dpr); canvas.height = Math.round(ch * dpr); }
    const ctx = canvas.getContext('2d', {alpha: false, desynchronized: true}); if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.fillStyle = '#05070a'; ctx.fillRect(0, 0, cw, ch);
    const rect = fitRect(cw, ch, bitmap.width, bitmap.height); ctx.drawImage(bitmap, rect.x, rect.y, rect.w, rect.h); slot.mediaWidth = bitmap.width; slot.mediaHeight = bitmap.height;
  }
  function waitFor(target, events, ready, signal, timeoutMs, message) {
    return new Promise((resolve, reject) => {
      let timer;
      const finish = error => { clearTimeout(timer); events.forEach(name => target.removeEventListener(name, tick)); signal.removeEventListener('abort', cancel); error ? reject(error) : resolve(); };
      const tick = () => { if (ready()) finish(); }, cancel = () => finish(abortError());
      if (signal.aborted) return reject(abortError()); if (ready()) return resolve();
      events.forEach(name => target.addEventListener(name, tick)); signal.addEventListener('abort', cancel, {once: true}); timer = setTimeout(() => finish(new Error(message)), timeoutMs);
    });
  }
  async function waitIce(pc, signal) {
    try { await waitFor(pc, ['icegatheringstatechange'], () => pc.iceGatheringState === 'complete', signal, 2000, 'ICE_GATHER_TIMEOUT'); }
    catch (error) { if (error.name === 'AbortError') throw error; }
  }
  function abortable(promise, signal) {
    return new Promise((resolve, reject) => {
      if (signal.aborted) return reject(abortError());
      const cancel = () => reject(abortError()); signal.addEventListener('abort', cancel, {once: true});
      Promise.resolve(promise).then(resolve, reject).finally(() => signal.removeEventListener('abort', cancel));
    });
  }
  function newAttempt(slot, name, timeoutMs = 25000) {
    const controller = new AbortController(), parentSignal = slot.controller.signal, abort = () => controller.abort(); parentSignal.addEventListener('abort', abort, {once: true});
    const attempt = {name, generation: slot.generation, controller, disposed: false, cleanup: [], pc: null, ws: null, sessionId: '', sessionUrl: '', lastFrameAt: performance.now(), lastRenderedAt: performance.now(), received: 0, rendered: 0, at: performance.now(), failure: null};
    attempt.negotiationTimer = setTimeout(() => { attempt.failure = new Error(`${name}_NEGOTIATION_TIMEOUT`); controller.abort(); }, timeoutMs);
    attempt.cleanup.push(() => clearTimeout(attempt.negotiationTimer));
    attempt.cleanup.push(() => parentSignal.removeEventListener('abort', abort)); slot.attempt = attempt; slot.transport = name;
    Object.assign(slot.metrics, {receivedFps: null, renderedFps: null, decodedFps: null, videoLatencyMs: null, frameAgeMs: null, frameAgeSource: null, playoutBufferMs: null, webRTCConnected: false, codec: null, jitterMs: null, packetsLost: null, roundTripMs: null, legacyTransport:null, lastRenderedAgoMs:null, lastFrameActivityAgoMs:null});
    setState(slot, 'connecting'); return attempt;
  }
  function deleteNativeSession(url) {
    if (!url) return;
    try { const parsed = new URL(url, location.href); if (parsed.origin !== location.origin || !parsed.pathname.startsWith('/api/v1/media/gateway/')) return;
      fetchBody(parsed.href, {method: 'DELETE', timeoutMs: 2500, keepalive: true}).catch(() => {}); } catch (_) {}
  }
  function closePythonSession(id) { if (id) fetchJson('/api/v1/media/webrtc/close', {method: 'POST', body: JSON.stringify({session_id: id}), timeoutMs: 2500, keepalive: true}).catch(() => {}); }
  function disposeAttempt(slot, attempt) {
    if (!attempt || attempt.disposed) return; attempt.disposed = true; attempt.controller.abort(); attempt.cleanup.splice(0).forEach(clean => { try { clean(); } catch (_) {} });
    if (attempt.pc) { attempt.pc.ontrack = attempt.pc.onconnectionstatechange = null; try { attempt.pc.close(); } catch (_) {} }
    if (attempt.ws) { const ws = attempt.ws; ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null; try { ws.send('close'); } catch (_) {} try { ws.close(); } catch (_) {} }
    deleteNativeSession(attempt.sessionUrl); closePythonSession(attempt.sessionId); attempt.sessionUrl = ''; attempt.sessionId = '';
    if (slot.attempt === attempt) {
      slot.attempt = null; try { slot.video.pause(); } catch (_) {} slot.video.srcObject = null;
      if (slot.image) { window.BTMHRuntime?.stopPreview?.(slot.image); slot.image.onload = slot.image.onerror = null; slot.image.removeAttribute('src'); }
    }
  }
  function closeMetadata(slot) {
    clearTimeout(slot.metaRetry); slot.metaRetry = null; const ws = slot.metaWs; slot.metaWs = null;
    if (ws) { ws.onmessage = ws.onclose = null; try { ws.send('close'); } catch (_) {} try { ws.close(); } catch (_) {} }
    const ctx = slot.overlay?.getContext?.('2d'); ctx?.clearRect(0, 0, slot.overlay.width || 1, slot.overlay.height || 1);
  }
  function closeTransport(slot) {
    // Local cleanup completes synchronously before another mount can reuse these elements.
    slot.controller?.abort(); disposeAttempt(slot, slot.attempt); closeMetadata(slot); clearTimeout(slot.reconnectTimer); slot.reconnectTimer = null; slot.negotiating = false;
  }
  function receivedFrame(slot, attempt) {
    check(slot, attempt); attempt.lastFrameAt = attempt.lastRenderedAt = performance.now(); attempt.received += 1; attempt.rendered += 1;
    slot.metrics.videoWidth = slot.video?.videoWidth || slot.mediaWidth || slot.image?.naturalWidth || null; slot.metrics.videoHeight = slot.video?.videoHeight || slot.mediaHeight || slot.image?.naturalHeight || null;
  }
  function startVideoFrameMeter(slot, attempt) {
    const video = slot.video; if (typeof video.requestVideoFrameCallback !== 'function') return; let callbackId;
    const tick = (now, metadata = {}) => {
      if (!owns(slot, attempt)) return; attempt.lastFrameAt = attempt.lastRenderedAt = performance.now(); attempt.rendered += 1;
      slot.metrics.videoWidth = video.videoWidth || null; slot.metrics.videoHeight = video.videoHeight || null;
      slot.metrics.frameAgeMs = slot.metrics.videoLatencyMs = slot.metrics.frameAgeSource = null;
      if (Number.isFinite(metadata.captureTime)) { const age = now - metadata.captureTime; if (age >= 0 && age < 60000) { slot.metrics.frameAgeMs = Math.round(age); slot.metrics.videoLatencyMs = Math.round(age); slot.metrics.frameAgeSource = 'browser_capture_time_estimate'; } }
      callbackId = video.requestVideoFrameCallback(tick);
    };
    callbackId = video.requestVideoFrameCallback(tick); attempt.cleanup.push(() => video.cancelVideoFrameCallback?.(callbackId));
  }
  function scheduleReconnect(slot, reason) {
    if (!alive(slot) || slot.recovering) return; slot.recovering = true; slot.metrics.reconnectCount += 1; const seq = ++slot.recoverySeq; closeTransport(slot);
    Object.assign(slot.metrics, {receivedFps: 0, renderedFps: 0, decodedFps: 0, webRTCConnected: false, reconnectReason: safeReason(reason)}); setState(slot, 'reconnecting');
    slot.reconnectTimer = setTimeout(() => { if (!alive(slot) || slot.recoverySeq !== seq) return; slot.reconnectTimer = null; slot.recovering = false; start(slot, true); }, 350);
  }
  function connectionFailure(slot, attempt, reason) {
    if (!owns(slot, attempt)) return;
    if (slot.negotiating) { attempt.failure = new Error(reason); attempt.controller.abort(); } else scheduleReconnect(slot, reason);
  }
  function configurePeer(slot, attempt) {
    const pc = new RTCPeerConnection({iceServers: []}); attempt.pc = pc;let disconnectTimer=null;
    attempt.cleanup.push(()=>clearTimeout(disconnectTimer));
    pc.ontrack = e => { if (!owns(slot, attempt)) return; slot.video.srcObject = e.streams?.[0] || new MediaStream([e.track]); slot.video.play().catch(() => {}); };
    pc.onconnectionstatechange = () => {
      if (!owns(slot, attempt)) return; slot.metrics.webRTCConnected = pc.connectionState === 'connected'; publish(slot);
      clearTimeout(disconnectTimer);disconnectTimer=null;
      if (['failed', 'closed'].includes(pc.connectionState)) connectionFailure(slot, attempt, `${attempt.name}_${pc.connectionState.toUpperCase()}`);
      if (pc.connectionState === 'disconnected') disconnectTimer=setTimeout(()=>{disconnectTimer=null;if(pc.connectionState==='disconnected')connectionFailure(slot,attempt,`${attempt.name}_DISCONNECTED`);},1500);
    };
    return pc;
  }
  async function startNativeGateway(slot, attempt, caps, quality = 'main') {
    const gateway = caps?.native_gateway || {};
    if (!gateway.available || !gateway.whep_url) throw new Error(gatewayReason(gateway) || 'NATIVE_GATEWAY_UNAVAILABLE');
    if (!window.RTCPeerConnection) throw new Error('BROWSER_WEBRTC_UNAVAILABLE');
    if (slot.cameraId != null && caps.camera_matches_active !== true) throw new Error('NON_PRIMARY_CAMERA');
    const whep = new URL(gateway.whep_url, location.href); if (whep.origin !== location.origin || !whep.pathname.startsWith('/api/v1/media/gateway/')) throw new Error('WHEP_SAME_ORIGIN_REQUIRED');
    if (slot.cameraId != null) whep.searchParams.set('camera_id', slot.cameraId);
    whep.searchParams.set('quality', quality); slot.metrics.quality = quality;
    if (quality === 'small') slot.metrics.qualityFallbackReason = null;
    const pc = configurePeer(slot, attempt); showLayer(slot, 'video'); pc.addTransceiver('video', {direction: 'recvonly'});
    const offer = await abortable(pc.createOffer(), attempt.controller.signal); check(slot, attempt); await abortable(pc.setLocalDescription(offer), attempt.controller.signal); check(slot, attempt); await waitIce(pc, attempt.controller.signal); check(slot, attempt);
    // The server may consume one bounded small attempt and one main retry.
    // Wait for that shared result before deciding on any browser-side retry.
    const result = await fetchBody(whep.href, {method: 'POST', signal: attempt.controller.signal, timeoutMs: quality === 'small' ? 24000 : 11000, headers: {'Content-Type': 'application/sdp', Accept: 'application/sdp'}, body: pc.localDescription?.sdp || offer.sdp,
      onResponse: response => {
        // Register ownership when headers arrive, including a slow/aborted SDP body.
        const header=response.headers.get('Location');
        if(header){
          const session=new URL(header,whep.href);if(session.origin!==location.origin||!session.pathname.startsWith('/api/v1/media/gateway/'))throw new Error('WHEP_SESSION_ORIGIN_INVALID');
          if(!owns(slot,attempt)||attempt.controller.signal.aborted){deleteNativeSession(session.href);throw abortError();}
          attempt.sessionUrl=session.href;
        }
        if(!response.ok || !owns(slot,attempt))return;
        const actual=response.headers.get('X-BTMH-Quality');
        if(actual && !['main','small'].includes(actual))throw new Error('INVALID_NATIVE_QUALITY');
        if(quality==='main' && actual==='small')throw new Error('MAIN_QUALITY_REQUIRED');
        slot.metrics.quality=actual || quality; attempt.nativeQuality=slot.metrics.quality;
        if(slot.requestedQuality==='small' && slot.metrics.quality==='main')recordQualityFallback(slot,response.headers.get('X-BTMH-Quality-Fallback') || slot.metrics.qualityFallbackReason || gateway.small_fallback_reason);
      }});
    check(slot, attempt); await abortable(pc.setRemoteDescription({type: 'answer', sdp: result.body}), attempt.controller.signal); check(slot, attempt);
    await waitFor(slot.video, ['loadeddata', 'playing'], () => slot.video.readyState >= 2 && slot.video.videoWidth > 0, attempt.controller.signal, 8000, 'NATIVE_GATEWAY_NO_VIDEO'); check(slot, attempt);
    slot.metrics.fallbackReason = null; slot.metrics.webRTCConnected = pc.connectionState === 'connected'; startVideoFrameMeter(slot, attempt); return true;
  }
  async function startWebRTC(slot, attempt, caps) {
    if (slot.cameraId != null && caps.camera_matches_active !== true) throw new Error('NON_PRIMARY_CAMERA');
    if (!window.RTCPeerConnection || !caps?.webrtc?.available) throw new Error('PYTHON_WEBRTC_UNAVAILABLE');
    const pc = configurePeer(slot, attempt); showLayer(slot, 'video'); pc.addTransceiver('video', {direction: 'recvonly'});
    const offer = await abortable(pc.createOffer(), attempt.controller.signal); check(slot, attempt); await abortable(pc.setLocalDescription(offer), attempt.controller.signal); check(slot, attempt); await waitIce(pc, attempt.controller.signal); check(slot, attempt);
    const answer = await fetchJson('/api/v1/media/webrtc/offer' + cameraQuery(slot), {method: 'POST', signal: attempt.controller.signal, timeoutMs: 10000, body: JSON.stringify({sdp: pc.localDescription?.sdp || offer.sdp, type: pc.localDescription?.type || offer.type})});
    if (!owns(slot, attempt)) { closePythonSession(answer.session_id); throw abortError(); } attempt.sessionId = answer.session_id || ''; check(slot, attempt);
    await abortable(pc.setRemoteDescription({type: answer.type || 'answer', sdp: answer.sdp}), attempt.controller.signal); check(slot, attempt);
    await waitFor(slot.video, ['loadeddata', 'playing'], () => slot.video.readyState >= 2 && slot.video.videoWidth > 0, attempt.controller.signal, 7500, 'PYTHON_WEBRTC_NO_VIDEO'); check(slot, attempt);
    slot.metrics.webRTCConnected = pc.connectionState === 'connected'; startVideoFrameMeter(slot, attempt); return true;
  }
  async function startWebSocket(slot, attempt, caps) {
    if (slot.cameraId != null && caps.camera_matches_active !== true) throw new Error('NON_PRIMARY_CAMERA'); if (!window.WebSocket) throw new Error('BROWSER_WEBSOCKET_UNAVAILABLE');
    slot.metrics.legacyTransport = 'WEBSOCKET_ACK_BITMAP'; const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/v1/media/preview/ws${cameraQuery(slot)}`); attempt.ws = ws; ws.binaryType = 'arraybuffer'; showLayer(slot, 'canvas');
    return await new Promise((resolve, reject) => {
      let settled = false, frameSeen = false;
      const finish = error => { if (settled) return; settled = true; clearTimeout(timer); attempt.controller.signal.removeEventListener('abort', cancel); error ? reject(error) : resolve(true); };
      const cancel = () => finish(attempt.failure || abortError()), timer = setTimeout(() => finish(new Error('WEBSOCKET_NO_VIDEO')), 5000); attempt.controller.signal.addEventListener('abort', cancel, {once: true});
      ws.onmessage = async e => {
        if (!owns(slot, attempt)) return; const blob = e.data instanceof Blob ? e.data : new Blob([e.data], {type: 'image/jpeg'}); let bitmap;
        try { bitmap = 'createImageBitmap' in window ? await createImageBitmap(blob) : await decodeImage(blob, attempt.controller.signal); check(slot, attempt); drawBitmap(slot, bitmap); receivedFrame(slot, attempt); frameSeen = true; setState(slot, 'live'); finish(); }
        catch (_) {} finally { bitmap?.close?.(); if (owns(slot, attempt) && ws.readyState === WebSocket.OPEN) ws.send('ack'); }
      };
      ws.onerror = () => { if (!frameSeen) finish(new Error('WEBSOCKET_ERROR')); };
      ws.onclose = e => { const reason = e.code === 4409 ? 'NON_PRIMARY_CAMERA' : 'WEBSOCKET_CLOSED'; if (!frameSeen) finish(new Error(reason)); else connectionFailure(slot, attempt, reason); };
    });
  }
  function decodeImage(blob, signal) {
    return new Promise((resolve, reject) => { const url = URL.createObjectURL(blob), image = new Image();
      const finish = error => { URL.revokeObjectURL(url); signal.removeEventListener('abort', cancel); image.onload = image.onerror = null; error ? reject(error) : resolve(image); };
      const cancel = () => { image.src = ''; finish(abortError()); }; signal.addEventListener('abort', cancel, {once: true}); image.onload = () => finish(); image.onerror = () => finish(new Error('JPEG_DECODE_FAILED')); image.src = url;
    });
  }
  function startImage(slot, attempt, polling) {
    if (!slot.image) throw new Error('IMAGE_TARGET_UNAVAILABLE'); if (!polling && !slot.allowMjpeg) throw new Error('GRID_PREFERS_BOUNDED_POLLING'); if (polling && !window.BTMHRuntime?.preview) throw new Error('POLLING_UNAVAILABLE'); showLayer(slot, 'image');
    return new Promise((resolve, reject) => {
      let settled = false; const finish = error => { if (settled) return; settled = true; clearTimeout(timer); attempt.controller.signal.removeEventListener('abort', cancel); error ? reject(error) : resolve(true); };
      const cancel = () => finish(abortError()), timer = setTimeout(() => finish(new Error(polling ? 'POLLING_NO_VIDEO' : 'MJPEG_NO_VIDEO')), 5000); attempt.controller.signal.addEventListener('abort', cancel, {once: true});
      slot.image.onload = () => { if (!owns(slot, attempt)) return; receivedFrame(slot, attempt); setState(slot, 'live'); finish(); };
      slot.image.onerror = () => { if (!settled) finish(new Error(polling ? 'POLLING_ERROR' : 'MJPEG_ERROR')); else connectionFailure(slot, attempt, `${attempt.name}_ERROR`); };
      if (polling) BTMHRuntime.preview(slot.image, slot.pollUrl, slot.pollInterval); else slot.image.src = `${slot.mjpegUrl}${slot.mjpegUrl.includes('?') ? '&' : '?'}t=${Date.now()}`;
    });
  }
  function startMonitor(slot, attempt) {
    const frameCallbacks = typeof slot.video.requestVideoFrameCallback === 'function', playbackQuality = typeof slot.video.getVideoPlaybackQuality === 'function';
    let previousInbound = null, statsBusy = false, retryAt = Date.now() + 12000, previousQuality = slot.video.getVideoPlaybackQuality?.();
    const timer = setInterval(async () => {
      if (!owns(slot, attempt) || statsBusy) return; const now = performance.now(), elapsed = Math.max(1, now - attempt.at);
      if (!attempt.pc) {
        // MJPEG img load is not a frame callback: its frame rate is unknown.
        slot.metrics.receivedFps = attempt.name === 'MJPEG' ? null : Math.round(attempt.received * 10000 / elapsed) / 10;
        slot.metrics.renderedFps = attempt.name === 'MJPEG' ? null : Math.round(attempt.rendered * 10000 / elapsed) / 10;
      } else {
        slot.metrics.renderedFps = frameCallbacks ? Math.round(attempt.rendered * 10000 / elapsed) / 10 : null; statsBusy = true;
        try {
          const reports = await attempt.pc.getStats(); if (!owns(slot, attempt)) return; let inbound;
          reports.forEach(report => { if (report.type === 'inbound-rtp' && (report.kind === 'video' || report.mediaType === 'video')) inbound = report; });
          if (inbound) {
            const codec = reports.get?.(inbound.codecId); slot.metrics.codec = codec ? `${codec.mimeType || ''}${codec.sdpFmtpLine ? '; ' + codec.sdpFmtpLine : ''}` : null;
            slot.metrics.jitterMs = Math.round(Number(inbound.jitter || 0) * 10000) / 10; slot.metrics.packetsLost = Number(inbound.packetsLost || 0);
            const current = {at: performance.now(), decoded: Number(inbound.framesDecoded || 0), received: Number.isFinite(inbound.framesReceived) ? inbound.framesReceived : null, bufferDelay: Number(inbound.jitterBufferDelay || 0), emitted: Number(inbound.jitterBufferEmittedCount || 0)};
            if (previousInbound) {
              const seconds = Math.max(.001, (current.at - previousInbound.at) / 1000); slot.metrics.decodedFps = Math.max(0, Math.round((current.decoded - previousInbound.decoded) / seconds * 10) / 10);
              slot.metrics.receivedFps = current.received == null || previousInbound.received == null ? null : Math.max(0, Math.round((current.received - previousInbound.received) / seconds * 10) / 10);
              const emitted = current.emitted - previousInbound.emitted; slot.metrics.playoutBufferMs = emitted > 0 ? Math.round((current.bufferDelay - previousInbound.bufferDelay) / emitted * 10000) / 10 : null;
              if (current.decoded > previousInbound.decoded) attempt.lastFrameAt = now;
            }
            previousInbound = current;
          }
          reports.forEach(report => { if (report.type === 'candidate-pair' && report.state === 'succeeded' && (report.nominated || report.selected)) slot.metrics.roundTripMs = Number.isFinite(report.currentRoundTripTime) ? Math.round(report.currentRoundTripTime * 1000) : null; });
          if (!frameCallbacks && playbackQuality) {
            const quality = slot.video.getVideoPlaybackQuality();
            if (previousQuality) {
              const rendered = (quality.totalVideoFrames - quality.droppedVideoFrames) - (previousQuality.totalVideoFrames - previousQuality.droppedVideoFrames);
              slot.metrics.renderedFps = Math.max(0, Math.round(rendered * 10000 / elapsed) / 10); if (rendered > 0) attempt.lastRenderedAt = now;
            }
            previousQuality = quality;
          }
          slot.metrics.webRTCConnected = attempt.pc.connectionState === 'connected';
        } catch (_) {} finally { statsBusy = false; }
      }
      if (!owns(slot, attempt)) return; attempt.at = performance.now(); attempt.received = attempt.rendered = 0;
      slot.metrics.lastFrameActivityAgoMs = Math.max(0, Math.round(performance.now() - attempt.lastFrameAt));
      slot.metrics.lastRenderedAgoMs = attempt.pc && !frameCallbacks && !playbackQuality ? null : Math.max(0, Math.round(performance.now() - attempt.lastRenderedAt));
      publish(slot);
      const stalledFor = slot.metrics.lastRenderedAgoMs ?? slot.metrics.lastFrameActivityAgoMs;
      if (attempt.name !== 'MJPEG' && stalledFor > 6500) { scheduleReconnect(slot, `${attempt.name}_VIDEO_STALLED`); return; }
      if (Date.now() >= retryAt) {
        retryAt = Date.now() + 12000;
        try {
          const caps = await capabilities(true, slot.cameraId, attempt.controller.signal);
          if (!owns(slot, attempt)) return;
          updateGateway(slot, caps.native_gateway); publish(slot);
          if (slot.cameraId != null && caps.camera_matches_active !== true && ['NATIVE_GATEWAY_WEBRTC', 'PYTHON_WEBRTC', 'WEBSOCKET'].includes(attempt.name)) { scheduleReconnect(slot, 'NON_PRIMARY_CAMERA'); return; }
          if (attempt.name === 'NATIVE_GATEWAY_WEBRTC' && slot.requestedQuality === 'small') {
            if (caps.native_gateway?.small_available !== true) slot.smallRetryBlocked = false;
            if (slot.metrics.quality === 'small' && caps.native_gateway?.small_available !== true) { scheduleReconnect(slot, 'SMALL_STREAM_UNAVAILABLE'); return; }
            if (slot.metrics.quality === 'main' && caps.native_gateway?.small_available === true && !slot.smallRetryBlocked) { scheduleReconnect(slot, 'SMALL_STREAM_READY'); return; }
            if (slot.metrics.quality === 'main') recordQualityFallback(slot, slot.smallRetryBlocked ? 'SMALL_NEGOTIATION_FAILED' : caps.native_gateway?.small_fallback_reason);
          }
          if (attempt.name !== 'NATIVE_GATEWAY_WEBRTC' && caps.native_gateway?.available && (slot.cameraId == null || caps.camera_matches_active === true)) scheduleReconnect(slot, 'NATIVE_GATEWAY_READY');
        } catch (_) {}
      }
    }, 1000); attempt.cleanup.push(() => clearInterval(timer));
  }
  function startMetadata(slot) {
    if (!slot.overlay || !window.WebSocket || !alive(slot)) return; const generation = slot.generation;
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/v1/media/metadata/ws`); slot.metaWs = ws;
    ws.onmessage = e => { if (!alive(slot) || slot.generation !== generation || slot.metaWs !== ws) return; try { slot.meta = JSON.parse(e.data || '{}'); drawOverlay(slot); } catch (_) {} if (ws.readyState === WebSocket.OPEN) ws.send('ack'); };
    ws.onclose = () => { if (!alive(slot) || slot.generation !== generation || slot.metaWs !== ws) return; slot.metaWs = null; slot.metaRetry = setTimeout(() => { slot.metaRetry = null; if (alive(slot) && slot.generation === generation) startMetadata(slot); }, 900); };
  }
  function drawOverlay(slot) {
    const canvas = slot.overlay, wrap = slot.wrap, meta = slot.meta; if (!canvas || !wrap || !meta) return;
    const cw = Math.max(1, wrap.clientWidth), ch = Math.max(1, wrap.clientHeight), dpr = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
    if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) { canvas.width = Math.round(cw * dpr); canvas.height = Math.round(ch * dpr); }
    const ctx = canvas.getContext('2d'); if (!ctx) return; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, cw, ch);
    const sw = Number(meta.frame_width || slot.mediaWidth || slot.video?.videoWidth || 0), sh = Number(meta.frame_height || slot.mediaHeight || slot.video?.videoHeight || 0); if (!sw || !sh) return;
    const rect = fitRect(cw, ch, sw, sh), sx = rect.w / sw, sy = rect.h / sh;
    for (const tr of (meta.tracks || [])) {
      const raw = Array.isArray(tr.face_bbox) && tr.face_bbox.some(Number) ? tr.face_bbox : tr.bbox; if (!Array.isArray(raw) || raw.length < 4) continue;
      const [x1, y1, x2, y2] = raw.map(Number); if (x2 <= x1 || y2 <= y1) continue;
      let dx = rect.x + x1 * sx; const dy = rect.y + y1 * sy, dw = (x2 - x1) * sx, dh = (y2 - y1) * sy; if (slot.mirror) dx = cw - (dx + dw);
      const blocked = !!tr.spoof_blocked, recognized = !!tr.recognized || !!tr.identity_verified; ctx.strokeStyle = blocked ? '#ff5d5d' : recognized ? '#2ed4a0' : '#18a9ff'; ctx.lineWidth = 2; ctx.strokeRect(dx, dy, dw, dh);
      const label = blocked ? 'PAD BLOCK' : recognized ? (tr.full_name || tr.student_code || 'FaceID') : 'ANALYZING'; ctx.font = '600 11px system-ui, sans-serif'; const tw = Math.ceil(ctx.measureText(label).width) + 12, ty = Math.max(16, dy - 5);
      ctx.fillStyle = 'rgba(4,18,29,.78)'; ctx.fillRect(dx, ty - 15, tw, 18); ctx.fillStyle = '#fff'; ctx.fillText(label, dx + 6, ty - 2);
    }
  }
  async function start(slot, retry = false) {
    if (!alive(slot)) return; slot.generation += 1; slot.controller = new AbortController(); slot.negotiating = true; slot.chainFailures=[]; const generation = slot.generation; let caps;
    try { caps = await capabilities(retry, slot.cameraId, slot.controller.signal); }
    catch (error) {
      if (!alive(slot) || generation !== slot.generation || slot.controller.signal.aborted) return; recordFallback(slot, 'CAPABILITIES', error);
      caps = {native_gateway: {available: false, reason_code: 'CAPABILITIES_UNAVAILABLE'}, webrtc: {available: false}, camera_matches_active: slot.cameraId == null};
    }
    if (!alive(slot) || generation !== slot.generation || slot.controller.signal.aborted) return;
    updateGateway(slot, caps.native_gateway);
    if (caps.native_gateway?.small_available !== true) slot.smallRetryBlocked = false;
    const small = slot.requestedQuality === 'small' && caps.native_gateway?.small_available === true && !slot.smallRetryBlocked;
    slot.metrics.quality = small ? 'small' : 'main';
    if (slot.requestedQuality === 'small' && !small) recordQualityFallback(slot, slot.smallRetryBlocked ? 'SMALL_NEGOTIATION_FAILED' : caps.native_gateway?.small_fallback_reason);
    else slot.metrics.qualityFallbackReason = null;
    const order = ['native', 'webrtc', 'ws', 'mjpeg', 'poll'];
    if (small) order.unshift('native-small');
    const labels = {'native-small': 'NATIVE_GATEWAY_WEBRTC', native: 'NATIVE_GATEWAY_WEBRTC', webrtc: 'PYTHON_WEBRTC', ws: 'WEBSOCKET', mjpeg: 'MJPEG', poll: 'POLLING'};
    let mainAlreadyTried = false;
    for (const transport of order) {
      if (transport === 'native' && mainAlreadyTried) continue;
      // A blocked gateway is reported explicitly without claiming its transport
      // even temporarily. The next existing fallback owns the video attempt.
      if ((transport === 'native' || transport === 'native-small') && !caps.native_gateway?.available) {
        recordFallback(slot, 'NATIVE_GATEWAY_WEBRTC', gatewayReason(caps.native_gateway)); continue;
      }
      if (!alive(slot) || generation !== slot.generation || slot.controller.signal.aborted) return; const attempt = newAttempt(slot, labels[transport], transport === 'native-small' ? 38000 : 25000);
      try {
        if (transport === 'native-small' || transport === 'native') await startNativeGateway(slot, attempt, caps, transport === 'native-small' ? 'small' : 'main'); else if (transport === 'webrtc') await startWebRTC(slot, attempt, caps); else if (transport === 'ws') await startWebSocket(slot, attempt, caps); else await startImage(slot, attempt, transport === 'poll');
        check(slot, attempt); clearTimeout(attempt.negotiationTimer); slot.negotiating = false; attempt.lastFrameAt = attempt.lastRenderedAt = performance.now(); setState(slot, 'live'); startMonitor(slot, attempt); startMetadata(slot); return;
      } catch (error) {
        if (!owns(slot, attempt)) return;
        if (transport === 'native-small') {
          mainAlreadyTried = error.code === 'SMALL_AND_MAIN_UNAVAILABLE' || attempt.nativeQuality === 'main';
          recordQualityFallback(slot, mainAlreadyTried && slot.metrics.qualityFallbackReason || qualityReason(error.code || (attempt.failure || error).message, 'SMALL_NEGOTIATION_FAILED'));
          if (mainAlreadyTried) recordFallback(slot, attempt.name, attempt.failure || error);
        }
        else recordFallback(slot, attempt.name, attempt.failure || error);
        disposeAttempt(slot, attempt);
      }
    }
    slot.negotiating = false; scheduleReconnect(slot, 'ALL_TRANSPORTS_FAILED');
  }
  function mount(key, options = {}) {
    stop(key);
    if (document.hidden || !presentationAllowed) return null;
    const slot = {key, cameraId: options.cameraId ?? null, requestedQuality: options.quality === 'small' ? 'small' : 'main', smallRetryBlocked: false, active: true, generation: 0, recoverySeq: 0, recovering: false, wrap: q(options.wrap), video: q(options.video), image: q(options.image), empty: q(options.empty), overlay: q(options.overlay),
      fit: options.fit || 'contain', mirror: !!options.mirror, allowMjpeg: options.allowMjpeg !== false, mjpegUrl: options.mjpegUrl || '/api/v1/camera/stream.mjpg', pollUrl: options.pollUrl || '/api/v1/camera/frame.jpg', pollInterval: options.pollInterval || 140,
      transport: '', state: 'connecting', attempt: null, controller: null, metaWs: null, reconnectTimer: null, metaRetry: null, negotiating: false, chainFailures:[], mediaWidth: 0, mediaHeight: 0,
      metrics: {requestedQuality: options.quality === 'small' ? 'small' : 'main', quality: 'main', qualityFallbackReason: null, receivedFps: null, renderedFps: null, decodedFps: null, videoLatencyMs: null, frameAgeMs: null, reconnectCount: 0, fallbackReason: null, fallbackHistory: [], nativeGatewayAvailable: null, nativeGatewayState: 'CHECKING', nativeGatewayReason: null, nativeGatewayRunning: null, rtspSourceHealthy: null}};
    ensureLayers(slot); slots.set(key, slot); setState(slot, 'connecting'); start(slot); return slot;
  }
  function stop(key) {
    const slot = slots.get(key); if (!slot) return; closeTransport(slot); slots.delete(key); slot.active = false; slot.generation += 1; showLayer(slot, 'none');
    if (slot.video.dataset.btmhMediaCreated === '1') slot.video.remove(); slot.canvas?.remove(); slot.status?.remove(); if (slot.empty) { slot.empty.classList.remove('hidden'); slot.empty.style.display = ''; }
  }
  function stopAll() { [...slots.keys()].forEach(stop); }
  function restart(reason = 'CAMERA_SOURCE_CHANGED') { invalidate(); [...slots.values()].forEach(slot => { slot.smallRetryBlocked = false; scheduleReconnect(slot, reason); }); }
  function stats() { const result = {}; slots.forEach((slot, key) => { result[key] = snapshot(slot); }); return result; }
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopAll(); });
  document.addEventListener('btmh:auth', e => { presentationAllowed=!!e.detail?.authenticated; if (!presentationAllowed) { stopAll(); invalidate(); } });
  document.addEventListener('btmh:camera-source-changed', () => restart()); document.addEventListener('btmh:camera-registry-changed', invalidate);
  window.addEventListener('pagehide', stopAll); window.BTMHMedia = {mount, stop, stopAll, stats, capabilities, invalidate, restart};
})();
