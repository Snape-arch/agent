# 开发指南

使用锁定的应用Python运行环境，准备方式见[部署说明](../clawos/deployment/README.md)。下列命令中的 `python` 应指向该环境；不要把模型权重安装进源码仓库。

## 启动

Windows从仓库根运行 `start_clawos.bat`。`--check-runtime`仅检查/选择依赖环境；`--local`是显式本地模型配置，会探测既有模型服务，使用前按启动器提示准备端点。常规整理和测试不需要启动模型。

Linux可运行 `bash clawos/scripts/start_mtclaw_stack.sh`。它使用仓库内 `clawos/mtclaw/router/server.py`，不再查找旁边的MTClaw克隆。配置与密钥保持本机，不提交生成的 `mtclaw_runtime/`。

## 统一开发命令

```powershell
python clawos/scripts/project.py check
python clawos/scripts/project.py test core
python clawos/scripts/project.py test router
python clawos/scripts/project.py test visualization
python clawos/scripts/project.py test web
python clawos/scripts/project.py build-web
```

`test all`顺序执行四类检查，失败立即返回。核心测试沿用原隔离回归脚本；模块测试使用临时数据目录，不继承用户模型、数据库和代理配置。GPU、真实模型、多天并发及人工教学另验，不用模拟器替代。

前端依赖在 `clawos/web/` 使用现有 `packageManager` 与 `pnpm-lock.yaml` 固定安装：`corepack pnpm install --frozen-lockfile`。开发入口为Vite输出的 `/academy/vision/`，API代理到运行中的ClawOS 18790。发布只用统一构建命令，生成 `clawos/static/vision/`，旧发布资源暂存到忽略的output，HTML最后发布。

可视化数据适配器可用已有锁安装到 `clawos/output/vision-libs/`；独立worker读取该目录或随包的 `clawos/visualization/runtime-libs/`。它们不进入源码提交。SDK、模块测试与高级实验工具放在 `clawos/visualization/`，不另建一份前端或应用数据库。

## 修改与交付

1. 阅读根README、PROJECT_CONTEXT和相关模块文档。
2. 保留他人未提交改动，先核对分支与远程；当前用户已选择master开发，禁止强推。
3. 修改对应源码，运行相关测试；路径、启动、打包或模块边界变更要跑完整检查。
4. 更新简短交接，记录真实通过/失败及未验收项。历史验收报告不反向改写。

只提交源码、锁文件、必要构建资源和文档。tools、权重、凭据、数据库、node_modules、运行日志、缓存及旧安装器保持忽略。桌面包从同一个 `clawos/` 源码树组装，不再复制第二份MT或Vision项目。
