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

`.env` 已在 `.gitignore` 中。`CURSOR_API_KEY`、`LARK_APP_SECRET`、`LANGSMITH_API_KEY` 只写入本机 `.env` 或配置页。配置页不回显密钥。`geni-studio config show` 对密钥只显示前四个字符。

不要把 `.env`、`tools/lark_cli/api.txt` 加入提交。不要在终端、日志或对话里打印密钥原文。不要用 `cat .env` 来核对。已有 `.env` 时不要覆盖。

工厂仓库和待开发项目分开。安装本身不创建 Run，也不把工厂仓库设为工作区。只有人明确要求用 GeniStudio 改这个仓库时，才设置 `GENI_STUDIO_ALLOW_FACTORY_TARGET=1`。

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

只想熟悉界面、确定不调用 Cursor 时，把依赖组改成 `.[dev]`。以后要接 Cursor，再执行一次带 `cursor` 的安装命令。

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

连通性脚本是 `scripts/smoke_cursor_backend.py`。只有人要求验证 Cursor 连通时才运行，并且不要把它的输出里的凭据转述出来。

## 接上飞书

飞书可以以后再配。需要时阅读 [`tools/lark_cli/README.md`](../tools/lark_cli/README.md) 与 [ADR 0004](decisions/0004-feishu-hitl-via-lark-cli.md)。最小闭环是：

1. 本机完成 `lark-cli config init`，凭据留在 lark-cli 自己的配置里，不写入仓库。
2. `.env` 中 `GENI_STUDIO_LARK_BACKEND=lark_cli`。`GENI_STUDIO_PUBLIC_BASE_URL` 写成实际打开页面的地址，默认是 `http://127.0.0.1:8765`。
3. 在飞书开放平台为这个应用订阅回调 `card.action.trigger`，否则决策点按钮没有入站事件。`im.message.receive_v1` 用于文字批复。`geni-studio-web` 默认会在本机有 `lark-cli` 时启动事件桥接，不必再开第二个进程。要关掉桥接，启动前设置 `GENI_STUDIO_FEISHU_BRIDGE=0`，再单独运行：

```bash
.venv/bin/geni-studio-feishu-bridge --webhook http://127.0.0.1:8765/api/webhooks/feishu
```

Web 端口如果改过，把 `GENI_STUDIO_FEISHU_WEBHOOK` 和 `GENI_STUDIO_PUBLIC_BASE_URL` 改成同一个端口。若设置了 `GENI_STUDIO_FEISHU_WEBHOOK_TOKEN`，桥接会带上这个请求头，Webhook 拒绝没有该头的批复。项目里的通知群或通知人优先于 `.env` 里的 `GENI_STUDIO_FEISHU_NOTIFY_CHAT_ID` 与 `GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID`。

## 开发这个仓库时

安装依赖组必须包含 `dev`。改过 `src/` 之后运行：

```bash
.venv/bin/ruff check src tests
.venv/bin/pytest -q
```

`langgraph dev` 使用 `src/geni_studio/workflows/default.py` 里的 `graph`，它不是使用产品的必要步骤。角色文件 `roles/*/role.md` 与该文件中的节点函数由人编写；安装手册不要求改它们。
