const assert=require('node:assert/strict');
const test=require('node:test');
const {operationTimeout}=require('../tasks');

test('paid planning and submission outlive ordinary read timeout',()=>{
  assert.equal(operationTimeout('view'),60000);
  assert.equal(operationTimeout('plan'),180000);
  assert.equal(operationTimeout('start'),180000);
  assert.equal(operationTimeout('resume'),180000);
  assert.equal(operationTimeout('assemble'),600000);
});
