(function () {
  const $ = (id) => document.getElementById(id);
  let mode = "open";
  let loadedId = "";
  let roles = [];
  let artifacts = [];
  let duties = [];
  let inputs = [];
  let outputs = [];
  let snapshot = "";

  function showError(msg) {
    const el = $("roleError");
    if (!el) return;
    el.hidden = !msg;
    el.textContent = msg || "";
  }

  function showSaved(msg) {
    const el = $("roleSaved");
    if (!el) return;
    el.hidden = !msg;
    el.textContent = msg || "";
  }

  function option(value, label) {
    const el = document.createElement("wa-option");
    el.value = value;
    el.textContent = label;
    return el;
  }

  function currentPayload() {
    return {
      title: ($("roleTitle").value || "").trim(),
      category: $("roleCategory").value || "execution",
      responsibilities: duties.map((item) => item.trim()).filter(Boolean),
      inputs: inputs.filter(Boolean),
      outputs: outputs.filter(Boolean),
      capabilities: [...$("roleCaps").querySelectorAll("input:checked")].map((el) => el.value),
      body: ($("roleBody").value || "").trim(),
    };
  }

  function takeSnapshot() {
    snapshot = JSON.stringify(currentPayload());
  }

  function isDirty() {
    if (!$("roleWork") || $("roleWork").hidden) return false;
    return JSON.stringify(currentPayload()) !== snapshot;
  }

  function confirmLeave() {
    if (!isDirty()) return true;
    return window.confirm("放弃未保存的修改？");
  }

  window.confirmLeaveRole = confirmLeave;

  function syncRolePick() {
    const pick = $("rolePick");
    if (!pick) return;
    pick.hidden = mode !== "open" || !roles.length;
  }

  function showPieces() {
    const editing = mode === "new" || Boolean(loadedId);
    const selecting = mode === "open" && !loadedId;
    $("roleOpen").hidden = !selecting;
    $("roleEditor").hidden = !editing;
    const created = mode === "open" && Boolean(loadedId);
    $("roleCreateRow").hidden = mode !== "new";
    $("roleWork").hidden = !created;
    syncRolePick();
    $("roleHint").hidden = !selecting || !roles.length;
    $("roleIdHint").hidden = created;
    $("roleIdLine").hidden = !created;
    $("roleUsage").hidden = !created;
    if (created) $("roleIdLine").textContent = "角色标识：" + loadedId;
    document.querySelectorAll("[data-role-mode]").forEach((el) => {
      el.classList.toggle("is-active", el.dataset.roleMode === mode);
    });
  }

  function renderNameList(host, values, onChange) {
    host.replaceChildren();
    values.forEach((value, index) => {
      const row = document.createElement("div");
      row.className = "io-line";
      const field = document.createElement("wa-input");
      field.value = value;
      field.label = "职责";
      field.addEventListener("input", () => {
        values[index] = field.value || "";
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "删除";
      remove.addEventListener("click", () => {
        values.splice(index, 1);
        renderNameList(host, values, onChange);
      });
      row.append(field, remove);
      host.appendChild(row);
    });
    if (onChange) onChange();
  }

  function renderArtifactList(host, values, emptyEl) {
    host.replaceChildren();
    if (emptyEl) emptyEl.hidden = values.length > 0;
    values.forEach((value, index) => {
      const row = document.createElement("div");
      row.className = "io-line";
      const select = document.createElement("wa-select");
      select.label = host.id === "roleOutputList" ? "输出" : "输入";
      select.appendChild(option("", "— 选择 —"));
      artifacts.forEach((item) => select.appendChild(option(item.id, item.label)));
      select.value = value || "";
      select.addEventListener("change", () => {
        values[index] = select.value || "";
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "删除";
      remove.addEventListener("click", () => {
        values.splice(index, 1);
        renderArtifactList(host, values, emptyEl);
      });
      row.append(select, remove);
      host.appendChild(row);
    });
  }

  function fillForm(role) {
    $("roleTitle").value = role.title || "";
    $("roleCategory").value = role.category === "management" ? "management" : "execution";
    duties = (role.responsibilities || []).slice();
    inputs = (role.inputs || []).slice();
    outputs = (role.outputs || []).slice();
    $("roleBody").value = role.body || "";
    $("roleCaps").querySelectorAll("input").forEach((el) => {
      el.checked = (role.capabilities || []).includes(el.value);
    });
    renderNameList($("roleDutyList"), duties);
    renderArtifactList($("roleInputList"), inputs, $("roleInputEmpty"));
    renderArtifactList($("roleOutputList"), outputs, null);
    const used = role.used_by || [];
    $("roleUsage").textContent = used.length ? "出现在这些流程里：" + used.join("、") + "。" : "还没有流程用到它。";
    takeSnapshot();
  }

  async function loadLists() {
    const data = await fetch("/api/roles").then((response) => response.json());
    roles = data.roles || [];
    artifacts = data.artifacts || [];
    const pick = $("rolePick");
    const selected = pick.value;
    pick.replaceChildren(option("", "— 选择 —"));
    roles.forEach((item) => pick.appendChild(option(item.id, item.title)));
    if (selected) pick.value = selected;
    const none = !roles.length;
    $("roleEmpty").hidden = !none;
    $("roleEmptyAction").hidden = !none;
    syncRolePick();
    if (mode === "open" && !loadedId) $("roleHint").hidden = none;
  }

  function writeUrl(nextMode, id, replace) {
    let url = "/role";
    if (nextMode === "open" && id) url += "?role=" + encodeURIComponent(id);
    const hash = nextMode === "new" ? "#new" : "#open";
    const next = url + hash;
    if (location.pathname + location.search + location.hash === next) return;
    history[replace ? "replaceState" : "pushState"]({ route: "role" }, "", next);
  }

  async function enterNew(replace) {
    if (!confirmLeave()) return;
    mode = "new";
    loadedId = "";
    showError("");
    showSaved("");
    $("roleTitle").value = "";
    showPieces();
    writeUrl("new", "", replace);
  }

  async function enterOpen(id, replace) {
    if (id && !confirmLeave()) return;
    mode = "open";
    showError("");
    if (!id) {
      loadedId = "";
      showSaved("");
      $("rolePick").value = "";
      await loadLists();
      showPieces();
      writeUrl("open", "", replace);
      return;
    }
    const response = await fetch("/api/roles/" + encodeURIComponent(id));
    const data = await response.json();
    if (!response.ok) {
      showError(data.detail || "没能打开角色。");
      loadedId = "";
      showPieces();
      return;
    }
    loadedId = id;
    await loadLists();
    $("rolePick").value = id;
    fillForm(data.role);
    showSaved("");
    showPieces();
    writeUrl("open", id, replace);
  }

  window.requestRoleMode = (next) => {
    if (next === "new") enterNew(false);
    else enterOpen("", false);
  };

  window.applyRoleLocation = async () => {
    if (location.pathname !== "/role") return;
    const params = new URLSearchParams(location.search);
    const id = params.get("role") || "";
    if (location.hash === "#new") {
      mode = "new";
      loadedId = "";
      showError("");
      showSaved("");
      showPieces();
      return;
    }
    if (id) await enterOpen(id, true);
    else if ((await fetch("/api/roles").then((response) => response.json())).roles.length) await enterOpen("", true);
    else await enterNew(true);
  };

  $("btnRoleGoNew").onclick = () => enterNew(false);

  if ($("rolePick")) {
    $("rolePick").addEventListener("change", async () => {
      if (mode !== "open") return;
      const next = ($("rolePick").value || "").trim();
      showError("");
      showSaved("");
      if (!next) {
        if (loadedId && !confirmLeave()) {
          $("rolePick").value = loadedId;
          return;
        }
        if (loadedId) await enterOpen("", false);
        return;
      }
      if (next === loadedId) return;
      if (!confirmLeave()) {
        $("rolePick").value = loadedId || "";
        return;
      }
      await enterOpen(next, false);
    });
  }

  $("btnCreateRole").onclick = async () => {
    const title = ($("roleTitle").value || "").trim();
    if (!title) {
      showError("先写标题。");
      $("roleTitle").focus();
      return;
    }
    showError("");
    showSaved("");
    const button = $("btnCreateRole");
    button.loading = true;
    button.disabled = true;
    try {
      const response = await fetch("/api/roles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      const data = await response.json();
      if (!response.ok) {
        showError(data.detail || "没能创建角色。");
        return;
      }
      loadedId = data.role.id;
      mode = "open";
      await loadLists();
      fillForm(data.role);
      showPieces();
      showSaved("已创建角色 " + loadedId + "。");
      writeUrl("open", loadedId, false);
    } catch (err) {
      showError(err.message || "没能创建角色。");
    } finally {
      button.loading = false;
      button.disabled = false;
    }
  };

  $("btnAddDuty").onclick = () => {
    duties.push("");
    renderNameList($("roleDutyList"), duties);
  };
  $("btnAddRoleInput").onclick = () => {
    inputs.push("");
    renderArtifactList($("roleInputList"), inputs, $("roleInputEmpty"));
  };
  $("btnAddRoleOutput").onclick = () => {
    outputs.push("");
    renderArtifactList($("roleOutputList"), outputs, null);
  };

  $("btnSaveRole").onclick = async () => {
    if (!loadedId) return;
    showError("");
    showSaved("");
    const response = await fetch("/api/roles/" + encodeURIComponent(loadedId), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentPayload()),
    });
    const data = await response.json();
    if (!response.ok) {
      showError(data.detail || "没能保存角色。");
      return;
    }
    await loadLists();
    fillForm(data.role);
    showSaved("已保存 " + loadedId + "。");
  };

  $("btnDeleteRole").onclick = async () => {
    if (!loadedId) return;
    const title = ($("roleTitle").value || "").trim() || loadedId;
    if (!window.confirm("删除「" + title + "」？")) return;
    showError("");
    showSaved("");
    const response = await fetch("/api/roles/" + encodeURIComponent(loadedId), { method: "DELETE" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      showError(data.detail || "没能删除角色。");
      return;
    }
    loadedId = "";
    mode = "open";
    await loadLists();
    showPieces();
    showSaved("已删除角色。");
    writeUrl("open", "", false);
  };

  if (location.pathname === "/role") window.applyRoleLocation();
})();
