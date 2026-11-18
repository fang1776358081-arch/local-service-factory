const {spawn}=require('child_process');
const path=require('path');
const {pathToFileURL}=require('url');
const allowed=new Set(['native-register','native-ingest','native-materialize','native-instance','native-plan','native-status','projects','overlay-text','assemble','batches','view','queue-view','queue-detail','raw-library-view','raw-library-folder','raw-library-qualify','raw-library-reindex','plan','start','resume','pause','retry','delete','replacement-prepare','repair-prepare','keys-view','keys-save','legacy-group','postprocess-view','postprocess-apply','postprocess-presets','postprocess-session','postprocess-preview','postprocess-preview-apply','postprocess-preview-sequence','postprocess-text','image-history','image-version-select','assets-view','assets-save','open-folder','package']);
const extendedOperations=new Set(['plan','start','resume','retry','replacement-prepare','repair-prepare']);
function operationTimeout(operation){return ['assemble','package'].includes(operation)?600000:extendedOperations.has(operation)?180000:60000;}
function enrich(root,operation,value){
 const fs=require('fs'),a=require('./assets');
 const add=(item,key='path',field='url')=>{if(!item)return;const file=item[key];if(!a.allowed(root,file)||!a.allowed(root,fs.realpathSync(file)))throw Error('素材路径越界');item[field]=pathToFileURL(file).href+(item.sha256?'?v='+encodeURIComponent(item.sha256):'');};
 if(operation==='queue-view')for(const c of [...value.cards,...(value.pages||[]).flatMap(p=>p.cards)])add(c.source);
 if(operation==='queue-detail'){add(value.card.source);if(value.delivery?.path)add(value.delivery);}
 if(operation==='raw-library-view')for(const entry of value.entries){
  if(entry.thumbnail&&fs.existsSync(entry.thumbnail))add(entry,'thumbnail');
  else entry.preview_missing=true;
  if(entry.original_path&&fs.existsSync(entry.original_path))add(entry,'original_path','original_url');
 }
 return value;
}
function runTasks(root,operation,request={}){
  return new Promise((resolve,reject)=>{
    if(!allowed.has(operation)||!request||typeof request!=='object'||Array.isArray(request))return reject(Error('不支持的任务请求'));
    const payload=JSON.stringify({...request,source:'dashboard'});
    if(operation!=='keys-save'&&Buffer.byteLength(payload)>65536)return reject(Error('任务请求过大'));
    const child=spawn(require('./backend').python(),['-X','utf8',require('./backend').entry(root),'tasks',operation],{cwd:root,windowsHide:true,shell:false,detached:operation==='assemble',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
    let output='',errors='',settled=false;
    const done=(error,value)=>{if(settled)return;if(!error)try{value=enrich(root,operation,value);}catch(e){error=e;}settled=true;clearTimeout(timer);error?reject(error):resolve(value);};
    // Assembly owns disk state and must survive window closure; only reads time out.
    const timer=setTimeout(()=>{if(operation!=='assemble')child.kill();done(Error(operation==='plan'?'检查可用密钥超时，尚未提交生成任务，请稍后重试':'本地任务仍在处理，请刷新查看磁盘状态'));},operationTimeout(operation));
    child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');
    child.stdout.on('data',s=>{output+=s;if(output.length>16*1024*1024)done(Error('结果过大，请分页读取'));});
    child.stderr.on('data',s=>{errors=(errors+s).slice(-1000);});
    child.on('error',e=>done(Error('无法运行本地任务工具：'+e.message)));
    child.on('close',(code)=>{try{const r=JSON.parse(output.trim());if(!r.ok)throw Error(r.error);if(operation==='view')for(const g of r.data.groups)for(const i of g.images){if(!require('./assets').inside(require('./assets').batchOutput(root,request.category,request.batch),i.path))throw Error('图片路径越界');i.url=pathToFileURL(i.path).href+'?v='+encodeURIComponent(i.revision||'');}if(operation==='postprocess-view'){const a=require('./assets');const base=request.batch==='legacy'||!request.batch?null:a.batchOutput(root,request.category,request.batch);const add=i=>{if(!i)return;if(!a.allowed(root,i.path))throw Error('图片路径越界');if(i.exists)i.url=pathToFileURL(i.path).href+'?v='+encodeURIComponent(i.revision||'');if(i.original)add(i.original);};add(r.data.delivery);for(const i of r.data.sources||[])add(i);}if(operation==='postprocess-session'||operation==='postprocess-preview'||operation==='postprocess-preview-sequence'){const rows=operation==='postprocess-session'?r.data.sources:operation==='postprocess-preview-sequence'?r.data.previews:[r.data];for(const i of rows){if(!require('./assets').allowed(root,i.path))throw Error('预览路径越界');i.url=pathToFileURL(i.path).href+'?v='+encodeURIComponent(i.sha256||'');}}if(operation==='image-history')for(const i of r.data.versions){const assets=require('./assets'),fs=require('fs'),work=path.join(root,'.runtime','image-work',request.category,'library');const safe=p=>assets.allowed(root,p)||(assets.inside(work,p)&&path.basename(p)==='image.png'&&p.split(path.sep).includes('.v'));if(!safe(i.path)||!safe(fs.realpathSync(i.path)))throw Error('历史图片路径越界');i.url=pathToFileURL(i.path).href+'?v='+i.sha256;}done(null,r.data);}catch(e){const missing=errors.match(/ModuleNotFoundError: No module named '([a-zA-Z0-9_.]+)'/);done(Error(output.trim().startsWith('{')?e.message:missing?`本地 Python 缺少依赖 ${missing[1]}，请修复开发环境后重启看板`:`本地任务没有返回有效结果（退出码：${code}）`));}});
    child.stdin.on('error',()=>{});child.stdin.end(payload);
  });
}
function readLibraryJobs(root){
 const fs=require('fs'),result=[];const home=path.join(root,'prompts','library');
 if(!fs.existsSync(home))return result;
 for(const category of fs.readdirSync(home,{withFileTypes:true}).filter(d=>d.isDirectory())){
  const c=path.join(home,category.name);
  for(const batch of fs.readdirSync(c,{withFileTypes:true}).filter(d=>d.isDirectory()&&d.name.startsWith('batch_'))){
   const tasks=path.join(c,batch.name,'tasks');if(!fs.existsSync(tasks))continue;
   try{if(JSON.parse(fs.readFileSync(path.join(c,batch.name,'batch.json'),'utf8')).automatic_repair_parent)continue;}catch{}
   for(const task of fs.readdirSync(tasks,{withFileTypes:true}).filter(d=>d.isDirectory())){
    try{const data=JSON.parse(fs.readFileSync(path.join(tasks,task.name,'task.json'),'utf8'));
     let repairUsed=0,updatedAt=data.updated_at;
     for(const [id,e] of Object.entries(data.auto_recovery?.children||{})){
      if(!/^batch_revision_auto_[a-f0-9]{28}$/.test(e.batch)||!/^auto-[a-f0-9]{28}$/.test(id))continue;
      const childDir=path.join(c,e.batch,'tasks',id);
      try{repairUsed+=JSON.parse(fs.readFileSync(path.join(childDir,'license.json'),'utf8')).requests_used||0;}catch{}
      if(data.status==='recovering')try{
       const child=JSON.parse(fs.readFileSync(path.join(childDir,'task.json'),'utf8'));
       if(child.id===id&&child.batch===e.batch&&child.category===category.name&&child.pid===data.pid&&Number.isFinite(Date.parse(child.updated_at))&&Date.parse(child.updated_at)>Date.parse(updatedAt||data.created_at))updatedAt=child.updated_at;
      }catch{}
     }
     result.push({...data,updated_at:updatedAt,requests_used:data.requests_used+repairUsed,job_id:data.id,job_type:'shared-task',project_id:category.name,category_id:category.name,batch_id:batch.name,
      group_start:Math.min(...data.groups),group_count:data.groups.length,api_key_slots:data.slots,
      requested_count:data.total_units,completed:data.completed_units||data.reused_units||0,
      request_budget:data.max_requests+(data.auto_complete?.max_requests||0),reused:data.reused_units||0,generated:Math.max(0,(data.completed_units||0)-(data.reused_units||0)),model:data.config.model,quality:data.config.quality,size:data.config.api_size,
      failed:data.auto_complete?.enabled?(data.resume_summary?.blocked_count||0):Object.values(data.results||{}).filter(r=>r.status==='failed').length});
    }catch{}
   }
  }
 }
 return result;
}
// Install admission is separate from API job presentation. The CLI holds the
// admin lock for short writes and a live process lease for work outside it.
function hasActiveNativeTasks(root){
 const fs=require('fs'),{processIsAlive}=require('./monitor');
 const dirs=dir=>{try{return fs.readdirSync(dir,{withFileTypes:true});}catch(e){if(e.code==='ENOENT')return [];throw e;}};
 const read=file=>{try{return JSON.parse(fs.readFileSync(file,'utf8'));}catch(e){if(e.code==='ENOENT')return null;throw e;}};
 try{
  for(const file of dirs(path.join(root,'.runtime/native-writes'))){
   if(file.isFile()&&file.name.endsWith('.lock')){
    const lease=read(path.join(root,'.runtime/native-writes',file.name));
    if(lease&&processIsAlive(lease.pid)!==false)return true;
   }
  }
  const home=path.join(root,'prompts/library');
  for(const category of dirs(home).filter(d=>d.isDirectory())){
   for(const batch of dirs(path.join(home,category.name)).filter(d=>d.isDirectory()&&d.name.startsWith('batch_'))){
    const dir=path.join(home,category.name,batch.name),state=read(path.join(dir,'native-execution.json'));
    if(!state||state.cancelled)continue;
    if(Object.values(state.units||{}).some(unit=>unit.status==='awaiting_result'))return true;
    // Compatibility with an in-flight renderer started before writer leases.
    // A leftover rendering status alone is recoverable, not a permanent blocker.
    const render=read(path.join(dir,'native-render.lock'));
    if(render&&processIsAlive(render.pid)!==false)return true;
   }
  }
  return false;
 }catch{return true;} // Unreadable activity cannot safely authorize installation.
}
module.exports={runTasks,readLibraryJobs,hasActiveNativeTasks,operationTimeout};
