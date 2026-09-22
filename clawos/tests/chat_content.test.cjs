const { test } = require('node:test');
const assert = require('node:assert/strict');
const { render, readStream } = require('../static/assets/chat-content.js');

test('nested lists, continuation paragraphs and fenced code retain structure', () => {
  const html = render('1. 安装\n   - 子步骤\n\n     第二段\n\n     ```python\n     print("你好")\n     ```\n2. 验证');
  assert.match(html, /<ol>[\s\S]*<ul>[\s\S]*子步骤[\s\S]*第二段[\s\S]*md-code[\s\S]*<\/ul>/);
  assert.match(html, /language-python/);
  assert.match(html, /<li>验证<\/li>/);
});
test('escaped table pipes, balanced URLs, entities and inline code survive', () => {
  const html = render('| 列 | 值 |\n| --- | --- |\n| a\\|b | `x < y` |\n\n[来源](https://example.com/a_(b)?x=1&y=2)');
  assert.match(html, /<td>a\|b<\/td>/);
  assert.match(html, /<code>x &lt; y<\/code>/);
  assert.match(html, /href="https:\/\/example.com\/a_\(b\)\?x=1&amp;y=2"/);
  assert.doesNotMatch(html, /&amp;amp;/);
});
test('unclosed fences render safely and HTML, script URLs and remote images stay inert', () => {
  const html = render('<img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))\n\n![tracker](https://example.com/pixel)\n\n```js\n<script>alert(1)</script>');
  assert.doesNotMatch(html, /<img|<script|href="javascript:/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /md-copy/);
});
test('formatting inside code remains literal; reference links and strike render', () => {
  const html = render('`**literal**` and ~~old~~\n\n[doc][ref]\n\n[ref]: https://example.com');
  assert.match(html, /<code>\*\*literal\*\*<\/code>/);
  assert.match(html, /<s>old<\/s>/);
  assert.match(html, /href="https:\/\/example.com"/);
});
function response(raw, size = 1) {
  const bytes = new TextEncoder().encode(raw);
  return new Response(new ReadableStream({ start(controller) {
    for (let i = 0; i < bytes.length; i += size) controller.enqueue(bytes.slice(i, i + size));
    controller.close();
  }}));
}
test('SSE supports byte-split Chinese, CRLF, multiline data, metadata and trailing DONE', async () => {
  const updates = [];
  const raw = ': heartbeat\r\n\r\nevent: clawos_meta\r\ndata: {"task_id":7}\r\n\r\ndata: {"choices":\r\ndata: [{"delta":{"content":"你好 🌱"}}]}\r\n\r\ndata: [DONE]';
  const result = await readStream(response(raw), x => updates.push(x));
  assert.equal(result.text, '你好 🌱'); assert.equal(result.meta.task_id, 7);
  assert.deepEqual(updates, ['你好 🌱']);
});
test('SSE transport loss and malformed frames fail visibly without erasing partial text', async () => {
  let partial = '';
  await assert.rejects(readStream(response('data: {"choices":[{"delta":{"content":"已收到"}}]}\n\n'), x => partial = x), /连接已中断/);
  assert.equal(partial, '已收到');
  await assert.rejects(readStream(response('data: {bad}\n\ndata: [DONE]\n\n')), /格式不完整/);
});
test('SSE provider errors, truncation and empty answers are not success', async () => {
  await assert.rejects(readStream(response('event: error\ndata: {"error":{"message":"unavailable"}}\n\n')), /unavailable/);
  await assert.rejects(readStream(response('data: {"choices":[{"finish_reason":"length"}]}\n\n')), /长度限制/);
  await assert.rejects(readStream(response('data: [DONE]\n\n')), /没有返回/);
});
