# Agent / ClawOS Workspace

本仓库是一个基于 ClawOS + MTClaw 思路的本地 Agent 项目，目标是从“聊天 + 工具调用 Demo”升级为可追踪、可恢复、可审计的个人智能体工作台。

如果你是下一次接手本仓库的 Codex，请先读：

1. `PROJECT_CONTEXT.md` - 当前项目状态、最近修改、下一步计划。
2. `clawos/README.md` - ClawOS 子项目启动方式和模块说明。
3. `clawos/ROADMAP.md` - 工程路线图。
4. `clawos/ENTERPRISE_READINESS.md` - 企业级差距评估。
5. `clawos/MTCLAW_INTEGRATION.md` - MTClaw 集成说明。

本仓库也提供 repo-local skills，方便双人协作时让不同 Codex 使用同一套流程：

- `.agents/skills/clawos-project-onboarding/SKILL.md`
- `.agents/skills/clawos-git-collaboration/SKILL.md`
- `.agents/skills/clawos-handoff-update/SKILL.md`

## 当前重点

短期目标是先把后端闭环做稳：

- 模型 provider 抽象和本地 `.env` 配置。
- MTClaw adapter 和 fallback。
- MemoryOS 长期记忆。
- Reflection 反思卡和经验沉淀。
- Task / Step / Event 持久化运行时。
- 前端工作台逐步从普通聊天页升级为任务控制台。

## Windows 本地运行

```powershell
cd D:\Projects\agent
.\start_clawos.bat
```

或手动运行：

```powershell
cd D:\Projects\agent\clawos
.\.venv\Scripts\python.exe clawos_server.py --host 127.0.0.1 --port 18790
```

浏览器打开：

```text
http://127.0.0.1:18790
```

## 本地配置

真实密钥只放在：

```text
clawos/.env
```

该文件已被 `.gitignore` 忽略，不要提交。示例配置看：

```text
clawos/.env.example
```

## 测试

推荐使用项目虚拟环境运行：

```powershell
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

注意：部分测试会触发 MTClaw / FastAPI 的 `on_event` deprecation warning，只要最终 `OK` 即可。

## 协作约定

- 每次做完一个开发块，都更新 `PROJECT_CONTEXT.md`。
- 每次开始工作，优先使用 `clawos-project-onboarding`。
- 涉及 GitHub 同步、合并、推送前，使用 `clawos-git-collaboration`。
- 完成开发块并准备交给另一人时，使用 `clawos-handoff-update`。
- 不要把 API Key、真实密钥、本地 `.env` 提交进仓库。
- 修改前先看 `PROJECT_CONTEXT.md`，避免重复扫全仓库。
- 大功能优先写测试，再改实现。
- 当前项目还不是企业级交付版本，任何“已完成工业级”之类表述都要有测试和验收证据。
