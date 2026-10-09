from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8')
a=html.index('<section class="page" id="page-recognition">')
b=html.index('<section class="page" id="page-classroom">',a)
section=html[a:b]
for token in ('recognitionSnapshot','profileName','profileConfidence','profileLiveness','recognitionAlert','recognitionRecentBody'):
    assert f'id="{token}"' in section, token
assert 'Chống giả mạo' in section
assert 'không yêu cầu nhìn camera' in section.lower()
print('[OK] recognition page contract preserved with passive anti-spoof UI')
