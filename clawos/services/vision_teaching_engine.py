"""Small, real CPU mechanism exercises. Fixtures are synthetic, never paper metrics."""
import math
import random
import statistics
from services import academy_rag_engine as rag

VERSION = 'vision-teaching.v1'
TEMPLATES = [
    dict(id='rag', lesson='rag', title='过期来源会怎样影响检索？', variable='current_only',
         baseline=False, choices=[True], unit='通过题数 / 6',
         prerequisites=['embedding', 'evaluation'],
         hypothesis='先写下你的预测：过滤旧版本后，哪些问题可能改善？哪些仍不能解决？',
         method='真实执行字符二元组检索与摘录式回答，六个固定教学问题逐题检查来源与拒答。',
         boundary='人工构造的六份短文与六题，无向量模型、生成模型或开放域语义认证。'),
    dict(id='peft', lesson='finetune', title='低秩更新的容量与成本', variable='rank',
         baseline=1, choices=[2, 3], unit='独立测试集均方误差',
         prerequisites=['linear', 'statistics', 'transformer'],
         hypothesis='先预测：增加 rank 后，测试误差和可训练参数会怎样变化？是否一定改善？',
         method='冻结六维线性基座，在相同合成训练集上真实梯度训练 B×A 适配器，再在独立样本评估。',
         boundary='六维合成线性回归；不是语言模型 LoRA、真实任务准确率、显存或论文指标复现。'),
    dict(id='diffusion', lesson='diffusion', title='采样步数与数值误差', variable='steps',
         baseline=8, choices=[16, 32, 64], unit='目标分位点均方根误差',
         prerequisites=['probability', 'calculus', 'vision'],
         hypothesis='先预测：增加积分步数，误差与分数函数调用次数会如何变化？',
         method='用已知一维高斯的解析 score，真实求解 VP 概率流 ODE，比较 Euler 步数。',
         boundary='解析 score 与一维合成分布，初值来自已知终点分布；不训练去噪网络、不生成图像。'),
]


def config(template, value, seed):
    spec = next((t for t in TEMPLATES if t['id'] == template), None)
    if not spec or type(seed) is not int or not 0 <= seed <= 9999:
        raise ValueError('模板或随机种子无效（0–9999）')
    if type(value) is not type(spec['choices'][0]) or value not in spec['choices']:
        raise ValueError('改动项必须使用模板允许的值')
    return spec


def low_rank(rank, seed):
    rng = random.Random(seed)
    train = [[rng.gauss(0, 1) for _ in range(6)] for _ in range(96)]
    test = [[rng.gauss(0, 1) for _ in range(6)] for _ in range(64)]
    # The same data and first adapter rows are shared by paired arms.
    init = random.Random(seed + 10000)
    a = [[init.gauss(0, .15) for _ in range(6)] for _ in range(rank)]
    b = [[0.] * rank for _ in range(6)]
    target = [1.8, 1.2, .6, 0., 0., 0.]

    def loss(rows):
        return sum((sum(b[o][k] * sum(a[k][j] * x[j] for j in range(6)) for k in range(rank))
                    - target[o] * x[o]) ** 2 for x in rows for o in range(6)) / (len(rows) * 6)

    curve = []
    for epoch in range(81):
        if epoch % 10 == 0:curve.append(dict(step=epoch, train=loss(train), test=loss(test)))
        if epoch == 80:break
        da = [[0.] * 6 for _ in range(rank)]; db = [[0.] * rank for _ in range(6)]
        for x in train:
            z = [sum(row[j] * x[j] for j in range(6)) for row in a]
            errors = [sum(b[o][k] * z[k] for k in range(rank)) - target[o] * x[o] for o in range(6)]
            for k in range(rank):
                for o in range(6):db[o][k] += 2 * errors[o] * z[k] / (96 * 6)
                dz = sum(errors[o] * b[o][k] for o in range(6)) * 2 / (96 * 6)
                for j in range(6):da[k][j] += dz * x[j]
        for k in range(rank):
            for j in range(6):a[k][j] -= .5 * da[k][j]
        for o in range(6):
            for k in range(rank):b[o][k] -= .5 * db[o][k]
    return dict(config=dict(rank=rank, seed=seed, epochs=80, learning_rate=.5, train_rows=96, test_rows=64,
                            dimension=6, frozen_base='0.2 × identity', target_update_diagonal=target),
                metric=loss(test), metrics=dict(train_mse=loss(train), test_mse=loss(test),
                                               trainable_parameters=12*rank, full_layer_parameters=36),
                curve=curve, evidence=dict(training_fixture=train, test_fixture=test, adapter_a=a, adapter_b=b))


def diffusion(steps):
    # Midpoint normal quantiles remove sampling noise from the numerical comparison.
    q = [statistics.NormalDist().inv_cdf((i+.5)/128) for i in range(128)]
    alpha = math.exp(-2)
    samples = [2*alpha + math.sqrt(alpha*alpha*.25 + 1-alpha*alpha)*z for z in q]
    target = [2+.5*z for z in q]; curve = []
    for i in range(steps+1):
        t = 1-i/steps
        curve.append(dict(step=i, time=t, mean=statistics.mean(samples), variance=statistics.pvariance(samples)))
        if i == steps:break
        a = math.exp(-2*t); mean = 2*a; variance = a*a*.25 + 1-a*a
        samples = [x - (-2*x + 2*(x-mean)/variance)/steps for x in samples]
    error = math.sqrt(sum((x-y)**2 for x,y in zip(samples,target))/128)
    return dict(config=dict(steps=steps, beta=4, initial_time=1, target_mean=2, target_variance=.25,
                            initial_distribution='exact marginal at t=1', solver='Euler', quantiles=128),
                metric=error, metrics=dict(quantile_rmse=error, mean=statistics.mean(samples),
                                          variance=statistics.pvariance(samples), score_evaluations=steps*128),
                curve=curve, evidence=dict(final_quantiles=samples, target_quantiles=target))


def execute(template, value, seed):
    spec = config(template, value, seed)
    if template == 'rag':
        def arm(current):
            result = rag.run(dict(chunk_size=80, top_k=1, min_score=.08, current_only=current))
            return dict(config=result['config'], metric=result['passed'],
                        metrics=dict(passed=result['passed'], total=result['total']),
                        curve=[], evidence=result)
        arms = [arm(False), arm(value)]
        fixture = dict(documents=rag.DOCUMENTS, cases=rag.CASES, version=rag.VERSION)
    elif template == 'peft':
        arms = [low_rank(1, seed), low_rank(value, seed)]
        fixture = dict(generator='random.Random.gauss', seed=seed, train_rows=96, test_rows=64)
    else:
        arms = [diffusion(8), diffusion(value)]
        fixture = dict(generator='NormalDist.inv_cdf', quantiles=128, seed_used=False)
    return dict(engine_version=VERSION, template=dict(spec), arms=arms, fixture=fixture,
                delta=arms[1]['metric']-arms[0]['metric'],
                boundary=spec['boundary'], execution='real_cpu_synthetic_fixture',
                model_calls=0, paper_reproduction_verified=False, learning_effect_verified=False)
