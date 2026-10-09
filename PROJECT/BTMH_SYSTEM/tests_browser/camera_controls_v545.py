from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
import os, shutil, tempfile
import threading,json
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1]
_temp=tempfile.TemporaryDirectory(prefix='btmh-camera-dom-');W=Path(_temp.name)
(W/'camera.js').write_bytes((R/'frontend/js/camera_tools_v544.js').read_bytes())
(W/'index.html').write_text('''<!doctype html><meta charset="utf-8"><title>Camera controls test</title>
<div class="v5-recognition-sourcebar"><select id="v5RecognitionCameraSelect"><option value="CAM02">Camera test</option><option value="0">Laptop</option></select><button id="v5RecognitionSwitchBtn" onclick="BTMHCameraTools.switchSource(document.querySelector('select'),this,document.querySelector('#v5RecognitionCameraNote'))">Switch</button><p id="v5RecognitionCameraNote"></p></div>
<button data-camera-edit="v5RecognitionCameraSelect">Edit</button><button data-camera-test="v5RecognitionCameraSelect">Test</button><script src="camera.js"></script>''')
checks=[];saved=[];errors=[]
def ok(name,condition):
 assert condition,name
 checks.append(name)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=os.getenv('BTMH_TEST_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome'),headless=True,args=['--no-sandbox'])
 context=browser.new_context(permissions=['clipboard-read','clipboard-write'])
 page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
 page.set_content((W/'index.html').read_text().replace('<script src="camera.js"></script>',''))
 page.evaluate("""() => {
 window.saved=[];window.copied='';
 Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.copied=text;},readText:async()=>window.copied}});
 window.fetch=async (url,opts={})=>{
  let data;
  if(url.endsWith('/connection') && (!opts.method || opts.method==='GET')) data={id:2,name:'Camera test',editable:true,host:'192.0.2.1',port:554,path:'/Streaming/Channels/101',username:'operator',credential_saved:true};
  else if(url.endsWith('/connection')){saved.push(JSON.parse(opts.body));data={ok:true};}
  else data={ok:false,code:'AUTH_FAILED',message:'Camera test auth failure',kept_previous:true,diagnostic:{code:'AUTH_FAILED',source_display:'rtsp://192.0.2.77:554/Streaming/Channels/101',reader:'native',backend:'ffmpeg-native',transport:'tcp',credential_supplied:true},runtime:{should_not_be_copied:'PRIVATE-DATA'}};
  return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
 };
 }""")
 page.add_script_tag(content=(W/'camera.js').read_text())
 page.evaluate("document.dispatchEvent(new Event('DOMContentLoaded'))")
 page.locator('[data-camera-edit]').click();page.locator('#camera544Host').wait_for()
 ok('saved host loaded',page.locator('#camera544Host').input_value()=='192.0.2.1')
 ok('password not returned to form',page.locator('#camera544Pass').input_value()=='')
 page.locator('#camera545Import summary').click()
 page.locator('#camera545Reference').fill('rtsp://192.0.2.77:554/Streaming/Channels/101')
 page.locator('#camera545Apply').click()
 ok('reference URL updates IP',page.locator('#camera544Host').input_value()=='192.0.2.77')
 ok('reference URL preserves user',page.locator('#camera544User').input_value()=='operator')
 ok('blank password retained on reference paste',page.locator('#camera544Pass').input_value()=='')
 ok('reference text cleared',page.locator('#camera545Reference').input_value()=='')
 ok('no automatic save',not page.evaluate('window.saved'))
 page.locator('#camera544Save').click();page.wait_for_timeout(200)
 ok('save sends corrected endpoint',page.evaluate('window.saved')[0]['host']=='192.0.2.77')
 ok('save keeps existing password',page.evaluate('window.saved')[0]['password'] is None)
 ok('dialog closes after save',not page.locator('#cameraConnectionDialog').is_visible())
 page.locator('[data-camera-test]').click();page.wait_for_timeout(200)
 ok('failure report visible',page.locator('[data-camera-report]').is_visible())
 ok('controls unlocked after failure',page.locator('[data-camera-test]').is_enabled() and page.locator('[data-camera-edit]').is_enabled() and page.locator('#v5RecognitionSwitchBtn').is_enabled())
 page.locator('[data-camera-report] button').click();page.wait_for_timeout(150)
 copied=page.evaluate('navigator.clipboard.readText()')
 ok('safe diagnostics copied',json.loads(copied)['code']=='AUTH_FAILED')
 ok('copy excludes full runtime', 'PRIVATE-DATA' not in copied and 'runtime' not in copied)
 page.locator('#v5RecognitionCameraSelect').select_option('0')
 ok('report clears on source change',page.locator('[data-camera-report]').count()==0)
 page.locator('#v5RecognitionCameraSelect').select_option('CAM02');page.locator('[data-camera-edit]').click()
 page.wait_for_timeout(100)
 page.locator('#camera545Reference').fill('https://example.test/not-rtsp')
 page.locator('#camera545Apply').click()
 ok('wrong protocol rejected',page.locator('#camera544Host').input_value()=='192.0.2.1')
 ok('no JavaScript errors',not errors)
 browser.close()

Path(os.getenv('BTMH_TEST_REPORT',str(W/'browser_result.json'))).write_text(json.dumps({'passed':len(checks),'checks':checks,'errors':errors,'backend':'MOCK fetch and clipboard; real Chromium DOM (localhost blocked by container policy)' },indent=2))
print(len(checks),'checks passed')
