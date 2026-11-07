(function () {
  const $ = (id) => document.getElementById(id);
  const STEP = 118;
  const NODE_W = 92;
  const LANE_H = 84;
  const ORIGIN_X = 84;

  let mode = "new";
  let loadedId = "";
  let selectedId = "";
  let roles = [];
  let graph = blankGraph("", "");
  let snapshot = "";
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
      if (typeof item === "string") return { name: item, source: "file", template: "" };
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
      role: node.role,
      returns_to: node.returns_to || "",
      decision: node.decision || "",
    };
    if (explicit && node.kind === "activity") {
      item.inputs = Array.isArray(node.inputs) ? node.inputs.map((name) => String(name)) : [];
      item.outputs = normalizeOutputs(node.outputs || []);
      item.contractTouched = true;
    }
    return item;
  }

  function applyRoleContract(node, roleId, touched) {
    const found = roleRecord(roleId);
    node.inputs = found && found.inputs ? found.inputs.slice() : [];
    node.outputs = ((found && found.outputs) || []).map((name) => ({ name, source: "file", template: "" }));
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
    return ((found && found.outputs) || []).map((name) => ({ name, source: "file", template: "" }));
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
    const hash = nextMode === "new" ? "#new" : "#open";
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
    graph.nodes.forEach((node) => {
      const match = /^n(\d+)$/.exec(node.id);
      if (match) max = Math.max(max, Number(match[1]));
    });
    return "n" + (max + 1);
  }

  function sanitizeReturns() {
    const index = new Map(graph.nodes.map((node, pos) => [node.id, pos]));
    graph.nodes.forEach((node, pos) => {
      const target = index.get(node.returns_to);
      if (node.returns_to && (target === undefined || target >= pos)) node.returns_to = "";
    });
  }

  function setGraph(data, yaml) {
    graph = {
      workflow_id: data.workflow_id || "",
      title: data.title || "",
      description: data.description || "",
      nodes: (data.nodes || []).map((node) => normalizeNode(node)),
    };
    yamlText = yaml || "";
    $("flowYaml").value = yamlText;
    $("flowTitle").value = graph.title;
    $("flowDescription").value = graph.description;
  }

  function showPieces() {
    const editing = mode === "new" || Boolean(loadedId);
    $("flowOpen").hidden = mode !== "open" || Boolean(loadedId);
    $("flowEditor").hidden = !editing;
    $("btnCreateFlow").hidden = mode !== "new";
    $("btnSaveFlow").hidden = mode !== "open" || !loadedId;
    $("flowRaw").hidden = mode !== "open" || !loadedId;
    if ($("flowIdHint")) $("flowIdHint").hidden = mode !== "new";
    $("flowIdLine").hidden = mode !== "open" || !loadedId;
    if (loadedId) $("flowIdLine").textContent = "流程标识：" + loadedId;
    highlight(mode);
    renderInspect();
    renderBoard();
  }

  function lanesOf() {
    const used = new Set(graph.nodes.map((node) => node.role));
    const lanes = [];
    if (used.has("human")) lanes.push({ id: "human", label: "人类" });
    roles.forEach((role) => {
      if (used.has(role.id)) lanes.push(role);
    });
    return lanes;
  }

  function layoutBoxes() {
    const lanes = lanesOf();
    const laneIndex = new Map(lanes.map((lane, index) => [lane.id, index]));
    return graph.nodes.map((node, index) => {
      const lane = laneIndex.get(node.role) || 0;
      const height = node.kind === "gate" ? 62 : 36;
      const top = lane * LANE_H + (LANE_H - height) / 2;
      return {
        node,
        left: ORIGIN_X + index * STEP,
        top,
        width: NODE_W,
        height,
      };
    });
  }

  function roundedLink(a, b) {
    const y1 = a.top + a.height / 2;
    const y2 = b.top + b.height / 2;
    const x1 = a.left + a.width;
    const x2 = b.left;
    if (x2 >= x1 + 8 && Math.abs(y2 - y1) < 3) return `M ${x1} ${y1} H ${x2}`;
    const forward = x2 > x1 + 20;
    const elbow = forward ? (x1 + x2) / 2 : x1 + 18;
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

  function renderBoard() {
    const board = $("flowBoard");
    const column = $("flowColumn");
    board.replaceChildren();
    column.replaceChildren();
    const lanes = lanesOf();
    const boxes = layoutBoxes();
    const width = Math.max(ORIGIN_X + graph.nodes.length * STEP + 24, 280);
    const height = Math.max(lanes.length, 1) * LANE_H;
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
    boxes.forEach((box, index) => {
      if (index < boxes.length - 1) svg.appendChild(pathEl(roundedLink(box, boxes[index + 1])));
      if (box.node.returns_to) {
        const target = boxes.find((item) => item.node.id === box.node.returns_to);
        if (target) svg.appendChild(pathEl(roundedLink(box, target)));
      }
    });
    board.appendChild(svg);
    boxes.forEach((box) => board.appendChild(nodeButton(box)));
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
  }

  function pathEl(d) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    return path;
  }

  function nodeButton(box) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "flow-node is-" + (box.node.kind === "gate" ? "gate" : box.node.kind === "activity" ? "activity" : "marker");
    if (box.node.id === selectedId) button.classList.add("is-selected");
    button.style.left = box.left + "px";
    button.style.top = box.top + "px";
    button.style.width = box.width + "px";
    button.style.height = box.height + "px";
    if (box.node.kind === "gate") {
      const img = document.createElement("img");
      img.src = "/static/fork-sign.png";
      img.alt = "";
      button.append(img, document.createTextNode(box.node.name));
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
    const x = clientX - board.getBoundingClientRect().left + $("flowScroll").scrollLeft;
    let to = Math.round((x - ORIGIN_X) / STEP);
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
    renderBoard();
    renderInspect();
  }

  function selectedNode() {
    return graph.nodes.find((node) => node.id === selectedId) || null;
  }

  function renderInspect() {
    const node = selectedNode();
    $("flowInspectMeta").hidden = Boolean(node);
    $("flowInspectNode").hidden = !node;
    if (!node) return;
    const fixed = node.kind === "start" || node.kind === "end";
    $("flowNodeHeading").textContent = node.kind === "gate" ? "决策点" : fixed ? node.name : "活动";
    $("flowNodeName").value = node.name;
    $("flowNodeName").label = node.kind === "gate" ? "决策点" : node.kind === "activity" ? "活动名" : "名称";
    $("flowNodeName").disabled = fixed;
    $("flowNodeRole").hidden = fixed;
    $("flowNodeReturn").hidden = fixed;
    $("flowNodeDecision").hidden = node.kind !== "gate";
    if (node.kind === "gate") $("flowNodeDecision").value = node.decision || "approve";
    $("flowContract").hidden = node.kind !== "activity";
    if (node.kind === "activity") renderContract(node);
    $("flowNodeFixed").hidden = !fixed;
    $("btnFlowUp").hidden = fixed;
    $("btnFlowDown").hidden = fixed;
    $("btnFlowDelete").hidden = fixed;
    if (!fixed) $("flowNodeRole").value = node.role;
    fillReturnOptions(node);
    const index = graph.nodes.findIndex((item) => item.id === node.id);
    const prev = index > 0 ? graph.nodes[index - 1].name : "无";
    const next = index < graph.nodes.length - 1 ? graph.nodes[index + 1].name : "无";
    $("flowNodeNeighbors").textContent = "前面是" + prev + "，后面是" + next + "。";
  }

  function fillReturnOptions(node) {
    const select = $("flowNodeReturn");
    const index = graph.nodes.findIndex((item) => item.id === node.id);
    select.replaceChildren(option("", "不回退"));
    graph.nodes.slice(0, index).forEach((item) => {
      if (item.kind !== "end") select.appendChild(option(item.id, item.name));
    });
    select.value = node.returns_to || "";
  }

  function fillRoleSelects() {
    const add = $("flowRole");
    const edit = $("flowNodeRole");
    add.replaceChildren();
    edit.replaceChildren();
    roles.forEach((role) => {
      add.appendChild(option(role.id, role.label));
      edit.appendChild(option(role.id, role.label));
    });
  }

  async function loadLists() {
    const [flowRes, roleRes] = await Promise.all([
      fetch("/api/workflows").then((response) => response.json()),
      fetch("/api/workflows/roles").then((response) => response.json()),
    ]);
    roles = roleRes.roles || [];
    fillRoleSelects();
    const pick = $("flowPick");
    const selected = pick.value;
    pick.replaceChildren(option("", "— 选择 —"));
    (flowRes.workflows || []).forEach((item) => {
      pick.appendChild(option(item.workflow_id, item.title + " (" + item.workflow_id + ")"));
    });
    if (selected) pick.value = selected;
    const none = !(flowRes.workflows || []).length;
    $("flowEmpty").hidden = !none;
    $("flowEmptyAction").hidden = !none;
    $("flowPick").hidden = none;
    $("btnOpenFlow").hidden = none;
    $("flowHint").hidden = none;
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

  async function enterOpen(id, replace) {
    mode = "open";
    if (!id) {
      loadedId = "";
      selectedId = "";
      setGraph(blankGraph("", ""), "");
      showPieces();
      markClean();
      writeUrl("open", "", replace);
      return;
    }
    const response = await fetch("/api/workflows/" + encodeURIComponent(id));
    const data = await response.json();
    if (!response.ok) {
      showError(data.detail || "打不开这个流程。");
      return;
    }
    loadedId = id;
    selectedId = "";
    setGraph(data.workflow, data.yaml);
    $("flowPick").value = id;
    $("flowHint").hidden = true;
    showPieces();
    markClean();
    writeUrl("open", id, replace);
  }

  async function requestWorkflowMode(nextMode) {
    if (nextMode === mode && !(nextMode === "open" && loadedId)) return;
    if (!confirmLeave()) return;
    if (nextMode === "new") await enterNew(false);
    else await enterOpen("", false);
  }

  window.requestWorkflowMode = requestWorkflowMode;

  window.applyWorkflowLocation = async () => {
    await loadLists();
    const opened = new URLSearchParams(location.search).get("workflow") || "";
    if (opened) await enterOpen(opened, true);
    else if (location.hash === "#new") await enterNew(true);
    else if ((await fetch("/api/workflows").then((response) => response.json())).workflows.length) await enterOpen("", true);
    else await enterNew(true);
  };

  $("btnOpenFlow").onclick = async () => {
    const id = $("flowPick").value;
    if (!id) {
      showError("先选择要打开的流程。");
      return;
    }
    if (id === loadedId) return;
    if (!confirmLeave()) return;
    showError("");
    await enterOpen(id, false);
  };

  $("btnFlowGoNew").onclick = () => requestWorkflowMode("new");

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
          body: JSON.stringify(graph),
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
    const response = await fetch("/api/workflows/" + encodeURIComponent(loadedId), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(graph),
    });
    const data = await response.json();
    if (!response.ok) {
      showError(data.detail || "没能保存流程。");
      return;
    }
    setGraph(data.workflow, data.yaml);
    showPieces();
    markClean();
    showSaved("已保存 " + loadedId + "。");
  };

  $("btnSaveFlowRaw").onclick = async () => {
    if (!loadedId) return;
    if (!confirmLeave() && $("flowYaml").value !== yamlText) return;
    const response = await fetch("/api/workflows/" + encodeURIComponent(loadedId) + "/raw", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml: $("flowYaml").value }),
    });
    const data = await response.json();
    if (!response.ok) {
      showError(data.detail || "没能用原文覆盖。");
      return;
    }
    setGraph(data.workflow, data.yaml);
    selectedId = "";
    showPieces();
    markClean();
    showSaved("已用原文覆盖 " + loadedId + "。");
  };

  $("btnAddActivity").onclick = () => {
    const name = ($("flowActivityName").value || "").trim();
    const role = $("flowRole").value;
    if (!name) {
      showError("先写活动名。");
      $("flowActivityName").focus();
      return;
    }
    if (!role) {
      showError("活动要选择已有角色。");
      return;
    }
    showError("");
    const created = {
      id: nextNodeId(),
      kind: role === "human" ? "gate" : "activity",
      name,
      role,
      returns_to: "",
      decision: role === "human" ? "approve" : "",
    };
    if (created.kind === "activity") applyRoleContract(created, role, false);
    graph.nodes.splice(graph.nodes.length - 1, 0, created);
    $("flowActivityName").value = "";
    renderBoard();
  };

  $("btnAddGate").onclick = () => {
    const name = ($("flowGateName").value || "").trim();
    if (!name) {
      showError("先写决策点。");
      $("flowGateName").focus();
      return;
    }
    showError("");
    graph.nodes.splice(graph.nodes.length - 1, 0, {
      id: nextNodeId(),
      kind: "gate",
      name,
      role: "human",
      returns_to: "",
      decision: "approve",
    });
    $("flowGateName").value = "";
    renderBoard();
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
    renderBoard();
  });
  $("flowNodeRole").addEventListener("change", () => {
    const node = selectedNode();
    if (!node || node.kind === "start" || node.kind === "end") return;
    const nextRole = $("flowNodeRole").value;
    const nextKind = nextRole === "human" ? "gate" : "activity";
    if (nextKind === "activity" && !node.contractTouched) applyRoleContract(node, nextRole, false);
    if (nextKind !== "activity") {
      delete node.inputs;
      delete node.outputs;
      node.contractTouched = false;
    }
    node.role = nextRole;
    node.kind = nextKind;
    node.decision = node.kind === "gate" ? (node.decision || "approve") : "";
    renderBoard();
    renderInspect();
  });
  $("flowNodeReturn").addEventListener("change", () => {
    const node = selectedNode();
    if (!node) return;
    node.returns_to = $("flowNodeReturn").value;
    renderBoard();
  });
  $("flowNodeDecision").addEventListener("change", () => {
    const node = selectedNode();
    if (!node || node.kind !== "gate") return;
    node.decision = $("flowNodeDecision").value;
  });
  $("btnFlowUp").onclick = () => moveSelected(-1);
  $("btnFlowDown").onclick = () => moveSelected(1);
  $("btnFlowDelete").onclick = () => {
    const node = selectedNode();
    if (!node || node.kind === "start" || node.kind === "end") return;
    if (!window.confirm("删除「" + node.name + "」？删除后前后节点会重新连上。")) return;
    graph.nodes = graph.nodes.filter((item) => item.id !== node.id);
    graph.nodes.forEach((item) => {
      if (item.returns_to === node.id) item.returns_to = "";
    });
    selectedId = "";
    renderBoard();
    renderInspect();
  };

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
