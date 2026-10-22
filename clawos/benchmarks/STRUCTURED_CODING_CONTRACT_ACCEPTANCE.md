# 结构化代码输出与完整契约链路验收

2026-10-08，接续f6c97b0；只改编码输出、契约与相关证据链路，沿用指定codex分支提交授权。

## 实现

修复ComparisonCapture覆盖调用方response_format的问题。新CodingStructuredOutput为单代理proposal、多代理planner/worker/repairer/conflict_resolver/diagnostician/reviewer生成有界JSON Schema：路径枚举来自当前授权写入范围，replace/create/hunks使用不同字段，禁止未知字段，约束数组、文本及数值；诊断目标绑定实际失败帧。调用参数原样进入真实HTTP请求及计费/回答凭据，保留输出上限和完整性门禁。提供方拒绝Schema时不悄悄降级为自由文本；未知usage或不完整输出仍保留为负例。

本地解析拒绝重复键、NaN/Infinity、嵌在任意说明中的JSON、错误类型、越界路径、混用编辑字段和无依据诊断目标。不自动重写坏JSON；沿用有界真实模型格式重试并计费。旧完整JSON代码围栏及可选summary/explanation字段仍兼容，所以请求strict=false；本地必需字段和作用域门禁继续强制，不能把标志称为某云平台strict=true兼容性验收。

原requirements仍兼容。可附加clauses，每条包含id/category/statement/test_indexes；类别可为input、validation、output、ordering、mutation、dependency、edge_case或behavior。逐条绑定原需求测试索引，覆盖原命令、去重、有界，并冻结进所有相关角色的完整contract_checklist。规划不可漏授权路径；调度、模型诊断、修复、评审、共同重放和交付都使用原契约。条款结果明确为caller_selected_command_exit_codes；整条命令通过不证明每个自然语言语义或全部边界值正确。

可声明interface={kind:python_signature,function,parameters}，可选keyword_only/positional_only/defaults/async，拒绝矛盾声明、Python关键字及未绑定参数。静态检查要求唯一顶层函数、准确参数顺序/种类/默认值、异步种类，不接受通过*args/**kwargs隐藏接口差异。单代理在任何写入前预览规范化补丁并检查接口，格式/签名错误进入有界模型重试；多代理在集成后检查，公共命令全绿也不能让接口不符合的结果通过。独立重放、交付与证据复核重新计算条款/接口结果与规范化源文本摘要。静态签名只证明接口形状，不证明类型行为、运行语义或动态替换。

例子（原API/CLI的requirements入口，无需新开执行接口）：

```json
{"id":"projection","statement":"Preserve exact projection API and validation.","paths":["projection.py"],"test_indexes":[0],"interface":{"kind":"python_signature","function":"project_record","parameters":["record","fields"]},"clauses":[{"id":"invalid-input","category":"validation","statement":"Invalid record or keys raises ValueError.","test_indexes":[0]}]}
```

真实首轮复杂Schema触发本地语法编译器的重复数量/复杂度限制，因此response_format只传简化的解码Schema：保留字段、类型、编辑操作分支、必需项、路径/实际诊断目标枚举；去除maxLength/maxItems/数值范围/identifier pattern的语法展开。完整本地Schema仍强制全部上限和标识符约束，输出/token上限不变；这不是改用自由文本。Schema只限制序列化，不替代精确锚点、源指纹、写权限、测试、后置重放和晋升质量门槛。新模块加入比较的已加载源码见证，直接比较12个核心选择性文件；策略执行额外5个，共17个；旧版本执行凭据不能冒充新版本。此处没有增加自动改源码/权重或自动策略发布。

实现依据：[llama.cpp服务器格式支持](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)、[Schema转语法及限制](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md)。提供方仅支持部分Schema功能，故作用域、字段类型、数值界限及诊断依据都在本地再次检查；目前只验本地既有Qwen服务，不声明所有云接口兼容。

## 验证

新增机制首轮8/8（10.191秒），加入原生交付重放后9/9（30.527秒），增加HTTP参数转发/不降级检查后10/10（30.665秒）；原契约7/7（39.619秒）。新增简化解码Schema仍保留作用域与全部本地上限测试后，11/11（51.740秒）；加入共享Python语义提示实际消息检查后最终11/11（44.217秒），产品兼容11/11（27.941秒）。8个变更Python编译通过，diff --check通过。测试含坏JSON/重复键/非有限数、读取依赖路径拒绝、操作字段混用、无依据诊断、参数默认值/种类/变长参数/重复定义、写前接口修复、公共命令通过但接口错误的多代理拒绝，以及条款/接口凭据真实Git交付重放。

真实Qwen Schema探针：1调用、51计费token，18输出token、stop，返回合规reviewer对象；不是实际编码通过。真实编码使用上轮finite-numbers和record-projection维护者任务，原公开及后置命令不变，新增6条明确条款和显式接口。两任务都为旧任务的契约增强版本，不是新外部盲测或新增独立语义任务。冻结同模型/预算、single/multi交替顺序，四变体全部保留，不回传后置测试反馈。最终实际single 2/2、2调用/4562计费token/150.172秒；multi 2/2、7调用/14768计费token/389.734秒；协议完整、预算合规、可比较执行与all_tasks_resolved均true。

真实首轮output/ss/bf0726acdb四变体全FAILED，6次HTTP调用全部400（没有已知提供方usage），保守扣账56,370、合计27.220秒；无任务执行通过。原因是语法编译器sane repetition/complexity bounds，不是代码测试失败。首轮旧源码bundle44617b29573c3e31d08daad4e9983175cf1643e549811fbc2900c83c8e212437和失败报告保留。简化后另开output/ss/0ce0f23e7a，该轮8源码bundle：5c84376fee458097e2fdb85939f8eddc95705acffa42edbc2d371e90bc3582e9；manifest在output/structured-final-20261008/final-source.json。日常数据库起点SHA256仍8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543；隔离数据、模型权重、tools、output与原skill_registry.jsonl不提交。该轮最终单/多均0/2，10调用/22,089token/4837.500秒；有精确类型遗漏和超时/预算失败，budget_conformant/execution_comparable均false。原负例保留。共享Python语义提示后另开ss\b06cba9cec，8文件bundle 48032ef38be88eb09747adda3c583f3080298b1529944ecde3e5fb83802fad91，报告SHA256 d64bcdcad43e5c580096321f5d4b9dadba03f5f40746e1f29d7ba8f0c858fada。独立CodingEvidenceService及CollaborationDelivery.verify_run核验通过：3个工作者提交和2个集成提交、基线/原快照、实际review/公开测试及范围均通过；9回答参数/摘要、原生上下文/回答、补丁、原命令、条款和签名绑定均复核；旧后置测试不回传模型。最终隔离全量942/942（1889.786秒），output/regression/ef4379114b7f45d8adffa51ca8cbf6bf；8源码指纹稳定。自有18935/PID68760精确核对关闭，生产未重启。按既有授权提交推送指定codex分支；Git最终提交结果以提交记录为准。

共享通用Python语义提示明确：isinstance接受子类、bool属于int子类；只在调用者要求精确类型时提示type检查，分别验证容器与元素，并遵循异常、输出、顺序、重复值和非变异。没有根据后置测试生成补丁或新增规则，不增加模型请求次数，也不放宽预算。最终两项四变体通过只证明这两项旧任务的本次执行，不能据此归因通用能力提升。

工具注册入口functions.jsonl已补齐clauses/interface，SHA256 d308187d0d5d08eda90cd9111a4f6f0d3e11cd7eb1b9a3668791311183389966。69条JSON及两项新契约的字段、必需项、类别与服务校验通过；这是入口声明核对，不是完整JSON Schema引擎验收或新模型执行。元数据在全量运行中补齐，8个Python源码冻结不变；补齐后的子代理9/9（0.528秒）、MTClaw路由6/6（1.501秒）兼容通过。

## 边界与下一步

“完整”指原调用者全部声明在链路中冻结、传递、检查并留证，不是任意自然语言契约的形式化证明。默认旧需求仍为完整原文清单，不擅自猜测或生成可放宽的规则。依赖/精确类型/非变异/顺序的语义要靠实际调用者测试；AST签名、模型评审和Schema不能代替它们。小型复用样本、单模型及缓存不证明通用仓库成功率或速度优势，finite多代理为1工作者，projection为2个同文件依赖工作者串行交接，不等于新的多人并行故障验收。

后续仍需扩充独立维护/外部任务、属性与边界测试、跨语言可检查接口，达到足够真实任务门槛后再走新鲜shadow/canary。严格OS隔离、多设备、读屏、多天负载不在本轮，历史48小时FAILED不改写。
