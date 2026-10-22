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
  const output = vscode.window.createOutputChannel("ClawOS Agent");
  context.subscriptions.push(output);

  async function openChangedFiles(result) {
    const attempts = result.attempts || [];
    const workflow = attempts.length ? attempts[attempts.length - 1].workflow || {} : result;
    const rounds = workflow.rounds || [];
    const paths = [...new Set(rounds.flatMap((round) =>
      (round.changes || round.files || []).map((item) =>
        typeof item === "string" ? item : item.path
      )
    ).filter(Boolean))];
    for (const relativePath of paths.slice(0, 20)) {
      const folders = vscode.workspace.workspaceFolders || [];
      if (!folders.length) break;
      const uri = vscode.Uri.joinPath(folders[0].uri, relativePath);
      try {
        await vscode.commands.executeCommand("git.openChange", uri);
      } catch (_error) {
        await vscode.window.showTextDocument(uri, {preview: false});
      }
    }
    return paths;
  }

  context.subscriptions.push(vscode.commands.registerCommand(
    "clawos.showLastChanges",
    async () => {
      const result = context.workspaceState.get("clawos.lastCodingResult");
      if (!result) {
        vscode.window.showInformationMessage("ClawOS has no applied coding result yet.");
        return;
      }
      const paths = await openChangedFiles(result);
      if (!paths.length) vscode.window.showInformationMessage("ClawOS result contains no changed files.");
    },
  ));

  context.subscriptions.push(vscode.commands.registerCommand(
    "clawos.rewindLastTask",
    async () => {
      const last = context.workspaceState.get("clawos.lastCodingResult");
      const checkpoint = last && (last.checkpoint ||
        ((last.attempts || []).at(-1)?.workflow || {}).checkpoint);
      if (!checkpoint) {
        vscode.window.showInformationMessage("ClawOS has no checkpoint to rewind.");
        return;
      }
      const decision = await vscode.window.showWarningMessage(
        "Restore the workspace to the last ClawOS checkpoint?",
        {modal: true},
        "Restore checkpoint",
      );
      if (decision !== "Restore checkpoint") return;
      const result = await post("/api/workspace/coding/rollback", {
        repo_path: ideContext().repo_path,
        checkpoint,
        actor: "vscode-extension",
        confirmed: true,
      });
      output.appendLine(JSON.stringify({event: "checkpoint_restored", result}));
      output.show(true);
      vscode.window.showInformationMessage("ClawOS checkpoint restored.");
    },
  ));

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
        let activeRunId = "";
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
          const run = await post("/api/agent-product/task-runs", {
            title: objective,
            session_id: sessionId,
            source: "vscode",
            surface: "vscode",
            actor_id: "vscode-extension",
            metadata: {requested_task_id: taskId},
          }, controller.signal);
          const runId = run.run_id;
          activeRunId = runId;
          await post(`/api/agent-product/task-runs/${runId}/transition`, {
            status: "running",
            actor_id: "vscode-extension",
            reason: "VS Code coding task started",
          }, controller.signal);
          const payload = {
            repo_path: ide.repo_path,
            objective,
            task_id: runId,
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
          output.appendLine(JSON.stringify({event: "proposal", run_id: runId, preview}));
          await post(`/api/agent-product/task-runs/${runId}/transition`, {
            status: "waiting_confirmation",
            actor_id: "vscode-extension",
            reason: "Proposal preview is waiting for user confirmation",
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
          if (decision !== "Apply and test" || token.isCancellationRequested) {
            await post(`/api/agent-product/task-runs/${runId}/transition`, {
              status: "canceled",
              actor_id: "vscode-extension",
              reason: token.isCancellationRequested
                ? "VS Code cancellation requested"
                : "User declined the proposed changes",
            });
            return;
          }
          progress.report({message: "Applying in checkpointed workflow"});
          const result = await post("/api/workspace/coding/autonomous", {
            ...payload,
            confirmed: true,
          }, controller.signal);
          await context.workspaceState.update("clawos.lastCodingResult", result);
          const paths = await openChangedFiles(result);
          const workflow = (result.attempts || []).at(-1)?.workflow || result;
          const checkpoint = workflow.checkpoint ? {
            uri: workflow.checkpoint,
            digest: result.proposal_digest || result.trajectory_digest || "workflow-checkpoint",
          } : {};
          await post(`/api/agent-product/task-runs/${runId}/transition`, {
            status: result.status === "passed" ? "succeeded" : "failed",
            actor_id: "vscode-extension",
            reason: `Coding workflow ${result.status || "completed"}; changed files: ${paths.length}`,
            checkpoint,
          }, controller.signal);
          output.appendLine(JSON.stringify({event: "completed", run_id: runId, result}));
          output.show(true);
          const resultDocument = await vscode.workspace.openTextDocument({
            content: JSON.stringify(result, null, 2),
            language: "json",
          });
          await vscode.window.showTextDocument(resultDocument, {preview: false});
        } catch (error) {
          if (controller.signal.aborted || token.isCancellationRequested) {
            if (activeRunId) {
              try {
                await post(`/api/agent-product/task-runs/${activeRunId}/transition`, {
                  status: "canceled",
                  actor_id: "vscode-extension",
                  reason: "VS Code cancellation requested",
                });
              } catch (transitionError) {
                output.appendLine(`Cancellation transition failed: ${transitionError.message || transitionError}`);
              }
            }
            vscode.window.showInformationMessage("ClawOS coding task cancelled.");
            return;
          }
          if (activeRunId) {
            try {
              await post(`/api/agent-product/task-runs/${activeRunId}/transition`, {
                status: "failed",
                actor_id: "vscode-extension",
                reason: String(error.message || error),
              });
            } catch (transitionError) {
              output.appendLine(`Failure transition failed: ${transitionError.message || transitionError}`);
            }
          }
          vscode.window.showErrorMessage(`ClawOS: ${error.message || error}`);
        }
      });
    },
  ));
}

function deactivate() {}

module.exports = {activate, deactivate, ideContext};
