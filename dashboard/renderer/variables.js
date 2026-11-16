/* Display only. All configuration changes belong to the Agent CLI. */
(() => {
  const el = id => document.getElementById(id);
  const node = (tag,text,cls) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; };
  const labels={camera:'机位',scale:'画面占比',subject:'主体位置',activity:'背景或作业活动',vehicle:'车辆位置',foreground:'前景',setting:'地点',facade:'建筑与门面',ground:'道路地面',neighbours:'周边环境',edge:'边缘元素',bays:'开间数',camera_area:'场地类型',business:'经营形态',color:'色彩',tone:'明暗',texture:'质感',palette:'配色',angle:'拍摄角度',services:'服务内容',label:'名称',period:'年代',scene_cues:'场景线索',facades:'建筑候选',vehicles:'车辆候选',signs:'招牌候选',action:'人物动作',state:'状态',placement:'位置',name:'名称',description:'描述',contact_phones:'联系电话',values:'已确认号码',confirmed:'已确认',required_for:'适用环节',rule:'规则',phone:'电话',service_items:'服务文案'};
  let catalog=null, selected=null, stamp='', generation=0, pollBusy=false, projectsPromise=null;
  const views=new Map();
  let activeProject='road_rescue';
  const call=(operation,category)=>window.roadRescue.variables({operation,category});
  const status=(text,error=false)=>{el('variable-status').textContent=text;el('variable-status').classList.toggle('error',error);};
  const roles=d=>(d.roles||[]).map(x=>x==='cover'?'封面':x==='detail'?'详情':x).join('、')||'全部';
  const legacy=d=>d.status==='legacy';
  const q=()=>el('variable-search').value.trim().toLowerCase();
  const contains=value=>JSON.stringify(value).toLowerCase().includes(q());
  const visibleOptions=d=>d.options.filter(o=>(el('variable-filter').value!=='disabled'||!o.enabled)&&(!q()||contains([d.name,d.description])||contains([o.name,o.value])));
  function dimensions(){return (catalog?.dimensions||[]).filter(d=>(!el('variable-role').value||d.roles.includes(el('variable-role').value))&&(!el('variable-filter').value||el('variable-filter').value==='disabled'||(el('variable-filter').value==='legacy')===legacy(d))&&visibleOptions(d).length);}
  function remember(){if(!catalog)return;views.set(catalog.category_id,{selected,search:el('variable-search').value,role:el('variable-role').value,filter:el('variable-filter').value,scroll:el('variables-panel').scrollTop,side:el('variable-types').scrollTop,open:[...el('variable-content').querySelectorAll('details[open]')].map(n=>n.dataset.key)});}
  function fields(parent,value){
    if(Array.isArray(value)){const list=node('ul');for(const v of value){const li=node('li');fields(li,v);list.append(li);}parent.append(list);}
    else if(value&&typeof value==='object'){const dl=node('dl',undefined,'variable-values');for(const [k,v]of Object.entries(value)){if(k==='id')continue;dl.append(node('dt',labels[k]||k));const dd=node('dd');fields(dd,k==='camera_area'?({street:'临街门店',yard:'院落、园区或停车场'}[v]||v):v);dl.append(dd);}parent.append(dl);}
    else parent.append(node('span',typeof value==='boolean'?(value?'是':'否'):String(value??'—')));
  }
  function condition(c){const d=catalog.dimensions.find(d=>d.id===c.dimension);return `${d?.name||c.dimension} → ${d?.options.find(o=>o.id===c.option)?.name||c.option}`;}
  function render(){
    const dims=dimensions(), side=el('variable-types'), root=el('variable-content');side.replaceChildren();root.replaceChildren();
    if(selected!=='readonly'&&!dims.some(d=>d.id===selected))selected=dims[0]?.id||'readonly';
    function nav(label,id){const b=node('button',label);b.type='button';b.classList.toggle('active',selected===id);b.onclick=()=>{selected=id;render();remember();};side.append(b);}
    for(const d of dims)nav(`${legacy(d)?'旧批次使用 · ':''}${d.name} · ${d.options.filter(o=>o.enabled).length}/${d.options.length}`,d.id);
    nav('固定输入与质量要求','readonly');
    if(selected==='readonly'){
      root.append(node('h3','固定输入与质量要求'),node('p','电话、已确认文案和固定规则不参与随机选择。','variable-muted'));
      for(const item of catalog.readonly||[]){if(q()&&!contains(item))continue;const card=node('section',undefined,'variable-card');card.append(node('h4',item.name),node('p',item.reason,'variable-muted'));fields(card,item.value);root.append(card);}
      return;
    }
    const d=dims.find(d=>d.id===selected);
    root.append(node('h3',d.name),node('p',(d.description||'该业务使用的随机候选项').replace('已有生成器候选池；保存后用于新组装','已有生成器候选池，按当前规则用于新组装')),node('p',`${legacy(d)?'旧批次使用，不用于当前组装':'当前生效'} · 适用：${roles(d)} · 候选 ${d.options.length} 项（启用 ${d.options.filter(o=>o.enabled).length} 项）`,'variable-muted'));
    root.append(node('p',d.kind==='custom'?`出现概率 ${Math.round((d.probability??1)*100)}% · 每次选择 ${d.min_select??1}–${d.max_select??1} 项`:'出现频率与数量：沿用业务生成器的抽样策略和场景兼容规则；候选权重表示相对频率。','variable-muted'));
    if(d.weight_locked)root.append(node('p','此类型按原有顺序分配，候选权重不参与随机选择。','variable-muted'));
    for(const o of visibleOptions(d)){
      const card=node('details',undefined,'variable-card');card.dataset.key=o.id;
      card.append(node('summary',o.name),node('p',`${legacy(d)?'旧批次使用':o.enabled?'已启用':'已停用'} · 相对权重 ${o.weight} · ${roles(d)}`,'variable-muted'));
      fields(card,o.value);
      card.append(node('p',o.conditions?.length?`搭配条件（全部满足）：${o.conditions.map(condition).join('；')}`:d.kind==='builtin'?'搭配条件：沿用内置业务兼容规则；成套字段共同使用。':'搭配条件：无额外限制','variable-muted'));
      card.ontoggle=()=>remember();root.append(card);
    }
  }
  function restore(view){if(!view)return;for(const detail of el('variable-content').querySelectorAll('details'))detail.open=view.open?.includes(detail.dataset.key)||false;el('variables-panel').scrollTop=view.scroll||0;el('variable-types').scrollTop=view.side||0;}
  async function refresh(category,{switching=false,force=false}={}){
    const ticket=++generation;
    if(switching){remember();catalog=null;stamp='';el('variable-types').replaceChildren();el('variable-content').replaceChildren();status('正在读取变量…');}
    try{
      const data=await call('list',category);if(ticket!==generation||category!==el('variable-project').value)return;
      const next=JSON.stringify(data), changed=stamp!==next;
      if(changed||force){
        if(!switching)remember();const view=views.get(category);catalog=data;stamp=next;
        if(switching){selected=view?.selected||data.dimensions[0]?.id;el('variable-search').value=view?.search||'';el('variable-role').value=view?.role||'';el('variable-filter').value=view?.filter||'';}
        render();restore(view);
      }
      status(`当前版本 ${data.revision} · ${data.dimensions.length} 个变量类型 · 只读展示 · 页面可见时每 5 秒检查更新`);
    }catch(error){if(ticket===generation)status(`读取失败：${error.message}；可点击刷新重试`,true);}
  }
  async function projects(){if(!projectsPromise)projectsPromise=call('projects','road_rescue').then(rows=>{for(const p of rows){const option=node('option',p.name);option.value=p.id;el('variable-project').append(option);}}).catch(e=>{projectsPromise=null;throw e;});return projectsPromise;}
  function mode(value){
    const page=typeof value==='boolean'?(value?'prompts':'batch'):value;window.dashboardPage=page;const variables=page==='prompts',postprocess=page==='postprocess',triptych=page==='triptych';
    document.body.classList.toggle('variables-mode',variables);document.body.classList.toggle('postprocess-mode',postprocess);
    el('gallery-panel').hidden=false;el('variables-panel').hidden=!variables;el('variable-types').hidden=!variables;el('triptych-panel').hidden=!triptych;
    el('task-batch-list').hidden=variables||triptych;el('triptych-task-list').hidden=!triptych;el('task-new').hidden=page!=='batch';el('triptych-new').hidden=!triptych;
    document.querySelector('.content-toolbar').hidden=page!=='batch';document.querySelector('.content-scroll').hidden=page!=='batch';
    el('gallery-page').classList.toggle('selected',page==='batch');el('variables-page').classList.toggle('selected',variables);el('postprocess-page').classList.toggle('selected',postprocess);el('triptych-page').classList.toggle('selected',triptych);
    window.dashboardPostprocessMode?.(page);window.dashboardTriptychMode?.(triptych);
  }
  window.dashboardSetPage=mode;
  el('gallery-page').onclick=()=>{remember();mode(false);};
  el('variables-page').onclick=async()=>{
    mode(true);
    try{await projects();el('variable-project').value=activeProject;await refresh(activeProject,{switching:catalog?.category_id!==activeProject});}catch(e){status(e.message,true);}
  };
  window.addEventListener('dashboard-project',e=>{remember();activeProject=e.detail;el('variable-project').value=activeProject;generation++;mode(window.dashboardPage||'batch');});
  window.addEventListener('dashboard-refresh',e=>{activeProject=e.detail;});
  el('variable-project').onchange=()=>refresh(el('variable-project').value,{switching:true});
  for(const id of ['variable-search','variable-role','variable-filter'])el(id)[id==='variable-search'?'oninput':'onchange']=()=>{if(catalog){render();remember();}};
  el('variable-reload').onclick=()=>refresh(el('variable-project').value,{switching:catalog?.category_id!==el('variable-project').value,force:true});
  setInterval(async()=>{if(pollBusy||el('variables-panel').hidden||document.hidden||document.body.classList.contains('compact')||!catalog)return;pollBusy=true;try{await refresh(el('variable-project').value);}finally{pollBusy=false;}},5000);
})();
