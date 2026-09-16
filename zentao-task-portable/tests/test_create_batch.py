import importlib.util
import io
import json
import pathlib
import sys
import tempfile
from contextlib import redirect_stdout
from unittest.mock import patch

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from zentao_common import ZentaoClient, ZentaoError, ZentaoWriteOutcomeUnknown

SPEC = importlib.util.spec_from_file_location('zentao_create', SCRIPTS / 'zentao-create-task-refactored.py')
CREATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CREATE)


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class Session:
    def get(self, _url, timeout):
        return Response({'data': json.dumps({'tasks': {
            '1': {'name': '任务 A', 'module': '10', 'assignedTo': 'alice'},
            '2': {'name': '任务 A-补充', 'module': '10', 'assignedTo': 'alice'},
        }})})


class CreationResponse:
    status_code = 200
    text = '''
        <select name="module"><option value="0">/</option><option value="11">/服务/行车</option></select>
        <select name="assignedTo[]"><option value="zhangbin">Z:张斌</option></select>
    '''


class CreationSession:
    def get(self, _url, timeout):
        return CreationResponse()


class FakeClient:
    base_url = 'https://example.test'

    def __init__(self):
        self.created = []
        self.verified = []
        self.screenshot_calls = 0

    def login_with_available_credentials(self):
        return True

    def get_project_info(self, _project_id):
        return {'id': 1681, 'name': '我的日志', 'status': 'doing'}

    def get_task_creation_options(self, _project_id):
        return {'modules': [{'id': 10, 'name': '/父'}, {'id': 11, 'name': '/父/子'}],
                'assignees': [{'account': 'alice', 'name': 'A:Alice'}]}

    def verify_task_created(self, _project_id, name, exact=False):
        self.verified.append((name, exact))
        return {'id': 8, 'name': name} if self.created else None

    def create_task(self, project_id, name, **kwargs):
        self.created.append((project_id, name, kwargs))

    def get_task_detail(self, _task_id):
        _, _, task = self.created[0]
        return {'project': '1681', 'module': str(task['module']), 'assignedTo': task['assigned_to'],
                'type': task['task_type'], 'estimate': task['estimate'], 'left': task['estimate'],
                'raw_fields': {'estStarted': task['begin'], 'deadline': task['end']}}

    def screenshot_task_list(self):
        self.screenshot_calls += 1
        return '/tmp/zentao-task-list.png'


def run_cli_args(client, argv):
    class ClientFactory:
        @staticmethod
        def detect_service_from_text(_text):
            return client.base_url

        def __new__(cls, _url):
            return client

    output = io.StringIO()
    with patch.object(CREATE, 'ZentaoClient', ClientFactory), \
            patch.object(sys, 'argv', argv), redirect_stdout(output):
        exit_code = CREATE.main()
    return exit_code, output.getvalue()


def run_cli(client, batch, dry_run=True, approved=True):
    with tempfile.NamedTemporaryFile('w', suffix='.json', encoding='utf-8') as handle:
        json.dump(batch, handle, ensure_ascii=False)
        handle.flush()
        option = '--approved-plan' if approved and not dry_run else '--batch-json'
        argv = ['zentao-create-task-refactored.py', option, handle.name]
        if dry_run:
            argv.append('--dry-run')
        return run_cli_args(client, argv)


def test_exact_create_verification_does_not_reuse_similar_task():
    client = ZentaoClient('https://example.test')
    client._logged_in = True
    client.session = Session()

    assert client.verify_task_created(1681, '任务 A') == {'id': '1', 'name': '任务 A', 'module': '10', 'assignedTo': 'alice'}
    assert client.verify_task_created(1681, '任务 A-补充', exact=True) == {
        'id': '2', 'name': '任务 A-补充', 'module': '10', 'assignedTo': 'alice'
    }


def test_creation_options_extracts_non_numeric_assignee_account():
    client = ZentaoClient('https://example.test')
    client._logged_in = True
    client.session = CreationSession()

    assert client.get_task_creation_options(1681) == {
        'modules': [{'id': 11, 'name': '/服务/行车'}],
        'assignees': [{'account': 'zhangbin', 'name': 'Z:张斌'}],
    }


def test_dry_run_preflight_has_no_create_call():
    client = FakeClient()
    batch = {'project_id': 1681, 'tasks': [{'name': '任务 A', 'module': 11, 'assigned_to': 'alice',
                                             'estimate': '2', 'task_type': 'devel',
                                             'begin': '2026-09-01', 'end': '2026-09-10', 'desc': ''}]}

    plan = CREATE.preflight_batch(client, batch)

    assert client.created == []
    assert plan['tasks'][0]['module_name'] == '/父/子'
    assert plan['tasks'][0]['assignee_name'] == 'A:Alice'


def test_batch_create_uses_keyword_fields_and_reads_back_left_hours():
    client = FakeClient()
    task = {'name': '任务 A', 'module': 11, 'assigned_to': 'alice', 'estimate': '2', 'task_type': 'devel',
            'begin': '2026-09-01', 'end': '2026-09-10', 'desc': '含数据示例：状态=异常'}

    result = CREATE.create_and_verify(client, 1681, task)

    assert client.created == [(1681, '任务 A', {
        'module': 11, 'assigned_to': 'alice', 'task_type': 'devel', 'estimate': '2',
        'begin': '2026-09-01', 'end': '2026-09-10', 'desc': '含数据示例：状态=异常'
    })]
    assert client.verified == [('任务 A', True), ('任务 A', True)]
    assert result['left'] == '2'


def test_cli_dry_run_returns_compact_confirmation_without_writes():
    client = FakeClient()
    batch = {'project_id': 1681, 'user_text': '田一禅道', 'tasks': [
        {'name': '任务 A', 'module': 11, 'assigned_to': 'alice', 'estimate': 2}
    ]}

    exit_code, raw_output = run_cli(client, batch)

    payload = json.loads(raw_output)
    assert exit_code == 0
    assert client.created == []
    assert 'leaf_modules' not in payload
    assert payload['tasks'][0]['module_name'] == '/父/子'
    assert payload['tasks'][0]['assignee_name'] == 'A:Alice'
    assert payload['tasks'][0]['begin'] == CREATE.default_dates()['begin']
    assert payload['tasks'][0]['end'] == CREATE.default_dates()['end']


def test_cli_dry_run_fails_closed_when_assignee_options_are_unavailable():
    client = FakeClient()
    client.get_task_creation_options = lambda _project_id: {
        'modules': [{'id': 11, 'name': '/父/子'}], 'assignees': []
    }
    batch = {'project_id': 1681, 'user_text': '田一禅道', 'tasks': [
        {'name': '任务 A', 'module': 11, 'assigned_to': 'alice', 'estimate': 2}
    ]}

    exit_code, raw_output = run_cli(client, batch)

    assert exit_code == 1
    assert client.created == []
    assert '负责人列表不可用' in raw_output


def test_cli_dry_run_resolves_unique_project_module_and_assignee_names():
    assert ZentaoClient.detect_service_from_text('田一禅道') == 'https://tycd.tygps.com'
    client = FakeClient()
    client.get_projects = lambda: [{'id': 1681, 'name': '我的日志'}]
    client.get_task_creation_options = lambda _project_id: {
        'modules': [{'id': 9701, 'name': '/服务和工单/行车记录'}],
        'assignees': [{'account': 'chenye', 'name': 'C:陈烨'}],
    }
    batch = {'project': '我的日志项目', 'user_text': '田一禅道', 'tasks': [
        {'name': '任务 A', 'module': '行车模块', 'assigned_to': '陈烨', 'estimate': 2}
    ]}

    exit_code, raw_output = run_cli(client, batch)

    payload = json.loads(raw_output)
    assert exit_code == 0
    assert client.created == []
    assert payload['project']['id'] == 1681
    assert payload['tasks'][0]['module'] == 9701
    assert payload['tasks'][0]['module_name'] == '/服务和工单/行车记录'
    assert payload['tasks'][0]['assigned_to'] == 'chenye'
    assert payload['tasks'][0]['assignee_name'] == 'C:陈烨'


def test_cli_dry_run_returns_compact_module_ambiguity_without_writes():
    client = FakeClient()
    client.get_task_creation_options = lambda _project_id: {
        'modules': [
            {'id': 9701, 'name': '/服务和工单/行车记录'},
            {'id': 9702, 'name': '/服务和工单/行车报表'},
            {'id': 9703, 'name': '/APP/Web 我的日志'},
        ],
        'assignees': [{'account': 'chenye', 'name': 'C:陈烨'}],
    }
    batch = {'project_id': 1681, 'user_text': '田一禅道', 'tasks': [
        {'name': '任务 A', 'module': '行车模块', 'assigned_to': '陈烨', 'estimate': 2}
    ]}

    exit_code, raw_output = run_cli(client, batch)

    payload = json.loads(raw_output)
    assert exit_code == 0
    assert client.created == []
    assert payload['status'] == 'needs_confirmation'
    assert payload['ambiguities'] == [{
        'task': '任务 A',
        'field': 'module',
        'input': '行车模块',
        'candidates': [
            {'id': 9701, 'name': '/服务和工单/行车记录'},
            {'id': 9702, 'name': '/服务和工单/行车报表'},
        ],
    }]


def make_approved_plan():
    return {
        'dry_run': True,
        'plan_version': 1,
        'status': 'ready',
        'service': 'https://tycd.tygps.com',
        'project': {'id': 1681, 'name': '我的日志', 'status': 'doing'},
        'tasks': [{
            'name': '任务 A', 'module': 11, 'module_name': '/父/子',
            'assigned_to': 'alice', 'assignee_name': 'A:Alice',
            'estimate': '2', 'task_type': 'devel',
            'begin': '2026-09-01', 'end': '2026-09-10', 'desc': '',
        }],
    }


def test_cli_executes_an_approved_preflight_plan_in_one_call():
    client = FakeClient()
    approved_plan = make_approved_plan()

    exit_code, raw_output = run_cli(client, approved_plan, dry_run=False)

    payload = json.loads(raw_output)
    assert exit_code == 0
    assert len(client.created) == 1
    assert payload['dry_run'] is False
    assert payload['tasks'][0]['source'] == 'created'
    assert payload['tasks'][0]['project'] == '1681'
    assert payload['tasks'][0]['left'] == '2'
    assert payload['screenshot'] == '/tmp/zentao-task-list.png'
    assert client.screenshot_calls == 1


def test_cli_recovers_a_timed_out_create_before_retrying():
    class UncertainClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.verify_count = 0

        def verify_task_created(self, _project_id, name, exact=False):
            self.verify_count += 1
            if self.verify_count == 1:
                return None
            return {'id': 9, 'name': name}

        def create_task(self, project_id, name, **kwargs):
            self.created.append((project_id, name, kwargs))
            raise ZentaoWriteOutcomeUnknown('创建请求结果未知: read timed out')

    client = UncertainClient()

    exit_code, raw_output = run_cli(client, make_approved_plan(), dry_run=False)

    payload = json.loads(raw_output)
    assert exit_code == 0
    assert len(client.created) == 1
    assert client.verify_count == 2
    assert payload['tasks'][0]['source'] == 'recovered'
    assert payload['tasks'][0]['id'] == 9


def test_cli_reuses_an_exact_existing_task_without_creating():
    class ExistingClient(FakeClient):
        def verify_task_created(self, _project_id, name, exact=False):
            self.verified.append((name, exact))
            return {'id': 10, 'name': name}

        def create_task(self, _project_id, _name, **_kwargs):
            raise AssertionError('不应创建已存在的精确同名任务')

        def get_task_detail(self, _task_id):
            task = make_approved_plan()['tasks'][0]
            return {
                'project': '1681', 'module': str(task['module']), 'assignedTo': task['assigned_to'],
                'type': task['task_type'], 'estimate': task['estimate'], 'left': task['estimate'],
                'raw_fields': {'estStarted': task['begin'], 'deadline': task['end']},
            }

    client = ExistingClient()

    exit_code, raw_output = run_cli(client, make_approved_plan(), dry_run=False)

    payload = json.loads(raw_output)
    assert exit_code == 0
    assert client.created == []
    assert client.verified == [('任务 A', True)]
    assert payload['tasks'][0]['source'] == 'reused'
    assert client.screenshot_calls == 1


def test_cli_stops_when_created_task_fails_read_back_verification():
    class MismatchClient(FakeClient):
        def get_task_detail(self, task_id):
            detail = super().get_task_detail(task_id)
            detail['left'] = '99'
            return detail

    client = MismatchClient()

    exit_code, raw_output = run_cli(client, make_approved_plan(), dry_run=False)

    assert exit_code == 1
    assert len(client.created) == 1
    assert '读回验证失败' in raw_output
    assert client.screenshot_calls == 0


def test_cli_does_not_recover_a_definite_create_failure():
    class DefiniteFailureClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.verify_count = 0

        def verify_task_created(self, _project_id, name, exact=False):
            self.verify_count += 1
            return None if self.verify_count == 1 else {'id': 12, 'name': name}

        def create_task(self, _project_id, _name, **_kwargs):
            raise ZentaoError('创建任务失败: 模块无效')

    client = DefiniteFailureClient()

    exit_code, raw_output = run_cli(client, make_approved_plan(), dry_run=False)

    assert exit_code == 1
    assert client.verify_count == 1
    assert '模块无效' in raw_output
    assert 'recovered' not in raw_output


def test_cli_rejects_an_unversioned_approved_plan():
    client = FakeClient()
    plan = make_approved_plan()
    del plan['plan_version']

    exit_code, raw_output = run_cli(client, plan, dry_run=False)

    assert exit_code == 1
    assert client.created == []
    assert '批准计划格式无效' in raw_output


def test_cli_rejects_approved_plan_when_assignee_account_is_stale():
    client = FakeClient()
    client.get_task_creation_options = lambda _project_id: {
        'modules': [{'id': 11, 'name': '/父/子'}],
        'assignees': [{'account': 'alice2', 'name': 'A:Alice'}],
    }

    exit_code, raw_output = run_cli(client, make_approved_plan(), dry_run=False)

    assert exit_code == 1
    assert client.created == []
    assert '批准计划负责人已失效' in raw_output


def test_cli_rejects_approved_plan_without_numeric_project_and_module_ids():
    client = FakeClient()
    client.get_projects = lambda: [{'id': 1681, 'name': '我的日志'}]
    plan = make_approved_plan()
    plan['project'] = {'name': '我的日志', 'status': 'doing'}
    plan['tasks'][0]['module'] = '/父/子'

    exit_code, raw_output = run_cli(client, plan, dry_run=False)

    assert exit_code == 1
    assert client.created == []
    assert '批准计划格式无效' in raw_output


def test_cli_keeps_legacy_batch_json_execution_compatible():
    client = FakeClient()
    batch = {'project_id': 1681, 'user_text': '田一禅道', 'tasks': [
        {'name': '任务 A', 'module': 11, 'assigned_to': 'alice', 'estimate': 2,
         'begin': '2026-09-01', 'end': '2026-09-10'}
    ]}

    exit_code, raw_output = run_cli(client, batch, dry_run=False, approved=False)

    payload = json.loads(raw_output)
    assert exit_code == 0
    assert payload['tasks'][0]['source'] == 'created'
    assert payload['tasks'][0]['left'] == '2'
    assert client.screenshot_calls == 1


def test_cli_keeps_legacy_positional_execution_compatible():
    client = FakeClient()
    argv = [
        'zentao-create-task-refactored.py', '1681', '任务 A', '11',
        'alice', 'devel', '2', '2026-09-01', '2026-09-10',
    ]

    exit_code, raw_output = run_cli_args(client, argv)

    payload = json.loads(raw_output)
    assert exit_code == 0
    assert payload['tasks'][0]['source'] == 'created'
    assert payload['tasks'][0]['assignedTo'] == 'alice'
    assert client.screenshot_calls == 1


def test_named_request_uses_one_preflight_then_one_approved_execution():
    client = FakeClient()
    client.get_projects = lambda: [{'id': 1681, 'name': '我的日志'}]
    client.get_task_creation_options = lambda _project_id: {
        'modules': [{'id': 9701, 'name': '/服务和工单/行车记录'}],
        'assignees': [{'account': 'chenye', 'name': 'C:陈烨'}],
    }
    request = {'project': '我的日志项目', 'user_text': '田一禅道', 'tasks': [
        {'name': '行车状态字段', 'module': '行车模块', 'assigned_to': '陈烨', 'estimate': 2}
    ]}

    preflight_code, preflight_output = run_cli(client, request, dry_run=True)
    approved_plan = json.loads(preflight_output)
    execute_code, execute_output = run_cli(client, approved_plan, dry_run=False)

    result = json.loads(execute_output)
    assert preflight_code == execute_code == 0
    assert approved_plan['status'] == 'ready'
    assert len(client.created) == 1
    assert result['tasks'][0]['name'] == '行车状态字段'
    assert result['tasks'][0]['assignedTo'] == 'chenye'
    assert client.screenshot_calls == 1
