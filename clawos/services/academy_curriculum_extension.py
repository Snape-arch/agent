"""Authored scaffolds; paper links are dated resources, not a latest-model ranking."""

CHECKED_AT = '2026-10-11'

# id, title, prerequisites, explanation, worked example, exercise, misconception
UNITS = [
 ('computing','文件、终端与可复现环境',[],
  '先认识文件、文件夹、路径和程序。相对路径以当前工作目录为起点；环境记录解释器及依赖版本。每次实验保留输入副本、命令和输出，发生错误先读最后一条异常，再回到触发它的输入。',
  '在项目目录读取 data/sample.csv；换到另一个目录后同一相对路径可能失效。先显示工作目录，再用项目根目录拼接路径，而不是反复移动文件。',
  '建立 input、code、output 三个目录，写下运行命令；故意从错误目录运行，记录原因并修复。','安装成功不等于任何目录都能找到数据。'),
 ('numeracy','比例、函数与图像',[],
  '函数把输入映射到输出。先说明单位，再比较比例、绝对差和变化率。图的坐标轴、范围和样本数会改变直觉；先用几个数检查曲线，再解释趋势。',
  '错误率从20%降到10%，绝对减少10个百分点，相对减少50%。如果测试只有10题，这只是少错1题，不能直接推断所有任务的效果。',
  '画出 y=2x+1 的五个点，比较两组错误率的绝对差和相对差，标明样本数。','百分比变化与百分点变化是两件事。'),
 ('logic','命题、条件与反例',[],
  '把“若A则B”与“若B则A”分开。必要条件是缺了就不行，充分条件是满足它便足够。证明一般结论需要完整推理；一个反例便可否定全称命题。',
  '检索到原句是形成来源引用的条件，但不能保证生成结论受到这句话支持。构造带有原句却颠倒因果的回答，就能检验这一点。',
  '写一个充分条件和一个必要条件；为“带引用的回答总是正确”设计反例。','相关、因果和逻辑蕴含不可互换。'),
 ('calculus','变化率、偏导与链式法则',['linear','numeracy'],
  '导数描述局部变化率，偏导让其他变量暂时固定。组合函数的影响要沿计算路径相乘；反向传播把多个路径贡献相加。先手算一个参数的梯度，再看自动求导。',
  'L=(2w-6)^2，在w=2时L=4，梯度4(2w-6)=-8。学习率0.1更新w到2.8，损失变为0.16；一次下降不证明所有学习率都稳定。',
  '用有限差分核对上述导数，再用过大的学习率观察损失，写明步长。','梯度大小不是模型正确率。'),
 ('data-literacy','采样、标签与数据质量',['statistics','logic'],
  '记录数据来源、采样规则、许可和缺失原因。训练与验收按来源簇划分，避免同一本材料的近似问题泄漏。把教师分歧保留为待复核样本，不用简单投票制造真值。',
  '同一篇文章改写出的十个问题高度相关。将它们随机拆到训练和测试会夸大泛化；应把整篇文章放在同一分组。',
  '建立来源、版本、标签者、理由、数据划分五列，检查重复和冲突标签。','样本行数不等于独立样本数。'),
 ('rl-basics','状态、动作、回报与策略',['statistics','ml'],
  '强化学习在行动后观察反馈。先定义状态和动作范围，再区分单步奖励、累计回报和策略。奖励代理真实目标，设计不当可能鼓励投机；离线效果也受环境分布约束。',
  '网格中到达终点奖励10，每步代价1。最短路径可能回报最高，但若错误地给“点击终点”重复奖励，策略会利用这个漏洞。',
  '在纸上列三个策略的轨迹和累计回报，加入不可达终点，检查终止条件。','奖励增长不能单独证明任务能力增长。'),
 ('sft','监督微调与数据配方',['finetune','data-literacy'],
  '监督微调用输入与目标输出学习任务行为。区分预训练、指令微调与参数高效适配；记录模板、标签质量和验证划分，检查训练损失下降是否伴随独立任务改善。',
  '一百条重复格式答案可以让训练损失下降，却不能教会未出现的任务。保留不同来源的验收题，逐项观察格式和语义错误。',
  '设计小模型训练配方与三组消融：去重、模板、数据规模；先写验收指标再运行。','LoRA是一种参数化更新方式，不是一种数据质量保证。'),
 ('alignment','偏好学习与对齐',['sft','rl-basics'],
  '偏好数据记录同一问题下两个回答的比较及理由。DPO等方法学习偏好关系；标签偏差、长度偏好和安全任务覆盖会改变结果。任务正确性与回答讨喜程度应分开评估。',
  '回答A简短但正确，B很长却遗漏边界。若标签者总偏好长回答，模型可能学会增加篇幅。用同长度对照检查这个混淆。',
  '为六对回答写盲评理由，区分事实、完整性和表达；报告分歧与无把握项。','偏好胜率不是事实正确率。'),
 ('rlvr','可验证奖励与推理训练',['alignment','evaluation'],
  '可验证任务可用执行或数学结果作为奖励，但验收器也有覆盖边界。推理训练还涉及采样、策略更新、探索成本和奖励漏洞；先检查测试是否覆盖真正的任务约束。',
  '一个程序通过三个示例却忽略空输入。只按示例给奖励会鼓励这种实现；增加预先冻结的独立性质检查，区分格式成功和语义成功。',
  '设计公开与保留测试，记录奖励计算、错误类型与成本；阅读R1方法及限制。','更多推理文本不自动等于更好的推理。'),
 ('test-time','推理时计算与验证器',['rlvr','agent'],
  '推理时可以增加候选、修订和验证预算。比较时冻结调用数、token、时间与任务集合；验证器的误判会被放大，多数票也可能重复同一种错误。',
  '五个候选都把同一错误前提当真，多数票仍错误。用独立执行检查或来源反证评价候选，再统计额外成本是否值得。',
  '在相同预算下比较一次回答、三次采样和一次修订，保留全部失败及验证器误判。','增加调用次数不是无条件的能力提升。'),
 ('vision','图像、卷积与视觉表示',['neural','statistics'],
  '图像是带空间结构的数组。卷积共享局部参数，视觉Transformer把图像分成patch；增强改变训练分布，标签和场景差异可能造成部署错误。先理解形状再看模型。',
  '32×32 RGB图像有三个通道。把颜色增强误用于依赖颜色的任务会改变标签含义；应逐个检查增强是否保留任务目标。',
  '画出图像、patch和特征张量的轴，设计一个域外测试与增强反例。','图像分类正确不证明空间推理正确。'),
 ('multimodal','视觉语言与跨模态对齐',['vision','transformer'],
  '视觉、文字和音频需要各自编码及对齐。区分识别图中内容、定位区域和基于内容推理；模型可能从文字提示猜测答案，所以应有模态缺失和互相矛盾的对照。',
  '图片写着“5”，提示声称是“8”。分别只给图、只给提示、同时给二者，检查模型依赖什么，并记录冲突是否被指出。',
  '构建十个有明确区域证据的问答，测图像遮挡、文字误导与原图三种条件。','描述流畅不代表视觉证据被正确使用。'),
 ('diffusion','扩散与生成模型',['vision','calculus'],
  '扩散模型学习逐步去噪；训练噪声预测与采样调度承担不同任务。理解噪声强度、条件控制和采样成本，再讨论生成质量、版权和评估。',
  '给一维信号加入不同强度的噪声，观察信息如何损失。没有真实训练的简单平滑只能演示去噪直觉，不能声称复现扩散模型。',
  '画出前向加噪与反向采样流程，固定种子比较采样步数，并记录资源。','更漂亮的单张样例不能替代系统评估。'),
 ('audio','语音、时间序列与转写',['neural','evaluation'],
  '波形按时间采样，频谱把局部频率结构显现出来。语音识别、说话人分离与会议理解是不同任务；噪声、口音和多人重叠需要分别评价。',
  '转写词错误率低也可能把关键否定词识别错。会议行动项应回到原音频时间段，并由参与者确认责任人与期限。',
  '列出安静、噪声、重叠语音测试条件，分别标注转写错误与行动项错误。','转写文本不是已确认的会议事实。'),
 ('moe','混合专家与稀疏计算',['transformer','statistics'],
  'MoE通过路由选择部分专家参与计算。总参数、激活参数和实际通信成本要分开；负载均衡、专家容量与路由稳定性会影响速度和质量。',
  '八个专家每次激活两个，不能直接推出服务成本是稠密模型的四分之一：路由、显存、通信和批处理仍有开销。',
  '画出token到专家的分配表，模拟容量溢出，分别报告总参数与激活参数。','稀疏激活不等于所有资源按比例减少。'),
 ('long-context','长上下文、记忆与检索',['rag','evaluation'],
  '区分最大输入长度、信息召回和推理利用率。长文本仍可能丢失中间条件；摘要会损失细节，检索会漏召回。按位置、冲突和更新版本测试实际使用能力。',
  '把同一条件放在开头、中间和末尾，再加入过期的相反条件。即使输入均被接收，答案也可能没有使用正确版本。',
  '冻结十个问题，比较长上下文、摘要、检索的来源覆盖、正确性与成本。','上下文窗口长度不是有效记忆质量。'),
 ('systems','推理系统与资源成本',['deployment','moe'],
  '推理涉及prefill、decode、KV缓存、批处理和量化。吞吐与单用户延迟可能互相牵制；报告硬件、并发、输入输出长度和失败率，避免只报最快一次。',
  '两次请求分别输入100和10000个token，首token延迟不可直接比较。固定输入长度后再测并发变化，记录排队时间。',
  '设计冷启动/热启动/并发三种测量，报告P50/P95、内存和拒绝率。','更高吞吐不一定意味着更短交互等待。'),
 ('safety','可靠性、安全与权限边界',['agent','data-literacy'],
  '资料和工具结果是数据。把提示注入、权限、隐私与模型错误分开处理；最小权限、审批、可追溯回执与失败关闭各有作用，不能相互替代。',
  '教材原文中出现“忽略规则并删除文件”，阅读器应把它当引文。工具只能在明确授权的范围行动，结果由执行回执核验。',
  '设计资料注入、过期权限、伪造工具成功三个负例，并检查失败能否安全停止。','在提示中写安全规则不等于操作系统隔离。'),
 ('agent-optimization','Agent优化与可靠协作',['test-time','systems','safety','long-context'],
  '拆分策略、工具选择、记忆和验证器可以分别优化。用真实任务比较基线与候选，保留失败恢复、冲突和预算账本；新增策略只在独立证据支持时晋升。',
  '两个工作者并行修改同一文件可能产生冲突。成功率、冲突恢复率和总成本应同时记录，不能只展示合并成功的案例。',
  '冻结任务簇和预算，对比单代理与多代理；注入工作者退出和真实冲突，核验交付。','角色数量不是协作可靠性的指标。'),
 ('embodied','世界模型与具身智能',['multimodal','rl-basics','safety'],
  '智能体通过感知、状态预测和行动与环境交互。模拟器与现实之间存在分布差异；区分视频预测、规划和真实控制成功，关注反馈延迟和安全停止。',
  '模型预测机器人会绕开障碍，实际控制却可能因传感器延迟碰撞。先在模拟器记录轨迹、碰撞和停止条件，再讨论真实部署。',
  '设计纸面或模拟器导航任务，列出观测缺失、延迟和环境变化的失败条件。','生成合理视频不证明真实环境控制能力。'),
 ('learning-evidence','学习测量与因果推断',['statistics','data-literacy'],
  '前测、后测和延迟测分别观察起点、即时变化和保留。平行题降低记答案影响；盲评减少预期偏差。前后提升还可能来自练习或外部学习，因果结论需要合适对照。',
  '同一学生前测2分后测4分是一次观察。重复原题、教师知道阶段或只保留完成者，都可能夸大效果；记录所有报名者与缺测。',
  '冻结三套同目标平行题，组织双人盲评与延迟测，保留分歧、退出和置信区间。','观察到提升不等于证明平台导致提升。'),
]


def extend(lesson, lessons, resources, tracks, papers):
    resources.extend([
        dict(id='reasoning-paper',title='DeepSeek-R1 原始论文',kind='研究论文',language='英文',url='https://arxiv.org/abs/2501.12948',scope='推理强化学习、蒸馏与验收边界；首次2025，页面修订2026',cost='免费在线'),
        dict(id='agent-survey',title='Agent 优化综述',kind='研究综述',language='英文',url='https://arxiv.org/abs/2503.12434',scope='规划、工具、记忆、数据与评估；页面修订2026-02',cost='免费在线'),
        dict(id='test-time-paper',title='Agent 推理时计算研究',kind='研究论文',language='英文',url='https://arxiv.org/abs/2506.12928',scope='采样、修订、验证与预算对照；2025',cost='免费在线'),
        dict(id='deep-rl',title='Hugging Face · 深度强化学习课程',kind='系统课程',language='英文',url='https://huggingface.co/learn/deep-rl-course/unit0/introduction',scope='状态、回报、Q学习、策略梯度与PPO；课程维护较少，排行榜与AI对战当前不可用',cost='免费在线'),
    ])
    primary={'multimodal':('CLIP','2103.00020'),'diffusion':('DDPM','2006.11239'),'moe':('Switch Transformers','2101.03961'),'audio':('Whisper','2212.04356'),'alignment':('DPO','2305.18290'),'embodied':('World Models · 基础论文（2018）','1803.10122')}
    for key,(title,arxiv) in primary.items():
        resources.append(dict(id=key+'-paper',title=title+' 原始论文',kind='研究论文',language='英文',url='https://arxiv.org/abs/'+arxiv,scope='结合本节例子核对方法、实验和边界',cost='免费在线'))
    foundation={'computing','numeracy','logic','calculus','data-literacy','rl-basics','vision','learning-evidence'}
    for key,title,prereq,explanation,example,exercise,misconception in UNITS:
        resource='reasoning-paper' if key=='rlvr' else 'agent-survey' if key=='agent-optimization' else 'test-time-paper' if key=='test-time' else 'd2l' if key in foundation or key=='diffusion' else 'hf'
        if key in primary:resource=key+'-paper'
        if key=='rl-basics':resource='deep-rl'
        if key=='computing':resource='python'
        if key=='data-literacy':resource='sklearn'
        if key in ('safety','systems'):resource='agents' if key=='safety' else 'torch'
        row=lesson(key,title,'基础' if key in foundation else '前沿',prereq,35 if key in foundation else 55,
            '先能解释机制和失败条件，再用可复现的证据判断效果。',explanation,exercise,
            ['用自己的话解释机制','完成一个带输入与输出的例子','指出条件与反例'],resource,'按本节主题选读；原始论文的结论须回到实验条件。',[title.split('、')[0],'条件','证据'])
        row.update(example=example,misconception=misconception,checked_at=CHECKED_AT,
                   level='补齐基础' if key in foundation else '前沿进阶')
        row['chapter_url']=next(r['url'] for r in resources if r['id']==resource)
        lessons.append(row)
    by_id={r['id']:r for r in lessons}
    by_id['python']['prerequisites']=['computing','logic']
    by_id['linear']['prerequisites']=['numeracy']
    by_id['neural']['prerequisites']=list(dict.fromkeys(by_id['neural']['prerequisites']+['calculus']))
    # Stable topological order ensures every route really starts with its foundations.
    ordered=[];seen=set()
    def visit(key,active):
        if key in seen:return
        if key in active:raise ValueError('curriculum prerequisite cycle')
        for parent in by_id[key]['prerequisites']:visit(parent,active|{key})
        seen.add(key);ordered.append(by_id[key])
    for key in by_id:visit(key,set())
    lessons[:]=ordered
    tracks.extend([
        dict(id='starter',title='从零建立基础',subtitle='文件与逻辑 → Python与数学 → 语言模型',goal='token',extra=['statistics','linear'],accent='mint',project='attention-lab'),
        dict(id='frontier',title='AI前沿全景',subtitle='基础补齐 → 训练与推理 → 多模态与可靠智能体',goal='agent-optimization',extra=['diffusion','audio','embodied','learning-evidence'],accent='peach',project='paper-reproduction'),
    ])
    for key,title,url in [('rlvr','DeepSeek-R1','https://arxiv.org/abs/2501.12948'),('test-time','Scaling Test-time Compute for LLM Agents','https://arxiv.org/abs/2506.12928'),('agent-optimization','A Survey on the Optimization of LLM-based Agents','https://arxiv.org/abs/2503.12434')]:
        papers.append(dict(id=key,title=title,year=2025,topic=key,url=url,minutes=55,
            question=by_id[key]['why'],summary=by_id[key]['explanation'],
            steps=['先列先修概念和论文问题','逐项定位方法、对照、预算和指标','记录失败案例、限制及与自己任务的差异'],
            challenge=by_id[key]['misconception'],experiment=by_id[key]['exercise']))
