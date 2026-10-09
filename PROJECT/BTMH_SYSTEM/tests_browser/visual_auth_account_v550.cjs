/* Static UI inspection using an isolated, already-running headless Chrome.
   Start preview_ui_v550.py --serve first. No product scripts/API are loaded. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const output = path.join(__dirname, '../frontend/.qa_preview_v550');
async function main() {
  const tab = await (await fetch('http://127.0.0.1:9228/json/new?about:blank', {method:'PUT'})).json();
  const socket = new WebSocket(tab.webSocketDebuggerUrl), waiting = new Map();
  let id = 0;
  socket.addEventListener('message', event => {
    const msg = JSON.parse(event.data);
    if (waiting.has(msg.id)) { const task=waiting.get(msg.id); waiting.delete(msg.id); msg.error?task.reject(new Error(msg.error.message)):task.resolve(msg.result); }
  });
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
  const call = (method,params={}) => new Promise((resolve,reject)=>{const next=++id;waiting.set(next,{resolve,reject});socket.send(JSON.stringify({id:next,method,params}));});
  const evaluate = async expression => {
    const result=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(result.exceptionDetails)throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const results=[];
  try {
    await call('Page.enable');await call('Runtime.enable');
    for (const item of [
      {name:'login-desktop',view:'login',width:1440,height:1000},
      {name:'login-tablet',view:'login',width:768,height:1024},
      {name:'login-mobile',view:'login',width:390,height:844},
      {name:'login-short',view:'login',width:1440,height:600},
      {name:'setup-desktop',view:'setup',width:1440,height:900},
      {name:'setup-mobile',view:'setup',width:390,height:844},
      {name:'help-mobile',view:'forgot',width:390,height:844},
      {name:'mfa-mobile',view:'mfa',width:390,height:844},
      {name:'recovery-mobile',view:'recovery',width:390,height:844},
      {name:'account-desktop',view:'account',width:1440,height:900},
      {name:'account-mobile',view:'account',width:390,height:844},
    ]) {
      await call('Emulation.setDeviceMetricsOverride',{width:item.width,height:item.height,deviceScaleFactor:1,mobile:false});
      await call('Page.navigate',{url:`http://127.0.0.1:8810/.qa_preview_v550/${item.view==='account'?'admin':'login'}.html`});
      await evaluate(`new Promise(resolve=>{if(document.readyState==='complete')resolve();else window.addEventListener('load',resolve,{once:true});})`);
      await evaluate(`(() => {
        const view=${JSON.stringify(item.view)};
        if(view==='account'){
          document.querySelector('#v23UserChip').disabled=false;
          document.querySelector('#v23UserName').textContent='Nguyễn Minh Anh';
          document.querySelector('#v23UserInitial').textContent='A';
          document.querySelector('#v23UserChip').setAttribute('aria-expanded','true');
          document.querySelector('#btmhAccountMenu').hidden=false;
          document.querySelector('#accountMenuManageBtn').hidden=false;
          document.querySelector('#accountMenuName').textContent='Nguyễn Minh Anh';
          document.querySelector('#accountMenuUsername').textContent='@quantri';
          document.querySelector('#accountMenuRole').textContent='Quản trị viên';
        }else{
          document.querySelector('#authGateSetup').classList.toggle('hidden',view!=='setup');
          document.querySelector('#authGateLogin').classList.toggle('hidden',view==='setup');
          for(const [key,id] of [['login','gateLoginView'],['forgot','gateForgotView'],['mfa','gateMfaView']])
            document.getElementById(id).classList.toggle('hidden',key!==(view==='recovery'?'mfa':view));
          if(view==='recovery'){
            document.querySelector('#gateMfaVerifyBox').classList.add('hidden');
            document.querySelector('#gateMfaRecoveryBox').classList.remove('hidden');
            document.querySelector('#gateMfaRecoveryCodes').innerHTML=Array.from({length:8},(_,i)=>'<code>DEMO-RECOVERY-0'+i+'</code>').join('');
          }
        }
      })()`);
      await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
      const metrics = await evaluate(`(() => {
        const view=${JSON.stringify(item.view)},box=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
        const root=document.querySelector(view==='account'?'#btmhAccountMenu':'#authGate');
        const cssFailures=Array.from(document.styleSheets).filter(s=>s.href&&s.cssRules.length===0).map(s=>s.href);
        const leaked=Array.from(document.querySelectorAll('#authGate .hidden,#btmhAccountControl [hidden]')).filter(el=>getComputedStyle(el).display!=='none').map(el=>el.id||el.className);
        const inputs=Array.from(root.querySelectorAll('input:not([type="hidden"]),button')).filter(el=>el.getClientRects().length);
        return {box:box(root),visibility:getComputedStyle(root).visibility,pageWidth:document.documentElement.scrollWidth,cssFailures,leaked,
          appInert:document.querySelector('.app-shell').inert,controls:inputs.map(el=>({id:el.id,box:box(el),font:getComputedStyle(el).fontSize})),
          viewHeight:innerHeight,viewWidth:innerWidth};
      })()`);
      assert.deepEqual(metrics.cssFailures,[],item.name+' CSS missing');assert.deepEqual(metrics.leaked,[],item.name+' hidden view revealed');
      assert.ok(metrics.box.width>0&&metrics.box.height>0,item.name+' root not rendered');
      assert.equal(metrics.visibility,'visible',item.name+' root not visible');
      assert.ok(metrics.box.x>=-1&&metrics.box.right<=item.width+1,item.name+' root horizontal overflow '+JSON.stringify(metrics.box));
      if(item.view==='account')assert.ok(metrics.box.bottom<=item.height,item.name+' menu outside viewport');
      else {
        assert.equal(metrics.appInert,true,item.name+' app should remain inert');
        assert.ok(metrics.controls.every(c=>c.box.x>=-1&&c.box.right<=item.width+1),item.name+' control horizontal overflow');
        const selector=item.view==='setup'?'#gateSetupBtn':item.view==='forgot'?'#forgotReturnBtn':item.view==='recovery'?'#gateMfaContinueBtn':item.view==='mfa'?'#gateMfaVerifyBtn':'#gateLoginBtn';
        metrics.actionReachable=await evaluate(`(() => {const el=document.querySelector(${JSON.stringify(selector)});el.scrollIntoView({block:'center'});const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;})()`);
        assert.equal(metrics.actionReachable,true,item.name+' final action unreachable');
        await evaluate("document.querySelector('#authGate').scrollTop=0");
      }
      const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
      fs.writeFileSync(path.join(output,item.name+'.png'),Buffer.from(shot.data,'base64'));
      results.push({name:item.name,status:'PASS',metrics});
    }
    fs.writeFileSync(path.join(output,'visual-results.json'),JSON.stringify(results,null,2));
    console.log(JSON.stringify({passed:results.length,screenshots:output}));
  }finally{socket.close();await fetch('http://127.0.0.1:9228/json/close/'+tab.id);}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
