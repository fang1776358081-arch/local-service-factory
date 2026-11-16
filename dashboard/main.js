const { app, BrowserWindow, dialog, ipcMain, Notification, shell, screen } = require('electron');
const fs = require('fs');
const path = require('path');
const applicationIcon = path.join(__dirname,'branding','logo.png');
const { inspectJob, summarizeJob } = require('./monitor');
const { runVariables } = require('./variables');
const { runTasks, readLibraryJobs, hasActiveNativeTasks } = require('./tasks');
const triptych = require('./triptych');
const {
  buildCompletionNotification,
  markNotificationSent,
  notificationWasSent,
} = require('./notifications');
const {
  buildDeliveryGallery,
  loadSessionJob,
  readDashboardDeliveryState,
  readDashboardSession,
} = require('./session');

// A portable GUI build can outlive the terminal that launched it. In that case
// Electron/Node may try to write diagnostics to a closed stdout/stderr pipe and
// raise EPIPE. The dashboard must keep running because this is only a logging
// transport failure, not an application or generation failure.
for (const stream of [process.stdout, process.stderr]) {
  if (stream && typeof stream.on === 'function') {
    stream.on('error', (error) => {
      if (error?.code !== 'EPIPE') throw error;
    });
  }
}
for (const method of ['log', 'info', 'warn', 'error']) {
  const original = console[method].bind(console);
  console[method] = (...args) => {
    try { original(...args); } catch (error) { if (error?.code !== 'EPIPE') throw error; }
  };
}

let projectRoot = null;
let updateService = null;
let compactMode = process.env.ROAD_RESCUE_DASHBOARD_COMPACT === '1' || process.argv.includes('--compact');
const testShellMode = process.env.ROAD_RESCUE_DASHBOARD_TEST === '1';
let mainWindow = null;
let viewerWindow = null;
let viewerImages = [];
let viewerIndex = 0;

function isProjectRoot(candidate) {
  return candidate && fs.existsSync(require('./backend').entry(candidate)) && fs.existsSync(path.join(candidate, 'output'));
}

function findProjectRoot() {
  const candidates = [
    process.env.ROAD_RESCUE_FACTORY_HOME,
    process.env.PORTABLE_EXECUTABLE_DIR,
    process.cwd(),
    path.dirname(process.execPath),
    path.resolve(__dirname, '..'),
    path.resolve(__dirname, '../..'),
  ].filter(Boolean);
  for (const candidate of candidates) {
    let current = path.resolve(candidate);
    for (let depth = 0; depth < 4; depth += 1) {
      if (isProjectRoot(current)) return current;
      const parent = path.dirname(current);
      if (parent === current) break;
      current = parent;
    }
  }
  return null;
}

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')); } catch { return null; }
}

function readEnvValues(file) {
  if (!fs.existsSync(file)) return {};
  const values = {};
  for (const rawLine of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#') || !line.includes('=')) continue;
    const index = line.indexOf('=');
    const name = line.slice(0, index).trim();
    let value = line.slice(index + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    values[name] = value;
  }
  return values;
}

function configuredKeySlots() {
  const values = readEnvValues(path.join(projectRoot, '.env'));
  const keys=[];const names=Object.keys(values).filter(n=>/^OPENAI_API_KEY(?:_\d+)?$/.test(n)).sort((a,b)=>(a==='OPENAI_API_KEY'?1:Number(a.split('_').pop()))-(b==='OPENAI_API_KEY'?1:Number(b.split('_').pop())));
  for(const n of names)if(values[n]&&!keys.includes(values[n]))keys.push(values[n]);
  for(const v of (values.OPENAI_API_KEYS||'').split(/[\s,;]+/))if(v&&!keys.includes(v))keys.push(v);
  return keys.map((_,i)=>i+1);
}

function readDashboardJobs() {
  const files = [];
  const legacy = path.join(projectRoot, '.runtime', 'jobs');
  if (fs.existsSync(legacy)) {
    for (const name of fs.readdirSync(legacy)) {
      if (name.endsWith('.json')) files.push(path.join(legacy, name));
    }
  }
  const categoryRoot = path.join(projectRoot, 'prompts', 'category_batches');
  if (fs.existsSync(categoryRoot)) {
    for (const category of fs.readdirSync(categoryRoot, { withFileTypes: true })) {
      if (!category.isDirectory()) continue;
      const categoryDir = path.join(categoryRoot, category.name);
      for (const batch of fs.readdirSync(categoryDir, { withFileTypes: true })) {
        if (!batch.isDirectory()) continue;
        const jobsDir = path.join(categoryDir, batch.name, 'production', 'jobs');
        if (!fs.existsSync(jobsDir)) continue;
        for (const name of fs.readdirSync(jobsDir)) {
          if (name.endsWith('.json')) files.push(path.join(jobsDir, name));
        }
      }
    }
  }
  return files.map((file) => readJson(file))
    .filter((job) => job?.job_id && Number(job.requested_count) > 0)
    .sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
}

function readDashboard() {
  if (!isProjectRoot(projectRoot)) return { connected: false, projectRoot };
  const session = readDashboardSession(projectRoot);
  const deliveryState = readDashboardDeliveryState(projectRoot);
  const sessionJob = loadSessionJob(projectRoot, session);
  const jobs = [...readDashboardJobs(), ...readLibraryJobs(projectRoot)].sort((a,b)=>String(b.updated_at||'').localeCompare(String(a.updated_at||''))); 
  const monitoredJobs = jobs.map((job) => ({ job, monitor: inspectJob(job, projectRoot) }));
  const activeJobs = monitoredJobs
    .filter(({ monitor }) => monitor.claimedActive && monitor.processAlive === true)
    .map(({ job }) => job);
  const latestLibrary = jobs.find(job=>job.job_type==='shared-task');
  const selectedJob = latestLibrary && (!sessionJob || latestLibrary.created_at > sessionJob.created_at) ? latestLibrary : sessionJob;
  const jobSummary = selectedJob
    ? { ...summarizeJob(selectedJob, projectRoot), activeCount: activeJobs.length }
    : null;
  const slotJobs = new Map();
  for (const job of activeJobs) {
    const slots = Array.isArray(job.api_key_slots) && job.api_key_slots.length ? job.api_key_slots : [1];
    for (const slot of slots) slotJobs.set(Number(slot), job);
  }
  const keyPool = configuredKeySlots().map((slot) => {
    const job = slotJobs.get(slot);
    return { slot, status: job ? 'busy' : 'idle', jobId: job?.job_id || null,
      groupStart: job?.group_start || null, groupCount: job?.group_count || null,
      completed: Number(job?.completed || 0), requested: Number(job?.requested_count || 0) };
  });
  const usedSlots=new Set();
  const slotRoot=path.join(projectRoot,'.runtime','api-slots');
  if(fs.existsSync(slotRoot))for(const name of fs.readdirSync(slotRoot)){const match=name.match(/^slot-(\d+)\.lock$/);if(!match)continue;const row=readJson(path.join(slotRoot,name));if(activeJobs.some(j=>Number(j.pid)===Number(row?.pid)))usedSlots.add(Number(match[1]));}
  for(const job of activeJobs.filter(j=>j.job_type!=='shared-task'))for(const slot of job.api_key_slots||[1])usedSlots.add(slot);
  const concurrency={current:usedSlots.size,limit:keyPool.length};
  const projectRegistry = require('./installed-runtime').registry(projectRoot);
  const pendingProjectIds = Object.entries(deliveryState.projects || {})
    .filter(([, project]) => Object.keys(project?.pending_groups || {}).length > 0)
    .map(([projectId]) => projectId);
  const focusProjectId = String(
    selectedJob?.project_id || selectedJob?.category_id || pendingProjectIds[0]
    || session.project_id || 'road_rescue'
  );
  const projects = projectRegistry.projects || [];
  const gallery = buildDeliveryGallery(projectRoot, deliveryState, selectedJob);
  return {
    connected: true,
    projectRoot,
    images: gallery.images,
    jobs: selectedJob ? [selectedJob] : [],
    jobSummary,
    keyPool,
    concurrency,
    projects,
    groups: gallery.groups,
    session,
    deliveryState,
    focusProjectId,
    refreshedAt: new Date().toISOString(),
  };
}

function showCompletionNotification(data) {
  if (testShellMode || !projectRoot) return;
  const notice = buildCompletionNotification(data?.jobSummary);
  if (!notice || notificationWasSent(projectRoot, notice.jobId)) return;
  try {
    if (Notification.isSupported()) {
      const notification = new Notification({
        title: notice.title,
        body: notice.body,
        silent: false,
      });
      notification.on('click', () => {
        if (!mainWindow || mainWindow.isDestroyed()) return;
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.show();
        mainWindow.focus();
      });
      notification.show();
    }
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.flashFrame(true);
    markNotificationSent(projectRoot, notice);
  } catch (error) {
    console.warn('Dashboard completion notification failed:', error);
  }
}

function readDashboardAndNotify() {
  const data = readDashboard();
  showCompletionNotification(data);
  return data;
}

function createWindow() {
  const win = new BrowserWindow({
    width: compactMode ? 440 : 1040, height: compactMode ? 38 : 720,
    minWidth: compactMode ? 440 : 820, minHeight: compactMode ? 38 : 560,
    backgroundColor: '#0c0d0e', title: '', icon: applicationIcon,
    autoHideMenuBar: true, frame: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  mainWindow = win;
  win.setResizable(!compactMode);
  win.setAlwaysOnTop(compactMode, compactMode ? 'floating' : 'normal');
  const notifyMaximized=()=>win.webContents.send('window:maximized-changed',win.isMaximized());
  win.on('maximize',notifyMaximized);win.on('unmaximize',notifyMaximized);
  win.webContents.on('did-finish-load',notifyMaximized);
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event) => event.preventDefault());
  win.on('focus', () => win.flashFrame(false));
  win.on('closed', () => { mainWindow = null; });
  return win;
}

function applyCompact(target, desired) {
  compactMode = desired;
  target.setMinimumSize(compactMode ? 440 : 820, compactMode ? 38 : 560);
  target.setSize(compactMode ? 440 : 1040, compactMode ? 38 : 720, true);
  target.setResizable(!compactMode);
  target.setAlwaysOnTop(compactMode, compactMode ? 'floating' : 'normal');
  target.webContents.send('window:compact-changed', compactMode);
  return compactMode;
}

function viewerPayload() {
  const image = viewerImages[viewerIndex];
  if(image&&fs.existsSync(image.path)){const stat=fs.statSync(image.path);image.url=require('url').pathToFileURL(image.path).href+'?v='+stat.mtimeMs+'-'+stat.size;}
  return image ? { ...image, historyRequest:{category:image.projectId,batch:(image.path.match(/[\\/]library[\\/](batch_[a-zA-Z0-9_-]+)/)||[])[1]||'legacy',group:image.groupIndex,position:image.position}, index: viewerIndex, count: viewerImages.length } : null;
}

function openViewer(parent, index) {
  const data = readDashboard();
  viewerImages = data.images || [];
  viewerIndex = Math.max(0, Math.min(Number(index) || 0, viewerImages.length - 1));
  if (!viewerImages.length) return null;
  if (viewerWindow && !viewerWindow.isDestroyed()) {
    viewerWindow.show();
    viewerWindow.focus();
    viewerWindow.webContents.send('viewer:updated', viewerPayload());
    return viewerPayload();
  }
  const display = screen.getDisplayMatching(parent.getBounds());
  const area = display.workArea;
  const width = Math.max(420, Math.round(area.width * 0.9));
  const height = Math.max(320, Math.round(area.height * 0.9));
  const x = area.x + Math.round((area.width - width) / 2);
  const y = area.y + Math.round((area.height - height) / 2);
  viewerWindow = new BrowserWindow({
    parent, x, y, width, height, minWidth: 420, minHeight: 320,
    frame: false, backgroundColor: '#050605', show: false, icon: applicationIcon,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  viewerWindow.loadFile(path.join(__dirname, 'renderer', 'viewer.html'));
  viewerWindow.once('ready-to-show', () => viewerWindow.show());
  viewerWindow.on('closed', () => { viewerWindow = null; });
  return viewerPayload();
}

if (testShellMode) {
  const base = process.env.ROAD_RESCUE_FACTORY_HOME || process.cwd();
  app.setPath('userData', path.join(base, '.runtime', 'dashboard-test-shell'));
}
const singleInstance = testShellMode || app.requestSingleInstanceLock();
if (!singleInstance) {
  app.quit();
} else {
  app.on('second-instance', (_, argv) => {
    if (!mainWindow) return;
    if (argv.includes('--compact')) applyCompact(mainWindow, true);
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
}

app.whenReady().then(() => {
  if (process.platform === 'win32') app.setAppUserModelId('local.roadrescue.dashboard');
  projectRoot = app.isPackaged ? require('./installed-runtime').initialize(app) : findProjectRoot();
  if(projectRoot){
    updateService=require('./update-service').createService({app,root:projectRoot,hasActiveTasks:()=>hasActiveNativeTasks(projectRoot)||[...readDashboardJobs(),...readLibraryJobs(projectRoot)].some(j=>{const m=inspectJob(j,projectRoot);return m.claimedActive&&m.processAlive!==false;})});
    if(!testShellMode)updateService.start();
  }
  ipcMain.handle('updates:request',(_,operation)=>{
    if(!updateService||!['status','check','syncRules'].includes(operation))throw Error('更新操作不可用');
    return updateService[operation]();
  });
  ipcMain.handle('dashboard:read', () => readDashboardAndNotify());
  ipcMain.handle('tasks:request', (_, operation, request) => {
    if(['native-register','native-ingest','native-materialize'].includes(operation))throw Error('请使用待回填单元的文件导入入口');
    if(request?.image_path||request?.destination)throw Error('请使用对应的文件选择操作');
    if(['assets-save','package','open-folder'].includes(operation))throw Error('请使用对应的目录选择操作');
    return runTasks(projectRoot, operation, request);
  });
  ipcMain.handle('tasks:native-import',async(event,request)=>{
    const binding={category:request.category,batch:request.batch,instance_id:request.instance_id,scope:request.scope,unit:request.unit,claim:request.claim};
    const state=await runTasks(projectRoot,'native-status',binding),unit=state.units[binding.unit];
    if(state.cancelled||!unit||unit.scope!==binding.scope||unit.claim!==binding.claim||!['awaiting_result','uncertain'].includes(unit.status))throw Error('该单元没有待回填的内置调用，请先在 Codex 核对');
    const selected=await dialog.showOpenDialog(BrowserWindow.fromWebContents(event.sender),{title:'选择该单元已返回并手动保存的图片（不是自动回填）',properties:['openFile'],filters:[{name:'图片',extensions:['png','jpg','jpeg','webp']}]});
    if(selected.canceled)return null;
    const file=selected.filePaths[0];if(fs.statSync(file).size>64*1024*1024)throw Error('图片超过 64MB');
    const payload=fs.readFileSync(file);if(payload.length>64*1024*1024)throw Error('图片超过 64MB');
    const sha256=require('crypto').createHash('sha256').update(payload).digest('hex');
    await runTasks(projectRoot,'native-register',{...binding,file,sha256,source_kind:unit.result?.source_kind||'manual_saved',tool_result_id:unit.result?.tool_result_id,synthetic:unit.result?.synthetic??testShellMode,handoff:'manual_saved'});
    await runTasks(projectRoot,'native-ingest',binding);
    return runTasks(projectRoot,'native-materialize',binding);
  });
  ipcMain.handle('postprocess:import',async(event,request)=>{
    const result=await dialog.showOpenDialog(BrowserWindow.fromWebContents(event.sender),{title:'选择后处理原图',properties:['openFile'],filters:[{name:'图片',extensions:['png','jpg','jpeg','webp']}]});
    if(result.canceled)return null;
    return runTasks(projectRoot,'postprocess-session',{category:request.category,batch:request.batch,kind:request.kind,image_path:result.filePaths[0]});
  });
  ipcMain.handle('postprocess:export',async(event,request)=>{
    const result=await dialog.showSaveDialog(BrowserWindow.fromWebContents(event.sender),{title:'保存后处理成品',defaultPath:'后处理成品.png',filters:[{name:'PNG 图片',extensions:['png']}]});
    if(result.canceled)return null;
    return runTasks(projectRoot,'postprocess-preview-apply',{category:request.category,session:request.session,preview:request.preview,destination:result.filePath});
  });
  ipcMain.handle('assets:choose', async () => {
    const current=await runTasks(projectRoot,'assets-view');
    const result=await dialog.showOpenDialog({title:'选择资产路径（用于新批次，已有批次保留原位置）',defaultPath:current.path,properties:['openDirectory','createDirectory']});
    if(result.canceled)return null;
    return runTasks(projectRoot,'assets-save',{path:result.filePaths[0]});
  });
  ipcMain.handle('assets:open', async (_,request) => {
    const result=await runTasks(projectRoot,'open-folder',request);
    const error=await shell.openPath(result.path);if(error)throw Error(error);return result;
  });
  ipcMain.handle('raw-library:open',async(_,request)=>{
    const result=await runTasks(projectRoot,'raw-library-folder',{category:request.category,root_id:request.root_id});
    const error=await shell.openPath(result.path);if(error)throw Error(error);return result;
  });
  ipcMain.handle('assets:package', async (_,request) => {
    const result=await dialog.showOpenDialog({title:'选择压缩包保存位置',properties:['openDirectory','createDirectory']});
    if(result.canceled)return null;
    return runTasks(projectRoot,'package',{...request,destination:result.filePaths[0]});
  });
  ipcMain.handle('variables:request', (_, request) => runVariables(projectRoot, request));
  ipcMain.handle('triptych:request', (_, operation, request = {}) => {
    if (!projectRoot) throw Error('尚未连接项目目录');
    if (request?.source || request?.destination || request?.directory) throw Error('三连屏文件路径必须通过系统选择窗口');
    return triptych.request(projectRoot, operation, request);
  });
  ipcMain.handle('triptych:import', async (event, request) => {
    if (!projectRoot) throw Error('尚未连接项目目录');
    const result = await dialog.showOpenDialog(BrowserWindow.fromWebContents(event.sender), {
      title: `选择第 ${Number(request?.group) || ''} 组横幅母图`,
      properties: ['openFile'],
      filters: [{ name: '图片', extensions: ['png', 'jpg', 'jpeg', 'webp'] }],
    });
    if (result.canceled) return null;
    return triptych.compose(projectRoot, { taskId: request.taskId, group: request.group, source: result.filePaths[0] });
  });
  ipcMain.handle('triptych:package', async (event, request) => {
    if (!projectRoot) throw Error('尚未连接项目目录');
    const result = await dialog.showOpenDialog(BrowserWindow.fromWebContents(event.sender), {
      title: '选择三连屏压缩包保存位置', properties: ['openDirectory', 'createDirectory'],
    });
    if (result.canceled) return null;
    return triptych.packageTask(projectRoot, { taskId: request.taskId, destination: result.filePaths[0] });
  });
  ipcMain.handle('triptych:open', async (_, request) => {
    if (!projectRoot) throw Error('尚未连接项目目录');
    const directory = triptych.taskDirectory(projectRoot, request?.taskId);
    const error = await shell.openPath(directory);
    if (error) throw Error(error);
    return { directory };
  });
  ipcMain.handle('project:choose', async () => {
    if(app.isPackaged)return readDashboardAndNotify();
    const result = await dialog.showOpenDialog({ properties: ['openDirectory'], title: '选择 road_rescue_image_factory 文件夹' });
    if (!result.canceled && isProjectRoot(result.filePaths[0])) {
      projectRoot = result.filePaths[0];updateService?.stop();
      updateService=require('./update-service').createService({app,root:projectRoot,hasActiveTasks:()=>hasActiveNativeTasks(projectRoot)||[...readDashboardJobs(),...readLibraryJobs(projectRoot)].some(j=>{const m=inspectJob(j,projectRoot);return m.claimedActive&&m.processAlive!==false;})});
      if(!testShellMode)updateService.start();
    }
    return readDashboardAndNotify();
  });
  ipcMain.handle('path:open', (_, target) => {
    if (!projectRoot || !require('./assets').allowed(projectRoot,target)) return false;
    shell.showItemInFolder(target);
    return true;
  });
  ipcMain.handle('window:compact', (event) => {
    const target = BrowserWindow.fromWebContents(event.sender);
    return applyCompact(target, !compactMode);
  });
  ipcMain.handle('window:is-compact', () => compactMode);
  ipcMain.handle('window:minimize', (event) => BrowserWindow.fromWebContents(event.sender).minimize());
  ipcMain.handle('window:maximize', (event) => {
    const target = BrowserWindow.fromWebContents(event.sender);
    if (target.isMaximized()) target.unmaximize(); else target.maximize();
    return target.isMaximized();
  });
  ipcMain.handle('window:close', (event) => BrowserWindow.fromWebContents(event.sender).close());
  ipcMain.handle('viewer:open', (event, index) => openViewer(BrowserWindow.fromWebContents(event.sender), index));
  ipcMain.handle('viewer:current', () => viewerPayload());
  ipcMain.handle('viewer:navigate', (_, delta) => {
    if (!viewerImages.length) return null;
    viewerIndex = (viewerIndex + Number(delta) + viewerImages.length) % viewerImages.length;
    const payload = viewerPayload();
    if (viewerWindow && !viewerWindow.isDestroyed()) viewerWindow.webContents.send('viewer:updated', payload);
    return payload;
  });
  ipcMain.handle('viewer:close', (event) => BrowserWindow.fromWebContents(event.sender).close());
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
