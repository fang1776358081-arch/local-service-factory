const fs = require('fs');
const path = require('path');
const { randomInt } = require('crypto');
const { spawn } = require('child_process');
const { pathToFileURL } = require('url');
const backend = require('./backend');

const TASK_ID = /^\d{8}T\d{12}Z$/;
const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.webp']);
const STORE_NAME_PREFIXES = ['安途', '畅途', '顺途', '路安', '路畅', '远途', '驰援', '护航', '通途', '行安', '车安', '途顺', '路顺', '安行', '畅行', '佳途', '诚途', '联途', '宏途', '众途'];
const STORE_NAME_SUFFIXES = ['道路救援', '汽车救援服务部', '车辆救援', '道路救援服务部', '汽车道路救援'];

function inside(parent, file) {
  const relative = path.relative(path.resolve(parent), path.resolve(file));
  return !relative || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

function taskHome(root) {
  return path.resolve(root, 'output', 'road_rescue_pinned');
}

function taskDirectory(root, taskId) {
  if (!TASK_ID.test(String(taskId || ''))) throw Error('三连屏任务编号无效');
  const home = taskHome(root);
  const directory = path.resolve(home, taskId);
  if (!inside(home, directory)) throw Error('三连屏任务路径越界');
  return directory;
}

function readTask(root, taskId) {
  const directory = taskDirectory(root, taskId);
  const file = path.join(directory, 'task.json');
  const stat = fs.statSync(file);
  if (!stat.isFile() || stat.size > 4 * 1024 * 1024) throw Error('三连屏任务记录无效');
  const task = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
  if (task.task_id !== taskId || task.category !== 'road_rescue' || !Array.isArray(task.groups)) {
    throw Error('三连屏任务身份不一致');
  }
  return { directory, task, stat };
}

function groupState(task, group) {
  const requests = (task.requests || []).filter((request) => Number(request.group) === Number(group.index));
  const unresolved = [...requests].reverse().find((request) => request.status === 'requesting');
  return {
    requests: requests.length,
    unresolved: Boolean(unresolved),
    attempt: unresolved?.attempt || requests.length,
    canClaim: group.status !== 'composed' && !unresolved
      && requests.length < 2 && (task.requests || []).length < Number(task.max_requests || 0),
    canImport: group.status !== 'composed' && Boolean(unresolved),
  };
}

function taskSummary(task, stat) {
  const groups = task.groups || [];
  const composed = groups.filter((group) => group.status === 'composed').length;
  const pendingImport = groups.filter((group) => groupState(task, group).unresolved).length;
  return {
    taskId: task.task_id,
    phone: task.phone,
    count: Number(task.count || groups.length),
    status: task.status,
    composed,
    pendingImport,
    storeName: task.store_identity?.name || (task.identity_mode === 'per_group' ? '每组不同店名' : ''),
    updatedAt: stat.mtime.toISOString(),
    packageVerified: task.package_verified === true,
  };
}

function list(root) {
  const home = taskHome(root);
  if (!fs.existsSync(home)) return [];
  return fs.readdirSync(home, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && TASK_ID.test(entry.name))
    .sort((left, right) => right.name.localeCompare(left.name))
    .slice(0, 100)
    .flatMap((entry) => {
      try {
        const { task, stat } = readTask(root, entry.name);
        return [taskSummary(task, stat)];
      } catch { return []; }
    });
}

function detail(root, taskId) {
  const { directory, task, stat } = readTask(root, taskId);
  const groups = task.groups.map((group) => {
    const state = groupState(task, group);
    const groupDirectory = path.join(directory, `group_${String(group.index).padStart(2, '0')}`);
    const preview = path.join(groupDirectory, 'preview.jpg');
    let previewUrl = null;
    if (inside(directory, preview) && fs.existsSync(preview)) {
      const previewStat = fs.statSync(preview);
      previewUrl = `${pathToFileURL(preview).href}?v=${previewStat.mtimeMs}-${previewStat.size}`;
    }
    return {
      index: Number(group.index),
      status: group.status,
      storeName: group.store_identity?.name || '',
      prompt: String(group.prompt || ''),
      visualReview: group.visual_review || null,
      previewUrl,
      ...state,
    };
  });
  return {
    ...taskSummary(task, stat),
    directory,
    styleStart: Number(task.style_start || 0),
    maxRequests: Number(task.max_requests || 0),
    requestsUsed: (task.requests || []).length,
    allComposed: groups.length > 0 && groups.every((group) => group.status === 'composed'),
    groups,
  };
}

function validatePrepare(request) {
  if (!request || typeof request !== 'object' || Array.isArray(request)) throw Error('三连屏创建参数无效');
  const phone = String(request.phone || '').trim();
  const storeName = String(request.storeName || '').trim();
  const count = Number(request.count);
  const styleStart = Number(request.styleStart || 0);
  if (!/^1[3-9][0-9]{9}$/.test(phone)) throw Error('请输入正确的11位手机号');
  if (!Number.isInteger(count) || count < 1 || count > 100) throw Error('组数必须是1到100');
  if (!Number.isInteger(styleStart) || styleStart < 0 || styleStart > 1000000) throw Error('样式起点无效');
  if (request.confirm !== true) throw Error('请先确认创建本地任务不会自动生图');
  if (request.randomStoreNames === true) {
    return { phone, storeNames: randomStoreNames(count), count, styleStart, fictionalName: true };
  }
  if (!/^[\u3400-\u9fffA-Za-z0-9·（）() -]{2,24}$/.test(storeName) || /\d{7}/.test(storeName)) throw Error('店名应为2到24个普通字符且不能包含电话号码');
  return { phone, storeName, count, styleStart, fictionalName: request.fictionalName === true };
}

function randomStoreNames(count) {
  if (!Number.isInteger(count) || count < 1 || count > 100) throw Error('随机店名数量必须是1到100');
  const names = STORE_NAME_PREFIXES.flatMap(prefix => STORE_NAME_SUFFIXES.map(suffix => prefix + suffix));
  for (let index = names.length - 1; index > 0; index -= 1) {
    const selected = randomInt(index + 1);
    [names[index], names[selected]] = [names[selected], names[index]];
  }
  return names.slice(0, count);
}

function runCommand(root, args, { timeout = 60000 } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(backend.python(), ['-X', 'utf8', backend.entry(root), 'pinned-triptych', ...args], {
      cwd: root,
      windowsHide: true,
      shell: false,
      env: { ...process.env, FACTORY_DATA_HOME: root, PYTHONIOENCODING: 'utf-8' },
    });
    let output = '';
    let errors = '';
    let settled = false;
    const done = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error); else resolve(value);
    };
    const timer = setTimeout(() => {
      child.kill();
      done(Error('三连屏本地操作超时，请刷新后检查磁盘状态'));
    }, timeout);
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      output += chunk;
      if (output.length > 4 * 1024 * 1024) done(Error('三连屏本地操作结果过大'));
    });
    child.stderr.on('data', (chunk) => { errors = (errors + chunk).slice(-1200); });
    child.on('error', (error) => done(Error(`无法运行三连屏工具：${error.message}`)));
    child.on('close', (code) => {
      if (settled) return;
      if (code !== 0) return done(Error(errors.trim() || output.trim() || `三连屏工具退出码 ${code}`));
      const text = output.trim();
      try { done(null, { text, json: text ? JSON.parse(text) : null }); }
      catch { done(null, { text, json: null }); }
    });
  });
}

async function prepare(root, request) {
  const value = validatePrepare(request);
  const args = ['prepare', '--phone', value.phone, '--count', String(value.count),
    '--style-start', String(value.styleStart), '--authorization', 'dashboard_explicit_confirmation'];
  for (const name of value.storeNames || [value.storeName]) args.push('--store-name', name);
  args.push('--confirm');
  if (value.fictionalName) args.push('--fictional-name');
  const result = await runCommand(root, args);
  const directory = path.resolve(String(result.json?.job_dir || ''));
  const home = taskHome(root);
  if (!inside(home, directory) || !TASK_ID.test(path.basename(directory))) throw Error('三连屏工具返回了无效任务目录');
  return detail(root, path.basename(directory));
}

async function claim(root, request) {
  const directory = taskDirectory(root, request.taskId);
  const group = Number(request.group);
  if (!Number.isInteger(group) || group < 1 || group > 100) throw Error('三连屏组号无效');
  const before = detail(root, request.taskId).groups.find((item) => item.index === group);
  if (!before || !before.canClaim) throw Error('本组当前不能领取新的生成请求');
  const result = await runCommand(root, ['claim', '--job-dir', directory, '--group', String(group)]);
  return { prompt: result.text, task: detail(root, request.taskId) };
}

async function compose(root, request) {
  const directory = taskDirectory(root, request.taskId);
  const group = Number(request.group);
  const source = path.resolve(String(request.source || ''));
  if (!Number.isInteger(group) || group < 1 || group > 100) throw Error('三连屏组号无效');
  if (!fs.existsSync(source) || !fs.statSync(source).isFile() || !IMAGE_EXTENSIONS.has(path.extname(source).toLowerCase())) throw Error('请选择有效的PNG、JPG或WEBP母图');
  if (fs.statSync(source).size > 64 * 1024 * 1024) throw Error('母图超过64MB');
  const before = detail(root, request.taskId).groups.find((item) => item.index === group);
  if (!before?.canImport) throw Error('本组没有已领取、待导入的生成请求');
  await runCommand(root, ['compose', '--job-dir', directory, '--group', String(group), '--source', source], { timeout: 120000 });
  return detail(root, request.taskId);
}

async function packageTask(root, request) {
  const directory = taskDirectory(root, request.taskId);
  const destination = path.resolve(String(request.destination || ''));
  if (!fs.existsSync(destination) || !fs.statSync(destination).isDirectory()) throw Error('压缩包保存目录无效');
  const current = detail(root, request.taskId);
  if (!current.allComposed) throw Error('全部组完成后才能打包');
  const result = await runCommand(root, ['package', '--job-dir', directory, '--destination', destination], { timeout: 600000 });
  return { result: result.json, task: detail(root, request.taskId) };
}

async function request(root, operation, payload = {}) {
  if (operation === 'list') return list(root);
  if (operation === 'detail') return detail(root, payload.taskId);
  if (operation === 'prepare') return prepare(root, payload);
  if (operation === 'claim') return claim(root, payload);
  throw Error('不支持的三连屏操作');
}

module.exports = {
  TASK_ID,
  compose,
  detail,
  list,
  packageTask,
  request,
  taskDirectory,
  validatePrepare,
  randomStoreNames,
};
