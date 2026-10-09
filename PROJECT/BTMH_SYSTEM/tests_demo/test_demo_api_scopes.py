"""Exercise changed route functions without booting cameras, models or customer data."""
import ast
import asyncio
import json
import csv
import io
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code, self.detail = status_code, detail


def route_functions(names, **injections):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'module_app' / 'main.py').read_text(encoding='utf-8'))
    definitions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    for node in definitions:
        node.decorator_list = []
    selected = ast.Module(body=definitions, type_ignores=[])
    namespace = {'Request': object, 'ShiftV5Payload': object, 'ShiftAssignPayload': object,
                 'HTTPException': HTTPException, 'date': date, 'datetime': datetime,
                 'timedelta': timedelta, 'timezone': timezone, 'csv': csv, 'io': io,
                 'ZoneInfo': ZoneInfo, 'WebSocket': object, 'Response': object,
                 'AccountError': type('AccountError', (ValueError,), {}),
                 'SelfProfilePayload': object, 'SelfPasswordPayload': object,
                 '_safe_name': lambda value: str(value or ''), **injections}
    exec(compile(selected, '<changed-routes>', 'exec'), namespace)
    return namespace


class DemoAPIScopeTests(unittest.TestCase):
    def setUp(self):
        self.user = {'role': 'MANAGER', 'store_id': 1}
        self.scope = lambda user: None if user.get('role') == 'ADMIN' else frozenset([user['store_id']])
        def enforce(user, store_id):
            allowed = self.scope(user)
            if allowed is not None and store_id not in allowed:
                raise PermissionError('STORE_SCOPE_DENIED')
        self.enforce = enforce

    def test_shift_read_filters_all_store_query_and_rejects_foreign_explicit_store(self):
        ns = route_functions({'_require_store_scope', 'work_shifts_v5'},
            _auth_permission=lambda *args: self.user, scoped_store_ids=self.scope, enforce_store_scope=self.enforce,
            list_shifts=lambda sid: [{'id': 1, 'store_id': 1}, {'id': 2, 'store_id': 2}, {'id': 3, 'store_id': None}])
        self.assertEqual([row['id'] for row in ns['work_shifts_v5'](object())['items']], [1])
        with self.assertRaises(HTTPException) as raised:
            ns['work_shifts_v5'](object(), 2)
        self.assertEqual(raised.exception.status_code, 403)

    def test_employee_route_denies_unassigned_and_foreign_employee(self):
        ns = route_functions({'_require_employee_scope', 'employee_shift_v5'},
            _auth_permission=lambda *args: self.user, scoped_store_ids=self.scope,
            fetchall=lambda sql, params: [{'store_id': 2}] if params[0] == 2 else [],
            employee_shift=lambda sid: self.fail('Denied employee must never be read'))
        for sid in (2, 3):
            with self.subTest(sid=sid), self.assertRaises(HTTPException) as raised:
                ns['employee_shift_v5'](sid, object())
            self.assertEqual(raised.exception.status_code, 403)

    def test_owner_can_read_employee_without_store_mapping(self):
        ns = route_functions({'_require_employee_scope', 'employee_shift_v5'},
            _auth_permission=lambda *args: {'role': 'ADMIN'}, scoped_store_ids=self.scope,
            employee_shift=lambda sid: {'student_id': sid, 'shift_id': 7})
        self.assertEqual(ns['employee_shift_v5'](3, object())['assignment']['shift_id'], 7)

    def test_existing_shift_store_checked_before_moving_configuration(self):
        ns = route_functions({'_require_store_scope', 'save_work_shift_v5'},
            _auth_permission=lambda *args: self.user, scoped_store_ids=self.scope, enforce_store_scope=self.enforce,
            fetchone=lambda *args: {'store_id': 2}, save_shift_v5=lambda *args: self.fail('Foreign shift mutation'))
        with self.assertRaises(HTTPException) as raised:
            ns['save_work_shift_v5'](SimpleNamespace(id=8, store_id=1), object())
        self.assertEqual(raised.exception.status_code, 403)

    def test_hr_report_passes_scope_before_query_and_denies_foreign_store(self):
        captured = []
        ns = route_functions({'_require_store_scope', 'hr_report_summary'},
            _auth_permission=lambda *args: self.user, scoped_store_ids=self.scope, enforce_store_scope=self.enforce,
            build_hr_report=lambda *args, **kwargs: captured.append(kwargs) or {'rows': []})
        ns['hr_report_summary'](object(), 'month', '2026-10-01')
        self.assertEqual(captured, [{'allowed_store_ids': frozenset([1]), 'store_id': None}])
        with self.assertRaises(HTTPException) as raised:
            ns['hr_report_summary'](object(), store_id=2)
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(len(captured), 1)

    def test_fleet_lists_only_authorized_context_and_actual_admission(self):
        ns = route_functions({'camera_fleet_status'}, _auth_permission=lambda *args: self.user,
            list_camera_contexts=lambda user: [{'camera_id': 5, 'store_id': user['store_id'], 'camera_name': 'Entry'}],
            AI_RUNTIME=SimpleNamespace(capacity=4, camera_state=lambda cid: {'ai_state': 'WAITING_FOR_CAPACITY', 'ai_admitted': False}))
        result = ns['camera_fleet_status'](object())
        self.assertEqual(result['capacity'], 4)
        self.assertFalse(result['items'][0]['active_ai_pipeline'])
        self.assertEqual(result['items'][0]['store_id'], 1)
        self.assertNotIn('source_display', result['items'][0])

    def test_history_date_range_accepts_leap_year_and_rejects_invalid_ranges(self):
        ns = route_functions({'_history_date_range'})
        self.assertEqual(ns['_history_date_range']('2024-01-01', '2024-12-31'), (date(2024, 1, 1), date(2024, 12, 31)))
        for start, end in [('2026-02-30', '2026-03-01'), ('2026-10-08', '2026-10-07'), ('2024-01-01', '2025-01-01')]:
            with self.subTest(start=start, end=end), self.assertRaises(HTTPException) as raised:
                ns['_history_date_range'](start, end)
            self.assertEqual(raised.exception.status_code, 400)

    def test_attendance_history_filters_then_paginates_and_never_returns_all_rows(self):
        rows = [{'employee_id': 1 if index % 2 else 2, 'status': 'MISSING_OUT', 'business_date': '2026-10-08', 'row': index} for index in range(500)]
        ns = route_functions({'_require_store_scope', '_history_date_range', '_attendance_filtered_report', 'shift_attendance_history'},
            _auth_permission=lambda *args: self.user, scoped_store_ids=self.scope, enforce_store_scope=self.enforce,
            build_shift_attendance_report=lambda *args, **kwargs: {'rows': rows, 'totals': {'scheduled_shifts': 500}})
        result = ns['shift_attendance_history'](object(), '2026-10-08', '2026-10-08', employee_id=1,
                                               result='missing_out', limit=10, offset=20)
        self.assertEqual(result['total'], 250)
        self.assertEqual(len(result['items']), 10)
        self.assertEqual(result['items'][0]['row'], 41)
        self.assertNotIn('rows', result)
        capped = ns['shift_attendance_history'](object(), '2026-10-08', '2026-10-08', limit=10000, offset=-5)
        self.assertEqual((len(capped['items']), capped['limit'], capped['offset']), (200, 200, 0))

    def test_metadata_snapshot_is_scoped_after_runtime_context_race(self):
        ns = route_functions({'_require_store_scope', 'media_metadata'},
            _auth_permission=lambda *args: self.user, enforce_store_scope=self.enforce,
            _camera_scope_context=lambda *args: {'store_id': 1},
            _media_tracking_payload=lambda *args: {'store_id': 2, 'tracks': [{'full_name': 'Foreign store'}]})
        with self.assertRaises(HTTPException) as raised:
            ns['media_metadata'](object(), 5)
        self.assertEqual(raised.exception.status_code, 403)

    def test_public_recognition_keeps_sequence_without_disclosing_unverified_identity_or_diagnostics(self):
        ns = route_functions({'_recognition_public_row'}, json=json)
        row = {'id': 42, 'daily_sequence': 7, 'appearance_id': 'appearance', 'business_date': '2026-10-08',
               'status': 'SPOOF_BLOCKED', 'student_id': 9, 'full_name': 'Candidate must stay private',
               'camera_source': 'internal source', 'detail_json': json.dumps({'snapshot_path': 'internal', 'liveness': {'status': 'FAIL'}})}
        blocked = ns['_recognition_public_row'](row)
        self.assertEqual((blocked['event_id'], blocked['daily_sequence']), (42, 7))
        self.assertIsNone(blocked['person_id'])
        self.assertNotIn('Candidate', blocked['full_name'])
        self.assertNotIn('camera_source', blocked)
        self.assertNotIn('detail', blocked)
        self.assertEqual(blocked['snapshot_url'], '')
        verified = ns['_recognition_public_row']({**row, 'status': 'RECOGNIZED', 'anti_spoof_passed': 1}, evidence_allowed=True)
        self.assertEqual(verified['person_id'], 9)
        self.assertEqual(verified['snapshot_url'], '/api/v1/events/42/evidence.jpg')
        malformed = ns['_recognition_public_row']({**row, 'detail_json': '{"liveness":"bad legacy value"}'})
        self.assertEqual(malformed['pad_status'], 'FAIL')

    def test_recent_query_scopes_store_and_camera_and_caps_rows_on_server(self):
        captured = []
        ns = route_functions({'recognition_recent'}, _auth_permission=lambda *args: self.user,
            scoped_store_ids=self.scope, _camera_scope_context=lambda *args: {'camera_id': 5, 'store_id': 1},
            fetchall=lambda sql, params: captured.append((sql, params)) or [],
            has_permission=lambda *args: False, utc_now=lambda: 'now')
        result = ns['recognition_recent'](object(), camera_id=5, limit=10000)
        self.assertEqual(result['items'], [])
        sql, params = captured[0]
        self.assertIn('r.camera_id=?', sql)
        self.assertIn('r.store_id IN (?)', sql)
        self.assertEqual(params, (5, 1, 50))

    def test_event_evidence_denies_foreign_store_before_accessing_private_file(self):
        ns = route_functions({'_require_store_scope', 'recognition_event_evidence'},
            _auth_permission=lambda *args: self.user, enforce_store_scope=self.enforce,
            fetchone=lambda *args: {'store_id': 2},
            recognition_evidence_path=lambda event_id: self.fail('Foreign evidence file must not be opened'))
        with self.assertRaises(HTTPException) as raised:
            ns['recognition_event_evidence'](object(), 42)
        self.assertEqual(raised.exception.status_code, 403)

    def test_csv_stream_quotes_and_neutralizes_formulas_without_discarding_unicode(self):
        ns = route_functions({'_csv_response'},
            StreamingResponse=lambda body, **kwargs: SimpleNamespace(body=body, **kwargs))
        response = ns['_csv_response']([{'name': ' =1+2', 'memo': 'Hà Đông, "Cửa vào"'}],
            [('name', 'Tên'), ('memo', 'Ghi chú')], 'BTMH.csv')
        content = ''.join(response.body)
        self.assertTrue(content.startswith('\ufeff'))
        rows = list(csv.reader(io.StringIO(content.lstrip('\ufeff'))))
        self.assertEqual(rows[1], ["' =1+2", 'Hà Đông, "Cửa vào"'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_recognition_csv_drains_all_keyset_pages_with_current_filters_and_scope(self):
        captured = []
        records = [{'event_id': event_id} for event_id in range(451, 0, -1)]
        def page(actor, start, end, **kwargs):
            captured.append((actor, start, end, kwargs))
            before = kwargs.get('before_id', 999)
            return {'items': [row for row in records if row['event_id'] < before][:200]}
        ns = route_functions({'recognition_history_csv'}, _auth_permission=lambda *args: self.user,
            _recognition_history_page=page, _csv_response=lambda rows, *args: list(rows))
        rows = ns['recognition_history_csv'](object(), '2026-10-01', '2026-10-08', store_id=1,
            zone_name='Cửa vào', camera_id=5, employee_id=9, subject_type='EMPLOYEE', result='RECOGNIZED', search='Đặng')
        self.assertEqual([row['event_id'] for row in rows], list(range(451, 0, -1)))
        self.assertEqual(len(captured), 3)
        for actor, start, end, filters in captured:
            self.assertIs(actor, self.user)
            self.assertEqual(filters['store_id'], 1)
            self.assertEqual(filters['search'], 'Đặng')
            self.assertEqual(filters['camera_id'], 5)
            self.assertEqual(filters['limit'], 200)
            self.assertNotIn('offset', filters)

    def test_attendance_csv_exports_all_filtered_rows_and_filtered_totals(self):
        records = [{'employee_id': 9, 'department': 'Kinh doanh', 'status': 'ABSENT'},
                   {'employee_id': 9, 'department': 'Kinh doanh', 'status': 'NOT_YET_DUE'},
                   {'employee_id': 8, 'department': 'Kho', 'status': 'ABSENT'}]
        ns = route_functions({'_require_store_scope', '_history_date_range', '_attendance_filtered_report', 'shift_attendance_csv'},
            _auth_permission=lambda *args: self.user, enforce_store_scope=self.enforce, scoped_store_ids=self.scope,
            build_shift_attendance_report=lambda *args, **kwargs: {'rows': records},
            _csv_response=lambda rows, *args: list(rows))
        filtered = ns['_attendance_filtered_report'](self.user, '2026-10-08', department='Kinh doanh', result='ABSENT')
        self.assertEqual(filtered['totals']['absent_days'], 1)
        rows = ns['shift_attendance_csv'](object(), '2026-10-08', department='Kinh doanh', result='ABSENT')
        self.assertEqual(rows, [records[0]])

    def test_timeline_keeps_last_seen_separate_from_out_and_scopes_overnight_query(self):
        captured = []
        record = {'employee_id': 9, 'business_date': '2026-10-08', 'store_id': 1,
                  'expected_start_at': '2026-10-08T15:00:00+00:00', 'expected_end_at': '2026-10-08T23:00:00+00:00',
                  'checkin_at': '2026-10-08T15:10:00+00:00', 'last_seen_at': '2026-10-08T22:30:00+00:00', 'checkout_at': None}
        ns = route_functions({'_history_date_range', 'shift_attendance_timeline'},
            _auth_permission=lambda *args: self.user, scoped_store_ids=self.scope,
            _attendance_filtered_report=lambda *args, **kwargs: {'rows': [record]},
            fetchall=lambda sql, params: captured.append((sql, params)) or [], utc_now=lambda: 'now')
        timeline = ns['shift_attendance_timeline'](object(), 9, '2026-10-08')
        self.assertEqual([row['event_type'] for row in timeline['items']], ['VALID_IN', 'LAST_OBSERVATION'])
        self.assertEqual(timeline['schedule_state'], 'ASSIGNED')
        sql, params = captured[0]
        self.assertIn('r.store_id IN (?)', sql)
        self.assertEqual(params[-1], 1)
        self.assertEqual(params[2], '2026-10-08T23:00:00+00:00')

    def test_timeline_unscheduled_is_neutral_and_excludes_next_midnight(self):
        captured = []
        ns = route_functions({'_history_date_range', 'shift_attendance_timeline'},
            _auth_permission=lambda *args: self.user, scoped_store_ids=self.scope,
            _attendance_filtered_report=lambda *args, **kwargs: {'rows': []},
            fetchall=lambda sql, params: captured.append(params) or [], utc_now=lambda: 'now')
        timeline = ns['shift_attendance_timeline'](object(), 9, '2026-10-08')
        self.assertEqual((timeline['items'], timeline['schedule_state']), ([], 'UNCONFIGURED'))
        self.assertEqual(captured[0][2], '2026-10-08T16:59:59.999999+00:00')

    def test_password_route_reuses_current_password_and_clears_all_session_cookies(self):
        captured, deleted, audit = [], [], []
        ns = route_functions({'auth_password_update'},
            _request_token=lambda request: 'session',
            change_self_password=lambda token, **kwargs: captured.append((token, kwargs)) or {'ok': True, 'relogin_required': True},
            AUTH_COOKIE='auth', sms_security=SimpleNamespace(TRUST_COOKIE='trust', PENDING_COOKIE='pending'),
            add_audit_event=lambda *args, **kwargs: audit.append(kwargs))
        result = ns['auth_password_update'](SimpleNamespace(current_password='current', new_password='new', confirm_password='new'),
            object(), SimpleNamespace(delete_cookie=lambda name, **kwargs: deleted.append(name)))
        self.assertEqual(deleted, ['auth', 'trust', 'pending'])
        self.assertEqual(captured, [('session', {'current_password': 'current', 'new_password': 'new', 'confirm_password': 'new'})])
        self.assertTrue(result['relogin_required'])
        self.assertNotIn('new', json.dumps(audit))

    def test_self_routes_are_authenticated_and_never_public_or_admin_only(self):
        ns = route_functions({'_api_permission_for'}, _AUTHENTICATED_ONLY='authenticated')
        for path in ('/api/v1/auth/profile', '/api/v1/auth/password'):
            for method in ('GET', 'PUT'):
                self.assertEqual(ns['_api_permission_for'](path, method), 'authenticated')

    def test_runtime_readiness_never_invents_active_camera_or_changes_historical_visits(self):
        ns = route_functions({'_visit_runtime_readiness'})
        report = {'stores': [{'store_id': 1, 'store_name': 'Entry', 'configured_camera_ids': [5],
            'configuration_state': 'READY', 'comparison_eligible': True, 'selected': 4, 'previous': 1, 'delta': 3,
            'percent': 300, 'change_state': 'INCREASE'}], 'totals': {'selected': 4, 'previous': 1}}
        result = ns['_visit_runtime_readiness'](report, [{'camera_id': 5, 'store_id': 1, 'ai_state': 'WAITING_FOR_CAPACITY', 'online': None}])
        self.assertEqual(result['configuration_state'], 'PARTIAL')
        self.assertEqual(result['totals']['selected'], 4)
        self.assertIsNone(result['max_rise'])

    def test_public_camera_status_does_not_initialize_models_open_readers_or_expose_diagnostics(self):
        ns = route_functions({'_public_camera_states', '_public_ai_status'},
            CAMERA=SimpleNamespace(current_source_identity=lambda: 'primary', status=lambda: {'opened': True, 'state': 'online', 'source': 'secret'}),
            source_context=lambda source: {'camera_id': 5}, runtime_config=SimpleNamespace(PAD_ENABLED=True), PAD=SimpleNamespace(_attempted=False),
            list_camera_contexts=lambda actor: [{'camera_id': 5, 'enabled': True}, {'camera_id': 6, 'enabled': True}],
            AI_RUNTIME=SimpleNamespace(camera_state=lambda cid: {'ai_state': 'DISABLED', 'reason_code': 'private diagnostic'}),
            FLEET_V4=SimpleNamespace(get=lambda cid: None), RECORDER_V4=SimpleNamespace(camera_status=lambda cid: {'active': False, 'error': 'secret'}))
        rows = ns['_public_camera_states'](self.user)
        self.assertEqual([row['connection_state'] for row in rows], ['ONLINE', 'UNKNOWN'])
        self.assertEqual(rows[0]['pad_state'], 'PENDING')
        self.assertNotIn('secret', json.dumps(rows))
        self.assertEqual(rows[0]['reason_code'], '')

    def test_dashboard_scopes_sql_before_serialization_and_filters_camera_total(self):
        captured = []
        ns = route_functions({'dashboard_summary'},
            _auth_permission=lambda *args: self.user, scoped_store_ids=self.scope, has_permission=lambda *args: False,
            query_management_summary=lambda **kwargs: captured.append(kwargs) or {'latest': [{'id': 7}], 'visits': {}},
            _public_camera_states=lambda actor: [{'camera_id': 5, 'store_id': 1, 'online': True}, {'camera_id': 6, 'store_id': 2, 'online': None}],
            _recognition_public_row=lambda row, **kwargs: {'event_id': row['id']}, _visit_runtime_readiness=lambda report, cameras: report)
        report = ns['dashboard_summary'](object(), store_id=1)
        self.assertEqual(captured, [{'allowed_store_ids': frozenset([1]), 'store_id': 1}])
        self.assertEqual(report['cameras'], {'total': 1, 'online': 1, 'unknown': 0})
        self.assertEqual(report['latest'], [{'event_id': 7}])


class MobileHistoryCompatibilityTests(unittest.TestCase):
    def test_mobile_readers_require_viewer_without_portal_permission_or_capability(self):
        ns = route_functions({'mobile_recognition_history', 'mobile_hr_history'}, _request_mobile_user=lambda request: None)
        for name in ('mobile_recognition_history', 'mobile_hr_history'):
            with self.subTest(name=name), self.assertRaises(HTTPException) as raised:
                ns[name](object())
            self.assertEqual(raised.exception.status_code, 401)

    def test_recognition_uses_safe_rows_without_calling_desktop_auth_route(self):
        queries = []
        ns = route_functions({'mobile_recognition_history'}, _request_mobile_user=lambda request: {'kind': 'MOBILE_VIEWER'},
            query_recognition_history=lambda *args, **kwargs: queries.append((args, kwargs)) or {'items': [{'id': 1, 'camera_source': 'private'}]},
            _recognition_public_row=lambda row: {'event_at': '2026-10-08', 'status': 'UNREGISTERED', 'confidence': .3}, utc_now=lambda: 'now')
        result = ns['mobile_recognition_history'](object(), limit=9999)
        self.assertEqual(queries[0][1]['limit'], 200)
        self.assertEqual(result['items'][0]['full_name'], 'Chưa xác định')
        self.assertEqual(result['items'][0]['status'], 'WARNING')
        self.assertNotIn('private', json.dumps(result))

    def test_hr_mobile_excludes_camera_loss_and_internal_diagnostics(self):
        rows = [{'event_type': 'PRESENCE_END', 'detail': {'reason': 'CAMERA_NOT_VISIBLE'}},
                {'event_type': 'TRACK_UPDATE'}, {'event_type': 'EXIT', 'full_name': 'Nhân viên', 'reason': 'decoder diagnostic'}]
        ns = route_functions({'mobile_hr_history'}, _request_mobile_user=lambda request: {'kind': 'MOBILE_VIEWER'},
            hr_event_history=lambda limit: rows, utc_now=lambda: 'now')
        result = ns['mobile_hr_history'](object())
        self.assertEqual([row['event_type'] for row in result['items']], ['EXIT'])
        self.assertNotIn('diagnostic', json.dumps(result))


class LegacyObservationScopeTests(unittest.TestCase):
    def test_restricted_account_never_reads_unattributed_legacy_rows(self):
        ns = route_functions({'visitors_list'}, _auth_permission=lambda *args: {'role': 'MANAGER'},
            scoped_store_ids=lambda actor: frozenset([1]),
            visitor_sessions=lambda **kwargs: self.fail('Global observations must not be fetched'))
        result = ns['visitors_list'](object())
        self.assertEqual(result, {'items': [], 'coverage': 'LEGACY_UNATTRIBUTED'})

    def test_details_review_and_shots_are_denied_before_reading_legacy_evidence(self):
        ns = route_functions({'_legacy_visitor_scope', 'visitors_detail', 'visitors_review', 'visitors_shot'},
            VisitorReviewPayload=object, _auth_permission=lambda *args: {'role': 'MANAGER'},
            scoped_store_ids=lambda actor: frozenset([1]),
            visitor_session=lambda *args: self.fail('Unattributed detail read'),
            visitor_shot_path=lambda *args: self.fail('Unattributed image read'),
            review_visitor_session=lambda *args, **kwargs: self.fail('Unattributed review'))
        calls = [('visitors_detail', ('session', object())), ('visitors_review', ('session', object(), object())),
                 ('visitors_shot', ('session', 1, object()))]
        for name, args in calls:
            with self.subTest(name=name), self.assertRaises(HTTPException) as raised:
                ns[name](*args)
            self.assertEqual(raised.exception.status_code, 403)

    def test_owner_observations_allowlist_hides_sources_paths_and_internal_reasons(self):
        raw = {'session_code': 'V-demo', 'status': 'ACTIVE', 'visitor_type': 'UNKNOWN',
            'camera_source': 'rtsp://fixture-user:fixture-password@192.0.2.9/fixture',
            'close_reason': 'TRACK_LOST', 'relative_path': 'private/evidence.jpg', 'label': 'Quan sát',
            'best_shots': [{'rank': 1, 'snapshot_url': 'https://wrong.invalid/secret',
                'relative_path': 'private.jpg', 'video': {'url': 'rtsp://secret'}, 'quality': .8}]}
        ns = route_functions({'_public_visitor_observation', 'visitors_list'}, re=re,
            _auth_permission=lambda *args: {'role': 'ADMIN'}, scoped_store_ids=lambda actor: None,
            visitor_sessions=lambda **kwargs: [raw])
        result = ns['visitors_list'](object())
        row = result['items'][0]
        self.assertEqual(row['measure'], 'OBSERVATION_SESSION')
        self.assertEqual(row['camera_name'], '')
        self.assertEqual(row['best_shots'][0]['snapshot_url'], '/api/v1/visitors/V-demo/shots/1.jpg')
        for secret in ('fixture-password', '192.0.2.9', 'private', 'TRACK_LOST', 'wrong.invalid', 'rtsp:'):
            self.assertNotIn(secret, json.dumps(result))


class PreviewSocketScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreign_store_socket_is_rejected_before_accept_or_first_frame(self):
        closed = []
        async def close(**kwargs): closed.append(kwargs['code'])
        async def accept(): self.fail('Foreign store preview accepted')
        async def threadpool(call, *args): return call(*args)
        def denied(*args): raise HTTPException(403, 'Denied store')
        ws = SimpleNamespace(query_params={'camera_id': '5'}, close=close, accept=accept)
        ns = route_functions({'media_preview_ws'}, run_in_threadpool=threadpool,
            _websocket_user=lambda ws: {'role': 'MANAGER', 'store_id': 1}, _camera_scope_context=denied)
        await ns['media_preview_ws'](ws)
        self.assertEqual(closed, [4403])

    async def test_revoked_socket_session_closes_without_another_frame(self):
        closed, sent, reads = [], [], []
        async def close(**kwargs): closed.append(kwargs['code'])
        async def accept(): pass
        async def threadpool(call, *args): return call(*args)
        def user(ws):
            reads.append(1)
            return {'role': 'MANAGER', 'store_id': 1} if len(reads) == 1 else None
        ws = SimpleNamespace(query_params={'camera_id': '5'}, close=close, accept=accept)
        ns = route_functions({'media_preview_ws'}, run_in_threadpool=threadpool,
            _websocket_user=user, _camera_scope_context=lambda *args: {'store_id': 1},
            _require_active_media_camera=lambda cid: '0', asyncio=asyncio,
            time=SimpleNamespace(monotonic=lambda: 1), WebSocketDisconnect=type('WebSocketDisconnect', (Exception,), {}),
            CAMERA=SimpleNamespace(latest_observation_packet=lambda: sent.append('read') or (b'frame', 1, 1)))
        await ns['media_preview_ws'](ws)
        self.assertEqual(closed, [4401])
        self.assertEqual(sent, [])


if __name__ == '__main__':
    unittest.main()
