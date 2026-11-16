/* Isolated Electron acceptance: no API calls and only a local synthetic panorama. */
const { app, BrowserWindow, dialog } = require('electron');
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '../..');
fs.mkdirSync(path.join(root, '.runtime'), { recursive: true });
const fixture = fs.mkdtempSync(path.join(root, '.runtime', 'triptych-ui-'));
fs.mkdirSync(path.join(fixture, 'output'), { recursive: true });
fs.mkdirSync(path.join(fixture, 'projects'), { recursive: true });
fs.copyFileSync(path.join(root, 'projects', 'registry.json'), path.join(fixture, 'projects', 'registry.json'));
fs.writeFileSync(path.join(fixture, 'factory.py'), [
  'import os,runpy,sys',
  `os.environ['FACTORY_DATA_HOME']=${JSON.stringify(fixture)}`,
  `sys.path.insert(0,${JSON.stringify(root)})`,
  `runpy.run_path(${JSON.stringify(path.join(root, 'factory.py'))},run_name='__main__')`,
  '',
].join('\n'));
const source = path.join(fixture, 'synthetic.png');
fs.writeFileSync(source, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64'));
const exportsDirectory = path.join(fixture, 'exports');
fs.mkdirSync(exportsDirectory);

process.env.ROAD_RESCUE_FACTORY_HOME = fixture;
process.env.ROAD_RESCUE_DASHBOARD_TEST = '1';
require('../main');

const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function run() {
  await app.whenReady();
  const win = BrowserWindow.getAllWindows()[0];
  win.show(); win.focus();
  const js = sourceCode => win.webContents.executeJavaScript(sourceCode).catch(error => {
    throw Error(`${sourceCode} : ${error.message}`);
  });
  async function until(expression) {
    for (let attempt = 0; attempt < 300; attempt += 1) {
      if (await js(expression)) return;
      await pause(100);
    }
    throw Error(`timeout ${expression} status=${await js('document.getElementById("triptych-status")?.textContent')}`);
  }

  await until('document.querySelectorAll(".project-tab").length>0');
  await js('document.getElementById("triptych-page").click()');
  await until('!document.getElementById("triptych-panel").hidden');
  assert.equal(await js('document.getElementById("triptych-task-list").hidden'), false);
  assert.equal(await js('document.getElementById("task-batch-list").hidden'), true);

  await js('document.getElementById("triptych-new").click()');
  await js('document.getElementById("triptych-random-store-names").click()');
  assert.equal(await js('document.getElementById("triptych-store-name").disabled'), true);
  assert.equal(await js('document.getElementById("triptych-fictional-name").checked'), true);
  await js(`document.getElementById('triptych-phone').value='13800138000';
    document.getElementById('triptych-count').value='2';
    document.getElementById('triptych-confirm').checked=true;
    document.getElementById('triptych-create-form').requestSubmit();`);
  await until('document.querySelectorAll(".triptych-task-row").length===1');
  assert.equal(await js('document.getElementById("triptych-auto").disabled'), false);
  dialog.showOpenDialog = async (_, options) => ({
    canceled: false,
    filePaths: options.properties.includes('openFile') ? [source] : [exportsDirectory],
  });
  for (const group of [1, 2]) {
    await until(`document.querySelector('[data-group="${group}"] [data-action=claim]')!==null`);
    await js(`document.querySelector('[data-group="${group}"] [data-action=claim]').click()`);
    await until('document.getElementById("triptych-prompt-dialog").open');
    assert.equal(await js('document.getElementById("triptych-prompt-text").value.includes("连续摄影画面")'), true);
    await js('document.getElementById("triptych-prompt-dialog").close()');
    await until(`document.querySelector('[data-group="${group}"] [data-action=import]')!==null`);
    await js(`document.querySelector('[data-group="${group}"] [data-action=import]').click()`);
    await until(`document.querySelector('[data-group="${group}"] .triptych-group-preview img')!==null`);
  }
  assert.equal(await js('document.getElementById("triptych-package").disabled'), false);
  await js('document.getElementById("triptych-package").click()');
  await until('document.getElementById("triptych-status").textContent.includes("打包完成")');
  assert.equal(fs.readdirSync(exportsDirectory).filter(name => name.endsWith('.zip')).length, 1);

  const taskDirectories = fs.readdirSync(path.join(fixture, 'output', 'road_rescue_pinned'));
  assert.equal(taskDirectories.length, 1);
  const task = JSON.parse(fs.readFileSync(path.join(fixture, 'output', 'road_rescue_pinned', taskDirectories[0], 'task.json')));
  assert.equal(task.requests.length, 2);
  assert.equal(task.identity_mode, 'per_group');
  assert.equal(new Set(task.groups.map(group => group.store_identity.name)).size, 2);
  assert.equal(task.groups.every(group => group.status === 'composed'), true);
  assert.equal(task.package_verified, true);
  fs.writeFileSync(path.join(root, '.runtime', 'triptych-ui.png'), (await win.webContents.capturePage()).toPNG());
  fs.writeFileSync(path.join(root, '.runtime', 'triptych-ui-result.json'), JSON.stringify({
    ok: true, fixture, taskId: task.task_id, requests: 2, paidRequests: 0, packaged: true, randomNames: true,
  }));
  app.exit(0);
}

run().catch(error => {
  fs.writeFileSync(path.join(root, '.runtime', 'triptych-ui-result.json'), JSON.stringify({ ok: false, error: error.stack, fixture }));
  app.exit(1);
});
