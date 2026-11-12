const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/geni_studio/web/static/hitl.js'), 'utf8');
const start = source.indexOf('    function escapeHtml(text) {');
const end = source.indexOf('    const conversations = {};', start);
assert.ok(start >= 0 && end > start);
const context = vm.createContext({});
vm.runInContext(source.slice(start, end), context);
const render = (text) => vm.runInContext(`renderMarkdown(${JSON.stringify(text)})`, context);

// 合法结论块渲染为结论卡片：通过标记、摘要、每个验收项的状态，不再出现 JSON 原文。
const verdict = {
  status: 'pass',
  ac: { 'AC-1': 'pass', 'AC-2': 'fail', 'AC-3': 'whatever' },
  summary: '界面验收全部通过 <b>',
};
const html = render('报告正文\n\n```verdict\n' + JSON.stringify(verdict) + '\n```');
assert.match(html, /<p>报告正文<\/p>/);
assert.match(html, /class="verdict-card is-pass"/);
assert.match(html, /verdict-badge is-pass">通过</);
assert.match(html, /界面验收全部通过 &lt;b&gt;/);
assert.match(html, /<li class="is-pass"><span class="verdict-ac-id">AC-1<\/span><span class="verdict-ac-state">通过/);
assert.match(html, /<li class="is-fail"><span class="verdict-ac-id">AC-2<\/span><span class="verdict-ac-state">未通过/);
assert.match(html, /<li class="is-untested"><span class="verdict-ac-id">AC-3<\/span><span class="verdict-ac-state">未验证/);
assert.doesNotMatch(html, /artifact-code|&quot;status&quot;|"status"/);

assert.match(render('```verdict\n{"status": "fail"}\n```'), /verdict-badge is-fail">未通过</);

// 不是合法结论时按原文显示，避免把格式错误的块藏起来。
for (const body of ['{"status": "maybe"}', 'not json', '[1, 2]']) {
  assert.match(render('```verdict\n' + body + '\n```'), /<pre class="artifact-code">/);
}
assert.match(render('```json\n{"status": "pass"}\n```'), /<pre class="artifact-code">/);
console.log('Verdict card regression passed');
