import copy
import io
import os
import shutil
import unittest
import threading
from unittest.mock import patch
from PIL import Image
from tests import test_shared_tasks as shared
from tools import task_library as lib,task_actions as actions,task_keys as keys,task_worker as worker

class TaskActions(unittest.TestCase):
 setUp=shared.SharedTasks.setUp
 batch=shared.SharedTasks.batch
 request=shared.SharedTasks.request
 ready=shared.SharedTasks.ready
 def test_delete_scope_and_project_confirmation(self):
  b=self.batch(count=2);base={**self.request(b,[1]),'authorization':'delete_selected'}
  actions.delete({**base,'scope':'image','group':1,'position':1})
  view=lib.view({**base,'limit':2})
  self.assertFalse(any(u['delivery_position']==1 for u in view['groups'][0]['units']))
  self.assertEqual(len(view['groups'][1]['units']),7)
  actions.delete({**base,'scope':'group','group':1})
  self.assertEqual([r['group'] for r in lib.view({**base,'limit':2})['groups']],[2])
  with self.assertRaises(ValueError):lib.selected(lib.batch_dir(b['category'],b['id']),lib.load_batch(b['category'],b['id'])[1],[1])
  registry={'projects':[{'id':'road_rescue','name':'汽车救援'},{'id':'pet_transport','name':'宠物托运'}]}
  lib.write(self.root/'projects/registry.json',registry)
  sentinel=self.root/'output/pet_transport/keep.txt';sentinel.parent.mkdir(parents=True);sentinel.write_text('keep')
  with self.assertRaises(ValueError):actions.delete({'category':'road_rescue','scope':'project','authorization':'delete_selected','confirmation':'wrong'})
  self.assertTrue(lib.batch_dir(b['category'],b['id']).exists())
  actions.delete({'category':'road_rescue','scope':'project','authorization':'delete_selected','confirmation':'删除汽车救援项目'})
  self.assertTrue(sentinel.exists());self.assertFalse(lib.batch_dir(b['category'],b['id']).exists())
  self.assertEqual(len(lib.read(self.root/'projects/registry.json')['projects']),1)
 def test_key_pool_private_revision_and_channels(self):
  (self.root/'.env').write_text('OPENAI_PROVIDER=official\nOPENAI_API_KEY=test-secret-one\n',encoding='utf-8')
  view=keys.view();self.assertNotIn('test-secret-one',str(view))
  saved=keys.save({'channel':'official','revision':view['revision'],'rows':[{'keep_slot':1},{'value':'test-secret-two'}]})
  self.assertEqual(saved['channels'][0]['limit'],2)
  self.assertNotIn('test-secret-two',str(saved))
  with self.assertRaises(ValueError):keys.save({'channel':'official','revision':view['revision'],'rows':[]})
  keys.save({'channel':'official','revision':saved['revision'],'rows':[{'keep_slot':2}]})
  self.assertEqual(keys.current()['keys'],['test-secret-two'])
 def test_unlimited_rows_dedup_and_agent_reads_saved_pool(self):
  import image_generate
  requested=[{'value':f'isolated-key-{i}'} for i in range(150)]
  saved=keys.save({'channel':'official','revision':keys.view()['revision'],'rows':requested})
  self.assertEqual(saved['channels'][0]['limit'],150)
  before=(self.root/'.env').read_bytes()
  with self.assertRaisesRegex(ValueError,'重复'):
   keys.save({'channel':'official','revision':saved['revision'],'rows':[{'keep_slot':1},{'value':' isolated-key-0 '}]})
  self.assertEqual((self.root/'.env').read_bytes(),before)
  with patch.object(image_generate,'ROOT',self.root),patch.dict(os.environ,{},clear=True):
   actual=image_generate.configured_api_keys()
  self.assertEqual(actual,[r['value'] for r in requested])
 def test_worker_uses_more_than_ten_keys_concurrently(self):
  b=self.batch(count=8);req=self.request(b,list(range(1,9)));barrier=threading.Barrier(50);guard=threading.Lock();state={'calls':0,'active':0,'peak':0}
  out=io.BytesIO();Image.new('RGB',(1024,1536),'blue').save(out,format='PNG');payload=out.getvalue()
  with self.ready(),patch.object(lib,'readiness',return_value=([],list(range(1,51)))),patch.object(lib,'launch',return_value=99999999):
   plan=lib.plan(req);self.assertEqual(plan['max_workers'],50)
   task=lib.start({**req,'request_id':'parallel-50','authorization':'execute_selected_groups','plan_sha256':plan['plan_sha256']})
   def generate(*args):
    with guard:state['calls']+=1;number=state['calls'];state['active']+=1;state['peak']=max(state['peak'],state['active'])
    if number<=50:barrier.wait(timeout=8)
    with guard:state['active']-=1
    return payload
   worker.run(b['category'],b['id'],task['id'],generate=generate,clients=[(i,object()) for i in range(1,51)],render=lambda *a:None)
  self.assertEqual(state['peak'],50);self.assertEqual(state['calls'],56)
 def test_running_targets_block_delete_and_batch_delete_is_scoped(self):
  a=self.batch();b=self.batch();path=lib.batch_dir(a['category'],a['id'])
  file=path/'tasks/live/task.json';lib.write(file,{'category':a['category'],'status':'running','pid':os.getpid()})
  request={'category':a['category'],'batch':a['id'],'scope':'batch','authorization':'delete_selected'}
  with self.assertRaisesRegex(ValueError,'正在运行'):actions.delete(request)
  lib.write(file,{'category':a['category'],'status':'completed','pid':os.getpid()})
  actions.delete(request)
  self.assertFalse(path.exists());self.assertTrue(lib.batch_dir(b['category'],b['id']).exists())
 def test_triptych_replacement_is_one_delivery_three_units(self):
  b=self.batch()
  prepared=actions.prepare_replacement({'category':b['category'],'batch':b['id'],'group':1,'position':2,'request_id':'triptych'})
  self.assertEqual(prepared['prompt_count'],3);self.assertEqual(prepared['structure']['total_images'],1)
 def test_replacement_exhausted_auto_retry_preserves_current_output(self):
  b=self.batch();original=lib.delivery_path(b['category'],b['id'],1,1,'cover');original.parent.mkdir(parents=True)
  Image.new('RGB',(1024,1536),'red').save(original);before=original.read_bytes()
  prepared=actions.prepare_replacement({'category':b['category'],'batch':b['id'],'group':1,'position':1,'request_id':'exhausted-replacement'})
  req={'category':b['category'],'batch':prepared['id'],'groups':[1]}
  with self.ready(),patch.object(lib,'launch',return_value=99999999):
   planned=lib.plan(req);task=lib.start({**req,'request_id':'exhausted-run','authorization':'execute_selected_groups','plan_sha256':planned['plan_sha256']})
   def fail(*args):raise TimeoutError('timed out')
   result=worker.run(b['category'],prepared['id'],task['id'],generate=fail,clients=[(1,object())],render=lambda *a:None)
   self.assertEqual(result,0)
   state=lib.read(lib.batch_dir(b['category'],prepared['id'])/'tasks'/task['id']/'task.json')
   self.assertEqual(state['status'],'completed_with_errors');self.assertEqual(state['requests_used'],2)
   self.assertEqual(state['skipped_units'],1);self.assertEqual(original.read_bytes(),before)
   with self.assertRaisesRegex(ValueError,'单图两次请求已用尽'):lib.resume({'category':b['category'],'batch':prepared['id'],'task':task['id']})

 def test_replacement_preserves_old_on_failure_and_replaces_one(self):
  b=self.batch();original=lib.delivery_path(b['category'],b['id'],1,1,'cover');original.parent.mkdir(parents=True)
  Image.new('RGB',(1024,1536),'red').save(original);before=original.read_bytes()
  other=original.parent/'03_detail.png';other.write_bytes(before)
  prepared=actions.prepare_replacement({'category':b['category'],'batch':b['id'],'group':1,'position':1,'request_id':'one-replacement'})
  self.assertEqual(original.read_bytes(),before);self.assertEqual(prepared['prompt_count'],1)
  req={'category':b['category'],'batch':prepared['id'],'groups':[1]}
  with self.ready(),patch.object(lib,'launch',return_value=99999999):
   planned=lib.plan(req);task=lib.start({**req,'request_id':'replace-run','authorization':'execute_selected_groups','plan_sha256':planned['plan_sha256']})
   def fail(*args):
    lib.pause({'category':b['category'],'batch':prepared['id'],'task':task['id']})
    raise TimeoutError('timed out')
   worker.run(b['category'],prepared['id'],task['id'],generate=fail,clients=[(1,object())],render=lambda *a:None)
   self.assertEqual(original.read_bytes(),before)
   lib.resume({'category':b['category'],'batch':prepared['id'],'task':task['id']})
   def generate(*args):
    out=io.BytesIO();Image.new('RGB',(1024,1536),'blue').save(out,format='PNG');return out.getvalue()
   def render(category,batch,data,rows,snapshot):
    for row in rows:
     for u in row['units']:
      if worker.raw_valid(category,batch,row['group'],u):
       target=lib.delivery_path(category,batch,row['group'],u['delivery_position'],u['kind']);shutil.copyfile(lib.unit_raw(category,batch,row['group'],u),target);lib.write(target.with_suffix('.validation.json'),{'status':'pending'})
   worker.run(b['category'],prepared['id'],task['id'],generate=generate,clients=[(1,object())],render=render)
  self.assertNotEqual(original.read_bytes(),before);self.assertEqual(other.read_bytes(),before)
  path,data=lib.load_batch(b['category'],b['id']);units=lib.selected(path,data,[1])[0]['units']
  self.assertTrue(worker.raw_valid(b['category'],b['id'],1,units[0]))
  self.assertEqual(len(lib.batches(b['category'])),1)
  self.assertEqual(lib.read(lib.batch_dir(b['category'],prepared['id'])/'tasks'/task['id']/'task.json')['requests_used'],2)
