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
    if (current?.autoRunning) return '自动生成队列中';
    return '待领取提示词';
  }

  function renderDetail() {
    el('triptych-open').disabled = !current;
    el('triptych-package').disabled = !current?.allComposed || current?.packageVerified;
    const autoButton = el('triptych-auto');
    autoButton.disabled = !current || (!current.autoRunning && !current.canAutoStart);
    autoButton.textContent = current?.autoRunning ? '暂停自动生成'
      : current?.autoStatus === 'paused' || current?.autoStatus === 'completed_with_errors' ? '继续自动生成' : '开始生成全部';
    if (!current) {
      el('triptych-summary').replaceChildren();
      el('triptych-groups').innerHTML = '<div class="triptych-empty">点击左侧＋创建任务</div>';
      return;
    }
    el('triptych-summary').innerHTML = [
      ['手机号', current.phone], ['店名', current.storeName],
      ['进度', `${current.composed}/${current.count} 组`], ['请求', `${current.requestsUsed}/${current.maxRequests}`],
      ['自动生成', current.autoRunning ? '进行中' : current.autoStatus === 'completed' ? '已完成' : current.autoStatus === 'paused' ? '已暂停' : current.autoStatus === 'completed_with_errors' ? '有失败，可继续' : '未开始'],
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
    syncRandomStoreNames();
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
        randomStoreNames: el('triptych-random-store-names').checked,
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
  function syncRandomStoreNames() {
    const random = el('triptych-random-store-names').checked;
    const store = el('triptych-store-name');
    const fictional = el('triptych-fictional-name');
    store.disabled = random;
    store.required = !random;
    store.placeholder = random ? '将为每组自动生成并冻结' : '同一任务内共用';
    fictional.disabled = random;
    if (random) fictional.checked = true;
  }
  el('triptych-random-store-names').onchange = syncRandomStoreNames;
  el('triptych-refresh').onclick = refresh;
  el('triptych-auto').onclick = async () => {
    if (busy || !current) return;
    const pausing = current.autoRunning;
    if (!pausing && !window.confirm(`将使用现有 API 密钥自动生成剩余 ${current.count - current.composed} 组，任务总请求上限 ${current.maxRequests} 次。是否开始？`)) return;
    busy = true;
    status(pausing ? '正在请求暂停；已发出的请求会先收尾…' : '正在启动自动生成并检查可用密钥…');
    try {
      current = await window.roadRescue.triptych(pausing ? 'pause-auto' : 'start-auto', {
        taskId: current.taskId, confirmPaid: !pausing,
      });
      renderDetail(); renderList();
      status(pausing ? '已请求暂停，请等待当前请求收尾。' : '自动生成已启动；先单路验证，成功后逐步增加并发。');
    } catch (error) { status(error.message, true); }
    finally { busy = false; }
  };
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
