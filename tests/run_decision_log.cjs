const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/geni_studio/web/static/hitl.js'), 'utf8');
const start = source.indexOf('    const DECISION_CHANNELS = {');
const end = source.indexOf('    /** 人工停点历次的决定', start);
assert.ok(start >= 0 && end > start);
const context = vm.createContext({});
vm.runInContext(source.slice(start, end), context);
const label = (entry) => vm.runInContext(`decisionLabel(${JSON.stringify(entry)})`, context);

// 决定按批复时下拉框的文字回显：退回某节点与结束本轮要分开。
assert.equal(label({ decision: 'approved', reject_label: '改代码' }), '批准');
assert.equal(label({ decision: 'rejected', reject_label: '改代码' }), '不通过——退回“改代码”');
assert.equal(label({ decision: 'rejected', reject_label: '' }), '驳回——结束本轮');
const tone = (entry) => vm.runInContext(`decisionTone(${JSON.stringify(entry)})`, context);
assert.equal(label({ kind: 'pm_clarification', decision: 'replied' }), '已答复');
assert.equal(label({ kind: 'escalation', decision: 'continue' }), '继续重试');
assert.equal(label({ kind: 'escalation', decision: 'abort' }), '终止本轮');
assert.equal(tone({ kind: 'escalation', decision: 'pause' }), 'is-paused');
assert.equal(tone({ kind: 'gate', decision: 'rejected' }), 'is-rejected');
assert.equal(vm.runInContext('decisionTime("not a time")', context), '');
assert.match(vm.runInContext('decisionTime("2026-11-12T07:20:00Z")', context), /11.*12/);
console.log('Decision log regression passed');
