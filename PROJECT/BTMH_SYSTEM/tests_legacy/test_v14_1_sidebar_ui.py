from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'frontend/index.html').read_text(encoding='utf-8')
css=(ROOT/'frontend/css/professional_v14_1_sidebar_icons.css').read_text(encoding='utf-8')
assert 'professional_v14_1_sidebar_icons.css?v=14.1.0' in html
assert 'v141-sidebar-icons' in html
for page in ['dashboard','live-monitor','recognition','operations','history','ops-center','students','register','classroom','camera-control','system']:
    marker=f'data-page="{page}"'
    i=html.index(marker)
    chunk=html[i:i+700]
    assert '<span class="nav-icon"><svg' in chunk, page
assert 'width:30px!important' in css
assert 'height:30px!important' in css
assert 'width:22px!important' in css
assert 'color:#63efd1!important' in css
assert 'font-size:13.5px!important' in css
print('[OK] V14.1 sidebar icon clarity contract')
