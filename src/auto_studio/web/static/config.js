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

async function loadLists() {
  const [sr, pr] = await Promise.all([
    fetch("/api/config/scenarios").then((r) => r.json()),
    fetch("/api/config/projects").then((r) => r.json()),
  ]);
  const sp = $("scenarioPick");
  sp.innerHTML = "";
  for (const s of sr.scenarios || []) {
    const o = document.createElement("option");
    o.value = s.scenario_key;
    o.textContent = `${s.title} (${s.scenario_key})`;
    sp.appendChild(o);
  }
  const pp = $("projectPick");
  pp.innerHTML = '<option value="">— 选择 —</option>';
  for (const p of pr.projects || []) {
    const o = document.createElement("option");
    o.value = p.project_id;
    o.textContent = `${p.title} (${p.project_id})`;
    pp.appendChild(o);
  }
}

async function loadScenarioYaml(key) {
  if (!key) return;
  const r = await fetch("/api/config/scenarios/" + encodeURIComponent(key));
  const data = await r.json();
  if (r.ok) $("scenarioYaml").value = data.yaml;
}

async function loadProjectYaml(id) {
  if (!id) {
    $("projectYaml").value = "";
    return;
  }
  const r = await fetch("/api/config/projects/" + encodeURIComponent(id));
  const data = await r.json();
  if (r.ok) $("projectYaml").value = data.yaml;
}

async function loadSettings() {
  const r = await fetch("/api/config/settings");
  const data = await r.json();
  const ul = $("settingsList");
  ul.innerHTML = "";
  for (const k of data.keys || []) {
    const li = document.createElement("li");
    li.innerHTML = `<span>${k.name}</span><span>${k.configured ? "已配置" : "未配置"}</span>`;
    ul.appendChild(li);
  }
  $("settingsNote").textContent = data.note || "";
  const lc = $("larkCliStatus");
  if (lc && data.lark_cli) {
    const b = data.lark_backend || "lark_cli";
    const x = data.lark_cli;
    lc.textContent = [
      `飞书后端：${b}`,
      `lark-cli：${x.installed ? "已安装" : "未安装"}`,
      x.config_ok ? "配置已验证" : "配置未验证",
      x.bot_ready ? "Bot 可发消息" : "Bot 未就绪",
      x.hint || "",
    ]
      .filter(Boolean)
      .join(" · ");
  }
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

$("projectPick").addEventListener("change", (e) => {
  loadProjectYaml(e.target.value);
  refreshEffective();
});

$("btnSaveProject").onclick = async () => {
  const id = $("projectPick").value;
  showError($("projectError"), "");
  if (!id) {
    showError($("projectError"), "请先选择或新建项目。");
    return;
  }
  const r = await fetch("/api/config/projects/" + encodeURIComponent(id), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ yaml: $("projectYaml").value }),
  });
  const data = await r.json();
  if (!r.ok) showError($("projectError"), data.detail || "保存失败");
  else refreshEffective();
};

$("btnNewProject").onclick = async () => {
  const id = prompt("新 project_id（字母开头，可含 _-）：");
  if (!id) return;
  const r = await fetch("/api/config/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: id.trim() }),
  });
  const data = await r.json();
  if (!r.ok) {
    showError($("projectError"), data.detail || "创建失败");
    return;
  }
  await loadLists();
  $("projectPick").value = id.trim();
  await loadProjectYaml(id.trim());
};

$("btnEffective").onclick = refreshEffective;

(function initTheme() {
  const key = "auto_studio_hitl_theme";
  const btn = $("themeToggle");
  function sync() {
    btn.textContent =
      document.documentElement.getAttribute("data-theme") === "dark" ? "白天" : "夜晚";
  }
  btn.onclick = () => {
    const next =
      document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem(key, next);
    sync();
  };
  sync();
})();

(async function init() {
  await loadLists();
  if ($("scenarioPick").options.length) {
    $("scenarioPick").selectedIndex = 0;
    await loadScenarioYaml($("scenarioPick").value);
  }
  await loadSettings();
  await refreshEffective();
})();
