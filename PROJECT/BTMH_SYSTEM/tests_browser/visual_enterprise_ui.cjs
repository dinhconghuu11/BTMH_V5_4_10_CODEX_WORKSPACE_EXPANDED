/* Real Chrome layout QA on isolated static source. No hardware or Production API.
   Empty API fixtures exercise presentation only, never commercial acceptance. */
'use strict';
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const before = process.argv.includes('--before');
const backend = process.argv.includes('--backend');
const checkpoint = path.resolve(__dirname, '../docs/checkpoints/'+(backend?'catalog-backend-20261009':'enterprise-ui-20261009'));
const frontend = before ? path.join(checkpoint, 'source-before', 'frontend') : path.resolve(__dirname, '../frontend');
const output = path.join(checkpoint, 'visual', before ? 'before' : 'after');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
function html() {
  let source = fs.readFileSync(path.join(frontend, 'index.html'), 'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
  source = source.replace('class="app-shell" inert', 'class="app-shell"').replace('id="authGate"', 'id="authGate" hidden');
  const scripts = ['btmh_customer_v541.js', 'btmh_management.js', ...(!before ? ['btmh_catalogs.js'] : [])];
  const setup = `<script>
    document.querySelector('#authGate').classList.add('hidden');
    const state={authUser:{role:'SUPER_ADMIN'},activePage:'dashboard'};
    const appPresentationActive=()=>!!state.authUser, hasUiPermission=()=>!!state.authUser;
    const api=async(url)=>{
      if(url.startsWith('/api/v1/dashboard/summary'))return {employees:{total:0},employee_with_valid_data_today:0,attendance:{configured:false},cameras:{total:0,online:0},incidents:{count_known:true,open:0},latest:[],generated_at:new Date().toISOString()};
      if(['/api/v1/stores','/api/v1/recognition/cameras'].includes(url))return {items:[]};
      if(url==='/api/v1/zones')return {available:true,items:[]};
      throw new Error('Static layout: API disabled');
    };
    window.navigate=page=>{const previousPage=state.activePage;state.activePage=page;document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id==='page-'+page));document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page===page));document.querySelector('#pageTitle').textContent=document.querySelector('.nav-item.active .nav-label')?.textContent||page;document.dispatchEvent(new CustomEvent('btmh:navigate',{detail:{page,previousPage}}));window.scrollTo(0,0);};
    document.querySelectorAll('.nav-item').forEach(el=>el.addEventListener('click',()=>navigate(el.dataset.page)));
    document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',event=>event.preventDefault()));
  </script>${scripts.map(name=>'<script src="/static/js/'+name+'"></script>').join('')}`;
  return source.replace('</body>', setup + '</body>');
}
async function main() {
  fs.mkdirSync(output, {recursive:true});
  const page = html(), served = [], errors = [], results = [];
  const server = http.createServer((request,response)=>{
    const pathname = new URL(request.url,'http://127.0.0.1').pathname;served.push(pathname);
    if(pathname==='/'){response.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});response.end(page);return;}
    const filename = path.resolve(frontend, '.'+decodeURIComponent(pathname.slice('/static'.length)));
    if(!pathname.startsWith('/static/')||!filename.startsWith(frontend+path.sep)||!fs.existsSync(filename)||!fs.statSync(filename).isFile()){response.writeHead(404);response.end();return;}
    const types={'.css':'text/css','.js':'application/javascript','.png':'image/png','.svg':'image/svg+xml'};
    response.writeHead(200,{'Content-Type':types[path.extname(filename)]||'application/octet-stream'});fs.createReadStream(filename).pipe(response);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base='http://127.0.0.1:'+server.address().port, profile=path.join(output,'chrome-profile-'+Date.now());
  let child,socket,call;
  try {
    const chrome=process.env.BTMH_QA_CHROME||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';assert.ok(fs.existsSync(chrome));
    child=spawn(chrome,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-extensions','--disable-sync','--disable-component-update','--disable-features=OptimizationHints,MediaRouter','--no-proxy-server','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{windowsHide:true,stdio:'ignore'});
    let childError;child.on('error',error=>{childError=error;});
    const portFile=path.join(profile,'DevToolsActivePort'),deadline=Date.now()+15000;
    while(!fs.existsSync(portFile)&&Date.now()<deadline&&!childError)await delay(100);
    if(childError)throw childError;assert.ok(fs.existsSync(portFile),'Isolated Chrome inspection unavailable');
    const debug='http://127.0.0.1:'+fs.readFileSync(portFile,'utf8').split(/\r?\n/)[0];
    const tab=await(await fetch(debug+'/json/new?about:blank',{method:'PUT'})).json();socket=new WebSocket(tab.webSocketDebuggerUrl);
    const pending=new Map();let next=0;
    socket.addEventListener('message',event=>{const message=JSON.parse(event.data);if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.text);if(pending.has(message.id)){const task=pending.get(message.id);pending.delete(message.id);clearTimeout(task.timer);message.error?task.reject(new Error(message.error.message)):task.resolve(message.result);}});
    await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
    call=(method,params={})=>new Promise((resolve,reject)=>{const id=++next,timer=setTimeout(()=>reject(new Error(method+' timeout')),8000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});
    const evaluate=async expression=>{const data=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(data.exceptionDetails)throw new Error(data.exceptionDetails.text);return data.result.value;};
    await call('Page.enable');await call('Runtime.enable');
    for(const [width,height] of [[1920,1080],[1440,900],[1366,768],[768,1024],[390,844]]){
      await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});await call('Page.navigate',{url:base+'/'});
      await evaluate(`new Promise(resolve=>document.readyState==='complete'?resolve():addEventListener('load',resolve,{once:true}))`);
      for(const name of ['dashboard','students','history','ops-center','system','recognition','live-grid','playback','register','work-shifts','hr-report','operations','incidents','visitors','admin-security','camera-control','live-monitor']){
        await evaluate(`navigate(${JSON.stringify(name)});new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
        const metrics=await evaluate(`(()=>{const p=document.getElementById('page-'+state.activePage),visible=el=>!!el.getClientRects().length;return {width:document.documentElement.scrollWidth,viewport:innerWidth,hiddenLeaks:[...document.querySelectorAll('[hidden],.permission-locked')].filter(visible).map(el=>el.id),controlOverflow:[...p.querySelectorAll('button,input,select,textarea')].filter(visible).filter(el=>!el.closest('.table-wrap,.recognition-camera-strip,.btmh-visit-hour-chart,.student-enterprise-nav')).filter(el=>{const r=el.getBoundingClientRect();return r.left<0||r.right>innerWidth+1}).map(el=>el.id||el.className),mainLeft:document.querySelector('.main').getBoundingClientRect().left};})()`);
        const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(output,name+'-'+width+'.png'),Buffer.from(shot.data,'base64'));
        results.push({page:name,width,height,...metrics});
        if(!before){assert.ok(metrics.width<=width+1,`${name}/${width}: page overflow ${metrics.width}`);assert.deepEqual(metrics.hiddenLeaks,[],`${name}: hidden leak`);assert.deepEqual(metrics.controlOverflow,[],`${name}/${width}: controls overflow`);if(width>900)assert.ok(metrics.mainLeft>=260,'Desktop sidebar overlap');}
      }
      if(!before){
        for (const formCase of ['store','zone','employee','system','report']) {
          await evaluate(`(async()=>{const name=${JSON.stringify(formCase)};navigate(['store','zone'].includes(name)?'ops-center':name==='employee'?'students':name==='system'?'system':'history');if(name==='store'){BTMHCatalogs.selectTab('stores');document.querySelector('#catalogAddStore').click();}if(name==='zone'){BTMHCatalogs.selectTab('zones');await new Promise(resolve=>setTimeout(resolve,20));document.querySelector('#catalogAddZone').click();}if(name==='employee'){document.querySelector('#studentCreateModal').classList.remove('hidden');}if(name==='system'){document.querySelector('#systemCameraDetails').open=true;document.querySelector('#cameraConnectionDetails').open=true;}if(name==='report'){document.querySelector('.demo-report-additional').open=true;}})();new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
          const geometry=await evaluate(`(()=>{const roots=[document.querySelector('.page.active'),document.querySelector('#studentCreateModal:not(.hidden)')].filter(Boolean);return {pageWidth:document.documentElement.scrollWidth,overflow:roots.flatMap(p=>[...p.querySelectorAll('button,input,select,textarea')]).filter(el=>el.getClientRects().length&&!el.closest('.student-enterprise-nav,.table-wrap,.demo-report-table-wrap')).filter(el=>{const r=el.getBoundingClientRect();return r.left<0||r.right>innerWidth+1}).map(el=>el.id||el.className)};})()`);
          assert.ok(geometry.pageWidth<=width+1,formCase+' form page overflow');assert.deepEqual(geometry.overflow,[],formCase+' form controls overflow');
          const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(output,'form-'+formCase+'-'+width+'.png'),Buffer.from(shot.data,'base64'));
          results.push({form:formCase,width,height,...geometry});
          await evaluate(`document.querySelector('#studentCreateModal').classList.add('hidden')`);
        }
        await evaluate(`navigate('ops-center');document.querySelector('#catalogTabZones').focus()`);
        await call('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowRight',code:'ArrowRight',windowsVirtualKeyCode:39});await call('Input.dispatchKeyEvent',{type:'keyUp',key:'ArrowRight',code:'ArrowRight',windowsVirtualKeyCode:39});
        assert.equal(await evaluate(`document.activeElement.id`),'catalogTabCameras');
        assert.equal(await evaluate(`document.querySelector('#catalogCameraPanel').hidden`),false);
        await evaluate(`navigate('dashboard');document.querySelector('#btmhMenuToggle').click()`);
        if(width<=900){assert.equal(await evaluate(`document.activeElement.closest('#btmhSidebar')!==null`),true,'Mobile menu focus');await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});assert.equal(await evaluate(`document.activeElement.id`),'btmhMenuToggle');}
      }
    }
    assert.deepEqual(errors,[],'Browser JS errors');assert.equal(served.some(url=>url.startsWith('/api/')),false,'No HTTP API');
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({mode:before?'BEFORE_OBSERVATION':'AFTER_STATIC_LAYOUT',results,errors,apiRequests:0,hardwareAcceptance:false},null,2));
    process.stdout.write(`${results.length} static page/viewport observations; ${before?'baseline recorded':'layout checks PASS'}; 0 HTTP API requests\n`);
  } finally {if(call)try{await call('Browser.close');}catch(_){}socket?.close();if(child&&!child.killed)child.kill();await new Promise(resolve=>server.close(resolve));}
}
main().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;});
