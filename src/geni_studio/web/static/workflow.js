(function () {
  const $ = (id) => document.getElementById(id);
  const NODE_GAP = 56;
  const MAX_GAP = 140;
  const BOARD_END = 40;
  const NODE_W = 104;
  const LANE_H = 88;
  const ORIGIN_X = 100;
  const TRACK_TOP = 22;
  const TRACK_GAP = 22;
  const LOOP_OUT = 8;
  const LOOP_IN = 24;
  const LOOP_DY = 11;
  /** 编辑器有控件的节点字段；其余字段（handler、routes、when、instruction 等）原样带回保存。 */
  const MANAGED_KEYS = new Set([
    "id", "kind", "name", "role", "returns_to", "decision", "max_loops", "reject_to",
    "commits_on_branch", "subgraph_id", "branches", "join", "inputs", "outputs", "contractTouched",
    "items", "pass_rule",
  ]);
  const LOOP_CHOICES = [1, 2, 3, 4, 5, 10];
  const DEFAULT_LOOPS = 3;
  const KIND_LABELS = {
    start: "启动", end: "结束", activity: "活动", gate: "决策点", parallel: "并行", subgraph: "子图", system: "系统节点",
  };
  const DECISIONS = [{ id: "approve", label: "批准或驳回" }, { id: "pick", label: "择一（两路对照）" }];
  const JOINS = [{ id: "merge", label: "合并各路" }, { id: "compare", label: "对照择一" }];
  const PASS_RULES = [
    { id: "all", label: "全部通过才放行", hint: "任一项不通过，即按“不通过时”的去向退回，并把该项原因交给那个活动。" },
    { id: "manual", label: "只作核对清单", hint: "逐项结论只作记录，最后仍由人选择批准或不通过。" },
  ];

  let mode = "new";
  let loadedId = "";
  let ignorePick = false;
  let selectedId = "";
  let selectedEdge = null;
  let boardGap = NODE_GAP;
  let fittedWidth = -1;
  let roles = [];
  let workflows = [];
  let graph = blankGraph("", "");
  let snapshot = "";
  let savedGraph = null;
  let usage = null;
  let versions = null;
  let showStats = (() => {
    try {
      return localStorage.getItem("geni.flowStats") === "1";
    } catch (_) {
      return false;
    }
  })();
  let stats = null;
  let trail = [];
  let undoStack = [];
  let undoAt = -1;
  let undoStamp = 0;
  let problems = null;
  let checkedSnap = "";
  let checkTimer = 0;
  let checkSeq = 0;
  let nameEdit = "";
  let yamlText = "";

  function blankGraph(id, title) {
    return {
      workflow_id: id,
      title: title || "",
      description: "",
      nodes: [
        { id: "start", kind: "start", name: "启动", role: "human", returns_to: "" },
        { id: "end", kind: "end", name: "结束", role: "human", returns_to: "" },
      ],
    };
  }

  function showError(msg) {
    const el = $("flowError");
    el.hidden = !msg;
    el.textContent = msg || "";
  }

  function showSaved(msg) {
    const el = $("flowSaved");
    el.hidden = !msg;
    el.textContent = msg || "";
  }

  function option(value, text) {
    const el = document.createElement("wa-option");
    el.value = value;
    el.textContent = text;
    return el;
  }

  function roleLabel(roleId) {
    if (roleId === "human") return "人类";
    const found = roles.find((item) => item.id === roleId);
    return found ? found.label : roleId;
  }

  function roleRecord(roleId) {
    return roles.find((item) => item.id === roleId) || null;
  }

  function normalizeOutputs(value) {
    if (!Array.isArray(value)) return [];
    return value.map((item) => {
      if (typeof item === "string") return { name: item, source: "file", template: "", plain: true };
      const source = item && item.source === "link" ? "link" : "file";
      return { name: (item && item.name) || "", source, template: (item && item.template) || "" };
    }).filter((item) => item.name);
  }

  function normalizeNode(node) {
    const explicit = Array.isArray(node.inputs) || Array.isArray(node.outputs);
    const item = {
      id: node.id,
      kind: node.kind,
      name: node.name,
      role: node.role || "",
      returns_to: node.returns_to || "",
      decision: node.decision || "",
    };
    const loops = Number(node.max_loops);
    if (item.returns_to && Number.isInteger(loops) && loops >= 1) item.max_loops = loops;
    if (node.reject_to) item.reject_to = node.reject_to;
    if (node.commits_on_branch) item.commits_on_branch = true;
    if (node.kind === "gate" && Array.isArray(node.items) && node.items.length) {
      item.items = node.items.map((entry) => {
        const one = { id: String(entry.id || ""), title: String(entry.title || "") };
        if (entry.hint) one.hint = String(entry.hint);
        if (entry.required === false) one.required = false;
        return one;
      });
      if (node.pass_rule === "manual") item.pass_rule = "manual";
    }
    if (node.kind === "subgraph") {
      item.role = "";
      item.returns_to = "";
      item.subgraph_id = node.subgraph_id || "";
    }
    if (node.kind === "parallel") {
      item.role = "";
      item.returns_to = "";
      item.branches = (node.branches || []).map((branch, index) => ({
        id: branch.id || ("b" + (index + 1)),
        name: branch.name || "",
        nodes: (branch.nodes || []).map((child) => normalizeNode(child)),
      }));
      if (node.join === "compare") item.join = "compare";
    }
    // 只写了 inputs 或 outputs 之一时，另一侧仍按角色默认，不能补成空表。
    if (explicit && node.kind === "activity") {
      if (Array.isArray(node.inputs)) item.inputs = node.inputs.map((name) => String(name));
      if (Array.isArray(node.outputs)) item.outputs = normalizeOutputs(node.outputs);
      item.contractTouched = true;
    }
    Object.keys(node).forEach((key) => {
      if (!MANAGED_KEYS.has(key) && !(key in item) && node[key] !== undefined && node[key] !== null) item[key] = node[key];
    });
    return item;
  }

  function applyRoleContract(node, roleId, touched) {
    const found = roleRecord(roleId);
    node.inputs = found && found.inputs ? found.inputs.slice() : [];
    node.outputs = ((found && found.outputs) || []).map((name) => ({ name, source: "file", template: "", plain: true }));
    node.contractTouched = Boolean(touched);
  }

  function viewInputs(node) {
    if (Array.isArray(node.inputs)) return node.inputs;
    const found = roleRecord(node.role);
    return found && found.inputs ? found.inputs.slice() : [];
  }

  function viewOutputs(node) {
    if (Array.isArray(node.outputs)) return node.outputs;
    const found = roleRecord(node.role);
    return ((found && found.outputs) || []).map((name) => ({ name, source: "file", template: "", plain: true }));
  }

  // 取自角色契约、只写名称的产物与服务端规则一致：不要求模板，保存时仍写成名称。
  function roleDefaultOutput(node, item) {
    const found = roleRecord(node.role);
    return Boolean(item.plain && !item.template && found && (found.outputs || []).includes(item.name));
  }

  function wireNodes(nodes) {
    return (nodes || []).map((node) => {
      const copy = { ...node };
      if (Array.isArray(node.outputs)) {
        copy.outputs = node.outputs.map((item) => (item.plain && !item.template
          ? item.name
          : { name: item.name, source: item.source, template: item.template }));
      }
      if (Array.isArray(node.branches)) {
        copy.branches = node.branches.map((branch) => ({ ...branch, nodes: wireNodes(branch.nodes) }));
      }
      return copy;
    });
  }

  function wire(source) {
    return { ...source, nodes: wireNodes(source.nodes) };
  }

  function earlierOutputs(node) {
    const index = graph.nodes.findIndex((item) => item.id === node.id);
    const names = [];
    graph.nodes.slice(0, index).forEach((item) => {
      viewOutputs(item).forEach((output) => {
        if (output.name && !names.includes(output.name)) names.push(output.name);
      });
    });
    return names;
  }

  function materializeContract(node) {
    if (!Array.isArray(node.inputs)) node.inputs = viewInputs(node).slice();
    if (!Array.isArray(node.outputs)) node.outputs = viewOutputs(node).map((item) => ({ ...item }));
    node.contractTouched = true;
  }

  let templatePickIndex = -1;

  function renderContract(node) {
    const inputs = viewInputs(node);
    const outputs = viewOutputs(node);
    $("flowInputEmpty").hidden = inputs.length > 0;
    $("flowOutputEmpty").hidden = outputs.length > 0;
    $("flowInputList").replaceChildren();
    $("flowOutputList").replaceChildren();
    inputs.forEach((name, index) => $("flowInputList").appendChild(inputRow(node, name, index)));
    outputs.forEach((item, index) => $("flowOutputList").appendChild(outputRow(node, item, index)));
    refreshContractCounts(node);
  }

  function refreshContractCounts(node) {
    const inputs = viewInputs(node);
    const outputs = viewOutputs(node);
    $("flowInputCount").textContent = inputs.length ? inputs.length + " 项" : "无";
    const problems = outputs.filter((item, index) => outputProblem(node, index)).length;
    const count = $("flowOutputCount");
    count.textContent = (outputs.length ? outputs.length + " 项" : "无") + (problems ? " · " + problems + " 项待补" : "");
    count.classList.toggle("is-warn", problems > 0 || !outputs.length);
  }

  function inputChoices(node, current) {
    const names = ["human_request", ...earlierOutputs(node)];
    if (current && !names.includes(current)) names.push(current);
    return names;
  }

  function inputRow(node, name, index) {
    const row = document.createElement("div");
    row.className = "io-row";
    const line = document.createElement("div");
    line.className = "io-line";
    const field = document.createElement("input");
    field.value = name === "human_request" ? "人类需求" : name;
    field.spellcheck = false;
    field.setAttribute("aria-label", "输入产物名");
    const pick = document.createElement("select");
    pick.setAttribute("aria-label", "从已有产物选择");
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "手写";
    pick.appendChild(blank);
    inputChoices(node, name).forEach((choice) => {
      const option = document.createElement("option");
      option.value = choice;
      option.textContent = choice === "human_request" ? "人类需求" : choice;
      pick.appendChild(option);
    });
    if (inputChoices(node, name).includes(name)) pick.value = name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "移除";
    field.addEventListener("input", () => {
      materializeContract(node);
      node.inputs[index] = field.value.trim() === "人类需求" ? "human_request" : field.value.trim();
      refreshContractErrors(node);
    });
    pick.addEventListener("change", () => {
      if (!pick.value) return;
      materializeContract(node);
      node.inputs[index] = pick.value;
      renderContract(node);
    });
    remove.addEventListener("click", () => {
      materializeContract(node);
      node.inputs.splice(index, 1);
      renderContract(node);
    });
    line.append(field, pick, remove);
    row.append(line, contractError(node, "input", index));
    return row;
  }

  function outputRow(node, item, index) {
    const row = document.createElement("div");
    row.className = "io-row";
    const nameLine = document.createElement("div");
    nameLine.className = "io-line";
    const field = document.createElement("input");
    field.value = item.name || "";
    field.spellcheck = false;
    field.setAttribute("aria-label", "输出产物名");
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "移除";
    const caption = document.createElement("p");
    caption.className = "io-caption";
    caption.textContent = "模板";
    const sourceLine = document.createElement("div");
    sourceLine.className = "io-line";
    const source = document.createElement("select");
    source.setAttribute("aria-label", "模板来源");
    [["file", "本地文件"], ["link", "链接"]].forEach(([value, text]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      source.appendChild(option);
    });
    source.value = item.source === "link" ? "link" : "file";
    const template = document.createElement("input");
    template.value = item.template || "";
    template.spellcheck = false;
    template.placeholder = source.value === "link" ? "https://example.com/template.md" : "/path/to/template.md";
    template.setAttribute("aria-label", "模板地址");
    const browse = document.createElement("button");
    browse.type = "button";
    browse.textContent = "选择文件";
    browse.hidden = source.value === "link";
    field.addEventListener("input", () => {
      materializeContract(node);
      node.outputs[index].name = field.value.trim();
      refreshContractErrors(node);
    });
    remove.addEventListener("click", () => {
      materializeContract(node);
      node.outputs.splice(index, 1);
      renderContract(node);
    });
    source.addEventListener("change", () => {
      materializeContract(node);
      node.outputs[index].source = source.value;
      node.outputs[index].template = "";
      renderContract(node);
    });
    template.addEventListener("input", () => {
      materializeContract(node);
      node.outputs[index].template = template.value.trim();
      refreshContractErrors(node);
    });
    template.addEventListener("change", () => checkTemplate(node, index));
    browse.addEventListener("click", () => openFilePicker(index));
    nameLine.append(field, remove);
    sourceLine.append(source, template, browse);
    row.append(nameLine, caption, sourceLine, contractError(node, "output", index));
    return row;
  }

  function contractError(node, kind, index) {
    const note = document.createElement("p");
    note.className = "hint-block";
    note.dataset.ioError = kind + ":" + index;
    note.hidden = true;
    note.textContent = kind === "input" ? inputProblem(node, index) : outputProblem(node, index);
    note.hidden = !note.textContent;
    return note;
  }

  function inputProblem(node, index) {
    const inputs = viewInputs(node);
    const name = inputs[index] || "";
    if (!name) return "先写产物名。";
    if (inputs.indexOf(name) !== index) return "这个产物名重复了。";
    return "";
  }

  function outputProblem(node, index) {
    const item = viewOutputs(node)[index];
    if (!item || !item.name) return "先写产物名。";
    const inputs = viewInputs(node);
    const outputs = viewOutputs(node).map((output) => output.name);
    if (outputs.indexOf(item.name) !== index || inputs.includes(item.name)) return "这个产物名重复了。";
    if (!item.template && roleDefaultOutput(node, item)) return "";
    if (!item.template) return item.source === "link" ? "先填写链接。" : "先选择本地文件。";
    if (item.source === "link" && !/^https?:\/\//.test(item.template)) return "链接必须是 http 或 https。";
    return item.fileError || "";
  }

  function refreshContractErrors(node) {
    document.querySelectorAll("[data-io-error]").forEach((note) => {
      const [kind, index] = note.dataset.ioError.split(":");
      note.textContent = kind === "input" ? inputProblem(node, Number(index)) : outputProblem(node, Number(index));
      note.hidden = !note.textContent;
    });
    refreshContractCounts(node);
  }

  async function checkTemplate(node, index) {
    const item = (node.outputs || [])[index];
    if (!item || item.source !== "file" || !item.template) {
      refreshContractErrors(node);
      return;
    }
    const response = await fetch("/api/config/files/check?path=" + encodeURIComponent(item.template));
    const data = await response.json();
    item.fileError = response.ok ? "" : (data.detail || "读不到这个文件。");
    refreshContractErrors(node);
  }

  function openFilePicker(index) {
    templatePickIndex = index;
    $("filePicker").hidden = false;
    loadFilePicker("");
  }

  async function loadFilePicker(path) {
    const note = $("filePickerNote");
    const err = $("filePickerError");
    err.hidden = true;
    const response = await fetch("/api/config/files?path=" + encodeURIComponent(path || ""));
    const data = await response.json();
    if (!response.ok) {
      err.hidden = false;
      err.textContent = data.detail || "读不到这个目录。";
      return;
    }
    $("filePickerPath").textContent = data.path || "";
    $("filePicker").dataset.path = data.path || "";
    $("filePicker").dataset.parent = data.parent || "";
    $("btnFileUp").hidden = !data.parent;
    note.hidden = !data.truncated;
    note.textContent = data.truncated ? "只列出前 500 项。" : "";
    const list = $("filePickerList");
    list.replaceChildren();
    (data.dirs || []).forEach((item) => list.appendChild(filePickerButton(item.name + "/", () => loadFilePicker(item.path))));
    (data.files || []).forEach((item) => list.appendChild(filePickerButton(item.name, () => chooseTemplateFile(item.path))));
  }

  function filePickerButton(text, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "dir-picker-item";
    button.textContent = text;
    button.addEventListener("click", onClick);
    return button;
  }

  function chooseTemplateFile(path) {
    const node = selectedNode();
    if (node && node.outputs && templatePickIndex >= 0) {
      materializeContract(node);
      node.outputs[templatePickIndex].source = "file";
      node.outputs[templatePickIndex].template = path;
      node.outputs[templatePickIndex].fileError = "";
      renderContract(node);
    }
    $("filePicker").hidden = true;
  }

  function snapshotNow() {
    return JSON.stringify({
      title: graph.title,
      description: graph.description,
      nodes: graph.nodes,
    });
  }

  function markClean() {
    snapshot = snapshotNow();
    refreshDirty();
  }

  function isDirty() {
    if (mode === "new") {
      return graph.nodes.length > 2 || snapshotNow() !== snapshot;
    }
    if (!loadedId) return false;
    return snapshotNow() !== snapshot;
  }

  function confirmLeave() {
    if (!isDirty()) return true;
    return window.confirm("放弃未保存的修改？");
  }

  function writeUrl(nextMode, id, replace) {
    let url = "/workflow";
    if (nextMode === "open" && id) url += "?workflow=" + encodeURIComponent(id);
    if (nextMode === "open" && id && trail.length) url += "&trail=" + trail.map(encodeURIComponent).join(",");
    const hash = nextMode === "new" ? "#new" : "#edit";
    const next = url + hash;
    if (location.pathname + location.search + location.hash === next) return;
    history[replace ? "replaceState" : "pushState"]({ route: "workflow" }, "", next);
  }

  function highlight(nextMode) {
    document.querySelectorAll("[data-workflow-mode]").forEach((el) => {
      el.classList.toggle("is-active", el.dataset.workflowMode === nextMode);
    });
  }

  function nextNodeId() {
    let max = 0;
    const visit = (node) => {
      const match = /^n(\d+)$/.exec(node.id || "");
      if (match) max = Math.max(max, Number(match[1]));
      (node.branches || []).forEach((branch) => (branch.nodes || []).forEach(visit));
    };
    graph.nodes.forEach(visit);
    return "n" + (max + 1);
  }

  function sanitizeReturns() {
    const index = new Map(graph.nodes.map((node, pos) => [node.id, pos]));
    graph.nodes.forEach((node, pos) => {
      const target = index.get(node.returns_to);
      if (node.returns_to && (target === undefined || target >= pos)) {
        node.returns_to = "";
        delete node.max_loops;
      }
      if (node.reject_to && !index.has(node.reject_to)) delete node.reject_to;
    });
    if (selectedEdge && !edgeExists(selectedEdge)) selectedEdge = null;
  }

  function setGraph(data, yaml) {
    graph = {
      workflow_id: data.workflow_id || "",
      title: data.title || "",
      description: data.description || "",
      builtin: Boolean(data.builtin),
      subgraph: Boolean(data.subgraph),
      workspace: data.workspace || "",
      profile: data.profile || null,
      rail: data.rail || "",
      nodes: (data.nodes || []).map((node) => normalizeNode(node)),
    };
    yamlText = yaml || "";
    savedGraph = JSON.parse(JSON.stringify(graph));
    undoStack = [snapshotNow()];
    undoAt = 0;
    undoStamp = 0;
    selectedEdge = null;
    $("flowTitle").value = graph.title;
    $("flowDescription").value = graph.description;
  }

  function locked() {
    return Boolean(graph.builtin);
  }

  function showPieces() {
    const editing = mode === "new" || Boolean(loadedId);
    $("flowOpen").hidden = mode !== "open";
    if ($("flowPick")) $("flowPick").disabled = false;
    $("flowEditor").hidden = !editing;
    const created = mode === "open" && Boolean(loadedId);
    const builtin = locked();
    $("flowCreateRow").hidden = mode !== "new";
    $("flowWork").hidden = !created;
    $("btnCreateFlow").hidden = mode !== "new";
    $("flowSubgraphForm").hidden = true;
    $("flowDeleteConfirm").hidden = true;
    closeNameEdit();
    $("flowTitle").disabled = builtin;
    $("flowDescription").hidden = !editing;
    $("flowDescription").disabled = builtin;
    $("flowMetaHint").hidden = mode === "new";
    $("flowMetaHint").textContent = builtin
      ? "这是内置流程，只能查看。要修改，从“更多”复制为新流程。点节点或虚线可以查看设置。"
      : "点空白处回到这里。点一个节点或一条虚线，在右侧修改它。";
    if ($("flowIdHint")) $("flowIdHint").hidden = mode !== "new";
    $("flowIdLine").hidden = mode !== "open" || !loadedId;
    if (!loadedId) {
      usage = null;
      stats = null;
      $("flowUsage").hidden = true;
      $("flowStatsNote").hidden = true;
    }
    if (!loadedId || builtin) {
      versions = null;
      $("flowVersions").hidden = true;
    }
    if (!loadedId || mode !== "open") {
      problems = null;
      checkedSnap = "";
      renderProblems();
    }
    if (loadedId) $("flowIdLine").textContent = "流程标识：" + loadedId;
    highlight(mode);
    renderTrail();
    renderInspect();
    renderBoard();
  }

  function refreshDirty() {
    const editable = mode === "open" && Boolean(loadedId) && !locked();
    const show = editable && !nameEdit && isDirty();
    $("flowDirty").hidden = !show;
    if (editable) recordHistory();
    if (mode === "open" && loadedId && snapshotNow() !== checkedSnap) scheduleCheck();
    $("btnFlowUndo").disabled = !editable || undoAt <= 0;
    $("btnFlowRedo").disabled = !editable || undoAt >= undoStack.length - 1;
  }

  function scheduleCheck() {
    clearTimeout(checkTimer);
    checkTimer = setTimeout(runCheck, 600);
  }

  async function runCheck() {
    if (mode !== "open" || !loadedId) return;
    const id = loadedId;
    const snap = snapshotNow();
    const seq = ++checkSeq;
    try {
      const response = await fetch("/api/workflows/" + encodeURIComponent(id) + "/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(wire(graph)),
      });
      const data = await response.json();
      if (seq !== checkSeq || id !== loadedId || !response.ok) return;
      checkedSnap = snap;
      problems = data.problems || [];
    } catch (_) {
      return;
    }
    renderProblems();
    markProblemNodes();
  }

  function problemNames() {
    const names = new Set();
    (problems || []).forEach((text) => {
      for (const match of text.matchAll(/“([^”]+)”/g)) names.add(match[1]);
    });
    return names;
  }

  function markProblemNodes() {
    const names = problemNames();
    graph.nodes.forEach((node) => {
      const hit = names.has(node.name);
      $("flowBoard").querySelectorAll('.flow-node[data-node-id="' + CSS.escape(node.id) + '"]').forEach((el) => {
        el.classList.toggle("has-problem", hit);
        if (hit) el.title = (problems || []).filter((text) => text.includes("“" + node.name + "”")).join("\n");
        else el.removeAttribute("title");
      });
    });
  }

  function renderProblems() {
    const chip = $("btnFlowCheck");
    const list = problems || [];
    chip.hidden = problems === null || Boolean(nameEdit);
    chip.classList.toggle("is-ok", !list.length);
    chip.textContent = list.length ? list.length + " 处待补" : "可以运行";
    chip.title = list.length ? "启动运行前要先补齐，点开查看" : "按启动时的规则检查过，可以运行";
    $("flowProblemList").replaceChildren(...list.map((text) => {
      const item = document.createElement("li");
      item.textContent = text;
      return item;
    }));
    $("flowProblems").hidden = !list.length;
  }

  // 连续输入在短时间内合并为一步，撤销时不必逐字回退。
  function recordHistory() {
    const now = snapshotNow();
    if (now === undoStack[undoAt]) return;
    undoStack = undoStack.slice(0, undoAt + 1);
    const stamp = Date.now();
    if (undoAt > 0 && stamp - undoStamp < 700) undoStack[undoAt] = now;
    else undoStack.push(now);
    if (undoStack.length > 100) undoStack.shift();
    undoAt = undoStack.length - 1;
    undoStamp = stamp;
  }

  function stepHistory(delta) {
    if (mode !== "open" || !loadedId || locked()) return;
    const target = undoAt + delta;
    if (target < 0 || target >= undoStack.length) return;
    undoAt = target;
    undoStamp = 0;
    const state = JSON.parse(undoStack[target]);
    graph.title = state.title;
    graph.description = state.description;
    graph.nodes = state.nodes;
    $("flowTitle").value = graph.title;
    $("flowDescription").value = graph.description;
    selectedEdge = null;
    if (selectedId && !graph.nodes.some((node) => node.id === selectedId)) selectedId = "";
    renderInspect();
    renderBoard();
    showSaved(delta < 0 ? "已撤销。" : "已重做。");
  }

  function laneKey(node) {
    if (node.kind === "subgraph") return "subgraph";
    if (node.kind === "parallel") return "parallel";
    return node.role;
  }

  function lanesOf() {
    const used = new Set(graph.nodes.map((node) => laneKey(node)));
    const lanes = [];
    if (used.has("human")) lanes.push({ id: "human", label: "人类" });
    if (used.has("subgraph")) lanes.push({ id: "subgraph", label: "子流程" });
    if (used.has("parallel")) lanes.push({ id: "parallel", label: "并行" });
    roles.forEach((role) => {
      if (role.id !== "human" && used.has(role.id)) lanes.push(role);
    });
    return lanes;
  }

  function nodeWidth(node) {
    if (node.kind !== "parallel") return NODE_W;
    const count = Math.max((node.branches || []).length, 2);
    return Math.max(NODE_W, count * 84);
  }

  function layoutBoxes() {
    const lanes = lanesOf();
    const laneIndex = new Map(lanes.map((lane, index) => [lane.id, index]));
    let left = ORIGIN_X;
    return graph.nodes.map((node) => {
      const lane = laneIndex.get(laneKey(node)) || 0;
      const height = node.kind === "parallel" ? 58 : 36;
      const width = nodeWidth(node);
      const box = {
        node,
        left,
        top: lane * LANE_H + (LANE_H - height) / 2,
        width,
        height,
      };
      left += width + boardGap;
      return box;
    });
  }

  /** 顺序连线在两节点间的拐点：左侧留给流出的虚线，右侧留给流入的虚线。 */
  function seqElbow(x1, x2) {
    return x2 - x1 >= LOOP_OUT + LOOP_IN + 16 ? (x1 + LOOP_OUT + x2 - LOOP_IN) / 2 : (x1 + x2) / 2;
  }

  /** 按中栏可用宽度排布：有富余时拉开节点间距；放不下时保持原尺寸，横向滚动查看。 */
  function fitBoard() {
    const scroll = $("flowScroll");
    const avail = scroll ? scroll.clientWidth : 0;
    fittedWidth = avail;
    boardGap = NODE_GAP;
    const count = graph.nodes.length;
    if (!avail || count < 2) return;
    const fixed = ORIGIN_X + graph.nodes.reduce((sum, node) => sum + nodeWidth(node), 0) + BOARD_END;
    const spare = Math.floor((avail - fixed) / (count - 1));
    boardGap = Math.min(MAX_GAP, Math.max(NODE_GAP, spare));
  }

  function roundedLink(a, b) {
    const y1 = a.top + a.height / 2;
    const y2 = b.top + b.height / 2;
    const x1 = a.left + a.width;
    const x2 = b.left;
    if (x2 >= x1 + 8 && Math.abs(y2 - y1) < 3) return `M ${x1} ${y1} H ${x2}`;
    const forward = x2 > x1 + 20;
    const elbow = forward ? seqElbow(x1, x2) : x1 + 18;
    const dir = y2 >= y1 ? 1 : -1;
    const gap = Math.abs(y2 - y1);
    const radius = Math.min(8, gap / 2, Math.abs(elbow - x1), Math.abs(x2 - elbow));
    if (radius < 3) return `M ${x1} ${y1} H ${elbow} V ${y2} H ${x2}`;
    const into = forward ? elbow + radius : elbow - radius;
    return [
      `M ${x1} ${y1}`,
      `H ${elbow - (forward ? radius : -radius)}`,
      `Q ${elbow} ${y1} ${elbow} ${y1 + dir * radius}`,
      `V ${y2 - dir * radius}`,
      `Q ${elbow} ${y2} ${into} ${y2}`,
      `H ${x2}`,
    ].join(" ");
  }

  /** 回退与不通过的连线；每条占画布下方的一条横向通道，跨度短的靠近泳道。 */
  function loopEdges(boxes) {
    const at = new Map(boxes.map((box) => [box.node.id, box]));
    const edges = [];
    graph.nodes.forEach((node) => {
      if (node.returns_to && at.has(node.returns_to)) edges.push({ from: node.id, to: node.returns_to, kind: "return" });
      if (node.kind === "gate" && node.reject_to && at.has(node.reject_to)) edges.push({ from: node.id, to: node.reject_to, kind: "reject" });
    });
    edges.forEach((edge) => {
      edge.a = at.get(edge.from);
      edge.b = at.get(edge.to);
      edge.span = Math.abs(edge.a.left - edge.b.left);
    });
    edges.sort((x, y) => x.span - y.span);
    return edges;
  }

  function edgeExists(edge) {
    const node = graph.nodes.find((item) => item.id === edge.from);
    if (!node) return false;
    return edge.kind === "return" ? Boolean(node.returns_to) : node.kind === "gate" && Boolean(node.reject_to);
  }

  function sameEdge(a, b) {
    return Boolean(a && b) && a.from === b.from && a.kind === b.kind;
  }

  /** 虚线的起止点：比顺序连线低一点，避免与顺序连线的箭头重合；接入前留出一段直线放箭头。 */
  function loopEnds(a, b) {
    const r = 6;
    const x1 = a.left + a.width;
    const x2 = b.left;
    const xo = x1 + LOOP_OUT;
    let xi = x2 - LOOP_IN;
    if (xi >= xo && xi - xo < 2 * r) xi = xo + 2 * r;
    return {
      x1,
      y1: a.top + a.height / 2 + Math.min(LOOP_DY, a.height / 2 - 6),
      x2,
      y2: b.top + b.height / 2 + Math.min(LOOP_DY, b.height / 2 - 6),
      xo,
      xi,
    };
  }

  /** 从较晚节点右侧流出，沿下方通道绕回，从目标节点左侧流入；不从节点上下边接入。 */
  function loopLink(a, b, y) {
    const r = 6;
    const { x1, y1, x2, y2, xo, xi } = loopEnds(a, b);
    const dir = xi >= xo ? 1 : -1;
    return [
      `M ${x1} ${y1}`,
      `H ${xo - r}`,
      `Q ${xo} ${y1} ${xo} ${y1 + r}`,
      `V ${y - r}`,
      `Q ${xo} ${y} ${xo + dir * r} ${y}`,
      `H ${xi - dir * r}`,
      `Q ${xi} ${y} ${xi} ${y - r}`,
      `V ${y2 + r}`,
      `Q ${xi} ${y2} ${xi + r} ${y2}`,
      `H ${x2}`,
    ].join(" ");
  }

  function edgeLabelText(edge) {
    if (edge.kind === "reject") return "不通过";
    const node = graph.nodes.find((item) => item.id === edge.from);
    return node && node.max_loops ? "回退 · 最多 " + node.max_loops + " 轮" : "回退 · 未设轮数";
  }

  function renderBoard() {
    closeMenu();
    const board = $("flowBoard");
    const column = $("flowColumn");
    board.replaceChildren();
    column.replaceChildren();
    fitBoard();
    const lanes = lanesOf();
    const boxes = layoutBoxes();
    const edges = loopEdges(boxes);
    const last = boxes[boxes.length - 1];
    const width = Math.max((last ? last.left + last.width : ORIGIN_X) + BOARD_END, 280);
    const lanesHeight = Math.max(lanes.length, 1) * LANE_H;
    const height = lanesHeight + (edges.length ? TRACK_TOP + (edges.length - 1) * TRACK_GAP + 18 : 0);
    board.style.width = width + "px";
    board.style.height = height + "px";
    lanes.forEach((lane, index) => {
      const row = document.createElement("div");
      row.className = "flow-lane";
      row.style.top = index * LANE_H + "px";
      row.style.height = LANE_H + "px";
      const label = document.createElement("span");
      label.className = "flow-lane-label";
      label.textContent = lane.label;
      row.appendChild(label);
      board.appendChild(row);
    });
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "flow-edges");
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    ["seq", "return", "reject"].forEach((kind) => {
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
      marker.setAttribute("id", "flowHead-" + kind);
      marker.setAttribute("class", "flow-head is-" + kind);
      marker.setAttribute("viewBox", "0 0 8 8");
      marker.setAttribute("markerUnits", "userSpaceOnUse");
      marker.setAttribute("markerWidth", "9");
      marker.setAttribute("markerHeight", "9");
      marker.setAttribute("refX", "8");
      marker.setAttribute("refY", "4");
      marker.setAttribute("orient", "auto");
      const head = document.createElementNS("http://www.w3.org/2000/svg", "path");
      head.setAttribute("d", "M0,0 L8,4 L0,8 Z");
      marker.appendChild(head);
      defs.appendChild(marker);
    });
    svg.appendChild(defs);
    boxes.forEach((box, index) => {
      if (index < boxes.length - 1) svg.appendChild(pathEl(roundedLink(box, boxes[index + 1]), "is-seq"));
    });
    const editable = !locked();
    const labels = [];
    edges.forEach((edge, index) => {
      const y = lanesHeight + TRACK_TOP + index * TRACK_GAP;
      const d = loopLink(edge.a, edge.b, y);
      const related = selectedId && (edge.from === selectedId || edge.to === selectedId);
      const picked = sameEdge(edge, selectedEdge);
      const cls = "is-" + edge.kind + (picked ? " is-selected" : related ? " is-related" : "");
      svg.appendChild(pathEl(d, cls));
      const hit = pathEl(d, "flow-edge-hit");
      hit.removeAttribute("marker-end");
      hit.addEventListener("click", (event) => {
        event.stopPropagation();
        selectEdge(edge);
      });
      svg.appendChild(hit);
      const label = document.createElement("button");
      label.type = "button";
      label.className = "flow-edge-label is-" + edge.kind + (picked ? " is-selected" : "");
      label.textContent = edgeLabelText(edge);
      const fromName = edge.a.node.name;
      const toName = edge.b.node.name;
      label.setAttribute("aria-label", label.textContent + "：从“" + fromName + "”到“" + toName + "”");
      const ends = loopEnds(edge.a, edge.b);
      const left = Math.min(ends.xo, ends.xi);
      const right = Math.max(ends.xo, ends.xi);
      label.style.left = (left + right) / 2 + "px";
      label.style.top = y + "px";
      label.addEventListener("click", (event) => {
        event.stopPropagation();
        selectEdge(edge);
      });
      labels.push(label);
      if (picked && editable) labels.push(edgeHandle(edge));
    });
    board.appendChild(svg);
    boxes.forEach((box) => board.appendChild(nodeButton(box)));
    if (editable) {
      boxes.forEach((box, index) => {
        if (index < boxes.length - 1) board.appendChild(insertButton(box, boxes[index + 1], index + 1));
      });
    }
    labels.forEach((label) => board.appendChild(label));
    board.onclick = (event) => {
      const target = event.target;
      if (target === board || target.classList.contains("flow-lane") || target.classList.contains("flow-lane-label")) {
        selectNode("");
      }
    };
    graph.nodes.forEach((node, index) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "flow-column-item" + (node.id === selectedId ? " is-selected" : "");
      button.textContent = (index + 1) + ". " + node.name;
      button.addEventListener("click", () => selectNode(node.id));
      item.appendChild(button);
      column.appendChild(item);
    });
    refreshDirty();
    markProblemNodes();
    markStats();
    requestAnimationFrame(updateScrollHints);
  }

  function statLines(item, kind) {
    const lines = [];
    if (item.turns) lines.push("执行 " + item.turns + " 次");
    if (item.avg_seconds !== null && item.avg_seconds !== undefined) {
      lines.push("平均 " + (item.avg_seconds >= 60 ? (item.avg_seconds / 60).toFixed(1) + " 分钟" : Math.round(item.avg_seconds) + " 秒"));
    }
    if (item.returns) lines.push("回退 " + item.returns);
    if (item.escalations) lines.push("升级 " + item.escalations);
    if (item.rejections) lines.push("驳回 " + item.rejections);
    const tokens = item.input_tokens + item.output_tokens;
    if (tokens) lines.push((tokens >= 1000 ? (tokens / 1000).toFixed(1) + "k" : tokens) + " tokens");
    if (!lines.length) lines.push(kind === "gate" && item.runs ? "均已批准" : "没有记录");
    return lines;
  }

  function markStats() {
    $("flowBoard").querySelectorAll(".flow-node-stat").forEach((el) => el.remove());
    if (!showStats || !stats) return;
    graph.nodes.forEach((node) => {
      const item = stats.nodes[node.id];
      if (!item || node.kind === "start" || node.kind === "end") return;
      const lines = statLines(item, node.kind);
      $("flowBoard").querySelectorAll('.flow-node[data-node-id="' + CSS.escape(node.id) + '"]').forEach((el) => {
        const label = document.createElement("span");
        label.className = "flow-node-stat";
        label.textContent = lines.slice(0, 2).join(" · ");
        label.title = "经过它的运行 " + item.runs + " 次\n" + lines.join("\n");
        el.appendChild(label);
      });
    });
  }

  function renderStatsNote() {
    const note = $("flowStatsNote");
    note.hidden = !showStats || !stats;
    if (!stats) return;
    note.textContent = stats.runs
      ? "画布上的运行数据汇总了用这份流程的 " + stats.runs + " 次运行；悬停数字查看全部。"
      : "还没有用这份流程的运行，画布上没有运行数据。";
  }

  async function loadStats(id) {
    if (!showStats || !id) return;
    try {
      const response = await fetch("/api/workflows/" + encodeURIComponent(id) + "/stats");
      const data = await response.json();
      if (!response.ok || id !== loadedId || !showStats) return;
      stats = data;
    } catch (_) {
      return;
    }
    renderStatsNote();
    markStats();
  }

  function toggleStats() {
    showStats = !showStats;
    try {
      localStorage.setItem("geni.flowStats", showStats ? "1" : "");
    } catch (_) {
      // 本地存储不可用时只在本页生效。
    }
    stats = null;
    renderStatsNote();
    markStats();
    if (showStats) loadStats(loadedId);
  }

  function pathEl(d, cls) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    path.setAttribute("class", cls);
    const kind = /is-(seq|return|reject)/.exec(cls);
    if (kind) path.setAttribute("marker-end", "url(#flowHead-" + kind[1] + ")");
    return path;
  }

  /** 两个相邻节点之间连线中点的“+”：在这里插入新节点。 */
  function insertButton(a, b, index) {
    const x1 = a.left + a.width;
    const y1 = a.top + a.height / 2;
    const x2 = b.left;
    const y2 = b.top + b.height / 2;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "flow-insert";
    button.textContent = "+";
    button.setAttribute("aria-label", "在“" + a.node.name + "”和“" + b.node.name + "”之间添加节点");
    button.title = "在这里添加节点";
    button.setAttribute("aria-haspopup", "menu");
    button.setAttribute("aria-expanded", "false");
    button.style.left = seqElbow(x1, x2) + "px";
    button.style.top = (y1 + y2) / 2 + "px";
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleMenu(button, () => insertRows(index), event.detail === 0);
    });
    return button;
  }

  /** 选中连线时，箭头端的圆点可以拖到另一个节点上，改这条连线的去向。 */
  function edgeHandle(edge) {
    const handle = document.createElement("span");
    handle.className = "flow-edge-handle is-" + edge.kind;
    handle.title = "拖到另一个节点上，改去向";
    const ends = loopEnds(edge.a, edge.b);
    const x = ends.x2 - 14;
    const y = ends.y2;
    handle.style.left = x + "px";
    handle.style.top = y + "px";
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      handle.style.pointerEvents = "none";
      handle.classList.add("is-dragging");
      const board = $("flowBoard");
      board.classList.add("is-edge-dragging");
      const ns = "http://www.w3.org/2000/svg";
      const ghost = document.createElementNS(ns, "path");
      ghost.setAttribute("class", "flow-edge-ghost is-" + edge.kind);
      ghost.setAttribute("marker-end", "url(#flowHead-" + edge.kind + ")");
      board.querySelector(".flow-edges").appendChild(ghost);
      const sx = ends.xo;
      const sy = ends.y1;
      let hover = null;
      const point = (ev) => {
        const rect = board.getBoundingClientRect();
        return { x: ev.clientX - rect.left, y: ev.clientY - rect.top };
      };
      const nodeAt = (ev) => {
        const el = document.elementFromPoint(ev.clientX, ev.clientY);
        const btn = el && el.closest && el.closest(".flow-node");
        return btn && board.contains(btn) ? btn : null;
      };
      const onMove = (ev) => {
        const p = point(ev);
        handle.style.left = p.x + "px";
        handle.style.top = p.y + "px";
        const over = nodeAt(ev);
        if (hover && hover !== over) hover.classList.remove("is-drop", "is-drop-bad");
        hover = over;
        const bad = over && edgeTargetProblem(edge, over.dataset.nodeId);
        if (over) over.classList.add(bad ? "is-drop-bad" : "is-drop");
        if (over && !bad) {
          const rect = board.getBoundingClientRect();
          const box = over.getBoundingClientRect();
          const tx = box.left - rect.left;
          const half = box.height / 2;
          const ty = box.top - rect.top + half + Math.min(LOOP_DY, half - 6);
          ghost.setAttribute("d", `M ${ends.x1} ${sy} H ${sx} L ${tx - LOOP_IN} ${ty} H ${tx}`);
        } else {
          ghost.setAttribute("d", `M ${ends.x1} ${sy} H ${sx} L ${p.x} ${p.y}`);
        }
      };
      const onUp = (ev) => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        board.classList.remove("is-edge-dragging");
        const over = nodeAt(ev);
        if (!over) {
          renderBoard();
          return;
        }
        setEdgeTarget(edge, over.dataset.nodeId);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });
    return handle;
  }

  function nodeButton(box) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.nodeId = box.node.id;
    const kindClass = box.node.kind === "gate"
      ? "gate"
      : box.node.kind === "activity" || box.node.kind === "system"
        ? "activity"
        : box.node.kind === "parallel"
          ? "parallel"
          : box.node.kind === "subgraph"
            ? "subgraph"
            : "marker";
    button.className = "flow-node is-" + kindClass;
    if (box.node.id === selectedId) button.classList.add("is-selected");
    button.style.left = box.left + "px";
    button.style.top = box.top + "px";
    button.style.width = box.width + "px";
    button.style.height = box.height + "px";
    if (box.node.kind === "gate") {
      button.append(window.geniIcons.decisionIcon(), document.createTextNode(box.node.name));
      const count = (box.node.items || []).length;
      if (count) {
        const tag = document.createElement("span");
        tag.className = "flow-node-count";
        tag.textContent = count + " 项";
        button.setAttribute("aria-label", box.node.name + "，" + count + " 个决策项");
        button.appendChild(tag);
      }
    } else if (box.node.kind === "parallel") {
      const title = document.createElement("span");
      title.textContent = box.node.name;
      const branches = document.createElement("span");
      branches.className = "flow-branches";
      (box.node.branches || []).forEach((branch) => {
        const name = document.createElement("span");
        name.textContent = branch.name;
        branches.appendChild(name);
      });
      button.append(title, branches);
    } else {
      button.textContent = box.node.name;
    }
    bindDrag(button, box);
    return button;
  }

  function bindDrag(button, box) {
    if (box.node.kind === "start" || box.node.kind === "end") {
      button.addEventListener("click", () => selectNode(box.node.id));
      return;
    }
    button.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const origin = event.clientX;
      let moved = false;
      function onMove(ev) {
        const delta = ev.clientX - origin;
        if (Math.abs(delta) > 4) moved = true;
        button.style.transform = "translateX(" + delta + "px)";
      }
      function onUp(ev) {
        button.releasePointerCapture(event.pointerId);
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        button.style.transform = "";
        if (!moved) {
          selectNode(box.node.id);
          return;
        }
        reorderByX(box.node.id, ev.clientX);
      }
      button.setPointerCapture(event.pointerId);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });
  }

  function reorderByX(id, clientX) {
    const board = $("flowBoard");
    const x = clientX - board.getBoundingClientRect().left;
    const others = layoutBoxes().filter((box) => box.node.id !== id);
    let to = others.filter((box) => box.left + box.width / 2 < x).length;
    to = Math.max(1, Math.min(graph.nodes.length - 2, to));
    const from = graph.nodes.findIndex((node) => node.id === id);
    if (from < 0 || to === from) {
      renderBoard();
      return;
    }
    const [item] = graph.nodes.splice(from, 1);
    graph.nodes.splice(to, 0, item);
    sanitizeReturns();
    selectedId = id;
    selectedEdge = null;
    renderBoard();
    renderInspect();
  }

  function moveSelected(delta) {
    const index = graph.nodes.findIndex((node) => node.id === selectedId);
    const node = graph.nodes[index];
    if (!node || node.kind === "start" || node.kind === "end") return;
    const target = index + delta;
    if (target <= 0 || target >= graph.nodes.length - 1) return;
    graph.nodes.splice(index, 1);
    graph.nodes.splice(target, 0, node);
    sanitizeReturns();
    renderBoard();
    renderInspect();
  }

  function selectNode(id) {
    selectedId = id;
    selectedEdge = null;
    showError("");
    renderBoard();
    renderInspect();
    revealSelected();
  }

  function selectEdge(edge) {
    selectedId = "";
    showError("");
    selectedEdge = { from: edge.from, kind: edge.kind };
    renderBoard();
    renderInspect();
  }

  function revealSelected() {
    if (!selectedId) return;
    const button = $("flowBoard").querySelector('.flow-node[data-node-id="' + CSS.escape(selectedId) + '"]');
    if (button) button.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  function updateScrollHints() {
    const scroll = $("flowScroll");
    const view = $("flowViewport");
    if (!scroll || !view) return;
    view.classList.toggle("can-left", scroll.scrollLeft > 2);
    view.classList.toggle("can-right", scroll.scrollLeft + scroll.clientWidth < scroll.scrollWidth - 2);
  }

  function nodeById(id) {
    return graph.nodes.find((item) => item.id === id) || null;
  }

  function indexOf(id) {
    return graph.nodes.findIndex((item) => item.id === id);
  }

  /** 回退只能指向更早的、不是结束的节点；不通过可以去启动以外的任何其他节点。 */
  function edgeTargetProblem(edge, targetId) {
    const from = indexOf(edge.from);
    const to = indexOf(targetId);
    const target = nodeById(targetId);
    if (!target || targetId === edge.from) return "不能指向自己。";
    if (edge.kind === "return") {
      if (to >= from || target.kind === "end") return "回退只能指向更早的节点。";
      return "";
    }
    if (target.kind === "start") return "不通过不能回到启动。";
    return "";
  }

  function returnTargets(node) {
    return graph.nodes.slice(0, indexOf(node.id)).filter((item) => item.kind !== "end");
  }

  function rejectTargets(node) {
    return graph.nodes.filter((item) => item.id !== node.id && item.kind !== "start" && item.kind !== "end");
  }

  function setReturn(node, targetId) {
    node.returns_to = targetId || "";
    if (!node.returns_to) delete node.max_loops;
    else if (!node.max_loops) node.max_loops = DEFAULT_LOOPS;
  }

  function setReject(node, targetId) {
    if (targetId) node.reject_to = targetId;
    else delete node.reject_to;
  }

  function setEdgeTarget(edge, targetId) {
    const node = nodeById(edge.from);
    const problem = edgeTargetProblem(edge, targetId);
    if (!node || problem) {
      showError(problem);
      renderBoard();
      return;
    }
    showError("");
    if (edge.kind === "return") setReturn(node, targetId);
    else setReject(node, targetId);
    selectedEdge = { from: edge.from, kind: edge.kind };
    renderBoard();
    renderInspect();
  }

  function deleteEdge(edge) {
    const node = nodeById(edge.from);
    if (!node) return;
    if (edge.kind === "return") setReturn(node, "");
    else setReject(node, "");
    selectedEdge = null;
    selectedId = node.id;
    renderBoard();
    renderInspect();
  }

  function deleteNode(node) {
    if (!node || node.kind === "start" || node.kind === "end" || locked()) return;
    if (!window.confirm("删除“" + node.name + "”？删除后前后节点会重新连上。")) return;
    graph.nodes = graph.nodes.filter((item) => item.id !== node.id);
    graph.nodes.forEach((item) => {
      if (item.returns_to === node.id) setReturn(item, "");
      if (item.reject_to === node.id) setReject(item, "");
    });
    selectedId = "";
    selectedEdge = null;
    renderBoard();
    renderInspect();
  }

  function defaultName(kind) {
    return kind === "gate" ? "新决策点" : kind === "parallel" ? "新并行" : "新活动";
  }

  function insertNode(index, kind, extra) {
    const at = Math.max(1, Math.min(graph.nodes.length - 1, index));
    let created;
    if (kind === "activity") {
      created = { id: nextNodeId(), kind, name: defaultName(kind), role: extra.role, returns_to: "", decision: "" };
      applyRoleContract(created, extra.role, false);
    } else if (kind === "gate") {
      created = { id: nextNodeId(), kind, name: defaultName(kind), role: "human", returns_to: "", decision: "approve" };
    } else if (kind === "parallel") {
      created = {
        id: nextNodeId(), kind, name: defaultName(kind), role: "", returns_to: "",
        branches: [
          { id: "b1", name: "支路1", nodes: [] },
          { id: "b2", name: "支路2", nodes: [] },
        ],
      };
    } else {
      const found = workflows.find((item) => item.workflow_id === extra.subgraph_id);
      created = { id: nextNodeId(), kind: "subgraph", name: found ? found.title : extra.subgraph_id, role: "", returns_to: "", subgraph_id: extra.subgraph_id };
    }
    graph.nodes.splice(at, 0, created);
    showError("");
    selectNode(created.id);
    if (kind !== "subgraph") {
      const field = $("flowNodeName");
      requestAnimationFrame(() => {
        field.focus();
        if (typeof field.select === "function") field.select();
      });
    }
  }

  /** “添加节点”插在选中节点之后；没有选中、或选中的是结束时，插在结束之前。 */
  function toolbarInsertIndex() {
    const at = selectedId ? indexOf(selectedId) : -1;
    if (at < 0 || at >= graph.nodes.length - 1) return graph.nodes.length - 1;
    return at + 1;
  }

  function insertRows(index) {
    const before = graph.nodes[index - 1];
    const after = graph.nodes[index];
    const rows = [];
    if (before && after) rows.push({ caption: "插在“" + before.name + "”与“" + after.name + "”之间" });
    const activityRoles = roles.filter((item) => item.id !== "human");
    rows.push({
      title: "活动",
      value: "选择角色",
      items: activityRoles.map((role) => ({ text: role.label, onPick: () => insertNode(index, "activity", { role: role.id }) })),
      empty: "还没有可用的角色。",
    });
    rows.push({ title: "决策点", value: "人类批复", onPick: () => insertNode(index, "gate") });
    rows.push({ title: "并行", value: "两条支路", onPick: () => insertNode(index, "parallel") });
    if (!graph.subgraph) {
      const subgraphs = workflows.filter((item) => item.subgraph && item.workflow_id !== loadedId);
      rows.push({
        title: "子图",
        value: subgraphs.length ? subgraphs.length + " 份" : "还没有",
        items: subgraphs.map((item) => ({
          text: (item.builtin ? "内置 · " : "") + item.title,
          onPick: () => insertNode(index, "subgraph", { subgraph_id: item.workflow_id }),
        })),
        empty: "还没有子图。可以从“更多”把一份流程存为子图。",
      });
    }
    return rows;
  }

  function moreRows() {
    const rows = [];
    const builtin = locked();
    if (!builtin) rows.push({ title: "重命名……", onPick: () => openNameEdit("rename") });
    rows.push({ title: "复制为新流程", onPick: () => openNameEdit("copy") });
    if (!builtin && !graph.subgraph) {
      rows.push({ title: "存为子图……", onPick: openSubgraphForm });
    }
    rows.push({ title: showStats ? "隐藏运行数据" : "显示运行数据", onPick: toggleStats });
    rows.push({
      title: "导出 YAML",
      value: isDirty() ? "已保存的版本" : "",
      onPick: exportYaml,
      disabled: !yamlText,
    });
    if (!builtin) {
      const inUse = usageCount() > 0;
      rows.push("divider");
      rows.push({ title: "删除流程……", danger: true, onPick: openDeleteConfirm, disabled: inUse, value: inUse ? "使用中" : "" });
    }
    return rows;
  }

  function exportYaml() {
    if (!yamlText || !loadedId) return;
    const blob = new Blob([yamlText], { type: "text/yaml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = loadedId + ".yaml";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showSaved(isDirty() ? "已导出上次保存的版本，未保存的修改不在其中。" : "已导出 " + loadedId + ".yaml。");
  }

  // 改名与复制都在选择框原位输入标题，保存或取消后换回选择框。
  function showNameEdit(on) {
    const created = mode === "open" && Boolean(loadedId);
    const builtin = locked();
    $("flowPick").hidden = on || !workflows.length;
    $("btnFlowAdd").hidden = on || !created || builtin;
    $("btnFlowUndo").hidden = on || !created || builtin;
    $("btnFlowRedo").hidden = on || !created || builtin;
    $("btnFlowCheck").hidden = on || !created || problems === null;
    $("btnSaveFlow").hidden = on || !created || builtin;
    $("btnFlowMore").hidden = on || !created;
    ["flowNameEdit", "btnNameSave", "btnNameCancel"].forEach((id) => {
      $(id).hidden = !on;
    });
    refreshDirty();
  }

  function openNameEdit(kind) {
    nameEdit = kind;
    $("flowSubgraphForm").hidden = true;
    $("flowDeleteConfirm").hidden = true;
    showError("");
    const input = $("flowNameEdit");
    const title = (savedGraph && savedGraph.title) || graph.title || loadedId;
    input.label = kind === "copy" ? "新流程标题" : "流程标题";
    input.value = kind === "copy" ? "副本 · " + title : title;
    showNameEdit(true);
    requestAnimationFrame(() => {
      input.focus();
      if (typeof input.select === "function") input.select();
    });
  }

  function closeNameEdit() {
    nameEdit = "";
    showNameEdit(false);
  }

  async function saveNameEdit() {
    const title = ($("flowNameEdit").value || "").trim();
    if (!title) {
      showError("先写标题。");
      $("flowNameEdit").focus();
      return;
    }
    const button = $("btnNameSave");
    if (button.loading) return;
    showError("");
    showSaved("");
    button.loading = true;
    button.disabled = true;
    try {
      if (nameEdit === "copy") {
        if (confirmLeave()) await copySelected(loadedId, title);
      }
      else if (nameEdit === "rename") await renameLoaded(title);
    } finally {
      button.loading = false;
      button.disabled = false;
    }
  }

  async function renameLoaded(title) {
    if (!loadedId || !savedGraph || graph.builtin) return;
    if (title === savedGraph.title) {
      closeNameEdit();
      return;
    }
    try {
      const response = await fetch("/api/workflows/" + encodeURIComponent(loadedId), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(wire({ ...savedGraph, title })),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        showError(data.detail || "没能重命名流程。");
        return;
      }
      const saved = data.workflow.title;
      const clean = JSON.parse(snapshot || "{}");
      clean.title = saved;
      snapshot = JSON.stringify(clean);
      savedGraph.title = saved;
      undoStack = undoStack.map((entry) => JSON.stringify({ ...JSON.parse(entry), title: saved }));
      yamlText = data.yaml || yamlText;
      graph.title = saved;
      $("flowTitle").value = saved;
      refreshDirty();
      await loadLists();
      closeNameEdit();
      showSaved("已重命名为“" + saved + "”。");
      loadVersions(loadedId);
    } catch (err) {
      showError(err.message || "没能重命名流程。");
    }
  }

  function usageCount() {
    return usage ? usage.projects.length + usage.workflows.length : 0;
  }

  function usageLine(label, items, href) {
    const line = document.createElement("p");
    line.append(label);
    items.forEach((item, index) => {
      if (index) line.append("、");
      const link = document.createElement("a");
      link.href = href(item);
      link.textContent = item.title;
      line.append(link);
    });
    line.append("。");
    return line;
  }

  async function loadUsage(id) {
    const box = $("flowUsage");
    try {
      const response = await fetch("/api/workflows/" + encodeURIComponent(id) + "/usage");
      const data = await response.json();
      if (!response.ok || id !== loadedId) return;
      usage = { projects: data.projects || [], workflows: data.workflows || [] };
    } catch (_) {
      return;
    }
    const lines = [];
    if (usage.projects.length) {
      lines.push(usageLine("选用它的项目：", usage.projects, (item) => "/project?project=" + encodeURIComponent(item.project_id)));
    }
    if (usage.workflows.length) {
      lines.push(usageLine("作为子图出现在：", usage.workflows, (item) => "/workflow?workflow=" + encodeURIComponent(item.workflow_id) + "#edit"));
    }
    if (!lines.length) {
      const none = document.createElement("p");
      none.textContent = "还没有项目选用它，也没有流程把它当作子图。";
      lines.push(none);
    } else if (!graph.builtin) {
      const note = document.createElement("p");
      note.textContent = "仍在使用时不能删除。";
      lines.push(note);
    }
    box.replaceChildren(...lines);
    box.hidden = false;
  }

  function versionTime(text) {
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return text || "时间不详";
    const pad = (value) => String(value).padStart(2, "0");
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate())
      + " " + pad(date.getHours()) + ":" + pad(date.getMinutes());
  }

  function versionChanges(changes) {
    if (!changes) return "最早的记录。";
    const quote = (names) => names.map((name) => "“" + name + "”").join("");
    const parts = [];
    if (changes.title) parts.push("改了标题");
    if (changes.description) parts.push("改了说明");
    if (changes.added.length) parts.push("新增" + quote(changes.added));
    if (changes.removed.length) parts.push("删除" + quote(changes.removed));
    if (changes.changed.length) parts.push("修改" + quote(changes.changed));
    if (changes.reordered) parts.push("调整了顺序");
    return parts.length ? parts.join("，") + "。" : "只改了节点以外的设置。";
  }

  function renderVersions() {
    const list = versions || [];
    $("flowVersionSummary").textContent = list.length ? "版本记录 · " + list.length : "版本记录";
    const rows = list.map((item, index) => {
      const row = document.createElement("li");
      const head = document.createElement("p");
      head.className = "flow-version-head";
      head.textContent = versionTime(item.saved_at) + (item.title ? " · " + item.title : "");
      if (!index) {
        const tag = document.createElement("span");
        tag.className = "flow-version-tag";
        tag.textContent = "当前";
        head.append(tag);
      }
      const text = document.createElement("p");
      text.textContent = versionChanges(item.changes);
      row.append(head, text);
      if (index) {
        const load = document.createElement("button");
        load.type = "button";
        load.className = "linkish";
        load.textContent = "载入到画布";
        load.addEventListener("click", () => loadVersion(item));
        row.append(load);
      }
      return row;
    });
    if (!rows.length) {
      const none = document.createElement("li");
      none.textContent = "每次保存都会留下一份版本，下次保存时开始记录。";
      rows.push(none);
    }
    $("flowVersionList").replaceChildren(...rows);
    $("flowVersions").hidden = false;
  }

  async function loadVersions(id) {
    if (!id || graph.builtin) return;
    try {
      const response = await fetch("/api/workflows/" + encodeURIComponent(id) + "/versions");
      const data = await response.json();
      if (!response.ok || id !== loadedId) return;
      versions = data.versions || [];
    } catch (_) {
      return;
    }
    renderVersions();
  }

  // 旧版本只载入画布，成为未保存的修改；保存后才生效，并作为新的一版记下。
  async function loadVersion(item) {
    if (!loadedId || locked()) return;
    const id = loadedId;
    let data;
    try {
      const response = await fetch("/api/workflows/" + encodeURIComponent(id) + "/versions/" + item.version);
      data = await response.json();
      if (!response.ok) {
        showError(data.detail || "没能读取这个版本。");
        return;
      }
    } catch (err) {
      showError(err.message || "没能读取这个版本。");
      return;
    }
    if (id !== loadedId) return;
    const workflow = data.workflow || {};
    graph.title = workflow.title || graph.title;
    graph.description = workflow.description || "";
    graph.nodes = (workflow.nodes || []).map((node) => normalizeNode(node));
    $("flowTitle").value = graph.title;
    $("flowDescription").value = graph.description;
    selectedId = "";
    selectedEdge = null;
    undoStamp = 0;
    renderInspect();
    renderBoard();
    showSaved("已载入 " + versionTime(item.saved_at) + " 的版本。确认无误后保存才生效；撤销可回到载入前。");
  }

  function openSubgraphForm() {
    $("flowDeleteConfirm").hidden = true;
    $("flowSubgraphForm").hidden = false;
    requestAnimationFrame(() => $("flowSubgraphTitle").focus());
  }

  function openDeleteConfirm() {
    $("flowSubgraphForm").hidden = true;
    const title = ($("flowTitle").value || "").trim() || graph.title || loadedId;
    $("flowDeleteText").textContent = "删除流程“" + title + "”（" + loadedId + "）？删除后不能恢复。";
    $("flowDeleteConfirm").hidden = false;
    requestAnimationFrame(() => $("btnDeleteCancel").focus());
  }

  // ---- 级联菜单：与运行页的模型菜单同一套样式与键盘操作 ----

  let menuState = null;

  function closeMenu() {
    if (menuState) menuState.close();
  }

  function toggleMenu(anchor, build, viaKeyboard) {
    if (menuState && menuState.anchor === anchor) {
      closeMenu();
      return;
    }
    openMenu(anchor, build(), viaKeyboard);
  }

  function menuRow(spec) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "role-menu-row" + (spec.danger ? " is-danger" : "");
    row.setAttribute("role", "menuitem");
    row.disabled = Boolean(spec.disabled);
    if (spec.hint) row.title = spec.hint;
    const name = document.createElement("span");
    name.className = "role-menu-row-title";
    name.textContent = spec.title;
    const value = document.createElement("span");
    value.className = "role-menu-row-value";
    value.textContent = spec.value || "";
    row.append(name, value);
    if (spec.items) {
      const more = document.createElement("span");
      more.className = "role-menu-more";
      more.setAttribute("aria-hidden", "true");
      row.appendChild(more);
      row.setAttribute("aria-haspopup", "menu");
    }
    return row;
  }

  function menuOption(item) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "role-menu-option" + (item.checked ? " is-checked" : "");
    el.setAttribute("role", "menuitemradio");
    el.setAttribute("aria-checked", item.checked ? "true" : "false");
    el.disabled = Boolean(item.disabled);
    if (item.hint) el.title = item.hint;
    const label = document.createElement("span");
    label.className = "role-menu-option-label";
    label.textContent = item.text;
    el.appendChild(label);
    if (item.suffix) {
      const extra = document.createElement("span");
      extra.className = "role-menu-option-suffix";
      extra.textContent = item.suffix;
      el.appendChild(extra);
    }
    const mark = document.createElement("span");
    mark.className = "role-menu-check";
    mark.setAttribute("aria-hidden", "true");
    el.appendChild(mark);
    return el;
  }

  /**
   * 一级菜单列出各项及当前值；鼠标移到或焦点落在有下级的行上时，在一级菜单旁弹出取值列表，
   * 优先放在右侧，右侧放不下才放左侧。右方向键进入取值列表，左方向键或 Esc 回到一级菜单。
   */
  function openMenu(anchor, rows, viaKeyboard) {
    closeMenu();
    const wrap = document.createElement("div");
    wrap.className = "role-menu-wrap flow-menu";
    wrap.setAttribute("role", "menu");
    const fly = document.createElement("div");
    fly.className = "role-menu-flyout";
    fly.hidden = true;
    const rowEls = [];
    let returning = false;

    const hideFly = () => {
      fly.hidden = true;
      fly.replaceChildren();
      rowEls.forEach((row) => row.classList.remove("is-open"));
    };
    const focusFly = () => {
      const target = fly.querySelector(".role-menu-option.is-checked:not([disabled])")
        || fly.querySelector(".role-menu-option:not([disabled])");
      if (target) target.focus({ preventScroll: true });
    };
    const placeFly = (row) => {
      const menu = wrap.getBoundingClientRect();
      const at = row.getBoundingClientRect();
      const gap = 4;
      const margin = 8;
      let left = menu.right + gap;
      if (left + fly.offsetWidth > window.innerWidth - margin) left = Math.max(margin, menu.left - gap - fly.offsetWidth);
      let top = at.top - 5;
      if (top + fly.offsetHeight > window.innerHeight - margin) top = Math.max(margin, window.innerHeight - margin - fly.offsetHeight);
      fly.style.left = left + "px";
      fly.style.top = top + "px";
    };
    const pick = (fn) => {
      close();
      if (typeof fn === "function") fn();
    };
    const showFly = (row, spec, focus) => {
      if (!fly.hidden && row.classList.contains("is-open")) {
        if (focus) focusFly();
        return;
      }
      rowEls.forEach((item) => item.classList.toggle("is-open", item === row));
      const list = document.createElement("div");
      list.className = "role-menu-list";
      list.setAttribute("role", "menu");
      spec.items.forEach((item) => {
        const el = menuOption(item);
        el.addEventListener("click", () => pick(item.onPick));
        list.appendChild(el);
      });
      if (!spec.items.length) {
        const empty = document.createElement("p");
        empty.className = "role-menu-empty";
        empty.textContent = spec.empty || "没有可选项。";
        list.appendChild(empty);
      }
      fly.replaceChildren(list);
      fly.hidden = false;
      placeFly(row);
      if (focus) focusFly();
    };
    const backToRow = (row) => {
      hideFly();
      returning = true;
      row.focus({ preventScroll: true });
      returning = false;
    };

    rows.forEach((spec) => {
      if (spec === "divider") {
        const divider = document.createElement("div");
        divider.className = "role-menu-divider";
        divider.setAttribute("role", "separator");
        wrap.appendChild(divider);
        return;
      }
      if (spec.caption) {
        const caption = document.createElement("p");
        caption.className = "flow-menu-caption";
        caption.textContent = spec.caption;
        wrap.appendChild(caption);
        return;
      }
      const row = menuRow(spec);
      if (spec.items) {
        row.dataset.sub = "1";
        row.addEventListener("click", () => showFly(row, spec, true));
        if (!spec.disabled) {
          row.addEventListener("mouseenter", () => showFly(row, spec, false));
          row.addEventListener("focus", () => {
            if (!returning) showFly(row, spec, false);
          });
          row.addEventListener("keydown", (ev) => {
            if (ev.key === "ArrowRight") {
              ev.preventDefault();
              showFly(row, spec, true);
            }
          });
        }
      } else {
        row.addEventListener("click", () => pick(spec.onPick));
        row.addEventListener("mouseenter", hideFly);
        row.addEventListener("focus", hideFly);
      }
      rowEls.push(row);
      wrap.appendChild(row);
    });

    wrap.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
      const items = rowEls.filter((row) => !row.disabled);
      if (!items.length) return;
      ev.preventDefault();
      const at = items.indexOf(document.activeElement);
      const step = ev.key === "ArrowDown" ? 1 : -1;
      items[(at + step + items.length) % items.length].focus();
    });
    fly.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowLeft") {
        ev.preventDefault();
        const row = rowEls.find((item) => item.classList.contains("is-open"));
        if (row) backToRow(row);
        return;
      }
      if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
      const items = [...fly.querySelectorAll(".role-menu-option:not([disabled])")];
      if (!items.length) return;
      ev.preventDefault();
      const at = items.indexOf(document.activeElement);
      const step = ev.key === "ArrowDown" ? 1 : -1;
      items[at < 0 ? 0 : (at + step + items.length) % items.length].focus();
    });

    const onDoc = (ev) => {
      if (ev.type === "keydown") {
        if (ev.key !== "Escape") return;
        ev.preventDefault();
        const row = !fly.hidden && fly.contains(document.activeElement) && rowEls.find((item) => item.classList.contains("is-open"));
        if (row) {
          backToRow(row);
          return;
        }
        close();
        anchor.focus({ preventScroll: true });
        return;
      }
      if (anchor.contains(ev.target) || wrap.contains(ev.target) || fly.contains(ev.target)) return;
      close();
    };
    const onScroll = (ev) => {
      if (ev.target instanceof Node && (wrap.contains(ev.target) || fly.contains(ev.target))) return;
      close();
    };
    function close() {
      document.removeEventListener("pointerdown", onDoc, true);
      document.removeEventListener("keydown", onDoc, true);
      document.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", close);
      wrap.remove();
      fly.remove();
      anchor.setAttribute("aria-expanded", "false");
      anchor.classList.remove("is-menu-open");
      if (menuState && menuState.anchor === anchor) menuState = null;
    }

    document.body.append(wrap, fly);
    const rect = anchor.getBoundingClientRect();
    const margin = 8;
    let left = rect.left;
    if (left + wrap.offsetWidth > window.innerWidth - margin) left = Math.max(margin, rect.right - wrap.offsetWidth);
    let top = rect.bottom + 6;
    if (top + wrap.offsetHeight > window.innerHeight - margin) top = Math.max(margin, rect.top - 6 - wrap.offsetHeight);
    wrap.style.left = left + "px";
    wrap.style.top = top + "px";
    anchor.setAttribute("aria-expanded", "true");
    anchor.classList.add("is-menu-open");
    document.addEventListener("pointerdown", onDoc, true);
    document.addEventListener("keydown", onDoc, true);
    document.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", close);
    menuState = { anchor, close };
    if (viaKeyboard) {
      const first = rowEls.find((row) => !row.disabled);
      if (first) first.focus({ preventScroll: true });
    }
  }

  function selectedNode() {
    return graph.nodes.find((node) => node.id === selectedId) || null;
  }

  function nodeHeading(node) {
    if (node.kind === "activity") return "活动 · " + roleLabel(node.role);
    return KIND_LABELS[node.kind] || "节点";
  }

  function loopsText(node) {
    return node.max_loops ? "最多 " + node.max_loops + " 轮" : "未设轮数";
  }

  function nameOf(id) {
    const node = nodeById(id);
    return node ? node.name : id;
  }

  function loopItems(node) {
    const values = LOOP_CHOICES.slice();
    if (node.max_loops && !values.includes(node.max_loops)) values.push(node.max_loops);
    values.sort((a, b) => a - b);
    return values.map((count) => ({
      text: count + " 轮",
      suffix: count === DEFAULT_LOOPS ? "默认" : "",
      checked: node.max_loops === count,
      onPick: () => {
        node.max_loops = count;
        renderBoard();
        renderInspect();
      },
    }));
  }

  function returnItems(node, afterPick) {
    const items = [{ text: "不回退", checked: !node.returns_to, onPick: () => { setReturn(node, ""); afterPick(); } }];
    returnTargets(node).forEach((item) => items.push({
      text: item.name,
      suffix: KIND_LABELS[item.kind] === "活动" ? "" : KIND_LABELS[item.kind],
      checked: node.returns_to === item.id,
      onPick: () => { setReturn(node, item.id); afterPick(); },
    }));
    return items;
  }

  function rejectItems(node, afterPick) {
    const items = [{ text: "结束本轮", checked: !node.reject_to, onPick: () => { setReject(node, ""); afterPick(); } }];
    rejectTargets(node).forEach((item) => items.push({
      text: item.name,
      suffix: indexOf(item.id) < indexOf(node.id) ? "更早" : "更晚",
      checked: node.reject_to === item.id,
      onPick: () => { setReject(node, item.id); afterPick(); },
    }));
    return items;
  }

  function changeKind(node, kind) {
    if (node.kind === kind) return;
    if (kind === "gate") {
      delete node.inputs;
      delete node.outputs;
      node.contractTouched = false;
      node.role = "human";
      node.kind = "gate";
      node.decision = node.decision || "approve";
      return;
    }
    const role = (roles.find((item) => item.id !== "human") || {}).id || "";
    node.kind = "activity";
    node.role = role;
    node.decision = "";
    delete node.reject_to;
    delete node.items;
    delete node.pass_rule;
    applyRoleContract(node, role, false);
  }

  function changeRole(node, roleId) {
    if (!node.contractTouched) applyRoleContract(node, roleId, false);
    node.role = roleId;
  }

  /** 节点设置的一级菜单行：类型、角色、回退、循环轮数、决定类型、不通过去向、子图。 */
  function nodeMenuRows(node) {
    const after = () => {
      renderBoard();
      renderInspect();
    };
    const rows = [];
    if (node.kind === "activity" || node.kind === "gate") {
      rows.push({
        title: "类型",
        value: KIND_LABELS[node.kind],
        items: ["activity", "gate"].map((kind) => ({
          text: KIND_LABELS[kind],
          suffix: kind === "gate" ? "由人批复" : "",
          checked: node.kind === kind,
          onPick: () => { changeKind(node, kind); after(); },
        })),
      });
    }
    if (node.kind === "activity") {
      rows.push({
        title: "角色",
        value: roleLabel(node.role),
        items: roles.filter((item) => item.id !== "human").map((role) => ({
          text: role.label,
          checked: node.role === role.id,
          onPick: () => { changeRole(node, role.id); after(); },
        })),
      });
    }
    if (node.kind === "gate") {
      rows.push({
        title: "决定类型",
        value: (DECISIONS.find((item) => item.id === (node.decision || "approve")) || DECISIONS[0]).label,
        items: DECISIONS.map((item) => ({
          text: item.label,
          checked: (node.decision || "approve") === item.id,
          onPick: () => {
            node.decision = item.id;
            if (item.id === "pick") {
              delete node.items;
              delete node.pass_rule;
            }
            after();
          },
        })),
      });
      rows.push({
        title: node.decision === "pick" ? "都不采用时" : "不通过时",
        value: node.reject_to ? "前往 " + nameOf(node.reject_to) : "结束本轮",
        items: rejectItems(node, after),
      });
    }
    if (node.kind === "activity" || (node.kind === "gate" && node.returns_to)) {
      rows.push("divider");
      rows.push({
        title: "回退到",
        value: node.returns_to ? nameOf(node.returns_to) : "不回退",
        items: returnItems(node, after),
        empty: "前面没有可以回退的节点。",
      });
      if (node.returns_to) rows.push({ title: "最多循环", value: loopsText(node), items: loopItems(node) });
    }
    if (node.kind === "subgraph" && !graph.subgraph) {
      const subgraphs = workflows.filter((item) => item.subgraph && item.workflow_id !== loadedId);
      rows.push({
        title: "子图",
        value: nameOf(node.id),
        items: subgraphs.map((item) => ({
          text: (item.builtin ? "内置 · " : "") + item.title,
          checked: node.subgraph_id === item.workflow_id,
          onPick: () => {
            const old = workflows.find((wf) => wf.workflow_id === node.subgraph_id);
            if (!old || node.name === old.title) node.name = item.title;
            node.subgraph_id = item.workflow_id;
            after();
          },
        })),
      });
    }
    return rows;
  }

  function nodeSummary(node) {
    const parts = [];
    if (node.kind === "activity") parts.push({ text: roleLabel(node.role) });
    if (node.kind === "gate") {
      parts.push({ text: (DECISIONS.find((item) => item.id === (node.decision || "approve")) || DECISIONS[0]).label });
      parts.push({ text: node.reject_to ? "不通过 → " + nameOf(node.reject_to) : "不通过则结束", muted: !node.reject_to });
    }
    if (node.kind === "activity" || node.returns_to) {
      parts.push(node.returns_to
        ? { text: "回退 → " + nameOf(node.returns_to) + " · " + loopsText(node) }
        : { text: "不回退", muted: true });
    }
    if (node.kind === "subgraph") parts.push({ text: nameOf(node.id) });
    return parts;
  }

  function menuChip(host, parts, build, disabled, label) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "role-menu-chip flow-settings-chip";
    chip.disabled = Boolean(disabled);
    chip.setAttribute("aria-haspopup", "menu");
    chip.setAttribute("aria-expanded", "false");
    chip.setAttribute("aria-label", label + "：" + parts.map((part) => part.text).join("，"));
    const main = document.createElement("span");
    main.className = "role-chip-main" + (parts[0] && parts[0].muted ? " is-inherited" : "");
    main.textContent = parts[0] ? parts[0].text : "";
    const tags = document.createElement("span");
    tags.className = "role-chip-tags";
    parts.slice(1).forEach((part) => {
      const tag = document.createElement("span");
      tag.className = "role-chip-tag" + (part.muted ? " is-inherited" : "");
      tag.textContent = part.text;
      tags.appendChild(tag);
    });
    const caret = document.createElement("span");
    caret.className = "role-chip-caret";
    caret.setAttribute("aria-hidden", "true");
    chip.append(main, tags, caret);
    chip.title = parts.map((part) => part.text).join("；");
    chip.addEventListener("click", (event) => toggleMenu(chip, build, event.detail === 0));
    host.replaceChildren(chip);
  }

  function routeHint(node) {
    const lines = [];
    if (node.returns_to) {
      lines.push("未通过时回到“" + nameOf(node.returns_to) + "”重做，" + loopsText(node) + "；到达上限后停下来等人处理。");
    }
    if (node.kind === "gate") {
      const when = node.decision === "pick" ? "都不采用时" : "不批准时";
      if (node.decision === "pick") lines.push("人从前面并行的各路中采用一路，合并它的改动；其余各路留作补丁。");
      lines.push(node.reject_to ? when + "前往“" + nameOf(node.reject_to) + "”。" : when + "结束本轮。");
    }
    return lines.join("");
  }

  function setInspectHead(title, kind) {
    $("flowInspectTitle").textContent = title;
    $("flowInspectKind").hidden = !kind;
    $("flowInspectKind").textContent = kind || "";
  }

  function renderInspect() {
    const node = selectedNode();
    const edge = !node && selectedEdge && edgeExists(selectedEdge) ? selectedEdge : null;
    $("flowInspectMeta").hidden = Boolean(node || edge);
    $("flowInspectNode").hidden = !node;
    $("flowInspectEdge").hidden = !edge;
    if (edge) {
      renderEdgeInspect(edge);
      return;
    }
    if (!node) {
      setInspectHead("流程说明", "");
      return;
    }
    const fixed = node.kind === "start" || node.kind === "end";
    const readOnly = locked();
    setInspectHead(node.name, nodeHeading(node));
    $("flowNodeName").value = node.name;
    $("flowNodeName").hidden = fixed;
    $("flowNodeName").label = node.kind === "gate"
      ? "决策点"
      : node.kind === "activity"
        ? "活动名"
        : node.kind === "parallel"
          ? "并行"
          : node.kind === "subgraph"
            ? "子图"
            : "名称";
    $("flowNodeName").disabled = readOnly || node.kind === "subgraph";
    const rows = fixed || node.kind === "parallel" || node.kind === "system" ? [] : nodeMenuRows(node);
    $("flowNodeSettings").hidden = !rows.length;
    if (rows.length) menuChip($("flowNodeMenuShell"), nodeSummary(node), () => nodeMenuRows(node), readOnly, "节点设置");
    const hint = routeHint(node);
    $("flowNodeRouteHint").hidden = !hint;
    $("flowNodeRouteHint").textContent = hint;
    $("flowContract").hidden = readOnly || node.kind !== "activity";
    if (!readOnly && node.kind === "activity") renderContract(node);
    const itemized = node.kind === "gate" && node.decision !== "pick";
    $("flowGateItemsBox").hidden = !itemized || (readOnly && !(node.items || []).length);
    if (itemized) renderGateItemsEditor(node, readOnly);
    $("flowSubgraphBox").hidden = node.kind !== "subgraph";
    $("flowParallelBox").hidden = node.kind !== "parallel";
    if (node.kind === "subgraph") renderSubgraph(node);
    if (node.kind === "parallel") renderParallel(node);
    $("flowNodeFixed").hidden = !fixed;
    $("flowNodeActions").hidden = fixed || readOnly;
    const index = indexOf(node.id);
    $("btnFlowUp").disabled = index <= 1;
    $("btnFlowDown").disabled = index >= graph.nodes.length - 2;
    const prev = index > 0 ? graph.nodes[index - 1].name : "无";
    const next = index < graph.nodes.length - 1 ? graph.nodes[index + 1].name : "无";
    $("flowNodeNeighbors").textContent = "前面是" + prev + "，后面是" + next + "。";
  }

  function edgeMenuRows(edge) {
    const node = nodeById(edge.from);
    const after = () => {
      selectedEdge = edgeExists(edge) ? { from: edge.from, kind: edge.kind } : null;
      if (!selectedEdge) selectedId = node.id;
      renderBoard();
      renderInspect();
    };
    if (edge.kind === "return") {
      const rows = [{ title: "回退到", value: nameOf(node.returns_to), items: returnItems(node, after) }];
      rows.push({ title: "最多循环", value: loopsText(node), items: loopItems(node) });
      return rows;
    }
    return [{ title: "前往", value: nameOf(node.reject_to), items: rejectItems(node, after) }];
  }

  function renderEdgeInspect(edge) {
    const node = nodeById(edge.from);
    const readOnly = locked();
    const target = edge.kind === "return" ? node.returns_to : node.reject_to;
    setInspectHead(edge.kind === "return" ? "回退" : "不通过", "连线");
    $("flowEdgeText").textContent = edge.kind === "return"
      ? "“" + node.name + "”未通过时回到“" + nameOf(target) + "”重做，" + loopsText(node) + "；到达上限后停下来等人处理。"
      : "决策点“" + node.name + "”不批准时前往“" + nameOf(target) + "”。删除这条连线后，不批准即结束本轮。";
    const parts = edge.kind === "return"
      ? [{ text: "回到 " + nameOf(target) }, { text: loopsText(node) }]
      : [{ text: "前往 " + nameOf(target) }];
    menuChip($("flowEdgeMenuShell"), parts, () => edgeMenuRows(edge), readOnly, "连线设置");
    $("flowEdgeDragHint").hidden = readOnly;
    $("btnEdgeDelete").hidden = readOnly;
  }

  function renderSubgraph(node) {
    const list = $("flowSubgraphList");
    const note = $("flowSubgraphNote");
    list.replaceChildren();
    note.hidden = true;
    note.textContent = "";
    const found = workflows.find((item) => item.workflow_id === node.subgraph_id);
    if (found && found.workflow_id === "llm_fullnet") {
      note.hidden = false;
      note.textContent = "整网或框架适配是一项；拆出的算子开发会插入 NPU 算子开发子图，并行完成后再做集成验证。";
    }
    fetch("/api/workflows/" + encodeURIComponent(node.subgraph_id))
      .then((response) => response.json())
      .then((data) => {
        if (selectedNode() !== node) return;
        if (data.workflow && data.workflow.description && data.workflow.workflow_id === "llm_fullnet") {
          note.hidden = false;
          note.textContent = data.workflow.description;
        }
        list.replaceChildren();
        (data.workflow && data.workflow.nodes || []).forEach((item) => {
          if (item.kind === "start" || item.kind === "end") return;
          const li = document.createElement("li");
          const kind = item.kind === "gate" ? "决策点" : item.kind === "parallel" ? "并行" : item.kind === "subgraph" ? "子图" : "活动";
          li.textContent = kind + " · " + item.name;
          list.appendChild(li);
        });
      })
      .catch(() => {
        const li = document.createElement("li");
        li.textContent = "读不到这份子图。";
        list.replaceChildren(li);
      });
  }

  // 支路内的回退只能回到同一支路里更早的活动，见 ADR 0031。
  function branchReturnRow(node, step, earlier, locked) {
    const row = document.createElement("div");
    row.className = "branch-return";
    const target = earlier.find((other) => other.id === step.returns_to);
    if (locked) {
      row.textContent = target ? "未通过时回到“" + target.name + "”，最多 " + (step.max_loops || DEFAULT_LOOPS) + " 轮" : "";
      row.hidden = !target;
      return row;
    }
    const label = document.createElement("label");
    label.textContent = "未通过时回到";
    const select = document.createElement("select");
    select.setAttribute("aria-label", "“" + step.name + "”未通过时回到");
    select.appendChild(new Option("不回退", ""));
    earlier.forEach((other) => select.appendChild(new Option(other.name, other.id)));
    select.value = target ? target.id : "";
    const loops = document.createElement("select");
    loops.setAttribute("aria-label", "“" + step.name + "”最多循环轮数");
    LOOP_CHOICES.forEach((count) => loops.appendChild(new Option("最多 " + count + " 轮", String(count))));
    loops.value = String(step.max_loops || DEFAULT_LOOPS);
    loops.hidden = !target;
    select.addEventListener("change", () => {
      step.returns_to = select.value;
      if (select.value) step.max_loops = Number(loops.value) || DEFAULT_LOOPS;
      else delete step.max_loops;
      loops.hidden = !select.value;
      renderBoard();
    });
    loops.addEventListener("change", () => {
      step.max_loops = Number(loops.value) || DEFAULT_LOOPS;
      renderBoard();
    });
    label.appendChild(select);
    row.append(label, loops);
    return row;
  }

  function nextItemId(node) {
    const taken = new Set((node.items || []).map((item) => item.id));
    let n = taken.size + 1;
    while (taken.has("i" + n)) n += 1;
    return "i" + n;
  }

  /** 决策点的决策项：逐项名称、说明、是否必答，以及汇总规则，见 ADR 0032。 */
  function renderGateItemsEditor(node, readOnly) {
    const host = $("flowGateItemsList");
    const items = node.items || [];
    $("flowGateItemsCount").textContent = items.length ? items.length + " 项" : "";
    $("flowGateItemsEmpty").hidden = Boolean(items.length);
    $("btnAddGateItem").hidden = readOnly;
    const changed = () => {
      if (!node.items.length) {
        delete node.items;
        delete node.pass_rule;
      }
      renderBoard();
      renderGateItemsEditor(node, readOnly);
    };
    host.replaceChildren(...items.map((item, index) => {
      const row = document.createElement("li");
      row.className = "gate-item-edit";
      const title = document.createElement("wa-input");
      title.label = "第 " + (index + 1) + " 项";
      title.placeholder = "例如：接口向后兼容";
      title.value = item.title;
      title.disabled = readOnly;
      title.addEventListener("input", () => {
        item.title = (title.value || "").trim();
        renderBoard();
      });
      const hint = document.createElement("wa-input");
      hint.placeholder = "说明（可空）：核对什么、看哪份产物";
      hint.value = item.hint || "";
      hint.disabled = readOnly;
      hint.addEventListener("input", () => {
        const text = (hint.value || "").trim();
        if (text) item.hint = text;
        else delete item.hint;
        renderBoard();
      });
      const tools = document.createElement("div");
      tools.className = "gate-item-edit-tools";
      const required = document.createElement("label");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = item.required !== false;
      box.disabled = readOnly;
      box.addEventListener("change", () => {
        if (box.checked) delete item.required;
        else item.required = false;
        renderBoard();
      });
      required.append(box, " 必答");
      tools.appendChild(required);
      if (!readOnly) {
        const move = (label, delta) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "linkish";
          button.textContent = label;
          const to = index + delta;
          button.disabled = to < 0 || to >= items.length;
          button.addEventListener("click", () => {
            items.splice(to, 0, items.splice(index, 1)[0]);
            changed();
          });
          return button;
        };
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "linkish";
        remove.textContent = "删除";
        remove.addEventListener("click", () => {
          items.splice(index, 1);
          changed();
        });
        tools.append(move("上移", -1), move("下移", 1), remove);
      }
      row.append(title, hint, tools);
      return row;
    }));
    const rule = $("flowGateRule");
    rule.hidden = !items.length;
    if (items.length) {
      const current = node.pass_rule === "manual" ? "manual" : "all";
      const found = PASS_RULES.find((item) => item.id === current);
      const label = document.createElement("label");
      label.textContent = "汇总规则";
      if (readOnly) {
        label.append(" " + found.label);
      } else {
        const select = document.createElement("select");
        PASS_RULES.forEach((item) => select.appendChild(new Option(item.label, item.id, false, item.id === current)));
        select.addEventListener("change", () => {
          if (select.value === "manual") node.pass_rule = "manual";
          else delete node.pass_rule;
          changed();
        });
        label.appendChild(select);
      }
      const hint = document.createElement("span");
      hint.className = "branch-join-hint";
      hint.textContent = found.hint;
      rule.replaceChildren(label, hint);
    }
  }

  function joinRow(node, locked) {
    const row = document.createElement("p");
    row.className = "branch-join";
    const label = document.createElement("label");
    label.textContent = "汇合方式";
    const current = node.join === "compare" ? "compare" : "merge";
    if (locked) {
      label.append(" " + JOINS.find((item) => item.id === current).label);
    } else {
      const select = document.createElement("select");
      JOINS.forEach((item) => select.appendChild(new Option(item.label, item.id, false, item.id === current)));
      select.addEventListener("change", () => {
        if (select.value === "compare") node.join = "compare";
        else delete node.join;
        renderParallel(node);
        renderBoard();
      });
      label.appendChild(select);
    }
    const hint = document.createElement("span");
    hint.className = "branch-join-hint";
    hint.textContent = current === "compare"
      ? "各路改动先不合并，汇合处生成两路对照；后面的“择一”决策点由人选定采用哪一路。"
      : "各路完成后合并改动，冲突时升级。";
    row.append(label, hint);
    return row;
  }

  function renderParallel(node) {
    const host = $("flowParallelBox");
    host.replaceChildren();
    const locked = Boolean(graph.builtin);
    host.appendChild(joinRow(node, locked));
    (node.branches || []).forEach((branch, index) => {
      const block = document.createElement("div");
      block.className = "branch-block";
      const name = document.createElement("wa-input");
      name.label = "支路";
      name.value = branch.name;
      name.disabled = locked;
      name.addEventListener("input", () => {
        branch.name = (name.value || "").trim();
        renderBoard();
      });
      block.appendChild(name);
      const steps = document.createElement("ol");
      steps.className = "settings-list";
      (branch.nodes || []).forEach((step, stepIndex) => {
        const li = document.createElement("li");
        const kind = step.kind === "subgraph" ? "子图" : "活动";
        li.textContent = kind + " · " + step.name;
        if (step.kind === "subgraph" && step.subgraph_id) {
          const open = document.createElement("button");
          open.type = "button";
          open.className = "linkish";
          open.textContent = "打开子图";
          open.addEventListener("click", () => {
            if (!confirmLeave()) return;
            enterOpen(step.subgraph_id, false, [...trail, loadedId]);
          });
          li.appendChild(open);
        }
        if (!locked) {
          const remove = document.createElement("button");
          remove.type = "button";
          remove.className = "linkish";
          remove.textContent = "删除";
          remove.addEventListener("click", () => {
            const removed = step.id;
            branch.nodes.splice(stepIndex, 1);
            branch.nodes.forEach((other) => {
              if (other.returns_to === removed) {
                other.returns_to = "";
                delete other.max_loops;
              }
            });
            renderParallel(node);
            renderBoard();
          });
          li.appendChild(remove);
        }
        const earlier = branch.nodes.slice(0, stepIndex).filter((other) => other.kind === "activity");
        if (step.kind === "activity" && earlier.length) li.appendChild(branchReturnRow(node, step, earlier, locked));
        steps.appendChild(li);
      });
      block.appendChild(steps);
      if (!locked) {
        const row = document.createElement("div");
        row.className = "row-actions";
        const role = document.createElement("wa-select");
        role.label = "角色";
        roles.forEach((item) => {
          if (item.id !== "human") role.appendChild(option(item.id, item.label));
        });
        const activity = document.createElement("wa-input");
        activity.label = "活动名";
        const add = document.createElement("wa-button");
        add.textContent = "添加活动";
        add.variant = "neutral";
        add.appearance = "outlined";
        add.addEventListener("click", () => {
          const activityName = (activity.value || "").trim();
          if (!activityName) {
            showError("先写活动名。");
            return;
          }
          if (!role.value) {
            showError("活动要选择已有角色。");
            return;
          }
          showError("");
          branch.nodes.push({
            id: nextNodeId(),
            kind: "activity",
            name: activityName,
            role: role.value,
            returns_to: "",
          });
          activity.value = "";
          renderParallel(node);
        });
        row.append(role, activity, add);
        block.appendChild(row);
        const drop = document.createElement("wa-button");
        drop.textContent = "删除支路";
        drop.variant = "neutral";
        drop.appearance = "outlined";
        drop.addEventListener("click", () => {
          if ((node.branches || []).length <= 2) {
            showError("并行至少要有两条支路。");
            return;
          }
          showError("");
          node.branches.splice(index, 1);
          renderBoard();
          renderParallel(node);
        });
        block.appendChild(drop);
      }
      host.appendChild(block);
    });
    if (!locked) {
      const addBranch = document.createElement("wa-button");
      addBranch.textContent = "添加支路";
      addBranch.variant = "neutral";
      addBranch.appearance = "outlined";
      addBranch.addEventListener("click", () => {
        node.branches.push({ id: nextBranchId(node), name: "支路" + (node.branches.length + 1), nodes: [] });
        showError("");
        renderBoard();
        renderParallel(node);
      });
      host.appendChild(addBranch);
    }
  }

  function nextBranchId(node) {
    let max = 0;
    (node.branches || []).forEach((branch) => {
      const match = /^b(\d+)$/.exec(branch.id || "");
      if (match) max = Math.max(max, Number(match[1]));
    });
    return "b" + (max + 1);
  }

  async function loadLists() {
    const [flowRes, roleRes] = await Promise.all([
      fetch("/api/workflows").then((response) => response.json()),
      fetch("/api/workflows/roles").then((response) => response.json()),
    ]);
    roles = roleRes.roles || [];
    workflows = flowRes.workflows || [];
    const pick = $("flowPick");
    const selected = pick.value || loadedId;
    ignorePick = true;
    pick.replaceChildren(option("", "请选择"));
    workflows.forEach((item) => {
      const prefix = item.builtin ? "内置 · " : "";
      pick.appendChild(option(item.workflow_id, prefix + item.title));
    });
    if (selected) pick.value = selected;
    ignorePick = false;
    const none = !(flowRes.workflows || []).length;
    $("flowEmpty").hidden = !none;
    $("flowEmptyAction").hidden = !none;
    $("flowPick").hidden = none;
    $("flowPick").disabled = false;
    $("flowHint").hidden = none || Boolean(loadedId);
  }

  async function enterNew(replace) {
    mode = "new";
    loadedId = "";
    selectedId = "";
    setGraph(blankGraph("", ""), "");
    showPieces();
    markClean();
    showError("");
    showSaved("");
    writeUrl("new", "", replace);
  }

  function renderTrail() {
    const nav = $("flowTrail");
    if (mode !== "open" || !loadedId || !trail.length) {
      nav.hidden = true;
      return;
    }
    const titleOf = (id) => (workflows.find((item) => item.workflow_id === id) || {}).title || id;
    const parts = [];
    trail.forEach((id, index) => {
      const link = document.createElement("a");
      link.href = "/workflow?workflow=" + encodeURIComponent(id) + (index ? "&trail=" + trail.slice(0, index).map(encodeURIComponent).join(",") : "") + "#edit";
      link.textContent = titleOf(id);
      link.addEventListener("click", async (event) => {
        event.preventDefault();
        if (!confirmLeave()) return;
        const back = trail.slice(0, index);
        await enterOpen(id, false, back);
      });
      parts.push(link, document.createTextNode(" › "));
    });
    const here = document.createElement("span");
    here.textContent = titleOf(loadedId);
    here.setAttribute("aria-current", "page");
    parts.push(here);
    nav.replaceChildren(...parts);
    nav.hidden = false;
  }

  async function enterOpen(id, replace, parents) {
    mode = "open";
    const nextTrail = (parents || []).filter((item) => item && item !== id && workflows.some((flow) => flow.workflow_id === item));
    if (!id) {
      trail = [];
      loadedId = "";
      selectedId = "";
      setGraph(blankGraph("", ""), "");
      ignorePick = true;
      $("flowPick").value = "";
      ignorePick = false;
      showPieces();
      markClean();
      writeUrl("open", "", replace);
      return;
    }
    const response = await fetch("/api/workflows/" + encodeURIComponent(id));
    const data = await response.json();
    if (!response.ok) {
      showError(data.detail || "打不开这个流程。");
      ignorePick = true;
      $("flowPick").value = loadedId || "";
      ignorePick = false;
      return;
    }
    loadedId = id;
    trail = nextTrail;
    selectedId = "";
    setGraph(data.workflow, data.yaml);
    ignorePick = true;
    $("flowPick").value = id;
    ignorePick = false;
    $("flowHint").hidden = true;
    usage = null;
    problems = null;
    checkedSnap = "";
    showPieces();
    markClean();
    writeUrl("open", id, replace);
    loadUsage(id);
    loadVersions(id);
    stats = null;
    renderStatsNote();
    loadStats(id);
    runCheck();
  }

  async function requestWorkflowMode(nextMode) {
    showSaved("");
    if (nextMode === "import") {
      if (!confirmLeave()) return;
      const input = $("flowImport");
      if (input) input.click();
      return;
    }
    if (nextMode === mode) return;
    if (!confirmLeave()) return;
    if (nextMode === "new") await enterNew(false);
    else await enterOpen("", false);
  }

  window.requestWorkflowMode = requestWorkflowMode;
  window.clearWorkflowNotice = () => showSaved("");

  window.applyWorkflowLocation = async () => {
    showSaved("");
    await loadLists();
    const params = new URLSearchParams(location.search);
    const opened = params.get("workflow") || "";
    if (opened) await enterOpen(opened, true, (params.get("trail") || "").split(","));
    else if (location.hash === "#new") await enterNew(true);
    else if (location.hash === "#edit" || location.hash === "#open") await enterOpen("", true);
    else if ((await fetch("/api/workflows").then((response) => response.json())).workflows.length) await enterOpen("", true);
    else await enterNew(true);
  };

  $("flowPick").addEventListener("wa-show", () => showSaved(""));
  $("flowPick").addEventListener("change", async () => {
    if (ignorePick) return;
    showSaved("");
    const id = ($("flowPick").value || "").trim();
    if (id === (loadedId || "")) return;
    if (!confirmLeave()) {
      ignorePick = true;
      $("flowPick").value = loadedId || "";
      ignorePick = false;
      return;
    }
    showError("");
    await enterOpen(id, false);
  });

  $("btnFlowGoNew").onclick = () => requestWorkflowMode("new");

  async function copySelected(id, title) {
    const source = workflows.find((item) => item.workflow_id === id);
    if (!id || !source) {
      showError("先选择要编辑的流程。");
      return;
    }
    showError("");
    try {
      const response = await fetch("/api/workflows/" + encodeURIComponent(id) + "/copy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        showError(data.detail || "没能复制流程。");
        return;
      }
      await loadLists();
      await enterOpen(data.workflow.workflow_id, false);
      showSaved("已复制为 " + data.workflow.workflow_id + "。");
    } catch (err) {
      showError(err.message || "没能复制流程。");
    }
  }

  if ($("flowImport")) {
    $("flowImport").addEventListener("change", async () => {
      const file = $("flowImport").files && $("flowImport").files[0];
      $("flowImport").value = "";
      if (!file) return;
      showError("");
      showSaved("");
      let text = "";
      try {
        text = await file.text();
      } catch (_) {
        showError("读不到这个文件。");
        return;
      }
      const response = await fetch("/api/workflows/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yaml: text }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        showError(data.detail || "没能导入流程。");
        return;
      }
      await loadLists();
      await enterOpen(data.workflow.workflow_id, false);
      showSaved("已导入 " + data.workflow.title + "。");
    });
  }

  $("btnNameSave").onclick = saveNameEdit;
  $("btnNameCancel").onclick = () => {
    closeNameEdit();
    $("flowPick").focus();
  };
  // 中文输入法用回车确认候选词时 isComposing 为真，不能当作提交。
  const isSubmitKey = (event) => event.key === "Enter" && !event.isComposing && event.keyCode !== 229;
  $("flowNameEdit").addEventListener("keydown", (event) => {
    if (isSubmitKey(event)) saveNameEdit();
    if (event.key === "Escape") {
      closeNameEdit();
      $("flowPick").focus();
    }
  });

  $("btnFlowAdd").addEventListener("click", (event) => {
    toggleMenu($("btnFlowAdd"), () => insertRows(toolbarInsertIndex()), event.detail === 0);
  });
  $("btnFlowMore").addEventListener("click", (event) => {
    toggleMenu($("btnFlowMore"), moreRows, event.detail === 0);
  });
  $("btnSubgraphCancel").onclick = () => {
    $("flowSubgraphForm").hidden = true;
  };
  $("btnDeleteCancel").onclick = () => {
    $("flowDeleteConfirm").hidden = true;
  };

  $("btnDeleteFlow").onclick = async () => {
    const id = loadedId;
    if (!id || graph.builtin) return;
    showError("");
    showSaved("");
    const button = $("btnDeleteFlow");
    button.loading = true;
    button.disabled = true;
    try {
      const response = await fetch("/api/workflows/" + encodeURIComponent(id), { method: "DELETE" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        showError(data.detail || "没能删除流程。");
        return;
      }
      if (Array.isArray(window.__workflows)) {
        window.__workflows = window.__workflows.filter((item) => item.workflow_id !== id);
      }
      if (typeof window.refreshWorkflowOptions === "function") window.refreshWorkflowOptions();
      loadedId = "";
      markClean();
      await loadLists();
      await enterOpen("", false);
      showSaved("已删除 " + id + "。");
    } catch (err) {
      showError(err.message || "没能删除流程。");
    } finally {
      button.loading = false;
      button.disabled = false;
      $("flowDeleteConfirm").hidden = true;
    }
  };

  $("btnCreateFlow").onclick = async () => {
    const title = ($("flowTitle").value || "").trim();
    showError("");
    showSaved("");
    if (!title) {
      showError("先写标题。");
      $("flowTitle").focus();
      return;
    }
    graph.title = title;
    const button = $("btnCreateFlow");
    button.loading = true;
    button.disabled = true;
    let data;
    let id = "";
    try {
      const response = await fetch("/api/workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: graph.title }),
      });
      data = await response.json();
      if (!response.ok) {
        showError(data.detail || "没能创建流程。");
        return;
      }
      id = data.workflow.workflow_id;
      graph.workflow_id = id;
      if (graph.nodes.length > 2 || graph.description) {
        const saved = await fetch("/api/workflows/" + encodeURIComponent(id), {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(wire(graph)),
        });
        const savedData = await saved.json();
        if (!saved.ok) {
          showError(savedData.detail || "流程已创建，但节点没能写入。");
          return;
        }
        data.workflow = savedData.workflow;
        data.yaml = savedData.yaml;
      }
    } catch (err) {
      showError(err.message || "没能创建流程。");
      return;
    } finally {
      button.loading = false;
      button.disabled = false;
    }
    await loadLists();
    loadedId = id;
    mode = "open";
    setGraph(data.workflow, data.yaml);
    showPieces();
    markClean();
    showSaved("已创建流程 " + id + "。");
    writeUrl("open", id, false);
  };

  $("btnSaveFlow").onclick = async () => {
    if (!loadedId) return;
    showError("");
    showSaved("");
    graph.title = ($("flowTitle").value || "").trim() || loadedId;
    graph.description = ($("flowDescription").value || "").trim();
    if (graph.nodes.some((node) => node.returns_to && !(Number.isInteger(Number(node.max_loops)) && Number(node.max_loops) >= 1))) {
      showError("先写最大循环次数。");
      return;
    }
    const response = await fetch("/api/workflows/" + encodeURIComponent(loadedId), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(wire(graph)),
    });
    const data = await response.json();
    if (!response.ok) {
      showError(data.detail || "没能保存流程。");
      return;
    }
    const renamed = (workflows.find((item) => item.workflow_id === loadedId) || {}).title !== data.workflow.title;
    setGraph(data.workflow, data.yaml);
    if (renamed) await loadLists();
    showPieces();
    markClean();
    showSaved("已保存 " + loadedId + "。");
    loadVersions(loadedId);
  };

  $("btnSaveSubgraph").onclick = async () => {
    if (!loadedId) return;
    const title = ($("flowSubgraphTitle").value || "").trim();
    if (!title) {
      showError("先写子图标题。");
      $("flowSubgraphTitle").focus();
      return;
    }
    showError("");
    showSaved("");
    const response = await fetch("/api/workflows/" + encodeURIComponent(loadedId) + "/as-subgraph", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        description: graph.description || "",
        nodes: wireNodes(graph.nodes),
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      showError(data.detail || "没能存为子图。");
      return;
    }
    $("flowSubgraphTitle").value = "";
    $("flowSubgraphForm").hidden = true;
    await loadLists();
    showSaved("已存为子图 " + data.workflow.workflow_id + "。");
  };

  $("btnOpenSubgraph").onclick = () => {
    const node = selectedNode();
    if (!node || node.kind !== "subgraph" || !node.subgraph_id) return;
    if (!confirmLeave()) return;
    enterOpen(node.subgraph_id, false, [...trail, loadedId]);
  };

  if ($("btnAddInput")) {
    $("btnAddInput").onclick = () => {
      const node = selectedNode();
      if (!node || node.kind !== "activity") return;
      materializeContract(node);
      node.inputs.push("");
      renderContract(node);
    };
  }
  if ($("btnAddGateItem")) {
    $("btnAddGateItem").onclick = () => {
      const node = selectedNode();
      if (!node || node.kind !== "gate") return;
      node.items = node.items || [];
      node.items.push({ id: nextItemId(node), title: "" });
      renderBoard();
      renderGateItemsEditor(node, locked());
      const inputs = $("flowGateItemsList").querySelectorAll("wa-input");
      if (inputs.length >= 2) inputs[inputs.length - 2].focus();
    };
  }
  if ($("btnAddOutput")) {
    $("btnAddOutput").onclick = () => {
      const node = selectedNode();
      if (!node || node.kind !== "activity") return;
      materializeContract(node);
      node.outputs.push({ name: "", source: "file", template: "" });
      renderContract(node);
    };
  }
  if ($("btnFileCancel")) $("btnFileCancel").onclick = () => { $("filePicker").hidden = true; };
  if ($("btnFileUp")) {
    $("btnFileUp").onclick = () => loadFilePicker($("filePicker").dataset.parent || "");
  }
  if ($("filePicker")) {
    $("filePicker").addEventListener("click", (event) => {
      if (event.target === $("filePicker")) $("filePicker").hidden = true;
    });
  }

  $("flowTitle").addEventListener("keydown", (event) => {
    if (mode === "new" && isSubmitKey(event)) $("btnCreateFlow").click();
  });
  $("flowSubgraphTitle").addEventListener("keydown", (event) => {
    if (isSubmitKey(event)) $("btnSaveSubgraph").click();
  });
  $("flowTitle").addEventListener("input", () => {
    graph.title = $("flowTitle").value;
  });
  $("flowDescription").addEventListener("input", () => {
    graph.description = $("flowDescription").value;
  });
  $("flowNodeName").addEventListener("input", () => {
    const node = selectedNode();
    if (!node || node.kind === "start" || node.kind === "end") return;
    node.name = $("flowNodeName").value.trim() || node.name;
    $("flowInspectTitle").textContent = node.name;
    renderBoard();
  });
  $("btnFlowUp").onclick = () => moveSelected(-1);
  $("btnFlowDown").onclick = () => moveSelected(1);
  $("btnFlowDelete").onclick = () => deleteNode(selectedNode());
  $("btnEdgeDelete").onclick = () => {
    if (selectedEdge && !locked()) deleteEdge(selectedEdge);
  };
  $("btnEdgeSource").onclick = () => {
    if (selectedEdge) selectNode(selectedEdge.from);
  };

  $("flowScroll").addEventListener("scroll", updateScrollHints, { passive: true });
  if (typeof ResizeObserver === "function") {
    let refit = 0;
    new ResizeObserver(() => {
      updateScrollHints();
      if (refit) return;
      refit = requestAnimationFrame(() => {
        refit = 0;
        const scroll = $("flowScroll");
        const board = $("flowBoard");
        if (Math.abs(scroll.clientWidth - fittedWidth) < 2) return;
        if (board.classList.contains("is-edge-dragging") || board.querySelector(".flow-node[style*=translateX]")) return;
        renderBoard();
      });
    }).observe($("flowScroll"));
  }
  $("flowScroll").addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.target.closest("input, textarea, wa-input, wa-textarea")) return;
    if (event.key === "Escape" && (selectedId || selectedEdge)) {
      selectNode("");
      return;
    }
    if (event.key !== "Delete" && event.key !== "Backspace") return;
    if (locked()) return;
    if (selectedEdge) {
      event.preventDefault();
      deleteEdge(selectedEdge);
    } else if (selectedId) {
      event.preventDefault();
      deleteNode(selectedNode());
    }
  });

  $("btnFlowCheck").onclick = () => {
    if (selectedId || selectedEdge) selectNode("");
    $("flowProblems").scrollIntoView({ block: "nearest" });
  };
  $("btnFlowUndo").onclick = () => stepHistory(-1);
  $("btnFlowRedo").onclick = () => stepHistory(1);
  document.addEventListener("keydown", (event) => {
    if (location.pathname !== "/workflow" || !(event.ctrlKey || event.metaKey) || event.altKey) return;
    const key = event.key.toLowerCase();
    if (key === "s") {
      if ($("btnSaveFlow").hidden || nameEdit) return;
      event.preventDefault();
      $("btnSaveFlow").click();
      return;
    }
    if (key !== "z" && key !== "y") return;
    // 文本框里的撤销交给浏览器，只撤销正在输入的文字。
    const target = event.composedPath()[0];
    if (target && target.closest && target.closest("input, textarea, [contenteditable='true']")) return;
    if (nameEdit || document.querySelector(".role-menu-wrap")) return;
    event.preventDefault();
    stepHistory(key === "y" || event.shiftKey ? 1 : -1);
  });

  const flowView = document.querySelector('.app-view[data-route="workflow"]');
  if (flowView) {
    ["input", "change", "click"].forEach((type) => {
      flowView.addEventListener(type, () => setTimeout(refreshDirty, 0));
    });
  }
  window.addEventListener("beforeunload", (event) => {
    if (location.pathname !== "/workflow" || !isDirty() || mode !== "open") return;
    event.preventDefault();
    event.returnValue = "";
  });

  document.addEventListener("DOMContentLoaded", () => {});

  (async function init() {
    if (!$("flowHeading")) return;
    try {
      await customElements.whenDefined("wa-select");
      await customElements.whenDefined("wa-option");
      if (location.pathname === "/workflow") await window.applyWorkflowLocation();
    } catch (err) {
      window.__workflowInitError = String((err && err.stack) || err);
    }
  })();
})();
