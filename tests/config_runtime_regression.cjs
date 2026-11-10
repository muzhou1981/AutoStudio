const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/geni_studio/web/static/config.js'), 'utf8');
const extract = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
const fields = new Map();
for (const id of ['runtimeError', 'runtimeSaved', 'btnSaveRuntime', 'backendPick', 'modelPick', 'larkBackend', 'publicBase', 'feishuChat', 'feishuOpen']) {
  fields.set(id, { value: '', disabled: false, loading: false });
}
const errors = [];
let writes = [];
const context = {
  $: id => fields.get(id),
  showError: (_, text) => errors.push(text),
  showSaved: () => {},
  loadSettings: async () => {},
  runtimeSettingsCache: { effective_backend: 'cursor', keys: [
    { name: 'GENI_STUDIO_DEFAULT_MODEL', configured: true, value_hint: 'cursor-old' },
  ] },
  fetch: async () => { throw new Error('offline'); },
};
vm.createContext(context);
vm.runInContext(extract('function resolveBackendPick(', 'function fillRuntime('), context);
vm.runInContext(extract('function defaultModelFromSettings(', 'let modelRequestVersion'), context);
vm.runInContext(extract('async function saveRuntime()', 'function agentFieldCopy('), context);
(async () => {
  assert.equal(context.defaultModelFromSettings(context.runtimeSettingsCache, 'codex'), '');
  assert.equal(context.defaultModelFromSettings(context.runtimeSettingsCache, 'cursor'), 'cursor-old');
  fields.get('backendPick').value = 'codex';
  fields.get('modelPick').value = 'codex-new';
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
  writes = [];
  context.runtimeSettingsCache = { effective_backend: 'codex', keys: [] };
  fields.get('backendPick').value = 'stub';
  await context.saveRuntime();
  assert.ok(!writes.some(x => x.key === 'GENI_STUDIO_CURSOR_MODEL' || x.key === 'GENI_STUDIO_CODEX_MODEL'));
  console.log('Config runtime regression passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
