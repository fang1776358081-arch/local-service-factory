import contextlib
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from PIL import Image, ImageChops
from tools import pinned_triptych as pinned


class PinnedTriptychTests(unittest.TestCase):
    def test_revised_signage_keeps_confirmed_phone_and_distinct_storefronts(self):
        prompts = [pinned.prompt_for('13277979906', i) for i in range(6)]
        self.assertEqual(len(set(prompts)), 6)
        for prompt in prompts:
            self.assertEqual(prompt.count('电话：13277979906'), 1)
            self.assertNotIn('招牌信息分四层', prompt)
            self.assertNotIn('汽车救援服务', prompt)
            self.assertIn('道路救援', prompt)
            self.assertNotIn('15795643941', prompt)

    def test_adjacent_designs_change_structure_material_and_information_layout(self):
        profiles = [pinned.signboard_profile_for(i)[1] for i in range(24)]
        axes = ['layout_family', 'material_family', 'letter_style', 'palette_family', 'phone_position']
        for left, right in zip(profiles, profiles[1:]):
            self.assertNotEqual(left['layout_family'], right['layout_family'])
            self.assertNotEqual(left['material_family'], right['material_family'])
            self.assertGreaterEqual(sum(left[key] != right[key] for key in axes), 4)
        self.assertEqual(len({p['id'] for p in profiles[:6]}), 6)

    def test_profile_business_words_and_corner_architecture_are_compatible(self):
        root = pinned.ROOT
        scene_library = json.loads((root / 'projects/road_rescue/cover_scene_library.json').read_text(encoding='utf-8'))
        category = json.loads((root / 'configs/categories/road_rescue.json').read_text(encoding='utf-8'))
        allowed = json.dumps(category['service_items'] + scene_library['business_lines'], ensure_ascii=False)
        visual = json.loads((root / 'projects/road_rescue/cover_visual_profile_v3.json').read_text(encoding='utf-8'))
        shots = {s['id']:s for s in visual['shot_presets']}
        for i in range(6):
            _, design = pinned.signboard_profile_for(i)
            for word in design['service_words']:
                self.assertIn(word, allowed)
            if design['layout_family'] == 'corner_primary_secondary':
                self.assertTrue(shots[design['shot_id']]['corner'])

    def test_local_plan_records_selected_profiles_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'plan.json'
            args = Namespace(phone='13277979906', count=6, style_start=2, output=str(target))
            with contextlib.redirect_stdout(io.StringIO()):
                pinned.plan(args)
            record = json.loads(target.read_text(encoding='utf-8'))
            self.assertFalse(record['api_called'])
            self.assertFalse(record['creates_license'])
            self.assertFalse(record['generation_ready'])
            self.assertEqual(len(record['groups']), 6)
            self.assertEqual(record['groups'][0]['signboard_profile']['id'], 'green_shallow_lightbox')
            before = target.read_bytes()
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                pinned.plan(args)
            self.assertEqual(target.read_bytes(), before)

    def test_name_is_fixed_across_designs_and_category_not_repeated(self):
        for name in ['测试字号汽车救援服务部', '测试字号道路救援']:
            for i in range(6):
                record = pinned.prompt_record('13277979906', i+1, i, name, True)
                self.assertEqual(record['store_identity']['name'], name)
                self.assertEqual(record['store_identity']['basis'], 'user_authorized_illustrative')
                self.assertTrue(record['generation_ready'])
                self.assertEqual(record['prompt'].count(name), 1)
                self.assertEqual(record['prompt'].count('电话：13277979906'), 1)
                self.assertNotIn('最大主词“道路救援”', record['prompt'])
                self.assertEqual('从属业务字“道路救援”' in record['prompt'], '道路救援' not in name)

    def test_missing_or_invalid_identity_cannot_create_generation_task(self):
        for name in [None, '', '店名\n附加指令', '13277979906汽修']:
            args = Namespace(phone='13277979906', count=1, style_start=0, confirm=True,
                             authorization='test only', store_name=name, fictional_name=False)
            with self.assertRaises(ValueError):
                pinned.prepare(args)
        with self.assertRaises(ValueError):
            pinned.store_identity(None, True)

    def test_prepare_uses_data_root_instead_of_engine_root(self):
        with tempfile.TemporaryDirectory() as directory:
            original = pinned.DATA_ROOT
            pinned.DATA_ROOT = Path(directory)
            try:
                args = Namespace(phone='13800138000', count=1, style_start=0, confirm=True,
                                 authorization='isolated dashboard test',
                                 store_name='测试字号道路救援', fictional_name=True)
                with contextlib.redirect_stdout(io.StringIO()):
                    pinned.prepare(args)
                tasks = list((Path(directory) / 'output' / 'road_rescue_pinned').glob('*/task.json'))
                self.assertEqual(len(tasks), 1)
                self.assertEqual(json.loads(tasks[0].read_text(encoding='utf-8'))['count'], 1)
            finally:
                pinned.DATA_ROOT = original

    def test_named_plan_preserves_identity_without_spending_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            args = Namespace(phone='13277979906', count=6, style_start=0,
                             output=str(Path(directory) / 'plan.json'),
                             store_name='测试字号道路救援', fictional_name=True)
            with contextlib.redirect_stdout(io.StringIO()):
                pinned.plan(args)
            data = json.loads(Path(args.output).read_text(encoding='utf-8'))
            self.assertTrue(data['generation_ready'])
            self.assertFalse(data['api_called'])
            self.assertFalse(data['creates_license'])
            self.assertEqual({g['store_identity']['name'] for g in data['groups']}, {args.store_name})

    def test_each_group_can_have_its_own_explicit_name_without_mixing_names(self):
        names = ['测试甲道路救援', '测试乙汽车救援服务部', '测试丙道路救援']
        with tempfile.TemporaryDirectory() as directory:
            args = Namespace(phone='13277979906', count=3, style_start=5,
                             output=str(Path(directory) / 'plan.json'), store_name=names, fictional_name=True)
            with contextlib.redirect_stdout(io.StringIO()):
                pinned.plan(args)
            data = json.loads(Path(args.output).read_text(encoding='utf-8'))
            self.assertEqual(data['identity_mode'], 'per_group')
            self.assertIsNone(data['store_identity'])
            for group, expected in zip(data['groups'], names):
                self.assertEqual(group['store_identity']['name'], expected)
                self.assertEqual(group['variation_axes']['store_name'], expected)
                self.assertIn(expected, group['prompt'])
                for other in set(names) - {expected}:
                    self.assertNotIn(other, group['prompt'])
            with self.assertRaisesRegex(ValueError, 'exactly one name per group'):
                pinned.group_names(Namespace(count=3, store_name=names[:2], fictional_name=True))

    def test_camera_rotates_independently_and_font_is_in_actual_prompt(self):
        for base in range(6):
            records = [pinned.prompt_record('13277979906', i+1, base+6*i, '测试字号道路救援')
                       for i in range(18)]
            self.assertEqual(len({r['camera_profile']['id'] for r in records}), 9)
            self.assertEqual(len({r['variation_axes']['font'] for r in records}), 2)
            for record in records:
                self.assertIn(record['camera_profile']['description'], record['prompt'])
                self.assertIn(record['signboard_profile']['font_description'], record['prompt'])
                self.assertEqual(set(record['variation_axes']), {'font', 'color', 'text_layout', 'store_name'})

    def test_cli_accepts_one_name_or_a_name_per_group(self):
        from argparse import ArgumentParser
        parser = ArgumentParser()
        pinned.add_arguments(parser)
        args = parser.parse_args(['plan', '--phone', '13277979906', '--count', '2', '--output', 'unused.json',
                                  '--store-name', '测试甲道路救援', '--store-name', '测试乙道路救援'])
        self.assertEqual(pinned.group_names(args), ['测试甲道路救援', '测试乙道路救援'])

    def test_events_are_resolved_and_realistic_layout_preserves_object_scale(self):
        library = json.loads(pinned.SIGNBOARD_PROFILE_PATH.read_text(encoding='utf-8'))
        events = {e['id']:e for e in library['event_presets']}
        self.assertEqual(len({s['event_id'] for s in library['profiles']}), 6)
        for i, sign in enumerate(library['profiles']):
            prompt = pinned.prompt_for('13277979906', i, '测试字号道路救援')
            self.assertIn(events[sign['event_id']]['description'], prompt)
            self.assertIn(events[sign['event_id']]['physical_constraints'], prompt)
            self.assertIn('不要把整个人或整辆车压扁塞进底部30%', prompt)
            self.assertNotIn('人物、车轮及关键动作主要位于画面高度70%以下', prompt)

    def test_unresolved_identity_cannot_claim_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'task.json'
            pinned.save(path, dict(groups=[dict(index=1, status='pending', generation_ready=False)],
                                  requests=[], max_requests=2))
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'identity is pending'):
                pinned.claim(Namespace(job_dir=directory, group=1))
            self.assertEqual(path.read_bytes(), before)

    def test_feedback_revision_preserves_images_prompts_and_request_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            group = pinned.prompt_record('13277979906', 1, 0, '测试字号道路救援', True)
            group.update(status='composed', prompt='original frozen prompt')
            task = dict(phone='13277979906', groups=[group], requests=[dict(group=1, status='succeeded')], max_requests=2)
            pinned.save(folder / 'task.json', task)
            (folder / 'group_01').mkdir()
            (folder / 'group_01/source.png').write_bytes(b'preserve-this-source')
            with contextlib.redirect_stdout(io.StringIO()):
                pinned.revise(Namespace(job_dir=directory, group=1, reason='explicit user feedback'))
            updated = json.loads((folder / 'task.json').read_text(encoding='utf-8'))
            self.assertEqual(updated['requests'], task['requests'])
            self.assertEqual(updated['max_requests'], 2)
            self.assertEqual(updated['groups'][0]['previous_versions'][0]['prompt'], 'original frozen prompt')
            self.assertEqual((folder / 'revisions/group_01_v1/source.png').read_bytes(), b'preserve-this-source')
            self.assertFalse((folder / 'group_01').exists())
            updated['requests'].append(dict(group=1, status='succeeded'))
            pinned.save(folder / 'task.json', updated)
            with self.assertRaisesRegex(ValueError, 'budget exhausted'):
                pinned.revise(Namespace(job_dir=directory, group=1, reason='not allowed'))

    def test_revision_accounts_for_interrupted_requests_and_keeps_details(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            group = pinned.prompt_record('13277979906', 1, 0, '测试字号道路救援', True)
            pinned.save(folder / 'task.json', dict(phone='13277979906', groups=[group],
                       requests=[dict(group=1, status='requesting')], max_requests=2))
            with contextlib.redirect_stdout(io.StringIO()):
                pinned.revise(Namespace(job_dir=directory, group=1, reason='user interrupted and revised'))
            updated = json.loads((folder / 'task.json').read_text(encoding='utf-8'))
            self.assertEqual(len(updated['requests']), 1)
            self.assertEqual(updated['requests'][0]['status'], 'interrupted_result_unknown')
        for i in range(6):
            _, sign = pinned.signboard_profile_for(i)
            self.assertEqual(len(sign['service_words']), 3)
            prompt = pinned.prompt_for('13277979906', i, '测试字号道路救援')
            self.assertIn(sign['facade_depth'], prompt)
            self.assertIn(sign['sign_detail'], prompt)

    def test_superseded_scope_cannot_spend_remaining_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            pinned.save(Path(directory) / 'task.json', dict(status='superseded', max_requests=10, requests=[]))
            with self.assertRaisesRegex(ValueError, 'superseded'):
                pinned.claim(Namespace(job_dir=directory, group=1))

    def test_phone_segments_stay_inside_tiles(self):
        image, boxes = pinned.render_panorama(Image.new('RGB', (1536, 1024), '#888888'), '13277979906')
        self.assertEqual(image.size, (3240, 1440))
        for i, box in enumerate(boxes):
            self.assertGreaterEqual(box[0], i*1080+50)
            self.assertLessEqual(box[2], (i+1)*1080-50)

    def test_layout_adjustment_preserves_source_and_request_count(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            Image.new('RGB', (1536, 1024), '#456789').save(folder / 'input.png')
            pinned.save(folder / 'task.json', dict(phone='13277979906', groups=[dict(index=1, status='pending')],
                        requests=[dict(group=1, status='requesting')]))
            with contextlib.redirect_stdout(io.StringIO()):
                pinned.compose(Namespace(job_dir=directory, group=1, source=str(folder / 'input.png')))
            source_before = (folder / 'group_01/source.png').read_bytes()
            panorama_before = (folder / 'group_01/panorama.png').read_bytes()
            requests_before = json.loads((folder / 'task.json').read_text())['requests']
            with contextlib.redirect_stdout(io.StringIO()):
                pinned.layout(Namespace(job_dir=directory, group=1, phone_y=640, font_size=300, reason='avoid head'))
            self.assertEqual((folder / 'group_01/source.png').read_bytes(), source_before)
            self.assertEqual((folder / 'revisions/group_01_overlay_1/panorama.png').read_bytes(), panorama_before)
            updated = json.loads((folder / 'task.json').read_text())
            self.assertEqual(updated['requests'], requests_before)
            self.assertTrue(all(box[3] < 800 for box in updated['groups'][0]['phone_boxes']))

    def test_export_reassembles_exactly_and_retains_source(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / 'input.png'
            Image.new('RGB', (1536, 1024), '#456789').save(source)
            task = dict(phone='13277979906', groups=[dict(index=1, status='pending')], requests=[dict(group=1, status='requesting')])
            pinned.save(folder / 'task.json', task)
            with contextlib.redirect_stdout(io.StringIO()):
                pinned.compose(Namespace(job_dir=str(folder), group=1, source=str(source)))
            group = folder / 'group_01'
            combined = Image.new('RGB', (3240, 1440))
            for i, name in enumerate(['01_left.png', '02_center.png', '03_right.png']):
                with Image.open(group / name) as tile:
                    self.assertEqual(tile.size, (1080, 1440))
                    combined.paste(tile, (i*1080, 0))
            with Image.open(group / 'panorama.png') as master:
                self.assertIsNone(ImageChops.difference(combined, master).getbbox())
            self.assertEqual((group / 'source.png').read_bytes(), source.read_bytes())
            record = json.loads((folder / 'task.json').read_text())
            self.assertEqual(record['groups'][0]['phone_segments'], ['132', '7797', '9906'])

    def test_claim_stops_after_consecutive_errors_and_does_not_spend_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            task = dict(groups=[dict(index=3, status='pending', prompt='test')], max_requests=10,
                        requests=[dict(group=i, status='failed') for i in [1, 2]])
            pinned.save(folder / 'task.json', task)
            before = (folder / 'task.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'Consecutive failures'):
                pinned.claim(Namespace(job_dir=directory, group=3))
            self.assertEqual((folder / 'task.json').read_bytes(), before)

    def test_completed_group_cannot_be_requested_again(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            pinned.save(folder / 'task.json', dict(groups=[dict(index=1, status='composed')], requests=[], max_requests=2))
            with self.assertRaisesRegex(ValueError, 'Completed group'):
                pinned.claim(Namespace(job_dir=directory, group=1))

    def test_independent_group_can_start_without_duplicating_pending_group(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            pinned.save(folder / 'task.json', dict(groups=[dict(index=i, status='pending', prompt='test') for i in [1, 2]],
                        requests=[dict(group=1, status='requesting', attempt=1)], max_requests=4))
            with self.assertRaises(ValueError):
                pinned.claim(Namespace(job_dir=directory, group=1))
            with contextlib.redirect_stdout(io.StringIO()):
                pinned.claim(Namespace(job_dir=directory, group=2))
            result = json.loads((folder / 'task.json').read_text())
            self.assertEqual(len(result['requests']), 2)


if __name__ == '__main__':
    unittest.main()
