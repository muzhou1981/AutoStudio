    const $ = (id) => document.getElementById(id);
    const readFetchResponse =
      window.geniApi && window.geniApi.readFetchResponse
        ? window.geniApi.readFetchResponse.bind(window.geniApi)
        : async (response) => {
            const raw = await response.text();
            let data = {};
            if (raw) {
              try {
                data = JSON.parse(raw);
              } catch {
                data = { detail: raw.trim() };
              }
            }
            return { ok: response.ok, status: response.status, data, raw };
          };
    const apiErrorMessage =
      (window.geniApi && window.geniApi.apiErrorMessage) ||
      function (data, fallback) {
        const d = data && data.detail;
        return typeof d === "string" ? d : fallback;
      };
    const formatApiDetail =
      (window.geniApi && window.geniApi.formatApiDetail) ||
      function (msg) {
        return msg == null ? "" : String(msg);
      };
    let awaitingKind = null;
    const PHASE_LABELS = {
      idle: "未启动",
      running: "运行中",
      awaiting_human: "等待人工",
      completed: "已完成",
      paused: "已暂停",
      interrupted: "中断",
      rejected: "已驳回",
      stopped: "已停止",
      saved: "已保存",
    };

    const PHASE_VARIANT = {
      idle: "neutral",
      running: "brand",
      awaiting_human: "warning",
      completed: "success",
      interrupted: "warning",
      rejected: "danger",
      stopped: "neutral",
    };

    const PHASE_ICON = {
      idle: "circle",
      paused: "pause",
      interrupted: "triangle-exclamation",
      completed: "check",
      rejected: "circle-xmark",
      saved: "file",
    };

    function phaseMark(phase) {
      const key = phase || "";
      if (key === "running" || key === "stopped" || key === "awaiting_human") {
        const wrap = document.createElement("span");
        wrap.className = "run-phase run-phase-svg" + (key === "running" ? " is-spin" : "");
        wrap.dataset.phase = key;
        wrap.setAttribute("aria-hidden", "true");
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 16 16");
        svg.setAttribute("focusable", "false");
        if (key === "running") {
          const ring = document.createElementNS("http://www.w3.org/2000/svg", "circle");
          ring.setAttribute("cx", "8");
          ring.setAttribute("cy", "8");
          ring.setAttribute("r", "5.2");
          ring.setAttribute("fill", "none");
          ring.setAttribute("stroke", "currentColor");
          ring.setAttribute("stroke-width", "2");
          ring.setAttribute("stroke-linecap", "round");
          ring.setAttribute("stroke-dasharray", "10 23");
          svg.appendChild(ring);
        } else if (key === "awaiting_human") {
          const mark = document.createElementNS("http://www.w3.org/2000/svg", "path");
          mark.setAttribute("fill", "currentColor");
          mark.setAttribute("fill-rule", "evenodd");
          mark.setAttribute(
            "d",
            "M8 1.5 14.8 14.5H1.2Z M7.2 5.6h1.6v4.1H7.2Z M7.1 12.15a.9.9 0 1 1 1.8 0 .9.9 0 1 1-1.8 0Z",
          );
          svg.appendChild(mark);
        } else {
          const box = document.createElementNS("http://www.w3.org/2000/svg", "rect");
          box.setAttribute("x", "3.4");
          box.setAttribute("y", "3.4");
          box.setAttribute("width", "9.2");
          box.setAttribute("height", "9.2");
          box.setAttribute("rx", "1.5");
          box.setAttribute("fill", "currentColor");
          svg.appendChild(box);
        }
        wrap.appendChild(svg);
        return wrap;
      }
      const meta = document.createElement("wa-icon");
      meta.className = "run-phase";
      meta.setAttribute("name", PHASE_ICON[key] || "circle");
      meta.setAttribute("library", "system");
      meta.dataset.phase = key;
      meta.setAttribute("aria-hidden", "true");
      return meta;
    }

    function setPhase(phase) {
      const p = phase || "idle";
      const pill = $("phasePill");
      pill.dataset.phase = p;
      pill.variant = PHASE_VARIANT[p] || "neutral";
      $("phaseLabel").textContent = PHASE_LABELS[p] || p;
    }

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

    function setLoading(btn, on) {
      btn.loading = !!on;
      btn.disabled = !!on;
    }

    let hitlSearch = location.pathname === "/config" || location.pathname === "/workflow" || location.pathname === "/help" ? "" : location.search;

    const HELP_TOPICS = {
      overview: "概览",
      architecture: "架构",
      guide: "入门指南",
      project: "项目",
      run: "运行",
      workflow: "流程",
      roles: "角色",
      agent: "Agent",
      workspace: "工作区",
      feishu: "飞书",
      env: "环境",
    };

    function showHelp(hash) {
      const raw = (hash || "").replace(/^#/, "");
      const known = Object.prototype.hasOwnProperty.call(HELP_TOPICS, raw);
      const topic = known ? raw : "overview";
      document.querySelectorAll("[data-help-article]").forEach((el) => {
        el.hidden = el.dataset.helpArticle !== topic;
      });
      const heading = $("helpHeading");
      if (heading) heading.textContent = HELP_TOPICS[topic];
      const missing = $("helpMissing");
      if (missing) missing.hidden = known || raw === "";
      document.querySelectorAll("[data-help-topic]").forEach((el) => {
        el.classList.toggle("is-active", el.dataset.helpTopic === topic);
      });
    }

    let draftId = "";
    let draftName = "";
    let loadedDraftProject = "";
    let ignoreProjectChange = false;

    function syncHitlQuery(patch) {
      const params = new URLSearchParams(hitlSearch.startsWith("?") ? hitlSearch.slice(1) : hitlSearch);
      Object.keys(patch).forEach((key) => {
        const value = patch[key];
        if (value) params.set(key, value);
        else params.delete(key);
      });
      const query = params.toString();
      hitlSearch = query ? "?" + query : "";
      if (document.documentElement.dataset.route !== "config") {
        history.replaceState({ route: "hitl" }, "", "/" + hitlSearch);
      }
    }

    function syncUrlThread(tid) {
      const patch = { thread_id: tid || "", thread: "" };
      if (tid) patch.draft = "";
      syncHitlQuery(patch);
    }

    function syncUrlDraft(id) {
      syncHitlQuery({ draft: id || "", thread_id: "", thread: "" });
    }

    function showRunSaved(msg) {
      const el = $("runSaved");
      if (!el) return;
      el.hidden = !msg;
      el.textContent = msg || "";
    }

    function clearDraftBinding() {
      draftId = "";
      draftName = "";
      loadedDraftProject = "";
    }

    let runAttachments = [];

    function formatAttachSize(bytes) {
      const size = Number(bytes) || 0;
      if (size < 1024) return size + " B";
      if (size < 1024 * 1024) return Math.round(size / 1024) + " KB";
      return (size / (1024 * 1024)).toFixed(1) + " MB";
    }

    function renderAttachments() {
      const box = $("attachList");
      if (!box) return;
      box.replaceChildren();
      box.hidden = !runAttachments.length;
      runAttachments.forEach((item) => {
        const row = document.createElement("div");
        row.className = "attach-chip";
        const name = document.createElement("span");
        name.className = "attach-name";
        name.textContent = item.name;
        const size = document.createElement("span");
        size.className = "attach-size";
        size.textContent = formatAttachSize(item.size);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "删除";
        remove.addEventListener("click", () => {
          runAttachments = runAttachments.filter((entry) => entry.id !== item.id);
          renderAttachments();
        });
        row.append(name, size, remove);
        box.appendChild(row);
      });
    }

    function clearAttachments() {
      runAttachments = [];
      renderAttachments();
    }

    async function uploadAttachmentFiles(fileList) {
      const files = [...(fileList || [])];
      if (!files.length) return;
      if (runAttachments.length + files.length > 8) {
        showError($("startError"), "一次最多 8 个附件。");
        return;
      }
      showError($("startError"), "");
      for (const file of files) {
        if (runAttachments.some((item) => item.name === file.name)) {
          showError($("startError"), "已经添加过「" + file.name + "」。");
          continue;
        }
        try {
          const r = await fetch("/api/runs/attachments", {
            method: "POST",
            headers: { "X-Filename": encodeURIComponent(file.name) },
            body: file,
          });
          const { ok, data } = await readFetchResponse(r);
          if (!ok) {
            showError($("startError"), apiErrorMessage(data, "附件没有上传。"));
            return;
          }
          runAttachments.push({ id: data.id, name: data.name, size: data.size });
          renderAttachments();
        } catch (_) {
          showError($("startError"), "附件没有上传。检查服务是否还在，然后重试。");
          return;
        }
      }
    }

    let runNameTouched = false;

    function syncThreadChrome(tid, name) {
      const el = $("sidebarThread");
      if (el) el.hidden = true;
    }

    function focusRunRailView(options) {
      if (document.documentElement.dataset.route !== "hitl") return;
      applyRoute("/", "#region-rail", {
        historyMode: "replace",
        smooth: !!(options && options.smooth),
        skipScroll: !!(options && options.skipScroll),
      });
    }

    function syncRunBoardLayout() {
      const board = document.querySelector(".run-board");
      if (!board) return;
      const bound = !!$("thread").value.trim();
      const compose = !bound;
      board.classList.toggle("is-run-bound", bound);
      board.classList.toggle("is-run-compose", compose);
      const draftActions = document.querySelector(".region-setup-actions");
      if (draftActions) draftActions.hidden = bound;
    }

    async function ensureProjectOnSelect(projectId) {
      const pj = $("project");
      const pid = String(projectId || "").trim();
      if (!pj || !pid) return;
      const hasOption = () =>
        [...pj.querySelectorAll("wa-option")].some((option) => option.value === pid);
      if (!hasOption()) await loadRunConfigOptions();
      if (!hasOption()) return;
      ignoreProjectChange = true;
      pj.value = pid;
      ignoreProjectChange = false;
    }

    function applyBoundRunName(data) {
      const bound = !!$("thread").value.trim();
      const input = $("runName");
      const project = $("project");
      if (input) input.disabled = bound;
      if (project) project.disabled = bound;
      if (!bound) return;
      const name = data && data.values && data.values.run_name;
      if (name && input) input.value = name;
      const projectId = data && data.values && data.values.project_id;
      if (projectId && project) {
        ignoreProjectChange = true;
        project.value = projectId;
        ignoreProjectChange = false;
      }
    }

    function noteFeishu(data) {
      const el = $("feishuNote");
      if (!el) return;
      const notice = data && data.feishu_notice;
      if (notice && !notice.sent && notice.detail) {
        el.hidden = false;
        el.textContent = "飞书通知没有发出：" + notice.detail;
      } else {
        el.hidden = true;
        el.textContent = "";
      }
    }

    const TRASH_ICON = '<svg class="run-delete-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M6.1 1.8h3.8l.35 1.15H13.2v1.25H2.8V2.95h2.95L6.1 1.8zM4.15 5.2h7.7l-.62 8.15c-.04.45-.42.8-.87.8H5.64c-.45 0-.83-.35-.87-.8L4.15 5.2zM6.55 6.7v5.15h1.2V6.7H6.55zm2.7 0v5.15h1.2V6.7H9.25z"/></svg>';

    const EFFORT_LABELS = {
      none: "不推理", minimal: "极低", low: "低", medium: "中", high: "高",
      xhigh: "很高", "extra-high": "很高", max: "最高", ultra: "极限",
    };

    function effortLabel(id) {
      return EFFORT_LABELS[id] ? EFFORT_LABELS[id] + "（" + id + "）" : id;
    }

    function roleModelOptions(role) {
      return runModelCatalogs[runRoleDefaults[role]?.backend] || [];
    }

    /** 某角色当前生效的模型与推理强度；推理强度的可选值来自所选模型在后端目录中的声明。 */
    function roleModelSetting(role) {
      const defaults = runRoleDefaults[role] || {};
      const backend = defaults.backend || "";
      const chosenModel = pendingRoleModels[role] || "";
      const modelId = chosenModel || defaults.model || "";
      const auto = backend === "cursor" && (!modelId || modelId === "default");
      const model = auto ? null : roleModelOptions(role).find((item) => item.id === modelId) || null;
      const efforts = (model && model.reasoning_efforts) || [];
      const effort = pendingRoleReasoningEfforts[role] || "";
      const explicit = !!effort && effort !== "default";
      let problem = "";
      if (explicit && auto) {
        problem = "Auto 模型由 Cursor 自动选择，不能指定推理强度。先选择具体模型，或把推理强度改回沿用默认。";
      } else if (explicit && model && !efforts.some((item) => item.id === effort)) {
        problem = (model.label || modelId) + " 不支持推理强度 " + effort + "，请重新选择。";
      }
      return { backend, defaults, chosenModel, modelId, auto, model, efforts, effort, problem };
    }

    function runReasoningError() {
      for (const role of Object.keys(pendingRoleReasoningEfforts || {})) {
        const problem = roleModelSetting(role).problem;
        if (problem) return (roleTitles[role] || role) + "：" + problem;
      }
      return "";
    }

    function roleModelsLocked(data) {
      return !!(data && data.thread_id && ["completed", "rejected", "stopped"].includes(data.phase));
    }

    function selectOption(value, label) {
      const item = document.createElement("wa-option");
      item.value = value;
      item.textContent = label;
      return item;
    }

    function settingsGroup(caption, className, label) {
      const group = document.createElement("div");
      group.className = "settings-group " + className;
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", label);
      const p = document.createElement("p");
      p.className = "settings-caption";
      p.textContent = caption;
      group.appendChild(p);
      return group;
    }

    /**
     * 右栏顶部的本步骤设置。模型与推理强度绑定角色，归入「角色属性」；Skill 与 MCP 只属于这一步，归入「步骤属性」。
     * 两组各带外框、并排均分，说明统一写在下方。
     */
    function inspectSettings(cell, data) {
      const strip = document.createElement("section");
      strip.className = "inspect-settings";
      strip.setAttribute("aria-label", "本步骤设置");
      const notes = [];
      const columns = document.createElement("div");
      columns.className = "inspect-settings-columns";
      const title = roleTitles[cell.role] || cell.role;
      const roleGroup = settingsGroup("角色属性", "settings-group-role", "角色" + title + "的模型与推理强度");
      roleGroup.appendChild(roleModelSection(cell, data, notes));
      const stepGroup = settingsGroup("步骤属性", "settings-group-step", "本步骤的 Skill 与 MCP");
      stepGroup.append(...nodeToolColumns(cell, data, notes));
      columns.append(roleGroup, stepGroup);
      strip.appendChild(columns);
      notes.sort((a, b) => Number(!!b.error) - Number(!!a.error)).forEach((item) => {
        const p = document.createElement("p");
        p.className = item.error ? "hint-block is-error" : "hint-block";
        p.textContent = item.text;
        strip.appendChild(p);
      });
      return strip;
    }

    /** 本步骤所属角色的模型与推理强度；按角色生效，同一角色的所有步骤共用。 */
    function roleModelSection(cell, data, notes) {
      const role = cell.role;
      const s = roleModelSetting(role);
      const locked = roleModelsLocked(data);
      const section = document.createElement("div");
      section.className = "role-model-block";
      section.setAttribute("aria-label", "角色模型与推理强度");
      const note = (text, cls) => {
        const p = document.createElement("p");
        p.className = cls || "hint-block";
        p.textContent = text;
        section.appendChild(p);
      };
      if (!s.backend) {
        note(runRoleDefaultsError || "正在读取这个角色的模型设置…", runRoleDefaultsError ? "hint-block is-error" : "");
        return section;
      }
      if (s.backend === "stub") {
        note("这个角色使用 Stub 后端，不调用模型。");
        return section;
      }
      const catalog = roleModelOptions(role);
      if (!catalog.length) note(runModelDetails[s.backend] || "读不到模型列表。");
      const model = document.createElement("wa-select");
      model.label = "模型";
      model.setAttribute("placement", "bottom-start");
      model.disabled = locked;
      const inherited = s.defaults.model;
      const inheritedLabel = inherited
        ? (catalog.find((item) => item.id === inherited) || {}).label || inherited
        : s.backend === "cursor" ? "Auto" : "后端默认";
      model.appendChild(selectOption("", "沿用默认（" + inheritedLabel + "）"));
      catalog.forEach((item) => model.appendChild(selectOption(item.id, item.label || item.id)));
      if (s.chosenModel && !catalog.some((item) => item.id === s.chosenModel)) {
        model.appendChild(selectOption(s.chosenModel, s.chosenModel + "（目录中没有）"));
      }
      model.value = s.chosenModel;
      model.addEventListener("change", () => setRoleModel(role, "model", model.value || "", data));
      section.appendChild(model);

      const effort = document.createElement("wa-select");
      effort.label = "推理强度";
      effort.setAttribute("placement", "bottom-start");
      const modelDefault = (s.model && s.model.default_reasoning_effort) || "";
      const configured = s.defaults.reasoning_effort || "";
      const inheritText = configured ? effortLabel(configured) + " · 项目配置"
        : modelDefault ? effortLabel(modelDefault) + " · 模型默认" : "模型默认";
      effort.appendChild(selectOption("", "沿用默认（" + inheritText + "）"));
      if (configured) {
        effort.appendChild(selectOption("default", "模型默认" + (modelDefault ? "（" + effortLabel(modelDefault) + "）" : "")));
      }
      s.efforts.forEach((item) => {
        effort.appendChild(selectOption(item.id, effortLabel(item.id) + (item.id === modelDefault ? " · 模型默认" : "")));
      });
      const explicit = s.effort && s.effort !== "default";
      if (explicit && !s.efforts.some((item) => item.id === s.effort)) {
        effort.appendChild(selectOption(s.effort, effortLabel(s.effort) + "（当前设置）"));
      }
      effort.value = s.effort;
      effort.disabled = locked || (!s.efforts.length && !s.effort);
      effort.hint = s.problem || locked || s.auto ? ""
        : s.modelId && !s.model ? "暂未读取到这个模型的能力。"
        : s.model && !s.efforts.length ? "这个模型没有可调的推理强度。"
        : !s.modelId ? "先选择模型，再选推理强度。" : "";
      effort.addEventListener("change", () => setRoleModel(role, "effort", effort.value || "", data));
      section.appendChild(effort);
      if (s.problem) notes.push({ text: s.problem, error: true });
      if (!locked && data && data.thread_id) notes.push({ text: "运行中修改模型或推理强度，从这个角色的下一次调用起生效。" });
      return section;
    }

    function setRoleModel(role, kind, value, data) {
      const current = kind === "model" ? pendingRoleModels[role] || "" : pendingRoleReasoningEfforts[role] || "";
      if (value === current) return;
      const next = { ...(kind === "model" ? pendingRoleModels : pendingRoleReasoningEfforts) };
      if (value) next[role] = value;
      else delete next[role];
      if (kind === "model") pendingRoleModels = next;
      else pendingRoleReasoningEfforts = next;
      const tid = data && data.thread_id;
      if (!tid || runReasoningError()) {
        renderInspect(lastStatus);
        return;
      }
      fetch("/api/runs/" + encodeURIComponent(tid) + "/role-models", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role_models: pendingRoleModels, role_reasoning_efforts: pendingRoleReasoningEfforts }),
      }).then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(apiErrorMessage(payload, "角色设置没有保存。"));
        lastStatus = payload;
        pendingRoleModels = (payload.values && payload.values.role_models) || {};
        pendingRoleReasoningEfforts = (payload.values && payload.values.role_reasoning_efforts) || {};
        renderInspect(lastStatus);
      }).catch((error) => showError($("startError"), error.message || "角色设置没有保存。"));
    }

    /** 读取各角色的默认后端、模型、推理强度和对应后端的模型目录，供右栏的角色设置使用。 */
    async function refreshRunRoleModels() {
      const version = ++runRoleRefreshVersion;
      const projectId = String($("project").value || "").trim();
      const tid = $("thread").value.trim();
      if (!projectId && !tid) {
        runRoleDefaults = {};
        runModelCatalogs = {};
        runModelDetails = {};
        runRoleDefaultsError = "";
        roleModelStamp = "";
        return;
      }
      const current = () => version === runRoleRefreshVersion;
      const read = async (url) => {
        const response = await fetch(url);
        const data = await response.json();
        if (!response.ok) throw new Error(apiErrorMessage(data, "无法读取角色设置。"));
        return data;
      };
      try {
        if (typeof window.syncRunBackendModels === "function") await window.syncRunBackendModels();
        if (!current()) return;
        const q = new URLSearchParams();
        if (projectId) q.set("project_id", projectId);
        if (tid) q.set("thread_id", tid);
        const defaults = await read("/api/runs/role-defaults?" + q.toString());
        const backends = [...new Set(Object.values(defaults.roles || {}).map((item) => item.backend))];
        const catalogs = {};
        const details = {};
        await Promise.all(backends.map(async (backend) => {
          if (!backend || backend === "stub") return;
          if (backend === window.__runBackendSynced) {
            catalogs[backend] = window.__backendModels || [];
            details[backend] = window.__backendModelsDetail || "";
            return;
          }
          try {
            const listed = await read("/api/config/models?backend=" + encodeURIComponent(backend));
            catalogs[backend] = listed.models || [];
            details[backend] = listed.detail || "";
          } catch (error) {
            catalogs[backend] = [];
            details[backend] = error.message || "读不到模型列表。";
          }
        }));
        if (!current()) return;
        const stamp = JSON.stringify([defaults, catalogs, details]);
        if (stamp === roleModelStamp && !runRoleDefaultsError) return;
        roleModelStamp = stamp;
        runRoleDefaultsError = "";
        runRoleDefaults = defaults.roles || {};
        runModelCatalogs = catalogs;
        runModelDetails = details;
        renderInspect(lastStatus);
      } catch (error) {
        if (!current()) return;
        roleModelStamp = "";
        runRoleDefaultsError = "读不到角色的模型设置：" + (error.message || "服务没有响应")
          + "。刷新页面重试；服务刚更新过代码时，需要先重启服务。";
        renderInspect(lastStatus);
      }
    }

    document.addEventListener("geni-run-backend-models", () => {
      roleModelStamp = "";
      refreshRunRoleModels();
    });

    function clearCurrentRun() {
      stopPoll();
      $("thread").value = "";
      clearDraftBinding();
      syncUrlThread("");
      syncUrlDraft("");
      showRunSaved("");
      syncThreadChrome("");
      applyBoundRunName(null);
      if ($("runName")) $("runName").disabled = false;
      syncStartButton("idle");
      syncStopButton("idle");
      pendingNodeTools = {};
      pendingRoleModels = {};
      pendingRoleReasoningEfforts = {};
      roleModelStamp = "";
      clearAttachments();
      refreshRunRoleModels();
      renderInspect(null);
      loadIdleRail();
      syncRunBoardLayout();
    }

    async function applyRunStartTemplate(data) {
      showError($("startError"), "");
      showRunSaved("");
      stopPoll();
      $("thread").value = "";
      draftId = "";
      draftName = "";
      loadedDraftProject = String(data.project_id || "");
      ignoreProjectChange = true;
      $("project").value = loadedDraftProject;
      ignoreProjectChange = false;
      runNameTouched = true;
      $("runName").value = data.run_name || "";
      $("runName").disabled = false;
      if ($("project")) $("project").disabled = false;
      $("req").value = data.human_request || "";
      runAttachments = (data.attachments || []).map((item) => ({
        id: item.id,
        name: item.name,
        size: item.size,
      }));
      renderAttachments();
      pendingNodeTools = data.node_tools || {};
      pendingRoleModels = data.role_models || {};
      pendingRoleReasoningEfforts = data.role_reasoning_efforts || {};
      roleModelStamp = "";
      syncUrlDraft("");
      syncUrlThread("");
      syncThreadChrome("");
      lastStatus = null;
      lastRailCurrent = "";
      renderInspect(null);
      loadIdleRail();
      syncStartButton("idle");
      syncStopButton("idle");
      setPhase("idle");
      syncRunBoardLayout();
      markRegion($("region-new"));
      const nextHash = "#region-new";
      if (location.hash !== nextHash) {
        history.replaceState(null, "", location.pathname + location.search + nextHash);
      }
      void ensureProjectOnSelect(loadedDraftProject).then(() => {
        void refreshRunRoleModels();
        void syncRunScenarioHint();
      });
      $("req").focus({ preventScroll: true });
    }

    async function copyRunItem(item) {
      const id = item.kind === "draft" ? item.draft_id : item.thread_id;
      try {
        const r = await fetch("/api/runs/" + encodeURIComponent(id) + "/copy", { method: "POST" });
        const data = await r.json();
        if (!r.ok) {
          showError($("startError"), data.detail || "复制失败。");
          return;
        }
        void applyRunStartTemplate(data);
        const from = item.run_name || id;
        showRunSaved("已从「" + from + "」复制到新建表单，确认后启动。");
      } catch (_) {
        showError($("startError"), "复制没有返回。检查服务是否还在，然后重试。");
      }
    }

    async function openDraft(id) {
      showError($("startError"), "");
      showRunSaved("");
      stopPoll();
      try {
        const r = await fetch("/api/runs/drafts/" + encodeURIComponent(id));
        const data = await r.json();
        if (!r.ok) {
          showError($("startError"), data.detail || "读不到这份 Run 配置。");
          return;
        }
        $("thread").value = "";
        draftId = data.draft_id;
        draftName = data.run_name || "";
        loadedDraftProject = String(data.project_id || "");
        ignoreProjectChange = true;
        $("project").value = loadedDraftProject;
        ignoreProjectChange = false;
        runNameTouched = true;
        $("runName").value = data.run_name || "";
        $("runName").disabled = false;
        $("req").value = data.human_request || "";
        runAttachments = (data.attachments || []).map((item) => ({
          id: item.id,
          name: item.name,
          size: item.size,
        }));
        renderAttachments();
        pendingNodeTools = data.node_tools || {};
        pendingRoleModels = data.role_models || {};
        pendingRoleReasoningEfforts = data.role_reasoning_efforts || {};
        roleModelStamp = "";
        syncUrlDraft(draftId);
        syncThreadChrome("");
        applyBoundRunName(null);
        syncStartButton("saved");
        syncStopButton("idle");
        syncRunBoardLayout();
        void ensureProjectOnSelect(loadedDraftProject).then(() => {
          void refreshRunRoleModels();
          void syncRunScenarioHint();
        });
        loadIdleRail();
        void loadRunList();
      } catch (_) {
        showError($("startError"), "读不到这份 Run 配置。检查服务是否还在，然后刷新。");
      }
    }

    function armDelete(row, item) {
      const label = item.run_name || item.thread_id;
      const box = row.parentElement;
      if (box) box.querySelectorAll(".run-confirm").forEach((el) => el.remove());
      const panel = document.createElement("div");
      panel.className = "run-confirm";
      const text = document.createElement("p");
      text.textContent = "删除「" + label + "」？这一轮记录不能恢复，目标仓库里的文件会保留。";
      const ok = document.createElement("button");
      ok.type = "button";
      ok.className = "run-delete-confirm";
      ok.textContent = "确认删除";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "run-delete-cancel";
      cancel.textContent = "取消";
      cancel.addEventListener("click", () => panel.remove());
      ok.addEventListener("click", async () => {
        ok.disabled = true;
        const draft = item.kind === "draft";
        const url = draft
          ? "/api/runs/drafts/" + encodeURIComponent(item.draft_id) + "/delete"
          : "/api/runs/" + encodeURIComponent(item.thread_id) + "/delete";
        const r = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirm_name: label }),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) {
          text.textContent = data.detail || "没有删除。";
          ok.disabled = false;
          return;
        }
        if (draft && draftId === item.draft_id) clearCurrentRun();
        if (!draft && $("thread").value.trim() === item.thread_id) clearCurrentRun();
        await loadRunList();
      });
      panel.append(text, ok, cancel);
      row.after(panel);
    }

    const RUN_PHASE_FILTERS = new Set([
      "running", "paused", "awaiting_human", "completed", "rejected", "stopped",
    ]);
    let runListSeq = 0;

    async function loadRunList() {
      const box = $("runList");
      if (!box) return;
      const raw = $("runPhaseFilter") ? $("runPhaseFilter").value : "all";
      const phase = RUN_PHASE_FILTERS.has(raw) ? raw : "";
      const seq = ++runListSeq;
      const q = new URLSearchParams();
      if (phase) q.set("phase", phase);
      try {
        const r = await fetch("/api/runs?" + q.toString());
        const data = await r.json();
        if (seq !== runListSeq) return;
        box.replaceChildren();
        const runs = (r.ok && data.runs) || [];
        if (!runs.length) {
          const empty = document.createElement("p");
          empty.className = "hint-block sidebar-sub";
          empty.textContent = "还没有运行。";
          box.appendChild(empty);
          return;
        }
        const current = $("thread").value.trim() || draftId;
        for (const item of runs) {
          const label = item.run_name || item.thread_id;
          const row = document.createElement("div");
          row.className = "run-row";
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "run-open" + (item.thread_id === current ? " is-current" : "");
          const phaseLabel = PHASE_LABELS[item.phase] || item.phase;
          const name = document.createElement("span");
          name.className = "run-name";
          name.textContent = label;
          const meta = phaseMark(item.phase);
          const phaseText = document.createElement("span");
          phaseText.className = "run-phase-label";
          phaseText.textContent = phaseLabel;
          btn.title = label + " · " + phaseLabel;
          btn.append(name, meta, phaseText);
          btn.addEventListener("click", () => {
            if (item.kind === "draft") {
              openDraft(item.draft_id);
              return;
            }
            clearDraftBinding();
            clearAttachments();
            $("thread").value = item.thread_id;
            syncUrlThread(item.thread_id);
            lastRailCurrent = "";
            applyBoundRunName(null);
            syncRunBoardLayout();
            void refresh({ quiet: true });
          });
          const del = document.createElement("button");
          del.type = "button";
          del.className = "run-delete";
          del.setAttribute("aria-label", "删除");
          del.title = "删除「" + label + "」";
          del.innerHTML = TRASH_ICON;
          const copy = document.createElement("button");
          copy.type = "button";
          copy.className = "run-copy";
          copy.setAttribute("aria-label", "复制");
          copy.title = "复制到新建 Run";
          copy.textContent = "复制";
          copy.addEventListener("click", (event) => {
            event.stopPropagation();
            void copyRunItem(item);
          });
          del.addEventListener("click", (event) => {
            event.stopPropagation();
            armDelete(row, item);
          });
          row.append(btn, copy, del);
          box.appendChild(row);
        }
      } catch (_) { /* 列表读不到时仍可按地址栏打开一轮 */ }
    }

    async function fillRunNameSuggestion() {
      const input = $("runName");
      if (!input || $("thread").value.trim() || runNameTouched) return;
      const pid = String($("project").value || "").trim();
      if (!pid) {
        input.value = "";
        return;
      }
      try {
        const r = await fetch("/api/runs/next-name?project_id=" + encodeURIComponent(pid));
        const data = await r.json();
        if (!r.ok || runNameTouched || $("thread").value.trim()) return;
        input.value = data.run_name || "";
      } catch (_) { /* 建议名取不到时仍可手填 */ }
    }

    const STATE_LABEL = {
      pending: "未到",
      skipped: "跳过",
      done: "完成",
      active: "进行中",
      waiting: "待批复",
      paused: "已暂停",
      interrupted: "中断",
      stopped: "已停止",
      initial: "初始",
      finished: "结束",
    };
    let lastStatus = null;
    let lastRailCurrent = "";
    let pendingNodeTools = {};
    let pendingRoleModels = {};
    let pendingRoleReasoningEfforts = {};
    let runRoleDefaults = {};
    let runModelCatalogs = {};
    let runModelDetails = {};
    let runRoleDefaultsError = "";
    let runRoleRefreshVersion = 0;
    let roleModelStamp = "";
    let runToolCatalog = { skills: [], mcp: [], detail: "" };
    let statusKey = "";
    let pollTimer = null;
    let refreshing = false;
    let startInFlight = false;

    function stopPoll() {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = null;
      if (pushSource) {
        pushSource.close();
        pushSource = null;
        pushThread = "";
      }
    }

    function currentCell(rail) {
      if (!rail || !rail.cells) return null;
      if (rail.current) {
        return rail.cells.find((cell) => cell.id === rail.current) || null;
      }
      const done = rail.cells.filter((cell) => cell.state === "done");
      return done.length ? done[done.length - 1] : null;
    }

    function viewedCell(rail) {
      if (!rail || !rail.cells) return null;
      const want = nodeParam();
      if (want) {
        const found = rail.cells.find((cell) => cell.id === want);
        if (found) return found;
      }
      return currentCell(rail);
    }

    function nodeParam() {
      const raw = hitlSearch.startsWith("?") ? hitlSearch.slice(1) : hitlSearch;
      return new URLSearchParams(raw).get("node") || "";
    }

    function setNodeParam(id) {
      const params = new URLSearchParams(hitlSearch.startsWith("?") ? hitlSearch.slice(1) : hitlSearch);
      if (id) params.set("node", id);
      else params.delete("node");
      const query = params.toString();
      hitlSearch = query ? "?" + query : "";
      if (document.documentElement.dataset.route !== "config") {
        history.replaceState({ route: "hitl" }, "", "/" + hitlSearch);
      }
    }

    function railArrow() {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "rail-arrow");
      svg.setAttribute("viewBox", "0 0 22 16");
      svg.setAttribute("width", "22");
      svg.setAttribute("height", "16");
      svg.setAttribute("aria-hidden", "true");
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("class", "awire-body");
      line.setAttribute("x1", "1");
      line.setAttribute("y1", "8");
      line.setAttribute("x2", "13");
      line.setAttribute("y2", "8");
      const head = document.createElementNS("http://www.w3.org/2000/svg", "path");
      head.setAttribute("class", "awire-head");
      head.setAttribute("d", "M11.4 3.6 L16.6 8 L11.4 12.4");
      svg.append(line, head);
      return svg;
    }

    function railWire(kind) {
      const mark = document.createElement("span");
      mark.className = "rail-wire" + (kind ? " " + kind : "");
      mark.setAttribute("aria-hidden", "true");
      mark.appendChild(railArrow());
      return mark;
    }

    const SWIM_LANES = [
      { id: "decision", label: "人类" },
      { id: "project", role: "project_manager" },
      { id: "config", role: "config_manager" },
      { id: "ux", role: "ux_designer" },
      { id: "ui", role: "ui_designer" },
      { id: "visual", role: "visual_designer" },
      { id: "architect", role: "architect" },
      { id: "develop", role: "developer" },
      { id: "review", role: "code_reviewer" },
      { id: "test", role: "tester" },
      { id: "qa", role: "qa" },
      { id: "compliance", role: "compliance" },
      { id: "process", role: "process_owner" },
      { id: "finance", role: "finance" },
    ];
    let roleTitles = {};
    let swimMeta = {};
    function laneLabel(lane) {
      if (lane.label) return lane.label;
      return roleTitles[lane.role] || lane.role || lane.id;
    }
    async function loadRoleTitles() {
      try {
        const data = await fetch("/api/workflows/roles").then((response) => response.json());
        roleTitles = {};
        (data.roles || []).forEach((role) => { roleTitles[role.id] = role.label; });
      } catch (err) { /* 角色名暂时用标识 */ }
    }
    const SWIM_LANE_OF = {
      run_start: "decision",
      run_end: "decision",
      project_manager_draft: "project",
      project_manager_scope: "project",
      project_manager_delivery: "project",
      gate_requirement_confirm: "decision",
      gate_architecture_review: "decision",
      gate_final_delivery: "decision",
      config_manager_plan: "config",
      config_manager_closeout: "config",
      ux_designer: "ux",
      ui_designer: "ui",
      visual_designer: "visual",
      architect: "architect",
      developer: "develop",
      change_control: "develop",
      code_reviewer: "review",
      tester_testability: "test",
      tester_execute: "test",
      qa: "qa",
      process_owner_retro: "process",
      finance_budget_rough: "finance",
      finance_budget_final: "finance",
      finance_cost_snapshot: "finance",
    };
    function swimLaneId(id) {
      const cell = swimMeta[id];
      if (cell && cell.role) {
        if (cell.role === "human" || cell.kind === "gate" || cell.kind === "start" || cell.kind === "end") return "decision";
        const lane = SWIM_LANES.find((item) => item.role === cell.role);
        if (lane) return lane.id;
      }
      if (SWIM_LANE_OF[id]) return SWIM_LANE_OF[id];
      if (String(id).startsWith("gate_")) return "decision";
      return "develop";
    }

    let swimObserver = null;

    function swimKind(id) {
      const cell = swimMeta[id];
      if (cell && (cell.kind === "start" || cell.kind === "end")) return "marker";
      if (cell && cell.kind === "gate") return "gate";
      if (id === "run_start" || id === "run_end") return "marker";
      if (String(id).startsWith("gate_")) return "gate";
      return "node";
    }

    function makeRailButton(cell, current) {
      const pointed = current && current.id === cell.id;
      const stateLabel = STATE_LABEL[cell.state] || cell.state;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "rail-cell" + (cell.state === "active" ? " is-live" : "");
      button.dataset.state = cell.state;
      button.dataset.id = cell.id;
      button.title = stateLabel;
      button.setAttribute("aria-label", cell.label + "，" + stateLabel);
      if (pointed) button.setAttribute("aria-current", "step");
      const viewing = nodeParam() || (current && current.id) || "";
      button.classList.toggle("is-viewed", cell.id === viewing);
      button.setAttribute("aria-pressed", cell.id === viewing ? "true" : "false");
      button.addEventListener("click", () => {
        const liveId = current && current.id;
        setNodeParam(cell.id === liveId ? "" : cell.id);
        const nextView = nodeParam() || liveId || "";
        document.querySelectorAll("#region-rail .rail-cell").forEach((el) => {
          const on = el.dataset.id === nextView;
          el.classList.toggle("is-viewed", on);
          el.setAttribute("aria-pressed", on ? "true" : "false");
        });
        renderInspect(lastStatus && lastStatus.rail ? lastStatus : null);
      });
      return button;
    }

    function renderFlatRail(cells, current) {
      const list = $("nodeRail");
      list.replaceChildren();
      cells.forEach((cell, index) => {
        const pointed = current && current.id === cell.id;
        const li = document.createElement("li");
        li.className = "rail-step";
        if (index > 0 || pointed) {
          const kind = pointed ? (cell.state === "active" ? "is-live" : "is-mark") : "";
          li.appendChild(railWire(kind));
        }
        const button = makeRailButton(cell, current);
        button.textContent = cell.label;
        li.appendChild(button);
        list.appendChild(li);
      });
    }

    function renderSwim(cells, current) {
      swimMeta = {};
      cells.forEach((cell) => { swimMeta[cell.id] = cell; });
      const host = $("swimRail");
      host.replaceChildren();
      const lanes = SWIM_LANES.filter((lane) => cells.some((cell) => swimLaneId(cell.id) === lane.id));
      const grid = document.createElement("div");
      grid.className = "swim-grid";
      const laterDone = current
        ? cells.some((cell, index) => index > cells.findIndex((item) => item.id === current.id) && cell.state === "done")
        : false;
      if (laterDone) grid.classList.add("has-return");
      lanes.forEach((lane) => {
        const row = document.createElement("div");
        row.className = "swim-lane";
        const label = document.createElement("div");
        label.className = "swim-label";
        label.textContent = laneLabel(lane);
        const track = document.createElement("div");
        track.className = "swim-track";
        cells.forEach((cell, index) => {
          if (swimLaneId(cell.id) !== lane.id) return;
          const kind = swimKind(cell.id);
          const button = makeRailButton(cell, current);
          button.classList.add("swim-cell", "is-" + kind);
          button.dataset.seq = String(index);
          button.title = cell.label + "，" + (STATE_LABEL[cell.state] || cell.state);
          const name = document.createElement("span");
          name.className = "swim-name";
          name.textContent = cell.label;
          if (kind === "gate") {
            const mark = document.createElement("img");
            mark.className = "swim-decision";
            mark.src = "/static/fork-sign.png";
            mark.alt = "";
            button.append(mark, name);
          } else {
            button.append(name);
          }
          track.appendChild(button);
        });
        row.append(label, track);
        grid.appendChild(row);
      });
      const scroller = document.createElement("div");
      scroller.className = "swim-scroll";
      scroller.appendChild(grid);
      host.appendChild(scroller);
      if (swimObserver) swimObserver.disconnect();
      swimObserver = new ResizeObserver(() => layoutSwimEdges());
      swimObserver.observe(scroller);
      layoutSwimEdges();
    }

    let swimLaying = false;

    function swimMarker(id, color) {
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
      marker.setAttribute("id", id);
      marker.setAttribute("viewBox", "0 0 8 8");
      marker.setAttribute("refX", "7");
      marker.setAttribute("refY", "4");
      marker.setAttribute("markerWidth", "7");
      marker.setAttribute("markerHeight", "7");
      marker.setAttribute("orient", "auto");
      const head = document.createElementNS("http://www.w3.org/2000/svg", "path");
      head.setAttribute("d", "M1 1 L7 4 L1 7");
      head.setAttribute("fill", "none");
      head.setAttribute("stroke", color);
      head.setAttribute("stroke-width", "1.4");
      head.setAttribute("stroke-linecap", "round");
      head.setAttribute("stroke-linejoin", "round");
      marker.appendChild(head);
      return marker;
    }

    function fitSwimLabels(grid) {
      const labels = [...grid.querySelectorAll(".swim-label")];
      if (!labels.length) return;
      labels.forEach((el) => { el.style.width = "auto"; });
      const width = Math.max(...labels.map((el) => el.scrollWidth));
      labels.forEach((el) => { el.style.width = width + "px"; });
    }

    function layoutSwimTimeline(grid) {
      fitSwimLabels(grid);
      const track = grid.querySelector(".swim-track");
      if (!track) return;
      const width = track.clientWidth;
      if (width < 2) return;
      const buttons = [...grid.querySelectorAll(".swim-cell")].sort(
        (a, b) => Number(a.dataset.seq) - Number(b.dataset.seq)
      );
      const n = buttons.length;
      if (!n) return;
      const widths = buttons.map((el) => el.offsetWidth);
      const gap = 6;
      const left = new Array(n).fill(0);
      if (n > 1) {
        const start = widths[0] / 2;
        const end = Math.max(start, width - widths[n - 1] / 2);
        for (let i = 0; i < n; i += 1) {
          left[i] = start + ((end - start) * i) / (n - 1) - widths[i] / 2;
        }
      }
      const groups = new Map();
      buttons.forEach((el, index) => {
        const lane = el.closest(".swim-lane");
        if (!groups.has(lane)) groups.set(lane, []);
        groups.get(lane).push(index);
      });
      const separate = () => {
        groups.forEach((indices) => {
          for (let k = 1; k < indices.length; k += 1) {
            const prev = indices[k - 1];
            const next = indices[k];
            const minLeft = left[prev] + widths[prev] + gap;
            if (left[next] < minLeft) left[next] = minLeft;
          }
        });
        const minStep = Math.max(14, width / (n + 2));
        for (let i = 1; i < n; i += 1) {
          const prevCenter = left[i - 1] + widths[i - 1] / 2;
          const center = left[i] + widths[i] / 2;
          if (center < prevCenter + minStep) left[i] += prevCenter + minStep - center;
        }
      };
      separate();
      const overflow = left[n - 1] + widths[n - 1] - width;
      if (overflow > 1 && left[n - 1] > 0) {
        const scale = (width - widths[n - 1]) / left[n - 1];
        for (let i = 0; i < n; i += 1) left[i] *= scale;
      }
      buttons.forEach((el, index) => {
        const maxLeft = Math.max(0, width - widths[index]);
        el.style.left = Math.min(Math.max(0, left[index]), maxLeft) + "px";
      });
    }

    function layoutSwimEdges() {
      if (swimLaying || !window.matchMedia("(min-width: 900px)").matches) return;
      swimLaying = true;
      const grid = document.querySelector("#swimRail .swim-grid");
      if (!grid) {
        swimLaying = false;
        return;
      }
      const buttons = [...grid.querySelectorAll(".swim-cell")].sort(
        (a, b) => Number(a.dataset.seq) - Number(b.dataset.seq)
      );
      if (buttons.length < 2) {
        swimLaying = false;
        return;
      }
      const box = grid.getBoundingClientRect();
      if (box.width < 2) {
        swimLaying = false;
        return;
      }
      layoutSwimTimeline(grid);
      let svg = grid.querySelector(".swim-edges");
      if (!svg) {
        svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("class", "swim-edges");
        svg.setAttribute("aria-hidden", "true");
        grid.appendChild(svg);
      }
      svg.setAttribute("viewBox", "0 0 " + grid.scrollWidth + " " + grid.scrollHeight);
      svg.replaceChildren();
      const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
      const accent = getComputedStyle(grid).getPropertyValue("--accent").trim() || "#2563eb";
      defs.append(swimMarker("swimHead", "#71717a"), swimMarker("swimHeadHot", accent));
      svg.appendChild(defs);
      const spot = (el) => {
        const rect = el.getBoundingClientRect();
        return {
          x: rect.left - box.left + rect.width / 2,
          y: rect.top - box.top + rect.height / 2,
          left: rect.left - box.left,
          right: rect.right - box.left,
          top: rect.top - box.top,
          bottom: rect.bottom - box.top,
        };
      };
      const roundedOrth = (points, radius) => {
        if (points.length < 2) return "";
        let d = "M " + points[0].x + " " + points[0].y;
        for (let i = 1; i < points.length - 1; i += 1) {
          const prev = points[i - 1];
          const cur = points[i];
          const next = points[i + 1];
          const inLen = Math.hypot(cur.x - prev.x, cur.y - prev.y);
          const outLen = Math.hypot(next.x - cur.x, next.y - cur.y);
          const rad = Math.min(radius, inLen / 2, outLen / 2);
          if (rad < 1) {
            d += " L " + cur.x + " " + cur.y;
            continue;
          }
          const inX = cur.x - ((cur.x - prev.x) / inLen) * rad;
          const inY = cur.y - ((cur.y - prev.y) / inLen) * rad;
          const outX = cur.x + ((next.x - cur.x) / outLen) * rad;
          const outY = cur.y + ((next.y - cur.y) / outLen) * rad;
          d += " L " + inX + " " + inY + " Q " + cur.x + " " + cur.y + " " + outX + " " + outY;
        }
        const last = points[points.length - 1];
        return d + " L " + last.x + " " + last.y;
      };
      const sideLink = (a, b) => {
        const x1 = a.right + 1;
        const y1 = a.y;
        const x2 = b.left - 2;
        const y2 = b.y;
        if (Math.abs(y1 - y2) < 8 && x2 > x1) {
          return "M " + x1 + " " + y1 + " L " + x2 + " " + y2;
        }
        if (x2 > x1 + 12) {
          const mid = (x1 + x2) / 2;
          return roundedOrth(
            [{ x: x1, y: y1 }, { x: mid, y: y1 }, { x: mid, y: y2 }, { x: x2, y: y2 }],
            8
          );
        }
        const xOut = a.right + 14;
        const xIn = b.left - 14;
        const midY = y1 + (y2 - y1) / 2;
        return roundedOrth(
          [
            { x: x1, y: y1 },
            { x: xOut, y: y1 },
            { x: xOut, y: midY },
            { x: xIn, y: midY },
            { x: xIn, y: y2 },
            { x: x2, y: y2 },
          ],
          8
        );
      };
      const points = buttons.map(spot);
      const current = buttons.find((el) => el.getAttribute("aria-current") === "step");
      const currentIndex = current ? buttons.indexOf(current) : -1;
      let returnFrom = -1;
      if (currentIndex >= 0) {
        for (let index = buttons.length - 1; index > currentIndex; index -= 1) {
          if (buttons[index].dataset.state === "done") {
            returnFrom = index;
            break;
          }
        }
      }
      const hot = !current
        ? ""
        : current.dataset.state === "active"
          ? "is-live"
          : (current.dataset.state === "waiting" || current.dataset.state === "paused" || current.dataset.state === "interrupted" || current.dataset.state === "stopped")
            ? "is-mark"
            : "";
      const add = (d, kind) => {
        if (!d) return;
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", d);
        path.setAttribute("class", "swim-edge" + (kind ? " " + kind : ""));
        path.setAttribute("marker-end", kind ? "url(#swimHeadHot)" : "url(#swimHead)");
        svg.appendChild(path);
      };
      for (let index = 0; index < points.length - 1; index += 1) {
        const intoCurrent = returnFrom < 0 && index + 1 === currentIndex;
        add(sideLink(points[index], points[index + 1]), intoCurrent ? hot : "");
      }
      if (returnFrom > currentIndex && currentIndex >= 0) {
        const from = points[returnFrom];
        const to = points[currentIndex];
        const low = Math.max(from.bottom, to.bottom) + 14;
        add(roundedOrth(
          [
            { x: from.x, y: from.bottom + 1 },
            { x: from.x, y: low },
            { x: to.x, y: low },
            { x: to.x, y: to.bottom + 1 },
          ],
          8
        ), hot);
        const note = document.createElementNS("http://www.w3.org/2000/svg", "text");
        note.setAttribute("class", "swim-return");
        note.setAttribute("x", String((from.x + to.x) / 2));
        note.setAttribute("y", String(low - 4));
        note.textContent = "退回";
        svg.appendChild(note);
      }
      swimLaying = false;
    }

    function renderRail(rail) {
      const count = $("railCount");
      count.hidden = true;
      const cells = (rail && rail.cells) || [];
      const current = currentCell(rail);
      if (!cells.length) {
        $("nodeRail").replaceChildren();
        $("swimRail").replaceChildren();
        return;
      }
      renderFlatRail(cells, current);
      renderSwim(cells, current);
    }

    function renderInspect(data) {
      const box = $("statusHuman");
      const rail = data && data.rail;
      const cell = viewedCell(rail);
      $("inspectTitle").textContent = cell ? cell.label : "运行检视";
      if (!data || !data.thread_id) {
        box.replaceChildren();
        if (isActivityCell(cell)) {
          box.append(inspectSettings(cell, null));
        } else {
          const p = document.createElement("p");
          p.className = "status-empty";
          p.textContent = "还没有运行记录。填写交付目标并启动后，阶段和会话会显示在这里。";
          box.appendChild(p);
        }
        setPhase(draftId ? "saved" : "idle");
        return;
      }
      setPhase(data.phase);
      if (!cell) {
        box.replaceChildren();
        const p = document.createElement("p");
        p.className = "status-empty";
        p.textContent = "这一步还没有记录。";
        box.appendChild(p);
        return;
      }
      const vals = data.values || {};
      const rows = [];
      if (rail && cell.id === rail.current && data.awaiting_human && data.awaiting_human.summary) {
        rows.push(["摘要", data.awaiting_human.summary, false]);
      }
      if (cell.id === "qa" && vals.qa_status) rows.push(["QA", vals.qa_status, false]);
      const dl = document.createElement("dl");
      dl.className = "status-dl";
      for (const [k, v, mono] of rows) {
        const row = document.createElement("div");
        row.className = "status-row";
        const dt = document.createElement("dt");
        dt.textContent = k;
        const dd = document.createElement("dd");
        if (mono) dd.className = "mono";
        dd.textContent = String(v);
        row.append(dt, dd);
        dl.appendChild(row);
      }
      const convPayload = conversations[cell.id];
      const convLive = data.phase === "running" && rail && cell.id === rail.current;
      const convTurns = (convPayload && convPayload.turns) || [];
      const showConversation = convLive || convTurns.length > 0;
      const session = showConversation
        ? formatConversation(convPayload, {
            live: convLive && (conversationTurnInFlight(convTurns.slice(-1)[0]) || !convTurns.length),
          })
        : "";
      const inspectParts = [];
      if (isActivityCell(cell)) inspectParts.push(inspectSettings(cell, data));
      if (rows.length) inspectParts.push(dl);
      if (showConversation) inspectParts.push(conversationSection(cell.id, session));
      box.replaceChildren(...inspectParts);
      if (cell.role) loadCellConversation(data.thread_id, cell.id);
    }

    function isActivityCell(cell) {
      if (!cell) return false;
      if (cell.kind === "activity") return true;
      if (cell.kind === "gate" || cell.kind === "start" || cell.kind === "end" || cell.kind === "parallel" || cell.kind === "subgraph") return false;
      if (cell.id === "run_start" || cell.id === "run_end") return false;
      if (String(cell.id).indexOf("gate_") === 0) return false;
      return Boolean(cell.role && cell.role !== "human");
    }

    function toolsLocked(cell, data) {
      if (!isActivityCell(cell)) return true;
      if (!data || !data.thread_id) return false;
      return cell.state !== "pending" && cell.state !== "initial";
    }

    function chosenNodeTools(cell, data) {
      if (data && data.thread_id) {
        const all = (data.values && data.values.node_tools) || {};
        const item = all[cell.id] || {};
        return { skills: item.skills || [], mcp: item.mcp || [] };
      }
      return pendingNodeTools[cell.id] || { skills: [], mcp: [] };
    }

    function loadRunToolCatalog() {
      fetch("/api/config/tools")
        .then((response) => response.json())
        .then((payload) => {
          runToolCatalog = {
            skills: payload.skills || [],
            mcp: payload.mcp || [],
            detail: payload.detail || "",
          };
          if (lastStatus) renderInspect(lastStatus.thread_id ? lastStatus : lastStatus);
        })
        .catch(() => {
          runToolCatalog = { skills: [], mcp: [], detail: "读不到 Skill 和 MCP。" };
        });
    }

    /** 本步骤的 Skill 与 MCP 两栏；目录读取失败和适用说明写入 notes，由上层统一放在各栏下方。 */
    function nodeToolColumns(cell, data, notes) {
      const locked = toolsLocked(cell, data);
      const chosen = chosenNodeTools(cell, data);
      if (runToolCatalog.detail) notes.push({ text: runToolCatalog.detail });
      if (!locked) notes.push({ text: "不添加时，这一步沿用后端已有的 Skill 和 MCP。" });
      return [
        runToolGroup(cell, data, "skills", "Skill", chosen.skills, runToolCatalog.skills, locked),
        runToolGroup(cell, data, "mcp", "MCP", chosen.mcp, runToolCatalog.mcp, locked),
      ];
    }

    function runToolGroup(cell, data, key, title, selected, catalog, locked) {
      const block = document.createElement("div");
      block.className = "tool-group";
      block.setAttribute("aria-label", title);
      const label = document.createElement("p");
      label.className = "section-title";
      label.textContent = title;
      block.appendChild(label);
      const byId = new Map((catalog || []).map((item) => [item.id, item]));
      if (!selected.length && (locked || (!(catalog && catalog.length) && !runToolCatalog.detail))) {
        const empty = document.createElement("p");
        empty.className = "hint-block";
        empty.textContent = locked ? "未添加。" : "后端没有列出 " + title + "。";
        block.appendChild(empty);
      }
      const remaining = (catalog || []).filter((item) => selected.indexOf(item.id) < 0);
      const add = !locked && remaining.length ? skillPickMenu(cell, data, key, selected, remaining) : null;
      if (selected.length) {
        const list = document.createElement("div");
        list.className = "tool-chosen-list" + (locked ? " is-locked" : "");
        selected.forEach((id) => {
          const item = byId.get(id) || { id: id, name: id, scope: "", description: "后端没有列出这项。" };
          list.appendChild(runToolRow(cell, data, key, item, locked));
        });
        if (add) list.lastElementChild.appendChild(add);
        block.appendChild(list);
      } else if (add) {
        block.appendChild(add);
      }
      return block;
    }

    function skillPickMenu(cell, data, key, selected, remaining) {
      const add = document.createElement("div");
      add.className = "tool-add";
      const shell = document.createElement("div");
      shell.className = "skill-pick-shell";
      const wrap = document.createElement("div");
      wrap.className = "skill-pick-wrap";
      wrap.hidden = true;
      const list = document.createElement("ul");
      list.className = "skill-pick-options";
      list.setAttribute("role", "listbox");
      const tip = document.createElement("div");
      tip.className = "skill-pick-tip";
      tip.hidden = true;
      tip.setAttribute("role", "tooltip");
      let hideTimer = 0;
      let docClose = null;
      function closeSkillPick() {
        wrap.hidden = true;
        tip.hidden = true;
        button.setAttribute("aria-expanded", "false");
        if (docClose) {
          document.removeEventListener("pointerdown", docClose, true);
          docClose = null;
        }
      }
      function openSkillPick() {
        wrap.hidden = false;
        button.setAttribute("aria-expanded", "true");
        if (!docClose) {
          docClose = (ev) => {
            if (!shell.contains(ev.target)) closeSkillPick();
          };
          document.addEventListener("pointerdown", docClose, true);
        }
      }
      remaining.forEach((item) => {
        const li = document.createElement("li");
        li.setAttribute("role", "presentation");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "skill-pick-option";
        btn.setAttribute("role", "option");
        btn.textContent = runToolLabel(item);
        btn.addEventListener("mouseenter", () => {
          list.querySelectorAll(".skill-pick-option.is-active").forEach((el) => el.classList.remove("is-active"));
          btn.classList.add("is-active");
          const text = (item.description || "").trim();
          if (!text) {
            tip.hidden = true;
            return;
          }
          tip.textContent = text;
          tip.hidden = false;
          const rowRect = btn.getBoundingClientRect();
          const wrapRect = wrap.getBoundingClientRect();
          tip.style.top = rowRect.bottom - wrapRect.top + 4 + "px";
        });
        btn.addEventListener("mouseleave", () => {
          btn.classList.remove("is-active");
          tip.hidden = true;
        });
        btn.addEventListener("click", () => {
          const next = chosenNodeTools(cell, data);
          next[key] = selected.concat([item.id]);
          saveNodeTools(cell, data, next);
          closeSkillPick();
        });
        li.appendChild(btn);
        list.appendChild(li);
      });
      wrap.append(list, tip);
      const button = document.createElement("wa-button");
      button.setAttribute("appearance", "outlined");
      button.setAttribute("variant", "neutral");
      button.setAttribute("aria-expanded", "false");
      button.setAttribute("aria-haspopup", "listbox");
      button.textContent = "增加";
      button.addEventListener("click", () => {
        if (wrap.hidden) openSkillPick();
        else closeSkillPick();
      });
      shell.addEventListener("mouseenter", () => {
        window.clearTimeout(hideTimer);
      });
      shell.addEventListener("mouseleave", () => {
        hideTimer = window.setTimeout(closeSkillPick, 140);
      });
      shell.append(button, wrap);
      add.appendChild(shell);
      return add;
    }

    function runToolLabel(item) {
      const where = item.scope === "project" ? "项目" : item.scope === "user" ? "用户" : "";
      return where ? item.name + "（" + where + "）" : item.name;
    }

    function runToolRow(cell, data, key, item, locked) {
      const row = document.createElement("div");
      row.className = "tool-chosen";
      const text = document.createElement("div");
      text.className = "tool-chosen-text";
      text.textContent = runToolLabel(item);
      text.title = item.description ? runToolLabel(item) + "\n" + item.description : runToolLabel(item);
      row.appendChild(text);
      if (!locked) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "tool-remove";
        remove.setAttribute("aria-label", "删除");
        remove.title = "删除「" + runToolLabel(item) + "」";
        remove.innerHTML = TRASH_ICON;
        remove.addEventListener("click", () => {
          const next = chosenNodeTools(cell, data);
          next[key] = (next[key] || []).filter((id) => id !== item.id);
          saveNodeTools(cell, data, next);
        });
        row.appendChild(remove);
      }
      return row;
    }

    function saveNodeTools(cell, data, choice) {
      const skills = (choice.skills || []).slice();
      const mcp = (choice.mcp || []).slice();
      const tid = data && data.thread_id;
      if (!tid) {
        if (skills.length || mcp.length) pendingNodeTools[cell.id] = { skills: skills, mcp: mcp };
        else delete pendingNodeTools[cell.id];
        renderInspect(lastStatus);
        return;
      }
      fetch("/api/runs/" + encodeURIComponent(tid) + "/nodes/" + encodeURIComponent(cell.id) + "/tools", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skills: skills, mcp: mcp }),
      }).then((response) => response.json().then((payload) => ({ ok: response.ok, payload: payload })))
        .then((result) => {
          if (!result.ok) return;
          lastStatus = result.payload;
          renderInspect(lastStatus);
        });
    }

    function escapeHtml(text) {
      return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }

    function inlineMarkdown(text) {
      let html = escapeHtml(text);
      html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
      html = html.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, href) => {
        if (/["'<>]/.test(href) || href.startsWith("//")) return match;
        if (!/^(https?:\/\/|[^:]*$)/.test(href)) return match;
        return '<a href="' + href + '">' + label + "</a>";
      });
      html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      return html;
    }

    function renderMarkdown(src) {
      const lines = String(src || "").replace(/\r\n/g, "\n").split("\n");
      const blocks = [];
      let i = 0;
      const isFence = (line) => line.startsWith("```");
      const isHeading = (line) => /^#{1,3}\s/.test(line);
      const isBullet = (line) => /^[-*]\s/.test(line);
      const isNumber = (line) => /^\d+\.\s/.test(line);
      const isTable = (index) => /^\s*\|/.test(lines[index] || "") && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1] || "");
      while (i < lines.length) {
        if (isFence(lines[i])) {
          const buf = [];
          i += 1;
          while (i < lines.length && !isFence(lines[i])) {
            buf.push(lines[i]);
            i += 1;
          }
          if (i < lines.length) i += 1;
          blocks.push("<pre class=\"artifact-code\"><code>" + escapeHtml(buf.join("\n")) + "</code></pre>");
          continue;
        }
        if (isTable(i)) {
          const header = lines[i].split("|").slice(1, -1).map((cell) => cell.trim());
          i += 2;
          const body = [];
          while (i < lines.length && /^\s*\|/.test(lines[i])) {
            body.push(lines[i].split("|").slice(1, -1).map((cell) => cell.trim()));
            i += 1;
          }
          let table = "<div class=\"artifact-table\"><table><thead><tr>";
          header.forEach((cell) => { table += "<th>" + inlineMarkdown(cell) + "</th>"; });
          table += "</tr></thead><tbody>";
          body.forEach((row) => {
            table += "<tr>";
            row.forEach((cell) => { table += "<td>" + inlineMarkdown(cell) + "</td>"; });
            table += "</tr>";
          });
          table += "</tbody></table></div>";
          blocks.push(table);
          continue;
        }
        if (isHeading(lines[i])) {
          const level = Math.min(lines[i].match(/^#+/)[0].length + 2, 5);
          const text = lines[i].replace(/^#{1,3}\s+/, "");
          blocks.push("<h" + level + ">" + inlineMarkdown(text) + "</h" + level + ">");
          i += 1;
          continue;
        }
        if (isBullet(lines[i])) {
          const items = [];
          while (i < lines.length && isBullet(lines[i])) {
            items.push("<li>" + inlineMarkdown(lines[i].replace(/^[-*]\s+/, "")) + "</li>");
            i += 1;
          }
          blocks.push("<ul>" + items.join("") + "</ul>");
          continue;
        }
        if (isNumber(lines[i])) {
          const items = [];
          while (i < lines.length && isNumber(lines[i])) {
            items.push("<li>" + inlineMarkdown(lines[i].replace(/^\d+\.\s+/, "")) + "</li>");
            i += 1;
          }
          blocks.push("<ol>" + items.join("") + "</ol>");
          continue;
        }
        if (!lines[i].trim() || /^---+$/.test(lines[i].trim())) {
          i += 1;
          continue;
        }
        const para = [];
        while (
          i < lines.length &&
          lines[i].trim() &&
          !isFence(lines[i]) &&
          !isHeading(lines[i]) &&
          !isBullet(lines[i]) &&
          !isNumber(lines[i]) &&
          !isTable(i)
        ) {
          para.push(lines[i]);
          i += 1;
        }
        blocks.push("<p>" + inlineMarkdown(para.join(" ")) + "</p>");
      }
      return blocks.join("");
    }

    const conversations = {};

    function conversationTurnInFlight(turn) {
      if (!turn || !turn.events || !turn.events.length) return true;
      return !turn.events.some((event) => event.kind === "result");
    }

    function shortPath(value) {
      const text = String(value || "").trim();
      if (!text) return "";
      const parts = text.split("/").filter(Boolean);
      return parts.length > 2 ? parts.slice(-2).join("/") : text;
    }

    function oneLine(value, limit) {
      const text = String(value || "").replace(/\s+/g, " ").trim();
      return text.length > limit ? text.slice(0, limit - 1) + "…" : text;
    }

    function toolSummary(name, args, failed) {
      const a = args && typeof args === "object" ? args : {};
      const where = shortPath(a.path || a.targetDirectory || a.cwd || a.workingDirectory || "");
      let verb = "";
      let target = "";
      switch (name) {
        case "read": verb = "读取"; target = shortPath(a.path); break;
        case "edit":
        case "write": verb = "编辑"; target = shortPath(a.path); break;
        case "delete": verb = "删除"; target = shortPath(a.path); break;
        case "shell":
        case "commandExecution": verb = "执行"; target = oneLine(a.command, 80); break;
        case "glob": verb = "查找文件"; target = [a.globPattern, where].filter(Boolean).join(" · "); break;
        case "grep": verb = "搜索"; target = [oneLine(a.pattern, 60), where || a.glob].filter(Boolean).join(" · "); break;
        case "ls": verb = "列出目录"; target = where; break;
        case "updateTodos":
        case "todoList":
        case "plan": verb = "更新待办"; target = Array.isArray(a.todos) ? a.todos.length + " 项" : ""; break;
        case "webSearch": verb = "搜索网页"; target = oneLine(a.query, 60); break;
        case "webFetch": verb = "读取网页"; target = oneLine(a.url, 80); break;
        default: verb = "调用"; target = String(name || "工具");
      }
      return { verb: verb, target: target, failed: !!failed };
    }

    function stepText(message) {
      if (typeof message === "string") return message;
      if (message && typeof message.text === "string") return message.text;
      return "";
    }

    function codexItemStep(item) {
      const type = String(item.type || "");
      if (type === "reasoning") {
        const parts = [].concat(item.summary || [], item.content || []);
        const text = parts.map((p) => (typeof p === "string" ? p : (p && p.text) || "")).join("\n").trim();
        return text ? { kind: "thinking", text: text } : null;
      }
      if (type === "agentMessage") {
        return item.phase === "final_answer" || !item.text ? null : { kind: "reply", text: item.text };
      }
      if (type === "commandExecution") {
        const failed = item.status === "failed" || (item.exitCode != null && item.exitCode !== 0);
        return { kind: "tool", tool: toolSummary("commandExecution", item, failed) };
      }
      if (type === "fileChange") {
        const changes = Array.isArray(item.changes) ? item.changes : [];
        const target = changes.length === 1 ? shortPath(changes[0].path) : changes.length + " 个文件";
        return { kind: "tool", tool: { verb: "编辑", target: target, failed: item.status === "failed" } };
      }
      if (type === "mcpToolCall" || type === "dynamicToolCall") {
        const name = [item.server, item.tool].filter(Boolean).join(".");
        return { kind: "tool", tool: { verb: "调用", target: name || "工具", failed: item.status === "failed" } };
      }
      if (type === "webSearch" || type === "todoList" || type === "plan") {
        return { kind: "tool", tool: toolSummary(type, item, false) };
      }
      return null;
    }

    /** 把各后端的原始步骤归一为思考、回复、工具、出错四类；过程事件返回 null。 */
    function conversationStep(step) {
      const type = String((step && step.type) || "");
      const message = step ? step.message : null;
      if (type === "thinkingMessage") {
        const text = stepText(message).trim();
        const ms = message && Number(message.thinking_duration_ms);
        return text ? { kind: "thinking", text: text, ms: Number.isFinite(ms) ? ms : 0 } : null;
      }
      if (type === "assistantMessage") {
        const text = stepText(message).trim();
        return text ? { kind: "reply", text: text } : null;
      }
      if (type === "toolCall") {
        const m = message && typeof message === "object" ? message : {};
        const result = m.result && typeof m.result === "object" ? m.result : {};
        const failed = !!result.status && result.status !== "success";
        return { kind: "tool", tool: toolSummary(String(m.type || ""), m.args, failed) };
      }
      if (type === "item/completed" && message && message.item) return codexItemStep(message.item);
      if (type === "error") return { kind: "error", text: stepText(message) || "调用出错" };
      return null;
    }

    function toolLine(tool) {
      return "<li class=\"conv-tool" + (tool.failed ? " is-failed" : "") + "\"><span class=\"conv-tool-verb\">"
        + escapeHtml(tool.verb) + "</span>"
        + (tool.target ? " <span class=\"conv-tool-target\">" + escapeHtml(tool.target) + "</span>" : "")
        + (tool.failed ? " <span class=\"conv-tool-failed\">失败</span>" : "") + "</li>";
    }

    function attrText(value) {
      return escapeHtml(String(value == null ? "" : value)).replace(/"/g, "&quot;");
    }

    function choiceSignature(group) {
      return ((group && group.choices) || []).map((c) => c.id + "=" + c.label).join("|");
    }

    const DECISION_LABELS = {
      approved: "批准", rejected: "不通过", replied: "已答复", continue: "继续", pause: "暂停", abort: "终止",
    };

    /** 回复里的 A/B/C 选项画成题卡；已答复的题卡只读并标出所选项，待批复时由 syncAskCards 激活。 */
    function askCard(group, picked, answered) {
      const options = (group.choices || []).map((c) => {
        const on = answered && picked === c.id;
        return "<label class=\"conv-ask-option" + (on ? " is-picked" : "") + "\"><input type=\"checkbox\" value=\""
          + attrText(c.id) + "\" disabled" + (on ? " checked" : "") + "><span class=\"conv-ask-id\">"
          + escapeHtml(String(c.id)) + "</span><span class=\"conv-ask-label\">" + inlineMarkdown(String(c.label || ""))
          + "</span>" + (c.recommended ? "<span class=\"conv-ask-tag\">推荐</span>" : "") + "</label>";
      }).join("");
      const hint = answered
        ? (picked ? "" : "<p class=\"conv-ask-hint\">未选择选项</p>")
        : "<p class=\"conv-ask-hint\" hidden>选中后写入附言，随下方批复一并提交。</p>";
      return "<div class=\"conv-ask" + (answered ? " is-answered" : "") + "\" data-signature=\""
        + attrText(group.signature || choiceSignature(group)) + "\"" + (answered ? " data-answered=\"1\"" : "") + ">"
        + (group.prompt ? "<p class=\"conv-ask-prompt\">" + inlineMarkdown(String(group.prompt)) + "</p>" : "")
        + "<div class=\"conv-ask-options\" role=\"group\">" + options + "</div>" + hint + "</div>";
    }

    function humanReply(event) {
      const who = String(event.actor || "").trim();
      const head = ["人工答复" + (who ? "（" + who + "）" : ""), DECISION_LABELS[event.decision] || "",
        event.channel === "feishu" ? "飞书" : ""].filter(Boolean).join(" · ");
      const reply = String(event.reply || "").trim();
      return "<div class=\"conv-human\"><p class=\"conv-human-head\">" + escapeHtml(head) + "</p>"
        + (reply ? "<p class=\"conv-human-text\">" + escapeHtml(reply) + "</p>" : "") + "</div>";
    }

    function formatConversation(payload, options) {
      const turns = (payload && payload.turns) || [];
      const live = !!(options && options.live);
      if (!turns.length) {
        return live
          ? "<p class=\"conv-live-status\"><span class=\"conv-live-dot\" aria-hidden=\"true\"></span>思考中…</p>"
          : "";
      }
      return turns.map((turn, turnIndex) => {
        const turnLive = live && turnIndex === turns.length - 1 && conversationTurnInFlight(turn);
        const events = turn.events || [];
        const results = new Set(events.filter((e) => e.kind === "result").map((e) => String(e.text || "").trim()));
        const seq = String(turn.seq);
        const open = turnLive || turnIndex === turns.length - 1;
        let html = "<details class=\"conv-turn\" data-key=\"turn-" + escapeHtml(seq) + "\"" + (open ? " open" : "")
          + "><summary><h4>第 " + escapeHtml(seq) + " 次</h4></summary>";
        let work = null;
        let workIndex = 0;
        const workBody = () => {
          let out = "";
          let tools = [];
          const flushTools = () => {
            if (tools.length) out += "<ul class=\"conv-tools\">" + tools.map(toolLine).join("") + "</ul>";
            tools = [];
          };
          for (const item of work.items) {
            if (item.tool) {
              tools.push(item.tool);
            } else {
              flushTools();
              out += "<div class=\"conv-thinking\">" + renderMarkdown(item.text) + "</div>";
            }
          }
          flushTools();
          return out;
        };
        const flushWork = (last) => {
          if (!work) return;
          if (turnLive && last) {
            html += workBody();
          } else {
            const parts = [];
            if (work.thinking) parts.push("思考" + (work.ms >= 1000 ? " " + Math.round(work.ms / 1000) + " 秒" : ""));
            if (work.tools) parts.push("工具调用 " + work.tools + " 次");
            html += "<details class=\"conv-work\" data-key=\"work-" + escapeHtml(seq) + "-" + workIndex + "\"><summary>"
              + parts.join(" · ") + "</summary>" + workBody() + "</details>";
          }
          work = null;
          workIndex += 1;
        };
        for (const event of events) {
          if (event.kind === "turn") {
            html += "<details data-key=\"prompt-" + escapeHtml(seq) + "\"><summary>提示</summary><pre class=\"artifact-code\"><code>" + escapeHtml(String(event.prompt || "").slice(0, 4000)) + "</code></pre></details>";
            continue;
          }
          if (event.kind === "result") {
            flushWork(false);
            const questions = turn.questions || [];
            const hide = new Set(questions.flatMap((q) => q.hide || []));
            const text = String(event.text || "").split("\n").filter((line) => !hide.has(line.trim())).join("\n");
            html += "<div class=\"artifact-body is-open\">" + renderMarkdown(text) + "</div>";
            const answer = events.find((e) => e.kind === "human");
            questions.forEach((q) => {
              html += askCard(q, answer ? (answer.answers || {})[q.id] || "" : "", !!answer);
            });
            continue;
          }
          if (event.kind === "human") {
            html += humanReply(event);
            continue;
          }
          if (event.kind !== "step") continue;
          const step = conversationStep(event.step);
          if (!step) continue;
          if (step.kind === "thinking" || step.kind === "tool") {
            work = work || { items: [], thinking: 0, tools: 0, ms: 0 };
            if (step.kind === "tool") {
              work.items.push({ tool: step.tool });
              work.tools += 1;
            } else {
              work.items.push({ text: step.text });
              work.thinking += 1;
              work.ms += step.ms || 0;
            }
            continue;
          }
          if (step.kind === "reply" && results.has(step.text)) continue;
          flushWork(false);
          html += step.kind === "error"
            ? "<p class=\"conv-error\">" + escapeHtml(step.text) + "</p>"
            : "<div class=\"conv-reply\">" + renderMarkdown(step.text) + "</div>";
        }
        flushWork(true);
        if (turnLive) {
          html += "<p class=\"conv-live-status\"><span class=\"conv-live-dot\" aria-hidden=\"true\"></span>思考中…</p>";
        }
        return html + "</details>";
      }).join("");
    }

    const conversationOpen = {};

    /** 折叠状态按节点记住；状态刷新或新步骤到达时重绘会话，不打乱人已展开或收起的块。 */
    function fillConversation(body, nodeId, html) {
      body.innerHTML = html;
      const saved = conversationOpen[nodeId] || {};
      body.querySelectorAll("details[data-key]").forEach((d) => {
        if (Object.prototype.hasOwnProperty.call(saved, d.dataset.key)) d.open = saved[d.dataset.key];
      });
      syncAskCards(body);
      if (body.dataset.trackOpen) return;
      body.dataset.trackOpen = "1";
      body.addEventListener("change", (ev) => {
        const box = ev.target;
        const card = box instanceof HTMLInputElement ? box.closest(".conv-ask") : null;
        if (card) pickChoice(card.dataset.signature, box.value, box.checked);
      });
      body.addEventListener("toggle", (ev) => {
        const d = ev.target;
        if (!(d instanceof HTMLDetailsElement) || !d.dataset.key) return;
        (conversationOpen[nodeId] = conversationOpen[nodeId] || {})[d.dataset.key] = d.open;
      }, true);
    }

    /** 题卡与人工待办里同一组选项对应时可点选，选中项两处同步。 */
    function syncAskCards(root) {
      root.querySelectorAll(".conv-ask:not([data-answered])").forEach((card) => {
        const group = choiceSurveyGroups.find((g) => choiceSignature(g) === card.dataset.signature);
        const picked = group ? choiceSurveyAnswers[group.id] : null;
        card.classList.toggle("is-pending", !!group);
        card.querySelectorAll("input[type=checkbox]").forEach((box) => {
          box.disabled = !group;
          box.checked = !!(picked && picked.id === box.value);
          box.closest(".conv-ask-option").classList.toggle("is-picked", box.checked);
        });
        const hint = card.querySelector(".conv-ask-hint");
        if (hint) hint.hidden = !group;
      });
    }

    function conversationSection(nodeId, html) {
      const section = document.createElement("section");
      section.className = "inspect-block";
      section.dataset.node = nodeId;
      section.setAttribute("aria-label", "会话");
      const body = document.createElement("div");
      body.className = "conversation-body";
      fillConversation(body, nodeId, html);
      section.append(body);
      return section;
    }

    function rememberConversation(payload) {
      if (payload && payload.node) conversations[payload.node] = payload;
    }

    async function loadCellConversation(tid, nodeId) {
      try {
        const r = await fetch("/api/runs/" + encodeURIComponent(tid) + "/conversations/" + encodeURIComponent(nodeId));
        if (!r.ok) return;
        const payload = await r.json();
        rememberConversation(payload);
        const section = document.querySelector('.inspect-block[data-node="' + nodeId + '"] .conversation-body');
        if (section) {
          fillConversation(section, nodeId, formatConversation(payload));
        } else if ((payload.turns || []).length && lastStatus) {
          renderInspect(lastStatus);
        }
      } catch (_) { /* 会话读不到时保留上一帧 */ }
    }

    function shouldFollowRailPhase(phase) {
      return phase === "running" || phase === "paused" || phase === "interrupted";
    }

    function applyStatus(data) {
      const prevCurrent = lastRailCurrent;
      const nextCurrent = (data && data.rail && data.rail.current) || "";
      const phase = data && data.phase;
      const railMoved = nextCurrent && nextCurrent !== prevCurrent;
      if (shouldFollowRailPhase(phase) && railMoved) {
        setNodeParam("");
      }
      lastRailCurrent = nextCurrent;
      const key = JSON.stringify({
        phase: data && data.phase,
        rail: data && data.rail,
        awaiting: data && data.awaiting_human,
      });
      const same = key === statusKey && data && data.thread_id;
      statusKey = key;
      lastStatus = data;
      renderRail(data && data.rail);
      if (!same || railMoved) renderInspect(data);
    }

    async function loadIdleRail() {
      const project = String($("project").value || "").trim();
      const q = new URLSearchParams();
      if (project) q.set("project_id", project);
      const r = await fetch("/api/rail?" + q.toString());
      if (!r.ok) return;
      const rail = await r.json();
      lastStatus = { rail };
      renderRail(rail);
      renderInspect(lastStatus);
    }

    async function syncRunScenarioHint() {
      const el = $("runScenarioHint");
      const pid = String($("project").value || "").trim();
      if (!pid) {
        el.textContent = "命名默认是项目标识加递增序号，可改。";
        return;
      }
      try {
        const r = await fetch("/api/config/projects/" + encodeURIComponent(pid) + "/form");
        const data = await r.json();
        const key = String((data && data.scenario_key) || "").trim();
        el.textContent = key
          ? "项目类型：" + key + "。"
          : "该项目尚未设置项目类型。请先到项目配置里设置。";
      } catch (_) {
        el.textContent = "项目类型在项目配置里设置，本轮沿用所选项目。";
      }
    }

    function appendReplySnippet(text) {
      const area = $("reply");
      if (!area) return;
      const chunk = String(text || "").trim();
      if (!chunk) return;
      const base = String(area.value || "").trim();
      area.value = base ? base + "\n\n" + chunk + "\n" : chunk + "\n";
      area.focus();
    }

    let choiceSurveyStep = 0;
    let choiceSurveyAnswers = {};
    let choiceSurveyGroups = [];

    function choiceReplyLine(choice) {
      const id = String((choice && choice.id) || "").trim();
      const label = String((choice && choice.label) || "").trim();
      if (!id) return label;
      if (choice && choice.recommended) return "选择 " + id + "（推荐）：" + label;
      return "选择 " + id + "：" + label;
    }

    /** 每组选项在附言里只占一行「选择 X：…」，改选时原位替换。 */
    function writeChoiceReply(group, choice) {
      const area = $("reply");
      if (!area) return;
      const own = new Set((group.choices || []).map(choiceReplyLine));
      const lines = String(area.value || "").split("\n");
      const at = lines.findIndex((line) => own.has(line.trim()));
      const kept = lines.filter((line) => !own.has(line.trim()));
      while (kept.length && !kept[kept.length - 1].trim()) kept.pop();
      if (choice) kept.splice(at >= 0 && at <= kept.length ? at : kept.length, 0, choiceReplyLine(choice));
      area.value = kept.length ? kept.join("\n") + "\n" : "";
    }

    function pickChoice(signature, id, on) {
      const group = choiceSurveyGroups.find((g) => choiceSignature(g) === signature);
      if (!group) return;
      const choice = on ? (group.choices || []).find((c) => c.id === id) : null;
      if (choice) choiceSurveyAnswers[group.id] = choice;
      else delete choiceSurveyAnswers[group.id];
      writeChoiceReply(group, choice);
      renderChoiceSurvey(choiceSurveyGroups);
    }

    function choiceGroupsFromStatus(data) {
      const groups = (data && data.choice_groups) || [];
      if (groups.length) return groups;
      const flat = (data && data.choices) || [];
      if (flat.length < 2) return [];
      return [{ id: "q1", prompt: "", choices: flat }];
    }

    function renderChoiceSurvey(groups) {
      const box = $("hitlChoiceActions");
      if (!box) return;
      box.replaceChildren();
      choiceSurveyGroups = groups || [];
      syncAskCards(document);
      if (!choiceSurveyGroups.length) {
        box.hidden = true;
        choiceSurveyStep = 0;
        choiceSurveyAnswers = {};
        return;
      }
      if (choiceSurveyStep >= choiceSurveyGroups.length) choiceSurveyStep = 0;
      box.hidden = false;
      const head = document.createElement("p");
      head.className = "section-title";
      head.textContent =
        "请择一（" + (choiceSurveyStep + 1) + "/" + choiceSurveyGroups.length + "）";
      box.appendChild(head);
      for (let index = 0; index < choiceSurveyStep; index += 1) {
        const group = choiceSurveyGroups[index];
        const answer = choiceSurveyAnswers[group.id];
        if (!answer) continue;
        const done = document.createElement("p");
        done.className = "choice-survey-done";
        const caption = String(group.prompt || "").trim() || "问题 " + (index + 1);
        done.textContent = caption + " → " + choiceReplyLine(answer);
        box.appendChild(done);
      }
      const group = choiceSurveyGroups[choiceSurveyStep];
      const promptText = String(group.prompt || "").trim();
      if (promptText) {
        const prompt = document.createElement("p");
        prompt.className = "choice-survey-prompt";
        prompt.textContent = promptText;
        box.appendChild(prompt);
      }
      const grid = document.createElement("div");
      grid.className = "choice-grid hitl-choice-grid";
      grid.setAttribute("role", "radiogroup");
      const picked = choiceSurveyAnswers[group.id];
      (group.choices || []).forEach((choice) => {
        const cb = document.createElement("wa-checkbox");
        const id = String(choice.id || "").trim();
        const label = String(choice.label || "").trim();
        const prefix = choice.recommended ? id + "（推荐）" : id;
        cb.textContent = prefix + "：" + label;
        cb.checked = !!(picked && picked.id === choice.id);
        cb.addEventListener("change", () => pickChoice(choiceSignature(group), choice.id, cb.checked));
        grid.appendChild(cb);
      });
      box.appendChild(grid);
      const nav = document.createElement("div");
      nav.className = "row-actions choice-survey-nav";
      if (choiceSurveyStep > 0) {
        const back = document.createElement("wa-button");
        back.appearance = "outlined";
        back.variant = "neutral";
        back.textContent = "上一题";
        back.addEventListener("click", () => {
          choiceSurveyStep -= 1;
          renderChoiceSurvey(choiceSurveyGroups);
        });
        nav.appendChild(back);
      }
      if (choiceSurveyStep < choiceSurveyGroups.length - 1) {
        const next = document.createElement("wa-button");
        next.variant = "brand";
        next.textContent = "下一题";
        next.disabled = !choiceSurveyAnswers[group.id];
        next.addEventListener("click", () => {
          choiceSurveyStep += 1;
          renderChoiceSurvey(choiceSurveyGroups);
        });
        nav.appendChild(next);
      }
      if (nav.childElementCount) box.appendChild(nav);
    }

    function renderClarifyActions(questions) {
      const box = $("hitlClarifyActions");
      if (!box) return;
      box.replaceChildren();
      if (!questions || !questions.length) {
        box.hidden = true;
        return;
      }
      box.hidden = false;
      const title = document.createElement("p");
      title.className = "section-title";
      title.textContent = "待澄清";
      box.appendChild(title);
      const list = document.createElement("ul");
      list.className = "question-list question-actions";
      questions.forEach((question, index) => {
        const li = document.createElement("li");
        const text = document.createElement("span");
        text.className = "question-text";
        text.textContent = (index + 1) + ". " + question;
        const use = document.createElement("button");
        use.type = "button";
        use.className = "question-use";
        use.textContent = "填入附言";
        use.addEventListener("click", () => {
          appendReplySnippet((index + 1) + ". " + question);
        });
        li.append(text, use);
        list.appendChild(li);
      });
      box.appendChild(list);
    }

    function renderReading(sections) {
      const box = $("hitlReading");
      box.replaceChildren();
      if (!sections || !sections.length) {
        box.hidden = true;
        return;
      }
      box.hidden = false;
      for (const section of sections) {
        if (section.title === "待澄清") continue;
        const heading = document.createElement("h4");
        heading.textContent = section.title;
        const body = document.createElement("p");
        body.textContent = section.body;
        box.append(heading, body);
      }
      if (!box.childElementCount) box.hidden = true;
    }

    function syncAgentLiveBanner(data) {
      const el = $("hitlAgentStatus");
      if (!el) return;
      const phase = data && data.phase;
      if (data && data.awaiting_human) {
        el.hidden = true;
        el.textContent = "";
        return;
      }
      if (phase === "running") {
        const cell = currentCell(data.rail);
        el.hidden = false;
        el.className = "hitl-agent-live is-busy";
        el.textContent = cell && cell.label ? "正在执行：" + cell.label + "…" : "流程推进中…";
        return;
      }
      el.hidden = true;
      el.className = "hitl-agent-live";
      el.textContent = "";
    }

    function escapeHtml(s) {
      return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function applyHitlFormMode(ah) {
      awaitingKind = ah ? ah.kind : null;
      const qList = $("questionList");
      $("fieldGateDecision").hidden = !ah || ah.kind !== "gate";
      $("fieldEscalation").hidden = !ah || ah.kind !== "escalation";
      if (ah && ah.kind === "pm_clarification") {
        $("reply").label = "澄清答复";
        $("reply").hint = "必填";
        $("reply").placeholder = "逐条回答待澄清问题…";
        qList.hidden = true;
        qList.replaceChildren();
        renderClarifyActions(ah.questions || []);
      } else if (ah && ah.kind === "escalation") {
        $("reply").label = "说明";
        $("reply").hint = "可空";
        $("reply").placeholder = "补充决策理由…";
        qList.hidden = true;
        qList.replaceChildren();
        renderClarifyActions([]);
      } else {
        $("reply").label = "附言";
        $("reply").hint = "可空";
        $("reply").placeholder = "补充范围说明或驳回原因…";
        qList.hidden = true;
        qList.replaceChildren();
        renderClarifyActions([]);
      }
    }

    function syncHumanChoices(data) {
      const ah = data && data.awaiting_human;
      const groups = choiceGroupsFromStatus(data);
      if (!groups.length) {
        choiceSurveyStep = 0;
        choiceSurveyAnswers = {};
      } else if (JSON.stringify(groups) !== JSON.stringify(choiceSurveyGroups)) {
        choiceSurveyStep = 0;
        choiceSurveyAnswers = {};
      }
      renderChoiceSurvey(groups);
      if (ah && ah.kind === "pm_clarification") {
        renderClarifyActions(ah.questions || []);
      } else if (!ah) {
        renderClarifyActions([]);
        renderChoiceSurvey([]);
      }
    }

    function roundIsOpen(phase) {
      return phase === "running" || phase === "awaiting_human" || phase === "paused" || startInFlight;
    }

    function syncStartButton(phase) {
      const btn = $("btnStart");
      const open = roundIsOpen(phase);
      btn.disabled = open;
      btn.loading = false;
      btn.textContent = open ? "进行中" : "启动";
      const save = $("btnSaveRun");
      if (save) {
        save.hidden = !!$("thread").value.trim();
        save.disabled = startInFlight;
      }
    }

    function syncPauseButton(phase) {
      const btn = $("btnPause");
      const note = $("pauseNote");
      const pausing = phase === "running" && !!(lastStatus && lastStatus.pause_requested);
      if (phase === "paused") {
        btn.hidden = false;
        btn.disabled = false;
        btn.loading = false;
        btn.textContent = "继续";
        note.hidden = false;
        return;
      }
      const show = phase === "running" || startInFlight;
      btn.hidden = !show;
      btn.disabled = !show || pausing;
      btn.loading = pausing;
      btn.textContent = pausing ? "正在暂停" : "暂停";
      note.hidden = true;
    }

    function syncContinueButton(phase) {
      const btn = $("btnContinueRun");
      const note = $("interruptHint");
      const show = phase === "interrupted";
      btn.hidden = !show;
      btn.disabled = !show;
      btn.loading = false;
      note.hidden = !show;
    }

    function syncStopButton(phase) {
      const btn = $("btnStop");
      const open = roundIsOpen(phase);
      const show = open || phase === "interrupted";
      const stopping = show && !!(lastStatus && lastStatus.stop_requested);
      btn.hidden = !show;
      btn.disabled = !show || stopping;
      btn.textContent = stopping ? "正在停止" : "停止";
      syncPauseButton(phase);
      syncContinueButton(phase);
    }

    let pushSource = null;
    let pushThread = "";
    let startPollTimer = null;

    function stopStartPoll() {
      if (startPollTimer) {
        clearInterval(startPollTimer);
        startPollTimer = null;
      }
    }

    function armStartPoll() {
      stopStartPoll();
      if (!startInFlight) return;
      startPollTimer = setInterval(() => {
        if (!startInFlight) {
          stopStartPoll();
          return;
        }
        void refresh({ quiet: true });
      }, 1200);
    }

    function ingestStatus(data) {
      showError($("startError"), "");
      applyStatus(data);
      applyBoundRunName(data);
      syncThreadChrome($("thread").value.trim(), data.values && data.values.run_name);
      syncStartButton(data.phase);
      syncStopButton(data.phase);
      const ah = data.awaiting_human;
      $("btnSubmit").disabled = data.phase !== "awaiting_human";
      syncAgentLiveBanner(data);
      if (ah) {
        $("banner").hidden = false;
        $("gateIdleHint").hidden = true;
        $("bannerText").textContent = ah.summary || "等待人工处理";
        const current = data.rail && data.rail.cells.find((cell) => cell.id === data.rail.current);
        $("bannerGate").textContent = current ? current.label : "";
        applyHitlFormMode(ah);
        renderReading(data.reading);
        syncHumanChoices(data);
      } else {
        $("banner").hidden = true;
        $("gateIdleHint").hidden = data.phase === "awaiting_human";
        if (data.phase === "completed") {
          $("gateIdleHint").hidden = false;
          $("gateIdleHint").textContent = "本轮已结束，右侧为最后一步的会话。";
        } else if (data.phase === "rejected") {
          $("gateIdleHint").hidden = false;
          $("gateIdleHint").textContent = "本轮已驳回。";
        } else if (data.phase === "stopped") {
          $("gateIdleHint").hidden = false;
          $("gateIdleHint").textContent = "本轮已停止。";
        } else {
          $("gateIdleHint").textContent = "暂无待办；需批复或澄清时表单会出现在此。";
        }
        applyHitlFormMode(null);
        renderReading([]);
        syncHumanChoices(null);
      }
      armPoll(data.phase);
      loadRunList();
      syncRunBoardLayout();
    }

    function armPoll(phase) {
      const tid = $("thread").value.trim();
      const live = (phase === "running" || phase === "awaiting_human") && !document.hidden && !!tid;
      if (!live) {
        stopPoll();
        return;
      }
      if (pushSource && pushThread === tid) return;
      stopPoll();
      if (typeof EventSource !== "function") {
        pollTimer = setInterval(() => { refresh({ quiet: true }); }, 2000);
        return;
      }
      pushThread = tid;
      pushSource = new EventSource("/api/runs/" + encodeURIComponent(tid) + "/events");
      pushSource.addEventListener("status", (ev) => {
        try { ingestStatus(JSON.parse(ev.data)); } catch (_) { /* 忽略坏帧 */ }
      });
      pushSource.addEventListener("conversation", (ev) => {
        try {
          rememberConversation(JSON.parse(ev.data));
          if (lastStatus) renderInspect(lastStatus);
        } catch (_) { /* 忽略坏帧 */ }
      });
      pushSource.addEventListener("end", () => { stopPoll(); });
      pushSource.onerror = () => { stopPoll(); };
    }

    async function refresh(opts) {
      if (refreshing) return;
      refreshing = true;
      const quiet = !!(opts && opts.quiet);
      const tid = $("thread").value.trim();
      showError($("hitlError"), "");
      if (!tid) {
        stopPoll();
        lastRailCurrent = "";
        renderInspect(null);
        syncThreadChrome("");
        applyBoundRunName(null);
        $("btnSubmit").disabled = true;
        $("banner").hidden = true;
        $("gateIdleHint").hidden = false;
        syncStartButton("idle");
        syncStopButton("idle");
        await loadIdleRail();
        await loadRunList();
        refreshing = false;
        return;
      }
      syncThreadChrome(tid, lastStatus && lastStatus.values && lastStatus.values.run_name);
      if (!quiet) setLoading($("btnRefresh"), true);
      try {
        const r = await fetch("/api/runs/" + encodeURIComponent(tid));
        const { ok, status, data } = await readFetchResponse(r);
        if (!ok) {
          if (startInFlight && (status === 404 || status === 503)) {
            return;
          }
          showError(
            $("startError"),
            status === 404
              ? "没有这一轮。核对地址栏中的 thread_id。"
              : apiErrorMessage(data, "读不到这一轮的状态。检查服务是否还在，然后刷新。")
          );
          if (startInFlight) {
            syncStartButton("running");
            syncStopButton("running");
            return;
          }
          syncStartButton(status === 404 ? "idle" : (lastStatus && lastStatus.phase));
          syncStopButton(status === 404 ? "idle" : (lastStatus && lastStatus.phase));
          return;
        }
        showError($("startError"), "");
        const models = (data.values && data.values.role_models) || {};
        pendingRoleModels = models;
        pendingRoleReasoningEfforts = (data.values && data.values.role_reasoning_efforts) || {};
        ingestStatus(data);
        refreshRunRoleModels();
      } catch (err) {
        showError($("startError"), "读不到这一轮的状态。检查服务是否还在，然后刷新。");
      } finally {
        if (!quiet) setLoading($("btnRefresh"), false);
        refreshing = false;
      }
    }

    $("btnStart").onclick = async () => {
      showError($("startError"), "");
      const reasoningError = runReasoningError();
      if (reasoningError) { showError($("startError"), reasoningError); return; }
      const body = {
        human_request: $("req").value.trim(),
        scenario_key: "",
        project_id: String($("project").value || "").trim(),
        run_name: String($("runName").value || "").trim(),
        node_tools: pendingNodeTools,
        attachments: runAttachments.map((item) => ({ id: item.id, name: item.name, size: item.size })),
        role_models: pendingRoleModels,
        role_reasoning_efforts: pendingRoleReasoningEfforts,
      };
      if (!body.project_id) {
        showError($("startError"), "先选择项目。");
        $("project").focus();
        return;
      }
      const projectForm = await fetch("/api/config/projects/" + encodeURIComponent(body.project_id) + "/form").then((r) => r.json());
      const chosen = String((projectForm && projectForm.profile_id) || "").trim();
      const known = await fetch("/api/workflows").then((r) => r.json());
      const workflows = (known && known.workflows) || [];
      if (!chosen || !workflows.some((item) => item.workflow_id === chosen)) {
        showError($("startError"), "这个项目还没有流程。");
        return;
      }
      if (!body.human_request) {
        showError($("startError"), "请先填写交付目标。");
        $("req").focus();
        return;
      }
      const previousThread = $("thread").value.trim();
      const tid = window.crypto && crypto.randomUUID ? crypto.randomUUID() : "";
      if (tid) {
        body.thread_id = tid;
        $("thread").value = tid;
        syncUrlThread(tid);
        syncThreadChrome(tid, String($("runName").value || "").trim());
        focusRunRailView({ smooth: true });
      }
      const btn = $("btnStart");
      startInFlight = true;
      syncStartButton("running");
      syncStopButton("running");
      armStartPoll();
      try {
        const r = await fetch("/api/runs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const parsed = await readFetchResponse(r);
        const { ok, data } = parsed;
        if (!ok) {
          $("thread").value = previousThread;
          syncUrlThread(previousThread);
          syncThreadChrome(previousThread, "");
          if (!previousThread && draftId) syncUrlDraft(draftId);
          showError($("startError"), apiErrorMessage(data, "启动失败，请检查项目类型或项目配置。"));
          syncStartButton(lastStatus && lastStatus.phase);
          syncStopButton(lastStatus && lastStatus.phase);
          return;
        }
        $("thread").value = data.thread_id;
        syncUrlThread(data.thread_id);
        if (draftId) {
          const savedId = draftId;
          const savedName = draftName;
          clearDraftBinding();
          fetch("/api/runs/drafts/" + encodeURIComponent(savedId) + "/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ confirm_name: savedName }),
          }).catch(() => {});
        }
        showRunSaved("");
        noteFeishu(data);
        pendingNodeTools = {};
        clearAttachments();
        roleModelStamp = "";
        ingestStatus(data);
        focusRunRailView({ smooth: true });
        armPoll(data.phase);
        await refresh({ quiet: true });
      } catch (err) {
        if (!$("thread").value.trim() || $("thread").value.trim() === tid) {
          $("thread").value = previousThread;
          syncUrlThread(previousThread);
          syncThreadChrome(previousThread, "");
          if (!previousThread && draftId) syncUrlDraft(draftId);
        }
        showError($("startError"), "启动没有返回。检查服务是否还在，然后重试。");
        syncStartButton(lastStatus && lastStatus.phase);
        syncStopButton(lastStatus && lastStatus.phase);
      } finally {
        startInFlight = false;
        stopStartPoll();
        btn.loading = false;
        syncStartButton((lastStatus && lastStatus.phase) || "idle");
        syncStopButton((lastStatus && lastStatus.phase) || "idle");
      }
    };

    $("btnStop").onclick = async () => {
      const tid = $("thread").value.trim();
      if (!tid) return;
      showError($("startError"), "");
      const btn = $("btnStop");
      btn.disabled = true;
      btn.textContent = "正在停止";
      if (lastStatus) lastStatus.stop_requested = true;
      try {
        const r = await fetch("/api/runs/" + encodeURIComponent(tid) + "/stop", {
          method: "POST",
        });
        const { ok, data } = await readFetchResponse(r);
        if (!ok) {
          if (lastStatus) lastStatus.stop_requested = false;
          showError($("startError"), apiErrorMessage(data, "停不了这一轮。刷新后再看阶段。"));
          syncStopButton((lastStatus && lastStatus.phase) || "running");
          return;
        }
        if (data.stop_requested && data.phase !== "stopped") {
          lastStatus = data;
          syncStartButton(startInFlight ? "running" : data.phase);
          syncStopButton(startInFlight ? "running" : data.phase);
          return;
        }
        if (!startInFlight) await refresh();
      } catch (err) {
        if (lastStatus) lastStatus.stop_requested = false;
        showError($("startError"), "停止没有返回。检查服务是否还在，然后刷新。");
        syncStopButton((lastStatus && lastStatus.phase) || "running");
      }
    };

    $("btnContinueRun").onclick = async () => {
      const tid = $("thread").value.trim();
      if (!tid) return;
      showError($("startError"), "");
      const btn = $("btnContinueRun");
      btn.disabled = true;
      btn.loading = true;
      try {
        const r = await fetch("/api/runs/" + encodeURIComponent(tid) + "/continue", { method: "POST" });
        const { ok, data } = await readFetchResponse(r);
        if (!ok) {
          showError($("startError"), apiErrorMessage(data, "没能续跑。"));
          syncStopButton((lastStatus && lastStatus.phase) || "interrupted");
          return;
        }
        lastStatus = data;
        noteFeishu(data);
        ingestStatus(data);
      } catch (err) {
        showError($("startError"), "续跑没有返回。检查服务是否还在，然后刷新。");
        syncStopButton((lastStatus && lastStatus.phase) || "interrupted");
      }
    };

    $("btnPause").onclick = async () => {
      const tid = $("thread").value.trim();
      if (!tid) return;
      const resume = $("btnPause").textContent === "继续";
      showError($("startError"), "");
      const btn = $("btnPause");
      btn.disabled = true;
      btn.loading = true;
      btn.textContent = resume ? "正在继续" : "正在暂停";
      if (!resume && lastStatus) lastStatus.pause_requested = true;
      try {
        const r = await fetch(
          "/api/runs/" + encodeURIComponent(tid) + (resume ? "/resume" : "/pause"),
          { method: "POST" }
        );
        const { ok, data } = await readFetchResponse(r);
        if (!ok) {
          if (lastStatus) lastStatus.pause_requested = false;
          showError(
            $("startError"),
            apiErrorMessage(data, resume ? "继续不了这一轮。" : "暂停不了这一轮。")
          );
          syncStopButton((lastStatus && lastStatus.phase) || "running");
          return;
        }
        lastStatus = data;
        if (data.pause_requested && data.phase === "running") {
          syncStartButton(data.phase);
          syncStopButton(data.phase);
          return;
        }
        await refresh();
      } catch (err) {
        if (lastStatus) lastStatus.pause_requested = false;
        showError($("startError"), resume ? "继续没有返回。检查服务是否还在。" : "暂停没有返回。检查服务是否还在。");
        syncStopButton((lastStatus && lastStatus.phase) || "running");
      }
    };

    $("btnSubmit").onclick = async () => {
      const tid = $("thread").value.trim();
      if (!tid) return;
      showError($("hitlError"), "");
      const btn = $("btnSubmit");
      setLoading(btn, true);
      try {
        const payload = { human_reply: $("reply").value, channel: "web" };
        if (awaitingKind === "gate") {
          payload.gate_decision = $("decision").value;
        } else if (awaitingKind === "escalation") {
          payload.escalation_choice = $("escalationChoice").value;
        }
        const r = await fetch("/api/runs/" + encodeURIComponent(tid) + "/hitl", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const { ok, data } = await readFetchResponse(r);
        if (!ok) {
          showError($("hitlError"), apiErrorMessage(data, "提交失败，当前可能不在等待人工状态。"));
          return;
        }
        $("reply").value = "";
        noteFeishu(data);
        await refresh();
      } finally {
        setLoading(btn, false);
      }
    };

    $("btnRefresh").onclick = refresh;

    $("btnAttach").addEventListener("click", () => $("attachInput").click());
    $("attachInput").addEventListener("change", () => {
      uploadAttachmentFiles($("attachInput").files);
      $("attachInput").value = "";
    });
    const promptBox = $("promptBox");
    if (promptBox) {
      ["dragenter", "dragover"].forEach((name) => {
        promptBox.addEventListener(name, (event) => {
          event.preventDefault();
          promptBox.classList.add("is-dropping");
        });
      });
      ["dragleave", "drop"].forEach((name) => {
        promptBox.addEventListener(name, (event) => {
          event.preventDefault();
          promptBox.classList.remove("is-dropping");
        });
      });
      promptBox.addEventListener("drop", (event) => {
        uploadAttachmentFiles(event.dataTransfer && event.dataTransfer.files);
      });
    }

    $("btnSaveRun").onclick = async () => {
      showError($("startError"), "");
      showRunSaved("");
      const projectId = String($("project").value || "").trim();
      if (!projectId) {
        showError($("startError"), "先选择项目。");
        $("project").focus();
        return;
      }
      const reasoningError = runReasoningError();
      if (reasoningError) { showError($("startError"), reasoningError); return; }
      const btn = $("btnSaveRun");
      setLoading(btn, true);
      try {
        const r = await fetch("/api/runs/drafts", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            draft_id: draftId,
            project_id: projectId,
            run_name: String($("runName").value || "").trim(),
            human_request: $("req").value.trim(),
            node_tools: pendingNodeTools,
            attachments: runAttachments.map((item) => ({ id: item.id, name: item.name, size: item.size })),
            role_models: pendingRoleModels,
        role_reasoning_efforts: pendingRoleReasoningEfforts,
          }),
        });
        const { ok, data } = await readFetchResponse(r);
        if (!ok) {
          showError($("startError"), apiErrorMessage(data, "没有保存。"));
          return;
        }
        draftId = data.draft_id;
        draftName = data.run_name || "";
        loadedDraftProject = String(data.project_id || projectId);
        runNameTouched = true;
        if (data.run_name) $("runName").value = data.run_name;
        pendingNodeTools = data.node_tools || {};
        pendingRoleModels = data.role_models || pendingRoleModels;
        pendingRoleReasoningEfforts = data.role_reasoning_efforts || pendingRoleReasoningEfforts;
        roleModelStamp = "";
        if (data.attachments) {
          runAttachments = data.attachments.map((item) => ({
            id: item.id,
            name: item.name,
            size: item.size,
          }));
          renderAttachments();
        }
        syncUrlDraft(draftId);
        setPhase("saved");
        showRunSaved("已保存 " + (data.run_name || "") + "，尚未启动。");
        await loadRunList();
      } catch (_) {
        showError($("startError"), "保存没有返回。检查服务是否还在，然后重试。");
      } finally {
        setLoading(btn, false);
        syncStartButton(draftId ? "saved" : "idle");
      }
    };

    $("btnSidebarNew").addEventListener("click", (event) => {
      event.preventDefault();
      const here = document.documentElement.dataset.route === "hitl";
      applyRoute("/", "#region-new", {
        historyMode: here && location.hash === "#region-new" ? undefined : "push",
        smooth: true,
      });
      $("thread").value = "";
      clearDraftBinding();
      syncUrlThread("");
      syncUrlDraft("");
      showRunSaved("");
      pendingNodeTools = {};
      pendingRoleModels = {};
      pendingRoleReasoningEfforts = {};
      roleModelStamp = "";
      clearAttachments();
      refreshRunRoleModels();
      syncThreadChrome("");
      stopPoll();
      runNameTouched = false;
      if ($("runName")) $("runName").disabled = false;
      fillRunNameSuggestion();
      loadIdleRail();
      syncStartButton("idle");
      syncStopButton("idle");
      $("req").focus({ preventScroll: true });
    });

    async function loadRunConfigOptions() {
      const pj = $("project");
      if (!pj) return;
      const previous = String(pj.value || "").trim();
      try {
        const pr = await fetch("/api/config/projects").then((r) => r.json());
        pj.replaceChildren();
        const blankProject = document.createElement("wa-option");
        blankProject.value = "";
        blankProject.textContent = "（不指定项目）";
        pj.append(blankProject);
        const items = pr.projects || [];
        for (const p of items) {
          const o = document.createElement("wa-option");
          o.value = p.project_id;
          const title = (p.title || p.project_id || "").trim();
          o.textContent = title === p.project_id ? p.project_id : title + " (" + p.project_id + ")";
          pj.appendChild(o);
        }
        const fromUrl = new URLSearchParams(location.search).get("project") || "";
        const pick =
          (fromUrl && items.some((p) => p.project_id === fromUrl) && fromUrl) ||
          (previous && items.some((p) => p.project_id === previous) && previous) ||
          "";
        pj.value = pick;
        const emptyHint = $("runProjectEmpty");
        if (emptyHint) emptyHint.hidden = items.length > 0;
        if (pick) syncRunScenarioHint();
      } catch (_) { /* 离线或未启动 API */ }
    }
    window.loadRunConfigOptions = loadRunConfigOptions;

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stopPoll();
      else if ($("thread").value.trim()) refresh({ quiet: true });
    });

    if ($("runPhaseFilter")) {
      $("runPhaseFilter").addEventListener("change", () => { loadRunList(); });
    }

    $("project").addEventListener("change", () => {
      void (async () => {
      const next = String($("project").value || "").trim();
      if (ignoreProjectChange || (draftId && next === loadedDraftProject)) {
        syncRunScenarioHint();
        return;
      }
      pendingNodeTools = {};
      pendingRoleModels = {};
      pendingRoleReasoningEfforts = {};
      roleModelStamp = "";
      loadedDraftProject = "";
      syncRunScenarioHint();
      await refreshRunRoleModels();
      if (!$("thread").value.trim()) {
        runNameTouched = false;
        fillRunNameSuggestion();
        loadIdleRail();
      }
      })();
    });
    $("runName").addEventListener("input", () => {
      if (!$("thread").value.trim()) runNameTouched = true;
    });

    (function initFromUrl() {
      loadRunToolCatalog();
      customElements.whenDefined("wa-select")
        .then(() => loadRoleTitles())
        .then(() => loadRunConfigOptions())
        .then(() => (typeof window.syncRunBackendModels === "function" ? window.syncRunBackendModels() : null))
        .then(() => {
        const params = new URLSearchParams(window.location.search);
        const tid = params.get("thread_id") || params.get("thread");
        const draft = params.get("draft") || "";
        if (tid) {
          $("thread").value = tid;
          applyBoundRunName(null);
          syncRunBoardLayout();
          if (params.get("thread") && !params.get("thread_id")) syncUrlThread(tid);
          refresh();
        } else if (draft) {
          openDraft(draft);
        } else {
          loadIdleRail();
          void refreshRunRoleModels();
          loadRunList();
          syncStartButton("idle");
          syncRunBoardLayout();
        }
      });
    })();

    (function initSidebarResize() {
      const handle = $("sidebarResize");
      const sidebar = document.querySelector(".sidebar");
      if (!handle || !sidebar) return;
      const key = "geni_studio_sidebar_w";
      const saved = localStorage.getItem(key);
      if (saved) document.documentElement.style.setProperty("--sidebar-w", saved);

      function widthPx() {
        return sidebar.getBoundingClientRect().width;
      }

      function paneMax() {
        const shell = document.querySelector(".app-shell");
        return shell ? shell.clientWidth : window.innerWidth;
      }

      function applyWidth(px) {
        const next = Math.round(Math.min(Math.max(px, 200), paneMax()));
        document.documentElement.style.setProperty("--sidebar-w", next + "px");
        return next;
      }

      handle.addEventListener("pointerdown", (event) => {
        if (window.innerWidth < 900) return;
        event.preventDefault();
        handle.classList.add("is-dragging");
        try { handle.setPointerCapture(event.pointerId); } catch (_) { /* 非真实指针时仍按移动事件调整 */ }
        const originX = event.clientX;
        const originW = widthPx();
        function move(ev) {
          applyWidth(originW + ev.clientX - originX);
        }
        function end(ev) {
          handle.classList.remove("is-dragging");
          try { handle.releasePointerCapture(ev.pointerId); } catch (_) { /* 未捕获指针 */ }
          localStorage.setItem(key, widthPx() + "px");
          handle.removeEventListener("pointermove", move);
          handle.removeEventListener("pointerup", end);
          handle.removeEventListener("pointercancel", end);
        }
        handle.addEventListener("pointermove", move);
        handle.addEventListener("pointerup", end);
        handle.addEventListener("pointercancel", end);
      });

      handle.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        const delta = event.key === "ArrowRight" ? 16 : -16;
        const next = applyWidth(widthPx() + delta);
        localStorage.setItem(key, next + "px");
      });
    })();

    (function initHitlDockResize() {
      const handle = $("hitlDockResize");
      const dock = $("region-todo");
      if (!handle || !dock) return;
      const key = "geni_studio_hitl_dock_h";
      const saved = localStorage.getItem(key);
      if (saved) document.documentElement.style.setProperty("--hitl-dock-h", saved);

      function applyHeight(px) {
        const shell = handle.closest(".inspect-body-run");
        const max = shell ? Math.max(120, shell.clientHeight - 80) : 480;
        const next = Math.round(Math.min(Math.max(px, 120), max));
        document.documentElement.style.setProperty("--hitl-dock-h", next + "px");
        return next;
      }

      handle.addEventListener("pointerdown", (event) => {
        if (window.innerWidth < 900) return;
        event.preventDefault();
        handle.classList.add("is-dragging");
        try { handle.setPointerCapture(event.pointerId); } catch (_) { /* 非真实指针 */ }
        const originY = event.clientY;
        const originH = dock.getBoundingClientRect().height;
        function move(ev) {
          applyHeight(originH + originY - ev.clientY);
        }
        function end(ev) {
          handle.classList.remove("is-dragging");
          try { handle.releasePointerCapture(ev.pointerId); } catch (_) { /* 未捕获指针 */ }
          localStorage.setItem(key, applyHeight(dock.getBoundingClientRect().height) + "px");
          handle.removeEventListener("pointermove", move);
          handle.removeEventListener("pointerup", end);
          handle.removeEventListener("pointercancel", end);
        }
        handle.addEventListener("pointermove", move);
        handle.addEventListener("pointerup", end);
        handle.addEventListener("pointercancel", end);
      });

      handle.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
        event.preventDefault();
        const delta = event.key === "ArrowUp" ? 16 : -16;
        const next = applyHeight(dock.getBoundingClientRect().height + delta);
        localStorage.setItem(key, next + "px");
      });
    })();

    (function initInspectResize() {
      const handles = document.querySelectorAll(".inspect-resize");
      if (!handles.length) return;
      const key = "geni_studio_inspect_w";
      const saved = localStorage.getItem(key);
      if (saved) document.documentElement.style.setProperty("--inspect-w", saved);

      function paneOf(handle) {
        return handle.closest(".workspace-inspect");
      }

      function paneMax() {
        const shell = document.querySelector(".app-shell");
        return shell ? shell.clientWidth : window.innerWidth;
      }

      function applyWidth(px) {
        const next = Math.round(Math.min(Math.max(px, 220), paneMax()));
        document.documentElement.style.setProperty("--inspect-w", next + "px");
        return next;
      }

      handles.forEach((handle) => {
        handle.addEventListener("pointerdown", (event) => {
          const pane = paneOf(handle);
          if (!pane || window.innerWidth < 900 || getComputedStyle(pane).display === "none") return;
          event.preventDefault();
          handle.classList.add("is-dragging");
          try { handle.setPointerCapture(event.pointerId); } catch (_) { /* 非真实指针时仍按移动事件调整 */ }
          const originX = event.clientX;
          const originW = pane.getBoundingClientRect().width;
          function move(ev) {
            applyWidth(originW + originX - ev.clientX);
          }
          function end(ev) {
            handle.classList.remove("is-dragging");
            try { handle.releasePointerCapture(ev.pointerId); } catch (_) { /* 未捕获指针 */ }
            localStorage.setItem(key, applyWidth(pane.getBoundingClientRect().width) + "px");
            handle.removeEventListener("pointermove", move);
            handle.removeEventListener("pointerup", end);
            handle.removeEventListener("pointercancel", end);
          }
          handle.addEventListener("pointermove", move);
          handle.addEventListener("pointerup", end);
          handle.addEventListener("pointercancel", end);
        });

        handle.addEventListener("keydown", (event) => {
          const pane = paneOf(handle);
          if (!pane || event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
          if (getComputedStyle(pane).display === "none") return;
          event.preventDefault();
          const delta = event.key === "ArrowLeft" ? 16 : -16;
          const next = applyWidth(pane.getBoundingClientRect().width + delta);
          localStorage.setItem(key, next + "px");
        });
      });
    })();

    (function initThemeToggle() {
      const key = "geni_studio_hitl_theme";
      const btn = $("themeToggle");

      function syncToggleLabel() {
        const dark = document.documentElement.getAttribute("data-theme") === "dark";
        btn.textContent = dark ? "白天" : "夜晚";
      }

      btn.addEventListener("click", function () {
        const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        document.documentElement.classList.toggle("wa-dark", next === "dark");
        document.documentElement.classList.toggle("wa-light", next !== "dark");
        localStorage.setItem(key, next);
        syncToggleLabel();
      });

      syncToggleLabel();
    })();

    function scrollBehavior(options) {
      if (!options || !options.smooth) return "auto";
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return "auto";
      return "smooth";
    }

    function routeFromPath(path) {
      if (path === "/config") return "config";
      if (path === "/project") return "project";
      if (path === "/workflow") return "workflow";
      if (path === "/role") return "role";
      if (path === "/help") return "help";
      return "hitl";
    }

    function markRegion(target) {
      document.querySelectorAll(".func-region.is-target").forEach((el) => el.classList.remove("is-target"));
      const region = target && (target.classList.contains("func-region") ? target : target.closest(".func-region"));
      if (region) region.classList.add("is-target");
      return region;
    }

    function scrollRegion(region, options) {
      const scroller = region.closest(".run-board-scroll") || region.closest(".workspace-main");
      if (!scroller) return;
      const top = region.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
      scroller.scrollTo({ top: Math.max(0, top), behavior: scrollBehavior(options) });
    }

    function applyRoute(path, hash, options) {
      const historyMode = options && options.historyMode;
      const route = routeFromPath(path);
      const titles = {
        hitl: "GeniStudio · 运行",
        project: "GeniStudio · 项目",
        workflow: "GeniStudio · 流程",
        role: "GeniStudio · 角色",
        config: "GeniStudio · 配置",
        help: "GeniStudio · 帮助",
      };
      document.documentElement.dataset.route = route;
      document.title = titles[route];
      document.querySelectorAll(".side-group").forEach((group) => {
        const on = group.dataset.route === route;
        group.classList.toggle("is-current", on);
        const link = group.querySelector(":scope > a.sidebar-link");
        if (link) link.classList.toggle("is-active", on);
      });
      let helpHash = hash || "";
      if (route === "help" && !(helpHash.replace(/^#/, ""))) helpHash = "#overview";
      if (historyMode === "push" || historyMode === "replace") {
        let base = "/" + hitlSearch;
        if (route === "config") base = "/config";
        if (route === "project") {
          const pid = new URLSearchParams(location.search).get("project");
          base = "/project" + (pid ? "?project=" + encodeURIComponent(pid) : "");
        }
        if (route === "workflow") {
          const wid = new URLSearchParams(location.search).get("workflow");
          base = "/workflow" + (wid ? "?workflow=" + encodeURIComponent(wid) : "");
        }
        if (route === "role") {
          const rid = new URLSearchParams(location.search).get("role");
          base = "/role" + (rid ? "?role=" + encodeURIComponent(rid) : "");
        }
        if (route === "help") base = "/help";
        const method = historyMode === "push" ? "pushState" : "replaceState";
        history[method]({ route }, "", base + (route === "help" ? helpHash : (hash || "")));
      }
      if (route === "workflow" && historyMode && !(options && options.skipWorkflow) && window.applyWorkflowLocation) {
        window.applyWorkflowLocation();
      }
      if (route === "role" && historyMode && !(options && options.skipRole) && window.applyRoleLocation) {
        window.applyRoleLocation();
      }
      if (route === "help") {
        showHelp(helpHash);
        return;
      }
      if (route === "config" && typeof window.refreshConfigRuntime === "function") {
        void window.refreshConfigRuntime();
      }
      if (route === "hitl") {
        if (typeof window.loadRunConfigOptions === "function") void window.loadRunConfigOptions();
        if (typeof window.syncRunBackendModels === "function") void window.syncRunBackendModels();
      }
      if (!hash || route === "project" || route === "workflow" || route === "role") return;
      const target = document.getElementById(decodeURIComponent(hash.slice(1)));
      const region = markRegion(target);
      if (region && !(options && options.skipScroll)) scrollRegion(region, options);
    }

    document.querySelector(".app-side-nav").addEventListener("click", (event) => {
      const link = event.target.closest("a");
      if (!link) return;
      let url;
      try {
        url = new URL(link.getAttribute("href") || "", location.origin);
      } catch (err) {
        return;
      }
      if (url.origin !== location.origin) return;
      if (url.pathname !== "/" && url.pathname !== "/config" && url.pathname !== "/project" && url.pathname !== "/workflow" && url.pathname !== "/role" && url.pathname !== "/help") return;
      event.preventDefault();
      if (location.pathname === "/role" && url.pathname !== "/role" && window.confirmLeaveRole && !window.confirmLeaveRole()) return;
      if (link.dataset.roleMode && window.requestRoleMode) {
        if (location.pathname !== "/role" && window.confirmLeaveRole && !window.confirmLeaveRole()) return;
        applyRoute("/role", url.hash, { skipRole: true });
        window.requestRoleMode(link.dataset.roleMode);
        return;
      }
      if (link.dataset.workflowMode && window.requestWorkflowMode) {
        applyRoute("/workflow", url.hash, { skipWorkflow: true });
        window.requestWorkflowMode(link.dataset.workflowMode);
        return;
      }
      if (link.dataset.projectMode && window.requestProjectMode) {
        window.requestProjectMode(link.dataset.projectMode);
        return;
      }
      if (link.id === "btnSidebarNew") return;
      const route = routeFromPath(url.pathname);
      const same = document.documentElement.dataset.route === route;
      if (same && !url.hash) return;
      if (same && url.hash === location.hash) {
        applyRoute(url.pathname, url.hash, { smooth: true });
        return;
      }
      applyRoute(url.pathname, url.hash, { historyMode: "push", smooth: true });
    });

    window.addEventListener("popstate", () => {
      if (location.pathname !== "/config" && location.pathname !== "/workflow" && location.pathname !== "/role" && location.pathname !== "/help") hitlSearch = location.search;
      applyRoute(location.pathname, location.hash);
      if (location.pathname === "/project" && window.applyProjectLocation) window.applyProjectLocation();
      if (location.pathname === "/workflow" && window.applyWorkflowLocation) window.applyWorkflowLocation();
      if (location.pathname === "/role" && window.applyRoleLocation) window.applyRoleLocation();
    });

    applyRoute(location.pathname, location.hash, { historyMode: "replace" });
