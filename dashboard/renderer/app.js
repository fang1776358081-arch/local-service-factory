const $ = (id) => document.getElementById(id);

let currentData = null;
let selectedProject = 'road_rescue';
let projectChosenByUser = false;

const statusText = {
  queued: '排队中',
  starting: '启动中',
  running: '运行中',
  recovering: '自动补齐中',
  waiting_for_api: '生成中',
  completed: '已完成',
  completed_with_errors: '执行已停止 · 原图待完成',
  awaiting_review: '待人工验收',
  failed: '失败',
  stopped_unexpectedly: '生成已停止',
  stopped_for_prompt_update: '已暂停',
};

const healthText = {
  live: '正在生成',
  stale: '长时间无更新',
  dead: '生成已停止',
  finished: '已完成',
  failed: '任务失败',
  idle: '空闲',
};

const partialTask = job => (job?.rawStatus || job?.status) === 'completed_with_errors';
const taskStateText = job => job?.health==='finished' ? '最近任务已完成' : (job?.rawStatus || job?.status)==='recovering' ? '自动补齐中' : partialTask(job) ? statusText.completed_with_errors : (healthText[job.health] || statusText[job.status] || job.status);

const formatTime = (iso) => (
  iso ? new Date(iso).toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' }) : '--'
);

const formatDateTime = (iso) => (
  iso ? new Date(iso).toLocaleString('zh-CN', { hour12: false }) : '--'
);

function formatAge(seconds) {
  if (!Number.isFinite(Number(seconds))) return '未知';
  const value = Math.max(0, Number(seconds));
  if (value < 60) return `${Math.floor(value)} 秒前`;
  if (value < 3600) return `${Math.floor(value / 60)} 分钟前`;
  if (value < 86400) return `${Math.floor(value / 3600)} 小时前`;
  return `${Math.floor(value / 86400)} 天前`;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function projectName(projects, projectId) {
  return projects.find((project) => project.id === projectId)?.name || projectId;
}

function renderProjectTabs(data) {
  const projects = data.projects || [];
  if (!projects.some((project) => project.id === selectedProject)) {
    selectedProject = projects[0]?.id || selectedProject;
  }
  $('project-tabs').innerHTML = projects.map((project) => {
    const active = project.id === selectedProject ? ' active' : '';
    return `<button class="project-tab${active}" data-project="${escapeHtml(project.id)}">${escapeHtml(project.name || project.id)}</button>`;
  }).join('');
  document.querySelectorAll('.project-tab').forEach((button) => {
    button.addEventListener('click', () => {
      selectedProject = button.dataset.project;
      projectChosenByUser = true;
      window.dispatchEvent(new CustomEvent('dashboard-project', {detail:selectedProject}));
      render(currentData);
    });
  });
}

function renderSummary(data) {
  const groups = (data.groups || []).filter((group) => group.projectId === selectedProject);
  const complete = groups.filter((group) => group.imageComplete).length;
  const pending = groups.filter((group) => group.imageComplete && !group.textApproved).length;
}

function renderKeyPool(data) {
  const pool = data.keyPool || [];
  $('key-pool').innerHTML = pool.length ? pool.map((key) => {
    const label = key.status === 'busy' ? `生成中 ${key.completed}/${key.requested}` : '空闲';
    return `<span class="${key.status}">Key ${key.slot} ${label}</span>`;
  }).join('') : '<span>未配置号池</span>';
}

function renderMonitor(job) {
  const monitor = $('job-monitor');
  document.body.classList.remove(
    'monitor-live', 'monitor-stale', 'monitor-dead', 'monitor-finished', 'monitor-failed', 'monitor-idle',
  );
  const health = job?.health || 'idle';
  document.body.classList.add(`monitor-${health}`);
  monitor.className = `job-monitor monitor-${health}`;

  if (!job) {
    $('monitor-body').innerHTML = '<div class="monitor-empty"><strong>暂无任务</strong></div>';
    return;
  }

  job=job||{};
  const done = Number(job.completed || 0);
  const total = Number(job.requested_count || 0);
  const remaining = Number.isFinite(Number(job.remaining)) ? Number(job.remaining) : Math.max(0, total - done);
  const failed = Number(job.failed || 0);
  const reusable = job.reusable === null || job.reusable === undefined ? '—' : Number(job.reusable);
  const generated = job.newGenerated === null || job.newGenerated === undefined ? '—' : Number(job.newGenerated);
  const requestsUsed = Number(job.requestsUsed || 0);
  const requestBudget = Number.isFinite(Number(job.requestBudget)) ? Number(job.requestBudget) : null;
  const requestLabel = requestBudget === null ? `${requestsUsed}/—` : `${requestsUsed}/${requestBudget}`;
  const percentage = total > 0 ? Math.max(0, Math.min(100, (done / total) * 100)) : 0;
  const model = [job.model, job.quality, job.size].filter(Boolean).join(' · ');
  const rawState = statusText[job.rawStatus] || job.rawStatus || '--';
  const alerts = {
    live: '生成进程正常，数据每 2 秒自动刷新。',
    stale: '生成进程仍存在，但已经超过 3 分钟没有进度更新。',
    dead: `生成进程已退出；付费生成当前没有继续。进度文件仍停留在“${escapeHtml(rawState)}”。`,
    failed: '任务已经失败，付费生成当前没有继续。',
    finished: partialTask(job) ? '其他图片已处理完毕，失败项已跳过；可在批次中展开待处理原因。' : '任务已经结束。',
    idle: `任务当前状态：${escapeHtml(rawState)}。`,
  };

  $('monitor-body').innerHTML = `
    <div class="monitor-header">
      <div>
        <strong>${escapeHtml(taskStateText(job))}</strong>
        <span>${escapeHtml(job.job_id || '')}</span>
      </div>
      <small>任务记录 · ${escapeHtml(model)}</small>
    </div>
    <div class="monitor-progress"><i style="width:${percentage.toFixed(2)}%"></i></div>
    <div class="monitor-metrics">
      <span><small>完成</small><b>${done}/${total}</b></span>
      <span><small>${partialTask(job) ? '待处理' : '剩余'}</small><b>${remaining}</b></span>
      <span><small>可复用</small><b>${reusable}</b></span>
      <span><small>新生成</small><b>${generated}</b></span>
      <span><small>失败</small><b>${failed}</b></span>
      <span><small>请求</small><b>${requestLabel}</b></span>
      <span class="monitor-updated"><small>最后更新</small><b>${escapeHtml(formatDateTime(job.updated_at))} · ${escapeHtml(formatAge(job.ageSeconds))}</b></span>
    </div>
    <div class="monitor-alert">${alerts[health] || ''}</div>`;
  const header=monitor.querySelector('.monitor-header');
  header.querySelector('span').hidden=true;
  header.querySelector('small').hidden=true;
  const visible=[0,1,4];
  Array.from(monitor.querySelector('.monitor-metrics').children).forEach((item,index)=>{if(!visible.includes(index))item.remove();});
  const alert=monitor.querySelector('.monitor-alert');if(!['stale','dead','failed'].includes(health))alert.textContent='';alert.hidden=!alert.textContent;
}

function groupedImages(data) {
  const groups=new Map(),key=item=>`${item.libraryBatch||'legacy'}:${item.groupIndex}`;
  for(const group of data.groups||[])if(group.projectId===selectedProject&&!group.libraryBatch)groups.set(key(group),{groupIndex:group.groupIndex,libraryBatch:group.libraryBatch,meta:group,items:[]});
  for(const image of data.images||[]){if(image.projectId!==selectedProject||image.libraryBatch)continue;const id=key(image);if(!groups.has(id))groups.set(id,{groupIndex:image.groupIndex,libraryBatch:image.libraryBatch,items:[]});groups.get(id).items.push(image);}
  return [...groups.values()].sort((a,b)=>String(a.libraryBatch||'').localeCompare(String(b.libraryBatch||''))||a.groupIndex-b.groupIndex).map(g=>({...g,items:g.items.sort((a,b)=>a.position-b.position)}));
}

function groupStatusLabel(group) {
  if (!group.meta && !group.items.length) return '未开始';
  if (group.meta?.deliveryReady) return '可交付';
  if (group.meta?.imageComplete) return '待验收';
  const expected = Number(group.meta?.expectedImageCount || 0);
  return expected > 0 ? `${group.items.length}/${expected}` : `本次 ${group.items.length} 张`;
}

let galleryFingerprint = null;
function renderGallery(data) {
  const groups = groupedImages(data);
  const signature=JSON.stringify([selectedProject,groups]);if(signature===galleryFingerprint)return;galleryFingerprint=signature;
  if (!groups.length) {
    $('gallery').innerHTML = '<div class="empty">当前没有待打包交付的图片</div>';
    return;
  }
  $('gallery').innerHTML = groups.map((group) => {
    const thumbs = group.items.map((image) => {
      const index = data.images.findIndex((item) => item.path === image.path);
      const role = image.role === 'cover' ? '首图' : (image.role === 'triptych' ? '三拼图' : `图 ${image.position || ''}`);
      return `<button class="thumb" data-index="${index}" data-position="${image.position}" title="${escapeHtml(image.name)}">
        <img src="${image.url}" loading="lazy">
        <span>${escapeHtml(role)}</span>
      </button>`;
    }).join('');
    return `<section class="group-row" data-group="${group.groupIndex}">
      <div class="group-meta">
        <strong>第 ${group.groupIndex} 组</strong>${group.libraryBatch ? `<small>${escapeHtml(group.libraryBatch)}</small>` : ''}
        <span>${groupStatusLabel(group)}</span>
        <small>${group.items.length ? formatTime(group.items[group.items.length - 1].modified) : '--'}</small>
      </div>
      <div class="group-images">${thumbs || '<span class="group-empty">暂无图片</span>'}</div>
      <details class="legacy-prompts" data-category="${escapeHtml(selectedProject)}" data-group="${group.groupIndex}" data-batch="${escapeHtml(group.libraryBatch||'')}"><summary>查看提示词</summary><div>读取本地提示词…</div></details>
    </section>`;
  }).join('');
  document.querySelectorAll('.legacy-prompts').forEach(details=>{details.ontoggle=()=>{if(details.open&&window.showSavedGroupPrompts)window.showSavedGroupPrompts(details);};});
  document.querySelectorAll('.thumb').forEach((button) => {
    button.addEventListener('click', () => window.roadRescue.openViewer(Number(button.dataset.index)));
  });
}

function render(data) {
  if (!projectChosenByUser && data.focusProjectId && (data.projects || []).some((project) => project.id === data.focusProjectId)) {
    selectedProject = data.focusProjectId;
  }
  currentData = data;window.dashboardData=data;
  if (!data.connected) {
    $('title-state').textContent = '未连接';
    renderMonitor(null);
    return;
  }
  const job = data.jobSummary || data.jobs[0];
  const active = Number(job?.activeCount || 0);
  const state = job ? (active > 1 ? `并行 ${active} 队列` : taskStateText(job)) : '空闲';
  const done = job ? Number(job.completed || 0) : 0;
  const total = job ? Number(job.requested_count || 0) : 0;
  const failed = job ? Number(job.failed || 0) : 0;
  const remaining = job ? (Number.isFinite(Number(job.remaining)) ? Number(job.remaining) : Math.max(0, total - done)) : 0;
  const requestBudget = Number.isFinite(Number(job?.requestBudget)) ? Number(job.requestBudget) : null;
  const requestsUsed = Number(job?.requestsUsed || 0);

  $('title-state').textContent = state;
  $('title-progress').textContent = `${done}/${total}`;
  $('title-images').textContent = `待打包 ${data.images.length}`;

  renderMonitor(job);
  renderProjectTabs(data);
  renderSummary(data);
  $('key-pool').replaceChildren();
  const concurrency=document.createElement('span');concurrency.className='global-concurrency';concurrency.innerHTML=`<small>并发</small><b>${Number(data.concurrency?.current)||0}/${Number(data.concurrency?.limit)||0}</b>`;concurrency.title='当前使用 / 并发上限，上限等于有效去重密钥数量';
  const updated=$('job-monitor').querySelector('.monitor-updated');
  if(updated)updated.before(concurrency);else $('job-monitor').append(concurrency);
  renderGallery(data);
  window.dispatchEvent(new CustomEvent('dashboard-refresh', {detail:selectedProject}));
}

let refreshInFlight = false;

async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    render(await window.roadRescue.read());
  } catch {
    $('title-state').textContent = '读取失败';
  } finally {
    refreshInFlight = false;
  }
}

async function toggleCompact() {
  document.body.classList.toggle('compact', await window.roadRescue.toggleCompact());
}

$('compact-toggle').addEventListener('click', toggleCompact);
document.querySelector('.titlebar').addEventListener('dblclick', () => {
  if (document.body.classList.contains('compact')) toggleCompact();
});
$('window-minimize').addEventListener('click', () => window.roadRescue.minimize());
$('window-maximize').addEventListener('click', () => window.roadRescue.maximize());
$('window-close').addEventListener('click', () => window.roadRescue.close());

refresh();
setInterval(refresh, 2000);
window.roadRescue.isCompact().then((value) => document.body.classList.toggle('compact', value));
window.roadRescue.onCompactChanged((value) => document.body.classList.toggle('compact', value));

window.addEventListener("dashboard-admin-refresh",()=>{galleryFingerprint=null;refresh();});
