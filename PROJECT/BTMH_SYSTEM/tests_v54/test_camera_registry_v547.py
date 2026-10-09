from module_app.camera_registry_v547 import candidate_hosts_for_legacy, legacy_hikvision_repair_plan
from module_app.camera_connection_v544 import connection_view


def _row(source='rtsp://admin:Old%40Pass@192.168.1.200:554/Streaming/Channels/101'):
    return {'id':2,'name':'Hikvision DS-2CD1123G0-IUF','source':source,'updated_at':'now'}


def test_candidate_uses_current_private_subnet_and_preserves_last_octet():
    values=candidate_hosts_for_legacy('192.168.1.200',['192.168.10.10','10.0.0.8','127.0.0.1'])
    assert '192.168.10.200' in values
    assert '10.0.0.200' in values
    assert '127.0.0.200' not in values


def test_unique_reachable_candidate_repairs_only_host_and_preserves_credential_and_path():
    plan=legacy_hikvision_repair_plan(
        _row(), local_ips=['192.168.10.10','192.168.50.9'],
        probe=lambda host,port: host=='192.168.10.200' and port==554,
    )
    assert plan is not None
    assert plan['previous_host']=='192.168.1.200'
    assert plan['new_host']=='192.168.10.200'
    assert 'Old%40Pass@192.168.10.200:554/Streaming/Channels/101' in plan['new_source']
    view=connection_view({'id':2,'name':'Hikvision DS-2CD1123G0-IUF','source':plan['new_source'],'updated_at':'now'})
    assert view['host']=='192.168.10.200'
    assert view['path']=='/Streaming/Channels/101'
    assert view['credential_saved'] is True


def test_ambiguous_candidates_do_not_modify_registry():
    plan=legacy_hikvision_repair_plan(
        _row(), local_ips=['192.168.10.10','192.168.50.9'], probe=lambda host,port: True,
    )
    assert plan is None


def test_unreachable_candidate_does_not_modify_registry():
    plan=legacy_hikvision_repair_plan(
        _row(), local_ips=['192.168.10.10'], probe=lambda host,port: False,
    )
    assert plan is None


def test_nonlegacy_or_nonhikvision_records_are_never_repaired():
    assert legacy_hikvision_repair_plan(
        {'id':3,'name':'Hikvision Camera','source':'rtsp://admin:x@192.168.10.200:554/Streaming/Channels/101'},
        local_ips=['192.168.20.10'], probe=lambda h,p: True,
    ) is None
    assert legacy_hikvision_repair_plan(
        {'id':4,'name':'Other Camera','source':'rtsp://admin:x@192.168.1.200:554/live'},
        local_ips=['192.168.10.10'], probe=lambda h,p: True,
    ) is None
