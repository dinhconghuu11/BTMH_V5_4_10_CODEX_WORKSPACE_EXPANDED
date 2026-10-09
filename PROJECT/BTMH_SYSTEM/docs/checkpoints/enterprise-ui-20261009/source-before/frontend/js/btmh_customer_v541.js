/* Event-driven navigation. No observer may mutate its own observed class. */
(() => {
  'use strict';
  const $=s=>document.querySelector(s);
  function syncNavigation(){
    const cluster=$('[data-nav-cluster="camera"]'),toggle=cluster?.querySelector('.btmh-nav-cluster-toggle');
    if(cluster?.querySelector('.nav-item.active'))cluster.classList.add('open');
    toggle?.setAttribute('aria-expanded',String(!!cluster?.classList.contains('open')));
    document.querySelectorAll('.nav-item').forEach(el=>{if(el.classList.contains('active'))el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
    document.body.classList.remove('btmh-menu-open');$('#btmhMenuToggle')?.setAttribute('aria-expanded','false');
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
    const menu=$('#btmhMenuToggle');const close=()=>{document.body.classList.remove('btmh-menu-open');menu?.setAttribute('aria-expanded','false');};
    menu?.addEventListener('click',()=>{const open=document.body.classList.toggle('btmh-menu-open');menu.setAttribute('aria-expanded',String(open));});
    $('#btmhMenuBackdrop')?.addEventListener('click',close);document.addEventListener('keydown',e=>{if(e.key==='Escape')close();});
    const mq=matchMedia('(prefers-reduced-motion: reduce)'),gate=$('#authGate');
    const motion=()=>gate?.classList.toggle('motion-paused',document.hidden||mq.matches||gate.classList.contains('hidden'));
    document.addEventListener('visibilitychange',motion);document.addEventListener('btmh:auth',motion);mq.addEventListener?.('change',motion);motion();syncNavigation();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
