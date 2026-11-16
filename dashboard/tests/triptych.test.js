const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '../..');
const service = require('../triptych');

function fixture() {
  fs.mkdirSync(path.join(root, '.runtime'), { recursive: true });
  const home = fs.mkdtempSync(path.join(root, '.runtime', 'triptych-service-'));
  fs.mkdirSync(path.join(home, 'output', 'road_rescue_pinned'), { recursive: true });
  return home;
}

function writeTask(home, overrides = {}) {
  const taskId = overrides.task_id || '20261116T010203123456Z';
  const directory = path.join(home, 'output', 'road_rescue_pinned', taskId);
  fs.mkdirSync(directory, { recursive: true });
  const task = {
    version: 1,
    task_id: taskId,
    phone: '13800138000',
    category: 'road_rescue',
    count: 2,
    status: 'generating',
    max_requests: 4,
    requests: [{ group: 1, attempt: 1, status: 'requesting' }],
    store_identity: { name: '测试字号道路救援' },
    groups: [
      { index: 1, status: 'pending', prompt: 'prompt one', store_identity: { name: '测试字号道路救援' } },
      { index: 2, status: 'composed', prompt: 'prompt two', store_identity: { name: '测试字号道路救援' }, visual_review: 'pending' },
    ],
    ...overrides,
  };
  fs.writeFileSync(path.join(directory, 'task.json'), JSON.stringify(task));
  fs.mkdirSync(path.join(directory, 'group_02'));
  fs.writeFileSync(path.join(directory, 'group_02', 'preview.jpg'), Buffer.from([0xff, 0xd8, 0xff, 0xd9]));
  return { taskId, directory };
}

test('validates local-only triptych preparation fields', () => {
  assert.deepEqual(service.validatePrepare({
    phone: '13800138000', count: 3, storeName: '测试字号道路救援', styleStart: 2,
    fictionalName: true, confirm: true,
  }), {
    phone: '13800138000', count: 3, storeName: '测试字号道路救援', styleStart: 2,
    fictionalName: true,
  });
  assert.throws(() => service.validatePrepare({ phone: '1', count: 3, storeName: '测试店', confirm: true }), /11位/);
  assert.throws(() => service.validatePrepare({ phone: '13800138000', count: 0, storeName: '测试店', confirm: true }), /1到100/);
  assert.throws(() => service.validatePrepare({ phone: '13800138000', count: 1, storeName: '测试店' }), /确认/);
});

test('lists and reads only bounded triptych task directories', () => {
  const home = fixture();
  const { taskId } = writeTask(home);
  const rows = service.list(home);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].pendingImport, 1);
  assert.equal(rows[0].composed, 1);
  const detail = service.detail(home, taskId);
  assert.equal(detail.groups[0].canClaim, false);
  assert.equal(detail.groups[0].canImport, true);
  assert.equal(detail.groups[1].previewUrl.startsWith('file:'), true);
  assert.equal(detail.allComposed, false);
  assert.throws(() => service.taskDirectory(home, '..\\outside'), /编号无效/);
  assert.throws(() => service.detail(home, '20261116T999999999999Z'), /ENOENT/);
});
