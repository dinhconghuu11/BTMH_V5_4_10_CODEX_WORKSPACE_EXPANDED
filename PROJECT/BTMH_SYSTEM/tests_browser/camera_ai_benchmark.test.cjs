'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../scripts/benchmark_camera_ai.js'), 'utf8');

test('host benchmark uses bounded authenticated GETs and excludes identities and private values', async () => {
  let now = 0, next = 0;
  const requests = [], timers = new Set(), window = {};
  const secret = 'PrivateCameraSecret';
  vm.runInNewContext(source, {window, AbortController, performance:{now:()=>now},
    setTimeout:(fn,ms)=>{const id=++next; timers.add(id); if(ms===1000){now+=1000;timers.delete(id);queueMicrotask(fn);}return id;},
    clearTimeout:id=>timers.delete(id), fetch:async(url,init)=>{requests.push({url,init}); return {ok:true,json:async()=>({
      ai_state:'ACTIVE', source:secret, ai_detection:{input_mode:secret, observed_faces:0},
      ai_performance:{actual_ai_fps:3,pad:{last_ms:secret}},
      tracks:[{recognized:false,full_name:secret,student_code:secret,status:secret,pad_status:secret,pad_live_score:secret,
        pad_spoof_score:Infinity,verification_reason_code:secret,face_quality:{score:.5,embedding:secret}},
        {status:'SPOOF_BLOCKED',pad_status:'BLOCKED',pad_live_score:.02,pad_spoof_score:.98}]
    })};}});
  const result = await window.BTMHCameraAIBenchmark({cameraIds:[2],seconds:1});
  assert.equal(requests.length,1); assert.equal(requests[0].init.method,'GET');
  assert.equal(requests[0].init.credentials,'same-origin'); assert.equal(requests[0].url,'/api/v1/media/metadata?camera_id=2');
  assert.equal(JSON.stringify(result).includes(secret),false); assert.equal(timers.size,0);
  assert.equal(result.samples[0].ai_performance.actual_ai_fps,3);
  assert.equal(result.samples[0].tracks[0].face_quality.score,.5);
  assert.equal(result.samples[0].tracks[0].status,null); assert.equal(result.samples[0].tracks[0].pad_status,null);
  assert.equal(result.samples[0].tracks[0].pad_live_score,null); assert.equal(result.samples[0].tracks[0].pad_spoof_score,null);
  assert.equal(result.samples[0].tracks[1].status,'SPOOF_BLOCKED'); assert.equal(result.samples[0].tracks[1].pad_status,'BLOCKED');
  assert.equal(result.samples[0].tracks[1].pad_live_score,.02); assert.equal(result.samples[0].tracks[1].pad_spoof_score,.98);
});

test('benchmark refuses invalid camera IDs and unbounded durations without requests', async () => {
  const window={}; vm.runInNewContext(source,{window});
  for (const config of [{cameraIds:[0]}, {cameraIds:[1,2,3,4,5]}, {seconds:1000}, {cameraIds:['rtsp://private']}]) {
    await assert.rejects(window.BTMHCameraAIBenchmark(config));
  }
});
