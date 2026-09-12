"""离线验证导入边界；不读取真实凭据、不连接Apifox、不修改远端数据。"""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import shutil

HOST_NODE = shutil.which("node")
import unittest
from unittest.mock import patch

import apifox


class ApifoxImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / 'api.json'
        self.file.write_text(json.dumps({'openapi': '3.0.3', 'info': {'title': 'test', 'version': '1'},
                                        'paths': {'/x': {'post': {'responses': {'200': {'description': 'ok'}}}}}}))
        self.args = ['import', '--project-id', '123', '--folder-id', '456', '--file', str(self.file),
                     '--endpoint', 'POST', '/x']
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def invoke(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = apifox.main(args)
        return code, json.loads(output.getvalue())

    def test_preview_needs_no_token_and_makes_no_network_request(self):
        with patch.object(apifox.urllib.request.OpenerDirector, 'open') as network:
            code, result = self.invoke(self.args)
        self.assertEqual(0, code)
        self.assertEqual('PREVIEW', result['status'])
        self.assertEqual([['POST', '/x']], result['endpoints'])
        self.assertEqual('OVERWRITE_EXISTING', result['options']['endpointOverwriteBehavior'])
        self.assertEqual('KEEP_EXISTING', result['options']['schemaOverwriteBehavior'])
        network.assert_not_called()

    def test_apply_requires_environment_token_without_fallback(self):
        with patch.object(apifox.subprocess, 'run') as process, patch.object(apifox.urllib.request.OpenerDirector, 'open') as network:
            code, result = self.invoke(self.args + ['--apply'])
        self.assertEqual(1, code)
        self.assertIn('APIFOX_ACCESS_TOKEN', result['message'])
        process.assert_not_called()
        network.assert_not_called()

    def test_extra_endpoint_is_rejected_before_writing(self):
        doc = json.loads(self.file.read_text())
        doc['paths']['/unrelated'] = {'delete': {}}
        self.file.write_text(json.dumps(doc))
        with patch.object(apifox.urllib.request.OpenerDirector, 'open') as network:
            code, result = self.invoke(self.args + ['--apply'])
        self.assertEqual(1, code)
        self.assertIn('--endpoint', result['message'])
        network.assert_not_called()

    def test_apply_uses_bearer_once_and_requires_readback(self):
        os.environ['APIFOX_ACCESS_TOKEN'] = 'unit-only-token'
        response = io.BytesIO(json.dumps({'data': {'counters': {'endpointCreated': 1}}}).encode())
        with patch.object(apifox.urllib.request.OpenerDirector, 'open', return_value=response) as network:
            code, result = self.invoke(self.args + ['--apply'])
        self.assertEqual(0, code)
        self.assertTrue(result['requiresReadback'])
        self.assertEqual('IMPORT_RESPONSE', result['status'])
        self.assertEqual(1, network.call_count)
        request = network.call_args.args[0]
        self.assertEqual('Bearer unit-only-token', request.get_header('Authorization'))
        self.assertEqual(456, json.loads(request.data)['options']['targetEndpointFolderId'])
        self.assertNotIn('unit-only-token', json.dumps(result))

    def test_timeout_is_unknown_and_never_retried(self):
        os.environ['APIFOX_ACCESS_TOKEN'] = 'unit-only-token'
        with patch.object(apifox.urllib.request.OpenerDirector, 'open', side_effect=TimeoutError) as network:
            code, result = self.invoke(self.args + ['--apply'])
        self.assertEqual(2, code)
        self.assertEqual('RESULT_UNKNOWN', result['status'])
        self.assertTrue(result['requiresReadback'])
        self.assertEqual(1, network.call_count)

    def test_cli_token_stays_out_of_command_line_and_output(self):
        os.environ['APIFOX_ACCESS_TOKEN'] = 'unit-only-token'
        entry = Path(self.temp.name) / 'cli.js'
        entry.write_text('')
        completed = type('Result', (), {'returncode': 0, 'stdout': '{"data":"unit-only-token"}'})()
        with patch.object(apifox.shutil, 'which', return_value='/usr/bin/node'), patch.object(apifox.subprocess, 'run', return_value=completed) as process:
            code, result = self.invoke(['cli', '--cli-js', str(entry), '--', 'project', 'list'])
        self.assertEqual(0, code)
        self.assertNotIn('unit-only-token', json.dumps(process.call_args.args[0]))
        self.assertNotIn('unit-only-token', json.dumps(result))
        self.assertEqual('unit-only-token', process.call_args.kwargs['env']['APIFOX_ACCESS_TOKEN'])

    def test_partial_import_is_not_a_successful_exit(self):
        os.environ['APIFOX_ACCESS_TOKEN'] = 'unit-only-token'
        response = io.BytesIO(json.dumps({'data': {'counters': {'endpointCreated': 0, 'endpointFailed': 1}}}).encode())
        with patch.object(apifox.urllib.request.OpenerDirector, 'open', return_value=response) as network:
            code, result = self.invoke(self.args + ['--apply'])
        self.assertEqual(2, code)
        self.assertEqual('IMPORT_PARTIAL', result['status'])
        self.assertTrue(result['requiresReadback'])
        self.assertEqual(1, network.call_count)

    def test_project_discovery_can_filter_large_lists(self):
        os.environ['APIFOX_ACCESS_TOKEN'] = 'unit-only-token'
        entry = Path(self.temp.name) / 'cli.js'
        entry.write_text('')
        completed = type('Result', (), {'returncode': 0, 'stdout': json.dumps({
            'data': [{'id': 1, 'name': 'service-a'}, {'id': 2, 'name': 'service-b'}]})})()
        with patch.object(apifox.shutil, 'which', return_value='/usr/bin/node'), patch.object(apifox.subprocess, 'run', return_value=completed):
            code, result = self.invoke(['cli', '--cli-js', str(entry), '--name-contains', 'service-b', '--', 'project', 'list'])
        self.assertEqual(0, code)
        self.assertEqual([{'id': 2, 'name': 'service-b'}], result['result']['data'])

    def test_cli_mutation_is_rejected(self):
        with patch.object(apifox.subprocess, 'run') as process:
            code, result = self.invoke(['cli', '--', 'endpoint', 'delete', '123', '--project', '123'])
        self.assertEqual(1, code)
        process.assert_not_called()

    def definition_command(self):
        self.case_file = Path(self.temp.name) / 'case.json'
        self.case_file.write_text(json.dumps({'name': 'case', 'apiDetailId': 20, 'categoryId': 30,
            'method': 'post', 'path': '/x', 'parameters': {'path': [], 'query': [], 'header': [], 'cookie': []},
            'commonParameters': {}, 'requestBody': {'type': 'application/json', 'data': '{}'}}))
        return ['test-case', 'create', '--project', '123', '--branch', 'ai/test', '--file', str(self.case_file)]

    def test_definition_preview_does_not_need_credentials_or_cli(self):
        command = self.definition_command()
        with patch.object(apifox.subprocess, 'run') as process:
            code, result = self.invoke(['cli', '--', *command])
        self.assertEqual(0, code)
        self.assertEqual('PREVIEW', result['status'])
        self.assertEqual('test-case-create', result['schemaKey'])
        self.assertFalse(result['testsExecuted'])
        process.assert_not_called()

    def test_execution_and_merging_are_always_rejected(self):
        for command in (['test-case', 'run', '1'], ['test-scenario', 'run', '1'],
                        ['run', '-t', '1'], ['branch', 'merge'], ['auth', 'login']):
            with self.subTest(command=command), patch.object(apifox.subprocess, 'run') as process:
                code, result = self.invoke(['cli', '--apply', '--', *command])
                self.assertEqual(1, code)
                process.assert_not_called()

    def test_placeholder_resource_ids_cannot_be_linked(self):
        with patch.object(apifox.subprocess, 'run') as process:
            code, result = self.invoke(['cli', '--apply', '--', 'test-scenario', 'import-steps', 'SCENARIO_ID',
                                       '--project', '123', '--branch', 'ai/test', '--source', 'test-case',
                                       '--endpoint', '20', '--ids', 'CASE_ID'])
        self.assertEqual(1, code)
        self.assertIn('占位ID', result['message'])
        process.assert_not_called()

    def test_definition_requires_explicit_project_and_branch(self):
        command = self.definition_command()
        for flag in ('--project', '--branch'):
            invalid = command.copy(); i = invalid.index(flag); del invalid[i:i+2]
            with self.subTest(flag=flag), patch.object(apifox.subprocess, 'run') as process:
                code, result = self.invoke(['cli', '--', *invalid])
                self.assertEqual(1, code)
                process.assert_not_called()

    def test_definition_validates_before_single_write(self):
        command = self.definition_command(); os.environ['APIFOX_ACCESS_TOKEN'] = 'unit-only-token'
        entry = Path(self.temp.name) / 'cli.js'; entry.write_text('')
        result = lambda text: type('Result', (), {'returncode': 0, 'stdout': text})()
        responses = [result('{"success":true,"data":{"valid":true}}'),
                     result('提示：请回查\n{"success":true,"data":{"id":456}}')]
        with patch.object(apifox.shutil, 'which', return_value='/usr/bin/node'), patch.object(apifox.subprocess, 'run', side_effect=responses) as process:
            code, data = self.invoke(['cli', '--cli-js', str(entry), '--apply', '--', *command])
        self.assertEqual(0, code)
        self.assertEqual('WRITE_RESPONSE', data['status'])
        self.assertTrue(data['requiresReadback'])
        self.assertFalse(data['testsExecuted'])
        self.assertEqual(2, process.call_count)
        self.assertNotIn('APIFOX_ACCESS_TOKEN', process.call_args_list[0].kwargs['env'])

    def test_schema_failure_prevents_definition_write(self):
        command = self.definition_command(); os.environ['APIFOX_ACCESS_TOKEN'] = 'unit-only-token'
        entry = Path(self.temp.name) / 'cli.js'; entry.write_text('')
        invalid = type('Result', (), {'returncode': 1, 'stdout': '{"success":false,"data":{"valid":false}}'})()
        with patch.object(apifox.shutil, 'which', return_value='/usr/bin/node'), patch.object(apifox.subprocess, 'run', return_value=invalid) as process:
            code, data = self.invoke(['cli', '--cli-js', str(entry), '--apply', '--', *command])
        self.assertEqual(2, code)
        self.assertEqual('VALIDATION_FAILED', data['status'])
        self.assertEqual(1, process.call_count)

    def test_definition_timeout_is_unknown_without_retry(self):
        command = self.definition_command(); os.environ['APIFOX_ACCESS_TOKEN'] = 'unit-only-token'
        entry = Path(self.temp.name) / 'cli.js'; entry.write_text('')
        valid = type('Result', (), {'returncode': 0, 'stdout': '{"success":true,"data":{"valid":true}}'})()
        with patch.object(apifox.shutil, 'which', return_value='/usr/bin/node'), patch.object(apifox.subprocess, 'run', side_effect=[valid, apifox.subprocess.TimeoutExpired('node', 60)]) as process:
            code, data = self.invoke(['cli', '--cli-js', str(entry), '--apply', '--', *command])
        self.assertEqual(2, code)
        self.assertEqual('RESULT_UNKNOWN', data['status'])
        self.assertTrue(data['requiresReadback'])
        self.assertEqual(2, process.call_count)

    @unittest.skipUnless(HOST_NODE, 'Node required for local stdout regression')
    def test_large_cli_read_is_not_truncated(self):
        os.environ['APIFOX_ACCESS_TOKEN'] = 'unit-only-token'
        entry = Path(self.temp.name) / 'cli.js'
        entry.write_text('console.log(JSON.stringify({success:true,data:{text:"x".repeat(200000)}}));process.exit(0);')
        with patch.object(apifox.shutil, 'which', side_effect=lambda name: HOST_NODE if name == 'node' else None):
            code, data = self.invoke(['cli', '--cli-js', str(entry), '--', 'test-scenario', 'get', '1', '--project', '123'])
        self.assertEqual(0, code)
        self.assertEqual(200000, len(data['result']['data']['text']))

    @unittest.skipUnless(HOST_NODE, 'Node required for local CLI exit regression')
    def test_write_retains_cli_immediate_exit_guard(self):
        command = self.definition_command(); os.environ['APIFOX_ACCESS_TOKEN'] = 'unit-only-token'
        entry = Path(self.temp.name) / 'cli.js'; forbidden = Path(self.temp.name) / 'must-not-write'
        entry.write_text('if(process.argv[2]==="cli-schema"){console.log(JSON.stringify({success:true,data:{valid:true}}));}'
                         'else{console.log(JSON.stringify({success:false,error:{message:"Automation caller branch required"}}));'
                         'process.exit(1);require("fs").writeFileSync(' + json.dumps(str(forbidden)) + ',"bad");}')
        with patch.object(apifox.shutil, 'which', side_effect=lambda name: HOST_NODE if name == 'node' else None):
            code, data = self.invoke(['cli', '--cli-js', str(entry), '--apply', '--', *command])
        self.assertEqual(2, code)
        self.assertEqual('WRITE_REJECTED', data['status'])
        self.assertFalse(forbidden.exists())


if __name__ == '__main__':
    unittest.main()
