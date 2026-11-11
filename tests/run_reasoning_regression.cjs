const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/geni_studio/web/static/hitl.js'), 'utf8');
const context = vm.createContext({
  roleTitles: { developer: '程序员', tester: '测试工程师' },
  runRoleDefaults: {
    developer: { backend: 'codex', model: 'full', reasoning_effort: 'low' },
    tester: { backend: 'cursor', model: '', reasoning_effort: '' },
  },
  runModelCatalogs: {
    codex: [
      { id: 'full', default_reasoning_effort: 'low', reasoning_efforts: [{ id: 'low' }, { id: 'ultra' }] },
      { id: 'small', default_reasoning_effort: 'low', reasoning_efforts: [{ id: 'low' }] },
    ],
    cursor: [
      { id: 'default', label: 'Auto' },
      { id: 'grok-4.7', label: 'Grok 4.7', reasoning_param: 'reasoning_effort', default_reasoning_effort: 'medium',
        reasoning_efforts: [{ id: 'low' }, { id: 'medium' }, { id: 'high' }] },
      { id: 'composer-2.5', label: 'Composer 2.5' },
    ],
  },
  pendingRoleModels: {},
  pendingRoleReasoningEfforts: {},
});
const start = source.indexOf('    const EFFORT_LABELS = {');
const end = source.indexOf('    function roleModelsLocked(', start);
assert.ok(start >= 0 && end > start);
vm.runInContext(source.slice(start, end), context);
const setting = (role) => vm.runInContext(`roleModelSetting(${JSON.stringify(role)})`, context);
const choose = (models, efforts) => vm.runInContext(
  `pendingRoleModels = ${JSON.stringify(models)}; pendingRoleReasoningEfforts = ${JSON.stringify(efforts)};`, context);

// Codex：推理级别来自所选模型；换成不支持的模型时报出问题。
choose({}, { developer: 'ultra' });
assert.equal(setting('developer').problem, '');
assert.deepEqual(setting('developer').efforts.map((item) => item.id), ['low', 'ultra']);
choose({ developer: 'small' }, { developer: 'ultra' });
assert.match(setting('developer').problem, /不支持推理强度 ultra/);
assert.match(context.runReasoningError(), /^程序员：/);
choose({ developer: 'small' }, { developer: 'default' });
assert.equal(context.runReasoningError(), '');
choose({ developer: 'not-in-catalog' }, { developer: 'high' });
assert.equal(setting('developer').model, null);
assert.equal(setting('developer').problem, '', '目录里没有的模型不判定为不支持');

// Cursor：沿用默认时为 Auto，不能指定推理强度；选具体模型后取该模型声明的级别。
choose({}, {});
assert.equal(setting('tester').auto, true);
assert.equal(setting('tester').efforts.length, 0);
choose({}, { tester: 'high' });
assert.match(setting('tester').problem, /Auto 模型/);
assert.match(context.runReasoningError(), /^测试工程师：/);
choose({ tester: 'grok-4.7' }, { tester: 'high' });
assert.equal(setting('tester').problem, '');
assert.deepEqual(setting('tester').efforts.map((item) => item.id), ['low', 'medium', 'high']);
choose({ tester: 'grok-4.7' }, { tester: 'max' });
assert.match(setting('tester').problem, /Grok 4.7 不支持推理强度 max/);
choose({ tester: 'composer-2.5' }, {});
assert.equal(setting('tester').efforts.length, 0, '没有推理参数的模型不提供级别');
assert.equal(context.effortLabel('xhigh'), '很高（xhigh）');
assert.equal(context.roleModelOptions('tester')[1].id, 'grok-4.7');
console.log('Run reasoning UI regression passed');
