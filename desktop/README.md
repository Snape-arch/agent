# ClawOS 桌面包

桌面壳与Web工作台使用同一应用源码。打包从 `clawos/` 复制运行文件，包含内置MT路由和可视化worker；React源码不进入运行包，前端发布资源来自统一构建。保留模块许可与MT来源说明。

## 构建

先按部署说明准备独立构建环境；当前脚本使用 `clawos/.venv`，不要为了安装PyInstaller而改动已验证的独立应用运行时。构建环境需要应用依赖与 `desktop/requirements-build.txt`。

```powershell
python clawos/scripts/project.py build-web
.\desktop\build_desktop.ps1
```

产物位于忽略的 `desktop/stage/`、`desktop/build/` 和 `dist/`。旧0.1.0安装器已移出源码版本管理；发布时重新构建并记录当次SHA256，不再要求为当前源码安装Git LFS。

运行包不包含前端依赖、测试、用户数据库、模型权重、凭据或运行日志。可选可视化适配器来自 `clawos/output/vision-libs/`，随包时放入内部模块的 `runtime-libs/`。用户数据仍位于 `%LOCALAPPDATA%\ClawOS`，安装位置为 `%LOCALAPPDATA%\Programs\ClawOS`。

## 验收范围

本机源码与payload检查不等于Windows干净机、系统重启或真实磁盘故障验收。新的安装器需要再运行 `clean_machine_acceptance.ps1 -Installer <本轮安装器>`；Windows Sandbox配置示例仍可使用。本轮没有把旧安装器测量当作迁移后新安装器结果，也没有取得代码签名认证。
