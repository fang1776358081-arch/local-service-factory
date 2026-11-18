"""Single public workflow for Agent and Electron. No network in assembly/read/plan."""
import argparse
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from tools import variable_catalog as vc, runtime_paths

ROOT=runtime_paths.data_root()
ACTIVE={'queued','running','recovering'}
_released_locks=set()

def generation_route(data):
    route=data.get('generation_route','api')
    if route not in {'api','codex_native'}:raise ValueError('未知生成方式')
    return route

def require_api(data):
    if generation_route(data)!='api':raise ValueError('Codex 内置批次不能使用 API 执行入口')

def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def io_path(path,*,force=False):
    """Keep public paths ordinary; extend only Windows filesystem operations."""
    path=Path(path)
    if os.name=='nt':
        value=str(path.absolute())
        if (force or len(value)>=240) and not value.startswith('\\\\?\\'):
            return Path('\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value)
    return path

def io_glob(base,pattern):
    """Extend the scan root even when only nested matches exceed MAX_PATH."""
    base=Path(base);scan=io_path(base,force=True)
    for item in scan.glob(pattern):
        yield base/item.relative_to(scan)

def read(path): return json.loads(io_path(path).read_text(encoding='utf-8-sig'))
def validation_record(path):
    """Optional delivery metadata is not an authoritative task/licence document."""
    path=io_path(path)
    if not path.is_file():return {}
    try:
        if path.stat().st_size>1024*1024:raise ValueError('oversized validation')
        value=read(path)
        if not isinstance(value,dict):raise ValueError('invalid validation')
        record=value.get('postprocess_record')
        if record is not None and not isinstance(record,dict):raise ValueError('invalid render evidence')
        if record is None:value.pop('postprocess_record',None)
        return value
    except (OSError,ValueError,TypeError):
        return {'status':'pending','note':'校验记录损坏或缺失；保留图片，此版本未审核'}
def write(path,value):
    path=io_path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=io_path(path.with_name(path.name+'.'+secrets.token_hex(6)+'.tmp'))
    try:
        with temp.open('w',encoding='utf-8') as out:
            json.dump(value,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())
        # Windows readers may briefly hold a file without delete sharing.
        # Retry only the local atomic replacement, never an image request.
        for attempt in range(8):
            try: os.replace(temp,path);break
            except PermissionError:
                if attempt==7: raise
                time.sleep(.025*(attempt+1))
    finally:
        if temp.exists(): temp.unlink()
def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',value): raise ValueError('无效标识')
    return value

def category_dir(category):
    if category not in {p['id'] for p in vc.projects()}: raise ValueError('未知业务')
    return ROOT/'prompts/library'/category

def batch_dir(category,batch): return category_dir(category)/identifier(batch)
def load_batch(category,batch):
    path=batch_dir(category,batch);data=read(path/'batch.json')
    if data['category']!=category or data['id']!=batch: raise ValueError('批次身份不一致')
    return path,data

def alive(pid):
    from tools.category_image_production import pid_is_running
    return bool(pid and pid_is_running(int(pid)))

@contextlib.contextmanager
def lock(path,wait_seconds=0):
    path=io_path(path);path.parent.mkdir(parents=True,exist_ok=True)
    # Persistent process lock; never remove a lock owned by a living process.
    deadline=time.monotonic()+wait_seconds;stale_attempts=0
    while True:
        try: fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY);break
        except FileExistsError:
            if str(path) in _released_locks:
                try:
                    if path.exists():path.unlink()
                    _released_locks.discard(str(path));continue
                except FileNotFoundError:
                    _released_locks.discard(str(path));continue
                except PermissionError:
                    try:path.rename(path.with_name(path.name+f'.stale-{os.getpid()}'));_released_locks.discard(str(path));continue
                    except OSError:
                        if time.monotonic()<deadline:time.sleep(.05);continue
                        raise ValueError('已有操作正在进行，请稍后重试')
            try: owner=read(path)
            except Exception:
                if time.monotonic()<deadline:time.sleep(.05);continue
                raise ValueError('任务锁正在建立，请稍后重试')
            if alive(owner.get('pid')):
                if time.monotonic()<deadline:time.sleep(.05);continue
                raise ValueError('已有操作正在进行，请稍后重试')
            if stale_attempts>=2:raise ValueError('无法取得任务锁')
            try:path.unlink()
            except FileNotFoundError:pass
            stale_attempts+=1
    try:
        os.write(fd,json.dumps({'pid':os.getpid(),'created_at':now()}).encode());os.close(fd)
        yield
    finally:
        released=False
        for attempt in range(25):
            try:
                if path.exists():path.unlink()
                released=True;break
            except FileNotFoundError:released=True;break
            except PermissionError:
                if attempt==24:
                    # A reader can keep the lock file open on Windows. Raising here
                    # aborted the whole batch after images were already saved.
                    try:path.rename(path.with_name(path.name+f'.stale-{os.getpid()}'));released=True
                    except OSError:pass
                    break
                time.sleep(.02)
        if released:_released_locks.discard(str(path))
        else:_released_locks.add(str(path))
        if released:
            try:
                stale=path.with_name(path.name+f'.stale-{os.getpid()}')
                if stale.exists():stale.unlink()
            except OSError:pass

def confirmed_phone(category):
    from tools.contact_numbers import normalize_contact_number
    definition=vc.read_json(vc.project_dir(category)/'project.json')
    field=definition.get('required_fields',{}).get('contact_phones',{})
    numbers=list(field.get('values',[])) if field.get('confirmed') else []
    runtime=ROOT/'.runtime/projects'/category/'business.json'
    if runtime.exists():
        value=read(runtime)
        if value.get('user_confirmed') and value.get('contact_phones'):
            stored=value['contact_phones']
            if numbers and set(numbers)!=set(stored): raise ValueError('联系电话确认记录冲突，请让 Agent 核对')
            numbers=stored
    if not numbers: raise ValueError('尚未确认该业务联系电话，请在 Agent 对话中确认后组装')
    if len(set(numbers))!=1: raise ValueError('该业务有多个已确认号码，请由 Agent 明确本批次使用的号码后再组装')
    return normalize_contact_number(numbers[0])

def _business_file(category):
    path=runtime_paths.CODE_ROOT/('configs/business_ktv/scene_library.json' if category=='business_ktv' else f'configs/categories/{category}.json')
    config=runtime_paths.read_json(path) if runtime_paths.rule_file(path).exists() else {}
    if category=='business_ktv':
        overlay=runtime_paths.read_json(runtime_paths.CODE_ROOT/'configs/business_ktv/local_overlay.json')
        config['legacy_interior_service_words']=list(overlay['service_words'])
        config['service_items']=['商务宴请', '派对聚会']
    return config

def base_service_items(category):
    config=_business_file(category)
    return list(config.get('service_items') or config.get('service_buttons') or [])

def postprocess_text_path(category):
    category_dir(category)
    return ROOT/'.runtime/projects'/category/'postprocess_text.json'

def clean_service_lines(services):
    if not isinstance(services,list) or len(services)>24: raise ValueError('文字最多24条')
    cleaned=[]
    for item in services:
        if not isinstance(item,str): raise ValueError('文字必须是可编辑的文本')
        text=item.strip()
        if not text: continue
        if any(ch in text for ch in '\n\r\t') or len(text)>20: raise ValueError('单条文字请控制在20个字以内，且不要换行')
        if text in cleaned: raise ValueError('文字不能重复')
        cleaned.append(text)
    return cleaned

def overlay_services(config):
    items=config.get('service_items')
    if isinstance(items,list): return list(items)
    return list(config.get('service_buttons') or [])

def overlay_text(request):
    category=request['category'];category_dir(category)
    config=business_config(category)
    result={'services':overlay_services(config)}
    if category=='diving_salvage':
        from tools.task_diving_salvage import task_types
        result['task_types']=[{'id':'random','name':'随机（每组）'},*task_types(config)]
    return result

def saved_service_items(category):
    path=postprocess_text_path(category)
    if not io_path(path).exists():return None
    services=read(path).get('services')
    if not isinstance(services,list) or any(not isinstance(item,str) for item in services):return None
    return list(services)

def remember_service_items(category,services):
    if list(services)==base_service_items(category):
        path=postprocess_text_path(category)
        if io_path(path).exists():io_path(path).unlink()
        return False
    write(postprocess_text_path(category),{'schema_version':1,'services':list(services),'updated_at':now()})
    return True

def business_config(category):
    config=_business_file(category)
    saved=saved_service_items(category)
    if saved is not None:config['service_items']=saved
    return config

def projects():
    result=[]
    for p in vc.projects():
        definition=runtime_paths.read_json(vc.project_dir(p['id'])/'project.json')
        result.append({**p,'structure':definition['content_group'],'assembly_blocked':definition.get('assembly_blocked'),
                       'required_assembly_fields':['count','phone']})
    return result

def assemble(request):
    definition=runtime_paths.read_json(vc.project_dir(request['category'])/'project.json')
    if definition.get('assembly_blocked'): raise ValueError(definition['assembly_blocked'])
    with lock(ROOT/'.runtime/task-admin.lock'):
        return _assemble(request)

def _assemble(request):
    if (ROOT/'.runtime/updates/installing.json').exists():raise ValueError('软件正在安装更新，请重新打开看板后操作')
    route=generation_route(request)
    category=request['category']; count=request.get('count');seed=request.get('seed')
    if type(count)!=int or not 1<=count<=100: raise ValueError('组数必须为 1–100 的整数')
    phone=request.get('phone')
    if not isinstance(phone,str) or not re.fullmatch(r'1[3-9][0-9]{9}',phone):
        raise ValueError('请填写本批次的有效 11 位手机号，不能自动沿用历史号码')
    from tools.raw_library import reuse_rate
    rate=reuse_rate(request.get('reuse_rate'))
    if rate:raise ValueError('新批次已停用原图库复用')
    if seed is None: seed=secrets.randbelow(1_000_000)+1401
    if type(seed)!=int or not 1401<=seed<=2_000_000: raise ValueError('种子须为 1401–2000000 的整数')
    source=request.get('source','agent')
    if source not in {'agent','dashboard'}: raise ValueError('来源不正确')
    services=clean_service_lines(request['services']) if 'services' in request else None
    request_id=identifier(request.get('request_id') or secrets.token_hex(16))
    if os.environ.get('FACTORY_DATA_HOME') and (runtime_paths.CODE_ROOT/'distribution/baseline-rules.json').is_file():
        from tools.rule_updates import bootstrap
        bootstrap()
    home=category_dir(category)
    with lock(home/'assemble.lock'):
        previous=home/'requests'/f'{request_id}.json'
        signature=digest({**({'generation_route':route} if route!='api' else {}),**{k:request.get(k) for k in ('category','count','seed','phone')},**({'task_type':request.get('task_type','objects')} if category=='diving_salvage' else {}),'reuse_rate':rate,**({'services':services} if services is not None else {})})
        if io_path(previous).exists():
            old=read(previous)
            if old['signature']!=signature: raise ValueError('同一请求标识不能用于不同组装内容')
            return read(home/old['batch']/'batch.json')
        catalog=copy.deepcopy(vc.load(category));vc.validate(catalog)
        config=business_config(category)
        if category=='diving_salvage':
            from tools.task_diving_salvage import select
            task_type=request.get('task_type','objects')
            config['task_type']='random' if task_type=='random' else select(config,task_type)['id']
            from tools.diving_salvage_branches import resolve_pipe_sources
            config=resolve_pipe_sources(config,lambda p:runtime_paths.read_json(runtime_paths.CODE_ROOT/p))
        if services is not None:
            remember_service_items(category,services);config['service_items']=list(services)
        batch='batch_'+phone+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+secrets.token_hex(5)
        path=home/batch;io_path(path).mkdir(parents=True)
        definition=runtime_paths.read_json(vc.project_dir(category)/'project.json');structure=definition['content_group']
        from tools.task_assets import settings
        summary={'generation_route':route,'clean_output':True,'asset_root':settings()['path'],'schema_version':1,'id':batch,'name':f'{phone} · {count} 组','category':category,'source':source,'seed':seed,'count':count,
                 'created_at':now(),'status':'assembling','completed_groups':0,'phone':phone,'revision':catalog['revision'],
                 'structure':structure,'api_called':False,'request_id':request_id}
        write(previous,{'signature':signature,'batch':batch});write(path/'batch.json',summary)
        try:
            from tools.task_groups import build_group
            from tools.postprocess_rules import load as load_postprocess
            snapshot={'postprocess':load_postprocess(category),'rules_version':runtime_paths.version(),'catalog':catalog,'business':config,'project':definition,
                      'batch_contact':{'phone':phone,'confirmation':'explicit_batch_input'}}
            summary['snapshot_sha256']=digest(snapshot)
            write(path/'snapshot.json',snapshot)
            manifest=[]
            for group in range(1,count+1):
                units=build_group(category,seed+group-1,phone,catalog,config)
                expected=structure.get('generation_unit_count') or structure['cover_count']+structure['detail_count']
                if len(units)!=expected: raise ValueError('完整组生成单元数量不符合业务结构')
                for unit in units:
                    unit['id']=f'g{group:04d}_u{unit["position"]:02d}'
                    unit['prompt_sha256']=hashlib.sha256(unit['prompt'].encode()).hexdigest()
                row={'group':group,'units':units,'sha256':digest(units)}
                write(path/'groups'/f'{group:04d}.json',row);manifest.append({'group':group,'sha256':row['sha256']})
                summary['completed_groups']=group;write(path/'batch.json',summary)
            summary.update(status='ready',prompt_count=count*expected,manifest_sha256=digest(manifest))
            write(path/'manifest.json',manifest);write(path/'batch.json',summary)
            from tools.raw_library import choose
            reuse=choose(category,summary,selected(path,summary,list(range(1,count+1))),rate)
            write(path/'raw-reuse.json',reuse)
            summary.update(raw_reuse_sha256=digest(reuse),reuse_rate=rate,library_reuse_count=reuse['actual'],reuse_shortfall=reuse['shortfall'])
            write(path/'batch.json',summary)
            return summary
        except Exception as error:
            summary.update(status='failed',error=str(error));write(path/'batch.json',summary);raise

def batches(category):
    return sorted([b for p in io_glob(category_dir(category),'batch_*/batch.json') if not (b:=read(p)).get('replacement')],key=lambda b:b['created_at'],reverse=True)

def selected(path,data,groups):
    if data['status']!='ready': raise ValueError('批次尚未完成组装')
    if not isinstance(groups,list) or not groups or any(type(g)!=int or not 1<=g<=data['count'] for g in groups) or len(set(groups))!=len(groups): raise ValueError('请选择有效且不重复的组')
    if digest(read(path/'snapshot.json'))!=data['snapshot_sha256']: raise ValueError('批次配置快照已改变')
    manifest=read(path/'manifest.json')
    if digest(manifest)!=data['manifest_sha256']: raise ValueError('批次清单校验失败')
    hashes={r['group']:r['sha256'] for r in manifest};result=[]
    for g in sorted(groups):
        if g in data.get('deleted_groups',[]):raise ValueError('所选组已删除')
        row=read(path/'groups'/f'{g:04d}.json')
        if row['sha256']!=hashes[g] or digest(row['units'])!=hashes[g]: raise ValueError('提示词文件已改变，禁止使用旧任务继续')
        row['units']=[u for u in row['units'] if u['delivery_position'] not in data.get('deleted_images',{}).get(str(g),[])]
        if not row['units']:raise ValueError('所选组没有可生成图片')
        result.append(row)
    return result

def scoped_rows(path,data,groups=None,unit_ids=None):
    """Validate the immutable manifest before narrowing a licensed raw-unit scope."""
    if unit_ids is not None:
        if not isinstance(unit_ids,list) or not unit_ids or any(not isinstance(u,str) for u in unit_ids) or len(set(unit_ids))!=len(unit_ids):
            raise ValueError('请选择有效且不重复的原图单元')
        if groups is None:
            groups=sorted({int(m.group(1)) for uid in unit_ids if (m:=re.fullmatch(r'g([0-9]{4})_u[0-9]{2}',uid))})
            if not groups:raise ValueError('原图单元标识无效')
    rows=selected(path,data,groups)
    if unit_ids is None:return rows
    valid={u['id'] for row in rows for u in row['units']}
    if not set(unit_ids)<=valid:raise ValueError('原图单元不在所选范围内')
    return [{**row,'units':[u for u in row['units'] if u['id'] in unit_ids]} for row in rows if any(u['id'] in unit_ids for u in row['units'])]

def task_rows(path,data,state):
    return scoped_rows(path,data,state['groups'],state.get('unit_ids'))

def delivery_rows(path,data,state):
    positions={(r['group'],u['delivery_position']) for r in task_rows(path,data,state) for u in r['units']}
    return [{**r,'units':[u for u in r['units'] if (r['group'],u['delivery_position']) in positions]} for r in selected(path,data,state['groups'])]

def output_dir(category,batch):
    from tools.task_assets import batch_root
    _,data=load_batch(category,batch)
    return batch_root(data)/category/'library'/identifier(batch)
def work_dir(category,batch):
    _,data=load_batch(category,batch)
    if data.get('clean_output'):return ROOT/'.runtime'/'image-work'/category/'library'/identifier(batch)
    return output_dir(category,batch)

def unit_raw(category,batch,group,unit): return work_dir(category,batch)/f'group_{group:04d}'/'raw'/f'{unit["id"]}.png'
def delivery_path(category,batch,group,position,kind): return work_dir(category,batch)/f'group_{group:04d}'/f'{position:02d}_{kind}.png'

def delivery_source(category,batch,group,position):
    """Current delivery content, separate from immutable production manifests."""
    path,data=load_batch(category,batch)
    revision=data.get('replacements',{}).get(f'{group}:{position}')
    if revision:
        source,child=load_batch(category,revision)
        if child.get('replacement')!={'batch':batch,'group':group,'position':position}:
            raise ValueError('单图版本与原图片关联不一致')
        units=selected(source,child,[1])[0]['units']
        return revision,1,units,read(source/'snapshot.json')
    units=[u for u in selected(path,data,[group])[0]['units'] if u['delivery_position']==position]
    if not units:raise ValueError('图片位置不存在')
    return batch,group,units,read(path/'snapshot.json')

def jobs(path,*,_budget_memo=None):
    rows=[]
    for p in io_glob(path/'tasks','*/task.json'):
        row=read(p)
        if row.get('parent_budget') or row.get('auto_complete',{}).get('mode')=='continuous':
            from tools.task_budget import project,licence_snapshot
            row,_=project(row,licence_snapshot(p.parent/'license.json',_budget_memo),memo=_budget_memo)
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(row['updated_at'])).total_seconds()
        if row['status'] in ACTIVE and ((row.get('pid') and not alive(row['pid'])) or (not row.get('pid') and age>30)): row={**row,'status':'interrupted'}
        rows.append(row)
    return sorted(rows,key=lambda row:row['created_at'],reverse=True)

def view(request):
    path,data=load_batch(request['category'],request['batch']);offset=request.get('offset',0);limit=request.get('limit',20)
    if type(offset)!=int or offset<0 or type(limit)!=int or not 1<=limit<=100: raise ValueError('分页参数错误')
    rows=[];task_rows=jobs(path)
    if not data.get('replacement'):
        for p in io_glob(category_dir(data['category']),'batch_revision_*/batch.json'):
            revision=read(p);target=revision.get('replacement',{})
            if target.get('batch')==data['id'] and not revision.get('automatic_repair_parent'):
                task_rows.extend({**t,'groups':[target['group']],'replacement_position':target['position'],'replacement_target':target} for t in jobs(p.parent))
        task_rows.sort(key=lambda t:t['created_at'],reverse=True)
    for g in range(offset+1,min(data.get('completed_groups',0),offset+limit)+1):
        if g in data.get('deleted_groups',[]):continue
        row=read(path/'groups'/f'{g:04d}.json');delivered={}
        row['units']=[u for u in row['units'] if u['delivery_position'] not in data.get('deleted_images',{}).get(str(g),[])]
        for u in row['units']:
            kind='triptych' if u['kind']=='triptych_panel' else u['kind'];target=delivery_path(data['category'],data['id'],g,u['delivery_position'],kind)
            if io_path(target).exists():
                review=target.with_suffix('.validation.json');validation=validation_record(review)
                decision='approved' if validation.get('approved') is True else validation.get('decision') or validation.get('status') or 'pending'
                stat=io_path(target).stat()
                display=output_dir(data['category'],data['id'])/target.parent.name/target.name if data.get('clean_output') and not data.get('replacement') else target
                delivered[u['delivery_position']]={'path':str(display),'position':u['delivery_position'],'kind':kind,'review':decision,'revision':str(stat.st_mtime_ns)+'-'+str(stat.st_size)}
        relevant=next((t for t in task_rows if g in t['groups'] and 'replacement_position' not in t),None)
        active_revision=next((t for t in task_rows if g in t['groups'] and 'replacement_position' in t and t['status'] in ACTIVE),None)
        if active_revision:relevant=active_revision
        row.update(images=list(delivered.values()),task=relevant['id'] if relevant else None,
                   status=('approved' if all(i['review']=='approved' for i in delivered.values()) else 'needs_fix' if any(i['review'] in {'needs_fix','rejected'} for i in delivered.values()) else 'generated') if len(delivered)==len({u['delivery_position'] for u in row['units']}) else (relevant['status'] if relevant else 'prompt_ready'))
        if not request.get('include_prompts',True):
            row['units']=[{k:v for k,v in u.items() if k not in {'prompt','variables'}} for u in row['units']]
        rows.append(row)
    from tools.task_auto_recovery import public_progress
    task_rows=[{**t,**public_progress(t)} for t in task_rows]
    if generation_route(data)=='codex_native':
        from tools.task_native import load_state as native_state,instance
        state=native_state(path)
        data={**data,'native_instance':instance(),'native_cancelled':state['cancelled']}
        for row in rows:
            for unit in row['units']:
                record=state['units'].get(unit['id'],{})
                unit['native_status']='cancelled' if state['cancelled'] and record.get('status')!='completed' else record.get('status','pending')
            if not row['images']:row['status']='cancelled' if state['cancelled'] else 'awaiting_codex'
    return {'batch':data,'groups':rows,'tasks':task_rows,'total':data['count']}

def choose_listed_model(ids):
    found=[name for name in ('gpt-image-2-4k','gpt-image-2.5-flare') if name in set(ids)]
    if len(found)!=1:raise ValueError('当前密钥分组不能确定唯一可用模型，不能开始')
    return found[0]

def apply_model_contract(config):
    config=dict(config)
    if config.get('model')=='gpt-image-2-4k':
        if config.get('provider')!='relay' or str(config.get('base_url','')).rstrip('/')!='https://tinysnow.one/v1':
            raise ValueError('gpt-image-2-4k 仅配置了 tinysnow 尺寸方案')
        config.update(quality='medium',api_size='2560x3840',raw_contract='tinysnow_2336_2352x3520_to_legacy_v1')
    elif config.get('model') not in {'gpt-image-2','gpt-image-2.5-flare'} or config.get('quality')!='medium' or config.get('api_size')!='1024x1536':
        raise ValueError('模型或尺寸不在已配置的生成方案内')
    allowed=('provider','model','quality','api_size','output_format','base_url','raw_contract')
    return {k:config[k] for k in allowed if k in config}

def api_config():
    import factory
    return apply_model_contract(factory.effective_api_config(factory.load_json(runtime_paths.CODE_ROOT/'config.json')))

def contract_for_model(base,model):
    picked=dict(base);picked['model']=model
    if model=='gpt-image-2.5-flare':
        picked.update(quality='medium',api_size='1024x1536');picked.pop('raw_contract',None)
    return apply_model_contract(picked)

def listed_model_ids(base,api_key):
    from openai import OpenAI
    kwargs={'api_key':api_key,'timeout':20,'max_retries':0}
    if base.get('base_url'):kwargs['base_url']=base['base_url']
    for attempt in range(3):
        try:
            page=OpenAI(**kwargs).models.list()
            return [getattr(item,'id','') for item in getattr(page,'data',())]
        except Exception as error:
            if getattr(error,'status_code',None) in (401,403):raise ValueError('密钥无法列出模型，请检查密钥') from None
            if attempt==2:raise ValueError('暂时无法读取可用模型，请稍后重试') from None
            time.sleep(.5*(2**attempt))

def probe_slot_models(slots=None,cache_seconds=0):
    # Offline tests replace api_config. A real call lists models per key and does not generate an image.
    if api_config is not _api_config_impl:return None
    import factory,image_generate
    base=dict(factory.effective_api_config(factory.load_json(runtime_paths.CODE_ROOT/'config.json')))
    keys=image_generate.configured_api_keys()
    if not keys:raise ValueError('尚未配置 API Key，请让 Agent 协助设置')
    chosen=list(slots) if slots is not None else list(range(1,len(keys)+1))
    if any(type(slot) is not int or not 1<=slot<=len(keys) for slot in chosen):raise ValueError('API Key 槽位必须位于已配置范围内')
    if not chosen:return {}
    cache_file=ROOT/'.runtime/private/model-probe-cache.json'
    signature=digest({'base':base,'slots':chosen,'keys':[hashlib.sha256(keys[slot-1].encode()).hexdigest() for slot in chosen]})
    if cache_seconds:
        try:
            cached=read(cache_file)
            if cached.get('signature')==signature and time.time()-float(cached.get('checked_at',0))<=cache_seconds:
                value=cached.get('slot_models')
                if isinstance(value,dict) and list(value)==[str(slot) for slot in chosen]:return value
        except (OSError,ValueError,TypeError):pass
    def inspect(slot):
        try:model=choose_listed_model(listed_model_ids(base,keys[slot-1]))
        except ValueError as error:
            if '唯一可用模型' in str(error):raise ValueError(f'密钥 {slot} 没有唯一可用的生图模型，不能开始') from None
            raise ValueError(f'密钥 {slot} {error}') from None
        return str(slot),contract_for_model(base,model)
    # Model discovery is read-only network I/O. Checking a large key pool in
    # series made a 50-key plan take more than the dashboard's entire timeout.
    # Keep one bounded request chain per key while preserving deterministic
    # slot ordering in the returned authorization record.
    with ThreadPoolExecutor(max_workers=min(50,len(chosen))) as pool:
        found=dict(pool.map(inspect,chosen))
    if cache_seconds:write(cache_file,{'signature':signature,'checked_at':time.time(),'slot_models':found})
    return found

def active_model_config():
    if api_config is not _api_config_impl:return api_config()
    return probe_slot_models([1])['1']

def frozen_models_match(state):
    if state.get('slot_models'):return probe_slot_models(state.get('slots'))==state['slot_models']
    return active_model_config()==state.get('config')

def remember_detected_model(slot_models):
    names=list(dict.fromkeys(item.get('model') for item in (slot_models or {}).values()))
    if len(names)!=1 or names[0] not in {'gpt-image-2-4k','gpt-image-2.5-flare'}:return
    model=names[0]
    env_file=io_path(ROOT/'.env')
    if env_file.is_file():
        text=env_file.read_text(encoding='utf-8-sig')
        lines=[f'OPENAI_IMAGE_MODEL={model}' if line.startswith('OPENAI_IMAGE_MODEL=') else line for line in text.splitlines()]
        if not any(line.startswith('OPENAI_IMAGE_MODEL=') for line in lines):lines.append(f'OPENAI_IMAGE_MODEL={model}')
        updated='\n'.join(lines)+('\n' if text.endswith('\n') or lines else '')
        if updated!=text:
            temp=env_file.with_name('.env.'+secrets.token_hex(6)+'.tmp')
            try:
                temp.write_text(updated,encoding='utf-8');os.replace(temp,env_file)
            finally:
                if temp.exists():temp.unlink()
    channel_file=ROOT/'.runtime/private/api_channels.json'
    if io_path(channel_file).is_file():
        saved=read(channel_file);changed=False
        for channel in saved.get('channels',[]):
            if isinstance(channel,dict) and channel.get('model') in {'gpt-image-2','gpt-image-2-4k','gpt-image-2.5-flare'} and channel.get('model')!=model:
                channel['model']=model;changed=True
        if changed:write(channel_file,saved)

def align_task_models(state):
    """Point this task at the key's current model. None means no live probe."""
    probed=probe_slot_models(state.get('slots'))
    if not probed:return None
    remember_detected_model(probed)
    config=next(iter(probed.values()))
    if state.get('slot_models')==probed and state.get('config')==config:return False
    state['slot_models']=probed;state['config']=config
    return True

def retie_model_license(file,state):
    license=read(file.parent/'license.json');terms=license['terms']
    terms['config']=state['config'];terms['slot_models']=state['slot_models']
    state['license_sha256']=digest(terms);license['terms']=terms
    write(file.parent/'license.json',license);write(file,state)

def apply_detected_models(file,state):
    changed=align_task_models(state)
    if changed:retie_model_license(file,state)
    return changed

def model_label(slot_models,config):
    if not slot_models:return (config or {}).get('model') or '未就绪'
    names=list(dict.fromkeys(item['model'] for item in slot_models.values()))
    if len(names)==1:return names[0]
    return '、'.join(f'密钥{slot} {item["model"]}' for slot,item in slot_models.items())

_api_config_impl=api_config

def readiness(category,config,snapshot):
    import image_generate
    reasons=[]
    try:
        from openai import OpenAI
    except ModuleNotFoundError as error:
        reasons.append('本地 Python 缺少依赖 '+(error.name or 'openai')+'，请修复开发环境后重启看板')
    image_generate.load_project_env(); slots=list(range(1,len(image_generate.configured_api_keys())+1))
    if not slots: reasons.append('尚未配置 API Key，请让 Agent 协助设置')
    if not (snapshot['business'].get('service_items') or snapshot['business'].get('service_buttons')) and not (category=='diving_salvage' and snapshot['business'].get('service_items')==[]):
        reasons.append('该业务缺少统一生成所需的已确认底部服务词配置，请由 Agent 补齐')
    return reasons,slots

def validate_batch_phone(category,data,snapshot):
    contact=snapshot.get('batch_contact')
    if contact:
        if contact.get('confirmation')!='explicit_batch_input' or contact.get('phone')!=data['phone']:
            raise ValueError('批次手机号与冻结确认记录不一致')
    elif confirmed_phone(category)!=data['phone']:
        raise ValueError('当前确认电话与旧批次不同，请由 Agent 处理')

def revision_conflicts(category,batch,groups,data,exclude_task=None,unit_ids=None):
    from tools.task_queue import origin_keys
    wanted=origin_keys(category,batch,scoped_rows(batch_dir(category,batch),data,groups,unit_ids))
    target=data.get('replacement');origin=target['batch'] if target else batch
    candidates=[]
    if target and origin!='legacy':candidates.append((batch_dir(category,origin),load_batch(category,origin)[1]))
    for file in io_glob(category_dir(category),'batch_revision_*/batch.json'):
        revision=read(file)
        if revision['id']!=batch and revision.get('replacement',{}).get('batch')==origin:candidates.append((file.parent,revision))
    for path,revision in candidates:
        for state in jobs(path):
            if state['status'] in ACTIVE and state['id']!=exclude_task and wanted&origin_keys(category,revision['id'],task_rows(path,revision,state)):return True
    return False


def plan(request,_parent=None):
    category=request['category'];batch=request['batch'];path,data=load_batch(category,batch)
    require_api(data)
    if data.get('automatic_repair_parent') and _parent is None:
        raise ValueError('自动补缺子任务由原任务管理，请继续原任务，不能另建预算')
    rows=scoped_rows(path,data,request.get('groups'),request.get('unit_ids'));groups=[r['group'] for r in rows];snapshot=read(path/'snapshot.json')
    validate_batch_phone(category,data,snapshot)
    blocks=[]
    for row in rows:
        for unit in row['units']:
            kind='triptych' if unit['kind']=='triptych_panel' else unit['kind']
            review=delivery_path(category,batch,row['group'],unit['delivery_position'],kind).with_suffix('.validation.json')
            validation=validation_record(review)
            if validation.get('status') in {'rejected','needs_fix'} or validation.get('decision')=='rejected':
                blocks.append('所选组包含未通过审核的图片，请由 Agent 按反馈处理，不自动重复生成');break
    from tools.task_worker import raw_valid
    from tools.task_queue import ReadContext
    from tools.raw_library import selection,validate_binding
    reuse_selection=selection(data)
    bindings={b['unit']:b for b in reuse_selection['bindings']}
    pending=[];reused=0;library_reused=0;reuse_blocks=[];retained_ids=[]
    raw_context=ReadContext(full=True)
    raw_context.batches[(category,batch)]=(path,data)
    raw_context.rows[(category,batch)]={row['group']:row for row in rows}
    for row in rows:
        for unit in row['units']:
            if unit['id'] in bindings:
                try:validate_binding(category,data,unit,bindings[unit['id']]);library_reused+=1
                except (OSError,ValueError):reuse_blocks.append('冻结复用素材已失效，请核对选图；不会自动改成付费生成')
            elif raw_valid(category,batch,row['group'],unit,_context=raw_context): reused+=1;retained_ids.append(unit['id'])
            elif unit.get('inherited_raw'):
                reused+=1;blocks.append('冻结继承素材待本地恢复，不能改为付费生成')
            else: pending.append(unit['id'])
    blocks.extend(reuse_blocks)
    slot_models=None
    try:
        if pending:
            # The immediately following start command revalidates this plan in
            # a new process. Reuse only the just-completed, key-fingerprinted
            # capability probe so one click never scans a large pool twice.
            slot_models=probe_slot_models(cache_seconds=300)
            config=active_model_config() if not slot_models else next(iter(slot_models.values()))
        else:config=api_config()
    except Exception as error:
        config={'model':'local-only','quality':None,'api_size':None};slot_models=None
        if pending:blocks.append(str(error))
    if pending:
        more,slots=readiness(category,config,snapshot);blocks+=more
    else:slots=[]
    wanted={u['id'] for row in rows for u in row['units']}
    for task in jobs(path):
        overlap=wanted&{u['id'] for row in task_rows(path,data,task) for u in row['units']}
        if task['status'] in ACTIVE and overlap: blocks.append('所选原图范围已有运行任务')
        elif task['status'] not in {'completed','cancelled'} and overlap: blocks.append('所选原图范围已有未完成任务，请继续原任务，不能另建预算')
    for p in io_glob(category_dir(category),'batch_revision_*/batch.json'):
        revision=read(p);target=revision.get('replacement',{})
        if target.get('batch')==batch and any(u['delivery_position']==target.get('position') for r in rows if r['group']==target.get('group') for u in r['units']) and any(t['status'] not in {'completed','cancelled'} for t in jobs(p.parent)):
            blocks.append('所选组已有单图重生成任务，请先处理该任务')
    if _parent:
        from tools.task_auto_recovery import validate_child_parent
        validate_child_parent(category,data,_parent)
        if not slot_models and (_parent.get('slot_models') or config!=_parent.get('config')):
            blocks.append('API配置与自动补缺授权不一致')
        slots=[s for s in slots if s in _parent['slots'] and s not in _parent.get('quarantined_slots',[])]
        if pending and not slots:blocks.append('自动补缺暂无可用的已授权密钥')
    if revision_conflicts(category,batch,groups,data,_parent['id'] if _parent else None,request.get('unit_ids')):blocks.append('同一图片范围已有运行任务，请等待请求收尾，不能重复执行')
    result={'category':category,'batch':batch,'groups':groups,'group_count':len(rows),'pending':pending,
            'pending_count':len(pending),'reused_count':reused+library_reused,'library_reused_count':library_reused,'retained_count':reused,'retained_unit_ids':retained_ids,'max_requests':len(pending)*2,'config':config,'slots':slots,
              'max_workers':len(slots),'concurrency':'key_pool','manifest_sha256':data['manifest_sha256'],'blocks':blocks}
    if slot_models:
        result['slot_models']=slot_models;result['model_label']=model_label(slot_models,config)
        remember_detected_model(slot_models)
    if request.get('unit_ids') is not None:result['unit_ids']=sorted(wanted)
    result['raw_reuse_sha256']=data.get('raw_reuse_sha256')
    result['reuse_summary']={key:reuse_selection[key] for key in ('rate','target','actual','shortfall')}
    from tools.task_auto_recovery import policy
    completion=request.get('auto_complete',not bool(data.get('replacement')))
    if completion=='automatic_cap':
        completion={'mode':'continuous','total_max_requests':len(pending)*6}
    result['auto_complete']=policy(completion,pending)
    if result['auto_complete'].get('mode')=='continuous':result['max_requests']=min(result['max_requests'],result['auto_complete']['total_max_requests'])
    if _parent and _parent.get('auto_complete',{}).get('mode')=='continuous':
        from tools.task_budget import binding,progress
        result['parent_budget']=binding(_parent)
        result['max_requests']=min(result['max_requests'],progress(_parent)['remaining'])
        if pending and not result['max_requests']:blocks.append('整批额度已用尽，原图等待追加额度')
    if data.get('replacement') and result['auto_complete']['enabled']:raise ValueError('补生成任务不允许递归增加补缺额度')
    result['total_max_requests']=result['max_requests']+result['auto_complete']['max_requests']
    result['plan_sha256']=digest(result)
    return result

def launch(category,batch,task):
    path=batch_dir(category,batch)/'tasks'/task
    log=io_path(path/'worker.log').open('ab')
    kwargs={'cwd':str(ROOT),'stdin':subprocess.DEVNULL,'stdout':log,'stderr':log}
    if os.name=='nt': kwargs['creationflags']=subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS
    else: kwargs['start_new_session']=True
    entry=runtime_paths.CODE_ROOT if os.environ.get('FACTORY_DATA_HOME') else ROOT
    try: proc=subprocess.Popen([sys.executable,'-X','utf8',str(entry/'factory.py'),'tasks','worker','--category',category,'--batch',batch,'--task',task],**kwargs)
    finally: log.close()
    return proc.pid

def start(request):
    with lock(ROOT/'.runtime/task-admin.lock'):
        return _start(request)

def _start(request,_parent=None,launch_task=True):
    if (ROOT/'.runtime/updates/installing.json').exists():raise ValueError('软件正在安装更新，请重新打开看板后执行任务')
    category=request['category'];batch=request['batch'];path,data=load_batch(category,batch)
    require_api(data)
    token=identifier(request['request_id'])
    if request.get('authorization')!='execute_selected_groups': raise ValueError('缺少本次所选组的明确执行指令')
    with lock(path/'control.lock'):
        file=path/'tasks'/token/'task.json'
        if io_path(file).exists():
            prior=read(file)
            requested=scoped_rows(path,data,request.get('groups'),request.get('unit_ids'))
            if prior['groups']!=[r['group'] for r in requested] or prior.get('unit_ids')!=(sorted(request['unit_ids']) if request.get('unit_ids') is not None else None): raise ValueError('请求标识已用于其他范围')
            return prior
        planned=plan(request,_parent=_parent)
        if planned['blocks']: raise ValueError('；'.join(planned['blocks']))
        if request.get('plan_sha256')!=planned['plan_sha256']: raise ValueError('任务计划已变化，请刷新执行信息')
        from tools.raw_library import adopt
        adopt(category,data,scoped_rows(path,data,planned['groups'],planned.get('unit_ids')))
        record={'schema_version':1,'id':token,'category':category,'batch':batch,'groups':planned['groups'],'source':request.get('source','agent'),
                'status':'queued','pid':None,'created_at':now(),'updated_at':now(),'config':planned['config'],
                'slots':planned['slots'],'max_workers':planned['max_workers'],'max_requests':planned['max_requests'],
                'total_units':planned['pending_count']+planned['reused_count'],'reused_units':planned['reused_count'],
                'library_reused_units':planned['library_reused_count'],'retained_units':planned['retained_count'],
                'retained_unit_ids':planned['retained_unit_ids'],
                'pending_unit_ids':planned['pending'],
                'requests_used':0,'attempts':{},'results':{},'manifest_sha256':data['manifest_sha256'],
                'plan_sha256':planned['plan_sha256'],'authorization':'execute_selected_groups',
                'download_job_id':'shared-'+digest({'category':category,'batch':batch,'task':token})[:32],
                'auto_complete':planned['auto_complete']}
        if 'unit_ids' in planned:record['unit_ids']=planned['unit_ids']
        if planned.get('slot_models'):record['slot_models']=planned['slot_models']
        if 'parent_budget' in planned:record['parent_budget']=planned['parent_budget']
        terms={k:record[k] for k in ('id','category','batch','groups','config','slots','max_workers','max_requests','manifest_sha256','authorization')}
        terms['auto_complete']=record['auto_complete']
        terms['download_job_id']=record['download_job_id']
        terms['pending_unit_ids']=record['pending_unit_ids']
        if 'unit_ids' in record:terms['unit_ids']=record['unit_ids']
        if 'slot_models' in record:terms['slot_models']=record['slot_models']
        if 'parent_budget' in record:terms['parent_budget']=record['parent_budget']
        record['license_sha256']=digest(terms)
        io_path(file.parent).mkdir(parents=True,exist_ok=True)
        with io_path(file.parent/'license.json').open('x',encoding='utf-8') as out: json.dump({'terms':terms,'requests_used':0,'attempts':{}},out,ensure_ascii=False)
        write(file,record)
        from tools.task_budget import initialize
        initialize(record)
        try: record['pid']=launch(category,batch,token) if launch_task else os.getpid()
        except Exception:
            record.update(status='failed_to_start');write(file,record);raise
        write(file,record)
        return record

def synchronize_license(file,state,*,repair_budget=False):
    license=read(file.parent/'license.json');terms=license['terms']
    if digest(terms)!=state.get('license_sha256') or any(state.get(k)!=v for k,v in terms.items()):
        raise ValueError('任务范围、模型或预算与一次性许可不一致')
    from tools.task_budget import project,reconcile
    original_license=license
    projected,license=project(state,license)
    state.update(projected)
    for ledger in (license,state):
        if type(ledger.get('requests_used')) is not int or not 0<=ledger['requests_used']<=terms['max_requests']:raise ValueError('许可请求计数无效')
        attempts=ledger.get('attempts')
        if not isinstance(attempts,dict) or any(not isinstance(k,str) or type(v) is not int or not 1<=v<=2 for k,v in attempts.items()):raise ValueError('单图请求计数无效')
        if sum(attempts.values())!=ledger['requests_used']:raise ValueError('请求总计与单图计数不一致')
    if state['requests_used']>license['requests_used'] or any(v>license['attempts'].get(k,0) for k,v in state['attempts'].items()):raise ValueError('任务计数超过许可记录，不能继续请求')
    path,data=load_batch(terms['category'],terms['batch'])
    valid={u['id'] for row in task_rows(path,data,terms) for u in row['units']}
    if not set(license['attempts'])<=valid:raise ValueError('许可包含范围外的生成单元')
    if 'pending_unit_ids' in terms:
        pending=terms['pending_unit_ids']
        if (not isinstance(pending,list) or any(not isinstance(uid,str) for uid in pending) or
                len(pending)!=len(set(pending)) or not set(pending)<=valid or not set(license['attempts'])<=set(pending)):
            raise ValueError('请求单元与许可冻结的初始生成范围不一致')
    state['requests_used']=max(state['requests_used'],license['requests_used'])
    for key,used in license['attempts'].items():
        if used>state['attempts'].get(key,0):
            state['attempts'][key]=used;state['results'][key]={'status':'request_reserved'}
    if repair_budget:return reconcile(file,state,original_license,persist=True)
    return license


def pause(request):
    category=request['category'];batch=request['batch'];path,data=load_batch(category,batch);task=identifier(request['task'])
    with lock(path/'control.lock'):
        file=path/'tasks'/task/'task.json';row=read(file)
        if request.get('unit_ids') is not None:
            synchronize_license(file,row)
            from tools.task_controls import change
            return {**row,'paused_unit_ids':change(row,request['unit_ids'],True)}
        if row['status'] not in ACTIVE: return row
        write(file.parent/'pause.json',{'requested_at':now()})
        return {**row,'pause_requested':True}

def resume(request):
    with lock(ROOT/'.runtime/task-admin.lock'):
        return _resume(request)

def _resume(request):
    if (ROOT/'.runtime/updates/installing.json').exists():raise ValueError('软件正在安装更新，请重新打开看板后继续任务')
    category=request['category'];batch=request['batch'];path,data=load_batch(category,batch);task=identifier(request['task'])
    require_api(data)
    if data.get('automatic_repair_parent'):
        raise ValueError('自动补缺子任务由原任务管理，请继续原任务')
    with lock(path/'control.lock'):
        file=path/'tasks'/task/'task.json';row=read(file)
        synchronize_license(file,row,repair_budget=True)
        from tools.task_controls import change,direct
        pause_file=file.parent/'pause.json'
        if request.get('unit_ids') is not None:
            change(row,request['unit_ids'],False)
            if io_path(pause_file).exists() or not (row['status'] in ACTIVE and alive(row.get('pid'))):
                from tools.task_worker import raw_valid
                others=[u['id'] for r in task_rows(path,data,row) for u in r['units'] if u['id'] not in request['unit_ids'] and not raw_valid(category,batch,r['group'],u)]
                if others:change(row,others,True)
                if io_path(pause_file).exists():io_path(pause_file).unlink()
        elif direct(row):change(row,sorted(direct(row)),False)
        if row['status'] in ACTIVE and alive(row.get('pid')): return row
        if row['status']=='completed': return row
        if row['status']=='cancelled':raise ValueError('该任务的目标已删除或重新组装，不能继续')
        if revision_conflicts(category,batch,row['groups'],data,task,row.get('unit_ids')):raise ValueError('同一图片范围已有运行任务，请等待请求收尾后继续')
        task_rows(path,data,row)
        validate_batch_phone(category,data,read(path/'snapshot.json'))
        if data.get('revision_kind')=='repair':
            from tools.task_actions import restore_repair_sources
            restore_repair_sources(category,data)
        records=task_rows(path,data,row)
        if request.get('only_failed') is not True:
            from tools.task_auto_recovery import prepare_local_resume
            prepare_local_resume(category,batch,row,records,request.get('unit_ids'))
        from tools.task_recovery import partition,no_work_message
        ready,summary=partition(category,batch,records,row)
        from tools.task_auto_recovery import paid_continuation
        repair_ready=paid_continuation(category,batch,records,row)
        only_failed=request.get('only_failed') is True
        retry_ids=[u['id'] for _,u in ready if row['results'].get(u['id'],{}).get('status')=='failed']
        row['resume_summary']=summary
        if not ready or (only_failed and not retry_ids):
            from tools.task_auto_recovery import remaining,has_returned_evidence
            if (summary['blocked_count'] and not row.get('local_render_errors') and not row.get('local_library_errors') and not remaining(row) and not repair_ready and not has_returned_evidence(category,batch,row,records)) or only_failed:
                row['updated_at']=now();write(file,row)
                raise ValueError(no_work_message(summary,only_failed))
            # All raw results may have arrived before an interrupted local render.
        if ready or repair_ready:
            if apply_detected_models(file,row) is None and not frozen_models_match(row): raise ValueError('API配置已变化，不能以不同模型或线路继续原任务')
            blocks,slots=readiness(category,row['config'],read(path/'snapshot.json'))
            if blocks: raise ValueError('；'.join(blocks))
            if not set(row['slots'])<=set(slots): raise ValueError('原任务绑定的 Key 槽位缺失')
            row['quarantined_slots']=[];row['resume_key_epoch']=secrets.token_hex(16)
        if repair_ready and row.get('auto_complete',{}).get('mode')=='continuous':
            row.setdefault('auto_recovery',{}).update(finished=False,phase='待继续补齐')
        if io_path(pause_file).exists(): io_path(pause_file).unlink()
        row.update(status='queued',pid=None,error=None,updated_at=now(),retry_unit_ids=retry_ids if only_failed else None);write(file,row)
        try: row['pid']=launch(category,batch,task)
        except Exception: row.update(status='failed_to_start');write(file,row);raise
        write(file,row);return row

def legacy_group(request):
    category=request['category'];category_dir(category);group=request.get('group')
    if type(group)!=int or group<1: raise ValueError('组号无效')
    project=vc.read_json(vc.project_dir(category)/'project.json');sources=project.get('prompt_sources',{})
    candidates=[sources.get('generation_manifest')] if sources.get('generation_manifest') else []
    if not candidates or not (ROOT/str(candidates[0])).is_file(): candidates=[sources.get('cover_manifest'),sources.get('detail_manifest'),sources.get('production_manifest')]
    result=[];missing=[];seen=set()
    for value in candidates:
        if not value: continue
        path=(ROOT/value).resolve()
        if ROOT.resolve() not in path.parents or not path.is_file(): missing.append(str(value));continue
        with path.open(encoding='utf-8-sig') as source:
            for i,line in enumerate(source):
                if i>=100000: break
                try: row=json.loads(line)
                except ValueError: continue
                if row.get('group_index')!=group: continue
                prompt=row.get('effective_prompt') or row.get('prompt') or row.get('positive_prompt')
                if not isinstance(prompt,str) or not prompt or prompt in seen: continue
                seen.add(prompt);result.append({'position':row.get('generation_position') or row.get('position') or len(result)+1,'kind':row.get('generation_kind') or row.get('role','detail'),'prompt':prompt,'service_role':row.get('service_role'),'historical':True})
                if len(result)>=30: break
    return {'group':group,'units':result,'note':'历史提示词，仅展示原记录；没有记录的变量与配置版本不推测补齐。' if result else '该组提示词未在当前登记来源中找到；旧图片保持可查看。','missing_sources':missing}


def dispatch(operation,request):
    if operation.startswith('native-'):
        from tools.task_native import dispatch as native_dispatch
        return native_dispatch(operation,request)
    if operation in {'raw-library-view','raw-library-folder','raw-library-qualify','raw-library-reindex'}:
        from tools import raw_library
        return {'raw-library-view':raw_library.view,'raw-library-folder':raw_library.folder,'raw-library-qualify':raw_library.qualify,'raw-library-reindex':raw_library.reindex}[operation](request)
    if operation=='queue-view':
        from tools.task_queue import view as queue_view
        return queue_view(request)
    if operation=='queue-detail':
        from tools.task_queue_details import view as queue_detail
        return queue_detail(request)
    if operation in {'postprocess-session','postprocess-preview','postprocess-preview-apply','postprocess-preview-sequence','postprocess-text'}:
        from tools import postprocess_workspace as workspace
        return {'postprocess-session':workspace.create,'postprocess-preview':workspace.preview,'postprocess-preview-apply':workspace.apply,'postprocess-preview-sequence':workspace.sequence,'postprocess-text':workspace.update_text}[operation](request)
    if operation in {'image-history','image-version-select'}:
        from tools import image_versions
        return image_versions.history(request) if operation=='image-history' else image_versions.select(request)
    if operation in {'postprocess-apply','postprocess-presets'}:
        from tools import postprocess_actions
        return postprocess_actions.apply(request) if operation=='postprocess-apply' else postprocess_actions.presets(request)
    if operation=='postprocess-view':
        from tools.postprocess_view import view as postprocess_view
        return postprocess_view(request)
    if operation in {'assets-view','assets-save','open-folder','package'}:
        from tools import task_assets
        return {'assets-view':lambda r:task_assets.settings(),'assets-save':task_assets.save,'open-folder':task_assets.open_folder,'package':task_assets.package}[operation](request)
    if operation in {'delete','replacement-prepare','repair-prepare'}:
        from tools import task_actions
        return task_actions.delete(request) if operation=='delete' else task_actions.prepare_replacement({**request,**({'mode':'repair'} if operation=='repair-prepare' else {})})
    if operation in {'keys-view','keys-save'}:
        from tools import task_keys
        return task_keys.view(request) if operation=='keys-view' else task_keys.save(request)
    if operation=='legacy-group': return legacy_group(request)
    if operation=='overlay-text': return overlay_text(request)
    if operation=='projects': return projects()
    if operation=='assemble': return assemble(request)
    if operation=='batches': return batches(request['category'])
    if operation=='view': return view(request)
    if operation=='plan': return plan(request)
    if operation=='start': return start(request)
    if operation=='resume': return resume(request)
    if operation=='pause': return pause(request)
    if operation=='retry': return resume({**request,'only_failed':True})
    raise ValueError('不支持的任务操作')

def cli(args):
    if args.operation=='worker':
        from tools.task_worker import run
        return run(args.category,args.batch,args.task)
    try:
        request=json.load(sys.stdin) if not sys.stdin.isatty() else {}
        result=dispatch(args.operation,request)
        print(json.dumps({'ok':True,'data':result},ensure_ascii=False));return 0
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False));return 1

def add_arguments(subparsers):
    p=subparsers.add_parser('tasks',help='Agent与看板共用的内容组及生成任务')
    p.add_argument('operation',choices=['native-discover','native-materialize','native-recover','native-register','native-ingest','native-instance','native-authorize','native-claim','native-reserve','native-outcome','native-status','native-cancel','native-plan','projects','overlay-text','assemble','batches','view','queue-view','queue-detail','raw-library-view','raw-library-folder','raw-library-qualify','raw-library-reindex','plan','start','resume','pause','retry','delete','replacement-prepare','repair-prepare','keys-view','keys-save','legacy-group','postprocess-view','postprocess-apply','postprocess-presets','postprocess-session','postprocess-preview','postprocess-preview-apply','postprocess-preview-sequence','postprocess-text','image-history','image-version-select','assets-view','assets-save','open-folder','package','worker'])
    p.add_argument('--category');p.add_argument('--batch');p.add_argument('--task');p.set_defaults(handler=cli)
