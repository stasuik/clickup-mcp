import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import clickup_agent as api
import clickup_mcp_server as server


class IntegrationTests(unittest.TestCase):
    def test_stdio_handshake(self):
        messages = [{'jsonrpc':'2.0','id':1,'method':'initialize'},
                    {'jsonrpc':'2.0','method':'notifications/initialized'},
                    {'jsonrpc':'2.0','id':2,'method':'tools/list'}]
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, CLICKUP_CONFIG_DIR=directory, CLICKUP_ENV_FILE=directory+'/.env')
            result = subprocess.run([sys.executable, 'clickup_mcp_server.py'],
                input=''.join(json.dumps(m)+'\n' for m in messages), capture_output=True, text=True, env=env, check=True)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r['id'] for r in replies], [1, 2])
        self.assertEqual(len(replies[1]['result']['tools']), 5)

    def test_explicit_config_and_environment_priority(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'CLICKUP_TEAM_ID':'existing'}, clear=True):
            path = Path(directory)/'.env'
            path.write_text('CLICKUP_TEAM_ID=file\nCLICKUP_LOOKAHEAD_DAYS=7\n')
            api.load_env(path)
            self.assertEqual(os.environ['CLICKUP_TEAM_ID'], 'existing')
            self.assertEqual(os.environ['CLICKUP_LOOKAHEAD_DAYS'], '7')

    def test_project_ambiguity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['alpha','beta']:
                (root/name).mkdir()
            with patch.object(server, 'LOCAL_PROJECTS_ROOT', root), patch.object(server, 'load_project_map', return_value={'alpha':['client'], 'beta':['client']}):
                with self.assertRaisesRegex(ValueError, 'Ambiguous'):
                    server.resolve_project({'name':'client task'})

    def test_dry_run_never_launches(self):
        with patch.object(server,'route_task',return_value={'command':'example'}), patch.object(server.subprocess,'run') as run:
            result = server.tool_launch_codex_for_task({'task':'example', 'dry_run':True})
            self.assertFalse(json.loads(result['content'][0]['text'])['launched'])
            run.assert_not_called()

    def test_ambiguous_task_does_not_fetch_detail(self):
        with patch.object(api, 'fetch_tasks', return_value=[{'id':'1','name':'Fix page'}, {'id':'2','name':'Fix page'}]), patch.object(api,'request_json') as request:
            with self.assertRaisesRegex(ValueError, 'Ambiguous'):
                server.find_task_by_query('Fix page')
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
