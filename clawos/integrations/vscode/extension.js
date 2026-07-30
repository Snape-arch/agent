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

function requestConfig() {
  const config = vscode.workspace.getConfiguration("clawos");
  return {
    baseUrl: config.get("baseUrl", "http://127.0.0.1:18790"),
    timeoutSeconds: config.get("requestTimeoutSeconds", 180),
  };
}

async function request(path, options = {}) {
  const {baseUrl, timeoutSeconds} = requestConfig();
  const controller = new AbortController();
  const externalSignal = options.signal;
  const onAbort = () => controller.abort();
  if (externalSignal) externalSignal.addEventListener("abort", onAbort, {once: true});
  const timer = setTimeout(() => controller.abort(), timeoutSeconds * 1000);
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      ...options,
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`${response.status}: ${await response.text()}`);
    }
    return response.json();
  } finally {
    clearTimeout(timer);
    if (externalSignal) externalSignal.removeEventListener("abort", onAbort);
  }
}

async function post(path, payload, signal) {
  return request(path, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload),
    signal,
  });
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
      await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: "ClawOS coding task",
        cancellable: true,
      }, async (progress, token) => {
        const controller = new AbortController();
        token.onCancellationRequested(() => controller.abort());
        try {
          if (token.isCancellationRequested) return;
          progress.report({message: "Checking local service"});
          await request("/health", {signal: controller.signal});
          const ide = ideContext();
          progress.report({message: "Building repository context"});
          const normalized = await post("/api/workspace/coding/ide-context", {
            repo_path: ide.repo_path,
            context: ide,
          }, controller.signal);
          const sessionId = `vscode-${Date.now()}`;
          const payload = {
            repo_path: ide.repo_path,
            objective,
            task_id: taskId,
            session_id: sessionId,
            focus_paths: normalized.focus_paths,
            diagnostics: normalized.diagnostics,
            actor_id: "vscode-extension",
          };
          progress.report({message: "Preparing preview"});
          const preview = await post("/api/workspace/coding/autonomous", {
            ...payload,
            confirmed: false,
          }, controller.signal);
          const document = await vscode.workspace.openTextDocument({
            content: JSON.stringify(preview, null, 2),
            language: "json",
          });
          await vscode.window.showTextDocument(document, {preview: false});
          const decision = await vscode.window.showWarningMessage(
            "Review the ClawOS proposal. Apply changes and run tests?",
            {modal: true},
            "Apply and test",
          );
          if (decision !== "Apply and test" || token.isCancellationRequested) return;
          progress.report({message: "Applying in checkpointed workflow"});
          const result = await post("/api/workspace/coding/autonomous", {
            ...payload,
            confirmed: true,
          }, controller.signal);
          const resultDocument = await vscode.workspace.openTextDocument({
            content: JSON.stringify(result, null, 2),
            language: "json",
          });
          await vscode.window.showTextDocument(resultDocument, {preview: false});
        } catch (error) {
          if (controller.signal.aborted || token.isCancellationRequested) {
            vscode.window.showInformationMessage("ClawOS coding task cancelled.");
            return;
          }
          vscode.window.showErrorMessage(`ClawOS: ${error.message || error}`);
        }
      });
    },
  ));
}

function deactivate() {}

module.exports = {activate, deactivate, ideContext};
