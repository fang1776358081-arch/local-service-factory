"""Pure complete-group adapters for the shared local task workflow."""
import copy
import random
from tools import variable_catalog as vc
from tools.variable_preview import text_of


def build_group(category, seed, phone, catalog, config):
    token=vc.CURRENT.set({'category':category,'catalog':catalog,'seed':str(seed),'revision':catalog['revision']})
    try:
        if category=='truck_rescue':
            from tools.truck_rescue_signage import load_signage_library,NAMING_EPOCH_GROUP
            from tools.truck_scene_diversity_v3 import EPOCH_GROUP
            available=NAMING_EPOCH_GROUP+len(load_signage_library()['brand_name_candidates'])-EPOCH_GROUP
            if available<1: raise ValueError('当前货车字号池不足以适配现行场景，请由 Agent 扩展候选')
            seed=EPOCH_GROUP+(seed%available)
        rows=_rows(category,seed,phone,config)
        result=[]
        for position, source in enumerate(rows,1):
            row=copy.deepcopy(source)
            kind=row.get('generation_kind') or row.get('generation_role') or row.get('role','detail')
            if kind not in {'cover','triptych_panel','detail'}: kind='detail'
            role='cover' if kind=='cover' else 'detail'
            row['category_id']=category;row['generation_kind']=kind
            raw=text_of(row).replace('{已确认电话}',phone)
            if not raw.strip(): raise ValueError('组装结果缺少提示词')
            row['prompt']=raw
            final=vc.finish(row,vc.CURRENT.get(),role)
            prompt=text_of(final)
            # Freeze the same effective text used by existing category generation.
            if category in {'road_rescue','pipe_unclogging','pet_transport','truck_rescue','home_appliance_repair','ktv'}:
                from tools.category_image_production import effective_prompt
                prompt=effective_prompt({**row,'prompt':prompt},phone)
            template=vc.read_json(vc.ROOT/'configs/prompt_templates.json')
            fragments=template['shared'][role]+template['projects'][category][role]
            if not all(isinstance(text,str) for text in fragments):raise ValueError('模板段落必须为文字列表')
            if fragments:
                import re
                from tools.task_library import overlay_services
                values={'phone':phone,'category':category,'services':'、'.join(overlay_services(config))}
                rendered=[]
                for text in fragments:
                    if set(re.findall(r'\{([^{}]+)\}',text))-set(values):raise ValueError('模板包含不支持的变量，仅支持 phone/category/services')
                    for key,value in values.items():text=text.replace('{'+key+'}',str(value))
                    rendered.append(text)
                prompt+='\n'+'\n'.join(rendered)
            result.append({'position':position,'kind':kind,'prompt':prompt,
                'delivery_position':int(row.get('delivery_position') or row.get('position') or position),
                'panel_index':row.get('panel_index') or row.get('triptych_panel_index'), 'service_role':row.get('service_role') or row.get('title'),
                'final_size':row.get('final_size','1024x1536'),
                'height_profile_id':row.get('height_profile_id','full_1536'),
                'triptych_layout_id':row.get('triptych_layout_id'),
                'structure_version':row.get('structure_version',config.get('image_group_structure',{}).get('structure_version','library_v1')),
                'generation_mode':row.get('generation_mode','independent_delivery_images'),
                'variables':final.get('variable_catalog',{}), 'source_group':seed,
                **({'salvage_context':row['salvage_context']} if 'salvage_context' in row else {})})
        return result
    finally: vc.CURRENT.reset(token)


def _rows(category,g,phone,config):
    if category=='diving_salvage':
        from tools.task_diving_salvage import rows
        return rows(g,phone,config)
    if category=='home_appliance_repair':
        import generate_home_appliance_groups as m
        return m.build_random_pool_rows(g,phone)
    if category=='computer_repair':
        import generate_computer_repair_groups as m
        return m.build_random_pool_rows(g,phone)
    if category=='lock_service':
        import factory
        from tools import lock_prompt_builder as m
        cat=vc.CURRENT.get()['catalog'];pools={d['source']:d for d in cat['dimensions'] if d['kind']=='builtin'}
        covers=vc.option_pool(pools['LOCK_SERVICE_COVER_VARIANTS'],factory.LOCK_SERVICE_COVER_VARIANTS)
        details=vc.option_pool(pools['LOCK_SERVICE_DETAIL_VARIANTS'],factory.LOCK_SERVICE_DETAIL_VARIANTS)
        cover=covers[g%len(covers)]
        rows=[{'role':'cover','prompt':m.cover_prompt(cover,cover['services'],[phone])}]
        for i in range(8):
            role,prompt=details[(g*8+i)%len(details)]
            rows.append({'role':'detail','title':role,'prompt':m.detail_prompt(prompt,g,i+2)})
        return rows
    if category=='pet_transport':
        import generate_pet_transport_groups as m
        pool=config['image_group_structure']['service_role_pool'];start=((g-1)*3)%len(pool)
        rows=[m._record('library',g,1,'cover',None,'')]
        return rows+[m._record('library',g,i+2,'detail',pool[(start+i)%len(pool)],'') for i in range(5)]
    if category=='truck_rescue':
        import generate_truck_rescue_groups as m
        from tools.truck_shared_variants import enhance_rows
        return enhance_rows(m._build_rows(g,1,1,config)[0], int(vc.CURRENT.get()['seed']))
    if category=='ktv':
        from tools.ktv_project import make_group
        return make_group(g,config)[0]
    if category=='business_ktv':
        from tools.business_ktv.group_prompt import select_group
        packed=select_group(g, phone)
        return [{
            'role': 'cover' if shot['id']=='01_storefront' else 'detail',
            'generation_kind': 'cover' if shot['id']=='01_storefront' else 'detail',
            'service_role': shot['role'],
            'prompt': shot['prompt'],
            'structure_version': 'business_ktv_v2_seven',
            'generation_mode': 'seven_role_sequence',
        } for shot in packed['shots']]
    if category=='pipe_unclogging':
        import generate_pipe_unclogging_groups as m
        structure=m._v2_validate_config(config)
        height,layout,cycle=m._v2_height_and_layout(structure,g)
        roles=m._v2_role_assignment(structure['service_role_pool'],g)
        cover,_=m._v2_cover_record(config,g,1,height,layout,cycle,set())
        rows=[cover]
        for i,role in enumerate(roles,1):
            rows.append(m._v2_service_record(config,g,i+1,i+1,'triptych_panel' if i<=3 else 'detail',role,2 if i<=3 else i-1,height,layout,cycle))
        return rows
    if category=='road_rescue':
        import generate_road_rescue_v3_groups as m
        from generate_group_prompts import cover_prompt_v3
        from generate_prompts import generate_records
        structure=m._validate_structure(config);height,layout,cycle=m._height_and_layout(structure,g)
        prompt,scene=cover_prompt_v3(g,vc.read_json(vc.ROOT/'projects/road_rescue/cover_scene_library.json'),vc.read_json(vc.ROOT/'projects/road_rescue/cover_visual_profile_v3.json'),[phone])
        size=f"{height['width']}x{height['height']}"
        rows=[{'prompt':prompt,'scene':scene,'generation_kind':'cover','delivery_position':1,'final_size':size,'structure_version':m.V3_STRUCTURE_VERSION,'generation_mode':m.V3_GENERATION_MODE}]
        library=vc.overlay_document(category,vc.read_json(vc.ROOT/'scene_library.json'),'scene_library.json')
        roles=m._assignment(structure['service_role_pool'],g)
        for i,role in enumerate(roles,1):
            local=copy.deepcopy(library);local['rescue_jobs']=[j for j in library['rescue_jobs'] if j['name']==role]
            if not local['rescue_jobs']: raise ValueError(f'缺少已启用的救援场景：{role}')
            source=generate_records(vc.read_json(vc.ROOT/'config.json'),local,1,seed=g*100+i)[0]
            # Existing builder enforces panel framing, role semantics and height rules.
            row=m._service_record(source,g,i+1,i+1,'triptych_panel' if i<=3 else 'detail',2 if i<=3 else i-1,height,layout,cycle)
            rows.append(row)
        return rows
    raise ValueError('业务尚未接入完整组装')
