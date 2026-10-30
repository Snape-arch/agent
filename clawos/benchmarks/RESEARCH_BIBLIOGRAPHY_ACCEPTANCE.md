# 论文引用与版本关系验收（2026-10-30）

## 交付与边界

研究订阅 → Crossref参考文献/显式版本关联、arXiv明确修订号 → 来源快照 → 冻结综述引用与版本网络 → 筛选、依据及MD/JSON导出已接通。

- DOI引用仅来自来源参考文献；缺DOI计入覆盖缺口，不猜标题。语料外DOI保留未解析节点，不抓取整个引用闭包。
- 保留is-preprint-of/has-preprint、is-version-of/has-version、is-identical-to，规范方向但保留原字段/索引/快照ID/SHA。arXiv自报DOI单列关联，不认证正式发表或同行评审。引用不代表支持、反对或方法继承；原主题候选继续人工复核。
- 版本只取明确字段/标识。已观察v1/v7建立观察顺序、标明中间5版未采集，不补造。旧记录可从明确的版本化来源标识恢复版本信息。
- 本人订阅论文可手动刷新Crossref DOI、arXiv最新或指定版本。共享采集锁/请求间隔、每用户每小时20次；响应必须匹配标识，写入前重验归属及租约。失败释放锁，只保存安全异常类型。不推进窗口水位、不重复通知、不改旧日报/综述，新报告纳入新快照。
- 每记录最多500参考文献/100版本关联；每篇最多20形态，全报告共享200形态/5000参考文献/1000关联，图最多1500节点/2000边。缺失、不完整及省略明确记录，界面每批40关系，支持引用/版本分类筛选。原全文/摘要预算继续生效。

## 验证

最终相关 **78/78，0失败/错误，10.424秒**：引用版本11、AI13、综述11、订阅27、论文8、数值证据8。覆盖来源关系与人工候选分离、真实/缺失版本、冻结旧报告、刷新水位/通知不变、失败释放锁、删除订阅后的迟到结果拒绝、跨用户/API校验、响应标识不符拒绝、共享元数据预算。Python AST、JS语法及diff通过。旧全项目绿灯/协作压测不替代本次验证。

本轮真实公开元数据采集18.473秒，6条记录：Crossref `10.1038/nature14539`、`10.1038/nature14236`；arXiv `1706.03762v1`、`1706.03762v7`；Crossref is-preprint-of筛选返回`10.1364/opticaopen.29459153.v1`及其声明目标`10.1364/oe.572415`。没有模型调用/PDF下载。

实际核对Deep learning → Human-level control through deep reinforcement learning的直接DOI引用、精确v1/v7、无伪造中间版本、来源预印本关系、所有边快照摘要与引用索引，5项通过。6形态、82节点、81边；77次引用指向语料外DOI、83条参考文献缺DOI、2条记录无参考文献元数据；本样本无预算省略。不把缺失当零引用，不认证领域全集或学术语义。

忽略证据目录`output/research-bibliography-live-20261030`。真实结果SHA256 `495f33bcf1c507a73a059b884db133eb442b7cc4962a02837d6444e8753be994`。最终源码以同6条捕获记录在新数据库回放，MD预算、缺失版本数和双端快照均通过；`final-code-audit.json`及`final-replay-b/overview-export.json`。9份相关源码/测试/脚本原始字节指纹集合（路径排序紧凑JSON再SHA256）`ffeab0e7d4374975f1ed72bbc0eebc041c3d8ceed2905a4e641eee0e397f52ad`。首个离线夹具因漏配必填方向被拒绝，保留final-replay；修正后使用final-replay-b，不算公开来源失败。

独立18929/独立DB使用真实捕获记录回放。浏览器核对历史报告、类型筛选、预印本关联、v1→v7/缺失5版提示与双端快照入口，截图`output/playwright/research-bibliography/source-graph.png`。刷新API由专项测试覆盖，本预览不声明浏览器实时刷新通过。预览在收尾时停止。此验收不等于多设备、屏幕阅读器或人工学术评审。

## 未完成与后续

旧arXiv窗口外修订仅提供显式最新/指定版本刷新，未自动全量跟踪/回填历史；未解析全文引文语境、支持/反对或自动认证方法继承。来源关系/参考文献依赖上游提交，缺少不代表不存在。规则依据：[arXiv API](https://github.com/arXiv/arxiv-docs/blob/develop/source/help/api/user-manual.md)、[Crossref关系筛选](https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/)、[预印本关联](https://www.crossref.org/documentation/schema-library/markup-guide-record-types/posted-content-includes-preprints/)。

第一阶段真实模型调用/中文综合质量仍按用户确认未验收。下一阶段做新增论文与旧综述的证据差异、版本化增量更新/通知，之后做真实多领域人工学术评审。

未重启生产/启动权重/操作tools，未重测48小时或恢复提醒。日常DB与原registry维持既有SHA，原脏改保留；只交相关源码/测试/Markdown，排除权重、凭据、DB、output与原registry脏改。
