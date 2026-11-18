"""Bounded offline tests for the shared Agent/dashboard workflow."""
import copy
import io
import json
from pathlib import Path
import threading
import unittest
import uuid
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from tools import task_library as lib,task_worker as worker,variable_catalog as vc

class SharedTasks(unittest.TestCase):
 def setUp(self):
  self.configs={p['id']:lib.business_config(p['id']) for p in vc.projects()}
  self.root=lib.ROOT/'.runtime'/('shared-task-test-'+uuid.uuid4().hex);self.root.mkdir()
  self.patches=[patch.object(lib,'ROOT',self.root),patch.object(lib,'business_config',side_effect=lambda c:copy.deepcopy(self.configs[c])),patch.object(lib,'confirmed_phone',return_value='15795643941')]
  for p in self.patches:p.start()
  self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)])
 def batch(self,category='road_rescue',count=1,source='agent'):
  return lib.assemble({'category':category,'count':count,'seed':1401,'phone':'15795643941','source':source})
 def request(self,b,groups):return {'category':b['category'],'batch':b['id'],'groups':groups,'auto_complete':False}
 def ready(self):
  return patch.multiple(lib,api_config=lambda:{'model':'offline-test','api_size':'1024x1536','quality':'medium','output_format':'png'},readiness=lambda *a:([],[1,2,3,4]))
 def test_all_eight_sources_produce_identical_frozen_groups(self):
  for p in vc.projects():
   definition=vc.read_json(vc.project_dir(p['id'])/'project.json')
   if definition.get('assembly_blocked'):
    with self.assertRaises(ValueError): self.batch(p['id'])
    continue
   a=self.batch(p['id'],source='agent');b=self.batch(p['id'],source='dashboard')
   self.assertEqual(a['manifest_sha256'],b['manifest_sha256'],p['id'])
   av=lib.view({**self.request(a,[1]),'limit':1});bv=lib.view({**self.request(b,[1]),'limit':1})
   self.assertEqual(av['groups'][0]['units'],bv['groups'][0]['units'])
   self.assertEqual(av['groups'][0]['images'],[])
 def test_invalid_quantity_idempotent_assembly_and_tampering(self):
  for count in [0,101,True,'10']:
   with self.assertRaises(ValueError):lib.assemble({'category':'road_rescue','count':count})
  req={'category':'road_rescue','count':1,'seed':1401,'phone':'15795643941','request_id':'same-assembly'}
  a=lib.assemble(req);b=lib.assemble(req);self.assertEqual(a['id'],b['id'])
  with self.assertRaises(ValueError):lib.assemble({**req,'count':2})
  path=lib.batch_dir('road_rescue',a['id']);row=lib.read(path/'groups/0001.json');row['units'][0]['prompt']='changed';lib.write(path/'groups/0001.json',row)
  with self.ready(),self.assertRaises(ValueError):lib.plan(self.request(a,[1]))
 def test_mobile_required_and_batch_name(self):
  with self.assertRaises(ValueError):lib.assemble({'category':'road_rescue','count':1})
  for phone in [None,'','123','400-123-4567']:
   with self.assertRaisesRegex(ValueError,'11 位手机号'):
    lib.assemble({'category':'road_rescue','count':1,'phone':phone})
  self.assertEqual(lib.batches('road_rescue'),[])
  a=self.batch()
  self.assertIn('15795643941',a['id'])
  self.assertIn('15795643941',a['name'])
  req={'category':'road_rescue','count':1,'seed':1401,'phone':'13800138000','request_id':'other-phone'}
  b=lib.assemble(req)
  snapshot=lib.read(lib.batch_dir(b['category'],b['id'])/'snapshot.json')
  lib.validate_batch_phone(b['category'],b,snapshot)
  self.assertEqual(snapshot['batch_contact']['phone'],'13800138000')
  with self.assertRaises(ValueError):lib.assemble({**req,'phone':'15795643941'})
 def test_atomic_save_retries_temporary_windows_reader_lock(self):
  original=lib.os.replace;calls=[]
  def replace(a,b):
   calls.append(1)
   if len(calls)<3:raise PermissionError('temporary sharing violation')
   return original(a,b)
  with patch.object(lib.os,'replace',side_effect=replace):lib.write(self.root/'atomic.json',{'ok':True})
  self.assertEqual(lib.read(self.root/'atomic.json'),{'ok':True});self.assertEqual(len(calls),3)
 def test_non_contiguous_selection_shared_start_resume_and_budget(self):
  b=self.batch(count=3);req=self.request(b,[1,3]);captures=[]
  with self.ready(),patch.object(lib,'launch',return_value=99999999) as launch:
   p=lib.plan(req)
   self.assertEqual(p['pending_count'],14);self.assertEqual(p['max_requests'],28)
   start={**req,'plan_sha256':p['plan_sha256'],'request_id':'execution-one','authorization':'execute_selected_groups'}
   task=lib.start(start);self.assertEqual(lib.start({**start,'source':'dashboard'})['id'],task['id']);self.assertEqual(launch.call_count,1)
   self.assertTrue(lib.plan(req)['blocks'])
   calls=[]
   def generate(client,config,prompt):
    calls.append(prompt)
    if len(calls)<=3:raise TimeoutError('timed out')
    captures.append(prompt);out=io.BytesIO();Image.new('RGB',(1024,1536),(40+len(captures),60,70)).save(out,format='PNG');return out.getvalue()
   worker.run(b['category'],b['id'],task['id'],generate=generate,clients=[(1,object()),(2,object())],render=lambda *args:None)
   done=lib.read(lib.batch_dir(b['category'],b['id'])/'tasks'/task['id']/'task.json')
   self.assertEqual(done['status'],'completed');self.assertEqual(done['requests_used'],17)
   self.assertTrue(all(n<=2 for n in done['attempts'].values()))
   expected={u['prompt'] for g in lib.selected(lib.batch_dir(b['category'],b['id']),b,[1,3]) for u in g['units']}
   self.assertEqual(set(captures),expected)
   self.assertFalse((lib.output_dir(b['category'],b['id'])/'group_0002').exists())
   self.assertEqual(lib.resume({'category':b['category'],'batch':b['id'],'task':task['id']})['requests_used'],17)
 def test_pause_finishes_inflight_and_retry_only_failed(self):
  b=self.batch();req=self.request(b,[1])
  with self.ready(),patch.object(lib,'launch',return_value=99999999):
   p=lib.plan(req);task=lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'queue-controls','authorization':'execute_selected_groups'})
   target={'category':b['category'],'batch':b['id'],'task':task['id']}
   file=lib.batch_dir(b['category'],b['id'])/'tasks'/task['id']/'task.json'
   def payload():
    out=io.BytesIO();Image.new('RGB',(1024,1536),(20,40,60)).save(out,format='PNG');return out.getvalue()
   def pause_inside(*args):lib.pause(target);return payload()
   worker.run(b['category'],b['id'],task['id'],generate=pause_inside,clients=[(1,object())],render=lambda *a:None)
   state=lib.read(file);self.assertEqual(state['requests_used'],1);self.assertEqual(state['status'],'paused');self.assertEqual(state['completed_units'],1)
   lib.resume(target)
   def fail(*args):lib.pause(target);raise TimeoutError('timed out')
   worker.run(b['category'],b['id'],task['id'],generate=fail,clients=[(1,object())],render=lambda *a:None)
   self.assertEqual(lib.read(file)['requests_used'],2)
   lib.dispatch('retry',target)
   worker.run(b['category'],b['id'],task['id'],generate=lambda *a:payload(),clients=[(1,object())],render=lambda *a:None)
   state=lib.read(file);self.assertEqual(state['requests_used'],3);self.assertEqual(state['completed_units'],2);self.assertEqual(state['status'],'paused')
   lib.resume(target)
   worker.run(b['category'],b['id'],task['id'],generate=lambda *a:payload(),clients=[(1,object())],render=lambda *a:None)
   state=lib.read(file);self.assertEqual(state['requests_used'],8);self.assertEqual(state['max_requests'],14);self.assertEqual(state['status'],'completed')
 def test_concurrent_start_budget_binding_and_uncertain_request(self):
  b=self.batch();req=self.request(b,[1]);barrier=threading.Barrier(2)
  with self.ready(),patch.object(lib,'launch',return_value=99999999) as launch:
   plan=lib.plan(req)
   def attempt(i):
    barrier.wait()
    try:return lib.start({**req,'request_id':'race-'+str(i),'plan_sha256':plan['plan_sha256'],'authorization':'execute_selected_groups'})
    except ValueError:return None
   with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(attempt,[1,2]))
   self.assertEqual(sum(r is not None for r in results),1);self.assertEqual(launch.call_count,1)
   task=next(r for r in results if r);file=lib.batch_dir(b['category'],b['id'])/'tasks'/task['id']/'task.json'
   changed=copy.deepcopy(task);changed['max_requests']+=1;lib.write(file,changed)
   with self.assertRaises(ValueError):lib.resume({'category':b['category'],'batch':b['id'],'task':task['id']})
   lib.write(file,task);lic=lib.read(file.parent/'license.json');lic['requests_used']=1;lic['attempts']={'g0001_u01':1};lib.write(file.parent/'license.json',lic)
   resumed=lib.resume({'category':b['category'],'batch':b['id'],'task':task['id']})
   self.assertEqual(resumed['requests_used'],1)
   self.assertEqual(resumed['resume_summary']['reasons'],{'uncertain':1})
   self.assertEqual(resumed['resume_summary']['ready_count'],6)
   self.assertEqual(lib.read(file.parent/'license.json'),lic)

 def test_real_local_render_and_queue_use_isolated_batch(self):
  for category in ('road_rescue','pet_transport','home_appliance_repair'):
   b=self.batch(category);req=self.request(b,[1])
   with self.ready(),patch.object(lib,'launch',return_value=99999999):
    p=lib.plan(req);task=lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'render-'+category,'authorization':'execute_selected_groups'})
    def generate(client,config,prompt):
     import random
     from PIL import ImageDraw
     rng=random.Random(prompt);im=Image.new('RGB',(1024,1536),(rng.randrange(255),rng.randrange(255),rng.randrange(255)));draw=ImageDraw.Draw(im)
     for i in range(20):draw.rectangle((rng.randrange(900),rng.randrange(1300),1023,1535),fill=tuple(rng.randrange(255) for _ in range(3)))
     out=io.BytesIO();im.save(out,format='PNG');return out.getvalue()
    status=worker.run(category,b['id'],task['id'],generate=generate,clients=[(1,object())])
    state=lib.read(lib.batch_dir(category,b['id'])/'tasks'/task['id']/'task.json')
    self.assertEqual(status,0,state.get('error'))
    data=lib.view({**req,'limit':1})
    self.assertEqual(len(data['groups'][0]['images']),b['structure']['total_images'])
    queue=lib.read(self.root/'.runtime/dashboard_delivery_state.json')
    self.assertIn(b['id']+':1',queue['projects'][category]['pending_library_groups'])
    self.assertFalse(any(i['review']=='approved' for i in data['groups'][0]['images']))

 def test_100_groups_are_visible_without_images(self):
  b=self.batch('pet_transport',100)
  view=lib.view({**self.request(b,list(range(1,101))),'limit':100,'include_prompts':False})
  self.assertEqual(len(view['groups']),100);self.assertEqual(b['prompt_count'],600)
  self.assertTrue(all(not g['images'] and 'prompt' not in g['units'][0] for g in view['groups']))

 def test_home_appliance_random_batch_has_five_watermarked_deliveries(self):
  b=self.batch('home_appliance_repair',2)
  rows=lib.selected(lib.batch_dir(b['category'],b['id']),b,[1,2])
  self.assertEqual(b['structure']['total_images'],5)
  self.assertEqual(b['prompt_count'],10)
  self.assertTrue(all(len(row['units'])==5 for row in rows))
  self.assertTrue(all(len({unit['delivery_position'] for unit in row['units']})==5 for row in rows))
  self.assertTrue(all({unit['kind'] for unit in row['units']}=={'detail'} for row in rows))
  self.assertTrue(all(len({unit['service_role'] for unit in row['units']})==5 for row in rows))
  snapshot=lib.read(lib.batch_dir(b['category'],b['id'])/'snapshot.json')
  self.assertEqual(len(snapshot['business']['service_items']),10)
  self.assertEqual(snapshot['business']['service_items'][0],'家电维修')
  with self.ready():
   plan=lib.plan(self.request(b,[1,2]))
  self.assertEqual(plan['pending_count'],10)
  self.assertEqual(plan['max_requests'],20)

if __name__=='__main__':unittest.main()
