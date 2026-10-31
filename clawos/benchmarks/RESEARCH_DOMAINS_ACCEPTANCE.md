# 代表文献、阅读链条与外部综述对照（2026-10-31）

## 交付与结论

三个具体AI方向各8篇初始论文，先冻结分类、阅读路径和助手初稿，再用外部综述定位遗漏，各补2篇，共30篇。站内研究订阅页新增按需加载的只读阅读包，包含分类、初稿、18项综述结构对照、补读理由、来源位置/哈希、3条作者明确表述关系及MD/JSON导出。查看/导出不创建订阅、不写日常文献库、不调用模型。独立库真实元数据回放完成每领域8→10篇的报告版本链，不能等同学术综述质量通过。

| 方向 | 初始入口 | 对照后补读 | 正式综述记录 |
| --- | --- | --- | --- |
| RAG | REALM、DPR、RAG、FiD、RETRO、HyDE、RAGAS、Self-RAG | kNN-LM、REST；补概率融合与检索式解码 | Zhao等，Data Science and Engineering，2026-01-02，DOI 10.1007/s41019-025-00335-5 |
| PEFT | Adapters、Prefix-Tuning、Prompt Tuning、BitFit、LoRA、IA³、AdaLoRA、QLoRA | UniPELT、SPoT；补混合适配与任务迁移 | Wang等，Artificial Intelligence Review，2025-05-03，DOI 10.1007/s10462-025-11236-4 |
| 扩散模型 | 原始扩散、NCSN、DDPM、DDIM、SDE、LDM、DPM-Solver、ControlNet | Improved DDPM、D3PM；补训练似然与离散结构 | Yang等，ACM Computing Surveys，2023-11-09，DOI 10.1145/3626235 |

阅读报告见 [RAG](research_domains/rag.md)、[PEFT](research_domains/peft.md)、[扩散模型](research_domains/diffusion.md)。正式DOI记录均由精确Crossref查询核对标题、刊物和日期；前两份使用出版商开放全文，扩散使用作者arXiv **2209.00796v15**修订全文，其2025年修订内容不冒充2023年期刊原版或新增内容均经同行评审。

## 初稿与验证边界

初稿冻结时间2026-10-31T06:29:50.000257Z；UTF-8/LF文件SHA256 `4eeaac94f0ad15db7ec3bb21b631654aa4ba2ac56820061212d1ba7762d4e2d6`。提交保留research_domain_initial.json，运行时只归一化Git可能转换的CRLF，实际内容变化拒绝读取。最终分类、阅读路径和初稿不回填修改，新增6篇和对照判断单列。

选综述时已见标题、摘要和搜索片段，原摘要核对与检索存在交叉；这是助手有先验的结构对照，**不是盲测**。18项覆盖判断由助手拟定，分“有代表入口、部分覆盖、初稿遗漏、初稿范围外”，不是专家金标准、语义准确率或领域召回率。综述自身不能认证初稿正确。期刊发表身份不依赖不稳定的引用数、影响因子或声誉打分。

论文正文未作为本轮全文证据绑定。论文解释主要依据作者摘要；综述对照使用可读全文的相关分节。阅读顺序、并行路线、问题演进不写成confirmed继承。Prefix→Prompt、Prompt→SPoT、DDPM→DDIM三条额外关系只标作者对简化/基于/相同训练过程的明确表述，带目标版本原文，不替代独立考证或复现。原始摘要和全文留在忽略output，提交包仅元数据、助手文字、每来源不超过25词的短引文及哈希。

## 真实来源与保留的失败

- 新采24篇arXiv页面及6篇补充，显式版本、标题和方法片段逐项定位；3份综述可读页面及3份Crossref期刊记录均捕获核对。
- output/research-domain-primary-20261031最初解析器误用了通用description元数据，不能当摘要；修复为blockquote.abstract后，在-b目录对原始HTML校验SHA并离线重解析，旧证据不覆盖。最终30篇均由正确摘要校验，单测防止导航说明冒充摘要。
- 两次综述采集因严格重定向白名单拒绝Springer官方匿名跳转，保留原失败目录。仅补充观察到的官方域名后，-c目录3/3可读；无Cookie jar、用户凭据或账户登录。未绕过付费墙。
- 真实ControlNet摘要暴露旧clean将`<50k … >1m`误作HTML的证据损失。修复为要求合法标签名，回归覆盖数值比较与JATS标签。旧数据库及冻结报告不自动改写；未来重新采集/刷新才能产生保留比较符的新快照。
- 受限终端的首次独立测试阻塞，无通过结论；按命令和创建时间核对后只终止该测试子进程。主机侧最终测试使用隔离临时库。此前日期比较未命中的清理未操作其他进程，随后按UTC时间值完成。

## 最终验证

- **134/134，0失败、0错误、0跳过，15.391秒**：领域阅读包12、边界15、评审13、更新16、引用版本11、AI13、综述11、订阅27、论文8、数值8。覆盖引用/阶段隔离、初稿篡改、CRLF、作者关系不能晋升或换绑、原文哈希、未知ID、身份验证及只读API不接触用户存储。
- 7个Python文件AST、JS语法与git diff --check通过。
- 最终output/research-domain-acceptance-20261031-c：3个独立订阅逐一8→10篇，每份新增2篇；115条提取片段（RAG38/PEFT40/扩散37）位置核对通过；旧版不变、跨owner读取拒绝、语义关系候选未自动确认。输入是本轮新采公开资料，执行为离线回放；61秒受控调度时钟不当真实等待或长期负载。
- 独立18934预览真实浏览器：三目录、分类、初稿、遗漏对照、来源展开、修订版说明和作者表述关系；实际Markdown下载到浏览器返回路径，读取确认为RAG完整报告。截图位于output/playwright/research-domains/rag-survey-comparison.png及declared-relation.png。预览PID82304/创建2026-10-31T06:40:37.906755Z按脚本、目录、端口核对后停止，测试页已关闭。
- 没有生产重启；UI/API新入口需应用下次正常启动载入。实际多设备、屏幕阅读器、移动端、浏览器长文档内存和长期采集不在本轮结论中。

真实本地模型调用0次，独立真人评审0次，semantic_validation_passed=false。未运行领域论文实验，不发布RAG、微调或生成质量排名，不宣称该30篇覆盖2026前沿全集。不恢复已删除的压测提醒，不启动权重或重测长压测。

## 复现与源码

固定采集脚本research_domain_capture.py支持primary/supplements/surveys/publications四阶段；对已经带version的包使用精确版本URL，每次新建output目录，HTTPS来源白名单、3.1秒间隔、20秒超时、4MB上限。primary可用--replay对已有HTML按记录SHA重解析。build脚本先验证初稿物料不变和每份捕获哈希，再生成短引文包。源站拒绝/片段变化均失败保留，不虚构通过。

```powershell
$env:PYTHONPATH='clawos;clawos/tests'
$env:CLAWOS_SKIP_LOCAL_ENV='1'
& <app-python> -X utf8 clawos/scripts/research_domain_acceptance.py `
  --primary clawos/output/research-domain-primary-20261031-b `
  --supplements clawos/output/research-domain-supplements-20261031 `
  --output <全新独立output目录>
```

12文件源码/数据集合SHA256（各文件UTF-8/LF摘要的排序path→sha256 JSON再求SHA256）：`f66a1a832c063558bb8cb154d79060080ef973a20421b9295211a52ff16900e7`。细目保存在最终-c/source-fingerprint.json；包含7个Python文件、HTML/JS/CSS及2份JSON，排除本验收文档和生成阅读报告。

日常memoryos.db SHA256 `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`、原registry脏改SHA256 `a72423d78ff1e7d67c646fcd7debf1824ce9e88767b0034455ff1fefcc5a23d4`前后不变。仅提交相关源码、短引文数据、测试和文档，排除tools、模型权重、凭据、DB、output及原registry改动。master正常推送，不强推。

下一步：把阅读包转为可编辑的领域研究计划、按缺口绑定授权全文与实验；待用户提供模型/评审条件后，再做真实模型概括、逐主张独立评审及实验效果验证。此次不以机械通过替代这些结论。
