import base64
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4
import zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat,PrivateFormat,NoEncryption
from tools import rule_updates as rules, runtime_paths as paths, update_protocol as protocol


class RuleUpdates(unittest.TestCase):
    def setUp(self):
        self.home=paths.CODE_ROOT/'.runtime'/('update-test-'+uuid4().hex);self.home.mkdir()
        self.cfg=copy.deepcopy(paths.config());self.key=Ed25519PrivateKey.generate()
        self.cfg['public_keys']={'test':base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()}
        self.env=patch.dict(os.environ,{'FACTORY_DATA_HOME':str(self.home)})
        self.config=patch.object(paths,'config',return_value=self.cfg)
        self.env.start();self.config.start();paths.installed_rules.cache_clear()
        self.addCleanup(self.env.stop);self.addCleanup(self.config.stop);self.addCleanup(paths.installed_rules.cache_clear)

    def bundle(self,version='100',marker=None):
        docs=rules.export_documents()
        if marker:
            name='projects/road_rescue/variable_catalog.json';catalog=json.loads(docs[name])
            catalog['dimensions'].append({'id':'update_marker','name':'更新验证','kind':'custom','roles':['cover','detail'],'probability':1,'min_select':1,'max_select':1,
                'options':[{'id':'marker','name':'更新验证','value':marker,'weight':1,'enabled':True,'conditions':[]}]})
            docs[name]=protocol.canonical(catalog)
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name,value in docs.items():z.writestr(name,value)
        archive=data.getvalue()
        payload={'kind':'rules','schema':1,'version':version,'min_app':self.cfg['app_version'],'engine_major':1,'sha256':protocol.sha(archive),'url':'https://github.com/eish1997/local-service-factory-rules/releases/download/test/rules.zip','files':{n:protocol.sha(v) for n,v in docs.items()}}
        env={'payload':payload,'key_id':'test','signature':base64.b64encode(self.key.sign(protocol.canonical(payload))).decode()}
        return env,archive

    def install(self,envelope,archive):
        response={'sha':'head-test','content':base64.b64encode(protocol.canonical(envelope)).decode()}
        def fetch(url,*args,**kwargs):
            if '/contents/' in url:return protocol.canonical(response)
            if '/HEAD/release-index.json' in url:return protocol.canonical(envelope)
            return archive
        with patch.object(protocol,'download',side_effect=fetch):return rules.sync()

    def test_signed_install_atomic_failures_and_new_prompt_version(self):
        env,data=self.bundle(marker='桌面规则更新验证标记')
        result=self.install(env,data);self.assertEqual(result['state'],'updated')
        # The next CLI process takes a new snapshot; in-flight processes stay pinned.
        paths.installed_rules.cache_clear()
        self.assertEqual(rules.status()['rules_version'],'100')
        from tools import task_library as lib
        with patch.object(lib,'ROOT',self.home):
            old=lib.assemble({'category':'road_rescue','count':1,'seed':1401,'phone':'13800138000'})
            snapshot=lib.read(lib.batch_dir('road_rescue',old['id'])/'snapshot.json')
            frozen=lib.read(lib.batch_dir('road_rescue',old['id'])/'groups/0001.json')
            self.assertEqual(snapshot['rules_version'],'100');self.assertIn('桌面规则更新验证标记',frozen['units'][0]['prompt'])
            next_env,next_data=self.bundle('101')
            self.install(next_env,next_data);paths.installed_rules.cache_clear()
            self.assertEqual(frozen,lib.read(lib.batch_dir('road_rescue',old['id'])/'groups/0001.json'))
            self.assertEqual(rules.status()['rules_version'],'101')
            from tools import task_worker
            from PIL import Image
            generated=io.BytesIO();Image.new('RGB',(1024,1536),'gray').save(generated,format='PNG');seen=[]
            request={'category':'road_rescue','batch':old['id'],'groups':[1]}
            with patch.multiple(lib,api_config=lambda:{'model':'offline-test','api_size':'1024x1536','quality':'medium','output_format':'png'},readiness=lambda *a:([],[1]),launch=lambda *a:99999999):
                plan=lib.plan(request);task=lib.start({**request,'plan_sha256':plan['plan_sha256'],'authorization':'execute_selected_groups','request_id':'old-rules-worker'})
                task_worker.run('road_rescue',old['id'],task['id'],generate=lambda *a:generated.getvalue(),clients=[(1,object())],render=lambda *a:seen.append(paths.version()))
            self.assertTrue(seen);self.assertEqual(set(seen),{'100'})
        bad=copy.deepcopy(next_env);bad['payload']['version']='102'
        with self.assertRaises(ValueError):self.install(bad,next_data)
        valid,new_data=self.bundle('103')
        with self.assertRaises(ValueError):self.install(valid,new_data+b'broken')
        with patch.object(protocol,'download',side_effect=TimeoutError('offline')),self.assertRaises(TimeoutError):rules.sync()
        self.assertEqual(rules.status()['rules_version'],'101')

    def test_privacy_and_maintainer_protection_and_permissions(self):
        for name,data in rules.export_documents().items():
            self.assertIsNone(rules.PHONE.search(data.decode()),name)
            self.assertNotIn('.env',name)
        self.assertEqual(rules.scrub({'phone':'15795643941','nested':{'api_key':'secret'},'text':'联系15795643941'}),{'nested':{},'text':'联系{已确认电话}'})
        env,data=self.bundle()
        with patch.dict(os.environ,clear=True),patch.object(paths,'data_root',return_value=self.home):
            result=self.install(env,data)
            self.assertEqual(result['state'],'available');self.assertFalse((rules.local()/'active_rules.json').exists())
        with self.assertRaises(ValueError):rules.publish({'version':'100'})
        with self.assertRaises(ValueError):rules.rollback({'from_version':'100'})
        with self.assertRaises(ValueError):protocol.public_url('http://github.com/x')
        with self.assertRaises(ValueError):protocol.public_url('https://github.com.attacker.invalid/x')

    def test_incompatible_and_tampered_archive_rejected(self):
        env,data=self.bundle();payload=env['payload'];payload['min_app']='99.0.0'
        env['signature']=base64.b64encode(self.key.sign(protocol.canonical(payload))).decode()
        with self.assertRaisesRegex(ValueError,'先更新软件'):self.install(env,data)
        self.assertFalse((rules.local()/'active_rules.json').exists())

    def test_publish_cas_and_rollback_are_explicit_and_assets_first(self):
        self.cfg.update(owner='test',rules_repo='rules')
        keyfile=self.home/'test-key.pem';keyfile.write_bytes(self.key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()))
        state={'head':None,'uploads':{},'order':[]}
        def github(method,url,body=None,raw=None):
            state['order'].append((method,url))
            if method=='GET':return {'sha':'a'*40} if '/commits/' in url else state['head'] if '/contents/' in url else None
            if method=='POST' and url.endswith('/releases'):return {'id':1,'upload_url':'https://uploads.github.com/repos/test/rules/releases/1/assets{?name}','html_url':'https://github.com/test/rules/releases/1'}
            if raw is not None:state['uploads'][url.split('name=')[1]]=raw;return {}
            if method=='PUT':state['head']={'sha':'new-head','content':body['content']};return {'content':{'sha':'new-head'}}
            return {}
        with patch.dict(os.environ,{'FACTORY_RELEASE_KEY_FILE':str(keyfile),'FACTORY_RELEASE_KEY_ID':'test'},clear=True),patch.object(paths,'data_root',return_value=self.home),patch.object(rules,'release_source_sha',return_value='a'*40):
            paths.installed_rules.cache_clear();plan=rules.release_plan({'version':'200'})
            with patch.object(protocol,'github',side_effect=github),patch.object(protocol,'download',side_effect=lambda url,*a:state['uploads'][url.rsplit('/',1)[-1]]):
                result=rules.publish({'version':plan['version'],'authorization':'publish_project_update'})
                self.assertTrue(result['published']);self.assertEqual(state['order'][-1][0],'PUT')
                rollback=rules.rollback({'from_version':'200','version':'201','authorization':'publish_project_update'})
                self.assertEqual(rollback['version'],'201')
                self.assertEqual(protocol.verify(json.loads(state['uploads']['manifest.json']),self.cfg['public_keys'])['version'],'201')
                rules.release_plan({'version':'202'})
                state['head']['sha']='concurrent-publisher'
                with self.assertRaisesRegex(ValueError,'远端版本已变化'):rules.publish({'version':'202','authorization':'publish_project_update'})

    def test_staged_engine_without_source_checkout(self):
        from tools.stage_distribution import stage_engine
        engine=stage_engine(self.home/'staged-engine')
        user=self.home/'fresh-user';user.mkdir()
        environment={**os.environ,'FACTORY_DATA_HOME':str(user),'PYTHONPATH':''}
        self.assertTrue((engine/'projects/road_rescue/pinned_signboard_profiles.json').is_file())
        result=subprocess.run([sys.executable,str(engine/'factory.py'),'tasks','projects'],cwd=user,input='{}',text=True,encoding='utf-8',capture_output=True,env=environment)
        self.assertEqual(result.returncode,0,result.stderr[-1200:]);self.assertEqual(len(json.loads(result.stdout)['data']),len(rules.PROJECTS))
        request={'category':'road_rescue','count':1,'phone':'13800138000','seed':1401}
        result=subprocess.run([sys.executable,str(engine/'factory.py'),'tasks','assemble'],cwd=user,input=json.dumps(request),text=True,encoding='utf-8',capture_output=True,env=environment)
        self.assertEqual(result.returncode,0,result.stdout[-1200:]+result.stderr[-1200:])
        self.assertTrue((user/'prompts/library/road_rescue').exists());self.assertFalse((engine/'prompts').exists())

    def test_official_raw_avoids_api_quota_and_api_fallback_keeps_signatures(self):
        from urllib.error import HTTPError
        env,data=self.bundle('9000000000000000001');response={'sha':'api-head','content':base64.b64encode(protocol.canonical(env)).decode()}
        calls=[]
        def raw_only(url,*args,**kwargs):
            calls.append(url)
            if '/contents/' in url:raise HTTPError(url,403,'quota',{},None)
            return protocol.canonical(env)
        with patch.object(protocol,'download',side_effect=raw_only):
            sha,envelope,payload=rules.remote_index(self.cfg)
        self.assertEqual(calls,[rules.raw_index(self.cfg)])
        raw=protocol.canonical(env)
        self.assertEqual(sha,__import__('hashlib').sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest())
        def fallback(url,*args,**kwargs):
            if '/HEAD/' in url:raise HTTPError(url,503,'temporary',{},None)
            return protocol.canonical(response)
        with patch.object(protocol,'download',side_effect=fallback):self.assertEqual(rules.remote_index(self.cfg)[0],'api-head')
        bad=copy.deepcopy(env);bad['payload']['version']='9000000000000000002'
        with patch.object(protocol,'download',return_value=protocol.canonical(bad)) as fetch:
            with self.assertRaisesRegex(ValueError,'签名'):rules.remote_index(self.cfg)
        self.assertEqual(fetch.call_count,1)
        with patch.dict(os.environ,clear=True),patch.object(protocol,'download',side_effect=raw_only):
            self.assertEqual(rules.remote_index(self.cfg)[0],sha)

    def test_offline_upgrade_preserves_old_and_compatible_signed_rules(self):
        from tools.stage_distribution import stage_engine
        from tools import variable_catalog as vc,task_library as lib
        engine=stage_engine(self.home/'bootstrap-engine')
        old=self.home/'.runtime/rules/1';old.mkdir(parents=True)
        baseline=json.loads((engine/'distribution/baseline-rules.json').read_text(encoding='utf-8'))
        for name in baseline['files']:
            destination=old/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes((engine/name).read_bytes())
        name='projects/truck_rescue/variable_catalog.json';catalog=json.loads((old/name).read_text(encoding='utf-8'))
        dimension=next(d for d in catalog['dimensions'] if d['binding'].get('module')=='tools.truck_scene_diversity_v3' and d['binding'].get('name')=='LOCATIONS')
        dimension['roles']=['cover','detail'];(old/name).write_bytes(protocol.canonical(catalog))
        previous_bytes=(old/name).read_bytes();rules.write(old/'manifest.json',{'version':'1','bundled':True,'app_version':'1.3.1'})
        rules.write(rules.local()/'active_rules.json',{'version':'1','bundled':True})
        with patch.object(paths,'CODE_ROOT',engine),patch.object(vc,'ROOT',engine),patch.object(lib,'ROOT',self.home):
            with patch.object(protocol,'download',side_effect=AssertionError('bootstrap must be offline')):
                result=rules.bootstrap()
            self.assertEqual(result['state'],'refreshed');self.assertNotEqual(result['version'],'1')
            self.assertEqual((old/name).read_bytes(),previous_bytes)
            self.assertEqual(rules.status()['active_rules']['previous'],'1')
            vc.validate(vc.load('truck_rescue'))
            batch=lib.assemble({'category':'truck_rescue','count':1,'phone':'13800138000','seed':1401})
            snap=lib.read(lib.batch_dir('truck_rescue',batch['id'])/'snapshot.json')
            self.assertEqual(snap['rules_version'],result['version'])
            self.assertEqual(rules.bootstrap()['state'],'compatible')
            envelope,archive=self.bundle('9000000000000000001')
            self.assertEqual(self.install(envelope,archive)['state'],'updated')
            paths.installed_rules.cache_clear();active=(rules.local()/'active_rules.json').read_bytes()
            self.assertEqual(rules.bootstrap()['bundled'],False)
            self.assertEqual((rules.local()/'active_rules.json').read_bytes(),active)
            # Compatible signed data stay active even though the current
            # software also has its own built-in snapshot.
            self.assertEqual(rules.status()['rules_version'],'9000000000000000001')
            bad=json.loads((paths.installed_rules()/name).read_text(encoding='utf-8'));bad['dimensions'][0]['roles']=['detail']
            (paths.installed_rules()/name).write_bytes(protocol.canonical(bad))
            self.assertEqual(rules.bootstrap()['state'],'refreshed')
            self.assertTrue((self.home/'.runtime/rules/9000000000000000001'/name).exists())
            pointer=(rules.local()/'active_rules.json').read_bytes()
            with self.assertRaisesRegex(ValueError,'缓存损坏'):self.install(envelope,archive)
            self.assertEqual((rules.local()/'active_rules.json').read_bytes(),pointer)

if __name__=='__main__':unittest.main()
