import json,os,unittest
from uuid import uuid4
from unittest.mock import patch
from tools import software_release as software,rule_updates as rules

class TransitionTests(unittest.TestCase):
    def test_same_artifacts_both_repositories_and_recovery(self):
        root=software.paths.CODE_ROOT/'.runtime'/('transition-'+uuid4().hex);root.mkdir(parents=True)
        new='new-repo';old='local-service-factory-dev'
        cfg={'owner':'new-owner','software_repo':new,'rules_repo':new,'legacy_software_repository':{'owner':'eish1997','repo':old},'app_version':'1.4.18','public_keys':{},'max_rules_bytes':1024}
        files={}
        for name in ['LocalServiceFactory-1.4.18-setup.exe','LocalServiceFactory-1.4.18-setup.exe.blockmap','latest.yml']:
            (root/name).write_bytes(name.encode());files[name]=software.protocol.sha(name.encode())
        (root/'build-provenance.json').write_text(json.dumps({'schema_version':1,'source_sha':'a'*40,'version':'1.4.18','repository':{'owner':'new-owner','repo':new},'files':files}),encoding='utf-8')
        states={repo:{'release':None,'latest':None,'lock':None} for repo in (new,old)};writes=[]
        def github(method,url,body=None,raw=None):
            repo=old if old in url else new;state=states[repo]
            if method=='GET':
                if '/commits/' in url:return {'sha':'a'*40}
                if '/git/ref/heads/' in url:return {'object':{'sha':'b'*40}}
                if url.endswith('/releases/latest'):return state['latest']
                if '/releases/tags/' in url:return state['release']
                if '/git/ref/tags/software-publish-lock' in url:return state['lock']
                if '/git/ref/tags/' in url:return {'object':{'sha':state['release']['target_commitish']}} if state['release'] else None
                return {'default_branch':'main'}
            writes.append((repo,method,url))
            if raw is not None:
                name=url.split('name=')[1];state['release']['uploads'][name]=raw;state['release']['assets'].append({'name':name});return {}
            if method=='POST' and url.endswith('/git/refs'):
                self.assertIsNone(state['lock']);state['lock']={'object':{'sha':body['sha']}};return {}
            if method=='POST' and url.endswith('/releases'):
                state['release']={**body,'id':1,'assets':[],'uploads':{},'upload_url':f'https://uploads.github.com/{repo}/assets{{?name}}','html_url':'fixture'};return state['release']
            if method=='PATCH':
                state['release'].update(body)
                if body.get('make_latest')=='true':state['latest']=state['release']
                return {}
            if method=='DELETE':state['lock']=None;return {}
            raise AssertionError(url)
        rule_payload={'version':'201','url':f'https://github.com/new-owner/{new}/releases/download/rules-201/rules.zip','sha256':software.protocol.sha(b'rules')}
        def download(url,*args,**kwargs):
            if url.endswith('/rules.zip'):return b'rules'
            repo=old if old in url else new
            return states[repo]['release']['uploads'][url.rsplit('/',1)[1]]
        with patch.dict(os.environ,{},clear=True),patch.object(software.paths,'config',return_value=cfg),patch.object(software.protocol,'github',side_effect=github),patch.object(software.protocol,'download',side_effect=download),patch.object(software.protocol,'sign',side_effect=lambda p,*a:{'payload':p}),patch.object(software.protocol,'verify',side_effect=lambda e,*a:e['payload']),patch.object(rules,'remote_index',return_value=('index',{},rule_payload)):
            request={'directory':str(root)}
            legacy={**request,'target':'legacy-software'}
            with self.assertRaises(ValueError):software.publish({**software.release_plan(legacy),'authorization':'publish_software_update'})
            self.assertEqual(writes,[])
            software.publish({**software.release_plan(request),'authorization':'publish_software_update'})
            software.publish({**software.release_plan(legacy),'authorization':'publish_software_update'})
            self.assertEqual(states[new]['release']['uploads'],states[old]['release']['uploads'])
            self.assertEqual(len(states[old]['release']['uploads']),4)
            self.assertEqual(states[old]['release']['target_commitish'],'b'*40)
            # Simulate a lost response after Latest changed but before lock deletion.
            states[old]['lock']={'object':{'sha':'b'*40}};before=len(writes)
            result=software.recover({**software.release_plan(legacy),'authorization':'finalize_software_recovery'})
            self.assertTrue(result['recovered']);self.assertEqual([x[1] for x in writes[before:]],['DELETE'])
            self.assertEqual(cfg['software_repo'],new)

    def test_target_allowlist(self):
        cfg={'owner':'eish1997','software_repo':'local-service-factory-dev'}
        self.assertEqual(software.publication_repo(cfg,{'target':'legacy-software'}),'local-service-factory-releases')
        moved={'owner':'new-owner','software_repo':'new-repo','legacy_software_repository':{'owner':'eish1997','repo':'local-service-factory-dev'}}
        self.assertEqual(software.publication_target(moved,{'target':'legacy-software'}),('eish1997','local-service-factory-dev'))
        for request in ({'target':'arbitrary'},{'target':'https://example.com'}):
            with self.assertRaises(ValueError):software.publication_repo(cfg,request)
        with self.assertRaises(ValueError):software.publication_repo({**cfg,'owner':'other'},{'target':'legacy-software'})
        for legacy in ({'owner':'new-owner','repo':'new-repo'},{'owner':'','repo':'old'}):
            with self.assertRaises(ValueError):software.publication_target({**moved,'legacy_software_repository':legacy},{'target':'legacy-software'})
        with self.assertRaises(ValueError):software.publication_target({**moved,'legacy_software_repository':'invalid'},{'target':'legacy-software'})
