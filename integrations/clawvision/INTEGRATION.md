# ClawVision in ClawOS

This is a source snapshot of the user's ClawVision working tree, based on
`65afd74a0fc170a32340a36594afd42207c1b5a9`, including newer uncommitted source.
`SOURCE_SNAPSHOT.json` preserves original file fingerprints before integration
changes. The original project and its Git history are untouched.

The source project declares Apache-2.0 in pyproject.toml; original attribution
and source notices are retained. No model weights, original databases, artifacts,
credentials, node_modules or Git metadata are imported.

ClawOS serves the rebuilt React app at `/academy/vision/` and gateways its API
under `/api/vision/service/`. The experiment backend runs in a separately owned
loopback child process with its own data directory. Only ClawOS's direct local
owner can operate this first integration. Document collaborator permissions do
not grant experiment or training access. Upstream standalone authentication and
tenant APIs remain in the source, but are not presented as integrated team SSO.

ClawOS credentials/environment are not inherited, models are not automatically
loaded, and the service starts only on explicit request. Built-in simulator and
local deterministic geometry are distinct from real training/model inference.

Integration changes: API/resource namespace helpers, ClawOS launch gate and
navigation, shared warm-paper color tokens, typography/layout, an authenticated
loopback worker entry, runtime supervision and bounded streaming gateway.
Standalone source mode retains the original AuthGate; use
`node node_modules/vite/bin/vite.js --base / --host 127.0.0.1` with a separately
configured standalone backend. The default production build targets ClawOS.

Install the tested optional data adapters into an isolated directory with:

```powershell
<app-python> -m pip install --only-binary=:all: --target clawos/output/vision-libs -r integrations/clawvision/requirements-integration.lock.txt
```

They are used only in the child experiment service. The desktop build copies
them into that service's separate `runtime-libs`, without merging them into the
main ClawOS Python environment. Neither directory is committed. GPU/ML/CAD
extras remain optional and require their own installation and validation.

Build the frontend with `node clawos/scripts/build_vision_frontend.mjs`; its
staging, cache and previous compiled assets stay in output. The actual product
assets and third-party notices are published to `clawos/static/vision`.

The integrated data page loads saved datasets instead of silently choosing
sample rows. Dashboard saves are private; reopening uses a saved visualization
ID. Charts describe the size of their preview rather than implying a whole
dataset scan. Built-in examples require explicit selection and remain labeled.
# 第二阶段：课程机制实验（2026-11-01）

从 `/academy/vision/?lesson=rag#teaching` 直接进入；LoRA课程用 `lesson=finetune`，扩散用 `lesson=diffusion`。此入口不需要启动实验子服务或模型。文献包与课程页均有入口，课程可回看对应实验与反思。

三个有界CPU模板分别执行合成短文的来源过滤、六维低秩适配梯度训练、一维解析score的概率流ODE积分。它们是可复跑的机制教学，不是大模型/原论文指标复现。实验保存在ClawOS `DATA_DIR/vision/teaching.sqlite`，与原Vision训练Runs分开显示，避免混用指标类型。

可选教材知识节点会冻结修订/图谱版本及原文来源，版本变化拒绝保存。反思追加而不覆盖，不写掌握度或真实教学效果。仍仅本机所有者访问，不继承文档协作授权。JSON导出可用仓库 `clawos/scripts/vision_teaching_replay.py` 复跑，完整范围见 `clawos/benchmarks/CLAWVISION_TEACHING_ACCEPTANCE.md`。
