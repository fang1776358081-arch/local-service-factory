"""Read-only raw-material board. Revision attempts never create extra cards."""
from tools import task_library as lib


class ReadContext:
    """Memoize immutable manifests within ONE read, never in paid execution."""
    def __init__(self,full=False):
        self.batches={};self.rows={};self.outputs={};self.controls={};self.parents={};self.budgets={};self.revision_records={};self.full=full

    def load(self,category,batch):
        key=(category,batch)
        if key not in self.batches:self.batches[key]=lib.load_batch(category,batch)
        return self.batches[key]

    def output(self,category,batch):
        from tools.task_assets import batch_root
        key=(category,batch)
        if key not in self.outputs:
            _,data=self.load(category,batch)
            root=lib.ROOT/'.runtime/image-work' if data.get('clean_output') else batch_root(data)
            self.outputs[key]=root/category/'library'/lib.identifier(batch)
        return self.outputs[key]

    def raw(self,category,batch,group,unit):
        return self.output(category,batch)/f'group_{group:04d}'/'raw'/f'{unit["id"]}.png'

    def delivery(self,category,batch,group,position,kind):
        return self.output(category,batch)/f'group_{group:04d}'/f'{position:02d}_{kind}.png'

    def parent(self,category,binding):
        key=(category,binding['batch'],binding['task'])
        if key not in self.parents:
            path,_=self.load(category,binding['batch'])
            self.parents[key]=lib.read(path/'tasks'/lib.identifier(binding['task'])/'task.json')
        return self.parents[key]

    def paused(self,state):
        from tools.task_controls import paused
        key=(state['category'],state['batch'],state['id'])
        if key not in self.controls:
            _,data=self.load(state['category'],state['batch'])
            self.controls[key]=paused(state,data)
        return self.controls[key]

    def row(self,category,batch,group):
        if not self.full:
            key=(category,batch,group)
            if key not in self.rows:
                path,data=self.load(category,batch);self.rows[key]=lib.selected(path,data,[group])[0]
            return self.rows[key]
        key=(category,batch)
        if key not in self.rows:
            path,data=self.load(category,batch)
            groups=[g for g in range(1,data['count']+1) if g not in data.get('deleted_groups',[])]
            self.rows[key]={r['group']:r for r in lib.selected(path,data,groups)} if groups else {}
        if group not in self.rows[key]:raise ValueError('原图来源组不存在')
        return self.rows[key][group]

    def revisions(self,category):
        if category not in self.revision_records:
            self.revision_records[category]=[lib.read(p) for p in lib.category_dir(category).glob('batch_revision_*/batch.json')]
        return self.revision_records[category]


def origin_keys(category,batch,rows,_context=None):
    context=_context or ReadContext()
    _,data=context.load(category,batch);target=data.get('replacement')
    if not target:return {(batch,row['group'],u['id']) for row in rows for u in row['units']}
    origin=target['batch'];group=target['group'];position=target['position']
    if origin=='legacy':return {(origin,group,f'd{position}-p{u.get("panel_index",0)}') for row in rows for u in row['units']}
    originals=[u for u in context.row(category,origin,group)['units'] if u['delivery_position']==position]
    all_child=context.row(category,batch,1)['units']
    ordered={u['id']:originals[i]['id'] for i,u in enumerate(all_child) if i<len(originals)}
    if len(ordered)!=len(all_child):raise ValueError('修订原图与原卡片结构不一致')
    return {(origin,group,ordered[u['id']]) for row in rows for u in row['units']}


def revision_units(category,batch,group,unit,revisions,_context=None):
    """Published content first, then exact-prompt repair evidence per panel."""
    context=_context or ReadContext()
    path,data=context.load(category,batch)
    published=data.get('replacements',{}).get(f'{group}:{unit["delivery_position"]}')
    original=[u for u in context.row(category,batch,group)['units'] if u['delivery_position']==unit['delivery_position']]
    index=next(i for i,u in enumerate(original) if u['id']==unit['id'])
    if published:
        _,child=context.load(category,published)
        if child.get('replacement')!={'batch':batch,'group':group,'position':unit['delivery_position']}:raise ValueError('单图版本与原图片关联不一致')
        units=context.row(category,published,1)['units']
        if index<len(units):yield published,1,units[index]
    yield batch,group,unit
    for revision in revisions:
        if revision.get('replacement')!={'batch':batch,'group':group,'position':unit['delivery_position']} or revision.get('revision_kind')!='repair':continue
        units=context.row(category,revision['id'],1)['units']
        if index<len(units) and units[index]['prompt_sha256']==unit['prompt_sha256']:yield revision['id'],1,units[index]


def view(request,*,_detail=None):
    from tools.task_budget import SnapshotChanged
    for attempt in range(3):
        detail=dict(_detail) if _detail is not None else None
        try:
            result=_view(request,_detail=detail)
        except SnapshotChanged:
            if attempt==2:raise
            continue
        if _detail is not None:_detail.update(detail)
        return result


def _view(request,*,_detail=None):
    from tools.task_worker import raw_evidence_valid,delivery_valid
    from tools.task_recovery import blocked_reason,REASONS
    offset=request.get('offset',0);limit=request.get('limit',60);column=request.get('column')
    if type(offset)!=int or offset<0 or type(limit)!=int or not 1<=limit<=200:raise ValueError('分页参数错误')
    if column not in (None,'pending','ongoing','completed'):raise ValueError('看板栏目无效')
    pages=request.get('pages');summary_only=request.get('summary_only',False)
    if type(summary_only)!=bool:raise ValueError('汇总参数错误')
    since=request.get('since')
    if since is not None and (not isinstance(since,str) or len(since)!=64 or any(c not in '0123456789abcdef' for c in since)):raise ValueError('状态版本参数错误')
    if pages is not None:
        if not isinstance(pages,list) or not 1<=len(pages)<=150:raise ValueError('分页窗口数量错误')
        for page in pages:
            if not isinstance(page,dict) or page.get('column') not in ('pending','ongoing','completed') or type(page.get('offset'))!=int or page['offset']<0 or type(page.get('limit'))!=int or not 1<=page['limit']<=200:raise ValueError('分页窗口参数错误')
    categories=[request['category']] if request.get('category') else [p['id'] for p in lib.projects()]
    cards=[];warnings=[];counts=dict(pending=0,ongoing=0,completed=0);executor_active=0;delivery_counts=dict(ready=0,waiting=0)
    context=ReadContext(full=True);source_counts=dict(library=0,generated=0,retained=0);request_counts=dict(used=0,maximum=0);active_tasks=0;recovering_tasks=0
    accessible={}
    def can_read(category,batch):
        if not request.get('board_overview'):return True
        key=(category,batch)
        if key not in accessible:
            try:context.output(category,batch);accessible[key]=True
            except ValueError:accessible[key]=False
        return accessible[key]
    for category in categories:
        home=lib.category_dir(category)
        revisions=[lib.read(p) for p in lib.io_glob(home,'batch_revision_*/batch.json')]
        for data in lib.batches(category):
            if request.get('batch') and data['id']!=request['batch']:continue
            if data['status']!='ready':
                warnings.append({'category':category,'batch':data['id'],'reason':'批次组装尚未完成，不能建立完整原图范围'});continue
            batch=data['id'];path=lib.batch_dir(category,batch);tasks=lib.jobs(path,_budget_memo=context.budgets)
            related=[r for r in revisions if r.get('replacement',{}).get('batch')==batch]
            for r in related:tasks.extend(lib.jobs(lib.batch_dir(category,r['id']),_budget_memo=context.budgets))
            projected=[]
            for state in tasks:
                taskpath,taskdata=context.load(category,state['batch'])
                from tools.task_budget import project as budget_projection,progress as budget_progress,licence_snapshot
                licence=licence_snapshot(taskpath/'tasks'/state['id']/'license.json',context.budgets)
                state,licence=budget_projection(state,licence,memo=context.budgets)
                terms=licence['terms']
                if lib.digest(terms)!=state['license_sha256']:raise ValueError('许可冻结记录校验失败')
                if any(state.get(k)!=v for k,v in terms.items()):warnings.append({'category':category,'batch':batch,'task':state['id'],'reason':'任务状态与冻结许可不一致，统计使用许可记录'})
                if state.get('requests_used')!=licence['requests_used'] or state.get('attempts')!=licence['attempts']:warnings.append({'category':category,'batch':batch,'task':state['id'],'reason':'任务计数尚未与许可一致，统计使用已记录的许可账本'})
                if state.get('auto_complete',{}).get('mode')=='continuous':
                    state['_queue_shared_budget']=budget_progress(state,memo=context.budgets)
                    request_counts['used']+=state['_queue_shared_budget']['used']
                elif not state.get('parent_budget'):request_counts['used']+=licence.get('requests_used',0)
                if not taskdata.get('automatic_repair_parent'):request_counts['maximum']+=terms['max_requests']+terms.get('auto_complete',{}).get('max_requests',0)
                results=dict(state.get('results',{}))
                for uid,attempts in licence['attempts'].items():
                    if attempts>state.get('attempts',{}).get(uid,0):results[uid]={'status':'request_reserved'}
                projected.append({**state,**terms,'attempts':licence['attempts'],'requests_used':licence['requests_used'],'results':results,
                                  '_automatic_parent':taskdata.get('automatic_repair_parent'),'_pending_frozen':'pending_unit_ids' in terms})
                if state['status'] in lib.ACTIVE:active_tasks+=1
                if state['status']=='recovering':recovering_tasks+=1
            tasks=projected
            owners={}
            for state in sorted(tasks,key=lambda t:t['created_at']):
                taskpath,taskdata=context.load(category,state['batch'])
                if taskdata.get('replacement',{}).get('group') in data.get('deleted_groups',[]):continue
                # This is a read model, not a licence mutation or execution plan.
                # Completed ledgers survive deletion; map only their live targets.
                for group in state['groups']:
                    if group in taskdata.get('deleted_groups',[]):continue
                    r=context.row(category,state['batch'],group)
                    for u in r['units']:
                        if state.get('unit_ids') is not None and u['id'] not in state['unit_ids']:continue
                        for key in origin_keys(category,state['batch'],[{**r,'units':[u]}],context):owners.setdefault(key,[]).append({**state,'_queue_unit':u['id'],'_queue_inherited':bool(u.get('inherited_raw'))})
            groups=[g for g in range(1,data['count']+1) if g not in data.get('deleted_groups',[])]
            if not groups:continue
            for group in groups:
                row=context.row(category,batch,group)
                positions={}
                for unit in row['units']:
                    key=(batch,row['group'],unit['id']);states=owners.get(key,[])
                    active=next((t for t in reversed(states) if t['status'] in lib.ACTIVE),None)
                    latest=active or next((t for t in reversed(states) if t['status']!='cancelled'),None)
                    attempted=any(t.get('attempts',{}).get(t['_queue_unit'],0)>0 for t in states)
                    source=None
                    candidates=list(revision_units(category,batch,row['group'],unit,related,context))
                    if data.get('replacements',{}).get(f'{row["group"]}:{unit["delivery_position"]}'):candidates=candidates[:1]
                    for sb,sg,su in candidates:
                        if not can_read(category,sb):continue
                        raw=context.raw(category,sb,sg,su)
                        if raw_evidence_valid(raw,su):
                            try:
                                receipt_path=lib.io_path(raw.with_suffix('.receipt.json'))
                                if receipt_path.stat().st_size>1024*1024:continue
                                receipt=lib.read(receipt_path)
                                if not isinstance(receipt,dict):continue
                            except (OSError,ValueError,TypeError):continue
                            source={'batch':sb,'group':sg,'unit':su['id'],'path':str(raw),'sha256':receipt.get('raw_sha256')};break
                    # Determine this revision's unit ID without exposing prompts or credentials.
                    attempt_unit=latest['_queue_unit'] if latest else unit['id']
                    result=latest.get('results',{}).get(attempt_unit,{}) if latest else {}
                    control=latest;control_unit=attempt_unit
                    if latest:
                        _,latest_data=context.load(category,latest['batch'])
                        binding=latest_data.get('automatic_repair_parent')
                        if binding:
                            control=context.parent(category,binding)
                            control_unit=unit['id']
                    cancelled_control=bool(control and control.get('status')=='cancelled')
                    if cancelled_control:control=None
                    is_paused=bool(control and control_unit in context.paused(control))
                    if source:
                        status='completed';stage='raw_saved';reason=None
                        proof=raw
                        is_library=lib.io_path(proof.with_suffix('.adoption.json')).exists() or su.get('inherited_raw',{}).get('asset')
                        if is_library:source_counts['library']+=1
                        elif any(t.get('attempts',{}).get(t['_queue_unit'],0)>0 for t in states):source_counts['generated']+=1
                        if not is_library and any(t['batch']==source['batch'] and source['unit'] in t.get('retained_unit_ids',[]) for t in states):source_counts['retained']+=1
                    elif not latest:
                        status='ongoing' if attempted else 'pending';stage='blocked' if attempted else 'unsubmitted';reason='cancelled_task' if attempted else None
                    elif active:
                        reason=None
                        if result.get('status')=='request_reserved':status='ongoing';stage='requesting'
                        elif result.get('status')=='failed':status='ongoing';stage='cooldown' if result.get('error') in {'transient','retryable_rejection'} else 'recovering'
                        elif active['status']=='recovering':status='ongoing';stage='recovering'
                        else:status='ongoing' if attempted else 'pending';stage='submitted_waiting'
                    else:
                        status='ongoing';reason=blocked_reason(latest,{'id':attempt_unit});stage='paused' if latest['status']=='paused' else 'blocked' if reason else 'waiting_resume'
                    if not source and is_paused and result.get('status')!='request_reserved':status='ongoing';stage='paused';reason='user_pause'
                    if not source and cancelled_control:status='ongoing';stage='blocked';reason='cancelled_task'
                    if active and result.get('status')=='request_reserved':executor_active+=1
                    if not can_read(category,batch):status='ongoing';stage='blocked';reason='asset_root_unavailable'
                    counts[status]+=1
                    kind='triptych' if unit['kind']=='triptych_panel' else unit['kind']
                    target=context.delivery(category,batch,row['group'],unit['delivery_position'],kind) if can_read(category,batch) else None
                    if unit['delivery_position'] not in positions:positions[unit['delivery_position']]=bool(target and delivery_valid(target,unit))
                    ready=positions[unit['delivery_position']]
                    cards.append({'id':lib.digest({'category':category,'batch':batch,'group':row['group'],'unit':unit['id']}),
                        'category':category,'batch':batch,'batch_name':data.get('name') or batch,'created_at':data.get('created_at'),'group':row['group'],'unit':unit['id'],'kind':unit['kind'],
                        'position':unit['delivery_position'],'panel_index':unit.get('panel_index'),'theme':unit.get('service_role',''),
                        'column':status,'stage':stage,'reason':reason,'message':REASONS.get(reason),
                        'task':control['id'] if control else None,'task_batch':control['batch'] if control else batch,
                        'control_unit':control_unit,'attempt_task':latest['id'] if latest else None,'unit_paused':is_paused,
                        'retry_not_before':result.get('retry_not_before'),
                        'attempts':sum(t.get('attempts',{}).get(t['_queue_unit'],0) for t in states),
                        'source':source,'source_type':('library' if is_library else 'generated' if any(t.get('attempts',{}).get(t['_queue_unit'],0)>0 for t in states) else 'retained') if source else 'pending',
                        'postprocess':'ready' if ready else 'waiting_sources' if not source else 'waiting_local'})
                    if _detail is not None and unit['id']==_detail['unit']:
                        _detail.update(card=cards[-1],states=states,target=target,ready=ready)
                for ready in positions.values():delivery_counts['ready' if ready else 'waiting']+=1
    if request.get('board_overview'):
        fields=('category','batch','batch_name','created_at','group','position','panel_index','kind','theme','column')
        rows=[{key:card[key] for key in fields} for card in cards]
        revision=lib.digest(rows)
        return {'cards':[] if since==revision else rows,'counts':counts,'unchanged':since==revision,'revision':revision}
    selected=[c for c in cards if column is None or c['column']==column]
    result={'cards':[] if summary_only or pages is not None else selected[offset:offset+limit],'total':len(cards),'filtered_total':len(selected),'counts':counts,
        'offset':offset,'limit':limit,'has_more':offset+limit<len(selected),'executor_active':executor_active,
        'delivery_counts':delivery_counts,'source_counts':source_counts,'request_counts':request_counts,'active_tasks':active_tasks,'recovering_tasks':recovering_tasks,
        'warnings':warnings[:20],'updated_at':lib.now()}
    if pages is not None:
        by_column={key:[c for c in cards if c['column']==key] for key in counts}
        result['pages']=[{**p,'cards':by_column[p['column']][p['offset']:p['offset']+p['limit']],
            'has_more':p['offset']+p['limit']<len(by_column[p['column']])} for p in pages]
    # A conditional read still checks evidence and licences afresh. It cannot
    # authorise execution, and different filters/windows never share a token.
    result['revision']=lib.digest({'scope':{'categories':categories,'batch':request.get('batch'),'column':column,
        'offset':offset,'limit':limit,'summary_only':summary_only,'pages':pages},'cards':cards,
        'summary':{k:v for k,v in result.items() if k not in ('cards','pages','updated_at')}})
    result['unchanged']=since==result['revision']
    if result['unchanged']:
        result['cards']=[]
        if pages is not None:result['pages']=[]
    return result
