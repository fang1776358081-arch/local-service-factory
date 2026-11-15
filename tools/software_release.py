"""Explicit software release publishing, separate from rule publication."""
import base64
import json
import os
import re
from pathlib import Path
from tools import runtime_paths as paths, update_protocol as protocol

def setup(request):
    if request.get('authorization')!='initialize_update_repositories' or os.environ.get('FACTORY_DATA_HOME'):raise ValueError('初始化仓库需要维护端明确指令')
    cfg=paths.config();user=protocol.github('GET','/user');result=[]
    for repo in dict.fromkeys((cfg['software_repo'],cfg['rules_repo'])):
        existing=protocol.github('GET',f'/repos/{cfg["owner"]}/{repo}')
        if existing:
            if existing.get('private'):raise ValueError('分发仓库必须公开，不能自动改变现有仓库权限')
            result.append(existing['html_url']);continue
        endpoint='/user/repos' if user['login'].lower()==cfg['owner'].lower() else '/orgs/'+cfg['owner']+'/repos'
        created=protocol.github('POST',endpoint,{'name':repo,'private':False,'auto_init':True,'description':'Local Service Image Factory official distribution'})
        result.append(created['html_url'])
    return {'repositories':result,'published_release':False}

def publication_target(cfg, request):
    target=request.get('target','unified')
    if target=='unified':return cfg['owner'],cfg['software_repo']
    configured=cfg.get('legacy_software_repository')
    if target=='legacy-software' and 'legacy_software_repository' in cfg and not isinstance(configured,dict):
        raise ValueError('旧软件仓库身份配置无效')
    if target=='legacy-software' and isinstance(configured,dict):
        owner=configured.get('owner');repo=configured.get('repo')
        if not isinstance(owner,str) or not owner or not isinstance(repo,str) or not repo:
            raise ValueError('旧软件仓库身份配置无效')
        if (owner.lower(),repo.lower())==(cfg['owner'].lower(),cfg['software_repo'].lower()):
            raise ValueError('旧软件仓库不能与当前软件仓库相同')
        return owner,repo
    if target=='legacy-software' and cfg['owner']=='eish1997' and cfg['software_repo']=='local-service-factory-dev':
        return cfg['owner'],'local-service-factory-releases'
    raise ValueError('过渡发布目标不在已记录的新旧仓库范围内')


def publication_repo(cfg, request):
    """Backward-compatible repository-name helper for existing callers/tests."""
    return publication_target(cfg,request)[1]


def release_plan(request):
    cfg=paths.config();publication_target(cfg,request);version=cfg['app_version'];folder=Path(request['directory']).resolve()
    names=[f'LocalServiceFactory-{version}-setup.exe',f'LocalServiceFactory-{version}-setup.exe.blockmap','latest.yml']
    if not all((folder/n).is_file() for n in names):raise ValueError('缺少安装包、差分文件或 latest.yml，请先明确授权构建')
    files={name:protocol.sha((folder/name).read_bytes()) for name in names}
    provenance=json.loads((folder/'build-provenance.json').read_text(encoding='utf-8'))
    if provenance.get('schema_version')!=1 or provenance.get('version')!=version or provenance.get('repository')!={'owner':cfg['owner'],'repo':cfg['software_repo']} or provenance.get('files')!=files:
        raise ValueError('构建来源记录与当前配置或附件不一致')
    source_sha=provenance.get('source_sha','')
    if not isinstance(source_sha,str) or not re.fullmatch(r'[a-f0-9]{40}',source_sha):raise ValueError('构建缺少有效源码 SHA')
    return {'version':version,'directory':str(folder),'files':files,'source_sha':source_sha,'target':request.get('target','unified'),'uploaded':False}

def validate_latest(latest, version):
    from tools.rule_updates import app_tuple
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('软件版本格式无效')
    if not latest:
        return
    tag = latest.get('tag_name', '')
    if not isinstance(tag, str) or not re.fullmatch(r'v\d+\.\d+\.\d+', tag) or latest.get('draft') or latest.get('prerelease'):
        raise ValueError('Latest 不是有效的正式软件版本；请先核对远端，不自动修复')
    if app_tuple(tag[1:]) >= app_tuple(version):
        raise ValueError('软件版本必须高于已发布版本')


def verify_unified_channels(cfg, plan, expected_payload, expected_envelope=None):
    from tools import rule_updates as rules
    repo=f'/repos/{cfg["owner"]}/{cfg["software_repo"]}'
    latest=protocol.github('GET',repo+'/releases/latest')
    if not latest or latest.get('tag_name')!='v'+plan['version'] or latest.get('draft') or latest.get('prerelease'):
        raise ValueError('新仓软件通道尚未就绪，不能推进旧仓过渡版')
    base=f'https://github.com/{cfg["owner"]}/{cfg["software_repo"]}/releases/download/v{plan["version"]}/'
    raw=protocol.download(base+'software-manifest.json',1024*1024)
    if protocol.verify(json.loads(raw),cfg['public_keys'])!=expected_payload:raise ValueError('新仓软件清单与过渡产物不一致')
    if expected_envelope is not None and raw!=protocol.canonical(expected_envelope):raise ValueError('双仓签名清单字节不一致')
    for name,digest in plan['files'].items():
        limit=(Path(plan['directory'])/name).stat().st_size+1
        if protocol.sha(protocol.download(base+name,limit,timeout=3600))!=digest:raise ValueError('新仓附件与过渡产物不一致')
    _,_,payload=rules.remote_index(cfg)
    expected=f'https://github.com/{cfg["owner"]}/{cfg["rules_repo"]}/releases/download/rules-{payload["version"]}/rules.zip'
    if payload.get('url')!=expected:raise ValueError('新仓规则索引仍指向旧通道')
    if protocol.sha(protocol.download(expected,cfg['max_rules_bytes']))!=payload['sha256']:raise ValueError('新仓规则下载尚未就绪')


def recover(request):
    """Inspect first; only finalize already-public, byte-verified releases."""
    if os.environ.get('FACTORY_DATA_HOME'):raise ValueError('使用端没有发布恢复权限')
    cfg=paths.config();plan=release_plan(request)
    target_owner,target_repo=publication_target(cfg,request)
    repo=f'/repos/{target_owner}/{target_repo}';version=plan['version']
    lock=protocol.github('GET',repo+'/git/ref/tags/software-publish-lock')
    release=protocol.github('GET',repo+'/releases/tags/v'+version)
    tag=protocol.github('GET',repo+'/git/ref/tags/v'+version)
    latest=protocol.github('GET',repo+'/releases/latest')
    blocks=[]
    release_sha=plan['source_sha'] if (target_owner,target_repo)==(cfg['owner'],cfg['software_repo']) else (release or {}).get('target_commitish','')
    if not isinstance(release_sha,str) or not re.fullmatch(r'[a-f0-9]{40}',release_sha):blocks.append('过渡发布缺少明确目标提交')
    if not lock or lock.get('object',{}).get('sha')!=release_sha:blocks.append('发布锁缺失或不属于构建源码')
    if not tag or tag.get('object',{}).get('sha')!=release_sha:blocks.append('发布标签缺失或源码不匹配')
    if not release or release.get('draft') or release.get('prerelease'):blocks.append('发布仍为草稿或不存在；先人工核对上传结果，不重放上传')
    if latest and latest.get('tag_name')=='v'+version:
        if not release or latest.get('id')!=release.get('id'):blocks.append('Latest 身份不一致')
    else:validate_latest(latest,version)
    if blocks:return {'recoverable':False,'blocks':blocks,'uploaded':False}
    expected=set(plan['files'])|{'software-manifest.json'}
    names=[a.get('name') for a in release.get('assets',[])]
    if len(names)!=len(expected) or set(names)!=expected:raise ValueError('远端附件缺失、重复或包含未知内容，保留锁')
    base=f'https://github.com/{target_owner}/{target_repo}/releases/download/v{version}/'
    for name,digest in plan['files'].items():
        limit=(Path(plan['directory'])/name).stat().st_size+1
        if protocol.sha(protocol.download(base+name,limit,timeout=3600))!=digest:raise ValueError('恢复附件摘要不一致，保留锁')
    envelope=json.loads(protocol.download(base+'software-manifest.json',1024*1024))
    payload=protocol.verify(envelope,cfg['public_keys'])
    expected_payload={'kind':'software','source_sha':plan['source_sha'],'version':version,'sha256':plan['files'][f'LocalServiceFactory-{version}-setup.exe'],'files':plan['files']}
    if payload!=expected_payload:raise ValueError('恢复签名清单不一致，保留锁')
    if (target_owner,target_repo)!=(cfg['owner'],cfg['software_repo']):verify_unified_channels(cfg,plan,payload,envelope)
    if request.get('authorization')!='finalize_software_recovery':
        return {'recoverable':True,'version':version,'source_sha':plan['source_sha'],'files':plan['files'],'uploaded':False}
    if request.get('source_sha')!=plan['source_sha'] or request.get('files')!=plan['files']:raise ValueError('请确认当前恢复计划')
    if not latest or latest.get('tag_name')!='v'+version:
        protocol.github('PATCH',repo+'/releases/'+str(release['id']),{'make_latest':'true'})
    protocol.github('DELETE',repo+'/git/refs/tags/software-publish-lock')
    return {'recovered':True,'version':version,'uploaded':False}


def publish(request):
    if request.get('authorization')!='publish_software_update' or os.environ.get('FACTORY_DATA_HOME'):raise ValueError('软件发布只允许维护端在明确发布指令后执行')
    cfg=paths.config();plan=release_plan(request)
    if request.get('files')!=plan['files'] or request.get('source_sha')!=plan['source_sha']:raise ValueError('构建产物已变化，请重新检查发布计划')
    version=plan['version'];target_owner,target_repo=publication_target(cfg,request);repo=f'/repos/{target_owner}/{target_repo}'
    payload={'kind':'software','source_sha':plan['source_sha'],'version':version,'sha256':plan['files'][f'LocalServiceFactory-{version}-setup.exe'],'files':plan['files']}
    envelope=protocol.sign(payload,os.environ.get('FACTORY_RELEASE_KEY_ID') or 'release-2026-09',
                           os.environ.get('FACTORY_RELEASE_KEY_FILE') or paths.data_root()/'.runtime/private/release-signing.pem',cfg['public_keys'])
    if (target_owner,target_repo)!=(cfg['owner'],cfg['software_repo']):verify_unified_channels(cfg,plan,payload,envelope)
    # Creating a unique Git ref is an atomic publishing lock; leave it for explicit recovery on error.
    metadata=protocol.github('GET',repo)
    if not metadata or not metadata.get('default_branch'):raise ValueError('请先初始化软件发布仓库')
    ref=protocol.github('GET',repo+'/git/ref/heads/'+metadata['default_branch'])
    if not ref:raise ValueError('软件仓库默认分支不存在')
    commit=protocol.github('GET',f'/repos/{cfg["owner"]}/{cfg["software_repo"]}/commits/'+plan['source_sha'])
    if not commit or commit.get('sha')!=plan['source_sha']:raise ValueError('构建源码提交尚未存在于发布仓库')
    release_sha=plan['source_sha'] if (target_owner,target_repo)==(cfg['owner'],cfg['software_repo']) else ref['object']['sha']
    latest=protocol.github('GET',repo+'/releases/latest')
    validate_latest(latest,version)
    if protocol.github('GET',repo+'/git/ref/tags/v'+version) or protocol.github('GET',repo+'/releases/tags/v'+version):
        raise ValueError('目标标签或发布已存在；先核对附件与发布锁，不重复上传')
    protocol.github('POST',repo+'/git/refs',{'ref':'refs/tags/software-publish-lock','sha':release_sha})
    release=protocol.github('POST',repo+'/releases',{'tag_name':'v'+version,'name':'软件 '+version,'draft':True,'target_commitish':release_sha,'make_latest':'false'})
    upload=release['upload_url'].split('{')[0]
    for name in plan['files']:protocol.github('POST',upload+'?name='+name,raw=(Path(plan['directory'])/name).read_bytes())
    protocol.github('POST',upload+'?name=software-manifest.json',raw=protocol.canonical(envelope))
    protocol.github('PATCH',repo+'/releases/'+str(release['id']),{'draft':False,'make_latest':'false'})
    base=f'https://github.com/{target_owner}/{target_repo}/releases/download/v{version}/'
    for name,expected in plan['files'].items():
        size=(Path(plan['directory'])/name).stat().st_size
        if protocol.sha(protocol.download(base+name,size+1,timeout=3600))!=expected:raise ValueError('软件公开下载校验失败，尚未设为最新版本')
    downloaded=protocol.verify(json.loads(protocol.download(base+'software-manifest.json',1024*1024,timeout=120)),cfg['public_keys'])
    if downloaded!=payload:raise ValueError('软件公开签名清单不一致，尚未设为最新版本')
    if (target_owner,target_repo)!=(cfg['owner'],cfg['software_repo']):verify_unified_channels(cfg,plan,payload,envelope)
    protocol.github('PATCH',repo+'/releases/'+str(release['id']),{'make_latest':'true'})
    protocol.github('DELETE',repo+'/git/refs/tags/software-publish-lock')
    return {'published':True,'version':version,'url':f'https://github.com/{target_owner}/{target_repo}/releases/tag/v{version}'}
