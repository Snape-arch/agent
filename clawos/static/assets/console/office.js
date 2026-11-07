// office behavior for the ClawOS workbench.
import { $, consoleState, esc } from './core.js';
export function loadOfficeEditorScript(url) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script"); script.src = url; script.onload = resolve; script.onerror = reject; document.head.appendChild(script);
  });
}

export async function openEmbeddedOfficeEditor(artifactId) {
  const modal = $("officeEditorModal"), mount = $("office-editor-mount"), status = $("officeEditorStatus");
  modal?.classList.add("on"); modal?.setAttribute("aria-hidden", "false");
  if (mount) mount.innerHTML = ""; if (status) status.textContent = "正在建立安全编辑会话…";
  try {
    const caps = await fetch("/api/office/editor/capabilities").then(r => r.json());
    const provider = ["onlyoffice", "wps", "collabora"].find(name => caps.configured?.includes(name));
    if (!provider) throw new Error("尚未配置 WPS、ONLYOFFICE 或 Collabora 编辑服务");
    const response = await fetch("/api/office/editor/session", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({artifact_id:artifactId,provider,mode:"edit"})});
    const session = await response.json(); if (!response.ok) throw new Error(session.detail || "编辑会话创建失败");
    const config = session.mount; if (status) status.textContent = `${provider} · 会话将在 15 分钟后过期`;
    if (config.type === "onlyoffice-docsapi") {
      if (!window.DocsAPI) await loadOfficeEditorScript(config.script_url);
      consoleState.office.embeddedOfficeInstance = new window.DocsAPI.DocEditor("office-editor-mount", config.config);
    } else if (config.type === "wps-jssdk") {
      if (!window.WebOfficeSDK) await loadOfficeEditorScript(config.sdk_url);
      consoleState.office.embeddedOfficeInstance = window.WebOfficeSDK.init(config.config);
    } else {
      mount.innerHTML = `<iframe title="Office editor" src="${esc(config.iframe_url)}" allow="clipboard-read; clipboard-write"></iframe>`;
    }
  } catch (error) { if (status) status.textContent = error.message || String(error); }
}

export function closeEmbeddedOfficeEditor() {
  try { consoleState.office.embeddedOfficeInstance?.destroy?.(); } catch (_) {}
  consoleState.office.embeddedOfficeInstance = null; $("office-editor-mount")?.replaceChildren();
  $("officeEditorModal")?.classList.remove("on"); $("officeEditorModal")?.setAttribute("aria-hidden", "true");
}
