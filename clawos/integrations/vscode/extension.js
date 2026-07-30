const vscode = require("vscode");

function ideContext() {
  const editor = vscode.window.activeTextEditor;
  const folders = vscode.workspace.workspaceFolders || [];
  const root = folders.length ? folders[0].uri.fsPath : "";
  const openFiles = vscode.workspace.textDocuments
    .filter((doc) => doc.uri.scheme === "file")
    .map((doc) => vscode.workspace.asRelativePath(doc.uri, false));
  let selection = {};
  if (editor) {
    selection = {
      path: vscode.workspace.asRelativePath(editor.document.uri, false),
      start_line: editor.selection.start.line + 1,
      end_line: editor.selection.end.line + 1,
      text: editor.document.getText(editor.selection),
    };
  }
  const diagnostics = [];
  for (const [uri, rows] of vscode.languages.getDiagnostics()) {
    if (uri.scheme !== "file") continue;
    for (const item of rows.slice(0, 100)) {
      diagnostics.push({
        path: vscode.workspace.asRelativePath(uri, false),
        line: item.range.start.line + 1,
        severity: item.severity,
        message: item.message,
        source: item.source || "",
      });
    }
  }
  return {
    repo_path: root,
    open_files: openFiles,
    selection,
    diagnostics: diagnostics.slice(0, 500),
    editor: "vscode",
  };
}

async function post(path, payload) {
  const baseUrl = vscode.workspace
    .getConfiguration("clawos")
    .get("baseUrl", "http://127.0.0.1:18790");
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
  return response.json();
}

function activate(context) {
  context.subscriptions.push(vscode.commands.registerCommand(
    "clawos.inspectContext",
    async () => {
      const value = ideContext();
      const document = await vscode.workspace.openTextDocument({
        content: JSON.stringify(value, null, 2),
        language: "json",
      });
      await vscode.window.showTextDocument(document);
    },
  ));
  context.subscriptions.push(vscode.commands.registerCommand(
    "clawos.runCodingTask",
    async () => {
      const objective = await vscode.window.showInputBox({
        prompt: "Coding objective",
      });
      if (!objective) return;
      const taskId = await vscode.window.showInputBox({prompt: "ClawOS task ID"});
      if (!taskId) return;
      const ide = ideContext();
      const normalized = await post("/api/workspace/coding/ide-context", {
        repo_path: ide.repo_path,
        context: ide,
      });
      const result = await post("/api/workspace/coding/autonomous", {
        repo_path: ide.repo_path,
        objective,
        task_id: taskId,
        session_id: `vscode-${Date.now()}`,
        focus_paths: normalized.focus_paths,
        diagnostics: normalized.diagnostics,
        confirmed: false,
        actor_id: "vscode-extension",
      });
      const document = await vscode.workspace.openTextDocument({
        content: JSON.stringify(result, null, 2),
        language: "json",
      });
      await vscode.window.showTextDocument(document);
    },
  ));
}

function deactivate() {}

module.exports = {activate, deactivate, ideContext};
