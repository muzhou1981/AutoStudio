const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/geni_studio/web/static/hitl.js'), 'utf8');
const stored = new Map();
const puts = [];
let serverPrefs = {};
const context = vm.createContext({
  localStorage: {
    getItem: (k) => (stored.has(k) ? stored.get(k) : null),
    setItem: (k, v) => stored.set(k, String(v)),
    removeItem: (k) => stored.delete(k),
  },
  fetch: async (url, opts) => {
    if (opts && opts.method === 'PUT') puts.push(JSON.parse(opts.body));
    return { ok: true, json: async () => ({ role_model_prefs: serverPrefs }) };
  },
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
        reasoning_efforts: [{ id: 'low' }, { id: 'medium' }, { id: 'high' }], fast: true, default_fast: 'on' },
      { id: 'composer-2.5', label: 'Composer 2.5' },
      { id: 'gpt-5.5', label: 'GPT-5.5', reasoning_param: 'reasoning', default_reasoning_effort: 'low',
        reasoning_efforts: [{ id: 'low' }, { id: 'high' }], fast: true, default_fast: 'off',
        params: [{ id: 'context', values: [{ id: '272k', label: '272K' }, { id: '1m', label: '1M' }], default: '1m' }],
        variants: [
          { context: '272k', reasoning: 'low', fast: 'false' }, { context: '272k', reasoning: 'low', fast: 'true' },
          { context: '272k', reasoning: 'high', fast: 'false' }, { context: '272k', reasoning: 'high', fast: 'true' },
          { context: '1m', reasoning: 'low', fast: 'false' }, { context: '1m', reasoning: 'high', fast: 'false' },
        ] },
    ],
  },
  pendingRoleModels: {},
  pendingRoleReasoningEfforts: {},
  pendingRoleFastModes: {},
  pendingRoleModelParams: {},
});
const start = source.indexOf('    const EFFORT_LABELS = {');
const end = source.indexOf('    function roleModelsLocked(', start);
assert.ok(start >= 0 && end > start);
vm.runInContext(source.slice(start, end), context);
const setting = (role) => vm.runInContext(`roleModelSetting(${JSON.stringify(role)})`, context);
const choose = (models, efforts, fast = {}, params = {}) => vm.runInContext(
  `pendingRoleModels = ${JSON.stringify(models)}; pendingRoleReasoningEfforts = ${JSON.stringify(efforts)};`
  + ` pendingRoleFastModes = ${JSON.stringify(fast)}; pendingRoleModelParams = ${JSON.stringify(params)};`, context);

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

// Codex 未配置模型：按目录里 is_default 的模型给出推理强度与 Fast。
vm.runInContext(`runRoleDefaults.developer.model = '';`
  + ` runModelCatalogs.codex[1] = { ...runModelCatalogs.codex[1], is_default: true, fast: true, default_fast: 'off' };`, context);
choose({}, { developer: 'low' }, { developer: 'on' });
assert.equal(setting('developer').model.id, 'small');
assert.equal(setting('developer').fastSupported, true);
assert.equal(setting('developer').problem, '');
choose({}, { developer: 'ultra' });
assert.match(setting('developer').problem, /不支持推理强度 ultra/);
vm.runInContext(`runRoleDefaults.developer.model = 'full'; delete runModelCatalogs.codex[1].is_default;`, context);

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

// Fast：只有模型目录声明了 fast 的模型才能指定；Auto 与不支持的模型报出问题。
choose({ tester: 'grok-4.7' }, {}, { tester: 'off' });
assert.equal(setting('tester').fastSupported, true);
assert.equal(setting('tester').problem, '');
choose({}, {}, { tester: 'on' });
assert.match(setting('tester').problem, /不能指定 Fast/);
assert.match(context.runReasoningError(), /^测试工程师：/);
choose({ tester: 'composer-2.5' }, {}, { tester: 'on' });
assert.match(setting('tester').problem, /Composer 2.5 没有 Fast 模式/);
choose({ tester: 'composer-2.5' }, {}, {});
assert.equal(context.runReasoningError(), '');

// 上下文：取值来自模型目录；组合须在目录允许的变体之内，沿用默认的项不参与比对。
choose({ tester: 'gpt-5.5' }, { tester: 'high' }, {}, { tester: { context: '272k' } });
assert.equal(setting('tester').problem, '');
assert.deepEqual(setting('tester').params.map((item) => item.id), ['context']);
choose({ tester: 'gpt-5.5' }, {}, { tester: 'on' }, { tester: { context: '1m' } });
assert.match(setting('tester').problem, /GPT-5.5 不支持这组设置/);
assert.match(context.runReasoningError(), /^测试工程师：/);
choose({ tester: 'gpt-5.5' }, {}, { tester: 'on' }, {});
assert.equal(setting('tester').problem, '', '上下文沿用默认时不按默认值比对组合');
assert.deepEqual({ ...context.comboFill(setting('tester')) }, { context: '272k' }, '默认 1M 不能开 Fast，补成离默认最近的 272K');
choose({ tester: 'gpt-5.5' }, { tester: 'high' }, {}, { tester: { context: '272k' } });
assert.deepEqual({ ...context.comboFill(setting('tester')) }, {}, '显式选择与默认项拼起来在目录内时不改');
choose({ tester: 'gpt-5.5' }, {}, {}, { tester: { context: '2m' } });
assert.match(setting('tester').problem, /不支持上下文 2m/);
choose({ tester: 'grok-4.7' }, {}, {}, { tester: { context: '1m' } });
assert.match(setting('tester').problem, /Grok 4.7 没有上下文选项/);
choose({}, {}, {}, { tester: { context: '1m' } });
assert.match(setting('tester').problem, /Auto 模型.*不能指定上下文/);
// 参数随模型记忆：换模型时记下旧模型的取值，换回时恢复；没记过的模型回到默认。
const pending = () => JSON.parse(vm.runInContext(
  'JSON.stringify([pendingRoleModels, pendingRoleReasoningEfforts, pendingRoleFastModes, pendingRoleModelParams])', context));
choose({ tester: 'gpt-5.5' }, { tester: 'high' }, { tester: 'on' }, { tester: { context: '272k' } });
vm.runInContext('rememberRolePrefs("tester");', context);
context.switchRoleModel('tester', 'grok-4.7');
assert.deepEqual(pending(), [{ tester: 'grok-4.7' }, {}, {}, {}], '没记过的模型回到默认');
vm.runInContext('pendingRoleReasoningEfforts = { tester: "low" }; rememberRolePrefs("tester");', context);
context.switchRoleModel('tester', 'gpt-5.5');
assert.deepEqual(pending(), [{ tester: 'gpt-5.5' }, { tester: 'high' }, { tester: 'on' }, { tester: { context: '272k' } }]);
context.switchRoleModel('tester', 'grok-4.7');
assert.deepEqual(pending()[1], { tester: 'low' });
context.switchRoleModel('tester', '');
assert.deepEqual(pending(), [{}, {}, {}, {}], 'Auto 没有记过取值');
choose({ tester: 'gpt-5.5' }, {}, {}, {});
context.switchRoleModel('tester', 'grok-4.7');
context.switchRoleModel('tester', 'gpt-5.5');
assert.deepEqual(pending()[1], { tester: 'high' }, '换走时不拿 Run 里沿用下来的空值覆盖记忆');
const prefs = () => JSON.parse(vm.runInContext('JSON.stringify(roleModelPrefs)', context));
assert.deepEqual(Object.keys(prefs().tester).sort(), ['cursor:gpt-5.5', 'cursor:grok-4.7'], '只记有过选择的模型');
assert.deepEqual(puts.map((p) => [p.model, p.effort, p.fast, p.params]), [
  ['gpt-5.5', 'high', 'on', { context: '272k' }],
  ['grok-4.7', 'low', '', {}],
], '每项改动逐项写回服务端，未变的不重复写');

(async () => {
  // 服务端记忆覆盖页面副本；本地旧记忆中服务端没有的项补写后删除本地副本。
  serverPrefs = { tester: { 'cursor:gpt-5.5': { effort: 'low' } } };
  stored.set('geni_studio_role_model_prefs', JSON.stringify({
    tester: { 'cursor:gpt-5.5': { effort: 'high' }, 'cursor:composer-2.5': { fast: 'on' } },
  }));
  puts.length = 0;
  await context.loadRolePrefs();
  assert.deepEqual(prefs(), { tester: { 'cursor:gpt-5.5': { effort: 'low' }, 'cursor:composer-2.5': { fast: 'on' } } });
  assert.deepEqual(puts.map((p) => [p.model, p.fast]), [['composer-2.5', 'on']]);
  assert.equal(stored.has('geni_studio_role_model_prefs'), false);
  // 读取期间页面又改过记忆时不覆盖页面副本。
  serverPrefs = {};
  const loading = context.loadRolePrefs();
  vm.runInContext('pendingRoleModels = { tester: "gpt-5.5" }; pendingRoleReasoningEfforts = { tester: "high" }; rememberRolePrefs("tester");', context);
  await loading;
  assert.deepEqual(prefs().tester['cursor:gpt-5.5'], { effort: 'high' });
  console.log('Run role model prefs regression passed');
})().catch((error) => { console.error(error); process.exit(1); });

choose({}, {}, {}, {});
assert.equal(context.comboAllowed({ variants: [] }, { context: 'x' }), true, '目录没有组合表时不限制');
assert.equal(context.effortLabel('xhigh'), '很高（xhigh）');
assert.equal(context.roleModelOptions('tester')[1].id, 'grok-4.7');
console.log('Run reasoning UI regression passed');
