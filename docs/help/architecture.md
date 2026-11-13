# 架构

本篇面向部署和维护 GeniStudio 的管理员，以及想了解内部结构的用户。日常使用不需要阅读。

## 分层结构 {#layers}

<figure class="arch-map">
  <figcaption class="visually-hidden">GeniStudio 架构。蓝框是 GeniStudio 自研部分，灰框是第三方组件。</figcaption>
  <section class="arch-layer" aria-label="界面">
    <p class="arch-title">界面</p>
    <div class="arch-row">
      <span class="arch-own">Web 页面</span>
      <span class="arch-own">飞书卡片</span>
      <span class="arch-own">命令行</span>
    </div>
  </section>
  <div class="arch-split">
    <section class="arch-layer" aria-label="编排层">
      <p class="arch-title">编排层</p>
      <div class="arch-row">
        <span class="arch-own">角色编排</span>
        <span class="arch-own">流程编排</span>
        <span class="arch-own">项目编排</span>
      </div>
    </section>
    <section class="arch-layer" aria-label="运行层">
      <p class="arch-title">运行层</p>
      <div class="arch-row">
        <span class="arch-own">Run 执行器</span>
      </div>
    </section>
  </div>
  <section class="arch-layer" aria-label="调度层">
    <p class="arch-title">调度层</p>
    <span class="arch-ext arch-wide">LangGraph</span>
  </section>
  <section class="arch-layer" aria-label="后端">
    <p class="arch-title">后端</p>
    <div class="arch-split arch-backends">
      <div class="arch-group">
        <span class="arch-own arch-wide">Agent 后端</span>
        <div class="arch-row">
          <span class="arch-ext">Cursor SDK</span>
          <span class="arch-ext">Codex SDK</span>
          <span class="arch-ext">DeepSeek Harness</span>
        </div>
      </div>
      <div class="arch-group">
        <span class="arch-own arch-wide">即时通信后端</span>
        <div class="arch-row">
          <span class="arch-ext">lark-cli</span>
          <span class="arch-ext">飞书应用凭据</span>
        </div>
      </div>
    </div>
  </section>
  <div class="arch-foot">
    <section class="arch-layer" aria-label="工具层">
      <p class="arch-title">工具层</p>
      <div class="arch-row">
        <span class="arch-own">Skills</span>
        <span class="arch-own">MCP</span>
        <span class="arch-own">知识库/RAG</span>
        <span class="arch-ext">沙箱</span>
      </div>
    </section>
    <section class="arch-layer arch-persist" aria-label="持久化">
      <p class="arch-title">持久化</p>
      <div class="arch-row">
        <span class="arch-ext">JSON</span>
        <span class="arch-ext">YAML</span>
        <span class="arch-ext arch-sqlite">SQLite</span>
      </div>
    </section>
  </div>
  <ul class="arch-legend">
    <li><span class="arch-own">自研</span></li>
    <li><span class="arch-ext">第三方</span></li>
  </ul>
</figure>

## 各层职责 {#responsibilities}

- **界面**：Web 页面与飞书卡片对同一轮的决定互相同步；命令行 `geni-studio` 用于配置与维护。
- **编排层**：角色、流程和项目分别定义谁来做、按什么顺序做、在哪里做，存放为工场仓库里的 Markdown 与 YAML 文件。
- **运行层**：执行器把一轮放入队列推进，启动、批复和续跑请求立即返回，不阻塞页面。
- **调度层**：流程编译成 LangGraph 状态图，在决策点前中断等人，状态保存在检查点中，服务重启后可以续跑。
- **后端**：活动交给所选的 Agent SDK 执行；通知与批复经即时通信后端发送和接收。
- **持久化**：项目、流程和角色是 YAML 与 Markdown 文件；运行状态保存在 SQLite 检查点库；决定与运行记录写成 JSON。

## 文件存放位置 {#files}

| 内容 | 位置 |
|------|------|
| 角色定义 | 工场仓库 `roles/<标识>/role.md` |
| 流程定义 | 工场仓库 `workflows/<标识>/workflow.yaml` |
| 项目定义 | 工场仓库 `projects/<标识>/project.yaml` |
| 共性设置 | 工场仓库 `.env`，不进入版本库 |
| 本轮工作树 | 待开发项目 `.geni_studio/worktrees/<Run 标识>/` |
| 本轮产物与附件 | 待开发项目 `.geni_studio/runs/<Run 标识>/` |
| 帮助正文 | 工场仓库 `docs/help/*.md` |

## 设计取舍 {#tradeoffs}

- 工场仓库与待开发项目分开。工场只在待开发项目的独立工作树里改动，不改自身源码。
- 流程是确定的图，而不是由模型临时决定下一步。这样每一轮可复现、可审计，适合已有成熟流程的规模化开发。
- 决策点是流程的一等节点。人对关键产物的批复与理由完整记录，并能作为需要修复的问题交还给角色。

更完整的设计说明见仓库的 `docs/architecture.md` 与 `docs/decisions/`。
