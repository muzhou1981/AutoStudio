const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/geni_studio/web/static/config.js'), 'utf8');
const extract = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
const fields = new Map();
for (const id of ['runtimeError', 'runtimeSaved', 'btnSaveRuntime', 'backendPick', 'modelPick', 'reasoningPick', 'codexReasoningField', 'larkBackend', 'publicBase', 'feishuChat', 'feishuOpen']) {
  fields.set(id, {
    value: '', disabled: false, loading: false, tagName: 'WA-SELECT', options: [],
    replaceChildren(...items) { this.options = items; },
    appendChild(item) { this.options.push(item); },
    querySelectorAll() { return this.options; },
  });
}
const errors = [];
let writes = [];
const context = {
  $: id => fields.get(id),
  showError: (_, text) => errors.push(text),
  showSaved: () => {},
  loadSettings: async () => {},
  waOption: (value, text) => ({value, textContent: text}),
  window: {},
  URLSearchParams,
  customElements: {whenDefined: async () => {}},
  runtimeSettingsCache: { effective_backend: 'cursor', keys: [
    { name: 'GENI_STUDIO_DEFAULT_MODEL', configured: true, value_hint: 'cursor-old' },
  ] },
  fetch: async () => { throw new Error('offline'); },
};
vm.createContext(context);
vm.runInContext(extract('function isFeishuOpenId(', 'function apiKeyEnvName('), context);
vm.runInContext(extract('function resolveBackendPick(', 'function fillRuntime('), context);
vm.runInContext(extract('function defaultModelFromSettings(', 'let modelRequestVersion'), context);
vm.runInContext(extract('async function saveRuntime()', 'function agentFieldCopy('), context);
vm.runInContext(extract('let modelRequestVersion', 'for (const id of ["modelPick", "reasoningPick"])'), context);
vm.runInContext(extract('function fillOneWorkflowSelect(', 'async function resolveEffectiveBackend('), context);
vm.runInContext(extract('function updateProjectFlowSummary(', '$("fieldSkipMode").addEventListener'), context);
vm.runInContext(extract('function fillScenarioOptions(', 'function renderSkipNodes('), context);
(async () => {
  assert.equal(context.defaultModelFromSettings(context.runtimeSettingsCache, 'codex'), '');
  assert.equal(context.defaultModelFromSettings(context.runtimeSettingsCache, 'cursor'), 'cursor-old');
  fields.get('backendPick').value = 'codex';
  fields.get('modelPick').value = 'codex-new';
  fields.get('reasoningPick').value = 'high';
  // Web Awesome 空输入初始值可为 null，状态比较和保存不能直接调用 trim。
  for (const id of ['publicBase', 'feishuChat', 'feishuOpen']) fields.get(id).value = null;
  const emptyForm = context.runtimeFormSnapshot();
  assert.equal(emptyForm.pub, '');
  assert.equal(emptyForm.chat, '');
  assert.equal(emptyForm.open, '');
  await context.saveRuntime();
  assert.equal(fields.get('btnSaveRuntime').disabled, false);
  assert.equal(fields.get('btnSaveRuntime').loading, false);
  assert.match(errors.at(-1), /部分配置/);
  context.fetch = async (url, args) => {
    if (url.endsWith('/probe')) return { ok: true, json: async () => ({ok: true}) };
    writes.push(JSON.parse(args.body));
    return { ok: true, json: async () => ({}) };
  };
  await context.saveRuntime();
  assert.ok(writes.some(x => x.key === 'GENI_STUDIO_CURSOR_MODEL' && x.value === 'cursor-old'));
  assert.ok(writes.some(x => x.key === 'GENI_STUDIO_CODEX_MODEL' && x.value === 'codex-new'));
  assert.ok(writes.some(x => x.key === 'GENI_STUDIO_CODEX_REASONING_EFFORT' && x.value === 'high'));
  context.runtimeSettingsCache = { effective_backend: 'codex', keys: [
    {name: 'GENI_STUDIO_CODEX_REASONING_EFFORT', configured: true, value_hint: 'high'},
  ] };
  context.fillReasoning(context.runtimeSettingsCache, 'codex');
  assert.equal(fields.get('codexReasoningField').hidden, false);
  assert.equal(fields.get('reasoningPick').value, 'high');
  assert.equal(context.runtimeSavedSnapshot(context.runtimeSettingsCache).reasoning, 'high');
  assert.equal(context.runtimeFormSnapshot().reasoning, 'high');
  fields.get('reasoningPick').value = 'default';
  assert.equal(context.runtimeFormSnapshot().reasoning, '');
  writes = [];
  await context.saveRuntime();
  assert.ok(writes.some(x => x.key === 'GENI_STUDIO_CODEX_REASONING_EFFORT' && x.value === 'default'));
  writes = [];
  context.runtimeSettingsCache = { effective_backend: 'codex', keys: [] };
  fields.get('backendPick').value = 'stub';
  context.fillReasoning(context.runtimeSettingsCache, 'stub');
  assert.equal(fields.get('codexReasoningField').hidden, true);
  await context.saveRuntime();
  assert.ok(!writes.some(x => x.key === 'GENI_STUDIO_CURSOR_MODEL' || x.key === 'GENI_STUDIO_CODEX_MODEL'));
  assert.ok(!writes.some(x => x.key === 'GENI_STUDIO_CODEX_REASONING_EFFORT'));

  // 两个模型的能力各自来自 SDK，不将一种模型的推理级别用于另一种。
  const models = [
    {id: 'dynamic-a', label: 'A', is_default: true, default_reasoning_effort: 'high',
      reasoning_efforts: [{id: 'low', description: 'Fast'}, {id: 'high', description: 'Thorough'}]},
    {id: 'dynamic-b', label: 'B', is_default: false, default_reasoning_effort: 'medium',
      reasoning_efforts: [{id: 'medium', description: 'Balanced'}]},
  ];
  fields.get('backendPick').value = 'codex';
  fields.get('reasoningPick').value = 'high';
  context.fetch = async () => ({ok: true, json: async () => ({models, detail: ''})});
  await context.refreshDefaultModelPick('codex', 'dynamic-a');
  assert.deepEqual(fields.get('reasoningPick').options.map(x => x.value), ['default', 'low', 'high']);
  assert.match(fields.get('reasoningPick').options[2].textContent, /模型建议/);
  assert.equal(fields.get('reasoningPick').options[2].title, 'Thorough');
  fields.get('modelPick').value = 'dynamic-b';
  context.refreshReasoningPick();
  assert.equal(fields.get('reasoningPick').value, 'high');
  assert.match(context.reasoningSelectionError(), /不支持/);
  assert.deepEqual(fields.get('reasoningPick').options.map(x => x.value), ['default', 'medium', 'high']);
  writes = [];
  context.fetch = async (_url, args) => {
    writes.push(args);
    throw new Error('should not write invalid selection');
  };
  await context.saveRuntime();
  assert.equal(writes.length, 0);
  assert.match(errors.at(-1), /不支持/);
  fields.get('reasoningPick').value = 'medium';
  context.refreshReasoningPick();
  assert.equal(context.reasoningSelectionError(), '');
  assert.deepEqual(fields.get('reasoningPick').options.map(x => x.value), ['default', 'medium']);

  // 模型留空时不把目录 is_default 当成本机配置的实际模型。
  fields.get('modelPick').value = '';
  fields.get('reasoningPick').value = 'default';
  context.refreshReasoningPick();
  assert.deepEqual(fields.get('reasoningPick').options.map(x => x.value), ['default']);
  assert.match(fields.get('reasoningPick').hint, /先明确选择模型/);

  // 加载失败与未知模型保留配置，不退回固定选项，也不清空已有设置。
  fields.get('reasoningPick').value = 'high';
  context.fetch = async () => {throw new Error('offline');};
  await context.refreshDefaultModelPick('codex', 'dynamic-a');
  assert.equal(fields.get('reasoningPick').value, 'high');
  assert.deepEqual(fields.get('reasoningPick').options.map(x => x.value), ['default', 'high']);
  assert.match(fields.get('reasoningPick').hint, /读不到推理级别/);

  // 较晚返回的旧请求不能覆盖最新模型及推理级别。
  const pending = [];
  context.fetch = () => new Promise(resolve => pending.push(resolve));
  fields.get('reasoningPick').value = 'default';
  const oldRequest = context.refreshDefaultModelPick('codex', 'dynamic-a');
  const newRequest = context.refreshDefaultModelPick('codex', 'dynamic-b');
  pending[1]({ok: true, json: async () => ({models, detail: ''})});
  await newRequest;
  pending[0]({ok: true, json: async () => ({models, detail: ''})});
  await oldRequest;
  assert.equal(fields.get('modelPick').value, 'dynamic-b');
  assert.deepEqual(fields.get('reasoningPick').options.map(x => x.value), ['default', 'medium']);

  // 首次初始化会先读取项目列表；已移除的 fieldDirScenario 不应阻断模型加载。
  for (const id of ['fieldProfile', 'fieldDirProfile', 'scenarioPick', 'fieldScenario', 'projectPick']) {
    fields.set(id, {value: '', options: [],
      replaceChildren(...items) { this.options = items; },
      appendChild(item) { this.options.push(item); },
    });
  }
  assert.equal(fields.has('fieldDirScenario'), false);
  context.fetch = async (url) => ({ok: true, json: async () => {
    if (url === '/api/config/scenarios') return {scenarios: [{scenario_key: 'general', title: '通用'}]};
    if (url === '/api/config/projects') return {projects: [{project_id: 'example', title: '示例'}], nodes: []};
    if (url === '/api/workflows') return {workflows: [{workflow_id: 'default', title: '通用流程'}]};
    return {models, detail: ''};
  }});
  fields.get('modelPick').replaceChildren();
  await context.loadLists();
  await context.refreshDefaultModelPick('codex', 'dynamic-a');
  assert.equal(context.window.__projects[0].project_id, 'example');
  assert.deepEqual(fields.get('modelPick').options.map(x => x.value), ['', 'dynamic-a', 'dynamic-b']);
  console.log('Config runtime regression passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
