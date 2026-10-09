/* Isolated visual QA: real frontend assets, empty recognition feed, no camera/model/API access.
   Run: node tests_browser/visual_recognition_console.cjs
   Uses an existing Chrome with a new workspace-only profile; never attaches to a user's browser. */
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const frontend = path.resolve(__dirname, '../frontend');
const photoQa = process.argv.includes('--photos');
const output = path.join(frontend, photoQa ? '.qa_evidence_photos' : '.qa_recognition_console');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function previewHtml() {
  let html = fs.readFileSync(path.join(frontend, 'index.html'), 'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
  html = html.replace('class="app-shell" inert', 'class="app-shell"');
  html = html.replace('id="authGate"', 'id="authGate" hidden');
  const app = fs.readFileSync(path.join(frontend, 'js/app.js'), 'utf8');
  const start = app.indexOf('function renderRecognitionSlotSelection(');
  const render = app.slice(start, app.indexOf('\ndocument.addEventListener', start));
  assert.ok(start > 0 && render.trimEnd().endsWith('}'));
  const setup = `<script>
    document.querySelector('#authGate').classList.add('hidden');
    document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id==='page-recognition'));
    document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page==='recognition'));
    document.querySelector('#pageTitle').textContent='Nhận diện & chấm công';
    document.querySelector('#pageSubtitle').textContent='Bản xem bố cục — không kết nối camera hoặc AI';
    const state={authUser:{preview:true},photoPermission:${photoQa}}, $=selector=>document.querySelector(selector);
    const appPresentationActive=()=>!!state.authUser, hasUiPermission=permission=>!!state.authUser&&(permission==='camera.live'||permission==='evidence.view'&&state.photoPermission);
    const initials=name=>name.slice(0,1), pct=value=>Math.round(value*100), formatTime=value=>new Date(value).toLocaleTimeString('vi-VN');
    const setEntryBadge=(text,tone)=>{const el=$('#entryStateBadge');el.textContent=text;el.className='entry-state-badge '+tone;};
    const setRecognitionProgress=(fraction,text)=>{$('#v21RecognitionState').textContent=text;$('#v21RecognitionPercent').textContent=Math.round(fraction*100)+'%';$('#v21RecognitionFill').style.width=(fraction*100)+'%';};
    // Camera names are layout fixtures only. No events, persons, images, verification or LIVE signals are generated.
    window.qaPhotoRequests=0;
    const api=async (url,options={})=>{
      if(${photoQa}&&options.rawResponse&&url==='/api/v1/events/1/evidence.jpg'){
        window.qaPhotoRequests++;const canvas=document.createElement('canvas');canvas.width=2;canvas.height=2;
        canvas.getContext('2d').fillRect(0,0,2,2);const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
        return new Response(blob,{headers:{'Content-Type':'image/png'}});
      }
      if(url==='/api/v1/recognition/cameras')return {items:Array.from({length:4},(_,i)=>({id:i+1,camera_name:'Camera '+(i+1)+' · Xem bố cục',enabled:true,ai_enabled:false,ai_state:'DISABLED',store_name:'Bản xem bố cục',zone_name:'Không kết nối camera'}))};
      if(url.startsWith('/api/v1/recognition/recent?'))return {items:${photoQa ? "[{id:1,event_id:1,appearance_id:'qa-image-only',camera_id:1,recognized:false,faceid_status:'CHECKING',pad_status:'PENDING',status:'ANALYZING',snapshot_url:'/api/v1/events/1/evidence.jpg'}]" : '[]'}};
      throw new Error('API disabled in static visual QA');
    };
    ${render}
    document.addEventListener('btmh:recognition-selection',event=>renderRecognitionSlotSelection(event.detail));
    document.querySelector('#btmhMenuToggle').addEventListener('click',()=>document.body.classList.toggle('btmh-menu-open'));
    document.querySelector('#btmhMenuBackdrop').addEventListener('click',()=>document.body.classList.remove('btmh-menu-open'));
    document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',event=>event.preventDefault()));
  </script><script src="/static/js/btmh_recognition_slots.js"></script><script src="/static/js/btmh_recent_recognition.js"></script>`;
  return html.replace('</body>', setup + '</body>');
}

async function main() {
  fs.mkdirSync(output, {recursive:true});
  const html = previewHtml(), served = [], pageErrors = [], results = [];
  const server = http.createServer((request, response) => {
    const pathname = new URL(request.url, 'http://127.0.0.1').pathname; served.push(pathname);
    if (pathname === '/') { response.writeHead(200, {'Content-Type':'text/html; charset=utf-8'}); response.end(html); return; }
    if (!pathname.startsWith('/static/')) { response.writeHead(404); response.end(); return; }
    const filename = path.resolve(frontend, '.' + decodeURIComponent(pathname.slice('/static'.length)));
    if (!filename.startsWith(frontend + path.sep) || !fs.existsSync(filename) || !fs.statSync(filename).isFile()) { response.writeHead(404); response.end(); return; }
    const types={'.css':'text/css','.js':'application/javascript','.png':'image/png','.svg':'image/svg+xml'};
    response.writeHead(200, {'Content-Type':types[path.extname(filename)] || 'application/octet-stream'}); fs.createReadStream(filename).pipe(response);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  const profile = path.join(output, 'chrome-profile-' + Date.now());
  const chromePath = process.env.BTMH_QA_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
  let child, socket, call, childError;
  try {
    assert.ok(fs.existsSync(chromePath), 'Existing Chrome is required; no browser will be downloaded');
    child = spawn(chromePath, ['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking',
      '--disable-extensions','--disable-sync','--disable-component-update','--disable-features=OptimizationHints,MediaRouter',
      '--no-proxy-server','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'], {windowsHide:true, stdio:'ignore'});
    child.on('error', error=>{childError=error;});
    const portFile=path.join(profile,'DevToolsActivePort'), deadline=Date.now()+15000;
    while (!fs.existsSync(portFile) && Date.now()<deadline && !childError) await delay(100);
    if (childError) throw childError;
    assert.ok(fs.existsSync(portFile), 'Isolated Chrome did not expose its local inspection port');
    const debugBase='http://127.0.0.1:'+fs.readFileSync(portFile,'utf8').split(/\r?\n/)[0];
    const tab=await (await fetch(debugBase+'/json/new?about:blank',{method:'PUT'})).json();
    socket=new WebSocket(tab.webSocketDebuggerUrl); const pending=new Map(); let sequence=0;
    socket.addEventListener('message', event=>{
      const msg=JSON.parse(event.data); if(msg.method==='Runtime.exceptionThrown')pageErrors.push(msg.params.exceptionDetails.text);
      if(pending.has(msg.id)){const task=pending.get(msg.id);pending.delete(msg.id);clearTimeout(task.timer);msg.error?task.reject(new Error(msg.error.message)):task.resolve(msg.result);}
    });
    await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
    call=(method,params={})=>new Promise((resolve,reject)=>{
      const id=++sequence, timer=setTimeout(()=>{pending.delete(id);reject(new Error('Inspection timeout: '+method));},8000);
      pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));
    });
    const evaluate=async expression=>{const response=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(response.exceptionDetails)throw new Error(response.exceptionDetails.text);return response.result.value;};
    await call('Page.enable'); await call('Runtime.enable'); await call('Page.bringToFront');
    const views=photoQa?[{name:'photo-regression',width:1440,height:1000}]:[{name:'desktop',width:1440,height:1000},{name:'wide',width:1920,height:1080},{name:'tablet',width:768,height:1024},{name:'mobile',width:390,height:844}];
    for (const view of views) {
      await call('Emulation.setDeviceMetricsOverride',{width:view.width,height:view.height,deviceScaleFactor:1,mobile:false});
      await call('Page.navigate',{url:base+'/'});
      await evaluate(`new Promise(resolve=>{if(document.readyState==='complete')resolve();else addEventListener('load',resolve,{once:true});})`);
      await evaluate(`new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
      if(photoQa){
        const loaded=selector=>evaluate(`new Promise(resolve=>{const end=Date.now()+1200;const check=()=>{const img=document.querySelector(${JSON.stringify(selector)});if(img&&!img.hidden&&img.naturalWidth>0)resolve(true);else if(Date.now()>end)resolve(false);else setTimeout(check,25);};check();})`);
        const cardLoaded=await loaded('#recentRecognitionItems img');
        assert.equal(cardLoaded,true,'Saved card image must decode while initially hidden; lazy-hidden image deadlock');
        await evaluate(`document.querySelector('.recent-recognition-card').click()`);
        assert.equal(await loaded('#recentRecognitionDetailContent img'),true,'Detail evidence image must decode');
        await evaluate(`window.qaDetailImage=document.querySelector('#recentRecognitionDetailContent img');window.qaDetailUrl=window.qaDetailImage.src;`);
        await evaluate(`(async()=>{for(let i=0;i<3;i++)await window.BTMHRecentRecognition.refresh()})()`);
        const stable=await evaluate(`({sameImage:window.qaDetailImage===document.querySelector('#recentRecognitionDetailContent img'),sameUrl:window.qaDetailUrl===document.querySelector('#recentRecognitionDetailContent img').src,decoded:!window.qaDetailImage.hidden&&window.qaDetailImage.naturalWidth===2,photoRequests:window.qaPhotoRequests})`);
        assert.deepEqual(stable,{sameImage:true,sameUrl:true,decoded:true,photoRequests:2},'Automatic polls preserve decoded detail image');
        await evaluate(`state.photoPermission=false;document.dispatchEvent(new CustomEvent('btmh:recognition-selection',{detail:window.BTMHRecognitionSlots.getSelection()}))`);
        assert.equal(await evaluate(`[...document.querySelectorAll('#page-recognition img')].some(img=>img.getAttribute('src'))`),false,'Permission revocation removes protected images');
        await evaluate(`state.authUser=null;document.dispatchEvent(new CustomEvent('btmh:auth',{detail:{authenticated:false}}))`);
        assert.equal(await evaluate(`document.querySelector('#recentRecognitionDetail').hidden`),true,'Logout closes evidence dialog');
        results.push({name:view.name,status:'PASS',hidden_png_decoded:true,detail_stable_across_three_polls:true,permission_logout_cleanup:true,technical_image_pixels:4,real_face_images:0,api_requests:0});
        continue;
      }
      const metrics=await evaluate(`(()=>{
        const page=document.querySelector('#page-recognition'),box=el=>{const r=el.getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
        return {page:box(page),pageWidth:document.documentElement.scrollWidth,camera:box(page.querySelector('.recognition-camera-panel')),detail:box(page.querySelector('.entry-current-card')),
          video:box(page.querySelector('.recognition-slot-viewport')),videoAspect:getComputedStyle(page.querySelector('.recognition-slot-viewport')).aspectRatio,history:box(page.querySelector('.recent-recognition-panel')),snapshot:box(page.querySelector('.entry-snapshot-wrap')),
          background:getComputedStyle(page).backgroundColor,mainColumns:getComputedStyle(page.querySelector('.entry-recognition-top')).gridTemplateColumns,
          cameras:page.querySelectorAll('.recognition-camera-choice').length,owners:page.querySelectorAll('.recognition-slot').length,
          hiddenLeaks:[...page.querySelectorAll('[hidden],.hidden')].filter(el=>getComputedStyle(el).display!=='none').map(el=>el.id||el.tagName),
          cssMissing:[...document.styleSheets].filter(sheet=>sheet.href&&!sheet.cssRules.length).map(sheet=>sheet.href),
          controlOverflow:[...page.querySelectorAll('button,select')].filter(el=>el.getClientRects().length).filter(el=>!el.closest('.recognition-camera-strip')).map(el=>box(el)).filter(r=>r.x<0||r.right>innerWidth+1),
          actualPictures:page.querySelectorAll('img[src]').length,events:document.querySelector('#recentRecognitionCount').textContent};
      })()`);
      assert.equal(metrics.owners,1);assert.equal(metrics.cameras,4);assert.equal(metrics.events,'0');assert.equal(metrics.actualPictures,0);
      assert.equal(metrics.background,'rgb(8, 17, 27)'); assert.deepEqual(metrics.hiddenLeaks,[]);assert.deepEqual(metrics.cssMissing,[]);assert.deepEqual(metrics.controlOverflow,[]);
      const initialShot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(output,view.name+'.png'),Buffer.from(initialShot.data,'base64'));
      assert.ok(metrics.pageWidth<=view.width+1,'Horizontal page overflow'); assert.ok(Math.abs(metrics.video.width/metrics.video.height-16/9)<.01,'Video aspect ratio: '+JSON.stringify({box:metrics.video,css:metrics.videoAspect}));
      assert.ok(metrics.snapshot.height<=161,'Compact evidence photo');
      if(view.width>=1440) assert.ok(metrics.detail.x>metrics.camera.x+metrics.camera.width,'Details must sit right of camera');
      else assert.ok(metrics.detail.y>=metrics.camera.bottom,'Small-screen details must follow camera');
      await evaluate(`document.querySelectorAll('.recognition-camera-choice')[2].focus()`);
      assert.equal(await evaluate(`document.activeElement.matches('.recognition-camera-choice')`),true,'Camera button focused before Enter');
      await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',text:'\r',unmodifiedText:'\r',windowsVirtualKeyCode:13,nativeVirtualKeyCode:13});
      await call('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,nativeVirtualKeyCode:13});
      assert.equal(await evaluate(`window.BTMHRecognitionSlots.getSelection().camera.camera_id`),3,'Keyboard camera switching');
      assert.equal(await evaluate(`document.activeElement.matches('.recognition-camera-choice')`),true,'Keyboard focus preserved');
      assert.ok(await evaluate(`getComputedStyle(document.activeElement).outlineStyle!=='none'`),'Visible keyboard focus');
      await evaluate(`document.querySelector('.recognition-attendance-details').open=true;document.querySelector('#recognitionAttendanceSession').scrollIntoView({block:'center',behavior:'instant'})`);
      await evaluate(`new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
      const attendance=await evaluate(`(()=>{const r=document.querySelector('#recognitionAttendanceSession').getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height,viewport:innerHeight}})()`);
      assert.ok(attendance.top>=0&&attendance.bottom<=attendance.viewport,'Attendance control reachable: '+view.name+' '+JSON.stringify(attendance));
      await evaluate(`document.querySelector('.recognition-attendance-details').open=false;window.scrollTo({top:0,behavior:'instant'});document.querySelector('.recognition-camera-strip').scrollLeft=0;document.activeElement.blur();`);
      const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false}); fs.writeFileSync(path.join(output,view.name+'.png'),Buffer.from(shot.data,'base64'));
      results.push({name:view.name,status:'PASS',metrics});
    }
    assert.deepEqual(pageErrors,[],'Browser script errors');assert.ok(!served.some(url=>url.startsWith('/api/')),'Preview must never send API requests');
    fs.writeFileSync(path.join(output,'visual-results.json'),JSON.stringify({preview_only:true,photo_regression_only:photoQa,real_camera_verified:false,api_requests:0,results},null,2));
    console.log(JSON.stringify({passed:results.length,api_requests:0,screenshots:output}));
  } finally {
    if(socket?.readyState===WebSocket.OPEN && call) { try{await call('Browser.close');}catch(_){} }
    socket?.close(); if(child && child.exitCode===null)child.kill(); await new Promise(resolve=>server.close(resolve));
  }
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
