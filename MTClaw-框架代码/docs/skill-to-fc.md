# skill-to-fc 使用指南

`skill-to-fc` 用来把已有的 **script-backed skill** 转换成 MTClaw / Function Router 可加载的工具配置：

- 一条 OpenAI-compatible function 定义，写入 `~/.function-router/functions.jsonl`
- 一个同名 shell wrapper，写入 `~/.function-router/scripts/<function_name>.sh`

转换完成后，Claude、Codex、OpenClaw、OpenCode 等客户端只要接入 MTClaw / Function Router，就可以通过自然语言触发这些工具。

## 适用场景

适合转换这类 skill：

- skill 有 `SKILL.md`
- skill 的实际能力由 `scripts/` 下的 shell、Python、Node、Go、Rust 或其他本地命令实现
- 希望把它变成 Function Router 可路由的工具

不适合转换纯提示词型 skill。没有本地脚本入口的 skill，通常需要先补一个可执行脚本，再用 `skill-to-fc` 转换。

## 前置要求

先完成 MTClaw / Function Router 的基础安装：

```bash
pip install .
./scripts/install.sh
```

确认本地服务能启动：

```bash
./restart_all.sh
curl -s http://127.0.0.1:18790/health | jq .
```

如果 `health` 返回正常，说明后续写入 `~/.function-router/functions.jsonl` 和 `~/.function-router/scripts/` 的工具可以被 MTClaw 加载。

## 安装 skill-to-fc

`skill-to-fc` 本身是一个需要安装到你正在使用的 Agent 框架里的 skill。安装时请复制整个目录，而不是只复制 `SKILL.md`，因为转换过程依赖 `scripts/convert_skill_to_fc.py` 和 `references/`。

源目录：

```text
skills/skill-to-fc/
```

### Claude Code

把目录复制到 Claude Code 的用户 skills 目录：

```bash
mkdir -p ~/.claude/skills
cp -R skills/skill-to-fc ~/.claude/skills/skill-to-fc
```

重启 Claude Code 后，在对话里要求它使用这个 skill，例如：

```text
使用 skill-to-fc，把 /path/to/my-skill 转换成 MTClaw 可用的 Function Router 工具。
```

### Codex

如果你的 Codex 环境支持 Claude Skills / agent skills 兼容目录，把目录复制到 Codex 的 skills 目录中：

```bash
mkdir -p ~/.codex/skills
cp -R skills/skill-to-fc ~/.codex/skills/skill-to-fc
```

重启 Codex，然后让 Codex 读取并执行该 skill：

```text
请使用 skill-to-fc，把 /path/to/my-skill 转换成 Function Router runtime artifacts，并安装到 ~/.function-router。
```

如果你的 Codex 版本没有自动发现 skills，可以在任务提示中显式附上或引用：

```text
请按 skills/skill-to-fc/SKILL.md 的流程执行，把 /path/to/my-skill 转换成 MTClaw 可用配置。
```

### OpenClaw

如果 OpenClaw 使用本仓库作为工作区，通常不需要额外复制，直接让 agent 使用仓库内的 skill：

```text
请使用 skills/skill-to-fc，把 /path/to/my-skill 转成 Function Router 配置。
```

如果你希望作为全局 skill 安装，可复制到 OpenClaw 的 skills 目录或项目约定目录：

```bash
mkdir -p ~/.openclaw/skills
cp -R skills/skill-to-fc ~/.openclaw/skills/skill-to-fc
```

OpenClaw 接入 MTClaw / Function Router 时，建议同时安装 session bridge plugin：

```bash
openclaw plugins install clawhub:openclaw-session-bridge-plugin
```

### OpenCode / Opencode

如果 OpenCode / Opencode 支持本地 skills 目录，把目录复制过去：

```bash
mkdir -p ~/.opencode/skills
cp -R skills/skill-to-fc ~/.opencode/skills/skill-to-fc
```

重启 OpenCode / Opencode 后，在对话中指定：

```text
请使用 skill-to-fc，把 /path/to/my-skill 转换成 MTClaw Function Router 工具。
```

如果当前版本不支持自动加载 skills，也可以让它直接按仓库路径执行：

```text
请读取 skills/skill-to-fc/SKILL.md，并按其中 workflow 转换 /path/to/my-skill。
```

## 转换一个已有 skill

假设已有 skill 位于：

```text
/path/to/my-skill/
  SKILL.md
  scripts/
    my-tool.sh
```

在 Claude、Codex、OpenClaw 或 OpenCode 中发起任务：

```text
使用 skill-to-fc，把 /path/to/my-skill 转换成 MTClaw 可用的 Function Router 工具，并安装到当前用户的 ~/.function-router。
```

Agent 会做这些事：

1. 读取目标 skill 的 `SKILL.md`
2. 读取目标 skill 引用的脚本
3. 设计一个适合路由模型调用的 function schema
4. 编写一个 Function Router wrapper 脚本
5. 生成临时 artifacts 文件，例如 `/tmp/my-skill-fr-artifacts.json`
6. 调用安装脚本写入 runtime 配置

安装命令形式如下：

```bash
python skills/skill-to-fc/scripts/convert_skill_to_fc.py \
  --install-runtime-artifacts /tmp/my-skill-fr-artifacts.json
```

安装成功后会写入：

```text
~/.function-router/functions.jsonl
~/.function-router/scripts/<function_name>.sh
```

如果已有同名 function 或脚本，安装器会先创建备份：

```text
~/.function-router/functions.jsonl.bak-YYYYMMDD-HHMMSS
~/.function-router/scripts/<function_name>.sh.bak-YYYYMMDD-HHMMSS
```

## 转换后必须重启

Function Router 在启动时加载工具定义，所以转换安装完成后，需要重启完整服务栈：

```bash
./restart_all.sh
```

如果你只重启了 Agent 客户端，但没有执行 `restart_all.sh`，新工具通常不会生效。

## 验证是否生效

查看健康检查中的工具数量：

```bash
curl -s http://127.0.0.1:18790/health | jq .
```

查看 function 是否已经写入：

```bash
grep '"name":"<function_name>"' ~/.function-router/functions.jsonl
```

查看 wrapper 是否存在且可执行：

```bash
ls -l ~/.function-router/scripts/<function_name>.sh
```

然后在你的 Agent 客户端中用自然语言触发目标能力，例如：

```text
帮我执行刚才转换的那个工具，参数是……
```

如果工具被路由执行，可以查看工具历史：

```bash
curl -s "http://127.0.0.1:18790/v1/tool_history?limit=5" | jq .
```

## 自定义安装路径

默认安装到当前用户的 Function Router runtime：

```text
~/.function-router/functions.jsonl
~/.function-router/scripts/
```

如果要先安装到测试目录，可以指定路径：

```bash
python skills/skill-to-fc/scripts/convert_skill_to_fc.py \
  --install-runtime-artifacts /tmp/my-skill-fr-artifacts.json \
  --functions-jsonl /tmp/function-router/functions.jsonl \
  --scripts-dir /tmp/function-router/scripts
```

确认生成结果无误后，再安装到默认 runtime。

## 常见问题

### 安装后工具没有触发

先检查三件事：

1. 是否已经执行 `./restart_all.sh`
2. `~/.function-router/functions.jsonl` 中是否有目标 function
3. 路由模型是否支持 tool calling

也可以打开 debug logging 后观察路由决策，配置见 `docs/config.md`。

### Agent 说找不到 skill-to-fc

说明 skill 没有被当前框架加载。请确认复制的是完整目录：

```text
skill-to-fc/
  SKILL.md
  scripts/convert_skill_to_fc.py
  references/
```

然后重启 Claude、Codex、OpenClaw 或 OpenCode。

### 目标 skill 没有脚本

`skill-to-fc` 主要转换 script-backed skill。纯 prompt skill 需要先补一个本地脚本入口，否则 Function Router 没有可执行目标。

### 转换出来的参数不理想

让 Agent 重新检查目标脚本的真实参数，并调整 artifacts 中的 function schema。建议 schema 只暴露用户真正需要提供的业务参数，不要暴露脚本名、临时文件、内部命令行参数等实现细节。

### 需要回滚

安装器会打印备份文件路径。可以手动恢复：

```bash
cp ~/.function-router/functions.jsonl.bak-YYYYMMDD-HHMMSS ~/.function-router/functions.jsonl
cp ~/.function-router/scripts/<function_name>.sh.bak-YYYYMMDD-HHMMSS ~/.function-router/scripts/<function_name>.sh
./restart_all.sh
```
