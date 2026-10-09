"""Local static visual QA of actual frontend markup; no API/runtime/customer data."""
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
OUTPUT = FRONTEND / ".qa_preview_v550"


def generate():
    OUTPUT.mkdir(exist_ok=True)
    source = (FRONTEND / "index.html").read_text(encoding="utf-8")
    source = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", "", source, flags=re.I)
    banner = '''<div style="position:fixed;bottom:8px;right:8px;z-index:100000;background:#fff6e6;color:#54212d;border:1px solid #bb934c;border-radius:8px;padding:6px 10px;font:12px Arial">Preview local · Giao diện không có API hoặc dữ liệu khách hàng</div>'''
    navigation = '''<script>
document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',e=>e.preventDefault()));
document.querySelectorAll('[data-page]').forEach(button=>button.addEventListener('click',()=>{
  const page=button.dataset.page;
  document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id==='page-'+page));
  document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page===page));
  const title=document.querySelector('#pageTitle');if(title)title.textContent=button.textContent.trim();
  document.body.classList.remove('btmh-menu-open');
  window.scrollTo(0,0);
}));
document.querySelector('#btmhMenuToggle')?.addEventListener('click',()=>document.body.classList.toggle('btmh-menu-open'));
document.querySelector('#btmhMenuBackdrop')?.addEventListener('click',()=>document.body.classList.remove('btmh-menu-open'));
</script>'''
    admin = source.replace('id="authGate"', 'id="authGate" hidden', 1)
    admin = re.sub(r'(<div class="[^"]+)(" id="authGate")', r'\1 hidden\2', admin, count=1)
    admin = admin.replace('class="app-shell" inert', 'class="app-shell"', 1)
    admin = admin.replace("</body>", banner + navigation + "</body>")
    login = source.replace('id="authGateLogin" class="hidden"', 'id="authGateLogin" class=""', 1)
    login = login.replace("</body>", banner + "</body>")
    (OUTPUT / "admin.html").write_text(admin, encoding="utf-8")
    (OUTPUT / "login.html").write_text(login, encoding="utf-8")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND), **kwargs)

    def do_GET(self):
        if self.path.startswith("/api/"):
            self.send_error(404, "Static QA has no API")
            return
        if self.path.startswith("/static/"):
            self.path = self.path[len("/static"):]
        if self.path == "/":
            self.path = "/.qa_preview_v550/admin.html"
        super().do_GET()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    generate()
    if "--serve" in sys.argv:
        print("Static QA: http://127.0.0.1:8810/.qa_preview_v550/admin.html", flush=True)
        ThreadingHTTPServer(("127.0.0.1", 8810), Handler).serve_forever()
