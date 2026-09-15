import importlib.util
import json
import pathlib
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from zentao_common import ZentaoClient

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
    assert [item['id'] for item in plan['leaf_modules']] == [11]


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
