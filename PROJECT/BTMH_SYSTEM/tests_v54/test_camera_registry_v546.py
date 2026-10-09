from module_app.camera_connection_v544 import connection_view, update_connection_source
from module_app.camera_registry_v546 import persisted_connection_matches, startup_source_tracks_previous
from module_app.recording_runtime_v4 import LocalRecorderSupervisorV4


def test_connection_update_changes_only_endpoint_and_encodes_secret():
    old='rtsp://admin:Old%40Pass@192.168.1.200:554/Streaming/Channels/101'
    new=update_connection_source(old,'192.168.10.200',554,'/Streaming/Channels/101','admin','New@Pass')
    assert '192.168.10.200:554/Streaming/Channels/101' in new
    assert 'New%40Pass' in new
    assert '192.168.1.200' not in new


def test_persistence_guard_accepts_canonical_readback_only():
    expected='rtsp://admin:New%40Pass@192.168.10.200:554/Streaming/Channels/101'
    assert persisted_connection_matches(expected, {'source':expected})
    assert not persisted_connection_matches(expected, {'source':'rtsp://admin:New%40Pass@192.168.1.200:554/Streaming/Channels/101'})
    assert not persisted_connection_matches(expected, None)


def test_startup_source_follows_edited_registry_source():
    old='rtsp://admin:Old%40Pass@192.168.1.200:554/Streaming/Channels/101'
    other='0'
    assert startup_source_tracks_previous(old, old)
    assert not startup_source_tracks_previous(other, old)


def test_connection_view_warns_about_legacy_hikvision_host_without_exposing_password():
    row={'id':2,'name':'Hikvision DS-2CD1123G0-IUF','source':'rtsp://admin:Secret%40One@192.168.1.200:554/Streaming/Channels/101','updated_at':'now'}
    view=connection_view(row)
    assert view['host']=='192.168.1.200'
    assert view['credential_saved'] is True
    assert view['legacy_host_warning']
    assert 'Secret' not in view['source_display']


def test_recorder_invalidation_terminates_stale_process():
    class Proc:
        def __init__(self): self.terminated=False; self.killed=False
        def terminate(self): self.terminated=True
        def wait(self, timeout=None): return 0
        def kill(self): self.killed=True
    r=LocalRecorderSupervisorV4();p=Proc()
    r._processes[7]=p;r._started_at[7]=123.0
    r.invalidate_camera(7)
    assert p.terminated is True
    assert 7 not in r._processes
    assert 7 not in r._started_at
