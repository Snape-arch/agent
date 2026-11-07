# 内置MT路由

源码位于 `clawos/mtclaw/router/`，与Adapter、安全工具桥和运行配置生成器同属ClawOS模块。原框架已采用的服务实现、内置工具定义与契约测试保留；独立上游安装/卸载脚本、演示视频、桌面控制样例和重复介绍已移除。

```text
ClawOS -> MTClawAdapter -> 内置Function Router
       -> 安全工具包装器 -> Tool History -> 请求级Trace -> Reflection
```

默认回环18791。生成的ClawOS路由配置关闭不受限内置工具；桥接工具按既有Schema、参数、动作和场景策略进一步收窄。写文件、任意命令等行为不会因归并获得额外权限。会话、请求编号、真实工具观察与历史过滤契约不变。

Windows、Linux和桌面包均引用同一实现。生成配置在本机 `clawos/mtclaw_runtime/`，不提交、不在说明中输出密钥。错误不能静默充当已经过真实路由的成功证据。

上游MIT许可保留在 `clawos/mtclaw/LICENSE`，历史来源和本地修改见同目录 `UPSTREAM.md`。原快照缺少可核验的确切上游URL/SHA；该来源缺口继续保留，不能通过重新整理文件夹消除或编造。

验证入口：`python clawos/scripts/project.py test router`；主应用Adapter和请求隔离回归属于 `test core`。真实模型、国产硬件和路由质量的证据边界仍以相应冻结验收记录为准。
