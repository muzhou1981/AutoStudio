const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/geni_studio/web/static/hitl.js'), 'utf8');
const extract = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
const context = vm.createContext({});
vm.runInContext(extract('function escapeHtml(text)', 'const conversations = {};'), context);
vm.runInContext(extract('function conversationTurnInFlight(', 'function conversationSection('), context);

const step = (type, message) => ({ kind: 'step', step: { type, message } });
const cursorTurn = {
  seq: 1,
  events: [
    { kind: 'turn', prompt: '角色提示' },
    step('thinkingMessage', { text: '先看一下需求文档。', thinking_duration_ms: 1200 }),
    step('thinkingMessage', { text: '再定位删除按钮。', thinking_duration_ms: 900 }),
    step('assistantMessage', { text: '我先读取需求，再查看流程编辑界面。' }),
    step('toolCall', { type: 'read', args: { path: '/repo/docs/design/ui-ux.md' }, result: { status: 'success', value: { content: 'SECRET_FILE_BODY' } } }),
    step('toolCall', { type: 'grep', args: { pattern: 'deleteWorkflow', path: '/repo/src/web', outputMode: 'content', offset: 0 }, result: { status: 'success', value: { matches: ['RAW_MATCH'] } } }),
    step('toolCall', { type: 'shell', args: { command: 'pytest -q\n  tests/test_a.py', timeout: 30000 }, result: { status: 'error', value: { stdout: 'RAW_STDOUT' } } }),
    step('toolCall', { type: 'updateTodos', args: { todos: [{ content: 'a' }, { content: 'b' }] }, result: { status: 'success' } }),
    step('thinkingMessage', { text: '确认测试结果。', thinking_duration_ms: 0 }),
    step('assistantMessage', { text: '已完成。' }),
    { kind: 'result', text: '已完成。' },
  ],
};

const html = context.formatConversation({ turns: [cursorTurn] }, { live: false });
for (const raw of ['SECRET_FILE_BODY', 'RAW_MATCH', 'RAW_STDOUT', 'outputMode', '"args"', '{"', 'thinking_duration_ms']) {
  assert.ok(!html.includes(raw), `不应出现原始内容：${raw}`);
}
assert.match(html, /<summary>思考 2 秒<\/summary>/, '回复前的两段思考合并为一块并累计用时');
assert.match(html, /先看一下需求文档。/);
assert.match(html, /<summary>思考 · 工具调用 4 次<\/summary>/, '两次回复之间的思考与工具调用合并为一块');
assert.equal((html.match(/<details class="conv-work"/g) || []).length, 2);
assert.match(html, /<div class="conv-reply"><p>我先读取需求，再查看流程编辑界面。<\/p><\/div>/);
assert.equal((html.match(/已完成。/g) || []).length, 1, '与最终结果相同的中间回复不重复显示');
assert.match(html, /读取<\/span> <span class="conv-tool-target">design\/ui-ux.md<\/span>/);
assert.match(html, /搜索<\/span> <span class="conv-tool-target">deleteWorkflow · src\/web<\/span>/);
assert.match(html, /conv-tool is-failed"><span class="conv-tool-verb">执行<\/span> <span class="conv-tool-target">pytest -q tests\/test_a.py<\/span> <span class="conv-tool-failed">失败<\/span>/);
assert.match(html, /更新待办<\/span> <span class="conv-tool-target">2 项<\/span>/);
assert.ok(html.indexOf('conv-reply') < html.indexOf('工具调用 4 次'), '按时间顺序展示');
assert.ok(html.indexOf('pytest -q') < html.indexOf('确认测试结果。'), '块内按时间顺序展示');

const live = context.formatConversation({ turns: [{ seq: 2, events: cursorTurn.events.slice(0, 6) }] }, { live: true });
assert.match(live, /<summary>思考 2 秒<\/summary>/, '进行中的轮次里，已有回复之前的过程收起');
assert.ok(!live.includes('工具调用 2 次'), '最新的过程直接展开');
assert.match(live, /读取<\/span> <span class="conv-tool-target">design\/ui-ux.md/);
assert.match(live, /思考中…<\/p><\/details>$/);
assert.match(live, /^<details class="conv-turn" data-key="turn-2" open><summary><h4>第 2 次<\/h4><\/summary>/);

const multi = context.formatConversation({ turns: [cursorTurn, { seq: 2, events: cursorTurn.events }] }, { live: false });
assert.match(multi, /<details class="conv-turn" data-key="turn-1"><summary>/, '较早的一次默认收起');
assert.match(multi, /<details class="conv-turn" data-key="turn-2" open><summary>/, '最近一次默认展开');
assert.match(multi, /data-key="work-2-1"/, '过程块带稳定的键，重绘后可恢复折叠状态');

const codexTurn = {
  seq: 1,
  events: [
    step('item/reasoning/summaryTextDelta', { delta: 'PARTIAL' }),
    step('item/completed', { item: { type: 'reasoning', summary: ['比较两种实现。'], content: [] } }),
    step('item/completed', { item: { type: 'commandExecution', command: 'make test', exitCode: 2, aggregatedOutput: 'RAW_OUTPUT' } }),
    step('item/completed', { item: { type: 'fileChange', changes: [{ path: '/repo/src/a.py', diff: 'RAW_DIFF' }] } }),
    step('item/completed', { item: { type: 'mcpToolCall', server: 'jira', tool: 'get_issue', arguments: { key: 'X' } } }),
    step('item/completed', { item: { type: 'agentMessage', phase: 'final_answer', text: 'FINAL_DUP' } }),
    step('thread/tokenUsage/updated', { tokenUsage: { total: 1 } }),
    { kind: 'result', text: '完成' },
  ],
};
const codex = context.formatConversation({ turns: [codexTurn] }, { live: false });
for (const raw of ['PARTIAL', 'RAW_OUTPUT', 'RAW_DIFF', 'FINAL_DUP', 'tokenUsage']) {
  assert.ok(!codex.includes(raw), `不应出现原始内容：${raw}`);
}
assert.match(codex, /比较两种实现。/);
assert.match(codex, /执行<\/span> <span class="conv-tool-target">make test<\/span> <span class="conv-tool-failed">失败/);
assert.match(codex, /编辑<\/span> <span class="conv-tool-target">src\/a.py<\/span>/);
assert.match(codex, /调用<\/span> <span class="conv-tool-target">jira.get_issue<\/span>/);
assert.match(codex, /<summary>思考 · 工具调用 3 次<\/summary>/);

const ask = {
  id: 'q1',
  prompt: '范围怎么定？',
  choices: [{ id: 'A', label: '只改 Run 页', recommended: true }, { id: 'B', label: '全站一起改', recommended: false }],
  signature: 'A=只改 Run 页|B=全站一起改',
  hide: ['**范围怎么定？**', '- **A（推荐）**：只改 Run 页', '- **B**：全站一起改'],
};
const askText = '先确认：\n\n**范围怎么定？**\n\n- **A（推荐）**：只改 Run 页\n- **B**：全站一起改\n\n请选 A / B。';
const askTurn = { seq: '001', events: [{ kind: 'result', text: askText }], questions: [ask] };
const pending = context.formatConversation({ turns: [askTurn] }, { live: false });
assert.ok(!pending.includes('全站一起改</li>'), '选项行由题卡展示，回复正文不再重复');
assert.equal((pending.match(/class="conv-ask"/g) || []).length, 1);
assert.equal((pending.match(/<input type="checkbox" value="[AB]" disabled>/g) || []).length, 2, '未答复题卡默认只读，待批复时再激活');
assert.match(pending, /<span class="conv-ask-tag">推荐<\/span>/);
assert.match(pending, /请选 A \/ B。/);
assert.ok(!pending.includes('conv-human'));

const answeredTurn = {
  ...askTurn,
  events: [...askTurn.events, { kind: 'human', decision: 'approved', channel: 'web', reply: '同意A', answers: { q1: 'A' } }],
};
const answered = context.formatConversation({ turns: [answeredTurn] }, { live: false });
assert.match(answered, /class="conv-ask is-answered" data-signature="A=只改 Run 页\|B=全站一起改" data-answered="1"/);
assert.match(answered, /<label class="conv-ask-option is-picked"><input type="checkbox" value="A" disabled checked>/);
assert.match(answered, /<label class="conv-ask-option"><input type="checkbox" value="B" disabled>/);
assert.match(answered, /<p class="conv-human-head">人工答复 · 批准<\/p><p class="conv-human-text">同意A<\/p>/);

const taskArgs = { description: '统计文件', prompt: '列出文件', subagentType: { kind: 'explore' }, model: 'composer-2.5-fast', agentId: 'sub-1' };
const taskTurn = {
  seq: 3,
  events: [
    step('taskStarted', { args: taskArgs }),
    step('taskStarted', { args: { ...taskArgs, description: '另一个子代理', agentId: 'sub-2' } }),
    step('toolCall', { type: 'shell', args: { command: 'nohup npm run dev >/tmp/dev.log 2>&1 &' }, result: { status: 'success', value: { exitCode: 0 } } }),
    step('toolCall', { type: 'shell', args: { command: 'sleep 30' }, result: { status: 'success', value: { exitCode: 0 } } }),
    step('toolCall', { type: 'shell', args: { command: 'nohup python -m http.server 8766 &' }, result: { status: 'success', value: { exitCode: 0 } } }),
    step('toolCall', { type: 'task', args: taskArgs, result: { status: 'success', value: { agentId: 'sub-1', isBackground: false, durationMs: 3064, toolCount: 2, reply: '**数量：0**' } } }),
  ],
};
const processes = [
  { pid: 41, command: 'npm run dev', started_at: 0 },
  { pid: 42, command: 'sleep 30', started_at: 0 },
];
const tasks = context.formatConversation({ turns: [taskTurn], processes }, { live: true });
assert.equal((tasks.match(/统计文件/g) || []).length, 1, '子代理完成后只保留完成的一条');
assert.match(tasks, /<div class="conv-task is-running">.*另一个子代理.*运行中/, '未完成的子代理标为运行中');
assert.match(tasks, /<div class="conv-task is-done">.*子代理<\/span> <span class="conv-task-desc">统计文件<\/span><span class="conv-tag">完成<\/span>/);
assert.match(tasks, /explore · composer-2.5-fast · 工具调用 2 次 · 3 秒/);
assert.match(tasks, /<summary>结果<\/summary><div class="conv-task-reply"><p><strong>数量：0<\/strong><\/p>/);
assert.match(tasks, /npm run dev &gt;\/tmp\/dev.log 2&gt;&amp;1 &amp;<\/span><span class="conv-tag is-live" title="pid 41">后台 · 运行中/, '仍在运行的后台命令按进程比对');
assert.match(tasks, /sleep 30<\/span><span class="conv-tag is-live" title="pid 42">后台 · 运行中/, '没有 & 的命令只要进程仍在也标为后台');
assert.match(tasks, /http.server 8766 &amp;<\/span><span class="conv-tag">后台 · 已结束/, '写法是后台但进程已不在');
assert.match(tasks, /^<details class="conv-procs" data-key="procs" open><summary>本轮仍在运行的进程 2 个<\/summary>/);
const noProcs = context.formatConversation({ turns: [taskTurn] }, { live: false });
assert.ok(!noProcs.includes('conv-procs'));
assert.match(noProcs, /http.server 8766 &amp;<\/span><span class="conv-tag">后台<\/span>/, '没有进程信息时不判断是否结束');

console.log('Conversation rendering regression passed');
