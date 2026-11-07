(function () {
const $ = (id) => document.getElementById(id);

function showError(el, msg) {
  if (!msg) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = msg;
}

function showSaved(el, msg) {
  if (!el) return;
  el.hidden = !msg;
  el.textContent = msg || "";
}

function chipFor(item) {
  if (item.name === "AUTO_STUDIO_CURSOR_MODEL" && !item.configured) return ["默认", "is-ok"];
  if (item.name === "AUTO_STUDIO_BACKEND" && !item.configured) return ["自动", "is-ok"];
  if (item.configured) return ["已配置", "is-ok"];
  return ["未配置", "is-missing"];
}

function waOption(value, text) {
  const option = document.createElement("wa-option");
  option.value = value;
  option.textContent = text;
  return option;
}

async function loadLists() {
  const [sr, pr] = await Promise.all([
    fetch("/api/config/scenarios").then((r) => r.json()),
    fetch("/api/config/projects").then((r) => r.json()),
  ]);
  const sp = $("scenarioPick");
  window.__scenarios = sr.scenarios || [];
  fillScenarioOptions(sp, window.__scenarios, sp.value);
  fillScenarioOptions($("fieldScenario"), window.__scenarios, $("fieldScenario").value);
  const pp = $("projectPick");
  const selected = pp.value;
  pp.replaceChildren(waOption("", "— 选择 —"));
  window.__projects = pr.projects || [];
  window.__nodes = pr.nodes || [];
  for (const p of window.__projects) {
    pp.appendChild(waOption(p.project_id, `${p.title} (${p.project_id})`));
  }
  if (selected) pp.value = selected;
  fillScenarioOptions($("fieldDirScenario"), window.__scenarios, $("fieldDirScenario").value);
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
      "#projectFields wa-input, #projectFields wa-select, #projectFields wa-textarea, #region-scenario wa-select, #region-notify wa-input",
    )
    .forEach((el) => {
      el.disabled = !on;
    });
}

function fillProjectForm(data) {
  fillScenarioOptions($("fieldScenario"), window.__scenarios || [], data.scenario_key);
  $("fieldTitle").value = data.title || "";
  $("fieldDescription").value = data.description || "";
  $("fieldRemoteUrl").value = data.remote_url || "";
  $("fieldProfile").value = data.profile_id || "";
  $("fieldRetries").value = data.max_dev_retries == null ? "" : String(data.max_dev_retries);
  $("fieldDesign").value = data.design_track_mode || "inherit";
  $("fieldSkipMode").value = data.skip_mode || "inherit";
  $("fieldChat").value = data.notify_chat_id || "";
  $("fieldOpen").value = data.notify_open_id || "";
  $("fieldWorkspace").value = data.workspace || "";
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
  for (const id of ["fieldTitle", "fieldDescription", "fieldRemoteUrl", "fieldProfile", "fieldRetries", "fieldChat", "fieldOpen", "fieldWorkspace"]) {
    $(id).value = "";
  }
  $("workspaceHint").textContent = "";
  $("fieldDesign").value = "inherit";
  $("fieldSkipMode").value = "inherit";
  renderSkipNodes(window.__nodes || [], []);
  syncSkipWrap();
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
    fillProjectForm(form);
    if (form.scenario_key && [...$("scenarioPick").querySelectorAll("wa-option")].some((o) => o.value === form.scenario_key)) {
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
  const pairs = [
    ["AUTO_STUDIO_BACKEND", $("backendPick").value],
    ["AUTO_STUDIO_CURSOR_MODEL", $("modelInput").value.trim()],
    ["AUTO_STUDIO_TARGET_ROOT", $("targetInput").value.trim()],
    ["AUTO_STUDIO_LARK_BACKEND", $("larkBackend").value],
    ["AUTO_STUDIO_PUBLIC_BASE_URL", $("publicBase").value.trim()],
    ["AUTO_STUDIO_FEISHU_NOTIFY_CHAT_ID", $("feishuChat").value.trim()],
    ["AUTO_STUDIO_FEISHU_NOTIFY_OPEN_ID", $("feishuOpen").value.trim()],
  ];
  const key = $("apiKeyInput").value;
  if (key) pairs.push(["CURSOR_API_KEY", key]);
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
  $("apiKeyInput").value = "";
  try {
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
    showError(err, "连通测试没有返回。配置已经写入，可再点一次写入。");
  } finally {
    btn.disabled = false;
    btn.loading = false;
  }
}

function fillRuntime(data) {
  const find = (name) => (data.keys || []).find((k) => k.name === name);
  if ($("backendPick")) {
    $("backendPick").value = data.effective_backend === "cursor" ? "cursor" : "stub";
  }
  const model = find("AUTO_STUDIO_CURSOR_MODEL");
  if (model && $("modelInput") && model.value_hint && !model.value_hint.startsWith("Auto")) {
    $("modelInput").value = model.value_hint;
  }
  const target = find("AUTO_STUDIO_TARGET_ROOT");
  if (target && $("targetInput")) $("targetInput").value = target.value_hint || "";
  if ($("larkBackend")) {
    $("larkBackend").value = data.lark_backend === "env_bot" ? "env_bot" : "lark_cli";
  }
  const pub = find("AUTO_STUDIO_PUBLIC_BASE_URL");
  if (pub && $("publicBase")) $("publicBase").value = pub.value_hint || "";
  const chat = find("AUTO_STUDIO_FEISHU_NOTIFY_CHAT_ID");
  if (chat && $("feishuChat")) $("feishuChat").value = chat.value_hint || "";
  const open = find("AUTO_STUDIO_FEISHU_NOTIFY_OPEN_ID");
  if (open && $("feishuOpen")) $("feishuOpen").value = open.value_hint || "";
}

async function loadSettings() {
  const ul = $("settingsList");
  const r = await fetch("/api/config/settings");
  const data = await r.json();
  ul.replaceChildren();
  if (!r.ok) {
    const li = document.createElement("li");
    li.className = "settings-pending";
    li.textContent = "读不到环境状态。确认服务已启动后再刷新。";
    ul.appendChild(li);
    return;
  }
  for (const k of data.keys || []) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.className = "setting-key";
    name.textContent = k.name;
    const state = document.createElement("span");
    state.className = "setting-value";
    state.textContent = k.value_hint === "已设置" ? "不在页面显示" : (k.value_hint || "—");
    const [label, tone] = chipFor(k);
    const chip = document.createElement("span");
    chip.className = "status-chip " + tone;
    chip.textContent = label;
    li.append(name, state, chip);
    ul.appendChild(li);
  }
  $("settingsNote").textContent = data.note || "";
  const lc = $("larkCliStatus");
  if (lc && data.lark_cli) {
    const b = data.lark_backend || "lark_cli";
    const x = data.lark_cli;
    lc.textContent = [
      `飞书后端 ${b}`,
      `lark-cli ${x.installed ? "已安装" : "未安装"}`,
      x.config_ok ? "配置已验证" : "配置未验证",
      x.bot_ready ? "可以发消息" : "还不能发消息",
      x.hint || "",
    ]
      .filter(Boolean)
      .join("\n");
  }
  fillRuntime(data);
}

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
    const id = ($("newProjectId").value || "").trim();
    return Boolean(id) || formSnapshotNow() !== formSnapshot;
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
  $("newIdRow").hidden = !isNew;
  $("projectFields").hidden = isDir;
  $("region-scenario").hidden = isDir;
  $("region-notify").hidden = isDir;
  $("projectActions").hidden = isDir;
  $("btnCreateProject").hidden = !isNew;
  $("btnSaveProject").hidden = !isOpen || !loadedProjectId;
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
  if ($("openChosenAction")) $("openChosenAction").hidden = none;
  $("openHint").hidden = none || Boolean(id);
  if (!id) {
    $("projectPick").value = "";
    $("openProjectId").hidden = true;
    clearProjectForm();
    setProjectFieldsEnabled(false);
    $("projectYaml").value = "";
    markFormClean();
    writeProjectUrl("open", "", replace);
    return;
  }
  $("projectPick").value = id;
  await loadProjectYaml(id);
  loadedProjectId = id;
  $("btnSaveProject").hidden = false;
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
  $("newProjectId").value = "";
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

if ($("btnOpenChosen")) $("btnOpenChosen").onclick = async () => {
  const next = $("projectPick").value;
  showError($("projectError"), "");
  showSaved($("projectSaved"), "");
  if (!next) {
    showError($("projectError"), "先选择要打开的项目。");
    $("projectPick").focus();
    return;
  }
  if (next === loadedProjectId) return;
  if (!confirmLeave()) {
    $("projectPick").value = loadedProjectId;
    return;
  }
  await enterOpen(next, false);
};

function projectFormPayload() {
  const retries = $("fieldRetries").value.trim();
  const skip_nodes = [...$("skipBox").querySelectorAll("wa-checkbox")]
    .filter((el) => el.checked)
    .map((el) => el.value);
  return {
    title: $("fieldTitle").value.trim(),
    description: $("fieldDescription").value.trim(),
    remote_url: $("fieldRemoteUrl").value.trim(),
    scenario_key: $("fieldScenario").value,
    profile_id: $("fieldProfile").value.trim(),
    max_dev_retries: retries === "" ? null : Number(retries),
    design_track_mode: $("fieldDesign").value,
    skip_mode: $("fieldSkipMode").value,
    skip_nodes,
    notify_chat_id: $("fieldChat").value.trim(),
    notify_open_id: $("fieldOpen").value.trim(),
    workspace: $("fieldWorkspace").value.trim(),
  };
}

$("fieldSkipMode").addEventListener("change", syncSkipWrap);

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
  if (payload.max_dev_retries != null && !Number.isInteger(payload.max_dev_retries)) {
    showError($("projectError"), "开发重试上限要填整数，或留空沿用项目类型。");
    $("fieldRetries").focus();
    return;
  }
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

const PROJECT_ID_RE = /^[A-Za-z][A-Za-z0-9_-]*$/;

async function createProjectRecord(id) {
  const r = await fetch("/api/config/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: id }),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || "没能创建项目。换一个标识再试。");
}

async function saveProjectForm(id, payload) {
  const r = await fetch("/api/config/projects/" + encodeURIComponent(id) + "/form", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || "没能写入项目。检查选项后再试。");
  return data;
}

$("btnCreateProject").onclick = async () => {
  const id = $("newProjectId").value.trim();
  showError($("projectError"), "");
  showSaved($("projectSaved"), "");
  if (!PROJECT_ID_RE.test(id)) {
    showError($("projectError"), "项目标识要以字母开头，后面只含字母、数字、_ 和 -。");
    $("newProjectId").focus();
    return;
  }
  const payload = projectFormPayload();
  if (payload.max_dev_retries != null && !Number.isInteger(payload.max_dev_retries)) {
    showError($("projectError"), "开发重试上限要填整数，或留空沿用项目类型。");
    $("fieldRetries").focus();
    return;
  }
  try {
    await createProjectRecord(id);
    await saveProjectForm(id, payload);
  } catch (err) {
    showError($("projectError"), err.message || "没能创建项目。");
    return;
  }
  await loadLists();
  showSaved($("projectSaved"), "已创建项目 " + id + "。");
  await enterOpen(id, false);
};

$("btnGoNew").onclick = () => requestProjectMode("new");

let dirPickerPath = "";

function closeDirPicker() {
  const picker = $("dirPicker");
  if (picker) picker.hidden = true;
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
  $("btnPickDirectory").onclick = async () => {
    $("dirPicker").hidden = false;
    const current = ($("dirPath").value || "").trim();
    const ok = await loadDirPicker(current);
    if (!ok && current) await loadDirPicker("");
  };
  $("btnDirUp").onclick = () => loadDirPicker($("btnDirUp").dataset.path || "");
  $("btnDirUse").onclick = async () => {
    const path = dirPickerPath;
    closeDirPicker();
    if (!path) return;
    $("dirPath").value = path;
    await openChosenDirectory(path);
  };
  $("dirPath").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    openChosenDirectory(($("dirPath").value || "").trim());
  });
  $("btnDirCancel").onclick = closeDirPicker;
  $("dirPicker").addEventListener("click", (event) => {
    if (event.target === $("dirPicker")) closeDirPicker();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && $("dirPicker") && !$("dirPicker").hidden) closeDirPicker();
  });
}

async function fillRemoteFromGit(remote) {
  const url = (remote || "").trim();
  if (!url || ($("fieldRemoteUrl").value || "").trim() || !loadedProjectId) return false;
  $("fieldRemoteUrl").value = url;
  const r = await fetch("/api/config/projects/" + encodeURIComponent(loadedProjectId) + "/form", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(projectFormPayload()),
  });
  const data = await r.json();
  if (!r.ok) {
    showError($("projectError"), data.detail || "没能写入远程仓库。");
    return false;
  }
  if (data.yaml) $("projectYaml").value = data.yaml;
  markFormClean();
  return true;
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
  $("dirPane").dataset.remoteUrl = data.remote_url || "";
  const ids = data.project_ids || [];
  if (ids.length === 1) {
    await enterOpen(ids[0], false);
    const wrote = await fillRemoteFromGit(data.remote_url);
    showSaved(
      $("projectSaved"),
      "这个目录已经是项目 " + ids[0] + "。" + (wrote ? "已从 git 写入远程仓库。" : ""),
    );
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
        await fillRemoteFromGit($("dirPane").dataset.remoteUrl || "");
      });
      box.appendChild(btn);
    });
    box.hidden = false;
    return;
  }
  $("fieldDirId").value = data.suggested_id || "";
  $("dirCreate").hidden = false;
}

$("btnCreateFromDir").onclick = async () => {
  const id = $("fieldDirId").value.trim();
  const scenario = $("fieldDirScenario").value;
  showError($("projectError"), "");
  if (!PROJECT_ID_RE.test(id)) {
    showError($("projectError"), "项目标识要以字母开头，后面只含字母、数字、_ 和 -。");
    $("fieldDirId").focus();
    return;
  }
  if (!scenario) {
    showError($("projectError"), "先选择项目类型。");
    return;
  }
  try {
    await createProjectRecord(id);
    await saveProjectForm(id, {
      title: id,
      description: "",
      remote_url: $("dirPane").dataset.remoteUrl || "",
      scenario_key: scenario,
      profile_id: "",
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
  }
  await loadLists();
  showSaved($("projectSaved"), "已创建项目 " + id + "。");
  await enterOpen(id, false);
};

$("btnEffective").onclick = refreshEffective;
$("btnSaveRuntime").onclick = saveRuntime;

(async function init() {
  try {
  await customElements.whenDefined("wa-select");
  await customElements.whenDefined("wa-option");
  await loadLists();
  const first = $("scenarioPick").querySelector("wa-option");
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
  await window.applyProjectLocation();
  await refreshEffective();
  } catch (err) {
    window.__configInitError = String(err && err.stack || err);
  }
})();
})();
