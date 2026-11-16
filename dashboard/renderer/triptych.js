(() => {
  const el = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[character]));
  const labels = {
    prepared: '已准备', generating: '生成中', awaiting_visual_review: '待验收',
    prepared_after_feedback: '已按反馈更新', checkpoint_after_failure: '失败后待处理', superseded: '已终止',
  };
  let active = false;
  let busy = false;
  let tasks = [];
  let selected = null;
  let current = null;

  function status(text, error = false) {
    el('triptych-status').textContent = text;
    el('triptych-status').classList.toggle('error', error);
  }

  function taskLabel(task) {
    if (task.packageVerified) return '已打包';
    if (task.composed === task.count) return '全部完成';
    if (task.pendingImport) return `${task.pendingImport} 组待导入`;
    return labels[task.status] || task.status || '本地任务';
  }

  function renderList() {
    const root = el('triptych-task-list');
    if (!tasks.length) {
      root.innerHTML = '<div class="triptych-empty">还没有三连屏任务</div>';
      return;
    }
    root.innerHTML = tasks.map(task => `<button class="triptych-task-row${task.taskId === selected ? ' selected' : ''}" data-task="${escape(task.taskId)}">
      <strong>${escape(task.phone)} · ${task.count} 组</strong>
      <span>${escape(task.storeName || '未记录店名')}</span>
      <small>${escape(taskLabel(task))} · ${task.composed}/${task.count}</small>
    </button>`).join('');
    root.querySelectorAll('[data-task]').forEach(button => {
      button.onclick = () => selectTask(button.dataset.task);
    });
  }

  function groupLabel(group) {
    if (group.status === 'composed') return group.visualReview === 'needs_fix' ? '已切图 · 需检查' : '已切图 · 待验收';
    if (group.unresolved) return `已领取第 ${group.attempt} 次 · 待导入母图`;
    if (group.requests >= 2) return '本组请求次数已用完';
    return '待领取提示词';
  }

  function renderDetail() {
    el('triptych-open').disabled = !current;
    el('triptych-package').disabled = !current?.allComposed || current?.packageVerified;
    if (!current) {
      el('triptych-summary').replaceChildren();
      el('triptych-groups').innerHTML = '<div class="triptych-empty">点击左侧＋创建任务</div>';
      return;
    }
    el('triptych-summary').innerHTML = [
      ['手机号', current.phone], ['店名', current.storeName],
      ['进度', `${current.composed}/${current.count} 组`], ['请求', `${current.requestsUsed}/${current.maxRequests}`],
    ].map(([name, value]) => `<div class="triptych-metric"><small>${escape(name)}</small><strong>${escape(value)}</strong></div>`).join('');
    el('triptych-groups').innerHTML = current.groups.map(group => `<section class="triptych-group" data-group="${group.index}">
      <div class="triptych-group-info"><strong>第 ${group.index} 组</strong><small>${escape(group.storeName || current.storeName)}</small><small>${escape(groupLabel(group))}</small></div>
      <div class="triptych-group-preview">${group.previewUrl ? `<img src="${escape(group.previewUrl)}" alt="第 ${group.index} 组三连屏预览">` : '生成一张连续横幅，导入后在本机切成三张封面'}</div>
      <div class="triptych-group-actions">
        ${group.canClaim ? '<button data-action="claim">领取并复制提示词</button>' : ''}
        ${group.unresolved ? '<button data-action="prompt">查看提示词</button>' : ''}
        ${group.canImport ? '<button data-action="import">导入母图</button>' : ''}
        ${group.previewUrl ? '<button data-action="folder">打开目录</button>' : ''}
      </div>
    </section>`).join('');
    el('triptych-groups').querySelectorAll('[data-action]').forEach(button => {
      const section = button.closest('[data-group]');
      button.onclick = () => groupAction(button.dataset.action, Number(section.dataset.group));
    });
  }

  function showPrompt(prompt) {
    el('triptych-prompt-text').value = prompt;
    el('triptych-copy-status').textContent = '';
    el('triptych-prompt-dialog').showModal();
    el('triptych-copy').focus();
  }

  async function copyPrompt() {
    const field = el('triptych-prompt-text');
    try {
      await navigator.clipboard.writeText(field.value);
      el('triptych-copy-status').textContent = '已复制，请粘贴到 Codex。';
    } catch {
      field.focus(); field.select();
      el('triptych-copy-status').textContent = '请按 Ctrl+C 复制已选中的提示词。';
    }
  }

  async function groupAction(action, group) {
    if (busy || !current) return;
    const row = current.groups.find(item => item.index === group);
    if (!row) return;
    if (action === 'prompt') return showPrompt(row.prompt);
    if (action === 'folder') return window.roadRescue.openTriptych({ taskId: current.taskId });
    busy = true;
    status(action === 'claim' ? `正在领取第 ${group} 组…` : `正在导入并切分第 ${group} 组…`);
    try {
      if (action === 'claim') {
        const result = await window.roadRescue.triptych('claim', { taskId: current.taskId, group });
        current = result.task;
        renderDetail(); renderList(); showPrompt(result.prompt);
      } else if (action === 'import') {
        const result = await window.roadRescue.importTriptych({ taskId: current.taskId, group });
        if (result) { current = result; await reloadList(false); status(`第 ${group} 组已切成左、中、右三张，等待人工验收。`); }
      }
    } catch (error) { status(error.message, true); }
    finally { busy = false; }
  }

  async function reloadList(selectFirst = true) {
    tasks = await window.roadRescue.triptych('list', {});
    if (selected && !tasks.some(task => task.taskId === selected)) selected = null;
    if (!selected && selectFirst) selected = tasks[0]?.taskId || null;
    renderList();
    if (selected) current = await window.roadRescue.triptych('detail', { taskId: selected });
    else current = null;
    renderDetail();
  }

  async function selectTask(taskId) {
    if (busy) return;
    selected = taskId;
    renderList();
    try {
      current = await window.roadRescue.triptych('detail', { taskId });
      renderDetail(); status('');
    } catch (error) { status(error.message, true); }
  }

  async function refresh() {
    if (!active || busy) return;
    busy = true;
    try { await reloadList(); status(tasks.length ? '' : '暂无任务，点击左侧＋创建。'); }
    catch (error) { status(error.message, true); }
    finally { busy = false; }
  }

  window.dashboardTriptychMode = value => {
    active = value;
    document.body.classList.toggle('triptych-mode', active);
    if (active) {
      el('task-message').hidden = true;
      refresh();
    }
  };

  el('triptych-page').onclick = () => {
    const road = document.querySelector('.project-tab[data-project="road_rescue"]');
    if (road && !road.classList.contains('active')) road.click();
    window.dashboardSetPage('triptych');
  };
  el('triptych-new').onclick = () => {
    el('triptych-create-form').reset();
    el('triptych-count').value = '3';
    el('triptych-style-start').value = '0';
    el('triptych-create-error').textContent = '';
    el('triptych-create-dialog').showModal();
    el('triptych-phone').focus();
  };
  el('triptych-create-close').onclick = el('triptych-create-cancel').onclick = () => el('triptych-create-dialog').close();
  el('triptych-create-form').onsubmit = async event => {
    event.preventDefault();
    if (busy) return;
    busy = true;
    const submit = el('triptych-create-submit'); submit.disabled = true;
    el('triptych-create-error').textContent = '';
    try {
      current = await window.roadRescue.triptych('prepare', {
        phone: el('triptych-phone').value,
        count: Number(el('triptych-count').value),
        storeName: el('triptych-store-name').value,
        styleStart: Number(el('triptych-style-start').value),
        fictionalName: el('triptych-fictional-name').checked,
        confirm: el('triptych-confirm').checked,
      });
      selected = current.taskId;
      el('triptych-create-dialog').close();
      await reloadList(false);
      status('本地任务已创建；页面不会自动生图。请逐组领取提示词。');
    } catch (error) { el('triptych-create-error').textContent = error.message; }
    finally { busy = false; submit.disabled = false; }
  };
  el('triptych-refresh').onclick = refresh;
  el('triptych-open').onclick = () => current && window.roadRescue.openTriptych({ taskId: current.taskId });
  el('triptych-package').onclick = async () => {
    if (busy || !current) return;
    busy = true; status('正在校验并打包…');
    try {
      const result = await window.roadRescue.packageTriptych({ taskId: current.taskId });
      if (result) { current = result.task; await reloadList(false); status(`打包完成：${result.result?.archive || ''}`); }
    } catch (error) { status(error.message, true); }
    finally { busy = false; }
  };
  el('triptych-copy').onclick = copyPrompt;
  setInterval(() => { if (active && !document.hidden && !el('triptych-create-dialog').open && !el('triptych-prompt-dialog').open) refresh(); }, 5000);
})();
