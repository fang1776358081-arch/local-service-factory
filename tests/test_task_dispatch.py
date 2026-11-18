"""Isolated dispatch/control invariants, with no provider requests."""
import collections
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import unittest
from unittest.mock import patch
from tests.test_shared_tasks import SharedTasks
from tests.test_task_continuation import TaskContinuation
from tools import task_library as lib,task_worker as worker,task_scheduler as scheduler


class UnitDispatch(unittest.TestCase):
    setUp=SharedTasks.setUp
    batch=SharedTasks.batch
    request=SharedTasks.request
    ready=SharedTasks.ready
    payload=TaskContinuation.payload

    def task(self,unit_ids=None):
        b=self.batch();request=self.request(b,[1])
        if unit_ids is not None:request['unit_ids']=unit_ids
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            plan=lib.plan(request)
            task=lib.start({**request,'plan_sha256':plan['plan_sha256'],'request_id':'dispatch','authorization':'execute_selected_groups'})
        target={'category':b['category'],'batch':b['id'],'task':task['id']}
        return b,task,target,lib.batch_dir(b['category'],b['id'])/'tasks'/task['id']/'task.json'

    def test_fair_turns_and_global_slot_lease(self):
        a={'category':'road_rescue','batch':'a','id':'a','slots':[1,2]};b={**a,'batch':'b','id':'b'}
        tickets=[scheduler.register(a,'a1',[1]),scheduler.register(a,'a2',[1]),scheduler.register(b,'b1',[1])]
        self.addCleanup(lambda:[scheduler.unregister(t) for t in tickets])
        self.assertIsNone(scheduler.claim(tickets[2],[1]))
        slot,lease=scheduler.claim(tickets[0],[1]);self.assertEqual(slot,1)
        try:self.assertIsNone(scheduler.claim(tickets[2],[1]))
        finally:lease.__exit__(None,None,None)
        self.assertIsNone(scheduler.claim(tickets[1],[1]))
        slot,lease=scheduler.claim(tickets[2],[1]);lease.__exit__(None,None,None)
        slot,lease=scheduler.claim(tickets[1],[1]);lease.__exit__(None,None,None)
        with self.assertRaises(ValueError):scheduler.register(a,'a3',[3])

    def test_fifty_local_contenders_do_not_fight_over_filesystem_lock(self):
        slots=list(range(1,51));state={'category':'road_rescue','batch':'stress','id':'stress','slots':slots}
        barrier=threading.Barrier(50)
        def dispatch(slot):
            barrier.wait(timeout=8)
            token=scheduler.register(state,f'u{slot:02d}',[slot])
            claimed=scheduler.claim(token,[slot])
            self.assertIsNotNone(claimed)
            actual,lease=claimed
            try:self.assertEqual(actual,slot)
            finally:lease.__exit__(None,None,None)
            scheduler.unregister(token)
            return actual
        with ThreadPoolExecutor(max_workers=50) as pool:
            self.assertEqual(sorted(pool.map(dispatch,slots)),slots)

    def test_slow_request_does_not_hold_next_dispatch(self):
        b,task,target,file=self.task();third=threading.Event();guard=threading.Lock();count=[0];observed=[]
        def generate(*args):
            with guard:count[0]+=1;number=count[0]
            if number==1:observed.append(third.wait(8))
            if number==3:third.set()
            return self.payload()
        worker.run(b['category'],b['id'],task['id'],generate=generate,clients=[(1,object()),(2,object())],render=lambda *a:None)
        self.assertEqual(observed,[True]);self.assertEqual(lib.read(file)['requests_used'],7)
        self.assertEqual(lib.read(file)['status'],'completed')

    def test_unit_pause_only_stops_selected_material_and_resumes_same_budget(self):
        b,task,target,file=self.task();units=lib.selected(lib.batch_dir(b['category'],b['id']),b,[1])[0]['units'];paused=units[0];calls=[]
        lib.pause({**target,'unit_ids':[paused['id']]})
        def generate(c,cfg,prompt):
            calls.append(prompt)
            return self.payload()
        worker.run(b['category'],b['id'],task['id'],generate=generate,clients=[(1,object())],render=lambda *a:None)
        state=lib.read(file);self.assertEqual(state['status'],'paused');self.assertEqual(state['requests_used'],6)
        self.assertNotIn(paused['prompt'],calls)
        with self.ready(),patch.object(lib,'launch',return_value=99999999):lib.resume({**target,'unit_ids':[paused['id']]})
        worker.run(b['category'],b['id'],task['id'],generate=generate,clients=[(1,object())],render=lambda *a:None)
        self.assertEqual(lib.read(file)['requests_used'],7);self.assertEqual(lib.read(file)['status'],'completed')
        self.assertEqual(collections.Counter(calls)[paused['prompt']],1)

    def test_transient_cooldown_is_persisted_and_respected(self):
        b,task,target,file=self.task(['g0001_u01']);times=[]
        def generate(*a):
            times.append(time.time())
            if len(times)==1:raise TimeoutError('timed out')
            return self.payload()
        worker.run(b['category'],b['id'],task['id'],generate=generate,clients=[(1,object())],render=lambda *a:None)
        self.assertGreaterEqual(times[1]-times[0],1.9)
        self.assertEqual(lib.read(file)['requests_used'],2)

    def test_single_resume_of_global_pause_keeps_other_cards_paused(self):
        b,task,target,file=self.task();unit=lib.selected(lib.batch_dir(b['category'],b['id']),b,[1])[0]['units'][0]
        lib.pause(target)
        with self.ready(),patch.object(lib,'launch',return_value=99999999):lib.resume({**target,'unit_ids':[unit['id']]})
        calls=[]
        worker.run(b['category'],b['id'],task['id'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())],render=lambda *a:None)
        self.assertEqual(calls,[unit['prompt']]);self.assertEqual(lib.read(file)['requests_used'],1)
        self.assertEqual(lib.read(file)['resume_summary']['paused_count'],6)
        with self.ready(),patch.object(lib,'launch',return_value=99999999):lib.resume(target)
        worker.run(b['category'],b['id'],task['id'],generate=lambda *a:self.payload(),clients=[(1,object())],render=lambda *a:None)
        self.assertEqual(lib.read(file)['requests_used'],7)

    def test_resume_during_final_render_is_not_lost(self):
        b,task,target,file=self.task();units=lib.selected(lib.batch_dir(b['category'],b['id']),b,[1])[0]['units']
        in_final=threading.Event();release=threading.Event();renders=[];calls=[]
        def generate(c,cfg,p):
            calls.append(p)
            if len(calls)==1:lib.pause(target)
            return self.payload()
        def render(*args):
            renders.append(1)
            if len(renders)==2:in_final.set();self.assertTrue(release.wait(8))
        errors=[]
        def run():
            try:worker.run(b['category'],b['id'],task['id'],generate=generate,clients=[(1,object())],render=render)
            except Exception as e:errors.append(e)
        thread=threading.Thread(target=run);thread.start()
        try:
            self.assertTrue(in_final.wait(8))
            with self.ready(),patch.object(lib,'launch',side_effect=AssertionError('existing owner must finish')):
                lib.resume({**target,'unit_ids':[units[1]['id']]})
        finally:release.set();thread.join(12)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertEqual(calls,[units[0]['prompt'],units[1]['prompt']])
        self.assertEqual(lib.read(file)['requests_used'],2)

    def test_scheduler_error_skips_one_unit(self):
        b,task,target,file=self.task();units=lib.selected(lib.batch_dir(b['category'],b['id']),b,[1])[0]['units'];bad=units[0];calls=[]
        original=scheduler.register
        def register(state,uid,slots):
            if uid==bad['id']:raise ValueError('派发槽位超出冻结许可')
            return original(state,uid,slots)
        with patch.object(scheduler,'register',side_effect=register):
            worker.run(b['category'],b['id'],task['id'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())],render=lambda *a:None)
        state=lib.read(file)
        self.assertNotEqual(state['status'],'failed')
        self.assertNotIn(bad['prompt'],calls)
        self.assertEqual(len(calls),len(units)-1)
        self.assertEqual(state['requests_used'],len(units)-1)
        self.assertEqual(state['attempts'].get(bad['id'],0),0)
        for unit in units[1:]:
            self.assertTrue(worker.raw_valid(b['category'],b['id'],1,unit))
