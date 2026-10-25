# P0 deployment, business persistence and recovery faults (2026-10-25)

## 当前交付：真实索引恢复及公式 PDF（2026-10-25）

最终终局：源码 **58cea8ae6948b2414dd419c62292a836ebd6b354** 的独立141依赖应用运行时本地冻结全量 **1086/1086，0跳过/失败/错误**；四组313/198/211/364项不重不漏，耗时574.156/160.406/130.203/859.252秒，整轮862.828秒。461个源码/依赖/基准/CLI夹具指纹及HEAD稳定，日常DB未变，原registry字节恢复。证据 `clawos/output/p0-math-final-20261025/{full-result,full-source-audit,verified-final-summary}.json`。同源码[GitHub运行40175858412](https://github.com/Snape-arch/agent/actions/runs/40175858412)四个Windows分片及最终deterministic-tests全部completed/success，逐个head_sha核对一致。首轮本地/云端失败继续保留；最终收尾只改Markdown并使用[skip ci]，不把跳过源码测试当成通过。

真实索引恢复与常见PDF公式交付两项已取得明确证据；最终向量实现摘要与773清零轮一致。P0整体仍不能标为全部完成：受阻浏览器、真实教师/学生学习效果与独立语义评测、屏幕阅读器/可访问数学语义、多天多人负载、用户保留的物理OS/磁盘故障、275项无可信原件，以及生产完整隔离认证仍未通过。production_sandbox_ready=false；未重启生产，不提交tools/权重/凭据/DB/output及原registry脏改。

本轮完整门禁首轮保留失败：源码bcb3342的本地1084项实际执行完毕、0跳过，只有TODO扫描超4秒失败（6348.166ms），source/HEAD/日常DB稳定、原registry恢复；云端40174508451三组成功、组3的CLI文本格式测试因重复会议工具用例4387.740/3047.444ms超过原3000ms失败。两者根因和范围不同，不混为公式渲染失败，也不借其他绿灯覆盖。

TODO默认候选枚举原来遍历output/依赖/备份，现按源码统计范围排除这些目录及权重目录，大小写无关，不跟随目录链接，显式exclude_dirs仍可自定义；2/2回归含Windows真实junction边界。CLI输出格式/计数测试改用两个真实快速calc工具的显式夹具，仍各3000ms；原competition-frozen-v1会议预算、完整会议业务用例和失败退出码检查一字未改，不声称已修复所有会议性能波动。专项模型CLI11/11（4.099秒）、原冻结基准7/7（6.139秒）通过，最终新源码仍须再跑完整门禁。

真实索引恢复已于源码 a3b88ceb23f490703b306ad85957cbc25f81bd5e 上通过，GitHub 40113186441 四分片/最终门禁均成功。三篇真实PDF的隔离测试数据库将773条积压清零，1059.828秒，1653个向量ID/版本与权威投影一致，无fallback、错误为0、正常退出、端口释放，原DB和registry摘要保持；证据output/p0-source-quality-20261023/index-resume-a3b88ce/report.json。它是API/应用进程索引验收，不是浏览器、多设备、屏幕阅读器、物理重启或多天负载。

本轮新增真正的Mathtext公式图片，支持常见行内/多行公式、分数/根号/上下标；原始Markdown保留。不支持的命令/超限表达式保持原式并显示核查提示；代码/货币不当公式，不调用外部TeX。含公式报告选择ReportLab渲染；修正标题与证据段的分页，避免标题孤立于页尾。不是完整LaTeX兼容，也未认证PDF/UA：公式图像仍需进一步提供可访问数学语义。

应用依赖从135增至141项，只新增6项Mathtext依赖，所有旧版本保持；wheel摘要/来源已锁定，新独立运行时windows-py312-1236dc16430a-0cf6cd54已通过pip check、二进制/Mathtext导入及独立性验证。没有向旧运行时或系统Python安装包，没有重启生产。专项Mathtext4/4（0.708秒）、部署8/8（0.551秒）、工作区19/19（11.987秒）先通过，最后分页增量后另跑终版专项/全量，结果以收尾回执为准。

三份原有真实模型报告重导出仍4/4/5页，LoRA嵌入9个公式图像，三个Markdown摘要均不变；13页全量渲染总览并细看LoRA1至3页与BERT2至3页，未观察到公式重叠/截断，BERT综合判断标题已随正文移到第3页。证据output/p0-math-20261025/exports。此前近似文本公式方案未提交，已换为真正图片渲染；三次临时回归失败与锁生成脚本编码/包名规范化错误均保留在output，不冒充通过。

纠正旧计时解读：上一失败续跑报告的wall=29010.922秒、progress秒数16021.5存在明显长空档，不能说是20分钟连续CPU负载，也不能据此单独认定CPU吞吐根因；批次16/32的1.730/0.543秒只是先后单次短文本测量，存在预热影响，不是受控提速证明。新773清零轮的真实完整性才是当前验收依据。

P0仍缺：浏览器工具策略拒绝而未绕过；用户明确保留物理OS重启/磁盘故障；275历史原件无可信来源不删不盲绑；真实教师/学习效果、独立语义评测、屏幕阅读器与多天多人负载及生产完整隔离仍未认证。源码提交后须核对新SHA的完整门禁，不借旧绿；tools/权重/凭据/DB/output及原registry脏改继续排除。


## 当前开发：索引状态首次创建与真实进程续跑（2026-10-24）

最新源码 `a3b88ceb23f490703b306ad85957cbc25f81bd5e` 的真实索引续跑已通过：隔离三篇真实 PDF 数据根 `output/real-paper-quality/49d72bc10e9a47fdbd5a35e6637b55cf`，初始待处理 773，CPU Qwen3 嵌入耗时 **1059.828 秒**降至 `ready/pending=0/failed=0`；health `consistent=true`、无 fallback，预期与实际向量均 **1653**，ID/版本一致，应用正常收尾且端口释放，日常 DB/registry/source 均未变。该轮是 API/本地应用的真实来源长索引验收，不是浏览器、多设备、屏幕阅读器、OS 重启或多天多人负载验收。

最终收尾：最新提交 `7e1135581fabc9a9ba9c4d00b57d3d546bf57fd1` 已推送 master，GitHub Actions 运行 `40109902117` 的四个 Windows 分片与 `deterministic-tests` 全部 completed/success；`bcb334f` 运行因后续提交触发并发取消，不计通过。当前本地 `HEAD...origin/master=0/0`，仅保留原始 `clawos/skills/skill_registry.jsonl` 脏改；日常 DB SHA256 `8167052e0c203036AD74BB1409CE74BD9CFAEF585244865848EA5BE7B2A8C543`、原 registry SHA256 `a72423d78ff1e7d67c646fcd7debf1824ce9e88767b0034455ff1fefcc5a23d4` 未变。

真实索引续跑仍未通过：第一轮由 1813 待处理降到 933 后 HTTP 连接断开；修正驱动后第二轮由 917 降到 781，20 分钟预算耗尽，应用正常收尾，事件未丢失且失败数为 0。CPU Qwen 嵌入吞吐仍是剩余瓶颈；批次已从 8 提升到 32，但未再虚构清零或向量全量一致。CUDA 尝试因独立运行时不可用而明确失败，未静默降级。下次应在独立机器/GPU 或更长窗口继续，并记录最终向量 ID/版本完整性。

报告 PDF 仅抽查 6/13 页：中英文可读、无观察到的重叠/截断；LoRA 页面仍含原始 `$...$` 公式标记，因此公式排版与 PDF/UA、屏幕阅读器、浏览器验收仍未通过。浏览器工具仍受策略拒绝；真实 OS 重启/磁盘故障由用户保留未验收；275 项历史原件无可信备份；语义蕴含、教师校准、真实学习效果和多天负载仍未验证。

GitHub 对提交 `5d9af15` 的唯一失败已定位为既有跨进程 CAS 在 Windows `os.replace` 瞬时 `PermissionError`（公开 job 注释，`test_cross_process_cas_has_one_winner`）；本机同测试此前通过。已增加 8 次递增退避重试和瞬时拒绝专项，当前本机文件/历史回归 **21/21** 通过；下一轮云端必须重新核对，不能借用旧红叉或旧绿灯。

同一轮本机回归又暴露 artifact registry 并发写入的同类替换竞态，已在 `ArtifactDeliveryService._write` 增加相同有限重试；修复后文件/历史回归仍为 **21/21**。因此 9b3f6ea 的云端结果不作为最终通过，需以包含两条替换路径的新提交为准。

针对真实 CPU PDF 索引续跑吞吐，后台 worker 默认批次由 8 提升到 32，仍异步执行且保持失败不确认/可恢复语义；worker 回归 **2/2** 通过。该优化尚未有新的真实长索引终局，不能把吞吐改善当作索引完整性通过。

本地嵌入基准显示同一 32 条短文本从 batch_size=16 的 1.730 秒降到 batch_size=32 的 0.543 秒；已将 `SentenceTransformerEncoder` 的批次设为可配置 `CLAWOS_EMBEDDING_BATCH_SIZE`，默认 32、上限 128，新增向量回归后为 **7/7**。实际长 PDF 仍须独立轮验证，内存压力未在生产环境认证。

上轮源码 b706b5841bd24302d6082f1206c5116cd03e2785 的GitHub运行39961159540四分片及deterministic-tests均success。它不覆盖下述最后增量；旧失败仍保留。

旧真实PDF测试根在应用重启时发现知识事件2056条、待1976条而索引状态表为空；CPU续跑221.719秒超启动预算并强制结束自有进程，不算恢复成功。增量投影原来仅UPDATE已有状态，现改为UPSERT创建带索引模式/嵌入指纹的状态，保留既有全量水位；新增回归阻止无谓重建，outbox专项6/6（1.522秒）。不直接补写旧失败DB状态，也不以新轮覆盖原失败。

新夹具 `output/real-paper-quality/49d72bc10e9a47fdbd5a35e6637b55cf` 用同三篇完整原始PDF，仅上传/原件摘要验收、实际生成模型0调用，不能当新模型报告质量轮。三篇202上传7.359/14.079/46.360秒；结束后1821条事件、1813待处理，状态行真实存在。新进程CPU续跑过程中HTTP已响应且待处理降至1637；驱动误将core_ready=false（索引确实未齐）视为未启动，已通过自有停止文件干净结束并保留该驱动误判记录，改为分开检验HTTP/DB可用和最终索引完整。最终续跑与最新源码全量/云端门禁尚待终局，不提前标绿。

此前自动审批额度耗尽导致新建环境操作未执行，停顿不计成功运行。仍按用户授权master提交推送，原registry/日常DB摘要保持，tools/权重/凭据/DB/output排除。浏览器工具策略拒绝、真实OS重启/磁盘故障（用户明确保留）、275缺失原件与生产完整隔离认证等缺口不变，P0未整体完成。


## 当前开发：真实论文报告与持久向量索引（2026-10-23）

继续master。新增固定公开Transformer/BERT/LoRA原始PDF、SHA256与六项预设事实的实际完整应用/本地Qwen3.5-9B验收入口。末轮 `clawos/output/real-paper-quality/125f69933e0e4ea59ba32278b7bbd14a/report.json` 三篇均通过、210.422秒：提供方成功且model_assisted、原始下载摘要、引用片段绑定、6/6预设事实通过；上传202分别7.500/11.812/47.078秒。伪造9999.12345%的本地归一化负向控制通过，但不是模型拒答实验。选定公开已知材料非独立盲测，也不证明语义蕴含、教师校准、真人效果、浏览器或长期负载。该轮源码指纹留档；其后仅补数字极小指数不能下溢为0的范围约束，并专项8/8复验，最终源码仍须新的完整门禁。

大文档先解析可阅读、SQLite outbox后台小批投影；有状态/失败重试接口和独立界面提示。批量合并重复事件、投影互斥、编码不持SQLite写锁、部分写入不确认并幂等重放；全载入仅确认开始前水位，防止吞掉期间新事件。冷索引缺失/模式变化的全量重建仍可能同步耗时，CPU吞吐未认证。末轮报告结束仍待1984条事件（进程关闭后1976），明确index_completion_verified=false。另行新应用进程CPU续跑验收中；CUDA尝试因独立运行时torch无可用CUDA启动失败3.281秒，未静默降级，失败留在output/p0-source-quality-20261023/index-resume。

模型输入只携带预算内原文片段、排除字形/几何对象并披露非全文覆盖；8MiB导出限制保留，完整元数据仍在原DB，通过快照摘要/长度引用避免复制巨大版面对象。完整JSON合同校验，缺失引用和所引片段不含的阿拉伯数字/常见倍率单位降为待核查，摘要/结论同样展示；数字相同不等于指标关系或语义已证实。

专项分别通过：outbox5/5（1.366秒）、后台worker2/2（0.344秒）、数值/预算/合同8/8（最终0.017秒）、并发响应3/3（0.152秒）、9MiB元数据投影1/1（0.329秒）、报告路由34/34（5.558秒）、工作区19/19（11.912秒）、知识27/27（34.211秒）、论文8/8（0.335秒）、前端静态45/45（0.085秒）；JS语法通过。这些分模块结果不拼接成全量或真实浏览器验收。旧1061门禁不覆盖本轮新源码。

保留真实失败：原同步上传180秒超时；仅批量化仍超时且需终止自有应用；首次异步模型输入53331>16384 tokens，LoRA元数据JSON超8MiB；修复首轮漏导入WorkspaceServices产生500，已补并跑34/34。验收驱动只取前20片段导致误报引用绑定失败的问题已修分页，不倒推为产品伪造引用。日志/隔离DB/PDF/权重不提交。

P0仍未整体完成：浏览器URL工具策略拒绝未绕过；用户明确保留实际OS重启/磁盘故障未验收；275历史原件无可信备份，不删记录/不盲绑；更广语义/教学质量与生产完整隔离仍缺，production_sandbox_ready=false。生产与日常DB未改，原registry脏改保留且排除。最新冻结全量/云端及索引续跑结果以本节后续终局为准。


## Real model workflow and report responsiveness follow-up

The final complete-app round `output/p0-business/c7c803bd16804dd889562b6f445ce8d3/report.json`
passed **34/34 checks in 50.609 seconds**, with zero preview-hold time. The prepared
application interpreter used actual Chroma/Qwen embeddings and local Qwen3.5-9B
generation. The report requires both provider success and `mode=model_assisted`;
a deterministic fallback cannot pass this check. The source-bound graph used one
recorded model call and zero contract repairs. Two full application processes had
the same startup source digest
`799c2ca51d9977941c698898bf5fd5dd91c46961b5d50d519c142b499e8ab14f`.
Notes, graph content/version/revision, completed tasks, reading position and
immutable report download hashes survived the process restart.

The final default no-generation compatibility round
`output/p0-business/b804682b6d704316a5eef16d1d0046fc/report.json` passed **32/32 in
29.078 seconds**, also with zero preview hold. Both rounds use labelled synthetic
inputs. They establish model transport, source contracts and persistence, not
general semantic accuracy, real teachers/learners or sustained load. Total actual
generation-call count is not independently instrumented and is recorded as null
in model mode; the graph's reported count is recorded separately.

The actual final report PDF was rendered separately with Poppler and both A4
pages visually inspected. Chinese text, citation/source-index blocks, headings
and page breaks were legible with no observed clipping or overlap on these two
pages. Rendered images remain under `output/p0-real-model-20261023/tmp/pdfs`.
Poppler emitted missing display-font warnings for Symbol/ArialUnicode; no visual
glyph defect was observed in this fixture. `pdfinfo` reports an untagged PDF,
so this is not PDF/UA or screen-reader acceptance, nor browser interaction.

Report generation, paper analysis, Markdown/JSON writes, PDF rendering and
artifact registration/hashing now run in worker threads instead of blocking the
HTTP event loop. Regression holds a slow report export until an unrelated read
has responded. Relevant isolated modules passed separately: responsiveness 3/3
(0.144 s), paper intelligence 8/8 (0.375 s), artifact delivery 4/4 (0.985 s),
model opt-in/preflight 2/2 (0.049 s). The model preflight is explicit loopback-only,
rejects credentials/remote URLs, and writes a failed receipt without launching the
app when the provider cannot be reached. Existing default behavior remains
generation-free. Script SHA-256:
`83ecdb778675b67f720998cd21e9272718431926265e78b300b235ad8e28eb08`.
Source fingerprints are in `output/p0-real-model-20261023/final-source-audit.json`.

The prepared interpreter also passed the native LPAC probe **26/26** in
`output/strict-sandbox/db33027ead91/report.json`: parent token verification,
file/process isolation, IPv4/IPv6 TCP/UDP denial, timeout/output limits and positive
controls passed. Its owned discovery profile was deleted and both ACL cleanups
returned zero. This remains the scoped Windows/Python-stdlib synthetic boundary;
`production_sandbox_ready=false` is unchanged.

Retained failures: the first restricted-context model listened but ordinary-user
HTTP preflight timed out; the ordinary-user owned model then worked. This does
not prove the exact Windows networking cause. The first harness unit run could
not create a restricted TEMP fixture; its isolated normal-user rerun passed.
Browser Use explicitly denied acquiring the existing 18942 tab under URL policy.
No alternate browser or policy workaround was used, and no browser test passed.
All owned app previews exited cleanly; the model was deliberately terminated via
its owned process handle (Windows exit 1), not reported as graceful model exit.
No production process was restarted; daily DB and original dirty registry hashes
remain unchanged. Ordinary-user exclusive binds verified that all three owned
ports (18942/18943/18947) were released; receipt `owned-ports-closed.json` is in the
same evidence directory. Previous rounds are retained separately.

Source `9963e719a37ff25d80c4b714981682cd4dd01cb2` passed its own frozen local full
suite **1061/1061, zero skips/failures/errors**. Partitions 309/190/209/353 are
complete and disjoint; JSON durations 492.938/146.016/110.860/783.266 seconds,
overall wall time 786.485 seconds. All 448 file fingerprints and HEAD stayed
unchanged; daily DB unchanged and original registry bytes restored. Receipts:
`output/p0-real-model-20261023/full-result.json` and `full-source-audit.json`.
Its own [hosted run 39945871186](https://github.com/Snape-arch/agent/actions/runs/39945871186)
is completed/success: all four Windows shards and the final `deterministic-tests`
gate completed successfully, with every `head_sha` matching the source above.
Raw receipts and independent verification are in the same evidence directory's
`cloud-terminal.json` and `verified-final-summary.json`; the old run is not used
to certify this increment. The final handoff is three Markdown files only with
`[skip ci]`, keeping tested code identical. Remaining P0 gates still include browser
operation, broader real-source/model-quality evidence, physical system/storage
tests, trusted historical recovery and production isolation.

The user confirmed on 2026-10-23 that no independent restart/fault-injection test
machine or Windows VM is currently available and explicitly requested that those
gates remain unaccepted. No current-host reboot or physical disk fault is performed.

## Previous verified source and terminal gates

Source **`db533d4deb2d09921c5fd6c747f9f7b0661d1cee`** passed the fresh local
full suite using the independently prepared application interpreter:
**1058/1058, zero skips, zero failures/errors**. The module partitions
307/189/209/353 are complete and disjoint. JSON summary durations are
501.688/148.906/111.031/783.375 seconds; total wall time 786.718 seconds.
All 447 recorded source/dependency/launcher fingerprints and HEAD stayed unchanged.
Daily DB stayed unchanged; the original dirty registry bytes were restored.
Evidence is retained in `output/p0-final-cli-20261023/full-result.json`,
`full-source-audit.json` and `verified-final-summary.json`.

The same source's [GitHub run 39941236996](https://github.com/Snape-arch/agent/actions/runs/39941236996)
is **completed/success**. All four Windows shards and the final
`deterministic-tests` gate are individually completed/success with matching
`head_sha`. Job durations including environment setup were 774/349/399/653 seconds
for shards 0/1/2/3; the final gate ran for three seconds. These durations are not
individual unittest durations or continuous-load evidence. Raw hosted terminal
receipts are in `output/p0-final-cli-20261023/cloud-terminal.json`.

This result includes the launcher and model-evaluator exit-code changes described
below. Previous failures remain recorded; a later passing run does not prove the
old hosted failure's unknown cause. The final handoff is Markdown-only with
`[skip ci]`; code, tests, dependencies and workflow remain identical to the tested
source. Skipping a documentation run is not reported as passing a new source run.

P0 as a whole remains unaccepted against the remaining gates below. Synthetic
HTTP evidence, process restarts and logical fault injection do not certify actual
browser interaction, generation quality, physical durability or recovered originals.

## Earlier terminal evidence and follow-up

Source `de3b5149b99af5fa3d8d044c021c4bfc04a65adc` passed the fresh local frozen
full suite on the independent application interpreter: **1055/1055, zero skips**.
Module partitions 307/189/208/351 were complete and disjoint; individual durations
503.188/150.141/114.625/785.563 seconds. Source bytes and HEAD stayed unchanged;
daily DB stayed unchanged and the original registry bytes were restored.
Evidence: `output/p0-deployment-final-20261023/full-result.json`,
`full-source-audit.json`. These are deterministic tests, not real model quality or
continuous-load evidence; independent shard durations are not summed as load.

The same source's hosted run [39814970787](https://github.com/Snape-arch/agent/actions/runs/39814970787)
**failed**: three shards passed; shard 3 failed
`test_model_acceptance_text_output_includes_counts` (mock evaluator: one of two
tool cases failed, score 8/10). The original text lacked per-case reasons; its
root cause, including any suspected latency, is **not proved** by this annotation.
The required final gate correctly failed. Raw terminal and annotation receipts
are retained; local success is not substituted for this hosted failure.

Follow-up CLI diagnostics retain failed case/scenario/tool, measured time and
reasons without echoing tool payloads. Exit success now also requires the provider
and full evaluation to pass, closing the existing `ok=false`/exit-zero path.
The frozen benchmark thresholds and provider requirements are unchanged.
The expanded model-acceptance module passed 11/11 (4.473 seconds); diagnostic and
provider-failure negatives are included. This does not establish the old cloud
failure's cause. The final source was subsequently covered by the full run above.

An additional real CMD negative check found that nested batch failure exits could
stop startup yet return zero. A standalone failure label now returns one for all
main startup failures; helper subroutine return contracts are retained. Actual
unmarked/missing interpreter checks return one without starting services; the
default prepared-runtime selection returns zero. Deployment module 8/8 (0.657
seconds), plus the actual prepared default batch check, passed. These changes
followed the 1055-case frozen source and are included in the final 1058-case source
and successful hosted gate recorded above.

Daily DB SHA-256 remains
`8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`;
original dirty registry SHA-256 remains
`a72423d78ff1e7d67c646fcd7debf1824ce9e88767b0034455ff1fefcc5a23d4`.

P0 is not wholly accepted. This block fixes the application dependency environment
and incomplete recovery activation; browser interaction, physical reboot/power-loss
durability and the 275 missing historical artifacts remain separate gaps.
`production_sandbox_ready=false` is unchanged.

## Remaining P0 acceptance gates

| Gate | Current evidence | Required evidence before acceptance |
| --- | --- | --- |
| Browser and real generation workflows | Synthetic HTTP 32/32; real embeddings, zero generation calls | Actual browser operations for the six business flows, real generation outputs checked against source material, saved/downloaded results and restart persistence; visual/keyboard/accessibility results reported separately |
| System and storage durability | Process restart, interrupted child writes, logical ENOSPC/EACCES | An authorized controlled OS restart and actual storage fault test in a disposable environment, with original hashes, interruption point and recovery outcome recorded |
| Historical artifacts | 275 missing; no trusted original or backup currently confirmed | Verify original identity before restoring, or record a separately authorized disposition; no same-name relinking, invented replacement or silent deletion |
| Strict production sandbox | Existing strict fail-closed regression only | Independently prove required file/network/process isolation on the deployment host; keep readiness false until that evidence exists |

Automated test completion recorded here applies to its exact source and environment. It
does not close these remaining gates, establish learning outcomes, or count a
pause between checks as sustained load.

## Implementation

- Windows x64 CPython 3.12 profile: 135 exact distributions with wheel SHA-256,
  explicit PyPI origin and transitive provenance. Preparation creates a new venv
  with `include-system-site-packages=false`, checks dependency conflicts, checks
  the entire distribution inventory/location, imports real native libraries and
  executes a CPU tensor operation. Failure preserves logs/state and the previous
  activation. LF/CRLF dependency inputs normalize to the same identity.
- `start_clawos.bat` selects the verified activation before starting services;
  verification failure stops startup. `--check-runtime` verifies the actual batch
  path without starting services or loading `.env`. Explicit `CLAWOS_PYTHON`
  remains a deliberate development override.
- Standard base CPython, LibreOffice/desktop tools, optional PaddleOCR and model
  weights remain external. This is an isolated venv, not a bundled portable
  interpreter or an attestation of every installed library byte. ASR imports do
  not certify recognition accuracy or provision its model weights.
- Recovery progress markers are written before copies. Database copy is now
  inside the error boundary; data/manifest/report writes are flushed, and JSON
  receipts publish atomically. Failed error-receipt writes preserve the original
  exception and pre-existing progress marker. Startup and health reject incomplete
  backup/recovery workspaces. No running user database is replaced.
- Knowledge create/update/delete embedding refresh and PDF upload parsing/indexing
  run in worker threads. Slow encoder regression proves unrelated HTTP reads can
  respond. Default numerical thread pools are bounded to two before imports;
  explicit operator settings are retained. This does not certify all CPU-heavy
  endpoints or multi-user load behavior.

## Evidence

Independent environment installed from the hash lock:
`output/app-runtimes/windows-py312-bb8d1b6c48bc-a2060ee0`.
Python 3.12.14; lock identity
`bb8d1b6c48bcf9b77ebfedb69db91cb4d0e51d3b474d38975a0a32a10e443a2a`.
`pip check` passed. Installation and receipts remain in ignored output; no package
binaries, model weights or private configuration are committed.

Targeted tests: application runtime 7/7 (0.053 s, including CRLF and tamper checks),
recovery 12/12 (3.582 s), HTTP responsiveness 2/2 (0.146 s). These are distinct runs,
not an aggregate model success rate or continuous load test.

Real storage-fault child processes on the deployment interpreter: 19/19 checks,
`output/recovery-faults/a39fc4a3633a46eda8a1afdf5ffb9f8d/report.json`.
Children exit 73 during partial database and partial source writes. Injected
ENOSPC/EACCES produce failures, no success report, and unusable workspace markers;
a fresh-directory retry succeeds. Source bundle and live fixture database remain
unchanged. Logical injection is not a physical disk-full device, physical power
cut, controller-cache or operating-system reboot test.

Full business terminal round: **32/32 passed**, 28.515 seconds,
`output/p0-business/f48cdf4357ea4d919675fcdc7208aac7/report.json`.
Two full application lifespans used the same prepared interpreter and actual
Chroma/Qwen embeddings. HTTP covers knowledge capture/search, exact PDF download
and citations, code/table/math notes and stale-write rejection, Markdown/PDF/JSON
report downloads, a real queued worker reaching `succeeded`, source search and
reading checkpoint, and source-bound textbook graph/route. A fresh process retained
notes, completed tasks, graph, reading position and download hashes. Health rejects
incomplete recovery, an exclusive bind proves port release, and the actual command
entry point rejects an incomplete workspace before creating its DB. Both owned
processes shut down normally. Synthetic inputs and zero generation calls remain
explicit; no browser, semantic-quality or multi-day result is claimed.

The actual batch `--check-runtime` command passed without starting services or
loading `.env`. Final full-suite terminal results are recorded above.

Historical artifact inventory remains 275 missing (11 reports/264 traces), zero
recorded expected hashes. A bounded inventory of existing backup/output trees
inspected 52,306 filenames and found eight same-name candidates, zero verified
identity matches. Tools/models/runtime packages were excluded. Same names are not
trusted restoration evidence. No references were deleted or relinked. Evidence:
`output/p0-deployment-20261022/missing-artifact-inventory.json`; daily DB unchanged.

On 2026-10-23 the user could not confirm whether old directories or original backups
still exist. No accessible trusted backup path is currently known; permanent loss
has not been established. Missing references remain intact, the eight same-name
candidates remain unlinked, and this recovery requirement remains unaccepted.

## Retained failures and boundaries

- The initial restricted-executor recovery test could not create/clean temporary
  fixtures (24 errors); normal-user isolated rerun exposed a real Windows fsync
  handle-mode bug. That 12-error round is retained; writable handles on only new
  snapshot/recovery files fixed it. Final 12/12 passes separately.
- Business rounds `9a6ba822330449dc86b3af42802c5718`,
  `759abe9eaa1a45179c65fc5c1db3cdbe`,
  `164edc4becc8435181c66e3aa61d5884` each exceeded the original 180-second write
  budget and failed. No failed round is overwritten. Tracebacks placed lazy
  SciPy native import on the waiting thread; numerical thread limits alone did
  not fix the application-shaped case. A simple isolated Chroma-then-transformer
  import completed in 5.64 seconds. Replacing the probe's blocking stdin shutdown
  watcher with an owned stop file allowed the same business operations to finish.
  This supports a test-driver stdin/native-initialization interaction; the exact
  CRT/DLL internal lock has not been proved. It does not establish a three-minute
  product latency fix solely from numerical thread limits.
- Round `9983a8ffeda1437788681f56ea6eaaf6` passed 30 recorded business/restart
  checks but failed overall when a closed-loopback HTTP probe returned
  ConnectTimeout rather than ConnectError. The final probe requires a real
  exclusive bind after process exit; a timeout is never counted as closure.
- In-app browser navigation timed out and its ERR_EMPTY_RESPONSE internal page
  was rejected by Browser Use URL policy. No alternate browser/CDP/Playwright
  bypass was attempted. Browser interaction remains unverified; HTTP checks do
  not certify visual quality, keyboard behavior, accessibility or screen readers.
- Business inputs are explicitly synthetic and generation-model calls are zero.
  Actual Chroma/Qwen embedding use is verified separately from teaching/research
  semantics. Real model quality, independent teachers/learners, multi-device and
  multi-day load remain unproved. Daily DB, original registry and production
  processes are preserved; historical missing artifacts are not fabricated.
- Round `4a4de134147a4d4b9d89f2aad4a15bed` correctly rejected incomplete startup
  before opening the database, but the custom Uvicorn Server driver returned zero
  after a failed lifespan; its exit-code assertion failed. The final negative
  check uses the real `clawos_server.py` command entry point, rather than changing
  the expected exit to zero or weakening the application guard.
- The first local full-suite shard 1 failed the frozen code-statistics case at
  4185.289 ms against its unchanged 4000 ms limit. Default stats were reading
  backup files and unknown/binary extensions. Defaults now exclude backups/tools
  (case-insensitive) and unrecognized extensions, and skip symlinks; explicit
  text-extension opt-in remains available. Scope regression 1/1 passed and the
  frozen scenario module passed 7/7 (7.187 s) on a separate rerun. That first full
  suite predates this delta; the final frozen-source full-suite proof is recorded above.
