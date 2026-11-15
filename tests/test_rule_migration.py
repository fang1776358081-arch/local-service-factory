import base64,json,os,unittest
from unittest.mock import patch
from urllib.error import HTTPError
from tools import rule_updates as rules,update_protocol as protocol
from tests import test_rule_updates as fixtures

class RuleMigrationTests(unittest.TestCase):
    setUp=fixtures.RuleUpdates.setUp
    bundle=fixtures.RuleUpdates.bundle

    def fixture(self):
        self.cfg.update(owner='eish1997',rules_repo='local-service-factory-dev')
        envelope,data=self.bundle(version='200')
        payload=envelope['payload'];payload['url']='https://github.com/eish1997/local-service-factory-rules/releases/download/rules-200/rules.zip'
        envelope['signature']=base64.b64encode(self.key.sign(protocol.canonical(payload))).decode()
        return envelope,data

    def test_initialize_preserves_old_head_and_requires_higher_version(self):
        envelope,data=self.fixture()
        with patch.dict(os.environ,{},clear=True),patch.object(rules.paths,'data_root',return_value=self.home),patch.object(protocol,'github',side_effect=lambda *a,**k:None if '/contents/' in a[1] else {'default_branch':'main'}),patch.object(protocol,'download',return_value=protocol.canonical({'sha':'old-index','content':base64.b64encode(protocol.canonical(envelope)).decode()})),patch.object(rules,'release_source_sha',return_value='a'*40):
            old=rules.local()/'remote_head.json';old.parent.mkdir(parents=True);old.write_text('{"sha":"legacy"}',encoding='utf-8')
            for version in ('199','200'):
                with self.assertRaises(ValueError):rules.release_plan({'version':version,'migration_from_legacy':True})
            result=rules.release_plan({'version':'201','migration_from_legacy':True})
            self.assertIsNone(result['base_sha']);self.assertEqual(result['migration']['version_floor'],'200');self.assertTrue(result['api_called'])
            self.assertEqual(old.read_text(encoding='utf-8'),'{"sha":"legacy"}')
            payload=json.loads((rules.local()/'release_plans/201/payload.json').read_text(encoding='utf-8'))
            self.assertIn('/local-service-factory-dev/',payload['url']);self.assertEqual(payload['version'],'201')

    def test_existing_index_forbidden_network_and_bad_signature_are_not_empty(self):
        envelope,data=self.fixture()
        with patch.dict(os.environ,{},clear=True):
            for response in ({'sha':'exists'},HTTPError('https://api.github.com',403,'forbidden',{},None),TimeoutError('offline')):
                with patch.object(protocol,'github',side_effect=[{'default_branch':'main'},response]),patch.object(rules,'remote_index') as old:
                    with self.assertRaises((ValueError,HTTPError,TimeoutError)):rules.migration_head(self.cfg)
                    old.assert_not_called()
            envelope['payload']['version']='999'
            with patch.object(protocol,'github',side_effect=[{'default_branch':'main'},None]),patch.object(protocol,'download',return_value=protocol.canonical({'sha':'old','content':base64.b64encode(protocol.canonical(envelope)).decode()})):
                with self.assertRaisesRegex(ValueError,'签名'):rules.migration_head(self.cfg)

    def test_legacy_advances_after_plan_and_blocks_all_writes(self):
        from cryptography.hazmat.primitives.serialization import Encoding,PrivateFormat,NoEncryption
        envelope,data=self.fixture()
        keyfile=self.home/'test-key.pem';keyfile.write_bytes(self.key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()))
        def api(method,url,*args,**kwargs):
            if '/commits/' in url:return {'sha':'a'*40}
            return None if '/contents/' in url else {'default_branch':'main'}
        def download(*args,**kwargs):return protocol.canonical({'sha':'old-index','content':base64.b64encode(protocol.canonical(envelope)).decode()})
        with patch.dict(os.environ,{'FACTORY_RELEASE_KEY_FILE':str(keyfile),'FACTORY_RELEASE_KEY_ID':'test'},clear=True),patch.object(rules.paths,'data_root',return_value=self.home),patch.object(protocol,'github',side_effect=api) as github,patch.object(protocol,'download',side_effect=download),patch.object(rules,'release_source_sha',return_value='a'*40):
            rules.release_plan({'version':'201','migration_from_legacy':True})
            envelope['payload']['version']='202'
            envelope['payload']['url']=envelope['payload']['url'].replace('rules-200','rules-202')
            envelope['signature']=base64.b64encode(self.key.sign(protocol.canonical(envelope['payload']))).decode()
            with self.assertRaisesRegex(ValueError,'旧仓版本已推进'):rules.publish({'version':'201','authorization':'publish_project_update'})
            self.assertTrue(all(call.args[0]=='GET' for call in github.call_args_list))

    def test_unified_empty_cache_requires_explicit_migration(self):
        self.cfg.update(owner='eish1997',rules_repo='local-service-factory-dev')
        with patch.dict(os.environ,{},clear=True),patch.object(rules.paths,'data_root',return_value=self.home),patch.object(rules,'export_documents') as export:
            with self.assertRaisesRegex(ValueError,'显式'):rules.release_plan({'version':'201'})
            export.assert_not_called()

    def test_cross_owner_migration_uses_explicit_old_unified_repository(self):
        self.cfg.update(owner='new-owner',rules_repo='new-repo',legacy_rules_repository={'owner':'eish1997','repo':'local-service-factory-dev'})
        envelope,data=self.bundle(version='200')
        envelope['payload']['url']='https://github.com/eish1997/local-service-factory-dev/releases/download/rules-200/rules.zip'
        envelope['signature']=base64.b64encode(self.key.sign(protocol.canonical(envelope['payload']))).decode()
        seen=[]
        def remote(old_cfg):
            seen.append((old_cfg['owner'],old_cfg['rules_repo']))
            return 'old-index',envelope,envelope['payload']
        with patch.dict(os.environ,{},clear=True),patch.object(rules.paths,'data_root',return_value=self.home),patch.object(protocol,'github',side_effect=lambda method,url,*a,**k:None if '/contents/' in url else {'default_branch':'main'}),patch.object(rules,'remote_index',side_effect=remote),patch.object(rules,'release_source_sha',return_value='a'*40):
            result=rules.release_plan({'version':'201','migration_from_legacy':True})
        self.assertEqual(seen,[('eish1997','local-service-factory-dev')])
        self.assertEqual(result['changed_files'],[])
        self.assertEqual(result['migration']['from_repository'],{'owner':'eish1997','repo':'local-service-factory-dev'})
        payload=json.loads((rules.local()/'release_plans/201/payload.json').read_text(encoding='utf-8'))
        self.assertEqual(payload['url'],'https://github.com/new-owner/new-repo/releases/download/rules-201/rules.zip')
        with self.assertRaises(ValueError):rules.migration_source({**self.cfg,'legacy_rules_repository':'invalid'})
