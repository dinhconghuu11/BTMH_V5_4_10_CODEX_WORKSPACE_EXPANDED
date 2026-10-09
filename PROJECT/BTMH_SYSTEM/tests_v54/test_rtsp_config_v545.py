from tests_v54.test_camera_v544 import client, login, add, FakeSession
from module_app import db


def test_corrected_registry_endpoint_reaches_decoder_without_secret_loss(client,monkeypatch):
    c,cam,old=client;cid=add();login(c)
    body={'host':'192.0.2.77','port':554,'path':'/Streaming/Channels/101','username':'operator','password':'Only@%40:/?#Secret'}
    r=c.put(f'/api/v1/cameras/devices/{cid}/connection',json=body)
    assert r.status_code==200 and 'Secret' not in r.text
    opened=[]
    def create(src):opened.append(src);return FakeSession(src)
    monkeypatch.setattr(cam,'_new_session',create)
    r=c.post('/api/v1/camera/test-source',json={'source':f'CAM{cid:02d}'})
    assert r.status_code==200 and r.json()['ok']
    assert len(opened)==1 and '@192.0.2.77:554/Streaming/Channels/101' in opened[0]
    assert 'Only%40%2540%3A%2F%3F%23Secret' in opened[0]
    assert not old.closed and cam.current_source_identity()=='0'


def test_test_connection_does_not_rewrite_network_or_database(client,monkeypatch):
    c,cam,old=client;cid=add();login(c)
    before=db.fetchone('SELECT * FROM camera_devices WHERE id=?',(cid,))
    monkeypatch.setattr(cam,'_new_session',lambda source:FakeSession(source,False))
    r=c.post('/api/v1/camera/test-source',json={'source':f'CAM{cid:02d}'})
    assert not r.json()['ok']
    after=db.fetchone('SELECT * FROM camera_devices WHERE id=?',(cid,))
    assert after==before and not old.closed
