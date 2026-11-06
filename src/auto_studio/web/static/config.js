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
  pp.replaceChildren(waOption("", "— 选择 —"));
  for (const p of pr.projects || []) {
    pp.appendChild(waOption(p.project_id, `${p.title} (${p.project_id})`));
  }
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
  for (const id of ["fieldTitle", "fieldDescription", "fieldProfile", "fieldRetries", "fieldChat", "fieldOpen", "fieldWorkspace"]) {
    $(id).value = "";
  }
  $("workspaceHint").textContent = "";
  $("fieldDesign").value = "inherit";
  $("fieldSkipMode").value = "inherit";
  renderSkipNodes([], []);
  syncSkipWrap();
  setProjectFieldsEnabled(false);
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
    if (form.scenario_key && [...$("scenarioPick").options].some((o) => o.value === form.scenario_key)) {
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
  const project_id = $("projectPick").value;
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

$("projectPick").addEventListener("change", async (e) => {
  await loadProjectYaml(e.target.value);
  await refreshEffective();
});

function projectFormPayload() {
  const retries = $("fieldRetries").value.trim();
  const skip_nodes = [...$("skipBox").querySelectorAll("wa-checkbox")]
    .filter((el) => el.checked)
    .map((el) => el.value);
  return {
    title: $("fieldTitle").value.trim(),
    description: $("fieldDescription").value.trim(),
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
  const id = $("projectPick").value;
  showError($("projectError"), "");
  showSaved($("projectSaved"), "");
  if (!id) {
    showError($("projectError"), "先选择一个项目，或在下面新建。");
    $("projectPick").focus();
    return;
  }
  const payload = projectFormPayload();
  if (payload.max_dev_retries != null && !Number.isInteger(payload.max_dev_retries)) {
    showError($("projectError"), "开发重试上限要填整数，或留空沿用场景。");
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
  refreshEffective();
};

$("btnSaveRaw").onclick = async () => {
  const id = $("projectPick").value;
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
  showSaved($("projectSaved"), "已用原文覆盖 " + id + "。");
  refreshEffective();
};

$("btnNewProject").onclick = () => {
  const row = $("newProjectRow");
  row.hidden = false;
  $("newProjectId").focus();
};

$("btnCancelProject").onclick = () => {
  $("newProjectRow").hidden = true;
  $("newProjectId").value = "";
  showError($("projectError"), "");
};

$("btnCreateProject").onclick = async () => {
  const id = $("newProjectId").value.trim();
  showError($("projectError"), "");
  showSaved($("projectSaved"), "");
  if (!/^[A-Za-z][A-Za-z0-9_-]*$/.test(id)) {
    showError($("projectError"), "项目标识要以字母开头，后面只含字母、数字、_ 和 -。");
    $("newProjectId").focus();
    return;
  }
  const r = await fetch("/api/config/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: id }),
  });
  const data = await r.json();
  if (!r.ok) {
    showError($("projectError"), data.detail || "没能创建项目。换一个标识再试。");
    return;
  }
  await loadLists();
  $("projectPick").value = id;
  $("newProjectId").value = "";
  $("newProjectRow").hidden = true;
  await loadProjectYaml(id);
  showSaved($("projectSaved"), "已创建项目 " + id + "。");
  refreshEffective();
};

$("btnEffective").onclick = refreshEffective;
$("btnSaveRuntime").onclick = saveRuntime;

(async function init() {
  await customElements.whenDefined("wa-select");
  await customElements.whenDefined("wa-option");
  await loadLists();
  const first = $("scenarioPick").querySelector("wa-option");
  if (first) {
    $("scenarioPick").value = first.value;
    await loadScenarioYaml(first.value);
  }
  await loadSettings();
  if (!$("projectPick").value) setProjectFieldsEnabled(false);
  await refreshEffective();
})();
})();
