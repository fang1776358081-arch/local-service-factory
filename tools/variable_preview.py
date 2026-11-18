"""Three bounded previews using the same pure builders as new production manifests."""
import copy
import random
from tools import variable_catalog as vc


def phone(category):
    p=vc.read_json(vc.project_dir(category)/'project.json')
    field=p.get('required_fields',{}).get('contact_phones',{})
    values=field.get('values',[]) if field.get('confirmed') else []
    return values[0] if values else '{已确认电话}'


def real_prompt(category,group,role):
    root=vc.ROOT
    forced_dimensions=[d for d in vc.CURRENT.get()['catalog']['dimensions'] if d['id'] in vc.FORCE.get()]
    if category=='road_rescue':
        if role=='cover':
            from generate_group_prompts import cover_prompt_v3
            return cover_prompt_v3(group,vc.read_json(root/'projects/road_rescue/cover_scene_library.json'),vc.read_json(root/'projects/road_rescue/cover_visual_profile_v3.json'),[phone(category)])
        from generate_prompts import generate_records
        return generate_records(vc.read_json(root/'config.json'),vc.read_json(root/'scene_library.json'),8,seed=group)[0]
    if category=='home_appliance_repair':
        from generate_home_appliance_groups import cover_prompt,detail_prompt,DETAILS
        slug=next((d['binding']['detail'] for d in forced_dimensions if d.get('binding',{}).get('detail')),DETAILS[0]['slug'])
        return cover_prompt(group,phone(category)) if role=='cover' else detail_prompt(group,next(d for d in DETAILS if d['slug']==slug))
    if category=='computer_repair':
        from generate_computer_repair_groups import detail_prompt,DETAILS
        slug=next((d['binding']['detail'] for d in forced_dimensions if d.get('binding',{}).get('detail')),DETAILS[0]['slug'])
        detail=next(d for d in DETAILS if d['slug']==slug)
        return detail_prompt(group,detail,1)
    if category=='lock_service':
        import factory
        from tools import lock_prompt_builder as lock
        cat=vc.CURRENT.get()['catalog']
        key='LOCK_SERVICE_COVER_VARIANTS' if role=='cover' else 'LOCK_SERVICE_DETAIL_VARIANTS'
        d=next(x for x in cat['dimensions'] if x['source']==key)
        pool=vc.option_pool(d,getattr(factory,key));selected=pool[group%len(pool)]
        return lock.cover_prompt(selected,selected['services'],[phone(category)]) if role=='cover' else lock.detail_prompt(selected[1],group,1)
    if category=='pipe_unclogging':
        from tools.prompt_engine import load_category_config,build_prompt_record
        config=load_category_config(category)
        key='cover' if role=='cover' else next(k for k in config['scene_types'] if k!='cover')
        key=next((d['binding']['path'][1] for d in forced_dimensions if d.get('binding',{}).get('path',[None])[0]=='scene_types'),key)
        for d in forced_dimensions:
            path=d.get('binding',{}).get('path',[])
            setting='indoor' if d['source']=='PIPE_INDOOR_LIGHT' else 'outdoor' if d['source'] in {'PIPE_OUTDOOR_LIGHT','PIPE_WEATHER'} else path[-1] if path[:1]==['environment_details_by_setting'] else None
            if setting and bool(config['scene_types'][key].get('weather_allowed'))!=(setting=='outdoor'):
                key=next(k for k,s in config['scene_types'].items() if k!='cover' and bool(s.get('weather_allowed'))==(setting=='outdoor'))
        return build_prompt_record(config,key,group,random.Random(group),group)
    if category=='truck_rescue':
        import generate_truck_rescue_groups as truck
        from tools.truck_shared_variants import enabled,enhance_rows
        if enabled():
            rows=enhance_rows(truck._build_rows(group,1,1,vc.read_json(root/'configs/categories/truck_rescue.json'))[0],group)
            if role=='cover': return rows[0]
            key=next((d['binding']['dictkey'] for d in forced_dimensions if d.get('binding',{}).get('name')=='EVENTS'),None)
            return next(r for r in rows[1:] if key is None or r['service_role']==key)
        if role=='cover': return truck._cover_positive_prompt(truck._cover_variant(truck._cover_library(),group))
        key=next((d['binding']['dictkey'] for d in forced_dimensions if d.get('binding',{}).get('name')=='EVENTS'),next(iter(truck.ROLE_IDS)));variant=truck.truck_scene_diversity_v3.detail_variant(key,group)
        return truck._detail_positive_prompt(key,variant,group,1,'detail')
    if category=='pet_transport':
        if role=='cover':
            from tools.category_image_production import _pet_transport_cover_prompt
            return _pet_transport_cover_prompt({'group_index':group,'category_id':category},phone(category))
        from generate_pet_transport_groups import _detail_prompt
        service=next((d['binding']['dictkey'] for d in forced_dimensions if d.get('binding',{}).get('name')=='DETAIL_ACTIONS'),'接宠交接')
        return _detail_prompt(group,2,service)
    if category=='ktv':
        from tools.ktv_project import make_group
        rows,_=make_group(group,vc.read_json(root/'configs/categories/ktv.json'))
        return rows[0 if role=='cover' else -1]
    if category=='business_ktv':
        if any(d.get('binding',{}).get('module')=='tools.business_ktv.group_prompt' for d in forced_dimensions):
            from tools.business_ktv.group_prompt import select_group
            packed=select_group(group,'00000000000')
            return '\n'.join(row['prompt'] for row in packed['shots'])
        from tools.business_ktv.scene import sample,prompt,initial_strategy
        config=vc.overlay_document(category,vc.read_json(root/'configs/business_ktv/scene_library.json'))
        strategy=initial_strategy(config);scene=sample(config,strategy,group)
        return prompt(scene,config,strategy),scene
    raise ValueError('业务未接入本地预览')


def text_of(result):
    if isinstance(result,str): return result
    if isinstance(result,(tuple,list)): return '\n'.join(text_of(x) for x in result)
    return (result.get('prompt') or result.get('positive_prompt') or '') if isinstance(result,dict) else ''


def builtin_evidence(data,result):
    prompt=text_of(result)
    def contains(node,value):
        if node==value: return True
        if isinstance(node,dict):
            if isinstance(value,dict) and all(k in node and node[k]==v for k,v in value.items()): return True
            return any(contains(v,value) for v in node.values())
        if isinstance(node,(list,tuple)): return any(contains(v,value) for v in node)
        return False
    selected=[]
    def leaves(v):
        if isinstance(v,str): return [v]
        if isinstance(v,dict): return [s for k,x in v.items() if k not in {'id','weight','name','label'} for s in leaves(x)]
        if isinstance(v,list): return [s for x in v for s in leaves(x)]
        return []
    for d in data['dimensions']:
        if d['kind']!='builtin' or d.get('status')=='legacy': continue
        for o in d['options']:
            v=o['value']
            if contains(result,v) or isinstance(v,dict) and (contains(result,v.get('id','__missing__')) or contains(result,v.get('name','__missing__')) or v.get('name','')+v.get('suffix','__missing__') in prompt) or isinstance(v,str) and len(v)>=6 and v in prompt or isinstance(v,(dict,list)) and any(len(s)>=5 and s in prompt for s in leaves(v)):
                selected.append({'type_id':d['id'],'type':d['name'],'option_id':o['id'],'option':o['name']})
    return selected


def build(category,request):
    data=copy.deepcopy(request.get('catalog') or vc.load(category))
    if data['category_id']!=category: raise ValueError('预览业务不匹配')
    vc.validate(data)
    force=request.get('force',{});role=request.get('role','cover')
    if category=='business_ktv': role='detail'
    if role not in {'cover','detail'}: raise ValueError('图片类型不正确')
    for key,value in force.items():
        d=next((d for d in data['dimensions'] if d['id']==key),None)
        if not d or not any(o['id']==value and o['enabled'] for o in d['options']): raise ValueError('指定选项不存在或已停用')
        if role not in d['roles']: role=d['roles'][0]
    result=[]
    forced_token=vc.FORCE.set(force)
    try:
        for attempt in range(24 if force else 3):
            i=len(result)
            group=int(request.get('seed',374 if category=='truck_rescue' else 1401))+attempt
            ctx={'category':category,'catalog':data,'seed':str(group)}; token=vc.CURRENT.set(ctx)
            try:
                raw=real_prompt(category,group,role)
                final=vc.finish(raw,ctx,role)
                evidence=builtin_evidence(data,raw)
                _,selected,skipped=vc.custom_selection(data,str(group),role,force,evidence)
                selected=evidence+selected
                if any(not any(s['type_id']==key and s['option_id']==value for s in selected) for key,value in force.items()): continue
                result.append({'index':i+1,'role':role,'prompt':text_of(final),'selected':selected,'skipped':skipped,'revision':data['revision'],'api_called':False})
                if len(result)==3: break
            finally: vc.CURRENT.reset(token)
    finally: vc.FORCE.reset(forced_token)
    if len(result)<3:
        labels=[d['name']+' / '+next(o['name'] for o in d['options'] if o['id']==force[d['id']]) for d in data['dimensions'] if d['id'] in force]
        raise ValueError('、'.join(labels)+'：在24次本地组装内未取得三份包含此项的有效场景；当前业务路径或场景兼容规则未采用此项，配置未保存')
    return result
