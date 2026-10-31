"""Small public-literature review candidates; proposals are NOT expert gold labels."""
import hashlib
import json
from pathlib import Path

SOURCES = {
    'attention-v1':('AI方法','Attention Is All You Need · v1','https://arxiv.org/abs/1706.03762v1','preprint','BLEU score of 41.0 after training for 3.5 days'),
    'attention-v7':('AI方法','Attention Is All You Need · v7','https://arxiv.org/abs/1706.03762v7','preprint','BLEU score of 41.8 after training for 3.5 days'),
    'gpt3':('AI方法','Language Models are Few-Shot Learners','https://arxiv.org/abs/2005.14165v4','preprint','Specifically, we train GPT-3, an autoregressive language model with 175 billion parameters'),
    'chile':('生物医学','Effect of a Nutrition Supplement and Physical Activity Program on Pneumonia and Walking Capacity in Chilean Older People: A Factorial Cluster Randomized Trial','https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed.1001023','trial',"Chile's nutritional supplementation program for older people is not effective in reducing the incidence of pneumonia."),
    'vitamin':('生物医学','Vitamin D levels and risk of type 1 diabetes: A Mendelian randomization study','https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed.1003536','mendelian_randomization','Study limitations include an inability to exclude the existence of smaller associations and a lack of evidence from non-European populations.'),
    'correction':('生物医学','Correction: Vitamin D levels and risk of type 1 diabetes: A Mendelian randomization study','https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed.1003624','correction','There is an error in reference 24.'),
    'carbon':('气候科学','Global Carbon Budget 2023','https://essd.copernicus.org/articles/15/5301/2023/','research_article','with a preliminary 2023 growth rate estimate of around 5.1 Gt C (2.4 ppm).'),
    'ipcc':('气候科学','IPCC AR6 Synthesis Report · Headline Statements','https://report.ipcc.ch/ar6syr/headline.html','assessment','Every increment of global warming will intensify multiple and concurrent hazards (high confidence).'),
}

# Each interpretation is an assistant-authored candidate for independent review.
# Altered claims are constructed controls, never attributed to the paper or a model.
CASES = [
    ('AI-01',['attention-v7'],'v7摘要报告BLEU为41.8，并提到训练3.5天。','supported','版本限定与数值一致；仅为作者摘要所报。',['version','quantity']),
    ('AI-02',['attention-v1'],'v1这条摘录报告BLEU为41.8。','contradicted','不能把v7的41.8移植到v1的41.0。',['version','quantity']),
    ('AI-03',['gpt3'],'作者描述GPT-3为1750亿参数的自回归语言模型。','supported','175 billion对应1750亿，中文单位换算需核对。',['quantity','unit']),
    ('AI-04',['gpt3'],'GPT-3在这条摘录中被描述为1750 billion参数。','contradicted','把175改为1750，构造的数值负控。',['quantity']),
    ('AI-05',['gpt3'],'这条参数规模摘录证明该模型已在所有临床任务中安全有效。','insufficient','参数规模不能支持临床有效性或全任务安全。',['scope','causality']),
    ('BIO-01',['chile'],'作者指出智利该老年人营养补充项目未降低肺炎发生率。','supported','保留项目、地区、老年人及否定范围。',['population','polarity']),
    ('BIO-02',['chile'],'作者指出该项目降低了智利老年人的肺炎发生率。','contradicted','构造的否定翻转。',['polarity']),
    ('BIO-03',['vitamin'],'作者承认不能排除较小关联，且缺少非欧洲人群证据。','supported','保留研究局限和人群边界。',['uncertainty','population']),
    ('BIO-04',['vitamin'],'本研究已证明维生素D对所有人群绝对没有任何效应。','insufficient','不能排除较小关联，且不能外推所有人群；不是临床建议。',['uncertainty','population','causality']),
    ('BIO-05',['correction'],'这份更正说明指出参考文献24存在错误，因此它本身证明原研究已经撤稿。','insufficient','更正引用与撤稿不同；不能从这份片段认证当前撤稿状态。',['correction','version']),
    ('CLIMATE-01',['ipcc'],'该评估以高置信度指出，每增量全球变暖会加剧多种并发危害。','supported','保留评估性质与high confidence，非确定性城市预测。',['uncertainty','scope']),
    ('CLIMATE-02',['ipcc'],'该段以100%确定性预测了所有城市每年相同的灾害损失。','insufficient','把置信度、地理尺度、变量和时间范围全部扩大。',['uncertainty','scope','quantity']),
    ('CLIMATE-03',['carbon'],'该段给出2023年大气CO2增长率约5.1 Gt C、2.4 ppm的初步估计。','supported','保留年份、初步估计以及碳质量单位。',['time','unit','uncertainty']),
    ('CLIMATE-04',['carbon'],'该摘录中的5.1质量单位为Gt CO2，并不是Gt C。','contradicted','碳质量和二氧化碳质量不能混同。',['unit']),
    ('CLIMATE-05',['carbon'],'这份2023年初步估计证明2026年实测增长率为2.4 ppm。','insufficient','不能把2023初步估计改称2026实测。',['time','uncertainty']),
]


def candidate_suite():
    manifest_path=Path(__file__).resolve().parents[1]/'benchmarks/fixtures/research_review_sources.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    captures={r['id']:r for r in manifest['records']}
    cases=[]
    for cid,ids,claim,label,reason,tags in CASES:
        refs=[]
        for sid in ids:
            domain,title,url,kind,quote=SOURCES[sid]
            capture=captures.get(sid,{})
            verified=capture.get('verified') is True and capture.get('url')==url and capture.get('fragment_sha256')==hashlib.sha256(quote.encode()).hexdigest()
            refs.append(dict(id=sid,title=title,url=url,source_type=kind,domain=domain,quote=quote,
                capture=dict(capture,verified=verified),
                fragment_sha256=hashlib.sha256(quote.encode()).hexdigest(),basis='curated_public_excerpt',
                boundary='人工选取的短片段；片段摘要不是整篇文档完整性证明，不能代替全文或实时更正状态核对。'))
        cases.append(dict(id=cid,domain=refs[0]['domain'],claim=claim,evidence=refs,tags=tags,
            origin='constructed_claim_control',curator_proposal=dict(verdict=label,reason=reason,status='unreviewed_assistant_proposal')))
    return dict(version='public-literature-candidates.v1',cases=cases,source_count=len(SOURCES),
        human_reviewed=False,boundary='真实公开文献片段上的构造主张/反例。参考标签由助手提出，尚无独立真人评审；不能当专家金标准或真实模型错误率。')
