/* Event-driven navigation. No observer may mutate its own observed class. */
(() => {
  'use strict';
  const $=s=>document.querySelector(s);
  const mobile=()=>matchMedia('(max-width: 900px)').matches;
  function closeMenu(){const menu=$('#btmhMenuToggle'),wasOpen=document.body.classList.contains('btmh-menu-open'),inside=$('#btmhSidebar')?.contains(document.activeElement);document.body.classList.remove('btmh-menu-open');menu?.setAttribute('aria-expanded','false');if(wasOpen&&inside)menu?.focus();}
  const menuButtons=()=>[...document.querySelectorAll('#btmhSidebar button')].filter(el=>!el.disabled&&el.getClientRects().length);
  function syncNavigation(){
    const cluster=$('[data-nav-cluster="camera"]'),toggle=cluster?.querySelector('.btmh-nav-cluster-toggle');
    if(cluster?.querySelector('.nav-item.active'))cluster.classList.add('open');
    toggle?.setAttribute('aria-expanded',String(!!cluster?.classList.contains('open')));
    if(cluster)cluster.hidden=![...cluster.querySelectorAll('.nav-item')].some(el=>!el.classList.contains('permission-locked')&&!el.classList.contains('hidden'));
    document.querySelectorAll('#btmhSidebar .v13-nav-group').forEach(group=>{group.hidden=![...group.querySelectorAll('.nav-item')].some(el=>!el.classList.contains('permission-locked')&&!el.classList.contains('hidden'));});
    document.querySelectorAll('.nav-item').forEach(el=>{if(el.classList.contains('active'))el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
    closeMenu();
  }
  function start(){
    const cluster=$('[data-nav-cluster="camera"]'),toggle=cluster?.querySelector('.btmh-nav-cluster-toggle');
    toggle?.addEventListener('click',()=>{const open=!cluster.classList.contains('open');cluster.classList.toggle('open',open);toggle.setAttribute('aria-expanded',String(open));});
    document.addEventListener('btmh:navigate',syncNavigation);document.addEventListener('btmh:auth',syncNavigation);
    document.addEventListener('click',event=>{
      const button=event.target.closest('[data-toggle-password]');if(!button)return;
      const input=document.getElementById(button.dataset.togglePassword||'');if(!input)return;
      const showing=input.type==='text';input.type=showing?'password':'text';
      button.setAttribute('aria-label',showing?'Hi\u1ec7n m\u1eadt kh\u1ea9u':'\u1ea8n m\u1eadt kh\u1ea9u');button.setAttribute('aria-pressed',String(!showing));input.focus({preventScroll:true});
    });
    const menu=$('#btmhMenuToggle');
    menu?.addEventListener('click',()=>{if(document.body.classList.contains('btmh-menu-open')){closeMenu();return;}document.body.classList.add('btmh-menu-open');menu.setAttribute('aria-expanded','true');if(mobile())menuButtons()[0]?.focus();});
    $('#btmhMenuBackdrop')?.addEventListener('click',closeMenu);document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeMenu();return;}if(e.key!=='Tab'||!mobile()||!document.body.classList.contains('btmh-menu-open'))return;const buttons=menuButtons(),first=buttons[0],last=buttons.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}});
    const mq=matchMedia('(prefers-reduced-motion: reduce)'),gate=$('#authGate');
    const motion=()=>gate?.classList.toggle('motion-paused',document.hidden||mq.matches||gate.classList.contains('hidden'));
    document.addEventListener('visibilitychange',motion);document.addEventListener('btmh:auth',motion);mq.addEventListener?.('change',motion);motion();syncNavigation();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
