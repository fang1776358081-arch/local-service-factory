"""Versioned, signed, data-only rule distribution. Publishing is explicit."""
import base64
import copy
import io
import json
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import time
import zipfile
from tools import runtime_paths as paths, update_protocol as protocol

PROJECTS=('road_rescue','lock_service','home_appliance_repair','computer_repair','pipe_unclogging','pet_transport','truck_rescue','ktv','business_ktv','diving_salvage')
CATALOG_FIELDS=('schema_version','category_id','revision','dimensions','readonly')
PRIVATE_FIELDS={'phone','phones','contact_phones','confirmed_phone','confirmed_phones','phone_source','api_key','api_keys','token','secret','source_thread_id','source_user_turn_id','source_thread_title','import_authorization','reference_files','reference_images','source_images','reference_evidence','source_image','source_file','latest_api_job','latest_groups_review','latest_local_text_review'}
PHONE=re.compile(r'(?<!\d)(?:1[3-9](?:[ -]?\d){9}|400[ -]?\d{3}[ -]?\d{4}|0\d{2,3}[- ]\d{7,8})(?!\d)')
PRIVATE_TEXT=re.compile(r'(?i)(?:\bsk-[a-z0-9_-]{10,}|\bgh[pousr]_[a-z0-9_]{15,}|[a-z]:[\\/]|file://|/Users/|/home/)')

def write(file,value):
    from tools.task_library import write as atomic
    atomic(file,value)

def local():return paths.data_root()/'.runtime/updates'

def scrub(value):
    if isinstance(value,dict):return {k:scrub(v) for k,v in value.items() if k.lower() not in PRIVATE_FIELDS and not any(t in k.lower() for t in ('api_key','credential','access_token'))}
    if isinstance(value,list):return [scrub(v) for v in value]
    if isinstance(value,str):
        if PRIVATE_TEXT.search(value):return '[本地信息不发布]'
        return PHONE.sub('{已确认电话}',value)
    return value

def field_map():return json.loads((paths.CODE_ROOT/'distribution/rules-fields.json').read_text(encoding='utf-8'))

def allowed_files():
    return set(field_map())|{'projects/registry.json','prompt_template_storefront.md'}|{f'projects/{c}/variable_catalog.json' for c in PROJECTS}

def export_documents():
    from tools import variable_catalog as vc
    docs={}
    for name,fields in field_map().items():
        value=json.loads((paths.CODE_ROOT/name).read_text(encoding='utf-8-sig'))
        if name=='configs/postprocess.json':
            from tools.postprocess_rules import validate
            validate(value)
        docs[name]=protocol.canonical(scrub({k:value[k] for k in fields if k in value}))
    registry=json.loads((paths.CODE_ROOT/'projects/registry.json').read_text(encoding='utf-8-sig'))
    docs['projects/registry.json']=protocol.canonical({'schema_version':1,'active_project':PROJECTS[0],'projects':[
        {k:r[k] for k in ('id','name','status','definition')} for r in registry['projects'] if r['id'] in PROJECTS]})
    if len(json.loads(docs['projects/registry.json'])['projects'])!=len(PROJECTS):raise ValueError('规则包须包含全部已支持业务')
    for category in PROJECTS:
        catalog=copy.deepcopy(vc.load(category));vc.validate(catalog)
        # Readonly sections are regenerated from sanitized definitions, never publish confirmed input history.
        catalog['readonly']=[]
        docs[f'projects/{category}/variable_catalog.json']=protocol.canonical(scrub({k:catalog[k] for k in CATALOG_FIELDS if k in catalog}))
    docs['prompt_template_storefront.md']=scrub((paths.CODE_ROOT/'prompt_template_storefront.md').read_text(encoding='utf-8')).encode('utf-8')
    for name,data in docs.items():
        text=data.decode('utf-8')
        if PHONE.search(text) or PRIVATE_TEXT.search(text):raise ValueError('公开规则隐私检查失败：'+name)
    return docs

def valid_version(value):
    if not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{0,19}',value):raise ValueError('规则版本必须为正整数字符串')
    return value

def app_tuple(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d+\.\d+\.\d+',value):raise ValueError('软件版本格式无效')
    return tuple(map(int,value.split('.')))

def validate_payload(payload,cfg):
    valid_version(payload.get('version'))
    if payload.get('kind')!='rules' or payload.get('schema')!=cfg['rules_schema']:raise ValueError('规则包格式不兼容')
    if app_tuple(payload['min_app'])>app_tuple(cfg['app_version']):raise ValueError('此规则版本需要先更新软件')
    if payload.get('engine_major')!=app_tuple(cfg['app_version'])[0]:raise ValueError('规则包与生成引擎不兼容')
    files=payload.get('files')
    if not isinstance(files,dict) or set(files) not in (allowed_files(), allowed_files()-{'configs/postprocess.json'}):raise ValueError('规则包文件范围与当前业务白名单不一致')
    if any(not re.fullmatch(r'[0-9a-f]{64}',v) for v in files.values()):raise ValueError('规则摘要格式无效')

def unpack(payload,archive,folder,cfg):
    validate_payload(payload,cfg)
    if len(archive)>cfg['max_rules_bytes'] or protocol.sha(archive)!=payload.get('sha256'):raise ValueError('规则压缩包摘要或大小不正确')
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        members=z.infolist()
        if len(members)!=len(payload['files']) or {m.filename for m in members}!=set(payload['files']):raise ValueError('规则包成员不正确或重复')
        if sum(m.file_size for m in members)>cfg['max_rules_bytes']:raise ValueError('规则解压后超过大小上限')
        for member in members:
            name=member.filename
            if member.is_dir() or (member.external_attr>>16)&0o170000==0o120000 or '\\' in name or '..' in PurePosixPath(name).parts:raise ValueError('规则包不能包含链接或越界路径')
            data=z.read(member)
            if protocol.sha(data)!=payload['files'][name]:raise ValueError('规则文件摘要不匹配：'+name)
            text=data.decode('utf-8')
            if PHONE.search(text) or PRIVATE_TEXT.search(text):raise ValueError('规则包含本地私密信息：'+name)
            if name.endswith('.json'):
                document=json.loads(text)
                if scrub(document)!=document:raise ValueError('规则包含私密字段：'+name)
                if name=='configs/postprocess.json':
                    from tools.postprocess_rules import validate
                    validate(document)
                if name in field_map() and not set(document)<=set(field_map()[name]):raise ValueError('规则出现未经允许的字段：'+name)
            target=folder/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    write(folder/'manifest.json',payload)

def validate_business(folder):
    from tools import variable_catalog as vc
    from tools.task_groups import build_group
    with paths.use_rules(folder):
        for category in PROJECTS:
            catalog=vc.load(category);vc.validate(catalog)
            config_path=paths.CODE_ROOT/('configs/business_ktv/scene_library.json' if category=='business_ktv' else f'configs/categories/{category}.json')
            config=paths.read_json(config_path) if paths.rule_file(config_path).exists() else {}
            # Local assembly validates each business, never invokes an image API.
            rows=build_group(category,1401,'00000000000',catalog,config)
            definition=paths.read_json(paths.CODE_ROOT/f'projects/{category}/project.json')
            structure=definition['content_group'];expected=structure.get('generation_unit_count') or structure['cover_count']+structure['detail_count']
            if len(rows)!=expected or any(not r['prompt'].strip() for r in rows):raise ValueError('业务组装验证失败：'+category)

def repository_identity(cfg):
    return {'owner': cfg['owner'], 'repo': cfg['rules_repo']}


def require_repository(record, cfg):
    if record.get('repository') != repository_identity(cfg):
        raise ValueError('规则缓存或计划不属于当前仓库；请同步当前仓库并重新生成计划，旧记录保留')


def migration_source(cfg):
    configured=cfg.get('legacy_rules_repository')
    if 'legacy_rules_repository' in cfg and not isinstance(configured,dict):
        raise ValueError('旧规则仓库身份配置无效')
    if isinstance(configured,dict):
        owner=configured.get('owner');repo=configured.get('repo')
        if not isinstance(owner,str) or not owner or not isinstance(repo,str) or not repo:
            raise ValueError('旧规则仓库身份配置无效')
        if (owner.lower(),repo.lower())==(cfg['owner'].lower(),cfg['rules_repo'].lower()):
            raise ValueError('旧规则仓库不能与当前规则仓库相同')
        return {'owner':owner,'repo':repo}
    if cfg['owner']=='eish1997' and cfg['rules_repo']=='local-service-factory-dev':
        return {'owner':'eish1997','repo':'local-service-factory-rules'}
    return None


def tracked_head(cfg):
    tracked = local()/'remote_head.json'
    if not tracked.exists():
        if migration_source(cfg):raise ValueError('统一仓库尚无同步基准；首次迁移必须显式 migration_from_legacy')
        return {'sha': None, 'files': {}, 'repository': repository_identity(cfg)}
    head = json.loads(tracked.read_text(encoding='utf-8'))
    require_repository(head, cfg)
    return head


def migration_head(cfg):
    source=migration_source(cfg)
    if os.environ.get('FACTORY_DATA_HOME') or not source:
        raise ValueError('规则迁移仅允许维护端使用已记录的统一仓库')
    repo=f'/repos/{cfg["owner"]}/{cfg["rules_repo"]}'
    metadata=protocol.github('GET',repo)
    if not metadata or not metadata.get('default_branch'):raise ValueError('目标仓库不存在或不可访问')
    if protocol.github('GET',repo+'/contents/release-index.json') is not None:
        raise ValueError('目标索引已存在，请正常同步，不重复初始化')
    old_cfg={**cfg,'owner':source['owner'],'rules_repo':source['repo']}
    revision,envelope,payload=remote_index(old_cfg)
    expected=f'https://github.com/{source["owner"]}/{source["repo"]}/releases/download/rules-{payload["version"]}/rules.zip'
    if payload.get('url')!=expected:raise ValueError('旧规则索引来源不匹配')
    return {'sha':None,'files':payload['files'],'repository':repository_identity(cfg),
            'migration':{'from_repository':repository_identity(old_cfg),'index_sha':revision,'version_floor':payload['version'],'envelope':envelope}}


def release_source_sha():
    from tools.stage_distribution import source_identity
    return source_identity()


def release_plan(request):
    cfg=paths.config();head=migration_head(cfg) if request.get('migration_from_legacy') is True else tracked_head(cfg);version=valid_version(request.get('version') or str(time.time_ns()))
    if head.get('migration') and int(version)<=int(head['migration']['version_floor']):raise ValueError('迁移规则版本必须严格高于旧仓版本')
    source_sha=release_source_sha()
    docs=export_documents()
    if release_source_sha()!=source_sha:raise ValueError('规则导出期间源码提交已变化')
    folder=local()/'release_plans'/version
    if folder.exists():raise ValueError('此规则版本计划已存在')
    folder.mkdir(parents=True)
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(docs.items()):z.writestr(name,data)
    data=archive.getvalue()
    payload={'kind':'rules','source_sha':source_sha,'schema':cfg['rules_schema'],'version':version,'min_app':max(cfg['app_version'],'1.4.0',key=app_tuple),
             'engine_major':app_tuple(cfg['app_version'])[0],'sha256':protocol.sha(data),
             'url':f'https://github.com/{cfg["owner"]}/{cfg["rules_repo"]}/releases/download/rules-{version}/rules.zip',
             'files':{n:protocol.sha(v) for n,v in docs.items()}}
    unpack(payload,data,folder/'validated',cfg);validate_business(folder/'validated')
    (folder/'rules.zip').write_bytes(data);write(folder/'payload.json',payload)
    plan={'source_sha':source_sha,'repository':repository_identity(cfg),'version':version,'base_sha':head['sha'],'changed_files':[n for n,h in payload['files'].items() if head.get('files',{}).get(n)!=h],
          'sha256':payload['sha256'],'files':len(docs),'businesses':len(PROJECTS),'validated':True,'api_called':False,'uploaded':False}
    if head.get('migration'):
        plan['migration']=head['migration']
        plan['api_called']=True
    write(folder/'plan.json',plan)
    return plan

def public_index(cfg):
    return f'https://api.github.com/repos/{cfg["owner"]}/{cfg["rules_repo"]}/contents/release-index.json'

def raw_index(cfg):
    return f'https://raw.githubusercontent.com/{cfg["owner"]}/{cfg["rules_repo"]}/HEAD/release-index.json'

def remote_index(cfg):
    from urllib.error import HTTPError,URLError
    # Consumers need the signed file, not anonymous Contents API quota. The
    # maintainer prefers the API's CAS SHA; raw fallback computes the identical
    # Git blob SHA from exact bytes and still cannot bypass the publish CAS.
    routes=['raw','api'] if os.environ.get('FACTORY_DATA_HOME') else ['api','raw']
    last=None
    for route in routes:
        try:
            data=protocol.download(raw_index(cfg) if route=='raw' else public_index(cfg),1024*1024,
                                   'application/octet-stream' if route=='raw' else 'application/vnd.github+json',timeout=12,attempts=1)
            break
        except (HTTPError,URLError,TimeoutError,ConnectionError) as error:last=error
    else:
        if isinstance(last,HTTPError):
            if last.code==404:raise ValueError('远程仓库尚未发布规则，继续使用本地版本') from None
            raise ValueError(f'GitHub 官方规则通道检查失败（HTTP {last.code}），当前兼容规则已保留，下次检查重试') from None
        raise last
    if route=='raw':
        envelope=json.loads(data)
        revision=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    else:
        response=json.loads(data);envelope=json.loads(base64.b64decode(response['content']));revision=response['sha']
    # Never try another route to accept an invalid signature or incompatible
    # payload. All official transports share the same trust and size checks.
    payload=protocol.verify(envelope,cfg['public_keys']);validate_payload(payload,cfg)
    return revision,envelope,payload

def status():
    result={'software_version':paths.config()['app_version'],'rules_version':'bundled','mode':'consumer' if os.environ.get('FACTORY_DATA_HOME') else 'maintainer',
            'configured':bool(paths.config()['public_keys']),'owner':paths.config()['owner']}
    for name in ('active_rules','rules_status','software_status','bootstrap_status'):
        file=local()/(name+'.json')
        if file.exists():result[name]=json.loads(file.read_text(encoding='utf-8'))
    result['rules_version']=result.get('active_rules',{}).get('version','bundled') if os.environ.get('FACTORY_DATA_HOME') else 'workspace'
    return result

def bootstrap(request=None):
    """Select compatible local rules offline; never rewrite frozen versions."""
    from tools.task_library import lock,io_path
    if not os.environ.get('FACTORY_DATA_HOME'):raise ValueError('内置规则准备仅用于独立安装端')
    cfg=paths.config();root=paths.data_root()/'.runtime/rules'
    with lock(local()/'sync.lock'):
        baseline=json.loads((paths.CODE_ROOT/'distribution/baseline-rules.json').read_text(encoding='utf-8'))
        names=baseline['files'];allowed=allowed_files()
        if not isinstance(names,list) or len(names)!=len(set(names)) or set(names) not in (allowed,allowed-{'configs/postprocess.json'}):raise ValueError('内置规则文件白名单无效')
        docs={name:(paths.CODE_ROOT/name).read_bytes() for name in names}
        if sum(map(len,docs.values()))>cfg['max_rules_bytes']:raise ValueError('内置规则大小超限')
        hashes={name:protocol.sha(data) for name,data in docs.items()}
        fingerprint=protocol.sha(protocol.canonical({'app_version':cfg['app_version'],'files':hashes}))
        # This is a local snapshot ID, not a remote release ordering value.
        # Signed sync always replaces a bundled snapshot after validation.
        version=str(2_000_000_000_000_000+int(fingerprint[:12],16))
        pointer=local()/'active_rules.json'
        active=json.loads(pointer.read_text(encoding='utf-8')) if pointer.exists() else {}
        previous=active.get('version');reason='首次启动'
        if previous is not None:
            valid_version(previous);current=root/previous
            try:
                manifest=json.loads((current/'manifest.json').read_text(encoding='utf-8'))
                if manifest['version']!=previous:raise ValueError('规则指针与记录不一致')
                if manifest.get('bundled'):
                    if manifest.get('baseline_sha256')!=fingerprint:raise ValueError('内置规则来自旧版软件')
                    if manifest.get('files')!=hashes:raise ValueError('内置规则摘要记录不完整')
                else:validate_payload(manifest,cfg)
                for name,digest in manifest.get('files',{}).items():
                    if name not in allowed or protocol.sha(io_path(current/name).read_bytes())!=digest:raise ValueError('本地规则文件校验失败')
                validate_business(current)
                paths.installed_rules.cache_clear()
                write(local()/'bootstrap_status.json',{'state':'compatible','version':previous,'checked_at':time.time()})
                return {'state':'compatible','version':previous,'bundled':bool(manifest.get('bundled'))}
            except (ValueError,KeyError,OSError) as error:reason=str(error)
        root.mkdir(parents=True,exist_ok=True);final=root/version
        manifest={'version':version,'bundled':True,'app_version':cfg['app_version'],'baseline_sha256':fingerprint,'files':hashes}
        if final.exists():
            if json.loads(io_path(final/'manifest.json').read_text(encoding='utf-8'))!=manifest or any(protocol.sha(io_path(final/name).read_bytes())!=digest for name,digest in hashes.items()):raise ValueError('内置规则缓存冲突，旧规则已保留，请重新安装软件')
        else:
            temp=root/('bundled-staging-'+secrets.token_hex(8));temp.mkdir()
            try:
                for name,data in docs.items():
                    out=io_path(temp/name);out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data)
                write(temp/'manifest.json',manifest);validate_business(temp);os.rename(temp,final)
            finally:
                if temp.exists():
                    if temp.resolve().parent!=root.resolve():raise ValueError('内置规则清理路径越界')
                    shutil.rmtree(temp)
        write(pointer,{'version':version,'previous':previous,'bundled':True,'baseline_sha256':fingerprint})
        paths.installed_rules.cache_clear()
        state='refreshed' if previous else 'initialized'
        write(local()/'bootstrap_status.json',{'state':state,'version':version,'previous':previous,'reason':reason,'message':'已准备与当前软件兼容的随包规则；历史版本保留','checked_at':time.time()})
        return {'state':state,'version':version,'previous':previous,'bundled':True}

def sync(request=None):
    from tools.task_library import lock
    cfg=paths.config()
    with lock(local()/'sync.lock'):
        try:
            if not cfg['public_keys']:raise ValueError('尚未配置发布验证公钥，继续使用本地规则')
            revision,envelope,payload=remote_index(cfg)
            write(local()/'remote_head.json',{'repository':repository_identity(cfg),'sha':revision,'files':payload['files'],'version':payload['version']})
            if not os.environ.get('FACTORY_DATA_HOME'):
                result={'state':'available','remote_version':payload['version'],'message':'维护端只检查远程版本，不覆盖本地编辑'}
            else:
                active=status().get('active_rules',{})
                if not active.get('bundled') and int(active.get('version','0'))>=int(payload['version']):result={'state':'current','version':active['version']}
                else:
                    data=protocol.download(payload['url'],cfg['max_rules_bytes'])
                    root=paths.data_root()/'.runtime/rules';root.mkdir(parents=True,exist_ok=True)
                    temp=root/('staging-'+secrets.token_hex(8));temp.mkdir()
                    try:
                        unpack(payload,data,temp,cfg);validate_business(temp)
                        final=root/payload['version']
                        if final.exists():
                            if json.loads((final/'manifest.json').read_text(encoding='utf-8'))!=payload:raise ValueError('规则版本号冲突')
                            if any(not (final/name).is_file() or protocol.sha((final/name).read_bytes())!=digest for name,digest in payload['files'].items()):raise ValueError('本地规则缓存损坏，当前兼容规则已保留')
                            validate_business(final)
                        else:os.rename(temp,final)
                        write(local()/'active_rules.json',{'version':payload['version'],'previous':active.get('version'),'sha256':payload['sha256']})
                    finally:
                        if temp.exists():
                            if temp.resolve().parent!=root.resolve():raise ValueError('规则临时目录清理路径越界')
                            shutil.rmtree(temp)
                    result={'state':'updated','version':payload['version']}
            write(local()/'rules_status.json',{**result,'checked_at':time.time()});return result
        except Exception as error:
            write(local()/'rules_status.json',{'state':'error','message':str(error),'checked_at':time.time()})
            raise

def publish(request):
    if request.get('authorization')!='publish_project_update':raise ValueError('需要明确发布项目更新指令')
    if os.environ.get('FACTORY_DATA_HOME'):raise ValueError('使用端没有项目发布权限')
    cfg=paths.config();version=valid_version(request['version']);folder=local()/'release_plans'/version
    payload=json.loads((folder/'payload.json').read_text(encoding='utf-8'));plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    require_repository(plan,cfg)
    source_sha=plan.get('source_sha','')
    if not isinstance(source_sha,str) or not re.fullmatch(r'[a-f0-9]{40}',source_sha) or payload.get('source_sha')!=source_sha:raise ValueError('规则计划缺少匹配源码 SHA')
    expected_url=f'https://github.com/{cfg["owner"]}/{cfg["rules_repo"]}/releases/download/rules-{version}/rules.zip'
    if payload.get('url')!=expected_url:raise ValueError('签名规则 URL 与目标仓库不一致')
    data=(folder/'rules.zip').read_bytes()
    if not plan['validated'] or protocol.sha(data)!=payload['sha256']:raise ValueError('发布计划内容已变化')
    validate_payload(payload,cfg)
    keyfile=os.environ.get('FACTORY_RELEASE_KEY_FILE') or str(paths.data_root()/'.runtime/private/release-signing.pem');key_id=os.environ.get('FACTORY_RELEASE_KEY_ID') or 'release-2026-09'
    if not keyfile or not key_id:raise ValueError('请先在维护端配置发布签名私钥文件和标识')
    envelope=protocol.sign(payload,key_id,keyfile,cfg['public_keys'])
    repo=f'/repos/{cfg["owner"]}/{cfg["rules_repo"]}'
    commit=protocol.github('GET',repo+'/commits/'+source_sha)
    if not commit or commit.get('sha')!=source_sha:raise ValueError('规则源码提交尚未存在于目标仓库')
    current=protocol.github('GET',repo+'/contents/release-index.json')
    current_sha=current['sha'] if current else None
    if current is None and migration_source(cfg) and not plan.get('migration'):
        raise ValueError('新仓空索引只能通过显式迁移计划初始化')
    if plan.get('migration'):
        old_payload=protocol.verify(plan['migration']['envelope'],cfg['public_keys'])
        if int(version)<=int(old_payload['version']):raise ValueError('迁移版本未超过旧仓版本')
        fresh=migration_head(cfg)
        if int(version)<=int(fresh['migration']['version_floor']):raise ValueError('旧仓版本已推进，请重新生成迁移计划')
    if current_sha!=plan['base_sha']:raise ValueError('远端版本已变化，请同步检查并重新生成发布计划')
    if current:
        old=protocol.verify(json.loads(base64.b64decode(current['content'])),cfg['public_keys'])
        if int(version)<=int(old['version']):raise ValueError('发布版本必须高于远端版本；回退内容也需要新版本号')
    if protocol.github('GET',repo+'/git/ref/tags/rules-'+version) or protocol.github('GET',repo+'/releases/tags/rules-'+version):
        raise ValueError('规则标签或发布已存在；核对附件和索引后恢复，不覆盖未知内容')
    release=protocol.github('POST',repo+'/releases',{'tag_name':'rules-'+version,'name':'项目规则 '+version,'draft':True,'make_latest':'false','target_commitish':source_sha})
    upload=release['upload_url'].split('{')[0]
    protocol.github('POST',upload+'?name=rules.zip',raw=data)
    protocol.github('POST',upload+'?name=manifest.json',raw=protocol.canonical(envelope))
    protocol.github('PATCH',repo+'/releases/'+str(release['id']),{'draft':False,'make_latest':'false'})
    if protocol.sha(protocol.download(payload['url'],cfg['max_rules_bytes']))!=payload['sha256']:raise ValueError('公开下载验证失败，最新版本指向未改变')
    remote_manifest=protocol.verify(json.loads(protocol.download(payload['url'].rsplit('/',1)[0]+'/manifest.json',1024*1024)),cfg['public_keys'])
    if remote_manifest!=payload:raise ValueError('规则公开签名清单不一致，最新版本指向未改变')
    body={'message':'Publish rules '+version,'content':base64.b64encode(protocol.canonical(envelope)).decode()}
    if current_sha:body['sha']=current_sha
    changed=protocol.github('PUT',repo+'/contents/release-index.json',body)
    write(local()/'remote_head.json',{'repository':repository_identity(cfg),'sha':changed['content']['sha'],'files':payload['files'],'version':version})
    return {'published':True,'version':version,'url':f'https://github.com/{cfg["owner"]}/{cfg["rules_repo"]}/releases/tag/rules-{version}'}

def rollback(request):
    # Repackage a previously verified local release under a new increasing version.
    if request.get('authorization')!='publish_project_update':raise ValueError('回退发布需要明确指令')
    old=local()/'release_plans'/valid_version(request['from_version'])
    new_version=valid_version(request.get('version') or str(time.time_ns()))
    cfg=paths.config();new=local()/'release_plans'/new_version
    if new.exists():raise ValueError('回退版本已存在')
    original=json.loads((old/'payload.json').read_text(encoding='utf-8'));data=(old/'rules.zip').read_bytes()
    source_sha=original.get('source_sha')
    if not isinstance(source_sha,str) or not re.fullmatch(r'[a-f0-9]{40}',source_sha):raise ValueError('历史规则缺少源码关联，需人工审阅后重新准备')
    original.update(version=new_version,url=f'https://github.com/{cfg["owner"]}/{cfg["rules_repo"]}/releases/download/rules-{new_version}/rules.zip')
    new.mkdir(parents=True);unpack(original,data,new/'validated',cfg);validate_business(new/'validated')
    (new/'rules.zip').write_bytes(data);write(new/'payload.json',original)
    head=tracked_head(cfg)
    write(new/'plan.json',{'source_sha':source_sha,'repository':repository_identity(cfg),'base_sha':head['sha'],'validated':True})
    return publish({**request,'version':new_version})

def cli(args):
    import sys
    try:
        request=json.load(sys.stdin) if not sys.stdin.isatty() else {}
        if args.family=='updates':
            if args.operation in {'release-plan','publish','setup','recover'}:
                from tools import software_release
                result=getattr(software_release,args.operation.replace('-','_'))(request)
            elif args.operation=='status':result=status()
            else:
                write(local()/'check_request.json',{'id':secrets.token_hex(16),'requested_at':time.time()})
                try:rules=sync(request)
                except Exception as error:rules={'state':'error','message':str(error)}
                result={'rules':rules,'software':'已请求桌面更新服务检查；若看板未打开，将在下次启动检查'}
        else:result={'bootstrap':bootstrap,'sync':sync,'release-plan':release_plan,'publish':publish,'rollback':rollback}[args.operation](request)
        print(json.dumps({'ok':True,'data':result},ensure_ascii=False));return 0
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False));return 1

def add_arguments(subparsers):
    for family,operations in [('rules',['bootstrap','sync','release-plan','publish','rollback']),('updates',['status','check','release-plan','publish','setup','recover'])]:
        parser=subparsers.add_parser(family);parser.add_argument('operation',choices=operations);parser.set_defaults(handler=cli,family=family)
