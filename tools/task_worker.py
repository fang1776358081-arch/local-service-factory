"""Detached shared task runner; reuses existing clients, request and image renderers."""
import copy
import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from pathlib import Path
from tools import task_library as lib
from tools import category_image_production as images
import image_generate


def save_task_raw(raw,payload,config,kind):
    if config.get('model')=='gpt-image-2-4k':
        from tools.category_4k_raw import save_4k_raw_png, WIDTH_TOLERANCE_SOURCE_CONTRACT
        if (config.get('raw_contract')!=WIDTH_TOLERANCE_SOURCE_CONTRACT or
                config.get('api_size')!='2560x3840' or config.get('quality')!='medium' or
                config.get('provider')!='relay' or str(config.get('base_url','')).rstrip('/')!='https://tinysnow.one/v1'):
            raise ValueError('TinySnow 4K 冻结请求参数或源图尺寸方案不一致')
        return save_4k_raw_png(raw,payload,archive_root=raw.parent/'originals',generation=config,
                              credential_epoch=None,anchor_y=0.0 if kind=='cover' else 0.5,
                              accepted_source_size='2352x3520',accepted_source_width_tolerance=16)
    result=images.save_raw_png(raw,payload,(1024,1536),provider=config.get('provider'),archive_root=raw.parent/'originals')
    # Even a standard-size response is re-encoded for the working PNG. Keep
    # the actual provider bytes as evidence, not its differently encoded work file.
    if not result.get('provider_original'):
        source=images._archive_provider_payload(raw.parent/'originals',raw,payload,result['source_format'],images.parse_size(result['source_returned_size']))
        result.update(provider_original=str(source),archive_status='preserved')
    return result


def raw_evidence_valid(raw,unit):
    try:
        if not lib.io_path(raw).is_file():return False
        from tools.raw_library import proof_file,source_category
        from tools.postprocess_view import confined as category_confined
        category=source_category(raw);category_confined(raw,category)
        receipt=lib.io_path(proof_file(raw,'.receipt.json',category))
        for suffix in ('.adoption.json','.inherited.json'):
            if lib.io_path(raw.with_suffix(suffix)).exists():proof_file(raw,suffix,category)
        if not images.valid_png(lib.io_path(raw),(1024,1536)) or not receipt.is_file() or receipt.stat().st_size>1024*1024:return False
        if lib.io_path(raw.with_suffix('.adoption.json')).exists():
            from tools.raw_library import adoption_valid
            return adoption_valid(raw,unit)
        if unit.get('inherited_raw'):
            from tools.raw_library import inheritance_valid
            return inheritance_valid(raw,unit)
        saved=lib.read(receipt)
        if isinstance(saved,dict) and saved.get('provider')=='codex_native':
            from tools.task_native import receipt_valid
            if not receipt_valid(saved,unit):return False
        return isinstance(saved,dict) and saved.get('prompt_sha256')==unit['prompt_sha256'] and saved.get('raw_sha256')==hashlib.sha256(lib.io_path(raw).read_bytes()).hexdigest()
    except (OSError,ValueError,TypeError,KeyError):return False


def register_library(category,batch,rows):
    if lib.load_batch(category,batch)[1].get('clean_output'):return []
    from tools.raw_library import register
    errors=[]
    for row in rows:
        for unit in row['units']:
            if raw_evidence_valid(lib.unit_raw(category,batch,row['group'],unit),unit):
                try:register(category,batch,row['group'],unit)
                except Exception as error:errors.append({'unit':unit['id'],'error':type(error).__name__})
    return errors


def resolve_raw(category,batch,group,unit,_context=None):
    """Resolve each panel independently, including saved partial repair evidence."""
    from tools.task_queue import ReadContext,revision_units
    context=_context or ReadContext()
    path,data=context.load(category,batch)
    published=data.get('replacements',{}).get(f'{group}:{unit["delivery_position"]}')
    candidates=list(revision_units(category,batch,group,unit,context.revisions(category),_context=context))
    # A published replacement defines active content; do not fall back to its old prompt.
    if published:candidates=candidates[:1]
    for sb,sg,su in candidates:
        raw=context.raw(category,sb,sg,su)
        if raw_evidence_valid(raw,su):return sb,sg,su,raw
    return None


def raw_valid(category,batch,group,unit,_seen=None,_context=None):
    from tools.task_queue import ReadContext
    context=_context or ReadContext()
    seen=set(_seen or ())
    if batch in seen:return False
    seen.add(batch)
    raw=context.raw(category,batch,group,unit)
    try:
        if raw_evidence_valid(raw,unit):return True
        if resolve_raw(category,batch,group,unit,_context=context):return True
        # An explicitly published revision satisfies this delivery without
        # rewriting the original prompts or licence of a paused parent task.
        _,data=context.load(category,batch)
        if f'{group}:{unit["delivery_position"]}' not in data.get('replacements',{}):return False
        source,g,units,_=lib.delivery_source(category,batch,group,unit['delivery_position'])
        if source==batch:return False
        kind='triptych' if unit['kind']=='triptych_panel' else unit['kind']
        target=lib.delivery_path(category,batch,group,unit['delivery_position'],kind)
        if not delivery_valid(target,unit):return False
        return all(raw_valid(category,source,g,u,seen,_context=context) for u in units)
    except (OSError,ValueError,TypeError,KeyError):return False


def delivery_valid(target,unit):
    try:
        size=images.parse_size(unit['final_size']) if isinstance(unit['final_size'],str) else tuple(unit['final_size'])
        return images.valid_png(lib.io_path(target),size) and isinstance(lib.read(target.with_suffix('.validation.json')),dict)
    except (OSError,ValueError,TypeError,KeyError):return False


def materialize(category,batch,data,rows,snapshot,*,failures=None,attempts=None):
    failures={} if failures is None else failures;attempts={} if attempts is None else attempts
    cfg=snapshot['business'];services=lib.overlay_services(cfg)
    original=images.load_category_config
    images.load_category_config=lambda c:copy.deepcopy(cfg) if c==category else original(c)
    try:
        for row in rows:
            by_position={}
            for unit in row['units']: by_position.setdefault(unit['delivery_position'],[]).append(unit)
            for position,units in by_position.items():
                kind='triptych' if units[0]['kind']=='triptych_panel' else units[0]['kind']
                target=lib.delivery_path(category,batch,row['group'],position,kind)
                key=f'{row["group"]}:{position}'
                if delivery_valid(target,units[0]):failures.pop(key,None);continue
                if attempts.get(key,0)>=2:continue
                attempts[key]=attempts.get(key,0)+1
                try:
                    source_batch,source_group,source_units,source_snapshot=lib.delivery_source(category,batch,row['group'],position)
                    resolved=[resolve_raw(category,source_batch,source_group,u) for u in source_units]
                    if not all(resolved):
                        if source_batch!=batch:raise ValueError('当前修订原图证据不完整，请保留已有版本并检查')
                        attempts[key]-=1
                        failures[key]={'group':row['group'],'position':position,'error':'MissingRaw','attempts':attempts[key]}
                        continue
                    source_data=data if source_batch==batch else lib.load_batch(category,source_batch)[1]
                    source_services=lib.overlay_services(source_snapshot['business'])
                    complete_row=lib.selected(lib.batch_dir(category,source_batch),source_data,[source_group])[0]
                    count=len({u['delivery_position'] for u in complete_row['units']})
                    render_delivery(category,source_batch,source_data,{**complete_row,'group':source_group},position,source_units,source_snapshot,source_services,count,target,
                        raw_sources={u['id']:r[3] for u,r in zip(source_units,resolved)})
                    failures.pop(key,None)
                except Exception as error:
                    failures[key]={'group':row['group'],'position':position,'error':type(error).__name__,'attempts':attempts[key]}
            # Persist the new namespace alongside the original unpackaged queue.
            produced=[]
            for position,units in by_position.items():
                kind='triptych' if units[0]['kind']=='triptych_panel' else units[0]['kind']
                target=lib.delivery_path(category,batch,row['group'],position,kind)
                if delivery_valid(target,units[0]): produced.append(str(target.resolve()))
            if produced and not data.get('replacement'):
                # A busy delivery queue must not abandon units that already reserved a request.
                try:
                    from tools.dashboard_delivery import load_state,write_state
                    statefile=lib.ROOT/'.runtime/dashboard_delivery_state.json'
                    with lib.lock(statefile.with_suffix('.lock')):
                        state=load_state(statefile)
                        project=state['projects'].setdefault(category,{'pending_groups':{}})
                        pool=project.setdefault('pending_library_groups',{});queue_key=f'{batch}:{row["group"]}'
                        all_units=lib.selected(lib.batch_dir(category,batch),lib.load_batch(category,batch)[1],[row['group']])[0]['units']
                        pool[queue_key]={'batch_id':batch,'group_index':row['group'],'expected_image_count':len({u['delivery_position'] for u in all_units}),
                            'paths':sorted(set(pool.get(queue_key,{}).get('paths',[]))|set(produced)),'updated_at':lib.now()}
                        write_state(statefile,state)
                except (ValueError,OSError):
                    continue
    finally: images.load_category_config=original
    return list(failures.values())


def render_delivery(category,batch,data,row,position,units,snapshot,services,count,target,raw_sources=None):
    import secrets
    import shutil
    from tools.image_versions import selection_token as current_revision
    before=current_revision(target)
    # Stage locally; a partial renderer output must not replace the current image.
    candidate=target.parent/'.render'/f'{position}_{secrets.token_hex(4)}.png'
    lib.io_path(candidate.parent).mkdir(parents=True,exist_ok=True)
    kind='triptych' if units[0]['kind']=='triptych_panel' else units[0]['kind']
    records=[]
    for u in units:
        record={**u,'index':(row['group']-1)*len(row['units'])+u['position'],'category_id':category,'generation_kind':u['kind'],'group_index':u['source_group'],
            'raw_target':str((raw_sources or {}).get(u['id']) or lib.unit_raw(category,batch,row['group'],u)),
            'generation_target_id':f'{batch}:{u["id"]}','delivery_target_id':f'{batch}:g{row["group"]}:d{position}'}
        record['service_items']=images._record_overlay_service_items(record,services);records.append(record)
    from tools.graphic_templates import production_rules
    render_rules=production_rules(snapshot.get('postprocess'),(row['group']-1)*count+position-1,int(records[0]['prompt_sha256'][:12],16),kind)
    if kind=='triptych':images.compose_triptych(records,candidate,data['phone'],services,postprocess_rules=render_rules)
    else:
        record=records[0]
        images.apply_overlays(Path(record['raw_target']),candidate,data['phone'],kind,record['group_index'],position,
            record['service_items'],record['final_size'],service_role=record.get('service_role'),
            generation_target_id=record['generation_target_id'],delivery_target_id=record['delivery_target_id'],
            category_id=category,structure_version=record['structure_version'],generation_mode=record['generation_mode'],postprocess_rules=render_rules,
            signboard_phone_required=(record.get('salvage_context',{}).get('shot',{}).get('type')=='storefront') if category=='diving_salvage' else None)
    if not delivery_valid(candidate,units[0]):raise ValueError('本地合成未产生有效成品与校验记录')
    event_id=lib.digest({'batch':batch,'group':row['group'],'position':position,'snapshot':lib.digest(snapshot),
        'inputs':[{'unit':u['id'],'sha256':hashlib.sha256(lib.io_path(r['raw_target']).read_bytes()).hexdigest()} for u,r in zip(units,records)]})
    with lib.lock(lib.ROOT/'.runtime/task-admin.lock',wait_seconds=10):
        live=lib.load_batch(category,batch)[1]
        if lib.generation_route(live)=='codex_native':
            from tools.task_native import load_state as native_state
            if native_state(lib.batch_dir(category,batch))['cancelled']:raise ValueError('内置任务已取消，不发布迟到成品')
        if row['group'] in live.get('deleted_groups',[]) or position in live.get('deleted_images',{}).get(str(row['group']),[]):raise ValueError('图片目标已失效，保留原图，不发布迟到成品')
        if current_revision(target)!=before:raise ValueError('当前版本已改变，保留用户选择，不覆盖迟到成品')
        from tools.image_versions import publish
        publish(target,candidate,category,'local_recovery',old_sources=[r['raw_target'] for r in records],new_sources=[r['raw_target'] for r in records],event_id=event_id)


def _run(category,batch,task,*,generate=None,clients=None,render=None):
    path,data=lib.load_batch(category,batch);task=lib.identifier(task);file=path/'tasks'/task/'task.json'
    lib.require_api(data)
    # Parent publishes pid under control lock; waiting avoids overwriting reserved requests.
    for _ in range(100):
        if not lib.io_path(path/'control.lock').exists(): break
        time.sleep(.05)
    with lib.lock(path/'tasks'/task/'worker.lock'):
        state=lib.read(file)
        if state['status']=='cancelled':return 1
        if data.get('automatic_repair_parent'):
            from tools.task_auto_recovery import validate_child_parent
            binding=data['automatic_repair_parent']
            parentfile=lib.batch_dir(category,binding['batch'])/'tasks'/binding['task']/'task.json'
            validate_child_parent(category,data,lib.read(parentfile))
        license=lib.synchronize_license(file,state,repair_budget=True)
        if state['status']=='completed': return 0
        if state.get('authorization')!='execute_selected_groups': raise ValueError('任务缺少范围授权')
        rows=lib.task_rows(path,data,state);snapshot=lib.read(path/'snapshot.json')
        if data.get('revision_kind')=='repair':
            from tools.task_actions import restore_repair_sources
            restore_repair_sources(category,data)
        if state['manifest_sha256']!=data['manifest_sha256']: raise ValueError('冻结任务清单不一致')
        # Saved returned bytes/registered URLs are free recovery evidence, even
        # on old licences or when automatic paid repair rounds are disabled.
        from tools.task_auto_recovery import has_returned_evidence,recover_returned
        if has_returned_evidence(category,batch,state,rows):
            recover_returned(category,batch,state,rows,file)
        from tools.task_recovery import partition,blocked_reason,no_work_message
        queue,state['resume_summary']=partition(category,batch,rows,state)
        state['retained_unit_ids']=sorted(set(state.get('retained_unit_ids',[]))|set(state['resume_summary']['retained_unit_ids']))
        if state.get('retry_unit_ids') is not None:
            queue=[item for item in queue if item[1]['id'] in state['retry_unit_ids']]
        if generate is None:
            lib.validate_batch_phone(category,data,snapshot)
            if queue:
                if lib.apply_detected_models(file,state) is None and not lib.frozen_models_match(state): raise ValueError('API配置与任务不一致')
                blocks,_=lib.readiness(category,state['config'],snapshot)
                if blocks: raise ValueError('；'.join(blocks))
        config=copy.deepcopy(state['config']);guard=threading.Lock();quarantine=set(state.get('quarantined_slots',[]))
        from tools.task_auto_recovery import pause_requested,save_returned,download_context,remaining,recover_returned
        def paused():return pause_requested(category,batch,state)
        from tools import task_controls as controls,task_scheduler as scheduler
        def unit_paused(uid):return uid in controls.paused(state,data)
        baseline=state['resume_summary']['reused_count'];generated_now=set()
        state.update(status='running',pid=os.getpid(),updated_at=lib.now(),error=None,completed_units=baseline,
            recovered_units=sum(raw_valid(category,batch,row['group'],u) and not raw_evidence_valid(lib.unit_raw(category,batch,row['group'],u),u) for row in rows for u in row['units']))
        lib.write(file,state)
        def persist(): state['updated_at']=lib.now();lib.write(file,state)
        def event(value):
            with lib.io_path(file.parent/'events.jsonl').open('a',encoding='utf-8') as out: out.write(json.dumps({**value,'at':lib.now()},ensure_ascii=False)+'\n')
        render_failures={};render_attempts={}
        def render_local(affected=None):
            # A one-panel licence must still compose all three frozen sources.
            render_rows=lib.delivery_rows(path,data,state)
            if affected is not None:
                keys={(g,u['delivery_position']) for g,u in affected}
                render_rows=[{**r,'units':[u for u in r['units'] if (r['group'],u['delivery_position']) in keys]} for r in render_rows if any((r['group'],u['delivery_position']) in keys for u in r['units'])]
            if render is not None:render(category,batch,data,render_rows,snapshot);return
            library_rows=rows if affected is None else [{'group':g,'units':[u]} for g,u in affected]
            state['local_library_errors']=register_library(category,batch,library_rows)
            state['local_render_errors']=materialize(category,batch,data,render_rows,snapshot,failures=render_failures,attempts=render_attempts)
            persist()
        def request_one(item):
            uid=item[1]['id'];token=None
            try:
                while not paused() and not unit_paused(uid):
                    with guard:
                        slots=[slot for slot,_ in clients if slot not in quarantine]
                    if not slots:return False
                    delay=state['results'].get(uid,{}).get('retry_not_before',0)-time.time()
                    if delay>0:time.sleep(min(.2,delay));continue
                    if token is None:token=scheduler.register(state,uid,slots)
                    claim=scheduler.claim(token,slots)
                    if claim is None:time.sleep(.1);continue
                    slot,lease=claim;token=None
                    try:return perform_request(item,slot,next(client for s,client in clients if s==slot))
                    finally:lease.__exit__(None,None,None)
                return False
            finally:
                if token is not None:scheduler.unregister(token)
        def perform_request(item,slot,client):
            group,unit=item;uid=unit['id']
            with guard:
                if paused() or unit_paused(uid) or slot in quarantine or state['requests_used']>=state['max_requests'] or state['attempts'].get(uid,0)>=2: return False
                from tools.task_budget import reserve
                if not reserve(state,uid,state['requests_used']+1,state['attempts'].get(uid,0)+1):
                    state['shared_budget_exhausted']=True;persist();return False
                state['requests_used']+=1;state['attempts'][uid]=state['attempts'].get(uid,0)+1
                state['results'][uid]={'status':'request_reserved','slot':slot,'attempt':state['attempts'][uid],'request_number':state['requests_used']}
                license.update(requests_used=state['requests_used'],attempts=dict(state['attempts']))
                lib.write(file.parent/'license.json',license);persist()
                request_number=state['requests_used'];attempt_number=state['attempts'][uid]
                request_config=dict((state.get('slot_models') or {}).get(str(slot)) or config)
                event({'kind':'request_reserved','unit':uid,'group':group,'slot':slot,'model':request_config['model'],'request':state['requests_used'],'prompt_sha256':unit['prompt_sha256']})
            returned=False
            try:
                if generate is None:
                    context=download_context(path,state,unit,{'request_number':request_number,'attempt':attempt_number})
                    request_config['_image_download_context']=context
                payload=(generate or image_generate.generate_one)(client,request_config,unit['prompt'])
                returned=True
                save_returned(state,unit,request_number,payload)
                raw=lib.unit_raw(category,batch,group,unit);lib.io_path(raw.parent).mkdir(parents=True,exist_ok=True)
                save_result=save_task_raw(raw,payload,request_config,unit['kind'])
                lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':hashlib.sha256(lib.io_path(raw).read_bytes()).hexdigest(),'task':task,'unit':uid,'source':save_result})
                context=download_context(path,state,unit,{'request_number':request_number,'attempt':attempt_number})
                from tools.image_download_receipts import mark_materialized
                mark_materialized(context,hashlib.sha256(lib.io_path(raw).read_bytes()).hexdigest())
                with guard:
                    state['results'][uid]={'status':'generated','slot':slot,'request_number':request_number,'attempt':attempt_number};state['consecutive_errors']=0
                    generated_now.add(uid);state['completed_units']=baseline+len(generated_now)
                    event({'kind':'generated','unit':uid,'group':group,'slot':slot});persist()
                return True
            except Exception as error:
                from tools.task_request_errors import classify,continuous
                classification,rejection_kind=('local_save_failed',None) if returned else classify(error)
                if classification=='retryable_rejection' and not continuous(state):classification='request_rejected'
                with guard:
                    # Never persist provider exceptions which may contain keys or signed URLs.
                    state['results'][uid]={'status':'failed','slot':slot,'error':classification or type(error).__name__,'request_number':request_number,'attempt':attempt_number}
                    http_status=getattr(error,'status_code',None)
                    if type(http_status) is int and 100<=http_status<=599:state['results'][uid]['http_status']=http_status
                    if rejection_kind:state['results'][uid]['rejection_kind']=rejection_kind
                    if isinstance(error,getattr(image_generate,'ReturnedImageDownloadError',())): state['results'][uid]['receipt_id']=getattr(error,'receipt_id',None)
                    if classification in {'transient','retryable_rejection'}:
                        delay=min(30,2**attempt_number)
                        retry_after=getattr(error,'retry_after',None)
                        if isinstance(retry_after,(int,float)) and not isinstance(retry_after,bool) and 0<retry_after<=60:delay=max(delay,retry_after)
                        state['results'][uid]['retry_not_before']=time.time()+delay
                        state['results'][uid]['cooldown_seconds']=delay
                    state['consecutive_errors']=state.get('consecutive_errors',0)+1
                    if classification in {'balance_exhausted','authentication_failed'}: quarantine.add(slot)
                    # A failed unit never stops unrelated units. Retry eligibility is
                    # shared with resume; uncertain/returned-image failures are skipped.
                    event({'kind':'failed','unit':uid,'group':group,'slot':slot,'error':classification or type(error).__name__});persist()
                return False
        try:
            clients=(clients if clients is not None else images.openai_clients_by_slot(config,state['slots'])) if queue else []
            maximum=max(1,min(state['max_workers'],len(clients)))
            limit=max(1,min(maximum,state.get('dispatch_limit',maximum)));healthy=0
            with ThreadPoolExecutor(max_workers=maximum) as pool:
                active={}
                while queue or active:
                    available=[c for c in clients if c[0] not in quarantine]
                    while queue and len(active)<min(limit,len(available)) and not paused() and state['requests_used']<state['max_requests']:
                        eligible=next((i for i,item in enumerate(queue) if not unit_paused(item[1]['id']) and state['results'].get(item[1]['id'],{}).get('retry_not_before',0)<=time.time()),None)
                        if eligible is None:break
                        item=queue.pop(eligible);active[pool.submit(request_one,item)]=item
                    if not active:
                        if paused() or not available or state.get('shared_budget_exhausted') or state['requests_used']>=state['max_requests'] or all(unit_paused(u['id']) for _,u in queue):break
                        time.sleep(.2);continue
                    done_futures,_=wait(active,timeout=.2,return_when=FIRST_COMPLETED)
                    affected=[]
                    for future in done_futures:
                        item=active.pop(future)
                        try:future.result()
                        except ValueError:continue
                        except OSError:
                            event({'kind':'local_os_error','error':'PermissionError','unit':item[1]['id']})
                            if not raw_valid(category,batch,item[0],item[1]) and not unit_paused(item[1]['id']) and blocked_reason(state,item[1]) is None:queue.append(item)
                            continue
                        if state['results'].get(item[1]['id'],{}).get('error')=='image_download_failed':
                            recover_returned(category,batch,state,rows,file,once=True,only_ids={item[1]['id']})
                        affected.append(item)
                        result=state['results'].get(item[1]['id'],{})
                        if result.get('error')=='transient':limit=max(1,limit//2);healthy=0
                        elif result.get('status')=='generated':
                            healthy+=1
                            if healthy>=2:limit=min(maximum,limit+1);healthy=0
                        if not state.get('shared_budget_exhausted') and not raw_valid(category,batch,item[0],item[1]) and not unit_paused(item[1]['id']) and blocked_reason(state,item[1]) is None:queue.append(item)
                    if affected:
                        state['dispatch_limit']=limit
                        try:render_local(affected)
                        except OSError:event({'kind':'local_os_error','error':'PermissionError'})
            try:render_local()
            except OSError:event({'kind':'local_os_error','error':'PermissionError'})
            done=all(raw_valid(category,batch,row['group'],u) for row in rows for u in row['units'])
            local_failed=bool(state.get('local_render_errors') or state.get('local_library_errors')) if render is None else False
            if done and not local_failed and data.get('replacement'):
                from tools.task_actions import commit_replacement
                with lib.lock(lib.ROOT/'.runtime/task-admin.lock',wait_seconds=10):
                    if not commit_replacement(category,batch,data):raise ValueError('新图未完成本地合成，原位置保持不变')
            _,state['resume_summary']=partition(category,batch,rows,state)
            summary=state['resume_summary'];user_paused=paused()
            pause_needed=user_paused or summary['ready_count']>0 or summary.get('paused_count',0)>0
            state.update(status='failed' if local_failed else 'completed' if done else 'paused' if pause_needed else 'completed_with_errors',
                         completed_units=summary['reused_count'],skipped_units=summary['blocked_count'],
                         quarantined_slots=sorted(quarantine),finished_at=lib.now())
            if remaining(state) and not user_paused and not summary['ready_count'] and (summary['blocked_count']>summary.get('paused_count',0) or local_failed):
                state['status']='recovering';state.pop('finished_at',None)
            if local_failed:
                state['error']=f'原图已保留；{len(state["local_render_errors"])} 张本地合成失败。继续原任务可重做合成，已保存原图不再调用生图接口'
            elif not done:
                if user_paused:state['error']='已按要求暂停调度，已发出请求已收尾'
                elif summary['ready_count']:
                    state['error']=(f'所有可用密钥槽位均已隔离或不可用，剩余 {summary["ready_count"]} 张保留原预算'
                        if not any(slot not in quarantine for slot,_ in clients) else
                        f'可继续 {summary["ready_count"]} 张；跳过待处理 {summary["blocked_count"]} 张，沿用原预算')
                else:state['error']=f'已结束：成功 {summary["reused_count"]} 张，跳过待处理 {summary["blocked_count"]} 张；'+no_work_message(summary)
            if state['status']=='recovering':state['error']=None
            if state.get('auto_complete',{}).get('enabled'):
                ledger=state.setdefault('auto_recovery',{})
                if 'requests_used' not in ledger:
                    used=0
                    for tid,entry in ledger.get('children',{}).items():
                        childfile=lib.batch_dir(category,entry.get('batch',''))/'tasks'/tid/'task.json'
                        if not lib.io_path(childfile).exists():continue
                        try:used+=lib.read(childfile)['requests_used']
                        except (OSError,ValueError,KeyError,TypeError):pass
                    ledger['requests_used']=used
            persist();return 0 if state['status'] in {'completed','completed_with_errors','recovering'} else 1
        except OSError:
            # A Windows sharing violation is local contention, not a failed generation.
            state.update(status='paused',error='本地文件暂时被占用，已保留已生成图片，继续原任务即可',finished_at=lib.now())
            try:persist()
            except OSError:pass
            try:event({'kind':'local_os_error','error':'PermissionError'})
            except OSError:pass
            return 1
        except Exception as error:
            message=('本地 Python 缺少依赖 '+(error.name or '未知模块')+'，请修复开发环境后继续原任务') if isinstance(error,ModuleNotFoundError) else type(error).__name__+'：本地执行失败，请让 Agent 检查'
            state.update(status='failed',error=message,finished_at=lib.now());persist();return 1
        finally:
            for _,client in clients or []:
                if hasattr(client,'close'):
                    try:client.close()
                    except Exception:pass  # Cleanup must not undo a durable outcome.


def run(category,batch,task,**test_hooks):
    _,data=lib.load_batch(category,batch)
    lib.require_api(data)
    try:
        def cycle():
            from tools import task_controls as controls,task_auto_recovery as recovery
            file=lib.batch_dir(category,batch)/'tasks'/task/'task.json'
            while True:
                before=lib.read(file);epoch=controls.resume_epoch(before)
                _,current_data=lib.load_batch(category,batch);binding=current_data.get('automatic_repair_parent')
                if binding:
                    parent=lib.read(lib.batch_dir(category,binding['batch'])/'tasks'/binding['task']/'task.json')
                    if parent.get('pid')!=os.getpid() or parent['status']!='recovering':return 1
                _run(category,batch,task,**test_hooks)
                result=recovery.finish(category,batch,task,**test_hooks)
                after=lib.read(file)
                if binding:
                    parent=lib.read(lib.batch_dir(category,binding['batch'])/'tasks'/binding['task']/'task.json')
                    if parent.get('pid')!=os.getpid() or parent['status']!='recovering':return result
                healthy=any(s not in after.get('quarantined_slots',[]) for s in after['slots'])
                if (after.get('pid')==os.getpid() and after['status']=='paused' and
                    controls.resume_epoch(after)!=epoch and after.get('resume_summary',{}).get('ready_count',0)>0 and
                    healthy and not recovery.pause_requested(category,batch,after)):
                    continue
                return result
        from tools import runtime_paths
        snapshot=lib.read(lib.batch_dir(category,batch)/'snapshot.json')
        version=snapshot.get('rules_version','workspace')
        if version!='workspace':
            from tools.rule_updates import valid_version
            root=lib.ROOT/'.runtime/rules'/valid_version(version)
            if not lib.io_path(root/'manifest.json').is_file():raise ValueError('该批次冻结规则版本缺失，不能改用新规则继续')
            with runtime_paths.use_rules(root):
                return cycle()
        return cycle()
    except Exception as error:
        path=lib.batch_dir(category,batch)/'tasks'/lib.identifier(task)/'task.json'
        if lib.io_path(path).exists():
            state=lib.read(path)
            # A second worker must not mark the legitimate owner as failed.
            if state.get('pid')!=os.getpid() and state.get('pid') and lib.alive(state['pid']): return 1
            state.update(status='failed',error=str(error) if isinstance(error,ValueError) else type(error).__name__,updated_at=lib.now())
            lib.write(path,state)
        return 1
