# GeniStudio 安装手册

这份手册同时给人读，也给 Agent 执行。说明性段落解释目的和取舍。标题为「执行契约」的一节是唯一的操作依据：命令、成功标准和停止条件都写在那里。Agent 遇到契约里没有授权的步骤时停下来，不要自行扩展。

仓库根目录是包含 `pyproject.toml` 的那一层。检出目录名可以仍是 `auto_studio`，不必改名。

## 装好之后应看到什么

本机有一个只服务于这个仓库的 Python 虚拟环境，包 `geni-studio` 以可编辑方式装在里面。仓库根目录有一份不进入版本库的 `.env`。浏览器打开 `http://127.0.0.1:8765/`，页面标题是「GeniStudio · 运行」。此时不必填写 Cursor 密钥，后端选 stub 就可以熟悉界面。

## 前提

- 操作系统能运行 bash，并已安装 git。
- Python 3.12。项目声明的下限是 3.11，持续集成使用 3.12，安装时以 3.12 为准。
- 能访问安装 Python 包所需的网络。
- 优先使用 `uv`。没有 `uv` 时，用下面契约里的 `venv` 与 `pip` 路径，这与持续集成一致。
- 调用 Cursor 时才需要 `CURSOR_API_KEY`，以及额外依赖组 `cursor`。
- 飞书通知和批复是可选项，依赖本机已配置的 `lark-cli`。不配飞书不影响 Web 页面。

## 密钥与仓库边界

`.env` 已在 `.gitignore` 中。`CURSOR_API_KEY`、`OPENAI_API_KEY`、`LARK_APP_SECRET`、`LANGSMITH_API_KEY` 只写入本机 `.env` 或配置页。配置页不回显密钥。`geni-studio config show` 对密钥只显示前四个字符。

不要把 `.env`、`tools/lark_cli/api.txt` 加入提交。不要在终端、日志或对话里打印密钥原文。不要用 `cat .env` 来核对。已有 `.env` 时不要覆盖。

工厂仓库和待开发项目通常分开；若要在本仓库内做工厂自举开发，可在项目里将工作区指向工厂根目录（须为 git 仓库）。

## 执行契约

以下命令都在仓库根目录执行。每一步的成功标准不满足就停止，不要继续后面的步骤。

### 1. 确认位置与 Python

```bash
test -f pyproject.toml && test -f .env.example
python3.12 --version
```

成功标准：两条测试都通过，版本行以 `Python 3.12` 开头。`python3.12` 不存在时停止，不要改用系统里别的主版本。

### 2. 创建虚拟环境并安装

有 `uv` 时：

```bash
uv venv --python 3.12
uv pip install -e ".[cursor,dev]"
```

没有 `uv` 时：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[cursor,dev]"
```

只想熟悉界面、确定不调用外部模型时，把依赖组改成 `.[dev]`。以后要接 Cursor，再执行一次带 `cursor` 的安装命令。要接 Codex，安装可选依赖组 `codex`（包 `openai-codex`），配置页后端选 codex。本机已登录 Codex 时不必写密钥；尚未登录时写入 `OPENAI_API_KEY`。

成功标准：

```bash
.venv/bin/python -c "import geni_studio, fastapi, langgraph; print('import-ok')"
```

输出恰好是 `import-ok`。安装写进 `.venv`，不要安装到系统 Python。

### 3. 准备环境文件

`.env` 不存在时：

```bash
test -f .env || cp .env.example .env
```

已存在则跳过复制。不要改写其中已有的密钥。

成功标准：`test -f .env` 通过，并且 `git check-ignore -q .env` 通过。

### 4. 启动 Web 并核对

默认地址是 `127.0.0.1:8765`。`geni-studio-web` 没有端口参数。先看这个端口：

```bash
ss -ltn | awk '$4 ~ /:8765$/'
```

已有监听时不要结束那个进程。把占用者告诉人，等指示后再换端口。换端口只能用下面这条，并把后面的核对地址改成同一个端口：

```bash
.venv/bin/python -m uvicorn geni_studio.web.app:app --host 127.0.0.1 --port 8765
```

端口空闲时，在前台启动：

```bash
.venv/bin/geni-studio-web
```

另开一个终端核对：

```bash
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/
curl -fsS http://127.0.0.1:8765/ | grep -o 'GeniStudio · 运行' | head -n 1
```

成功标准：第一行是 `200`，第二行是 `GeniStudio · 运行`。浏览器打开同一地址即可使用。

到这里安装完成。不要为了核对而去启动一轮真实 Run。

## 只熟悉界面

在「配置」的 Agent 里把后端选为 stub，然后写入 `.env`。stub 不调用 Cursor，密钥可以留空。模型留空时使用 Auto。工作区可以先空着。

页面上的使用顺序是：先在「流程」里选用或新建一份流程，再在「项目」里选定该流程，然后到「运行」里选定项目并启动。这些动作不属于安装。

## 运行期排障

本节在 Web 已能打开、但启动 Run、界面状态或服务行为异常时使用。命令均在仓库根目录执行。

### 确认 8765 由谁占用

GeniStudio Web 默认监听 `127.0.0.1:8765`。先查监听进程，再决定是复用还是重启：

```bash
ss -tlnp | grep ':8765'
lsof -iTCP:8765 -sTCP:LISTEN
```

常见情况：

| 表现 | 含义 |
|------|------|
| 命令行为 `geni-studio-web` 或 `.venv/bin/python3 … geni-studio-web` | 正常产品进程 |
| `uvicorn geni_studio.web.app:app` | 手工 uvicorn 启动，行为与入口脚本一致 |
| 其他未知进程 | 不要直接强杀；先记下 PID 与完整命令行，再换端口或按指示处理 |

查看完整命令行：

```bash
ps -fp <PID> -o pid,lstart,cmd
```

需要在本机重启 Web（改动了 `src/` 下的 Python 或刚拉代码后）：

```bash
kill -TERM <PID>
.venv/bin/geni-studio-web
```

另开终端核对：

```bash
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/
```

### 何时必须重启 Web、何时只强刷页面

| 改动类型 | 操作 |
|----------|------|
| `src/` 内 Python（新 API、启动逻辑、工作区校验等） | **重启** `geni-studio-web` |
| `src/geni_studio/web/static/` 下 HTML/CSS/JS | 浏览器 **强刷**（Ctrl+Shift+R）；若仍像旧版，确认 `hitl.html` 里 `config.js` 等带 `?v=` 查询参数已更新 |
| 只改 `.env` | 重启 Web 后配置才注入进程 |

### 启动 Run 失败或按钮一直转圈

1. **看页面红色提示**（启动按钮上方）。后端业务错误会以中文 `detail` 返回，例如工作区不是 git 仓库、场景材料未齐、目标项目写入锁被占用等。
2. **用 curl 复现**（便于区分网络与业务错误）：

```bash
curl -sS -i -X POST http://127.0.0.1:8765/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"human_request":"试启动","project_id":"_example","run_name":"试跑","node_tools":{},"attachments":[],"role_models":{}}'
```

应返回 `200` 或 `400` 且 `Content-Type: application/json`。若长时间无响应，多半是服务端仍在执行图节点；重启 Web 后重试，并查看终端里 `geni-studio-web` 的报错栈。

3. **「启动没有返回」或纯英文 `Internal Server Error`**：多半是旧进程未加载新 API，或响应不是 JSON。先重启 Web 并强刷页面。
4. **侧栏 Run 列表或泳道不动**：启动后应很快出现 `thread_id` 与轨道更新。若仍停在启动前，确认未阻塞在旧版同步启动（当前默认在后台 invoke，POST 应快速返回）。仍异常时打开开发者工具 Network，看 `POST /api/runs` 与 `GET /api/runs/<id>` 是否成功。

### 工作区与写入锁

- **自我改进**（`self_improve`、工作区指向工厂或目标仓库当前分支）允许开工时已有未提交改动；确认入库时由程序员节点在同一分支提交。
- **分离头指针**（`git` 处于 detached HEAD）仍不能启动，需先切回命名分支。
- 提示 **「目标项目已有写入进行中」**：同一可写目录上一次启动未正常结束，锁仍被占用。独立工作树的锁在 `.geni_studio/locks/<运行标识>.lock`，各轮互不阻塞；当前分支模式的锁在 `.geni_studio/write.lock`，同一仓库同时只有一轮。锁文件记录了持有者（`pid=… thread=… since=…`）。执行器遇到写锁占用时，该轮显示「等待写锁」并自动重试；若持有进程已不存在，结束卡住的 `geni-studio-web` 或执行进程后重启。
- **推送防护**：每个运行工作区在 `config.worktree` 中把远端的 `pushurl` 设为不可用地址，并把 `core.hooksPath` 指向拒绝推送的钩子目录（其余钩子链接回原钩子）。当前分支模式下防护作用于仓库本身，本轮结束（完成、驳回或停止）后自动撤销；运行期间如需人工推送，请等本轮结束。
- **回收**：删除运行时会移除其工作树与运行目录，未合入的 `geni-studio/<thread_id>` 分支保留。`geni-studio gc --dry-run` 列出孤立的工作树、运行目录与已合入分支，去掉 `--dry-run` 执行回收。

### 本地项目与流程不进 git

Web 里新建的项目目录与「另存为」流程默认在 `.gitignore` 中忽略（见仓库根 `.gitignore`）。若启动后找不到项目，确认 `projects/<id>/project.yaml` 与 `workflows/<id>/workflow.yaml` 在本机存在即可，不必提交到远端。

### 测试与生产启动行为

持续集成与本地 `pytest` 默认设置 `GENI_STUDIO_SYNC_START=1`，推进任务在请求线程内执行（执行器 `inline` 模式），`POST /api/runs` 会等图跑到关卡再返回。日常手工启动的 `geni-studio-web` **不**设置该项：启动、批复、继续与续跑请求只写入决定并入队，立即返回「运行中」，由 Web 进程内的执行器推进（`GENI_STUDIO_EXECUTOR_WORKERS` 控制并发，默认 4）。设置 `GENI_STUDIO_EXECUTOR=external` 时 Web 只入队，另起 `.venv/bin/geni-studio-worker` 执行；两者须使用同一检查点目录。设计见 [ADR 0011](decisions/0011-run-executor-and-runtime-store.md)。

### 访问控制

- `GENI_STUDIO_WEB_TOKEN`：设置后，`/api/*`（飞书回调除外）须带令牌，可用请求头 `X-Geni-Studio-Token`、`Authorization: Bearer <令牌>` 或 Cookie。浏览器首次打开 `http://<地址>/?token=<令牌>` 写入 Cookie。
- `GENI_STUDIO_WEB_HOST`：监听地址，默认 `127.0.0.1`。监听非回环地址时必须设置访问令牌，否则 `geni-studio-web` 拒绝启动。
- `GENI_STUDIO_WEB_OPERATOR`：Web 入口的审批人名称，写入审计行的 `actor=`，缺省为 `web`。审计中的 `channel` 由服务端按入口确定，不读取请求体。

## 接上 Cursor

人在配置页写入 Cursor API Key。Agent 若被明确要求写入，使用：

```bash
.venv/bin/geni-studio config set CURSOR_API_KEY '<密钥>'
.venv/bin/geni-studio config set GENI_STUDIO_BACKEND cursor
```

命令里的密钥不要回显，不要写入仓库文件以外的 `.env`。核对只用：

```bash
.venv/bin/geni-studio config show
```

`CURSOR_API_KEY` 一行应显示为前四个字符加省略号，不应出现完整密钥。模型要用固定值时再写 `GENI_STUDIO_CURSOR_MODEL`；留空表示 Auto。

Cursor 角色的推理强度可在项目 YAML 的 `backends.<角色>.reasoning_effort` 中填写，或在运行页点选活动节点后于右栏为本轮选择。可选级别取自 `Cursor.models.list` 中该模型声明的推理参数，调用时以 `ModelSelection` 参数传给 SDK；Auto 模型不能指定推理强度，所选级别不受该模型支持时拒绝启动。目录中列出的模型可能因账号所在地区不可用，此时调用会返回地区不支持的错误。

连通性脚本是 `scripts/smoke_cursor_backend.py`。只有人要求验证 Cursor 连通时才运行，并且不要把它的输出里的凭据转述出来。

## 接上 Codex

在仓库根目录安装可选依赖；当前适配与测试固定为 `openai-codex==0.167.0`：

```bash
uv pip install -e '.[codex,dev]'
```

不用 uv 时，执行 `.venv/bin/python -m pip install -e '.[codex,dev]'`。

认证可选择以下一种方式：

- 复用启动服务的同一系统用户的 Codex 登录。若本机已有 Codex CLI，可用 `codex login` 登录、`codex login status` 查看状态；这种方式不需要另设 `OPENAI_API_KEY`。
- 在配置页 Agent 中选择 codex，添加 OpenAI API Key。密钥保存在本机 `.env`，不写入项目 YAML。环境中存在 `OPENAI_API_KEY` 时，后端优先使用它；切回本机账号时，应清除这个 Key 并重新确认 Codex 登录状态。

启动：

```bash
export GENI_STUDIO_BACKEND=codex
export GENI_STUDIO_WORKSPACE=1
.venv/bin/geni-studio-web
```

打开 `http://127.0.0.1:8765/`，项目选择目标 Git 工作区及流程，再从运行页启动。模型留空、`default` 或 `auto` 时沿用 SDK 默认模型。需要固定模型时设置 `GENI_STUDIO_CODEX_MODEL`，或在项目 YAML 中为角色配置：

```yaml
backends:
  developer:
    backend: codex
    reasoning_effort: high
    sandbox: workspace-write
    timeout_seconds: 1800
  code_reviewer:
    backend: codex
    reasoning_effort: medium
    sandbox: read-only
verification:
  command: python -m unittest discover -v
```

`model` 是各角色可选字段；运行页临时选择优先于项目配置。沙箱只接受 `read-only` 和 `workspace-write`，需要写入的角色不能选择只读。`timeout_seconds` 为 SDK 客户端启动完成后的调用时限，必须是有限正数。验证命令在本轮工作树中执行；真实测试角色缺少验证命令时，工厂不会自动认定测试通过。

推理强度可在「配置 → Agent」选择 Codex 后设置，或在工厂 `.env` 中填写 `GENI_STUDIO_CODEX_REASONING_EFFORT=high`。也可在运行页点选活动节点后，在右栏为该角色选择本轮的推理强度。优先级是本轮角色选择、项目 YAML 中该角色的 `reasoning_effort`、工厂环境配置、Codex 默认；省略项目角色字段表示继承工厂设置，填写 `default`、`auto` 或空字符串表示跳过工厂设置并沿用 Codex 默认。

运行页选择「沿用项目 / 工厂设置」表示不覆盖原配置；选择「沿用 Codex 默认」则跳过项目和工厂推理设置。可用级别随该角色选中的模型刷新；继承的默认模型已明确时，也会直接显示其支持的级别。本轮选择随「保存 Run 配置」、重新打开、复制与 Run 续跑保留，不修改 `.env` 或项目 YAML；已启动 Run 的控件与模型控件一样只读。

模型列表通过 SDK `models()` 动态获取；推理选项来自该模型的 `supported_reasoning_efforts`，并将 `default_reasoning_effort` 标为「模型建议」。页面不再枚举固定的推理选项。模型切换后，若已有推理设置不在新模型能力列表中，会保留原值并提示重新选择，保存时拒绝明确不支持的组合。

模型留在「Codex 默认」时，SDK 模型目录的 `is_default` 不保证等于本机配置或目标工作区最终使用的模型，页面不据此猜测推理能力；要选择具体推理级别，请先明确选择模型。请求失败或已保存模型不在目录中时，保留已有配置并显示未确认支持的提示，可刷新配置页重试，不自动清空配置。

当前 SDK 协议接受 `none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`、`ultra`，配置写入仍作协议枚举校验；这不等于各模型都支持全部级别。未设置时不传 SDK 的 `effort` 参数，由 Codex 配置及模型默认决定，不保证是 medium。参考 [Codex 配置说明](https://developers.openai.com/codex/config-reference/)。

工厂推理设置和角色配置在 Run 启动时保存，后续修改供新 Run 使用；旧 Run 续跑仍使用其快照。选择「沿用 Codex 默认」时，工厂不冻结外部 Codex 配置文件的内容。显式推理级别不同的调用使用不同会话，不复用可能带有旧推理设置的线程。

`verification` 还支持以下字段：

```yaml
verification:
  command: [make, test]        # 字符串或参数列表
  allow: [make, ctest, bash]   # 在内置白名单（pytest、python、python3、go、cargo、npm）之外追加
  timeout_seconds: 1800        # 缺省 120 秒
  sandbox: bwrap               # none（缺省）或 bwrap：根文件系统只读、仅工作树可写、无网络
```

验证命令的子进程不继承密钥类环境变量（名称含 `KEY`、`TOKEN`、`SECRET`、`PASSWORD`、`CREDENTIAL`，或以 `LARK_`、`CURSOR_`、`OPENAI_` 等前缀开头）。命令不允许包含 shell 元字符；需要管道时写成脚本，并把解释器（如 `bash`）加入 `allow`。

配置页连通检查不生成内容，不能证明某个模型具有推理权限。开发者明确需要执行真实 SDK 集成测试时，可运行：

```bash
GENI_STUDIO_CODEX_LIVE_TEST=1 .venv/bin/pytest tests/test_codex_live.py -v
```

这会调用已认证账号的模型，在临时目录验证会话恢复、开发与测试闭环，以及运行中停止；不属于普通安装核对步骤。

## 接上飞书

飞书可以以后再配。需要时阅读 [`tools/lark_cli/README.md`](../tools/lark_cli/README.md) 与 [ADR 0004](decisions/0004-feishu-hitl-via-lark-cli.md)。最小闭环是：

1. 本机完成 `lark-cli config init`，凭据留在 lark-cli 自己的配置里，不写入仓库。
2. `.env` 中 `GENI_STUDIO_LARK_BACKEND=lark_cli`。`GENI_STUDIO_PUBLIC_BASE_URL` 写成实际打开页面的地址，默认是 `http://127.0.0.1:8765`。
3. 在飞书开放平台为这个应用订阅回调 `card.action.trigger`，否则决策点按钮没有入站事件。`im.message.receive_v1` 用于文字批复。`geni-studio-web` 默认会在本机有 `lark-cli` 时启动事件桥接，不必再开第二个进程。要关掉桥接，启动前设置 `GENI_STUDIO_FEISHU_BRIDGE=0`，再单独运行：

```bash
.venv/bin/geni-studio-feishu-bridge --webhook http://127.0.0.1:8765/api/webhooks/feishu
```

Web 端口如果改过，把 `GENI_STUDIO_FEISHU_WEBHOOK` 和 `GENI_STUDIO_PUBLIC_BASE_URL` 改成同一个端口。飞书回调必须带 `GENI_STUDIO_FEISHU_WEBHOOK_TOKEN`：内置桥接在未配置时自动生成一个随机令牌；单独运行 `geni-studio-feishu-bridge` 时须在 `.env` 中设置该令牌并与 Web 进程一致，否则桥接拒绝启动、Webhook 拒绝回调。仅本地调试可设置 `GENI_STUDIO_FEISHU_WEBHOOK_INSECURE=1` 跳过校验。项目可在 `project.yaml` 的 `hitl.feishu.approvers` 中列出允许批复的 `open_id`，配置后名单外的飞书批复被拒绝；审计行记录批复人的 `open_id`。项目里的通知群或通知人优先于 `.env` 里的 `GENI_STUDIO_FEISHU_NOTIFY_CHAT_ID` 与 `GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID`。

从桌面、IDE 或 systemd 启动 `geni-studio-web` 时，进程 `PATH` 往往**不含** nvm 下的 `lark-cli`，日志会出现 `[feishu-bridge] 未启动：找不到 lark-cli`，配置页也会显示 lark-cli 未安装。任选一种处理：在启动命令前 `export PATH="$HOME/.nvm/versions/node/<版本>/bin:$PATH"`；`ln -s "$(which lark-cli)" ~/bin/lark-cli`（`~/bin` 常在默认 PATH 中）；或在 `.env` 设置 `GENI_STUDIO_LARK_CLI_PATH=/绝对路径/lark-cli`。代码也会对 `~/.nvm/versions/node/*/bin/lark-cli` 做补充查找，但重启 Web 后方能生效。

## 开发这个仓库时

安装依赖组必须包含 `dev`。改过 `src/` 之后运行：

```bash
.venv/bin/ruff check src tests
.venv/bin/pytest -q
```

`langgraph dev` 使用 `src/geni_studio/workflows/default.py` 里的 `graph`，它由 `workflows/factory_default/workflow.yaml` 编译而来，不是使用产品的必要步骤。角色文件 `roles/*/role.md` 与 `default.py` 中的节点函数由人编写；安装手册不要求改它们。
