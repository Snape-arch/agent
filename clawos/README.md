# ClawOS — 自进化个人智能体操作系统

A self-evolving personal AI agent operating system based on the observe-plan-execute-reflect-memory-improve loop.

## 系统要求

- Python 3.10+
- 操作系统：Windows 10/11（当前支持），macOS/Linux 需调整路径格式

## 快速开始

Windows 启动器优先使用项目 `.venv`；也可设置 `CLAWOS_PYTHON` 为已准备好的 Python 可执行文件绝对路径。`start_clawos.bat --local` 会跳过项目 `.env`，并在启动前检查 Chroma、sentence-transformers 和 Torch。依赖不齐时明确退出，避免把轻量检索降级当成本地嵌入就绪；完整模型兼容性仍以实际加载为准。

`GET /api/runtime/release` 提供进程实例、启动提交、启动/当前源码摘要和 `restart_required`。`GET /health` 的 `core_ready` 还要求数据库可访问、工作区服务初始化、向量一致且未降级；固定 `status: ok` 仅作存活信息。模型端点可达性另用 `/api/model/health?probe=true` 核验。指纹只覆盖明确列出的源码和页面文件，不能证明所有延迟导入模块或外部依赖版本。

恢复包现在包含已注册下载产物和任务检查点文件。`clawos/scripts/p0_recovery_acceptance.py` 可在独立进程和合成数据中验证六类持久化链路；`recovery_drill.py` 对指定数据库做只读快照和隔离恢复，默认重建离线向量，实际 Chroma/嵌入恢复须显式传入 `--vector-config`。它们都不认证任意代码任务续跑或模型语义质量。范围、失败记录和剩余门槛见 [P0 运行与恢复验收](benchmarks/P0_RUNTIME_RECOVERY_ACCEPTANCE.md)。

Windows 编码任务可部署独立的 Python 标准库运行时。从仓库根目录执行 `clawos/.venv/Scripts/python.exe clawos/scripts/sandbox_runtime.py setup --confirmed`，之后用 `status` 核验、`quarantine` 查看未确认收尾的任务。未指定运行时/profile环境变量时，编码服务会自动发现并校验该部署；损坏或未知清理状态拒绝执行。当前仅覆盖 Python 标准库与调用者退出后监督者存活的收尾场景，仍非生产就绪。部署与验收详见 [默认运行时与监督验收](benchmarks/SANDBOX_RUNTIME_SUPERVISION_ACCEPTANCE.md)。

### 1. 克隆或复制项目

将本目录完整复制到目标机器。

### 2. 安装依赖

`ash
cd clawos
pip install -r requirements.txt
`

### 3. 配置环境变量

ClawOS 通过 config.json 配置文件读取环境变量。首次使用需要设置 API Key：

`ash
# Windows (CMD)
set DEEPSEEK_API_KEY=sk-your-api-key-here

# Windows (PowerShell)
="sk-your-api-key-here"
`

可选环境变量：
| 变量 | 说明 | 默认值 |
|------|------|--------|
| DEEPSEEK_API_KEY | DeepSeek API 密钥 | **必填** |
| DEEPSEEK_BASE_URL | API 端点地址 | https://api.deepseek.com/v1 |
| DEEPSEEK_MODEL | 模型名称 | deepseek-chat |
| CLAWOS_MEMORY_DB | MemoryOS SQLite 数据库路径 | clawos/memoryos.db |

真实模型联调可运行：

```powershell
$env:MODEL_API_KEY="your-key"
python scripts/provider_smoke.py
```

该脚本覆盖基础对话、Function Calling 和 Reflection JSON，不会输出 API Key。

## MTClaw 比赛模式

ClawOS 已通过 OpenAI-compatible Provider 契约真实接入本地 MTClaw Function Router。
MTT AIBOOK Linux 环境可运行：

```bash
export MODEL_API_KEY="your-key"
bash scripts/start_mtclaw_stack.sh
```

完整代码证据、Trace 验证和低风险工具清单见
[`MTCLAW_INTEGRATION.md`](MTCLAW_INTEGRATION.md)。

> 如果使用本地模型（如 Qwen-7B + vLLM），可将 DEEPSEEK_BASE_URL 指向本地端点。

### 4. 启动服务器

**方法一：双击启动脚本**

`ash
start_clawos.bat
`

首次运行会自动安装 Python 依赖。

**方法二：手动启动**

`ash
cd clawos
python clawos_server.py --host 127.0.0.1 --port 18790
`

### 5. 访问界面

打开浏览器访问：http://127.0.0.1:18790

## 项目结构

`
clawos/
├── clawos_server.py      # 主服务器（FastAPI）
├── config.json            # 配置文件（支持环境变量替换）
├── functions.jsonl        # 工具定义（LLM Function Calling）
├── requirements.txt       # Python 依赖
├── static/
│   └── index.html         # 前端界面（ChatGPT 风格）
├── scripts/
│   └── tool_runner.py     # 38 个本地工具
├── memoryos/
│   ├── memory_store.py    # SQLite 持久化存储
│   ├── context_builder.py # 上下文构建（注入记忆）
│   └── services/
│       ├── ingestion.py   # 对话→记忆自动提取
│       ├── retrieval.py   # 混合检索（关键词+BM25+向量）
│       ├── vector_store.py# 向量语义搜索（纯Python，无外部依赖）
│       └── evaluation.py  # 记忆质量评估
├── skills/
│   ├── skill_registry.py  # 技能固化引擎
│   └── skill_registry.jsonl # 预置技能（4大场景）
├── reflection/
│   ├── engine.py          # 反思引擎
│   ├── perception.py      # 执行轨迹感知
│   ├── analyzer.py        # 根因分析（规则+LLM双模式）
│   ├── memory_writer.py   # 反思→记忆写入
│   └── learning_loop.py   # 持续学习循环
└── notes/                 # 笔记存储目录（自动创建）
`

## 核心功能

### MemoryOS（五维记忆系统）
- **Profile Memory** — 用户画像（专业、兴趣、研究方向）
- **Preference Memory** — 用户偏好（代码风格、PPT风格、沟通方式）
- **Project Memory** — 项目追踪（目标、进度、团队）
- **Experience Memory** — 经验案例（成功/失败/部分成功，含向量语义搜索）
- **Skill Memory** — 固化工作流（JSONL + 自动生成 replay 脚本）

### Reflection Engine（反思学习引擎）
- 工具执行后自动反思
- 规则分析 + LLM 深度分析双模式
- 总结经验存入 MemoryOS，形成持续进化闭环

### Skill Registry（技能固化）
- 用户演示 → 固化 Skill → 毫秒级本地执行
- 跨步骤参数引用（$step_N.field）
- 预置 4 个场景技能：科研、竞赛、开发、办公

### 38 个内置工具
文件操作、代码分析、搜索、笔记、待办、定时器、项目管理等

## 端口配置

默认端口 18790，可通过命令行参数修改：
`ash
python clawos_server.py --host 127.0.0.1 --port 8080
`

## 本地化推理（可选）

如需完全离线运行，将 config.json 中的 DEEPSEEK_BASE_URL 改为本地端点：

`json
{
  "routing": {
    "base_url": "http://localhost:8000/v1",
    "model": "Qwen/Qwen2.5-7B-Instruct"
  }
}
`

支持任何兼容 OpenAI API 格式的推理框架（vLLM、Ollama、llama.cpp 等）。

## 许可

MIT License
