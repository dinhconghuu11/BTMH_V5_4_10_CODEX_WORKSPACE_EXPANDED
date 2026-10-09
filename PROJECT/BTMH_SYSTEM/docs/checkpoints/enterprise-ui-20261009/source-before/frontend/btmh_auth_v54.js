(() => {
  'use strict';
  function sync(){const gate=document.getElementById('authGate');document.body.classList.toggle('btmh-auth-active',!!gate&&!gate.classList.contains('hidden'));}
  document.addEventListener('btmh:auth',sync);
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',sync,{once:true});else sync();
})();
