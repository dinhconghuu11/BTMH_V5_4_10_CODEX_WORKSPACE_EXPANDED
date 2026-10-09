/* Paste into the authenticated BTMH browser console, then call
   await BTMHCameraAIBenchmark({cameraIds:[2], seconds:30}).
   Finite GET-only measurements; never reads credentials or emits identities. */
(function () {
  'use strict';
  const number = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
  const numbers = (raw, keys) => Object.fromEntries(keys.map(key => [key, number(raw?.[key])]));
  window.BTMHCameraAIBenchmark = async function ({cameraIds = [2], seconds = 30} = {}) {
    const ids = [...new Set(cameraIds)];
    if (!ids.length || ids.length > 4 || ids.some(id => !Number.isSafeInteger(id) || id < 1) ||
        !Number.isInteger(seconds) || seconds < 1 || seconds > 60) throw new Error('Use 1–4 configured camera IDs and 1–60 seconds.');
    const samples = [], start = performance.now();
    while (performance.now() - start < seconds * 1000) {
      for (const cameraId of ids) {
        const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 6000);
        const began = performance.now();
        try {
          const response = await fetch(`/api/v1/media/metadata?camera_id=${cameraId}`,
            {method:'GET', credentials:'same-origin', cache:'no-store', signal:controller.signal});
          if (!response.ok) { samples.push({camera_id:cameraId, http_status:response.status}); continue; }
          const meta = await response.json(), perf = meta.ai_performance || {}, detect = meta.ai_detection || {};
          const tracks = Array.isArray(meta.tracks) ? meta.tracks : [];
          const browser = Object.values(window.BTMHMedia?.stats?.() || {}).find(item => Number(item.cameraId) === cameraId);
          samples.push({camera_id:cameraId, elapsed_ms:Math.round(performance.now()-start),
            http_round_trip_ms:Math.round(performance.now()-began),
            ai_state:['ACTIVE','ERROR','PAUSED','DISABLED','OFFLINE','STARTING','STOPPING','WAITING_FOR_CAPACITY'].includes(meta.ai_state)?meta.ai_state:null,
            ...numbers(meta,['tracking_age_ms','source_age_ms','frame_width','frame_height','ai_successful_results_current_source']),
            ai_detection:{input_mode:['HIKVISION_SUBSTREAM','MAIN_FALLBACK'].includes(detect.input_mode)?detect.input_mode:null,
              ...numbers(detect,['input_seq','input_width','input_height','substream_capture_fps','substream_age_ms','detected_faces','observed_faces','observation_errors','no_face_streak'])},
            ai_performance:{...numbers(perf,['actual_ai_fps','capture_fps','avg_ai_ms','p95_ai_ms','effective_target_fps']),
              stage_times:numbers(perf.stage_times,['work_lock_wait_ms','acquisition_ms','preprocessing_ms','detection_ms','observation_ms','tracking_ms','verification_dispatch_ms','sample_total_ms','capture_to_result_ms']),
              pad:numbers(perf.pad,['fps','completed','dropped','errors','last_ms','last_latency_ms','last_queue_wait_ms','pending']),
              faceid:numbers(perf.faceid,['fps','completed','dropped','errors','last_ms','last_latency_ms','last_queue_wait_ms','pending'])},
            tracks:tracks.map(track => ({recognized:track.recognized === true, blocked:track.spoof_blocked === true,
              status:['OBSERVING_QUALITY','VERIFYING_PASSIVE','ANALYZING','RECOGNIZED','UNREGISTERED','SPOOF_BLOCKED'].includes(track.status)?track.status:null,
              pad_status:['PASS','PENDING','CHECKING','BLOCKED','FAIL'].includes(track.pad_status)?track.pad_status:null,
              ...numbers(track,['pad_live_score','pad_spoof_score']),
              verification_reason_code:['PAD_BLOCKED','PAD_CHECKING','PAD_INFERENCE_FAILED','FACE_TOO_SMALL','FACE_POSE','FACE_PITCH','FACE_BLUR','FACE_LIGHTING','FACE_QUALITY_WAIT',''].includes(track.verification_reason_code)?track.verification_reason_code:null,
              face_quality:numbers(track.face_quality,['face_px','score','sharpness','brightness','contrast'])})),
            browser:numbers(browser,['renderedFps','decodedFps','receivedFps','videoLatencyMs','roundTripMs','playoutBufferMs'])});
        } catch (_) { samples.push({camera_id:cameraId, error_code:'MEASUREMENT_REQUEST_FAILED'}); }
        finally { clearTimeout(timeout); }
      }
      if (performance.now() - start < seconds * 1000) await new Promise(resolve => setTimeout(resolve, 1000));
    }
    return {read_only:true, samples, note:'HTTP round trip includes API work; video latency may be unknown. No worker/configuration changes. No identities or images.'};
  };
})();
