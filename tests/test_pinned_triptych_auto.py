import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tools import pinned_triptych as pinned
from tools import pinned_triptych_auto as auto


def image_bytes():
    buffer = io.BytesIO()
    Image.new('RGB', (1536, 1024), '#58748a').save(buffer, format='PNG')
    return buffer.getvalue()


class PinnedTriptychAuto(unittest.TestCase):
    def task(self, folder, count=2):
        groups = [pinned.prompt_record('13800138000', index, index - 1,
                                       f'测试{index}道路救援', True)
                  for index in range(1, count + 1)]
        task = dict(version=1, task_id='20261117T010203123456Z', phone='13800138000',
                    category='road_rescue', count=count, status='prepared', max_requests=count * 2,
                    requests=[], groups=groups,
                    auto_generation=dict(status='starting', requested_max_workers=50))
        pinned.save(Path(folder) / 'task.json', task)

    def test_auto_worker_generates_and_composes_every_group_without_extra_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            self.task(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                code = auto.run(directory, config={'model': 'gpt-image-2.5-flare'},
                                clients=[(1, object()), (2, object())],
                                generate=lambda client, config, prompt: image_bytes())
            self.assertEqual(code, 0)
            task = json.loads((Path(directory) / 'task.json').read_text(encoding='utf-8'))
            self.assertEqual(task['auto_generation']['status'], 'completed')
            self.assertEqual(len(task['requests']), 2)
            self.assertTrue(all(request['status'] == 'succeeded' for request in task['requests']))
            self.assertTrue(all(group['status'] == 'composed' for group in task['groups']))
            for group in (1, 2):
                self.assertTrue((Path(directory) / f'group_{group:02d}' / 'preview.jpg').is_file())

    def test_invalid_landscape_parameter_stops_after_first_bounded_request(self):
        class InvalidSize(Exception):
            status_code = 400
            code = 'invalid_parameter'

        with tempfile.TemporaryDirectory() as directory:
            self.task(directory, count=3)
            def reject(client, config, prompt):
                raise InvalidSize('unsupported size')
            code = auto.run(directory, config={'model': 'gpt-image-2.5-flare'},
                            clients=[(1, object()), (2, object()), (3, object())], generate=reject)
            self.assertEqual(code, 1)
            task = json.loads((Path(directory) / 'task.json').read_text(encoding='utf-8'))
            self.assertEqual(len(task['requests']), 1)
            self.assertEqual(task['requests'][0]['status'], 'failed')
            self.assertEqual(task['requests'][0]['rejection_kind'], 'parameters')
            self.assertEqual(task['auto_generation']['status'], 'completed_with_errors')

    def test_saved_provider_image_is_composed_locally_without_another_request(self):
        with tempfile.TemporaryDirectory() as directory:
            self.task(directory, count=1)
            folder = Path(directory)
            source = folder / 'auto_sources' / 'group_01_attempt_1.image'
            source.parent.mkdir()
            source.write_bytes(image_bytes())
            task = json.loads((folder / 'task.json').read_text(encoding='utf-8'))
            task['requests'].append({'group': 1, 'attempt': 1, 'status': 'saved_pending_compose',
                                     'tool': 'api', 'provider_source': 'auto_sources/group_01_attempt_1.image'})
            pinned.save(folder / 'task.json', task)
            calls = 0
            def must_not_generate(client, config, prompt):
                nonlocal calls
                calls += 1
                raise AssertionError('paid generation must not run')
            code = auto.run(directory, config={'model': 'gpt-image-2.5-flare'},
                            clients=[(1, object())], generate=must_not_generate)
            self.assertEqual(code, 0)
            self.assertEqual(calls, 0)
            updated = json.loads((folder / 'task.json').read_text(encoding='utf-8'))
            self.assertEqual(len(updated['requests']), 1)
            self.assertEqual(updated['requests'][0]['status'], 'succeeded')

    def test_model_probe_timeout_is_not_reused_for_paid_generation_client(self):
        created = []
        class Models:
            @staticmethod
            def list():
                return type('Page', (), {'data': [type('Model', (), {'id': 'gpt-image-2.5-flare'})()]})()
        class Client:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.models = Models()
                created.append(self)
        with patch('image_generate.configured_api_keys', return_value=['hidden']), \
             patch.object(auto, '_base_config', return_value={'base_url': 'https://example.invalid/v1'}), \
             patch('openai.OpenAI', Client):
            _, clients = auto.discover_clients(1)
        self.assertEqual(created[0].kwargs['timeout'], 20)
        self.assertNotIn('timeout', clients[0][1].kwargs)
        self.assertEqual(clients[0][1].kwargs['max_retries'], 0)

    def test_single_lane_retries_same_group_before_touching_next_group(self):
        with tempfile.TemporaryDirectory() as directory:
            self.task(directory, count=2)
            prompts = []
            def flaky(client, config, prompt):
                prompts.append(prompt)
                if len(prompts) == 1:
                    raise TimeoutError('fixture timeout')
                return image_bytes()
            code = auto.run(directory, config={'model': 'gpt-image-2.5-flare'},
                            clients=[(1, object())], generate=flaky)
            self.assertEqual(code, 0)
            self.assertEqual(prompts[0], prompts[1])


if __name__ == '__main__':
    unittest.main()
