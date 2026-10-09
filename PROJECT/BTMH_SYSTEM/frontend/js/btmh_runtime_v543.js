/* Bounded presentation work. Camera/AI/recording continue independently. */
(() => {
  'use strict';
  const jobs = new Map(), previews = new Map();
  let timer = null, networkInFlight = 0, presented = true;
  const abortError = () => new DOMException('Aborted', 'AbortError');
  function cancelBody(response) {
    try { response?.body?.cancel()?.catch(() => {}); } catch (_) {}
  }
  function abortable(signal, work, discard) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (callback, value) => {
        if (settled) return false;
        settled = true; signal.removeEventListener('abort', abort); callback(value); return true;
      };
      const abort = () => finish(reject, abortError());
      if (signal.aborted) { abort(); return; }
      signal.addEventListener('abort', abort, {once:true});
      // A transport or body reader may ignore abort; it cannot retain our owner.
      Promise.resolve().then(() => {
        if (signal.aborted) throw abortError();
        return work();
      }).then(value => {
        if (!finish(resolve, value) && discard) discard(value);
      }, error => finish(reject, error));
    });
  }
  async function request(url, options = {}) {
    const {timeoutMs = 15000, ...init} = options;
    const controller = new AbortController(), abort = () => controller.abort();
    if (init.signal?.aborted) throw abortError();
    init.signal?.addEventListener('abort', abort, {once:true});
    const timeout = setTimeout(abort, Number.isFinite(timeoutMs) && timeoutMs >= 0 ? timeoutMs : 15000);
    let response;
    try {
      // API calls are finite: keep the timeout until the body is received too.
      response=await abortable(controller.signal,()=>fetch(url,{...init,signal:controller.signal}),cancelBody);
      if(controller.signal.aborted)throw abortError();
      if(!response.body)return response;
      const body=await abortable(controller.signal,()=>response.arrayBuffer());
      if(controller.signal.aborted)throw abortError();
      return new Response(body,{status:response.status,statusText:response.statusText,headers:response.headers});
    }
    finally { if(controller.signal.aborted)cancelBody(response); clearTimeout(timeout); init.signal?.removeEventListener('abort',abort); }
  }
  function once(key, work, {signal} = {}) {
    if(jobs.has(key)) return jobs.get(key).promise;
    if(signal?.aborted)return Promise.reject(abortError());
    const job={controller:new AbortController(),promise:null};
    const abort=()=>{if(jobs.get(key)===job)jobs.delete(key);job.controller.abort();};
    signal?.addEventListener('abort',abort,{once:true});
    jobs.set(key,job);
    job.promise=abortable(job.controller.signal,()=>work(job.controller.signal)).finally(()=>{
      signal?.removeEventListener('abort',abort);
      if(jobs.get(key)===job)jobs.delete(key);
    });
    return job.promise;
  }
  function cancel(key) {
    const job=jobs.get(key);if(!job)return false;
    jobs.delete(key);job.controller.abort();return true;
  }
  function mark(job, state) {
    if(job.img.dataset.previewState===state)return;
    job.img.dataset.previewState=state;
    const wrap=job.img.parentElement;if(!wrap)return;
    let badge=wrap.querySelector('.btmh-preview-status');
    if(!badge){badge=document.createElement('span');badge.className='btmh-preview-status';badge.setAttribute('role','status');wrap.append(badge);}
    badge.hidden=state==='live';
    badge.textContent=state==='stale'?'Khung h\u00ecnh c\u0169 \u00b7 \u0111ang k\u1ebft n\u1ed1i l\u1ea1i':'\u0110ang k\u1ebft n\u1ed1i camera...';
  }
  function visible(img){return presented&&!document.hidden&&img.isConnected&&!img.closest('.hidden')&&!document.querySelector('#authGate:not(.hidden)')&&(!img.closest('.page')||img.closest('.page').classList.contains('active'));}
  async function pull(job){
    if(job.busy||previews.get(job.img)!==job)return;
    job.busy=true;networkInFlight++;
    const controller=new AbortController();job.controller=controller;
    const timeout=setTimeout(()=>controller.abort(),4000);
    let res;
    try{
      res=await abortable(controller.signal,()=>fetch(`${job.url}${job.url.includes('?')?'&':'?'}t=${Date.now()}`,{credentials:'same-origin',cache:'no-store',signal:controller.signal}),cancelBody);
      if(!res.ok)throw new Error(`preview-${res.status}`);
      const blob=await abortable(controller.signal,()=>res.blob());
      if(previews.get(job.img)!==job||controller.signal.aborted)return;
      if(!visible(job.img)){stopPreview(job.img);return;}
      if(!blob.type.includes('image/'))throw new Error('preview-format');
      const next=URL.createObjectURL(blob),old=job.objectUrl;job.objectUrl=next;job.img.src=next;if(old)URL.revokeObjectURL(old);
      const seq=res.headers.get('X-Camera-Seq'),age=Number(res.headers.get('X-Frame-Age-Ms')||0);
      if(!seq||seq!==job.seq){job.changedAt=performance.now();job.seq=seq;}
      mark(job,age>3500||performance.now()-job.changedAt>5000?'stale':'live');job.failures=0;
    }catch(error){if(previews.get(job.img)===job){job.failures++;mark(job,controller.signal.aborted?'stale':'reconnecting');}}
    finally{if(controller.signal.aborted||!res?.ok)cancelBody(res);clearTimeout(timeout);job.busy=false;job.controller=null;networkInFlight--;job.due=performance.now()+(job.failures?Math.min(5000,750*2**Math.min(job.failures,3)):job.interval);}
  }
  function pump(){
    const now=performance.now();
    for(const job of [...previews.values()].sort((a,b)=>a.due-b.due)){
      if(!visible(job.img)){stopPreview(job.img);continue;}
      if(!job.busy&&now>=job.due&&networkInFlight<3)void pull(job);
    }
  }
  function preview(img,url,interval=100){
    if(!img)return;if(!visible(img)){stopPreview(img);return;}const old=previews.get(img);if(old?.url===url)return;
    stopPreview(img);
    const job={img,url,interval,due:0,busy:false,failures:0,controller:null,objectUrl:null,seq:null,changedAt:performance.now()};
    previews.set(img,job);img.dataset.started='1';mark(job,'connecting');
    if(!timer)timer=setInterval(pump,45);pump();
  }
  function stopPreview(img){
    if(!img)return;const job=previews.get(img);previews.delete(img);job?.controller?.abort();
    if(job?.objectUrl)URL.revokeObjectURL(job.objectUrl);
    img.removeAttribute('src');delete img.dataset.started;delete img.dataset.previewState;
    const badge=img.parentElement?.querySelector('.btmh-preview-status');if(badge)badge.hidden=true;
    if(!previews.size&&timer){clearInterval(timer);timer=null;}
  }
  function stopAll(){for(const img of [...previews.keys()])stopPreview(img);}
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopAll();});
  window.addEventListener('pagehide',()=>{presented=false;stopAll();});
  window.addEventListener('pageshow',()=>{presented=true;});
  window.BTMHRuntime={request,once,cancel,preview,stopPreview,stopAll,stats:()=>({previews:previews.size,inFlight:networkInFlight,jobs:jobs.size})};
})();
