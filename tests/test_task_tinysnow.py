import io
import threading
import time
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import call,patch
from PIL import Image
from tools import task_library as lib, task_worker as worker


class TinySnowTasks(unittest.TestCase):
    def config(self):
        with patch('factory.effective_api_config',return_value={
            'provider':'relay','base_url':'https://tinysnow.one/v1',
            'model':'gpt-image-2-4k','quality':'medium','api_size':'1024x1536','output_format':'png'}):
            return lib.api_config()

    def test_default_contract_and_wrong_provider(self):
        cfg=self.config()
        self.assertEqual(cfg['api_size'],'2560x3840')
        self.assertEqual(cfg['raw_contract'],'tinysnow_2336_2352x3520_to_legacy_v1')
        with patch('factory.effective_api_config',return_value={**cfg,'base_url':'https://other.example/v1'}):
            with self.assertRaises(ValueError):lib.api_config()

    def test_probe_keeps_the_only_listed_model(self):
        self.assertEqual(lib.choose_listed_model(['gpt-image-2','gpt-image-2.5-flare','gpt-image-2.5-sunburst']),'gpt-image-2.5-flare')
        self.assertEqual(lib.choose_listed_model(['gpt-image-2-4k']),'gpt-image-2-4k')
        with self.assertRaisesRegex(ValueError,'唯一可用模型'):lib.choose_listed_model(['gpt-image-2-4k','gpt-image-2.5-flare'])
        with self.assertRaisesRegex(ValueError,'唯一可用模型'):lib.choose_listed_model(['gpt-image-2'])
        class Models:
            def __init__(self,name):self.name=name
            def list(self):return type('Page',(),{'data':[type('Model',(),{'id':self.name})()]})()
        class Client:
            def __init__(self,**kwargs):self.kwargs=kwargs;self.models=Models(Client.names[kwargs['api_key']])
        saved={'provider':'relay','base_url':'https://tinysnow.one/v1','model':'gpt-image-2-4k','quality':'medium','api_size':'1024x1536','output_format':'png'}
        with patch('factory.effective_api_config',return_value=dict(saved)),patch('image_generate.configured_api_keys',return_value=['key-a','key-b']),patch('openai.OpenAI',Client):
            Client.names={'key-a':'gpt-image-2.5-flare','key-b':'gpt-image-2-4k'}
            slots=lib.probe_slot_models()
            Client.names={'key-a':'gpt-image-2.5-flare'}
            flare=lib.active_model_config()
            Client.names={'key-a':'gpt-image-2-4k'}
            fourk=lib.active_model_config()
        self.assertEqual(slots['1']['model'],'gpt-image-2.5-flare')
        self.assertEqual(slots['1']['api_size'],'1024x1536')
        self.assertEqual(slots['2']['model'],'gpt-image-2-4k')
        self.assertEqual(slots['2']['api_size'],'2560x3840')
        self.assertEqual(lib.model_label(slots,slots['1']),'密钥1 gpt-image-2.5-flare、密钥2 gpt-image-2-4k')
        self.assertEqual(flare['model'],'gpt-image-2.5-flare')
        self.assertEqual(flare['api_size'],'1024x1536')
        self.assertNotIn('raw_contract',flare)
        self.assertEqual(fourk['model'],'gpt-image-2-4k')
        self.assertEqual(fourk['api_size'],'2560x3840')
        self.assertEqual(fourk['raw_contract'],'tinysnow_2336_2352x3520_to_legacy_v1')
        with patch.object(lib,'api_config',return_value={'model':'offline'}):
            self.assertEqual(lib.active_model_config(),{'model':'offline'})

    def test_key_pool_model_probes_run_concurrently_and_keep_slot_order(self):
        lock=threading.Lock();active=0;maximum=0
        def listed(base,key):
            nonlocal active,maximum
            with lock:active+=1;maximum=max(maximum,active)
            try:
                time.sleep(.03)
                return ['gpt-image-2.5-flare' if key.endswith('1') else 'gpt-image-2-4k']
            finally:
                with lock:active-=1
        base={'provider':'relay','base_url':'https://tinysnow.one/v1','model':'gpt-image-2-4k','quality':'medium','api_size':'1024x1536','output_format':'png'}
        with patch('factory.effective_api_config',return_value=base), \
             patch('image_generate.configured_api_keys',return_value=['key-1','key-2','key-3']), \
             patch.object(lib,'listed_model_ids',side_effect=listed):
            result=lib.probe_slot_models()
        self.assertGreater(maximum,1)
        self.assertEqual(list(result),['1','2','3'])
        self.assertEqual(result['1']['model'],'gpt-image-2.5-flare')
        self.assertEqual(result['2']['model'],'gpt-image-2-4k')

    def test_recent_probe_cache_is_key_fingerprinted_and_reused(self):
        root=Path('.runtime')/('test-model-cache-'+uuid4().hex);previous=lib.ROOT;lib.ROOT=root
        calls=[]
        base={'provider':'relay','base_url':'https://tinysnow.one/v1','model':'gpt-image-2-4k','quality':'medium','api_size':'1024x1536','output_format':'png'}
        def listed(config,key):calls.append(key);return ['gpt-image-2.5-flare']
        try:
            with patch('factory.effective_api_config',return_value=base), \
                 patch('image_generate.configured_api_keys',return_value=['key-a','key-b']), \
                 patch.object(lib,'listed_model_ids',side_effect=listed):
                first=lib.probe_slot_models(cache_seconds=300)
                second=lib.probe_slot_models(cache_seconds=300)
            self.assertEqual(first,second)
            self.assertEqual(sorted(calls),['key-a','key-b'])
            saved=lib.read(root/'.runtime/private/model-probe-cache.json')
            self.assertNotIn('key-a',str(saved));self.assertNotIn('key-b',str(saved))
        finally:
            lib.ROOT=previous
            if root.exists():
                import shutil;shutil.rmtree(root)

    def test_model_listing_retries_transient_errors_but_not_authentication(self):
        class Failure(Exception):
            def __init__(self,status_code=None):
                self.status_code=status_code
        class Models:
            calls=0
            failures=[]
            def list(self):
                Models.calls+=1
                if Models.failures:raise Models.failures.pop(0)
                return type('Page',(),{'data':[type('Model',(),{'id':'gpt-image-2.5-flare'})()]})()
        class Client:
            def __init__(self,**kwargs):self.models=Models()
        base={'base_url':'https://tinysnow.one/v1'}
        Models.calls=0;Models.failures=[Failure(),Failure()]
        with patch('openai.OpenAI',Client),patch.object(lib.time,'sleep') as sleep:
            self.assertEqual(lib.listed_model_ids(base,'hidden-key'),['gpt-image-2.5-flare'])
        self.assertEqual(Models.calls,3)
        self.assertEqual(sleep.call_args_list,[call(.5),call(1.)])
        Models.calls=0;Models.failures=[Failure(401)]
        with patch('openai.OpenAI',Client),patch.object(lib.time,'sleep') as sleep:
            with self.assertRaisesRegex(ValueError,'检查密钥'):
                lib.listed_model_ids(base,'hidden-key')
        self.assertEqual(Models.calls,1)
        sleep.assert_not_called()

    def test_detected_model_replaces_frozen_task_without_resetting_counts(self):
        root=Path('.runtime')/('test-model-adopt-'+uuid4().hex)
        previous=lib.ROOT;lib.ROOT=root
        try:
            root.mkdir(parents=True)
            (root/'.env').write_text('OPENAI_PROVIDER=relay\nOPENAI_IMAGE_MODEL=gpt-image-2-4k\n',encoding='utf-8')
            private=root/'.runtime'/'private';private.mkdir(parents=True)
            (private/'api_channels.json').write_text('{"channels":[{"id":"relay","provider":"relay","model":"gpt-image-2-4k","keys":["kept"]}]}',encoding='utf-8')
            flare={'provider':'relay','model':'gpt-image-2.5-flare','quality':'medium','api_size':'1024x1536','base_url':'https://tinysnow.one/v1'}
            file=root/'tasks'/'t'/'task.json'
            state={'slots':[1],'config':{'model':'gpt-image-2-4k','quality':'medium','api_size':'2560x3840'},'requests_used':7,'attempts':{'u':1}}
            lib.write(file.parent/'license.json',{'terms':{'id':'t','config':dict(state['config'])},'requests_used':7,'attempts':{'u':1}})
            with patch.object(lib,'probe_slot_models',return_value={'1':flare}):
                self.assertTrue(lib.apply_detected_models(file,state))
            self.assertEqual(state['requests_used'],7)
            self.assertEqual(state['config']['model'],'gpt-image-2.5-flare')
            self.assertEqual(state['config']['api_size'],'1024x1536')
            saved=lib.read(file.parent/'license.json')
            self.assertEqual((saved['requests_used'],saved['attempts']), (7,{'u':1}))
            self.assertEqual(saved['terms']['slot_models']['1']['model'],'gpt-image-2.5-flare')
            self.assertEqual(state['license_sha256'],lib.digest(saved['terms']))
            self.assertEqual(lib.read(file)['requests_used'],7)
            self.assertIn('OPENAI_IMAGE_MODEL=gpt-image-2.5-flare',(root/'.env').read_text(encoding='utf-8'))
            self.assertNotIn('gpt-image-2-4k',(root/'.env').read_text(encoding='utf-8'))
            self.assertEqual(lib.read(private/'api_channels.json')['channels'][0]['keys'],['kept'])
            self.assertEqual(lib.read(private/'api_channels.json')['channels'][0]['model'],'gpt-image-2.5-flare')
            with patch.object(lib,'probe_slot_models',return_value=None):
                self.assertIsNone(lib.apply_detected_models(file,state))
            self.assertEqual(lib.read(file)['requests_used'],7)
        finally:
            lib.ROOT=previous

    def test_actual_source_contract_archives_and_normalizes(self):
        root=Path('.runtime')/('test-shared-4k-'+uuid4().hex)
        root.mkdir(parents=True)
        for width in (2336,2352,2340):
            data=io.BytesIO();Image.new('RGB',(width,3520),'gray').save(data,format='PNG')
            raw=root/str(width)/'raw.png';raw.parent.mkdir()
            if width==2340:
                with self.assertRaises(Exception):worker.save_task_raw(raw,data.getvalue(),self.config(),'cover')
                self.assertFalse(raw.exists())
            else:
                result=worker.save_task_raw(raw,data.getvalue(),self.config(),'cover')
                with Image.open(raw) as image:self.assertEqual(image.size,(1024,1536))
                self.assertTrue(result)
            self.assertTrue(any(p.is_file() and p.read_bytes()==data.getvalue() for p in (raw.parent/'originals').rglob('*')))


if __name__=='__main__':unittest.main()
