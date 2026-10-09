from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8')
js=(ROOT/'frontend'/'js'/'app.js').read_text(encoding='utf-8')
css=(ROOT/'frontend'/'css'/'v1_3_cleanfix.css').read_text(encoding='utf-8')
boss=(ROOT/'frontend'/'css'/'boss_scope.css').read_text(encoding='utf-8')
v20=(ROOT/'frontend'/'css'/'v20.css').read_text(encoding='utf-8')
assert 'renderClassroomRoster()' not in js
assert '#page-classroom,' not in boss
assert '#page-classroom,#page-operations' not in v20
assert '#page-classroom.page.active{display:block!important}' in css
assert html.count('id="page-classroom"')==1
for token in ('classroomVideo','classroomOverlay','classroomStudents','classroomSeated','classroomStanding','classroomRaised','classroomMoving','classroomTracks','classroomEventsBody'):
    assert f'id="{token}"' in html, token
for token in ('/api/v1/classroom/start','/api/v1/classroom/stop','/api/v1/classroom/latest','drawClassroomOverlay','startClassroomStream'):
    assert token in js, token
# No inline navigation target may point to the removed class-operations page.
assert "navigate('class-operations')" not in html
print('[OK] V1.3 classroom clean-fix removes the exact blank-page regressions')
