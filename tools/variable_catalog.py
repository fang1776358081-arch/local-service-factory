"""Local variable catalog. No network or image generation operations."""
from __future__ import annotations
from tools import runtime_paths
import ast
import contextvars
import copy
import functools
import hashlib
import inspect
import itertools
import json
import os
from pathlib import Path
import random
import re
import sys
import time
import types
import uuid

ROOT = Path(__file__).resolve().parent.parent
CURRENT = contextvars.ContextVar('variable_catalog_context', default=None)
FORCE = contextvars.ContextVar('variable_catalog_force', default={})
DISABLED = contextvars.ContextVar('variable_catalog_disabled', default=False)

# Explicit sources only: never scan generated manifests, images or private .env.
MODULES = {
 'road_rescue': [('tools.road_signboard_variants', None), ('tools.road_composition_variants', ['COMPOSITIONS']),
                 ('tools.road_environment_variants', ['ENVIRONMENTS','INCIDENTAL_TYPES']), ('tools.road_postprocess_variants', ['POSTPROCESS_PRESETS']),
                 ('tools.road_snapshot_variants',['FLAWS','ROLL_ANGLES'])],
 'home_appliance_repair': [('generate_home_appliance_groups', None)],
 'pet_transport': [('generate_pet_transport_groups', ['DETAIL_ACTIONS','LOCATIONS','PET_CONTEXTS','CAMERAS','LIGHTING']),('tools.category_image_production',['PET_STORE_NAMES','PET_VEHICLES','PET_ACTIONS'])],
 'truck_rescue': [('generate_truck_rescue_groups', ['CAMERAS','LIGHTING']),('tools.truck_scene_diversity_v3',['EVENTS','DETAIL_CAMERAS','LOCATIONS','LIGHTS','WORKWEAR','COVER_FRAMES','COVER_EVENTS','LEARNED_COMPOSITIONS','COVER_WORK_DETAILS']),('tools.truck_shared_variants',['CAPTURE_DEVICES','PHOTO_TREATMENTS','SNAPSHOT_FLAWS','HANDHELD_ROLL','BACKGROUND_ELEMENTS','HEAVY_VEHICLES','OTHER_VEHICLES','COVER_ENVIRONMENTS','SIGN_MATERIALS','SIGN_LAYOUTS','SIGN_WEAR'])],
 'lock_service': [('factory', ['LOCK_SERVICE_COVER_VARIANTS','LOCK_SERVICE_DETAIL_VARIANTS'])],
 'pipe_unclogging': [('tools.prompt_engine',['PIPE_CAMERAS','PIPE_INDOOR_LIGHT','PIPE_OUTDOOR_LIGHT','PIPE_WEATHER'])], 'ktv': [],
 'business_ktv': [('tools.business_ktv.group_prompt', ['STORE_NAMES','BUILDINGS','EXTERIOR_LIGHTS','TYPEFACES','SIGN_LAYOUTS','STREETS','MATERIALS','EXTRA_SERVICES','GUEST_CLOTHES','STAFF_POSTS','SINGER_LOOKS','ROOM_SIDES'])],
}
FILES = {
 'road_rescue': [('projects/road_rescue/cover_visual_profile_v3.json', ['capture_devices','light_presets','worker_presentations']),
                 ('projects/road_rescue/cover_scene_library.json', ['era_profiles']),
                 ('scene_library.json', ['times','rescue_jobs','vehicle_types','rescue_workers','camera_styles','camera_angles','compositions','location_groups','weather_groups','context_details','rescue_vehicles_by_policy'])],
 'truck_rescue': [('projects/truck_rescue/cover_scene_library.json', None)],
 'lock_service': [], 'home_appliance_repair': [], 'pet_transport': [('projects/pet_transport/cover_scene_library.json',None)],
 'pipe_unclogging': [('configs/categories/pipe_unclogging.json', ['scene_types','realism_factors','environment_details_by_setting'])],
 'ktv': [('configs/categories/ktv.json', ['random_variables','linked_randomization','camera_scenarios'])],
 'business_ktv': [('configs/business_ktv/scene_library.json', ['variables','imperfections','prompt_structures'])],
}
LABELS = {'SHOP_PREFIXES':'商号字号','OWNER_PREFIXES':'师傅称呼','SHOP_SUFFIXES':'商号业务后缀','OWNER_SUFFIXES':'称呼业务后缀',
 'legal_combinations':'合法作业组合','actions':'作业动作','problems':'客户问题','pipe_types':'管道类型','tools':'施工工具',
 'realism_factors':'写实细节','indoor':'室内环境','outdoor':'室外环境','PIPE_CAMERAS':'施工拍摄位置','PIPE_INDOOR_LIGHT':'室内光线','PIPE_OUTDOOR_LIGHT':'室外光线','PIPE_WEATHER':'室外天气',
 'PET_STORE_NAMES':'宠物门店名称','PET_VEHICLES':'宠物服务车辆','PET_ACTIONS':'门前照护动作','LOGO_SYMBOLS':'门店符号','LOGO_FRAMES':'符号外框','LOGO_ACCENTS':'符号细节',
 'FLAWS':'随手拍缺陷','ROLL_ANGLES':'握持旋转角度','INCIDENTAL_TYPES':'随机生活元素',
 'SERVICES':'招牌服务词','FABRICATIONS':'招牌材质与配色','LAYOUTS':'招牌排版','CONDITIONS':'招牌使用状态',
 'COMPOSITIONS':'构图与作业组合','ENVIRONMENTS':'门面环境','POSTPROCESS_PRESETS':'后期调色',
 'capture_devices':'拍摄设备','light_presets':'拍摄光线','worker_presentations':'人物呈现','era_profiles':'门店年代',
 'COVER_SIGN_STYLES':'招牌风格','COVER_FACADES':'门面建筑','COVER_INTERIORS':'店内环境','COVER_CAMERAS':'拍摄机位',
 'COVER_STREET_ELEMENTS':'周边生活元素','COVER_LIGHTING':'封面光线','SERVICE_LINES':'服务文案',
 'DETAIL_CAMERA_STYLES':'详情机位','DETAIL_LIGHTING':'详情光线','DETAIL_WORKER_STATES':'详情人物状态',
 'LOCATIONS':'场景位置','PET_CONTEXTS':'宠物状态','CAMERAS':'拍摄机位','LIGHTING':'光线',
 'LOCK_SERVICE_COVER_VARIANTS':'门店成套场景','LOCK_SERVICE_DETAIL_VARIANTS':'详情服务事件',
 'ROOM_TYPE':'空间类型','LAYOUT':'空间布局','SOFA':'沙发','TABLE':'桌型','ROOM_STYLE':'室内风格','LIGHTING':'光线',
 'CAMERA_POSITION':'拍摄位置','CAMERA_DISTANCE':'取景距离','COMPOSITION':'构图','TABLE_STATE':'桌面状态',
 'DRINKS':'饮品状态','FRUIT':'水果','DENSITY':'物品密度','imperfections':'自然使用痕迹','prompt_structures':'叙述方式',
 'STORE_NAME_HEADS':'店名首字','STORE_NAME_TAILS':'店名次字','LOBBY_NAMES':'大厅是否写店名','STORE_NAMES':'一组店名','VENUE_FAMILIES':'店型拍照与室内','BUILDINGS':'门头建筑','EXTERIOR_LIGHTS':'门头时间与光','TYPEFACES':'门头字体','SIGN_LAYOUTS':'门头文字排版','STREETS':'门头街道','MATERIALS':'一组装修材料','EXTRA_SERVICES':'门头附加用途','GUEST_CLOTHES':'进门客人衣着','STAFF_POSTS':'大厅服务人员','SINGER_LOOKS':'女歌手形象','ROOM_SIDES':'包厢机位',
 'brand_name_candidates':'店名字号','generic_store_titles':'通用店铺后缀','store_name_prefixes':'店名前缀',
 'store_name_suffixes':'店名后缀','sign_color_schemes':'招牌配色','business_lines':'服务行','sign_conditions':'招牌状态',
 'locations':'位置','facade_archetypes':'建筑原型','storefront_layouts':'门店布局','business_modes':'经营形态',
 'workshop_activities':'作业动作','street_activity_levels':'街道活动','foreground_elements':'前景',
 'service_vehicle_prominence':'车辆可见程度','sign_surface_styles':'招牌面板','sign_shapes':'招牌形状',
 'sign_information_layouts':'招牌信息层级','sign_accent_details':'招牌强调细节','sign_installation_details':'安装细节',
 'truck_vehicle_types':'货车类型','vehicle_layouts':'车辆位置','camera_compositions':'取景构图','shop_states':'营业状态',
 'weather_atmospheres':'天气','support_vehicles':'辅助车辆','workers':'人员','tools_and_equipment':'工具设备',
 'street_details':'街边细节','lighting':'环境光','camera_styles':'拍摄风格'}

def read_json(path):
    return runtime_paths.read_json(path)

def projects():
    return [p for p in read_json(ROOT/'projects/registry.json')['projects'] if p['id'] not in runtime_paths.hidden_projects()]

def project_dir(category):
    if category not in {p['id'] for p in projects()}:
        raise ValueError('未知业务类型')
    return ROOT/'projects'/category

def plain(value):
    return json.loads(json.dumps(value, ensure_ascii=False))

def uid(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:14]

def schema(value):
    if isinstance(value, dict): return {'type':'object','fields':{k:schema(v) for k,v in value.items()}}
    if isinstance(value, (list,tuple)):
        if len({type(x).__name__ for x in value})>1: return {'type':'array','positions':[schema(x) for x in value]}
        return {'type':'array','item':schema(value[0]) if value else {'type':'string'},'allow_empty':not value}
    if isinstance(value,bool): return {'type':'boolean'}
    if isinstance(value,(int,float)): return {'type':'number'}
    return {'type':'string','allow_empty':value==''}

def valid_shape(value, spec):
    kind = spec['type']
    if kind == 'object':
        return isinstance(value,dict) and set(value)==set(spec['fields']) and all(valid_shape(value[k],v) for k,v in spec['fields'].items())
    if kind == 'array':
        if 'positions' in spec: return isinstance(value,list) and len(value)==len(spec['positions']) and all(valid_shape(v,s) for v,s in zip(value,spec['positions']))
        return isinstance(value,list) and (bool(value) or spec.get('allow_empty')) and all(valid_shape(v,spec['item']) for v in value)
    if kind == 'number': return isinstance(value,(int,float)) and not isinstance(value,bool) and abs(value)<1e6
    if kind == 'boolean': return isinstance(value,bool)
    return isinstance(value,str) and (bool(value.strip()) or spec.get('allow_empty')) and len(value)<=12000

class LiteralDict(ast.NodeTransformer):
    def visit_Call(self,node):
        if isinstance(node.func,ast.Name) and node.func.id=='dict' and not node.args and all(k.arg for k in node.keywords):
            return ast.Dict(keys=[ast.Constant(k.arg) for k in node.keywords],values=[self.visit(k.value) for k in node.keywords])
        return node

def option_name(v, index):
    if isinstance(v,str): return v[:70] or '无额外变化'
    if isinstance(v,dict): return str(v.get('name') or v.get('label') or v.get('description') or v.get('facade') or v.get('id') or f'方案 {index+1}')[:70]
    return ' / '.join(str(x) for x in v)[:70] if isinstance(v,list) else str(v)

def dimension(key, values, binding, roles=None, fixed=False):
    shapes=[{'type':'array','positions':[schema(x) for x in v]} if isinstance(v,tuple) else schema(v) for v in values]
    values = plain(values)
    short=key.split(':')[-1].split('.')[-1]
    return {'id':uid(key),'name':LABELS.get(short, short), 'source':key,
            'description':'已有生成器候选池；保存后用于新组装', 'kind':'builtin','binding':binding,
            'roles':roles or ['cover','detail'], 'probability':1.0,'min_select':1,'max_select':1,
            'fixed_shape':fixed,'schema':shapes[0],
            'options':[{'id':f'o_{i}_{uid(v)}','name':option_name(v,i)+(f' · {i+1}' if sum(option_name(x,0)==option_name(v,0) for x in values)>1 else ''),'value':v,'schema':shapes[i],'weight':1.0,'enabled':True,'conditions':[]} for i,v in enumerate(values)]}

def defaults(category):
    project_dir(category)
    dimensions=[]; readonly=[]
    for module, only in MODULES.get(category,[]):
        path=ROOT/(module.replace('.','/')+'.py')
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in tree.body:
            if not isinstance(node,(ast.Assign,ast.AnnAssign)): continue
            try:
                name=node.targets[0].id if isinstance(node,ast.Assign) else node.target.id
                value=ast.literal_eval(LiteralDict().visit(node.value))
            except (ValueError,TypeError,AttributeError): continue
            if only is not None and name not in only: continue
            if name in {'EVENTS','COVER_WORK_DETAILS','DETAIL_ACTIONS'} and isinstance(value,dict):
                for role,pool in value.items():
                    scalar=name=='COVER_WORK_DETAILS'
                    d=dimension(name+'.'+role,[pool] if isinstance(pool,str) else pool,{'module':module,'name':name,'dictkey':role,'scalar':scalar},['cover'] if scalar else ['detail'],scalar)
                    d['name']=role+(' · 工位摆放' if scalar else ' · 作业动作' if name=='DETAIL_ACTIONS' else ' · 车辆动作工具组合');dimensions.append(d)
                continue
            if not isinstance(value,(list,tuple)) or not value: continue
            if name in {'DETAILS'}:
                for detail in value:
                    for field in ('actions','settings','props'):
                        d=dimension('DETAILS.'+detail['slug']+'.'+field,detail[field],{'module':module,'name':'DETAILS','detail':detail['slug'],'field':field},['detail'])
                        d['name']=detail['title']+' · '+{'actions':'作业动作','settings':'环境','props':'工具物品'}[field]
                        dimensions.append(d)
                continue
            dimensions.append(dimension(name,value,{'module':module,'name':name,'tuple':isinstance(value,tuple)},
                              ['detail'] if name.startswith('DETAIL_') or name=='LOCK_SERVICE_DETAIL_VARIANTS' else ['cover'] if name.startswith('COVER_') or (module=='tools.truck_shared_variants' and name.startswith('SIGN_')) or category=='road_rescue' or name=='LOCK_SERVICE_COVER_VARIANTS' else None))
    for path, allowed in FILES.get(category,[]):
        document=read_json(ROOT/path)
        def walk(v, keys):
            if isinstance(v,list) and v and all(isinstance(x,(str,dict,list)) for x in v):
                if any(w in keys[-1] for w in ('rules','negative')): return
                if keys[-1] in {'source_image_common_traits','source_images','reference_images','required_signboard_text','approved_traits'}:
                    readonly.append({'name':'.'.join(keys),'value':v,'reason':'已确认参考与固定要求，不参与随机'})
                    return
                if not all(valid_shape(plain(x),schema(v[0])) for x in v):
                    readonly.append({'name':'.'.join(keys),'value':v,'reason':'异构关联表，需保留现有结构'})
                    return
                fixed=category=='truck_rescue' and keys[-1] in {'business_modes','workshop_activities','vehicle_layouts','service_vehicle_prominence','sign_shapes'}
                roles=['detail'] if path=='scene_library.json' else ['cover'] if 'cover_' in path else None
                if category=='pipe_unclogging' and keys[0]=='scene_types': roles=['cover'] if keys[1]=='cover' else ['detail']
                dimensions.append(dimension(path+':'+'.'.join(keys),v,{'file':path,'path':keys},roles,fixed=fixed))
            elif isinstance(v,dict):
                for k,x in v.items(): walk(x,keys+[k])
        for k,v in document.items():
            if allowed is None or k in allowed: walk(v,[k])
    # Expose non-random required inputs separately; never turn contact values into candidates.
    definition=read_json(project_dir(category)/'project.json')
    readonly.append({'name':'已确认输入','value':definition.get('required_fields',{}),'reason':'电话等固定输入不参与随机；沿用确认流程'})
    config=ROOT/'configs/categories'/f'{category}.json'
    if config.exists():
        d=read_json(config)
        for key in ('service_items','negative_prompt','physical_rules'):
            if key in d: readonly.append({'name':{'service_items':'本地服务文字','negative_prompt':'排除规则','physical_rules':'物理约束'}[key],'value':d[key],'reason':'固定文案或质量约束'})
    enrich_catalog(category,dimensions,readonly)
    if category=='road_rescue':
        style_path=definition.get('prompt_sources',{}).get('visual_style','configs/visual_styles/realistic_mobile_documentary_v2.json')
        style=read_json(ROOT/style_path)
        for section,values in style.get('lens_presets',{}).items():
            dimensions.append(dimension('lens_presets.'+section,values,{'file':style_path,'path':['lens_presets',section]},['detail']))
        readonly.append({'name':'通用固定质量要求','value':{k:v for k,v in style.items() if k!='lens_presets'},'reason':'固定规则始终执行，不进入随机池'})
    counts={}
    for d in dimensions: counts[d['name']]=counts.get(d['name'],0)+1
    for d in dimensions:
        if counts[d['name']]>1:
            keys=d.get('binding',{}).get('path',[])
            d['name'] = (keys[1]+' · '+d['name']) if len(keys)>1 and keys[0]=='scene_types' else d['name']+' · '+d['source']
    if category=='business_ktv':
        for d in dimensions: d['roles']=['detail']
    return {'schema_version':1,'category_id':category,'revision':0,'supported_roles':['detail'] if category=='business_ktv' else ['cover','detail'],'dimensions':dimensions,'readonly':readonly}


def enrich_catalog(category, dimensions, readonly):
    """Expose associated fields as one editable option, never split causal maps."""
    for d in list(dimensions):
        b=d.get('binding',{}); keys=b.get('path',[])
        if category=='pet_transport' and b.get('module')=='generate_pet_transport_groups': d['roles']=['detail']
        if category=='pet_transport' and b.get('module')=='tools.category_image_production': d['roles']=['cover']
        if category=='home_appliance_repair' and d['source'].startswith('LOGO_'): d['roles']=['cover']
        if category=='home_appliance_repair' and d['source'] in {
            'V3_HEIGHTS', 'V3_LAYOUTS', 'STORE_NAME_PREFIXES',
            'STORE_NAME_SUFFIXES', 'V3_EXTRA_DETAILS',
        }:
            # These are fixed v3 delivery/signage controls. Existing editable
            # cover and detail pools remain the public prompt variables.
            dimensions.remove(d);continue
        if category=='pipe_unclogging' and (d['source']=='PIPE_INDOOR_LIGHT' or keys==['environment_details_by_setting','indoor']): d['roles']=['detail']
        if category=='pipe_unclogging' and keys[:1]==['scene_types'] and keys[-1]!='legal_combinations':
            d['status']='legacy';d['description']='旧批次独立素材池；当前在该服务的合法作业组合中一起编辑地点、问题、管道、工具和动作'
        if category=='pet_transport' and b.get('file')=='projects/pet_transport/cover_scene_library.json' and keys!=['signboard_variants']:
            d['status']='legacy';d['description']='历史场景或参考登记信息；当前门店生成不从此字段随机取值'
        if category=='truck_rescue' and b.get('name')=='COVER_WORK_DETAILS':
            dimensions.remove(d);continue
        if category=='truck_rescue' and b.get('module')=='tools.truck_scene_diversity_v3' and b.get('name')=='LOCATIONS':
            d['roles']=['detail']
        if category=='truck_rescue' and b.get('name')=='COVER_EVENTS':
            source=ast.parse((ROOT/'tools/truck_scene_diversity_v3.py').read_text(encoding='utf-8'))
            details=ast.literal_eval(next(n.value for n in source.body if isinstance(n,ast.Assign) and n.targets[0].id=='COVER_WORK_DETAILS'))
            b['event_details']=True
            for o in d['options']:
                event,action,state=o['value'];o['value']={'id':event,'action':action,'state':state,'placement':details[event]};o['schema']=schema(o['value'])
            d['schema']=d['options'][0]['schema']
        if category=='truck_rescue' and b.get('file') and keys[-1] not in {'brand_name_candidates','sign_information_layouts','sign_accent_details','sign_installation_details'}:
            d['status']='legacy';d['description']='旧批次使用或历史备用池；当前采用成套事件、机位与光线'
        if category=='truck_rescue' and b.get('module')=='generate_truck_rescue_groups':
            d['status']='legacy';d['description']='旧批次使用；当前详情采用场景组合模块'
        if category=='ktv' and keys[:2]==['linked_randomization','lighting_by_style']:
            dimensions.remove(d);continue
        mappings=[]
        if category=='ktv' and keys==['random_variables','包厢风格']:
            mappings=[('lighting',['linked_randomization','lighting_by_style']),('description',['style_prompts'])]
        elif category=='ktv' and keys==['random_variables','拍摄位置']:
            mappings=[('description',['camera_scenarios'])]
        elif category=='business_ktv' and keys[:1]==['variables']:
            mapping={'ROOM_STYLE':('materials','materials_by_style'),'LIGHTING':('description','lighting_by_choice'),
                     'LAYOUT':('description','layout_relations'),'SOFA':('description','sofa_details'),'TABLE':('description','table_details')}.get(keys[-1])
            if mapping: mappings=[(mapping[0],['realism_profile',mapping[1]])]
        elif category=='road_rescue' and keys==['rescue_jobs']:
            mappings=[('compatibility',['job_rules'])]
        if mappings:
            document=read_json(ROOT/b['file']); b['associated_maps']=plain(mappings)
            for o in d['options']:
                value=o['value']; name=value['name'] if isinstance(value,dict) else value
                bundle=copy.deepcopy(value) if isinstance(value,dict) else {'name':name}
                for field,path in mappings:
                    ptr=document
                    for key in path: ptr=ptr.get(key,{})
                    bundle[field]=copy.deepcopy(ptr.get(name,''))
                o['value']=bundle; o['schema']=schema(bundle)
            d['schema']=schema(d['options'][0]['value'])
        if category=='ktv' and keys in (['random_variables','水果'],['random_variables','拍摄位置']): d['minimum_pool']=5
        if category=='truck_rescue' and keys==['brand_name_candidates']:
            d['minimum_pool']=50;d['weight_locked']=True
            d['description']='按组号顺序分配不重复字号；可新增，至少保留50项；顺序分配不支持频率权重'
        if category=='business_ktv' and keys==['imperfections']: d['minimum_pool']=4
        if category=='road_rescue' and keys==['rescue_jobs']:
            d['fixed_shape']=True;d['description']='固定服务类别及兼容关系，可编辑动作和工具；不新增或删除已登记服务角色'
        if d['source']=='SERVICES': d['minimum_pool']=6
        if category=='business_ktv' and keys==['prompt_structures']:
            d['status']='legacy'; d['description']='旧批次使用；当前写实叙述路径不采用此池'
        if category=='ktv' and keys in (['random_variables','灯光'],['random_variables','酒水状态'],['random_variables','桌面状态']):
            d['status']='legacy'; d['description']='旧批次使用；当前使用关联灯光或事件组合'
        d.setdefault('status','active')
    # Pet covers share an original source file, but edits are isolated in the pet catalog.
    if category=='pet_transport':
        doc=read_json(ROOT/'projects/road_rescue/cover_scene_library.json')
        for key in ('era_profiles','facade_archetypes','storefront_layouts','sign_shapes','sign_conditions','sign_installation_details','camera_compositions','camera_styles','shop_states','weather_atmospheres','lighting','street_activity_levels','foreground_elements'):
            dimensions.append(dimension('pet_cover.'+key,doc[key],{'file':'projects/road_rescue/cover_scene_library.json','path':[key]},['cover']))
    if category=='road_rescue':
        doc=read_json(ROOT/'projects/road_rescue/cover_scene_library.json')
        readonly.append({'name':'旧批次使用 · 早期门店候选池','value':{k:v for k,v in doc.items() if k!='era_profiles'},'reason':'当前封面已由招牌、环境、构图等独立变量替代；保留历史来源'})
    if category=='business_ktv':
        doc=read_json(ROOT/'configs/business_ktv/scene_library.json')
        for key in ('screen_states',):
            values=doc.get('realism_profile',{}).get(key)
            if values: dimensions.append(dimension('realism_profile.'+key,values,{'file':'configs/business_ktv/scene_library.json','path':['realism_profile',key]}))
        readonly.append({'name':'商务KTV固定场景兼容与质量要求','value':doc.get('realism_profile',{}),'reason':'事件、公共区域、几何和光源兼容规则始终执行；候选关联字段在对应类型编辑'})

def load(category):
    path=project_dir(category)/'variable_catalog.json'
    return read_json(path) if path.exists() else defaults(category)


def initialize(category):
    if os.environ.get('FACTORY_DATA_HOME'):raise ValueError('使用端变量由发布规则维护，请在维护端 Agent 修改')
    directory=project_dir(category);path=directory/'variable_catalog.json'
    if path.exists(): return read_json(path)
    lock=directory/'variable_catalog.lock'
    try: fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError: raise ValueError('目录正在初始化，请稍后重新加载')
    try:
        if path.exists(): return read_json(path)
        data=validate(defaults(category))
        atomic(directory/'variable_history'/'000000.json',data);atomic(path,data)
        return data
    finally: os.close(fd);lock.unlink()


def version(category,revision):
    data=load(category)
    return data if data['revision']==revision else read_json(project_dir(category)/'variable_history'/f'{int(revision):06d}.json')

def validate(data, base=None):
    category=data.get('category_id'); default=base or defaults(category)
    dims=data.get('dimensions',[])
    if not isinstance(dims,list) or len(dims)>180: raise ValueError('变量类型数量或格式不正确')
    ids={}; names=set(); originals={d['id']:d for d in default['dimensions']}
    for d in dims:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',d.get('id','')) or d['id'] in ids: raise ValueError('类型标识重复或不正确')
        if not str(d.get('name','')).strip() or d['name'] in names: raise ValueError('变量类型名称不能为空或重复')
        ids[d['id']]=d; names.add(d['name'])
        if not d.get('roles') or not set(d['roles'])<= {'cover','detail'}: raise ValueError('请选择封面或详情')
        if not 0<=d.get('probability',1)<=1: raise ValueError('出现频率必须为0到100%')
        if category=='business_ktv' and d.get('probability',1)==0: raise ValueError('商务KTV不能把出现概率设为零，请保留正权重')
        if not 1<=d.get('min_select',1)<=d.get('max_select',1)<=10: raise ValueError('选取数量必须为1到10')
        if d.get('kind')=='builtin':
            orig=originals.get(d['id'])
            if not orig or any(d.get(k)!=orig.get(k) for k in ('binding','schema','fixed_shape','source','minimum_pool','status','roles','weight_locked')): raise ValueError('内置变量关联和适用范围不可改写')
            if d.get('probability',1)!=1 or d.get('min_select',1)!=1 or d.get('max_select',1)!=1: raise ValueError('内置变量沿用原生成器的选取数量，出现频率请调整选项权重')
        elif d.get('kind')!='custom' or d.get('binding'): raise ValueError('自定义类型格式不正确')
        if category=='business_ktv' and d['roles']!=['detail']: raise ValueError('商务KTV生成现场素材，请选择用于详情')
        if d.get('status')=='legacy' and d['options']!=originals[d['id']]['options']: raise ValueError('旧批次变量仅供查阅，不能作为当前编辑项')
        opts=d.get('options',[]); opt_ids=set(); opt_names=set()
        if not opts or len(opts)>2000: raise ValueError('至少保留一个候选项')
        for o in opts:
            if o.get('id') in opt_ids or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',o.get('id','')): raise ValueError('选项标识重复或不正确')
            if not o.get('name','').strip() or o['name'] in opt_names: raise ValueError('选项名称不能为空或重复')
            opt_ids.add(o['id']); opt_names.add(o['name'])
            if not isinstance(o.get('weight'),(int,float)) or not .1<=o['weight']<=5: raise ValueError('选项权重必须为0.1到5')
            if d.get('weight_locked') and o['weight']!=1: raise ValueError(f"{d['name']}：按组号顺序分配，不支持频率权重")
            if category=='business_ktv' and not o.get('enabled'): raise ValueError('商务KTV不能永久排除变量，请使用降低权重')
            original_option=next((x for x in originals.get(d['id'],{}).get('options',[]) if x['id']==o['id']),None)
            shape=original_option['schema'] if original_option else d.get('schema',{'type':'string'})
            if not valid_shape(o.get('value'),shape): raise ValueError(f"{d['name']}：候选内容缺少字段或类型错误")
            if isinstance(o.get('value'),dict) and 'bays' in o['value'] and o['value']['bays'] not in (1,2,3): raise ValueError('门面开间数必须为1、2或3')
            if original_option and d.get('binding',{}).get('path')==['rescue_jobs'] and o['value']['name']!=original_option['value']['name']: raise ValueError('服务角色名称与既有组结构关联，不能改名')
            if re.search(r'(?<!\d)1[3-9](?:[ -]?\d){9}(?!\d)',json.dumps(o.get('value'),ensure_ascii=False)):
                raise ValueError('电话号码属于固定确认输入，不能写入随机候选内容')
            if d.get('kind')=='builtin' and o.get('conditions'): raise ValueError('内置候选的搭配使用原场景约束；新增跨类型条件请建自定义类型')
        active=sum(bool(o.get('enabled')) for o in opts)
        if active<d.get('max_select',1): raise ValueError('可用候选项少于选取数量')
        if active<d.get('minimum_pool',1): raise ValueError(f"{d['name']}：原抽样策略至少需要{d['minimum_pool']}个启用选项")
        value_ids=[o['value'].get('id',o['value'].get('name')) for o in opts if isinstance(o['value'],dict)]
        value_ids=[x for x in value_ids if x is not None]
        if len(value_ids)!=len(set(value_ids)): raise ValueError(f"{d['name']}：成套选项的内部名称或标识重复")
        if d.get('fixed_shape'):
            orig=originals[d['id']]
            if [o['id'] for o in opts]!=[o['id'] for o in orig['options']] or any(not o['enabled'] or o['weight']!=1 for o in opts): raise ValueError('此类型含固定位置关联，可编辑内容但不能更改数量、顺序或权重')
    if not set(originals)<=set(ids): raise ValueError('不能删除内置类型，可恢复默认或停用候选项')
    edges={d['id']:set() for d in dims}
    for d in dims:
        for o in d['options']:
            for c in o.get('conditions',[]):
                target=ids.get(c.get('dimension'))
                if not target or target['id']==d['id'] or c.get('option') not in {x['id'] for x in target['options'] if x['enabled']}: raise ValueError('搭配条件引用不存在、已停用或当前类型的选项')
                if target.get('status')=='legacy': raise ValueError('不能依赖旧批次变量')
                if not set(d['roles'])&set(target['roles']) or target.get('probability',1)==0: raise ValueError('搭配条件的适用图片类型或出现概率无法满足')
                edges[d['id']].add(target['id'])
    seen=set(); visiting=set()
    def visit(k):
        if k in visiting: raise ValueError('搭配条件存在循环')
        if k in seen: return
        visiting.add(k)
        for x in edges[k]: visit(x)
        visiting.remove(k); seen.add(k)
    for k in edges: visit(k)
    # Contradictory AND conditions on a single-choice dimension are unsatisfiable.
    for d in dims:
        for o in d['options']:
            needed={}
            def collect(option):
                for c in option.get('conditions',[]):
                    needed.setdefault(c['dimension'],set()).add(c['option'])
                    collect(next(x for x in ids[c['dimension']]['options'] if x['id']==c['option']))
            collect(o)
            if any(len(v)>ids[k].get('max_select',1) for k,v in needed.items()): raise ValueError('搭配条件无法同时满足')
        if d['kind']=='custom' and d.get('probability',1)==1 and sum(o['enabled'] and not o.get('conditions') for o in d['options'])<d.get('max_select',1):
            raise ValueError(f"{d['name']}：必选类型须保留足够的无条件候选项，避免某些组合没有可选项；也可设为可选出现")
    return data

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temp,path)
    finally:
        if temp.exists(): temp.unlink()

def save(category,data,expected):
    if os.environ.get('FACTORY_DATA_HOME'):raise ValueError('使用端变量由发布规则维护，请在维护端 Agent 修改')
    directory=project_dir(category); lock=directory/'variable_catalog.lock'
    try: fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError: raise ValueError('另一个窗口正在保存，请稍后重试')
    try:
        old=load(category)
        if old['revision']!=expected: raise ValueError('配置已被其他窗口修改，请重新加载后合并')
        if data.get('category_id')!=category: raise ValueError('不能跨业务保存变量')
        validate(data)
        # Exercise both real rendering paths before replacing the saved catalog.
        # Pure local prompt assembly only; existing manifests and APIs are untouched.
        for role in ('cover','detail'):
            try: preview(category,{'catalog':data,'role':role})
            except Exception as error: raise ValueError(f'{role}场景适配失败：{error}') from error
        previous={d['id']:d for d in old['dimensions']}
        for d in data['dimensions']:
            if d['kind']!='builtin' or d.get('fixed_shape') or d.get('status')=='legacy': continue
            prior={o['id']:o for o in previous.get(d['id'],{}).get('options',[])}
            for option in d['options']:
                if not option['enabled'] or option.get('value')==prior.get(option['id'],{}).get('value'): continue
                try: preview(category,{'catalog':data,'role':d['roles'][0],'force':{d['id']:option['id']}})
                except Exception as error: raise ValueError(f"{d['name']} / {option['name']} 无法接入：{error}") from error
        data=copy.deepcopy(data); data['readonly']=defaults(category)['readonly']
        data['revision']=old['revision']+1
        history=directory/'variable_history'
        atomic(history/f"{old['revision']:06d}.json",old)
        atomic(directory/'variable_catalog.json',data)
        return data
    finally:
        os.close(fd); lock.unlink()

def history(category):
    directory=project_dir(category)/'variable_history'
    return sorted([int(p.stem) for p in directory.glob('*.json')],reverse=True) if directory.exists() else []

def option_pool(d, original):
    if DISABLED.get() or d.get('status')=='legacy': return original
    enabled=[o for o in d['options'] if o['enabled']]
    forced=FORCE.get().get(d['id'])
    if forced:
        if d.get('fixed_shape'): raise ValueError('此变量有固定位置关联，请使用普通抽样预览')
        requested=[o for o in enabled if o['id']==forced]
        if not requested: raise ValueError('指定候选项不存在或已停用')
        minimum=d.get('minimum_pool',1)
        enabled=enabled if d.get('weight_locked') else requested+[o for o in enabled if o['id']!=forced][:minimum-1]
    vals=[]
    for o in enabled:
        vals.extend([copy.deepcopy(o['value'])] * (1 if all(x['weight']==1 for x in enabled) else max(1,round(o['weight']*10))))
    if isinstance(original,tuple): return tuple(tuple(v) if isinstance(v,list) else v for v in vals)
    return vals


def sample_unique(rng,values,count):
    unique=[];weights=[]
    for value in values:
        if value in unique: weights[unique.index(value)]+=1
        else: unique.append(value);weights.append(1)
    if len(unique)<count: raise ValueError(f'组合需要{count}个不同候选项，当前只有{len(unique)}个')
    if all(w==1 for w in weights): return rng.sample(values,count)
    result=[]
    for _ in range(count):
        index=rng.choices(range(len(unique)),weights)[0];result.append(unique.pop(index));weights.pop(index)
    return result

def overlay_document(category, value, source=None):
    if DISABLED.get(): return value
    ctx=CURRENT.get(); data=ctx['catalog'] if ctx and ctx['category']==category else load(category)
    value=copy.deepcopy(value)
    if ctx and ctx['category']==category:
        if 'originals' not in ctx: ctx['originals']={d['id']:d for d in defaults(category)['dimensions']}
        originals=ctx['originals']
    else: originals={d['id']:d for d in defaults(category)['dimensions']}
    for d in data['dimensions']:
        b=d.get('binding',{})
        if not b.get('file') or source and b['file']!=source: continue
        # Existing callers sometimes pass a narrower compatible subset. Default
        # catalogs preserve that subset; explicit catalog edits replace the source.
        if d['id'] not in FORCE.get() and d['options']==originals.get(d['id'],{}).get('options'): continue
        ptr=value
        try:
            for key in b['path'][:-1]: ptr=ptr[key]
            key=b['path'][-1]
            if key in ptr and isinstance(ptr[key],list):
                values=option_pool(d,ptr[key])
                maps=b.get('associated_maps',[])
                if maps:
                    for option in values:
                        for field,path in maps:
                            target=value
                            for part in path: target=target.setdefault(part,{})
                            target[option['name']]=copy.deepcopy(option[field])
                    values=[{k:v for k,v in option.items() if k not in {m[0] for m in maps}} if key=='rescue_jobs' else option['name'] for option in values]
                ptr[key]=values
        except (KeyError,TypeError): continue
    return value

def custom_selection(data, seed, role, forced=None, evidence=()):
    rng=random.Random(f"catalog:{data['category_id']}:{seed}"); chosen={}; rejected=[]; remaining=list(data['dimensions'])
    force=forced or {}
    while remaining:
        advanced=False
        for d in list(remaining):
            if d['kind']=='builtin':
                chosen[d['id']]=[s['option_id'] for s in evidence if s['type_id']==d['id']]
                remaining.remove(d); advanced=True; continue
            deps={c['dimension'] for o in d['options'] for c in o.get('conditions',[])}
            if any(x in {r['id'] for r in remaining} for x in deps): continue
            remaining.remove(d); advanced=True
            if role not in d['roles']: chosen[d['id']]=[]; continue
            available=[]
            for o in d['options']:
                valid=o['enabled'] and all(c['option'] in chosen.get(c['dimension'],[]) for c in o.get('conditions',[]))
                if valid: available.append(o)
                elif d['kind']=='custom': rejected.append({'type':d['name'],'option':o['name'],'reason':'停用或搭配条件未满足'})
            if d['id'] in force:
                available=[o for o in available if o['id']==force[d['id']]]
                if not available: raise ValueError('指定选项不适用当前图片或搭配条件')
            if not available:
                rejected.append({'type':d['name'],'reason':'没有满足搭配条件的候选，本次未出现'})
                chosen[d['id']]=[]; continue
            if d['id'] not in force and rng.random()>d.get('probability',1): chosen[d['id']]=[]; continue
            count=1 if d['id'] in force else rng.randint(d.get('min_select',1),d.get('max_select',1))
            if len(available)<count: raise ValueError('满足条件的候选项数量不足')
            picked=[]
            for _ in range(count):
                opt=rng.choices(available,[o['weight'] for o in available])[0]; available.remove(opt); picked.append(opt['id'])
            chosen[d['id']]=picked
        if not advanced: raise ValueError('条件依赖无法解析')
    selected=[]; lines=[]
    for d in data['dimensions']:
        if d['kind']!='custom': continue
        for o in d['options']:
            if o['id'] in chosen.get(d['id'],[]):
                selected.append({'type_id':d['id'],'type':d['name'],'option_id':o['id'],'option':o['name']})
                lines.append(f"{d['name']}：{o['value']}")
    return lines,selected,rejected

def finish(result,ctx,role):
    if isinstance(result,dict) and result.get('variable_catalog'): return result
    if isinstance(result,tuple) and len(result)==2 and isinstance(result[1],dict) and result[1].get('variable_catalog'): return result
    from tools.variable_preview import builtin_evidence
    data=ctx['catalog']; evidence=builtin_evidence(data,result)
    lines,selected,rejected=custom_selection(data,ctx['seed'],role,FORCE.get(),evidence)
    suffix=('\n本业务自定义变量（不得覆盖已确认电话和固定质量规则）：\n'+'\n'.join(lines)) if lines else ''
    meta={'category_id':ctx['category'],'revision':data['revision'],'selected':evidence+selected,'custom_selected':selected,'skipped':rejected}
    if isinstance(result,str): return result+suffix
    if isinstance(result,tuple) and len(result)==2 and isinstance(result[0],str) and isinstance(result[1],dict):
        scene=copy.deepcopy(result[1]); scene['variable_catalog']=meta; return result[0]+suffix,scene
    if isinstance(result,tuple): return tuple(finish(x,ctx,role) for x in result)
    if isinstance(result,dict):
        result=copy.deepcopy(result)
        prompt_key='prompt' if 'prompt' in result else 'positive_prompt'
        if isinstance(result.get(prompt_key),str):
            result[prompt_key]+=suffix; result['variable_catalog']=meta
            if prompt_key=='prompt' and isinstance(result.get('positive_prompt'),str): result['positive_prompt']+=suffix
            if 'prompt_sha256' in result: result['prompt_sha256']=hashlib.sha256(result['prompt'].encode()).hexdigest()
            if isinstance(result.get('scene'),dict) and 'scene_signature' not in result: result['scene']['variable_catalog']=meta
        return result
    if isinstance(result,list): return [finish(r,ctx,'cover' if r.get('generation_kind')=='cover' else 'detail') if isinstance(r,dict) else r for r in result]
    return result

def document_loader(fn):
    @functools.wraps(fn)
    def wrapper(path,*args,**kwargs):
        value=fn(path,*args,**kwargs); ctx=CURRENT.get()
        if not ctx or not isinstance(value,dict): return value
        try: relative=Path(path).resolve().relative_to(ROOT).as_posix()
        except ValueError: return value
        return overlay_document(ctx['category'],value,relative)
    return wrapper

def managed(category, role='cover', documents=(), finish_result=True):
    """Clone a module namespace per call; no global mutation or concurrency leakage."""
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args,**kwargs):
            if DISABLED.get(): return fn(*args,**kwargs)
            bound=inspect.signature(fn).bind(*args,**kwargs); bound.apply_defaults()
            config=bound.arguments.get('config',{})
            if isinstance(config,dict) and config.get('_catalog_legacy'):
                legacy=DISABLED.set(True)
                try: return fn(*args,**kwargs)
                finally: DISABLED.reset(legacy)
            cat=category
            if cat=='$config': cat=bound.arguments['config']['category_id']
            if cat=='$project': cat=bound.arguments.get('project_id','road_rescue')
            historical_group=bound.arguments.get('start_group',bound.arguments.get('group_index'))
            if cat=='truck_rescue' and historical_group is not None and int(historical_group)<274:
                historical=DISABLED.set(True)
                try: return fn(*args,**kwargs)
                finally: DISABLED.reset(historical)
            actual_role=('cover' if bound.arguments.get('generation_kind',bound.arguments.get('role'))=='cover' else 'detail') if role=='$role' else role
            ctx=CURRENT.get(); own=not ctx or ctx['category']!=cat
            if own:
                data=config.get('variable_catalog_snapshot') or load(cat)
                prior=bound.arguments.get('scene',{}).get('variable_catalog_revision')
                if prior is not None and not config.get('variable_catalog_snapshot'): data=version(cat,prior)
                seed=bound.arguments.get('group_index',bound.arguments.get('seed',bound.arguments.get('index',bound.arguments.get('scene',{}).get('seed',bound.arguments.get('record',{}).get('group_index',1)))))
                ctx={'category':cat,'catalog':data,'seed':str(seed),'revision':data['revision']}
                token=CURRENT.set(ctx)
            try:
                ns=dict(fn.__globals__)
                for d in ctx['catalog']['dimensions']:
                    b=d.get('binding',{})
                    module_path=str(ROOT/(str(b.get('module','')).replace('.','/')+'.py'))
                    if (b.get('module')==fn.__module__ or str(Path(ns.get('__file__','')).resolve())==module_path) and b.get('name') in ns:
                        if b.get('detail'):
                            ns[b['name']]=copy.deepcopy(ns[b['name']])
                            for detail in ns[b['name']]:
                                if detail['slug']==b['detail']: detail[b['field']]=option_pool(d,detail[b['field']])
                            if 'detail' in bound.arguments and bound.arguments['detail'].get('slug')==b['detail']:
                                bound.arguments['detail']=copy.deepcopy(bound.arguments['detail'])
                                bound.arguments['detail'][b['field']]=option_pool(d,bound.arguments['detail'][b['field']])
                        elif b.get('dictkey'):
                            ns[b['name']]=copy.deepcopy(ns[b['name']])
                            original=ns[b['name']][b['dictkey']]
                            ns[b['name']][b['dictkey']]=option_pool(d,[original])[0] if b.get('scalar') else option_pool(d,original)
                        elif b.get('event_details'):
                            rows=option_pool(d,ns[b['name']]); ns[b['name']]=[(v['id'],v['action'],v['state']) for v in rows]
                            ns['COVER_WORK_DETAILS']={v['id']:v['placement'] for v in rows}
                        else: ns[b['name']]=option_pool(d,ns[b['name']])
                # Helpers use the same overridden constants without touching imported modules.
                for k,v in list(ns.items()):
                    if isinstance(v,types.FunctionType) and v.__module__==fn.__module__ and not hasattr(v,'__wrapped__'):
                        clone=types.FunctionType(v.__code__,ns,v.__name__,v.__defaults__,v.__closure__); clone.__kwdefaults__=v.__kwdefaults__; ns[k]=clone
                for arg,source in documents:
                    if arg in bound.arguments: bound.arguments[arg]=overlay_document(cat,bound.arguments[arg],source)
                target=types.FunctionType(fn.__code__,ns,fn.__name__,fn.__defaults__,fn.__closure__); target.__kwdefaults__=fn.__kwdefaults__
                result=target(*bound.args,**bound.kwargs)
                if cat=='business_ktv' and fn.__name__=='sample': result['variable_catalog_revision']=ctx['catalog']['revision']
                local_ctx={**ctx,'seed':str(bound.arguments.get('group_index',bound.arguments.get('seed',ctx['seed'])))}
                if cat=='business_ktv' and fn.__name__=='prompt':
                    rendered,annotated=finish((result,{}),local_ctx,actual_role)
                    bound.arguments['scene']['variable_catalog']=annotated['variable_catalog']
                    return rendered
                return finish(result,local_ctx,actual_role) if finish_result and (own or finish_result=='always') else result
            finally:
                if own: CURRENT.reset(token)
        return wrapper
    return decorate

def cli(args):
    try:
        request=json.load(sys.stdin) if args.operation in {'save','validate','preview','restore'} else {}
        cat=args.category
        if args.operation=='projects': result=[{'id':p['id'],'name':p['name']} for p in projects()]
        elif args.operation=='list': result=load(cat)
        elif args.operation=='history': result=history(cat)
        elif args.operation=='validate': validate(request['catalog']); result={'valid':True}
        elif args.operation=='save': result=save(cat,request['catalog'],request['expected_revision'])
        elif args.operation=='restore':
            value=defaults(cat) if request.get('revision')=='default' else read_json(project_dir(cat)/'variable_history'/f"{int(request['revision']):06d}.json")
            current_defaults={d['id']:d for d in defaults(cat)['dimensions']}
            for d in value['dimensions']:
                if d['kind']!='builtin' or d['id'] not in current_defaults: continue
                for key in ('binding','roles','schema','fixed_shape','source','minimum_pool','status','weight_locked'):
                    if key in current_defaults[d['id']]: d[key]=copy.deepcopy(current_defaults[d['id']][key])
                    else: d.pop(key,None)
            present={d['id'] for d in value['dimensions']}
            value['dimensions'].extend(d for d in defaults(cat)['dimensions'] if d['id'] not in present)
            result=save(cat,value,request['expected_revision'])
        elif args.operation=='preview': result=preview(cat,request)
        else: raise ValueError('不支持的变量操作')
        print(json.dumps({'ok':True,'data':result},ensure_ascii=False)); return 0
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False)); return 1

def add_arguments(subparsers):
    p=subparsers.add_parser('variables',help='本地变量管理，不生图')
    p.add_argument('operation',choices=['projects','list','save','validate','preview','history','restore'])
    p.add_argument('--category',default='road_rescue')
    p.set_defaults(handler=cli)

def preview(category, request):
    # Implemented against real pure prompt builders, never production or API commands.
    from tools.variable_preview import build
    return build(category,request)
