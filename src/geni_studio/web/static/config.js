(function () {
const $ = (id) => document.getElementById(id);

const formatApiDetail =
  (window.geniApi && window.geniApi.formatApiDetail) ||
  function (detail) {
    return detail == null ? "" : String(detail);
  };

const apiErrorMessage =
  (window.geniApi && window.geniApi.apiErrorMessage) ||
  function (data, fallback) {
    const text = formatApiDetail(data && data.detail);
    return text || fallback;
  };

function showError(el, msg) {
  const text = formatApiDetail(msg);
  if (!text) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = text;
}

function showSaved(el, msg) {
  if (!el) return;
  el.hidden = !msg;
  el.textContent = msg || "";
}

function showFieldInline(id, msg) {
  const el = $(id);
  if (!el) return;
  if (!msg) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = msg;
}

async function fetchWorkspaceFieldCheck(workspace) {
  const q = new URLSearchParams();
  if (workspace !== undefined) q.set("workspace", workspace);
  const r = await fetch("/api/config/projects/field-check?" + q.toString());
  const data = await r.json();
  if (!r.ok) return { ok: false, errors: {} };
  return data;
}

async function validateWorkspaceField() {
  const value = ($("fieldWorkspace").value || "").trim();
  if (!value) {
    showFieldInline("fieldWorkspaceError", "");
    syncWorkspaceClearButton();
    return true;
  }
  const data = await fetchWorkspaceFieldCheck(value);
  const msg = (data.errors && data.errors.workspace) || "";
  showFieldInline("fieldWorkspaceError", msg);
  syncWorkspaceClearButton();
  return !msg;
}

function syncWorkspaceClearButton() {
  const btn = $("btnClearWorkspace");
  if (!btn) return;
  const has = Boolean(($("fieldWorkspace").value || "").trim());
  btn.hidden = !has;
}

function chipFor(item) {
  if (item.name === "GENI_STUDIO_DEFAULT_MODEL" && !item.configured) return ["后端默认", "is-ok"];
  if (item.name === "GENI_STUDIO_CURSOR_MODEL" && !item.configured) return ["默认", "is-ok"];
  if (item.name === "GENI_STUDIO_BACKEND" && !item.configured) return ["自动", "is-ok"];
  if (item.name === "GENI_STUDIO_LARK_BACKEND" && !item.configured) return ["默认", "is-ok"];
  if (item.configured) return ["已配置", "is-ok"];
  return ["未配置", "is-missing"];
}

const HIDDEN_SETTINGS = new Set(["GENI_STUDIO_TARGET_ROOT"]);
let runtimeSettingsCache = null;

function apiKeyEnvName(backend) {
  if (backend === "cursor") return "CURSOR_API_KEY";
  if (backend === "codex") return "OPENAI_API_KEY";
  return "";
}

function secretMask(length) {
  const n = Math.max(0, Number(length) || 0);
  return n ? "*".repeat(n) : "";
}

const GROUP_ORDER = {
  Agent: ["GENI_STUDIO_BACKEND", "GENI_STUDIO_DEFAULT_MODEL", "GENI_STUDIO_CURSOR_MODEL", "GENI_STUDIO_CODEX_MODEL", "CURSOR_API_KEY", "OPENAI_API_KEY", "LANGSMITH_API_KEY", "LANGSMITH_TRACING"],
  飞书: [
    "GENI_STUDIO_LARK_BACKEND",
    "GENI_STUDIO_PUBLIC_BASE_URL",
    "GENI_STUDIO_FEISHU_NOTIFY_CHAT_ID",
    "GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID",
    "LARK_APP_ID",
    "LARK_APP_SECRET",
    "LARK_VERIFICATION_TOKEN",
    "LARK_ENCRYPT_KEY",
  ],
};

const SETTING_GROUPS = {
  CURSOR_API_KEY: ["Agent", "Cursor API Key"],
  OPENAI_API_KEY: ["Agent", "OpenAI API Key"],
  GENI_STUDIO_BACKEND: ["Agent", "后端"],
  GENI_STUDIO_DEFAULT_MODEL: ["Agent", "默认模型"],
  GENI_STUDIO_CODEX_MODEL: ["Agent", "Codex 模型"],
  GENI_STUDIO_CURSOR_MODEL: ["Agent", "Cursor 模型"],
  LANGSMITH_API_KEY: ["Agent", "LangSmith API Key"],
  LANGSMITH_TRACING: ["Agent", "LangSmith 追踪"],
  GENI_STUDIO_LARK_BACKEND: ["飞书", "飞书后端"],
  LARK_APP_ID: ["飞书", "应用标识"],
  LARK_APP_SECRET: ["飞书", "应用密钥"],
  LARK_VERIFICATION_TOKEN: ["飞书", "校验令牌"],
  LARK_ENCRYPT_KEY: ["飞书", "加密密钥"],
  GENI_STUDIO_PUBLIC_BASE_URL: ["飞书", "Web 地址"],
  GENI_STUDIO_FEISHU_NOTIFY_CHAT_ID: ["飞书", "默认通知群"],
  GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID: ["飞书", "默认通知人"],
};

function settingDetail(item) {
  const hint = (item.value_hint || "").trim();
  if (!hint || hint === "已设置") return "";
  if (item.name === "GENI_STUDIO_DEFAULT_MODEL" && hint === "后端默认") return "";
  if (item.name === "GENI_STUDIO_CURSOR_MODEL" && hint.startsWith("Auto")) return "Auto";
  if (item.name === "GENI_STUDIO_BACKEND" && hint.startsWith("未设置")) {
    const matched = hint.match(/当前生效\s+([^）)\s]+)/);
    return matched ? "当前生效 " + matched[1] : "";
  }
  if (item.name === "LANGSMITH_TRACING") {
    if (hint === "true") return "开启";
    if (hint === "false") return "关闭";
  }
  if (item.name === "GENI_STUDIO_LARK_BACKEND") {
    return hint.replaceAll("lark_cli", "lark-cli").replaceAll("env_bot", "应用凭据").replace(/^默认\s+/, "");
  }
  return hint;
}

function settingRow(item) {
  const meta = SETTING_GROUPS[item.name] || ["其他", item.name];
  const li = document.createElement("li");
  const name = document.createElement("span");
  name.className = "setting-key";
  name.textContent = meta[1];
  name.title = item.name;
  const detail = document.createElement("span");
  detail.className = "setting-value";
  detail.textContent = settingDetail(item);
  const [label, tone] = chipFor(item);
  const chip = document.createElement("span");
  chip.className = "status-chip " + tone;
  chip.textContent = label;
  li.append(name, chip, detail);
  return li;
}

function statusRow(label, value, ok) {
  const li = document.createElement("li");
  const name = document.createElement("span");
  name.className = "setting-key";
  name.textContent = label;
  const chip = document.createElement("span");
  chip.className = "status-chip " + (ok ? "is-ok" : "is-missing");
  chip.textContent = value;
  li.append(name, chip);
  return li;
}

function noteItem(parts) {
  const li = document.createElement("li");
  parts.forEach((part) => {
    if (part && part.code) {
      const code = document.createElement("code");
      code.textContent = part.code;
      li.appendChild(code);
      return;
    }
    li.appendChild(document.createTextNode(part));
  });
  return li;
}

function larkNotes(data) {
  const cli = data.lark_cli || {};
  if (data.lark_backend === "env_bot") {
    return [
      ["飞书使用应用凭据。在 .env 填写应用标识和应用密钥。"],
      ["也可以把飞书后端改为 lark-cli。"],
    ];
  }
  const standing = [
    ["凭据由 lark-cli 管理，不必在这里填写应用密钥。"],
    ["通知群写在项目的 ", { code: "hitl.feishu.notify_chat_id" }, "。"],
  ];
  if (cli.installed && cli.config_ok && cli.bot_ready) {
    return [["发消息使用 lark-cli 的 bot 身份。"], ...standing];
  }
  return [[cli.hint || "先完成 lark-cli 的配置。"], ...standing];
}

function waOption(value, text) {
  const option = document.createElement("wa-option");
  option.value = value;
  option.textContent = text;
  return option;
}

function fillOneWorkflowSelect(el, selected) {
  if (!el) return;
  const value = selected || "";
  const workflows = window.__workflows || [];
  if (el.tagName !== "WA-SELECT") {
    el.value = value;
    return;
  }
  el.replaceChildren(waOption("", "选择流程"));
  for (const item of workflows) {
    const prefix = item.builtin ? "内置 · " : "";
    el.appendChild(waOption(item.workflow_id, prefix + item.title));
  }
  if (value && !workflows.some((item) => item.workflow_id === value)) {
    el.appendChild(waOption(value, value));
  }
  el.value = value;
}

function fillWorkflowOptions(selected) {
  fillOneWorkflowSelect($("fieldProfile"), selected);
  if ($("fieldDirProfile")) fillOneWorkflowSelect($("fieldDirProfile"), $("fieldDirProfile").value);
  const none = !(window.__workflows || []).length;
  if ($("flowProfileEmpty")) $("flowProfileEmpty").hidden = !none;
  if ($("goCreateFlow")) $("goCreateFlow").hidden = !none;
}

window.refreshWorkflowOptions = () => {
  fillWorkflowOptions($("fieldProfile") && $("fieldProfile").value);
};

async function loadLists() {
  const [sr, pr, wr] = await Promise.all([
    fetch("/api/config/scenarios").then((r) => r.json()),
    fetch("/api/config/projects").then((r) => r.json()),
    fetch("/api/workflows").then((r) => r.json()),
  ]);
  window.__workflows = wr.workflows || [];
  fillWorkflowOptions($("fieldProfile") && $("fieldProfile").value);
  const sp = $("scenarioPick");
  window.__scenarios = sr.scenarios || [];
  if (sp) fillScenarioOptions(sp, window.__scenarios, sp.value);
  if ($("fieldScenario")) fillScenarioOptions($("fieldScenario"), window.__scenarios, $("fieldScenario").value);
  const pp = $("projectPick");
  const selected = (pp.value || "").trim();
  pp.replaceChildren(waOption("", "— 选择 —"));
  window.__projects = pr.projects || [];
  window.__nodes = pr.nodes || [];
  for (const p of window.__projects) {
    pp.appendChild(waOption(p.project_id, `${p.title} (${p.project_id})`));
  }
  const stillThere = selected && window.__projects.some((p) => p.project_id === selected);
  pp.value = stillThere ? selected : "";
  fillScenarioOptions($("fieldDirScenario"), window.__scenarios, $("fieldDirScenario").value);
}

async function resolveEffectiveBackend() {
  try {
    const r = await fetch("/api/config/settings");
    const data = await r.json();
    if (r.ok) return resolveBackendPick(data);
  } catch (_) {
    /* 忽略 */
  }
  const pick = ($("backendPick") && $("backendPick").value) || "";
  return pick || "stub";
}

async function loadScenarioYaml(key) {
  if (!key) return;
  const r = await fetch("/api/config/scenarios/" + encodeURIComponent(key));
  const data = await r.json();
  if (r.ok) $("scenarioYaml").value = data.yaml;
}

function fillScenarioOptions(target, scenarios, selected) {
  target.replaceChildren();
  for (const s of scenarios) {
    target.appendChild(waOption(s.scenario_key, `${s.title} (${s.scenario_key})`));
  }
  if (selected) target.value = selected;
}

function renderSkipNodes(nodes, selected) {
  const box = $("skipBox");
  box.replaceChildren();
  const picked = new Set(selected || []);
  for (const name of nodes || []) {
    const input = document.createElement("wa-checkbox");
    input.value = name;
    input.checked = picked.has(name);
    input.textContent = name;
    box.appendChild(input);
  }
}

function syncSkipWrap() {
  $("skipWrap").hidden = $("fieldSkipMode").value !== "custom";
}

function setProjectFieldsEnabled(on) {
  document
    .querySelectorAll(
      "#projectFields wa-input, #projectFields wa-select, #projectFields wa-textarea, #region-scenario wa-select, #region-notify wa-input, #region-extra wa-input, #region-extra wa-select",
    )
    .forEach((el) => {
      el.disabled = !on;
    });
}

async function fillProjectForm(data) {
  fillScenarioOptions($("fieldScenario"), window.__scenarios || [], data.scenario_key);
  $("fieldTitle").value = data.title || "";
  $("fieldDescription").value = data.description || "";
  fillWorkflowOptions(data.profile_id || "");
  $("fieldRetries").value = data.max_dev_retries == null ? "" : String(data.max_dev_retries);
  $("fieldDesign").value = data.design_track_mode || "inherit";
  $("fieldSkipMode").value = data.skip_mode || "inherit";
  $("fieldChat").value = data.notify_chat_id || "";
  $("fieldOpen").value = data.notify_open_id || "";
  $("fieldWorkspace").value = data.workspace || "";
  syncWorkspaceClearButton();
  showFieldInline("fieldWorkspaceError", "");
  void validateWorkspaceField();
  const hint = $("workspaceHint");
  if (data.workspace) {
    hint.textContent = "启动后在这个目录下建立本轮工作树。";
  } else if (data.workspace_resolved) {
    hint.textContent = "未填写时使用：" + data.workspace_resolved;
  } else {
    hint.textContent = "未填写时使用运行配置里的默认工作区。";
  }
  renderSkipNodes(data.nodes, data.skip_nodes);
  syncSkipWrap();
  setProjectFieldsEnabled(true);
}

function clearProjectForm() {
  for (const id of ["fieldTitle", "fieldDescription", "fieldProfile", "fieldRetries", "fieldChat", "fieldOpen", "fieldWorkspace"]) {
    $(id).value = "";
  }
  $("workspaceHint").textContent = "";
  $("fieldDesign").value = "inherit";
  $("fieldSkipMode").value = "inherit";
  renderSkipNodes(window.__nodes || [], []);
  syncSkipWrap();
  updateProjectFlowSummary();
  syncWorkspaceClearButton();
  showFieldInline("fieldWorkspaceError", "");
}

async function loadProjectYaml(id) {
  if (!id) {
    $("projectYaml").value = "";
    clearProjectForm();
    return;
  }
  const [raw, form] = await Promise.all([
    fetch("/api/config/projects/" + encodeURIComponent(id)).then((r) => r.json()),
    fetch("/api/config/projects/" + encodeURIComponent(id) + "/form").then((r) => r.json()),
  ]);
  if (raw.yaml) $("projectYaml").value = raw.yaml;
  if (form.project_id) {
    await fillProjectForm(form);
    if ($("scenarioPick") && form.scenario_key && [...$("scenarioPick").querySelectorAll("wa-option")].some((o) => o.value === form.scenario_key)) {
      $("scenarioPick").value = form.scenario_key;
      await loadScenarioYaml(form.scenario_key);
    }
  }
}

async function saveRuntime() {
  const err = $("runtimeError");
  const btn = $("btnSaveRuntime");
  showError(err, "");
  showSaved($("runtimeSaved"), "");
  btn.disabled = true;
  btn.loading = true;
  const backend = $("backendPick").value;
  const previous = resolveBackendPick(runtimeSettingsCache || {});
  const legacy = (runtimeSettingsCache?.keys || []).find((k) => k.name === "GENI_STUDIO_DEFAULT_MODEL");
  const modelPairs = [];
  if (legacy?.configured && previous !== backend && ["cursor", "codex"].includes(previous)) {
    modelPairs.push([`GENI_STUDIO_${previous.toUpperCase()}_MODEL`, defaultModelFromSettings(runtimeSettingsCache, previous)]);
  }
  if (["cursor", "codex"].includes(backend)) {
    modelPairs.push([`GENI_STUDIO_${backend.toUpperCase()}_MODEL`, (($("modelPick") || $("modelInput"))?.value || "").trim()]);
  }
  const pairs = [
    ...modelPairs,
    ["GENI_STUDIO_BACKEND", backend],
    ["GENI_STUDIO_DEFAULT_MODEL", ""],
    ["GENI_STUDIO_LARK_BACKEND", $("larkBackend").value],
    ["GENI_STUDIO_PUBLIC_BASE_URL", $("publicBase").value.trim()],
    ["GENI_STUDIO_FEISHU_NOTIFY_CHAT_ID", $("feishuChat").value.trim()],
    ["GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID", $("feishuOpen").value.trim()],
  ];
  try {
    for (const [name, value] of pairs) {
      const r = await fetch("/api/config/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: name, value }),
      });
      const data = await r.json();
      if (!r.ok) {
        showError(err, data.detail || "保存失败");
        btn.disabled = false;
        btn.loading = false;
        return;
      }
    }
    const probe = await fetch("/api/config/settings/probe", { method: "POST" });
    const pdata = await probe.json();
    await loadSettings();
    if (!probe.ok) {
      showError(err, pdata.detail || "连通测试没有完成。配置已经写入。");
      return;
    }
    if (pdata.ok) showSaved($("runtimeSaved"), pdata.summary || "已连通。");
    else showError(err, pdata.summary || "连不上。");
  } catch (e) {
    showError(err, "写入或连通测试失败，部分配置可能已保存。请检查后重试。");
  } finally {
    btn.disabled = false;
    btn.loading = false;
  }
}

function agentFieldCopy(backend) {
  if (backend === "cursor") {
    return {
      keyLabel: "Cursor API Key",
      keyHint: "不改就留空。只写入 .env，页面不回显。",
      keyDisabled: false,
    };
  }
  if (backend === "codex") {
    return {
      keyLabel: "OpenAI API Key",
      keyHint: "本机已登录 Codex 时留空。不改就留空，页面不回显。",
      keyDisabled: false,
    };
  }
  return {
    keyLabel: "API Key",
    keyHint: "stub 不调用外部模型，无需填写。",
    keyDisabled: true,
  };
}

function setInputReadonly(el, on) {
  if (!el) return;
  el.readonly = on;
  if (on) el.setAttribute("readonly", "");
  else el.removeAttribute("readonly");
}

function syncApiKeyActions(backend, keyMeta) {
  const del = $("btnDeleteApiKey");
  const add = $("btnAddApiKey");
  if (!del || !add) return;
  const envName = apiKeyEnvName(backend);
  if (!envName) {
    del.hidden = true;
    add.hidden = true;
    return;
  }
  const configured = Boolean(keyMeta && keyMeta.configured);
  del.hidden = !configured;
  add.hidden = configured;
}

function applyApiKeyField(backend, keyMeta) {
  const copy = agentFieldCopy(backend);
  const key = $("apiKeyInput");
  const labelEl = $("apiKeyFieldLabel");
  if (!key) return;
  if (labelEl) labelEl.textContent = copy.keyLabel;
  key.label = "";
  key.type = "text";
  setInputReadonly(key, true);
  if (copy.keyDisabled) {
    key.disabled = true;
    key.value = "";
    key.hint = copy.keyHint;
    key.placeholder = "";
    syncApiKeyActions(backend, keyMeta);
    return;
  }
  key.disabled = false;
  const configured = Boolean(keyMeta && keyMeta.configured);
  if (configured) {
    const len = keyMeta.secret_length || 0;
    key.value = secretMask(len);
    key.hint = "";
    key.placeholder = "";
  } else {
    key.value = "";
    key.hint = "";
    key.placeholder = "—";
  }
  syncApiKeyActions(backend, keyMeta);
}

function openApiKeyDialog() {
  const backend = $("backendPick").value;
  const copy = agentFieldCopy(backend);
  const shell = $("apiKeyDialog");
  const title = $("apiKeyDialogTitle");
  const input = $("apiKeyDialogInput");
  if (!shell || !input) return;
  if (title) title.textContent = `添加 ${copy.keyLabel}`;
  input.label = copy.keyLabel;
  input.value = "";
  showError($("apiKeyDialogError"), "");
  shell.hidden = false;
  input.focus();
}

function closeApiKeyDialog() {
  const shell = $("apiKeyDialog");
  if (shell) shell.hidden = true;
  showError($("apiKeyDialogError"), "");
  const input = $("apiKeyDialogInput");
  if (input) input.value = "";
}

async function saveApiKeyDialog() {
  const backend = $("backendPick").value;
  const name = apiKeyEnvName(backend);
  const input = $("apiKeyDialogInput");
  const btn = $("btnApiKeyDialogSave");
  const err = $("apiKeyDialogError");
  if (!name || !input) return;
  const value = (input.value || "").trim();
  if (!value) {
    showError(err, "请先输入 API Key。");
    return;
  }
  showError(err, "");
  if (btn) {
    btn.disabled = true;
    btn.loading = true;
  }
  try {
    const r = await fetch("/api/config/settings/secret", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: name, value }),
    });
    let data = {};
    try {
      data = await r.json();
    } catch (_parse) {
      data = {};
    }
    if (!r.ok) {
      if (r.status === 404) {
        showError(err, "服务端未加载密钥保存接口。请重启 geni-studio-web 后重试。");
        return;
      }
      showError(err, data.detail || "校验或保存失败");
      return;
    }
    runtimeSettingsCache = data;
    closeApiKeyDialog();
    applyApiKeyField(backend, (data.keys || []).find((k) => k.name === name));
    await refreshDefaultModelPick(backend, defaultModelFromSettings(data));
    const saved = $("runtimeSaved");
    if (saved) showSaved(saved, "API Key 已校验并保存。");
  } catch (e) {
    showError(err, "请求失败。请稍后再试。");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.loading = false;
    }
  }
}

async function deleteConfiguredApiKey() {
  const backend = $("backendPick").value;
  const name = apiKeyEnvName(backend);
  if (!name) return;
  if (!window.confirm("确定删除已保存的 API Key？")) return;
  const err = $("runtimeError");
  showError(err, "");
  const r = await fetch("/api/config/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key: name, value: "" }),
  });
  const data = await r.json();
  if (!r.ok) {
    showError(err, data.detail || "删除失败");
    return;
  }
  runtimeSettingsCache = data;
  applyApiKeyField(backend, (data.keys || []).find((k) => k.name === name));
  await refreshDefaultModelPick(backend, defaultModelFromSettings(data));
}

function resolveBackendPick(data) {
  const backendKey = (data.keys || []).find((k) => k.name === "GENI_STUDIO_BACKEND");
  if (backendKey?.configured) {
    const raw = (backendKey.value_hint || "").trim().toLowerCase();
    if (raw === "cursor" || raw === "codex" || raw === "stub") return raw;
  }
  const eff = (data.effective_backend || "stub").toLowerCase();
  if (eff === "cursor" || eff === "codex") return eff;
  return "stub";
}

function fillRuntime(data) {
  runtimeSettingsCache = data;
  const find = (name) => (data.keys || []).find((k) => k.name === name);
  const backend = resolveBackendPick(data);
  if ($("backendPick")) $("backendPick").value = backend;
  const pickBackend = ($("backendPick") && $("backendPick").value) || backend;
  applyApiKeyField(pickBackend, find(apiKeyEnvName(pickBackend)));
  if ($("larkBackend")) {
    $("larkBackend").value = data.lark_backend === "env_bot" ? "env_bot" : "lark_cli";
  }
  const pub = find("GENI_STUDIO_PUBLIC_BASE_URL");
  if (pub && $("publicBase")) $("publicBase").value = pub.value_hint || "";
  const chat = find("GENI_STUDIO_FEISHU_NOTIFY_CHAT_ID");
  if (chat && $("feishuChat")) $("feishuChat").value = chat.value_hint || "";
  const open = find("GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID");
  if (open && $("feishuOpen")) $("feishuOpen").value = open.value_hint || "";
}

function wireApiKeyButtons() {
  const add = $("btnAddApiKey");
  const del = $("btnDeleteApiKey");
  if (add && add.dataset.wired !== "1") {
    add.dataset.wired = "1";
    add.onclick = () => openApiKeyDialog();
  }
  if (del && del.dataset.wired !== "1") {
    del.dataset.wired = "1";
    del.onclick = () => {
      void deleteConfiguredApiKey();
    };
  }
  const save = $("btnApiKeyDialogSave");
  const cancel = $("btnApiKeyDialogCancel");
  const shell = $("apiKeyDialog");
  if (save && save.dataset.wired !== "1") {
    save.dataset.wired = "1";
    save.onclick = () => {
      void saveApiKeyDialog();
    };
  }
  if (cancel && cancel.dataset.wired !== "1") {
    cancel.dataset.wired = "1";
    cancel.onclick = () => closeApiKeyDialog();
  }
  if (shell && shell.dataset.wired !== "1") {
    shell.dataset.wired = "1";
    shell.addEventListener("click", (event) => {
      if (event.target === shell) closeApiKeyDialog();
    });
  }
}

function defaultModelFromSettings(data, backend = resolveBackendPick(data)) {
  if (backend === "stub") return "";
  const rows = data?.keys || [];
  const key = backend === "codex" ? "GENI_STUDIO_CODEX_MODEL" : "GENI_STUDIO_CURSOR_MODEL";
  const scoped = rows.find((k) => k.name === key);
  if (scoped?.configured) return scoped.value_hint || "";
  const legacy = rows.find((k) => k.name === "GENI_STUDIO_DEFAULT_MODEL");
  return backend === resolveBackendPick(data) && legacy?.configured ? legacy.value_hint || "" : "";
}

let modelRequestVersion = 0;
async function refreshDefaultModelPick(backend, selected) {
  const version = ++modelRequestVersion;
  const el = $("modelPick") || $("modelInput");
  if (!el) return;
  const value = selected !== undefined ? selected : el.value || "";
  let data = { models: [], detail: "" };
  try {
    const q = new URLSearchParams();
    if (backend) q.set("backend", backend);
    const r = await fetch("/api/config/models?" + q.toString());
    if (r.ok) data = await r.json();
    else data.detail = "读不到模型列表。";
  } catch (_err) {
    data.detail = "读不到模型列表。";
  }
  if (version !== modelRequestVersion || ($("backendPick") && $("backendPick").value !== backend)) return;
  const defaultLabel =
    backend === "cursor" ? "Auto（后端默认）" : backend === "codex" ? "Codex 默认" : "后端默认";
  if (el.tagName === "WA-SELECT") {
    el.replaceChildren(waOption("", defaultLabel));
    for (const item of data.models || []) {
      const id = item.id || "";
      if (!id) continue;
      const label = item.label && item.label !== id ? `${item.label} (${id})` : id;
      el.appendChild(waOption(id, label));
    }
    const has = [...el.querySelectorAll("wa-option")].some((o) => o.value === value);
    if (value && !has) el.appendChild(waOption(value, value));
    el.value = value;
  } else {
    el.value = value;
  }
  if (data.detail) el.hint = data.detail;
  else if (backend === "stub") el.hint = "stub 不调用外部模型。";
  else el.hint = "";
  window.__backendModels = data.models || [];
}

async function syncBackendFields() {
  const backend = $("backendPick").value;
  const envName = apiKeyEnvName(backend);
  let data = runtimeSettingsCache;
  if (envName) {
    try {
      const r = await fetch("/api/config/settings");
      if (r.ok) {
        data = await r.json();
        runtimeSettingsCache = data;
      }
    } catch (_err) {
      /* 使用缓存 */
    }
  }
  const find = (name) => (data?.keys || []).find((k) => k.name === name);
  if ($("backendPick").value !== backend) return;
  applyApiKeyField(backend, envName ? find(envName) : null);
  const selected = defaultModelFromSettings(data, backend);
  await refreshDefaultModelPick(backend, selected);
}

if ($("backendPick")) {
  $("backendPick").addEventListener("change", () => {
    void syncBackendFields();
  });
  $("backendPick").addEventListener("input", () => {
    void syncBackendFields();
  });
}
wireApiKeyButtons();

async function loadSettings() {
  const root = $("settingsList");
  const block = $("larkStatusBlock");
  const r = await fetch("/api/config/settings");
  const data = await r.json();
  root.replaceChildren();
  if (!r.ok) {
    const pending = document.createElement("p");
    pending.className = "settings-pending";
    pending.textContent = "读不到环境状态。确认服务已启动后再刷新。";
    root.appendChild(pending);
    if (block) block.hidden = true;
    return;
  }
  const grouped = new Map();
  for (const item of data.keys || []) {
    if (HIDDEN_SETTINGS.has(item.name)) continue;
    const title = (SETTING_GROUPS[item.name] || ["其他"])[0];
    if (!grouped.has(title)) grouped.set(title, []);
    grouped.get(title).push(item);
  }
  for (const title of ["Agent", "飞书", "其他"]) {
    const items = grouped.get(title);
    if (!items || !items.length) continue;
    const order = GROUP_ORDER[title] || [];
    items.sort((a, b) => (order.indexOf(a.name) + 1 || 99) - (order.indexOf(b.name) + 1 || 99));
    const section = document.createElement("section");
    section.className = "env-group";
    const heading = document.createElement("p");
    heading.className = "section-title";
    heading.textContent = title;
    const list = document.createElement("ul");
    list.className = "settings-list";
    items.forEach((item) => list.appendChild(settingRow(item)));
    section.append(heading, list);
    root.appendChild(section);
  }
  const cli = $("larkCliStatus");
  const notes = $("settingsNote");
  if (block && cli && notes && data.lark_cli) {
    const status = data.lark_cli;
    block.hidden = false;
    cli.replaceChildren(
      statusRow("安装", status.installed ? "已安装" : "未安装", status.installed),
      statusRow("配置", status.config_ok ? "已验证" : "未验证", status.config_ok),
      statusRow("发消息", status.bot_ready ? "可发送" : "还不能", status.bot_ready),
    );
    notes.replaceChildren(...larkNotes(data).map(noteItem));
  } else if (block) {
    block.hidden = true;
  }
  fillRuntime(data);
  const backend = ($("backendPick") && $("backendPick").value) || resolveBackendPick(data);
  await refreshDefaultModelPick(backend, defaultModelFromSettings(data));
  await loadBackendModels(backend);
}

let syncRunBackendModelsInflight = null;

async function syncRunBackendModels() {
  if (syncRunBackendModelsInflight) return syncRunBackendModelsInflight;
  syncRunBackendModelsInflight = (async () => {
    const backend = await resolveEffectiveBackend();
    if ($("backendPick")) $("backendPick").value = backend;
    await loadBackendModels(backend);
    window.__runBackendSynced = backend;
    window.dispatchEvent(new CustomEvent("geni-run-backend-models", { detail: { backend } }));
  })();
  try {
    await syncRunBackendModelsInflight;
  } finally {
    syncRunBackendModelsInflight = null;
  }
}

window.syncRunBackendModels = syncRunBackendModels;

async function refreshEffective() {
  const scenario_key = $("scenarioPick").value;
  const project_id = loadedProjectId;
  const q = new URLSearchParams();
  if (scenario_key) q.set("scenario_key", scenario_key);
  if (project_id) q.set("project_id", project_id);
  const r = await fetch("/api/config/effective?" + q.toString());
  const data = await r.json();
  $("effectiveOut").textContent = r.ok
    ? JSON.stringify(data, null, 2)
    : data.detail || "预览失败";
}

$("scenarioPick").addEventListener("change", (e) => {
  loadScenarioYaml(e.target.value);
  refreshEffective();
});

let projectMode = "";
let formSnapshot = "";
let loadedProjectId = "";

function formSnapshotNow() {
  return JSON.stringify(projectFormPayload()) + "\n" + ($("projectYaml").value || "");
}

function markFormClean() {
  formSnapshot = formSnapshotNow();
}

function formIsDirty() {
  if (projectMode === "from-directory") return false;
  if (projectMode === "new") {
    return formSnapshotNow() !== formSnapshot;
  }
  if (!loadedProjectId) return false;
  return formSnapshotNow() !== formSnapshot;
}

function confirmLeave() {
  if (!formIsDirty()) return true;
  return window.confirm("放弃未保存的修改？");
}

function writeProjectUrl(mode, id, replace) {
  let url = "/project";
  if (mode === "open" && id) url += "?project=" + encodeURIComponent(id);
  const hash = mode === "from-directory" ? "#from-directory" : mode === "new" ? "#new" : "#open";
  const next = url + hash;
  if (location.pathname + location.search + location.hash === next) return;
  const method = replace ? "replaceState" : "pushState";
  history[method]({ route: "project" }, "", next);
}

function highlightProjectMode(mode) {
  document.querySelectorAll("[data-project-mode]").forEach((el) => {
    el.classList.toggle("is-active", el.dataset.projectMode === mode);
  });
}

function showProjectPieces(mode) {
  const isNew = mode === "new";
  const isOpen = mode === "open";
  const isDir = mode === "from-directory";
  $("openPicker").hidden = !isOpen;
  $("dirPane").hidden = !isDir;
  if ($("newIdHint")) $("newIdHint").hidden = !isNew;
  $("projectFields").hidden = isDir;
  $("region-scenario").hidden = true;
  $("region-notify").hidden = isDir;
  if ($("region-models")) $("region-models").hidden = isDir;
  if ($("region-extra")) $("region-extra").hidden = isDir;
  $("projectActions").hidden = isDir;
  $("btnCreateProject").hidden = !isNew;
  $("btnSaveProject").hidden = !isOpen || !loadedProjectId;
  if ($("btnDeleteProject")) $("btnDeleteProject").hidden = !isOpen || !loadedProjectId;
  $("projectRaw").hidden = !isOpen;
  if ($("dirPicker")) $("dirPicker").hidden = true;
  highlightProjectMode(mode);
}

async function enterOpen(id, replace) {
  projectMode = "open";
  if (!id) loadedProjectId = "";
  showProjectPieces("open");
  const none = !(window.__projects || []).length;
  $("openEmpty").hidden = !none;
  $("openEmptyAction").hidden = !none;
  $("projectPick").hidden = none;
  $("openHint").hidden = none || Boolean(id);
  if (!id) {
    $("projectPick").value = "";
    $("openProjectId").hidden = true;
    clearProjectForm();
    setProjectFieldsEnabled(false);
    $("projectYaml").value = "";
    markFormClean();
    writeProjectUrl("open", "", replace);
    await refreshEffective();
    return;
  }
  $("projectPick").value = id;
  await loadProjectYaml(id);
  loadedProjectId = id;
  $("btnSaveProject").hidden = false;
  if ($("btnDeleteProject")) $("btnDeleteProject").hidden = false;
  $("openProjectId").hidden = false;
  $("openProjectId").textContent = "项目标识：" + id;
  $("openHint").hidden = true;
  markFormClean();
  writeProjectUrl("open", id, replace);
  await refreshEffective();
}

function enterNew(replace) {
  projectMode = "new";
  showProjectPieces("new");
  clearProjectForm();
  $("projectYaml").value = "";
  setProjectFieldsEnabled(true);
  markFormClean();
  writeProjectUrl("new", "", replace);
}

function enterDirectory(replace) {
  projectMode = "from-directory";
  showProjectPieces("from-directory");
  $("dirCreate").hidden = true;
  $("dirMatches").hidden = true;
  markFormClean();
  writeProjectUrl("from-directory", "", replace);
}

async function requestProjectMode(mode, options) {
  const opts = options || {};
  if (!opts.force && mode === projectMode && !(mode === "open" && opts.project)) return;
  if (!opts.skipDirty && !confirmLeave()) return;
  if (mode === "new") enterNew(opts.replace);
  else if (mode === "from-directory") enterDirectory(opts.replace);
  else await enterOpen(opts.project || "", opts.replace);
}

window.requestProjectMode = requestProjectMode;

window.setProjectMode = (mode, options) => {
  const opts = options || {};
  const params = new URLSearchParams(location.search);
  const fromUrl = params.get("project") || "";
  if (!mode) {
    if (fromUrl) mode = "open";
    else if ((window.__projects || []).length) mode = "open";
    else mode = "new";
  }
  const project = mode === "open" ? (opts.project || fromUrl) : "";
  return requestProjectMode(mode, {
    project,
    replace: true,
    force: Boolean(project) || mode !== projectMode,
    skipDirty: true,
  });
};

if ($("projectPick")) {
  $("projectPick").addEventListener("change", async () => {
    if (projectMode !== "open") return;
    const next = ($("projectPick").value || "").trim();
    showError($("projectError"), "");
    showSaved($("projectSaved"), "");
    if (!next) {
      if (loadedProjectId && !confirmLeave()) {
        $("projectPick").value = loadedProjectId;
        return;
      }
      await enterOpen("", false);
      return;
    }
    if (next === loadedProjectId) return;
    if (!confirmLeave()) {
      $("projectPick").value = loadedProjectId;
      return;
    }
    await enterOpen(next, false);
  });
}

function projectFormPayload() {
  const retries = ($("fieldRetries") && $("fieldRetries").value || "").trim();
  const skipHost = $("skipBox");
  const skip_nodes = skipHost
    ? [...skipHost.querySelectorAll("wa-checkbox")]
        .filter((el) => el.checked)
        .map((el) => el.value)
    : [];
  return {
    title: $("fieldTitle").value.trim(),
    description: $("fieldDescription").value.trim(),
    scenario_key: ($("fieldScenario") && $("fieldScenario").value) || "",
    profile_id: ($("fieldProfile").value || "").trim(),
    max_dev_retries:
      retries === ""
        ? null
        : Number.isFinite(Number(retries)) && Number.isInteger(Number(retries))
          ? Number(retries)
          : null,
    design_track_mode: ($("fieldDesign") && $("fieldDesign").value) || "inherit",
    skip_mode: ($("fieldSkipMode") && $("fieldSkipMode").value) || "inherit",
    skip_nodes,
    notify_chat_id: $("fieldChat").value.trim(),
    notify_open_id: $("fieldOpen").value.trim(),
    workspace: $("fieldWorkspace").value.trim(),
  };
}

async function loadBackendModels(backend) {
  const mode = backend || (await resolveEffectiveBackend());
  const q = new URLSearchParams();
  if (mode) q.set("backend", mode);
  const response = await fetch("/api/config/models?" + q.toString());
  const data = await response.json();
  window.__backendModels = (data && data.models) || [];
  const hint = $("roleModelHint");
  if (hint) {
    const detail = (data && data.detail) || "";
    const source = ((data && data.source) || mode || "").toLowerCase();
    if (source === "stub" || mode === "stub") {
      hint.textContent =
        "当前后端为 stub，不调用外部模型。请在「配置」中选择 Cursor 或 Codex SDK 并写入 .env。";
    } else if (detail) {
      hint.textContent = detail;
    } else {
      hint.textContent = "留空表示沿用配置里的默认模型。这一轮的选择不影响其它 Run。";
    }
  }
}

function updateProjectFlowSummary() {
  const summary = $("projectFlowSummary");
  if (!summary || !$("fieldProfile")) return;
  const id = ($("fieldProfile").value || "").trim();
  const item = (window.__workflows || []).find((workflow) => workflow.workflow_id === id);
  summary.textContent = item ? item.title + "（" + item.workflow_id + "）。" : "还没有选定流程。";
}

$("fieldSkipMode").addEventListener("change", syncSkipWrap);
if ($("fieldProfile")) {
  $("fieldProfile").addEventListener("change", () => {
    updateProjectFlowSummary();
  });
}

$("btnSaveProject").onclick = async () => {
  const id = loadedProjectId;
  showError($("projectError"), "");
  showSaved($("projectSaved"), "");
  if (!id) {
    showError($("projectError"), "先选择要打开的项目。");
    $("projectPick").focus();
    return;
  }
  const payload = projectFormPayload();
  if (!(window.__workflows || []).length) {
    showError($("projectError"), "还没有流程。先创建一份。");
    return;
  }
  if (!payload.profile_id) {
    showError($("projectError"), "先选择流程。");
    $("fieldProfile").focus();
    return;
  }
  if (payload.max_dev_retries != null && !Number.isInteger(payload.max_dev_retries)) {
    showError($("projectError"), "开发重试上限要填整数，或留空沿用项目类型。");
    $("fieldRetries").focus();
    return;
  }
  const workspaceOk = await validateWorkspaceField();
  if (!workspaceOk) return;
  const r = await fetch("/api/config/projects/" + encodeURIComponent(id) + "/form", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await r.json();
  if (!r.ok) {
    showError($("projectError"), data.detail || "没能写入项目。检查选项后再试。");
    return;
  }
  if (data.yaml) $("projectYaml").value = data.yaml;
  showSaved($("projectSaved"), "已写入 " + id + " 的项目字段。");
  markFormClean();
  refreshEffective();
};

if ($("btnDeleteProject")) {
  $("btnDeleteProject").onclick = async () => {
    const id = loadedProjectId;
    showError($("projectError"), "");
    showSaved($("projectSaved"), "");
    if (!id || projectMode !== "open") {
      showError($("projectError"), "先选择要打开的项目。");
      return;
    }
    const title = ($("fieldTitle").value || "").trim() || id;
    if (
      !window.confirm(
        "确定删除项目「" + title + "」（" + id + "）？将永久删除 projects/" + id + "/，无法恢复。",
      )
    ) {
      return;
    }
    const button = $("btnDeleteProject");
    button.loading = true;
    button.disabled = true;
    try {
      const r = await fetch("/api/config/projects/" + encodeURIComponent(id), { method: "DELETE" });
      const data = await r.json();
      if (!r.ok) {
        showError($("projectError"), apiErrorMessage(data, "没能删除项目。"));
        return;
      }
      showSaved($("projectSaved"), "已删除项目 " + id + "。");
      loadedProjectId = "";
      await loadLists();
      await enterOpen("", true);
    } finally {
      button.loading = false;
      button.disabled = false;
    }
  };
}

$("btnSaveRaw").onclick = async () => {
  const id = loadedProjectId;
  showError($("projectError"), "");
  showSaved($("projectSaved"), "");
  if (!id) {
    showError($("projectError"), "先选择一个项目，再覆盖原文。");
    return;
  }
  const r = await fetch("/api/config/projects/" + encodeURIComponent(id), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ yaml: $("projectYaml").value }),
  });
  const data = await r.json();
  if (!r.ok) {
    showError($("projectError"), data.detail || "没能用原文覆盖。检查 YAML 后再试。");
    return;
  }
  await loadProjectYaml(id);
  markFormClean();
  showSaved($("projectSaved"), "已用原文覆盖 " + id + "。");
  refreshEffective();
};

async function createProjectRecord(title) {
  const r = await fetch("/api/config/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title }),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(apiErrorMessage(data, "没能创建项目。"));
  return data.project_id;
}

async function saveProjectForm(id, payload) {
  const r = await fetch("/api/config/projects/" + encodeURIComponent(id) + "/form", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(apiErrorMessage(data, "没能写入项目。检查选项后再试。"));
  return data;
}

$("btnCreateProject").onclick = async () => {
  const title = ($("fieldTitle").value || "").trim();
  showError($("projectError"), "");
  showSaved($("projectSaved"), "");
  if (!title) {
    showError($("projectError"), "先写标题。");
    $("fieldTitle").focus();
    return;
  }
  const payload = projectFormPayload();
  if (!(window.__workflows || []).length) {
    showError($("projectError"), "还没有流程。先创建一份。");
    return;
  }
  if (!payload.profile_id) {
    showError($("projectError"), "先选择流程。");
    $("fieldProfile").focus();
    return;
  }
  if (payload.max_dev_retries != null && !Number.isInteger(payload.max_dev_retries)) {
    showError($("projectError"), "开发重试上限要填整数，或留空沿用项目类型。");
    $("fieldRetries").focus();
    return;
  }
  const workspaceOk = await validateWorkspaceField();
  if (!workspaceOk) return;
  const button = $("btnCreateProject");
  button.loading = true;
  button.disabled = true;
  let id = "";
  try {
    id = await createProjectRecord(title);
    await saveProjectForm(id, payload);
  } catch (err) {
    showError($("projectError"), err.message || "没能创建项目。");
    return;
  } finally {
    button.loading = false;
    button.disabled = false;
  }
  await loadLists();
  showSaved($("projectSaved"), "已创建项目 " + id + "。");
  await enterOpen(id, false);
  if (typeof window.loadRunConfigOptions === "function") await window.loadRunConfigOptions();
};

$("btnGoNew").onclick = () => requestProjectMode("new");

let dirPickerPath = "";
let dirPickerOnUse = null;

function closeDirPicker() {
  const picker = $("dirPicker");
  if (picker) picker.hidden = true;
  dirPickerOnUse = null;
}

async function openDirPicker(initialPath, onUse) {
  dirPickerOnUse = onUse;
  $("dirPicker").hidden = false;
  const start = (initialPath || "").trim();
  const ok = await loadDirPicker(start);
  if (!ok && start) await loadDirPicker("");
}

async function loadDirPicker(path) {
  const note = $("dirPickerNote");
  const err = $("dirPickerError");
  showError(err, "");
  note.hidden = true;
  note.textContent = "";
  const q = new URLSearchParams();
  if (path) q.set("path", path);
  const r = await fetch("/api/config/directories?" + q.toString());
  const data = await r.json();
  if (!r.ok) {
    showError(err, data.detail || "读不到这个目录。");
    return false;
  }
  dirPickerPath = data.path || "";
  $("dirPickerPath").textContent = dirPickerPath;
  const up = $("btnDirUp");
  up.hidden = !data.parent;
  up.dataset.path = data.parent || "";
  const list = $("dirPickerList");
  list.replaceChildren();
  const dirs = data.dirs || [];
  if (!dirs.length) {
    const empty = document.createElement("p");
    empty.className = "hint-block";
    empty.textContent = "这个目录下没有子目录。";
    list.appendChild(empty);
  } else {
    for (const dir of dirs) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "dir-picker-item";
      btn.textContent = dir.name;
      btn.addEventListener("click", () => loadDirPicker(dir.path));
      list.appendChild(btn);
    }
  }
  if (data.truncated) {
    note.hidden = false;
    note.textContent = "子目录较多，只显示前 500 个。";
  }
  return true;
}

if ($("btnPickDirectory")) {
  $("btnPickDirectory").onclick = () =>
    openDirPicker(($("dirPath").value || "").trim(), async (path) => {
      $("dirPath").value = path;
      await openChosenDirectory(path);
    });
}
if ($("btnPickWorkspace")) {
  $("btnPickWorkspace").onclick = () =>
    openDirPicker(($("fieldWorkspace").value || "").trim(), async (path) => {
      $("fieldWorkspace").value = path;
      markFormDirty();
      syncWorkspaceClearButton();
      await validateWorkspaceField();
    });
}
if ($("btnClearWorkspace")) {
  $("btnClearWorkspace").onclick = async () => {
    $("fieldWorkspace").value = "";
    markFormDirty();
    syncWorkspaceClearButton();
    await validateWorkspaceField();
  };
}
if ($("dirPicker")) {
  $("btnDirUp").onclick = () => loadDirPicker($("btnDirUp").dataset.path || "");
  $("btnDirUse").onclick = async () => {
    const path = dirPickerPath;
    const onUse = dirPickerOnUse;
    closeDirPicker();
    if (!path || !onUse) return;
    await onUse(path);
  };
  if ($("dirPath")) {
    $("dirPath").addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      openChosenDirectory(($("dirPath").value || "").trim());
    });
  }
  $("btnDirCancel").onclick = closeDirPicker;
  $("dirPicker").addEventListener("click", (event) => {
    if (event.target === $("dirPicker")) closeDirPicker();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && $("dirPicker") && !$("dirPicker").hidden) closeDirPicker();
  });
}

async function openChosenDirectory(path) {
  showError($("projectError"), "");
  showSaved($("projectSaved"), "");
  $("dirCreate").hidden = true;
  $("dirMatches").hidden = true;
  const r = await fetch("/api/config/projects/by-workspace?path=" + encodeURIComponent(path || ""));
  const data = await r.json();
  if (!r.ok) {
    showError($("projectError"), data.detail || "打不开这个目录。");
    return;
  }
  $("dirPane").dataset.path = data.path || path;
  const ids = data.project_ids || [];
  if (ids.length === 1) {
    await enterOpen(ids[0], false);
    showSaved($("projectSaved"), "这个目录已经是项目 " + ids[0] + "。");
    return;
  }
  if (ids.length > 1) {
    const box = $("dirMatches");
    box.replaceChildren();
    ids.forEach((pid) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "project-mode";
      btn.textContent = pid;
      btn.addEventListener("click", async () => {
        await enterOpen(pid, false);
      });
      box.appendChild(btn);
    });
    box.hidden = false;
    return;
  }
  $("dirPane").dataset.folderName = (data.path || "").split(/[/\\]/).filter(Boolean).pop() || "";
  $("dirCreate").hidden = false;
}

$("btnCreateFromDir").onclick = async () => {
  const folder = $("dirPane").dataset.folderName || "";
  const profile = ($("fieldDirProfile").value || "").trim();
  showError($("projectError"), "");
  if (!folder) {
    showError($("projectError"), "先填写目录。");
    return;
  }
  if (!profile) {
    showError($("projectError"), "先选择流程。");
    return;
  }
  const button = $("btnCreateFromDir");
  button.loading = true;
  button.disabled = true;
  let id = "";
  try {
    id = await createProjectRecord(folder);
    await saveProjectForm(id, {
      title: folder,
      description: "",
      scenario_key: "",
      profile_id: profile,
      max_dev_retries: null,
      design_track_mode: "inherit",
      skip_mode: "inherit",
      skip_nodes: [],
      notify_chat_id: "",
      notify_open_id: "",
      workspace: $("dirPane").dataset.path || ($("dirPath").value || "").trim(),
    });
  } catch (err) {
    showError($("projectError"), err.message || "没能创建项目。");
    return;
  } finally {
    button.loading = false;
    button.disabled = false;
  }
  await loadLists();
  showSaved($("projectSaved"), "已创建项目 " + id + "。");
  await enterOpen(id, false);
  if (typeof window.loadRunConfigOptions === "function") await window.loadRunConfigOptions();
};

$("btnEffective").onclick = refreshEffective;
$("btnSaveRuntime").onclick = saveRuntime;

window.refreshConfigRuntime = loadSettings;

(async function init() {
  try {
  await customElements.whenDefined("wa-select");
  await customElements.whenDefined("wa-option");
  await loadLists();
  const first = $("scenarioPick") && $("scenarioPick").querySelector("wa-option");
  if (first) {
    $("scenarioPick").value = first.value;
    await loadScenarioYaml(first.value);
  }
  await loadSettings();
  document.querySelectorAll(".project-mode").forEach((el) => {
    el.addEventListener("click", (event) => {
      event.preventDefault();
      requestProjectMode(el.dataset.projectMode);
    });
  });
  window.applyProjectLocation = async () => {
    const hashMode = { "#new": "new", "#open": "open", "#from-directory": "from-directory" }[location.hash] || "";
    const opened = new URLSearchParams(location.search).get("project") || "";
    if (opened) await enterOpen(opened, true);
    else if (hashMode === "from-directory") enterDirectory(true);
    else if (hashMode === "new") enterNew(true);
    else if ((window.__projects || []).length) await enterOpen("", true);
    else enterNew(true);
  };
  if (location.pathname === "/project") await window.applyProjectLocation();
  await refreshEffective();
  } catch (err) {
    window.__configInitError = String(err && err.stack || err);
  }
})();
})();
