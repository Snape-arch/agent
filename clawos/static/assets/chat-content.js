/* Shared by live messages, persisted history and Node regression tests. */
(function (root, factory) {
  const api = factory(typeof module === "object" && module.exports
    ? require("./vendor/markdown-it-14.1.0.min.js") : root.markdownit);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ClawChatContent = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (markdownit) {
  "use strict";
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
  const parser = markdownit({ html: false, linkify: true, breaks: false, typographer: false });
  const defaultLink = parser.renderer.rules.link_open || ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options));
  parser.renderer.rules.link_open = (tokens, idx, options, env, self) => {
    tokens[idx].attrSet("target", "_blank");
    tokens[idx].attrSet("rel", "noopener noreferrer");
    return defaultLink(tokens, idx, options, env, self);
  };
  // Model-supplied images must not silently make remote requests.
  parser.renderer.rules.image = (tokens, idx) => escape(tokens[idx].content || "图片");
  parser.renderer.rules.table_open = () => '<div class="md-table-wrap"><table>\n';
  parser.renderer.rules.table_close = () => '</table></div>\n';
  function codeBlock(code, info) {
    const language = String(info || "").trim().split(/\s+/)[0].replace(/[^a-z0-9_+.#-]/gi, "").slice(0, 30);
    return `<figure class="md-code"><figcaption><span>${escape(language || "代码")}</span><button type="button" class="md-copy" aria-label="复制代码">复制</button></figcaption><pre><code${language ? ` class="language-${escape(language)}"` : ""}>${escape(code)}</code></pre></figure>\n`;
  }
  parser.renderer.rules.fence = (tokens, idx) => codeBlock(tokens[idx].content, tokens[idx].info);
  parser.renderer.rules.code_block = (tokens, idx) => codeBlock(tokens[idx].content, "");
  function render(text) {
    return parser.render(String(text ?? "").replace(/\r\n?/g, "\n"));
  }
  async function readStream(response, onText = () => {}, onMeta = () => {}) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "", text = "", meta = {}, finished = false;
    function dispatch(block) {
      let event = "message";
      const data = [];
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (!data.length) return;
      const raw = data.join("\n");
      if (raw.trim() === "[DONE]") { finished = true; return; }
      let payload;
      try { payload = JSON.parse(raw); }
      catch (_) { throw new Error("回答数据格式不完整，请重试。"); }
      if (event === "error" || payload.error) {
        throw new Error(typeof payload.error === "string" ? payload.error : payload.error?.message || payload.message || "模型返回错误");
      }
      if (event === "clawos_meta") { meta = { ...meta, ...payload }; onMeta(meta); return; }
      if (payload.clawos) { meta = { ...meta, ...payload.clawos }; onMeta(meta); }
      const choice = payload.choices?.[0];
      const piece = choice?.delta?.content;
      if (typeof piece === "string" && piece) { text += piece; onText(text); }
      if (choice?.finish_reason === "length") throw new Error("回答达到模型长度限制，内容尚未完成。");
      if (choice?.finish_reason === "content_filter") throw new Error("模型未能完成回答。");
      if (choice?.finish_reason === "stop" || event === "canceled") finished = true;
    }
    function drain() {
      let match;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        const block = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        dispatch(block);
      }
    }
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) { buffer += decoder.decode(); break; }
        buffer += decoder.decode(value, { stream: true });
        drain();
      }
      drain();
      if (buffer.trim()) dispatch(buffer);
      if (!finished) throw new Error("连接已中断，回答可能不完整，请重试。");
      if (!text.trim()) throw new Error("模型没有返回可显示的回答，请重试。");
      return { text, meta };
    } finally { reader.releaseLock(); }
  }
  return { render, readStream };
});
