"""Offline raw-unit scope and board invariants; no paid production."""
import io
import unittest
from unittest.mock import patch
from PIL import Image
from tests.test_shared_tasks import SharedTasks
from tools import task_library as lib,task_worker as worker,task_queue as queue


class RawQueue(unittest.TestCase):
    setUp=SharedTasks.setUp
    batch=SharedTasks.batch
    request=SharedTasks.request
    ready=SharedTasks.ready

    def payload(self):
        out=io.BytesIO();Image.new('RGB',(1024,1536),(50,70,90)).save(out,format='PNG');return out.getvalue()

    def test_large_board_counts_all_cards_and_three_triptych_panels(self):
        b=self.batch(count=43)
        result=queue.view({'category':b['category'],'batch':b['id'],'limit':3})
        self.assertEqual(result['total'],301)
        self.assertEqual(result['counts'],{'pending':301,'ongoing':0,'completed':0})
        self.assertTrue(result['has_more'])
        panels=queue.view({'category':b['category'],'batch':b['id'],'limit':7})['cards']
        self.assertEqual(sum(c['kind']=='triptych_panel' for c in panels),3)
        self.assertEqual(len({c['id'] for c in panels}),7)

    def test_large_multiple_batches_new_process_preserves_all_canonical_ids(self):
        import json,subprocess,sys
        batches=[self.batch(count=43),self.batch(count=43),self.batch('truck_rescue')]
        before=queue.view({'summary_only':True})
        self.assertEqual((before['total'],before['counts']['pending']),(609,609))
        original=[]
        for offset in range(0,609,200):original.extend(c['id'] for c in queue.view({'offset':offset,'limit':200})['cards'])
        self.assertEqual(len(set(original)),609)
        for batch in batches:
            scoped=queue.view({'category':batch['category'],'batch':batch['id'],'summary_only':True})
            self.assertEqual(scoped['total'],batch['count']*7)
        code="import sys,json;from pathlib import Path;from tools import task_library as l,task_queue as q;l.ROOT=Path(sys.argv[1]);s=q.view({'summary_only':True});ids=[]\nfor offset in range(0,s['total'],200):ids.extend(c['id'] for c in q.view({'offset':offset,'limit':200})['cards'])\nprint(json.dumps({'total':s['total'],'counts':s['counts'],'ids':sorted(ids)}))"
        fresh=subprocess.run([sys.executable,'-X','utf8','-c',code,str(self.root)],capture_output=True,text=True,timeout=40,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(fresh.returncode,0,fresh.stderr[-1500:]);result=json.loads(fresh.stdout)
        self.assertEqual(result['ids'],sorted(original));self.assertEqual(result['counts'],before['counts'])

    def test_single_unit_licence_two_disjoint_tasks_and_stable_card(self):
        b=self.batch();base={'category':b['category'],'batch':b['id'],'auto_complete':False}
        before=queue.view(base)['cards'];calls=[]
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            tasks=[]
            for n in (1,2):
                req={**base,'unit_ids':[f'g0001_u{n:02d}']};p=lib.plan(req)
                self.assertEqual(p['pending_count'],1);self.assertEqual(p['max_requests'],2)
                tasks.append(lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':f'unit-{n}','authorization':'execute_selected_groups'}))
            t=tasks[0]
            worker.run(b['category'],b['id'],t['id'],generate=lambda *a:(calls.append(a[-1]) or self.payload()),clients=[(1,object())],render=lambda *a:None)
            self.assertEqual(len(calls),1)
            file=lib.batch_dir(b['category'],b['id'])/'tasks'/t['id']/'task.json'
            state=lib.read(file);self.assertEqual(state['completed_units'],1)
            lic=lib.read(file.parent/'license.json');self.assertEqual(lic['terms']['unit_ids'],['g0001_u01'])
            changed={**state,'unit_ids':['g0001_u02']}
            with self.assertRaises(ValueError):lib.synchronize_license(file,changed)
        after=queue.view(base)
        self.assertEqual([c['id'] for c in before],[c['id'] for c in after['cards']])
        self.assertEqual(after['counts']['completed'],1)
        self.assertEqual(after['total'],7)

    def test_scope_rejects_unknown_duplicate_and_outside_group(self):
        b=self.batch(count=2);base=self.request(b,[1])
        with self.ready():
            for ids in ([],['g0001_u01','g0001_u01'],['g0002_u01'],['../../file'],['g0001_u99']):
                with self.assertRaises(ValueError):lib.plan({**base,'unit_ids':ids})

    def test_revision_maps_to_original_card_ids(self):
        from tools.task_actions import prepare_replacement
        b=self.batch();req=self.request(b,[1]);before=queue.view(req)
        revision=prepare_replacement({**req,'group':1,'position':2,'request_id':'revision'})
        path,data=lib.load_batch(b['category'],revision['id']);rows=lib.selected(path,data,[1])
        keys=queue.origin_keys(b['category'],revision['id'],rows)
        original=lib.selected(lib.batch_dir(b['category'],b['id']),b,[1])[0]['units']
        self.assertEqual(keys,{(b['id'],1,u['id']) for u in original if u['delivery_position']==2})
        self.assertEqual(queue.view(req)['total'],before['total'])

    def test_mixed_repair_sources_complete_triptych_in_frozen_order(self):
        import hashlib
        from tools.task_actions import prepare_replacement
        b=self.batch();req=self.request(b,[1]);path=lib.batch_dir(b['category'],b['id']);row=lib.selected(path,b,[1])[0]
        panels=[u for u in row['units'] if u['kind']=='triptych_panel']
        revision=prepare_replacement({**req,'group':1,'position':2,'mode':'repair','request_id':'mixed'})
        child=lib.selected(lib.batch_dir(b['category'],revision['id']),revision,[1])[0]['units']
        expected=[]
        for i,u in enumerate(panels):
            sb=revision['id'] if i==0 else b['id'];su=child[0] if i==0 else u
            raw=lib.unit_raw(b['category'],sb,1,su);raw.parent.mkdir(parents=True,exist_ok=True);raw.write_bytes(self.payload())
            lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':su['prompt_sha256'],'raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest()})
            expected.append(raw)
        self.assertTrue(all(worker.raw_valid(b['category'],b['id'],1,u) for u in panels))
        captured=[]
        def render(*args,**kwargs):captured.append((args,kwargs))
        with patch.object(worker,'render_delivery',side_effect=render):
            errors=worker.materialize(b['category'],b['id'],b,[{**row,'units':panels}],lib.read(path/'snapshot.json'))
        self.assertFalse(errors);self.assertEqual(len(captured),1)
        args,kwargs=captured[0];self.assertEqual(args[8],5)
        self.assertEqual([kwargs['raw_sources'][u['id']] for u in panels],expected)

    def test_submitted_waiting_stays_pending(self):
        import os
        b=self.batch();req={**self.request(b,[1]),'unit_ids':['g0001_u01']}
        with self.ready(),patch.object(lib,'launch',return_value=os.getpid()):
            p=lib.plan(req);lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'submitted','authorization':'execute_selected_groups'})
        result=queue.view(req);card=next(c for c in result['cards'] if c['unit']=='g0001_u01')
        self.assertEqual((card['column'],card['stage']),('pending','submitted_waiting'));self.assertEqual(result['executor_active'],0)

    def failed_cover(self,b,auto_complete=False):
        req={**self.request(b,[1]),'unit_ids':['g0001_u01']}
        req['auto_complete']=auto_complete
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            planned=lib.plan(req)
            task=lib.start({**req,'plan_sha256':planned['plan_sha256'],'request_id':'failed-cover','authorization':'execute_selected_groups'})
            def generate(*args):raise TimeoutError('timed out')
            worker.run(b['category'],b['id'],task['id'],generate=generate,clients=[(1,object())],render=lambda *a:None)
        return req,task

    def test_retry_waiting_keeps_original_card_ongoing(self):
        import os
        from tools.task_actions import prepare_replacement
        b=self.batch();req,task=self.failed_cover(b)
        before=queue.view(req)['cards'][0]
        child=prepare_replacement({**req,'group':1,'position':1,'mode':'repair','request_id':'queued-repair'})
        child_req={**self.request(child,[1]),'category':b['category']}
        with self.ready(),patch.object(lib,'launch',return_value=os.getpid()):
            planned=lib.plan(child_req)
            lib.start({**child_req,'plan_sha256':planned['plan_sha256'],'request_id':'queued-child','authorization':'execute_selected_groups'})
        result=queue.view(req);card=result['cards'][0]
        self.assertEqual(card['id'],before['id'])
        self.assertEqual((card['column'],card['stage'],card['attempts']),('ongoing','submitted_waiting',2))
        self.assertEqual((result['total'],result['executor_active'],result['counts']['completed']),(7,0,0))

    def test_cancelled_licence_keeps_surviving_card_history_without_control(self):
        from tools.task_actions import delete
        from tools.task_queue_details import view as detail
        b=self.batch();req,task=self.failed_cover(b)
        licence=lib.batch_dir(b['category'],b['id'])/'tasks'/task['id']/'license.json'
        evidence=licence.read_bytes();before=queue.view(req)['cards'][0]
        delete({'category':b['category'],'batch':b['id'],'scope':'image','group':1,'position':3,'authorization':'delete_selected'})
        result=queue.view(req);card=result['cards'][0]
        self.assertEqual((card['id'],card['attempts']),(before['id'],2))
        self.assertEqual((card['column'],card['reason'],card['task']),('ongoing','cancelled_task',None))
        self.assertEqual((result['total'],result['counts']['completed']),(6,0))
        self.assertEqual(licence.read_bytes(),evidence)
        records=detail({'category':b['category'],'batch':b['id'],'unit':card['unit']})
        self.assertEqual(records['licences'][0]['used'],2)
        self.assertEqual(records['licences'][0]['status'],'cancelled')
        self.assertIn('重新查看执行计划',records['next_action'])

    def test_cancelled_parent_does_not_become_automatic_child_control(self):
        from tools.task_actions import delete
        from tools.task_queue_details import view as detail
        b=self.batch();req,task=self.failed_cover(b,auto_complete=True)
        before=queue.view(req)['cards'][0]
        self.assertEqual(before['attempts'],6)
        delete({'category':b['category'],'batch':b['id'],'scope':'image','group':1,'position':3,'authorization':'delete_selected'})
        card=queue.view(req)['cards'][0]
        self.assertEqual((card['column'],card['attempts'],card['reason'],card['task']),('ongoing',6,'cancelled_task',None))
        self.assertEqual(card['id'],before['id'])
        records=detail({'category':b['category'],'batch':b['id'],'unit':card['unit']})
        self.assertEqual(sum(l['used'] for l in records['licences']),6)
        self.assertIn('不能继续被取消的任务',records['next_action'])

    def test_multi_page_snapshot_and_summary_share_counts_and_read_manifests_once(self):
        b=self.batch(count=43);request={'category':b['category'],'batch':b['id']}
        pages=[{'column':'pending','offset':0,'limit':120},{'column':'pending','offset':120,'limit':181},
               {'column':'completed','offset':0,'limit':60},{'column':'ongoing','offset':0,'limit':60}]
        with patch.object(lib,'selected',wraps=lib.selected) as reads:
            result=queue.view({**request,'pages':pages})
        self.assertEqual(reads.call_count,1)
        self.assertEqual(result['counts'],{'pending':301,'ongoing':0,'completed':0})
        self.assertEqual(len(result['pages'][0]['cards']),120)
        self.assertEqual(len(result['pages'][1]['cards']),181)
        self.assertFalse(result['pages'][1]['has_more'])
        self.assertEqual(len({c['id'] for p in result['pages'] for c in p['cards']}),301)
        self.assertEqual(result['cards'],[])
        summary=queue.view({**request,'summary_only':True})
        self.assertEqual(summary['cards'],[]);self.assertEqual(summary['counts'],result['counts'])
        self.assertEqual(summary['request_counts'],{'used':0,'maximum':0})
        for value in ([],[{'column':'pending','offset':-1,'limit':60}],[{'column':'invalid','offset':0,'limit':60}]):
            with self.assertRaises(ValueError):queue.view({**request,'pages':value})
        with self.assertRaises(ValueError):queue.view({**request,'summary_only':'true'})

    def test_latest_single_revision_does_not_replace_canonical_batch_statistics(self):
        from tools.task_actions import prepare_replacement
        b=self.batch();base={**self.request(b,[1]),'auto_complete':False}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            first=lib.plan(base);t=lib.start({**base,'plan_sha256':first['plan_sha256'],'request_id':'all','authorization':'execute_selected_groups'})
            worker.run(b['category'],b['id'],t['id'],generate=lambda *a:self.payload(),clients=[(1,object())],render=lambda *a:None)
            child=prepare_replacement({**base,'group':1,'position':3,'request_id':'single'})
            req={**base,'batch':child['id']};p=lib.plan(req)
            revision=lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'revision-start','authorization':'execute_selected_groups'})
            worker.run(b['category'],child['id'],revision['id'],generate=lambda *a:self.payload(),clients=[(1,object())],render=lambda *a:None)
        result=queue.view({'category':b['category'],'summary_only':True})
        self.assertEqual(result['total'],7);self.assertEqual(result['counts']['completed'],7)
        self.assertEqual(result['source_counts']['generated'],7)
        self.assertEqual(result['request_counts'],{'used':8,'maximum':16})

    def complete_one(self,b,token='one'):
        req={**self.request(b,[1]),'unit_ids':['g0001_u01'],'auto_complete':False}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            p=lib.plan(req);t=lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':token,'authorization':'execute_selected_groups'})
            worker.run(b['category'],b['id'],t['id'],generate=lambda *a:self.payload(),clients=[(1,object())],render=lambda *a:None)
        return req,t

    def test_deleted_completed_scope_does_not_break_global_summary(self):
        from tools.task_actions import delete
        b=self.batch(count=2);_,t=self.complete_one(b)
        file=lib.batch_dir(b['category'],b['id'])/'tasks'/t['id']/'license.json';ledger=file.read_bytes()
        delete({'category':b['category'],'batch':b['id'],'scope':'group','group':1,'authorization':'delete_selected'})
        result=queue.view({'category':b['category'],'summary_only':True})
        self.assertEqual(result['total'],7);self.assertEqual(result['counts']['pending'],7)
        self.assertEqual(result['request_counts'],{'used':1,'maximum':2});self.assertEqual(file.read_bytes(),ledger)

    def test_statistics_use_frozen_licence_and_reserved_attempts_without_writeback(self):
        b=self.batch();_,t=self.complete_one(b)
        path=lib.batch_dir(b['category'],b['id'])/'tasks'/t['id'];state=lib.read(path/'task.json')
        for maximum in (999,2):
            with self.subTest(maximum=maximum):
                state.update(max_requests=maximum,attempts={},requests_used=0);lib.write(path/'task.json',state)
                original={name:(path/name).read_bytes() for name in ('task.json','license.json')}
                result=queue.view({'category':b['category']})
                self.assertEqual(result['request_counts'],{'used':1,'maximum':2})
                card=next(c for c in result['cards'] if c['unit']=='g0001_u01')
                self.assertEqual(card['attempts'],1);self.assertEqual(result['source_counts']['generated'],1)
                self.assertTrue(result['warnings'])
                self.assertTrue(all((path/name).read_bytes()==saved for name,saved in original.items()))

    def test_retained_is_auxiliary_to_original_generated_completion(self):
        b=self.batch();req,_=self.complete_one(b)
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            p=lib.plan(req);self.assertEqual(p['retained_count'],1)
            t=lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'retain','authorization':'execute_selected_groups'})
            worker.run(b['category'],b['id'],t['id'],generate=lambda *a:self.fail('retained raw must not generate'),clients=[],render=lambda *a:None)
        result=queue.view({'category':b['category'],'summary_only':True})
        self.assertEqual(result['counts']['completed'],1)
        self.assertEqual(result['source_counts'],{'library':0,'generated':1,'retained':1})
        self.assertEqual(result['request_counts'],{'used':1,'maximum':2})

    def test_worker_revision_source_scope_does_not_expand_to_other_groups(self):
        b=self.batch(count=2);path=lib.batch_dir(b['category'],b['id']);unit=lib.selected(path,b,[1])[0]['units'][0]
        other=lib.read(path/'groups'/'0002.json');other['units'][0]['prompt']='corrupt unrelated group';lib.write(path/'groups'/'0002.json',other)
        candidates=list(queue.revision_units(b['category'],b['id'],1,unit,[]))
        self.assertEqual(candidates,[(b['id'],1,unit)])
        self.assertEqual(queue.origin_keys(b['category'],b['id'],[{'group':1,'units':[unit]}]),{(b['id'],1,unit['id'])})

    def test_read_context_paths_and_controls_are_per_query_not_per_card(self):
        import os
        from tools import task_assets,task_controls
        b=self.batch(count=43);req={**self.request(b,[1]),'auto_complete':False}
        with self.ready(),patch.object(lib,'launch',return_value=os.getpid()):
            p=lib.plan(req);lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'path-memo','authorization':'execute_selected_groups'})
        with patch.object(task_assets,'batch_root',wraps=task_assets.batch_root) as roots,patch.object(lib,'load_batch',wraps=lib.load_batch) as batches,patch.object(task_controls,'paused',wraps=task_controls.paused) as controls:
            result=queue.view({'category':b['category'],'batch':b['id'],'summary_only':True})
        self.assertEqual(result['total'],301)
        self.assertEqual(roots.call_count,1);self.assertEqual(batches.call_count,1);self.assertEqual(controls.call_count,1)
        context=queue.ReadContext();unit=lib.selected(lib.batch_dir(b['category'],b['id']),b,[1])[0]['units'][0]
        self.assertEqual(context.raw(b['category'],b['id'],1,unit),lib.unit_raw(b['category'],b['id'],1,unit))
        self.assertEqual(context.delivery(b['category'],b['id'],1,1,'cover'),lib.delivery_path(b['category'],b['id'],1,1,'cover'))

    def test_large_plan_reuses_one_raw_resolution_context(self):
        b=self.batch(count=43);req=self.request(b,list(range(1,44)))
        contexts=[];original=worker.raw_valid
        def capture(*args,**kwargs):
            contexts.append(kwargs.get('_context'))
            return original(*args,**kwargs)
        with self.ready(),patch.object(worker,'raw_valid',side_effect=capture):
            result=lib.plan(req)
        self.assertEqual(result['pending_count'],301)
        self.assertEqual(len(contexts),301)
        self.assertIsNotNone(contexts[0])
        self.assertEqual(len({id(context) for context in contexts}),1)

    def test_new_read_context_rechecks_registered_asset_root(self):
        b=self.batch();context=queue.ReadContext();old=context.output(b['category'],b['id'])
        directory=self.root/'custom-assets';directory.mkdir()
        path=lib.batch_dir(b['category'],b['id']);saved=lib.read(path/'batch.json');saved['asset_root']=str(directory);lib.write(path/'batch.json',saved)
        with self.assertRaisesRegex(ValueError,'未登记'):queue.ReadContext().output(b['category'],b['id'])
        lib.write(self.root/'.runtime/asset_settings.json',{'path':str(directory),'previous_paths':[]})
        fresh=queue.ReadContext().output(b['category'],b['id'])
        self.assertNotEqual(old,fresh);self.assertEqual(fresh,lib.output_dir(b['category'],b['id']))

    def test_conditional_read_rechecks_evidence_and_window_scope(self):
        import hashlib
        b=self.batch();req,_=self.complete_one(b);scope={'category':b['category'],'batch':b['id']}
        pages=[{'column':'pending','offset':0,'limit':60},{'column':'completed','offset':0,'limit':60}]
        first=queue.view({**scope,'pages':pages});same=queue.view({**scope,'pages':pages,'since':first['revision']})
        self.assertTrue(same['unchanged']);self.assertEqual(same['pages'],[]);self.assertEqual(same['counts'],first['counts'])
        for change in ({'pages':[{'column':'pending','offset':0,'limit':2}]},{'summary_only':True},{'column':'completed'}):
            self.assertFalse(queue.view({**scope,**change,'since':first['revision']})['unchanged'])
        unit=lib.selected(lib.batch_dir(b['category'],b['id']),b,[1])[0]['units'][0];raw=lib.unit_raw(b['category'],b['id'],1,unit)
        out=io.BytesIO();Image.new('RGB',(1024,1536),(190,20,80)).save(out,format='PNG');raw.write_bytes(out.getvalue())
        receipt=lib.read(raw.with_suffix('.receipt.json'));receipt['raw_sha256']=hashlib.sha256(out.getvalue()).hexdigest();lib.write(raw.with_suffix('.receipt.json'),receipt)
        changed=queue.view({**scope,'pages':pages,'since':first['revision']})
        self.assertFalse(changed['unchanged']);self.assertEqual(changed['counts'],first['counts'])
        raw.write_bytes(b'broken')
        invalid=queue.view({**scope,'pages':pages,'since':changed['revision']})
        self.assertFalse(invalid['unchanged']);self.assertEqual(invalid['counts']['completed'],0)
        for value in ('bad','a'*65,False):
            with self.assertRaises(ValueError):queue.view({**scope,'since':value})


if __name__=='__main__':unittest.main()
