"""Bounded claim-boundary risk patterns, not an entailment classifier."""
from decimal import Decimal,DecimalException,localcontext
import re
import unicodedata

VERSION='claim-boundary-patterns.v1'
LABELS={
    'polarity_requires_review':'主张与所引片段的否定或方向可能不一致',
    'scope_requires_review':'主张可能超出所引片段的人群或适用范围',
    'certainty_requires_review':'主张可能把不确定或无法排除改为确定结论',
    'null_requires_review':'未发现证据或不显著不能直接改成绝对无效',
    'causality_requires_review':'相关性片段不足以直接认证因果',
    'projection_requires_review':'预测或初步估计可能被改称实测结果',
    'status_requires_review':'更正或普通片段不足以认证撤稿状态',
    'physical_unit_requires_review':'物理数值与单位组合未被所引片段覆盖',
}

def hit(pattern,text):return bool(re.search(pattern,text,re.I))
def norm(text):return unicodedata.normalize('NFKC',str(text)).lower()

_UNCERTAIN=r'cannot (?:rule out|exclude)|could not (?:rule out|exclude)|not without|not unlikely|not ineffective|不能排除|无法排除|并非没有|不无'
_HEDGE=r'\b(?:may|might|could|suggests?|preliminary|estimated?|project(?:ed|ion)?|uncertain|confidence|not necessarily)\b|可能|尚|不一定|初步|估计|预测|置信|不能排除|无法排除|缺少|不足|不应|不能据此|未证实'
_FAMILIES=[r'improv\w*|outperform\w*|\bbetter\b|提升|改善|提高|优于|更好',r'reduc\w*|降低|减少',r'effective|ineffective|benefit\w*|有效|无效|获益',r'increas\w*|增加|上升']

def polarity(text,family):
    neg=(r'\b(?:not|no|cannot|failed to|fails to|without)\b[^.;。]{0,32}(?:'+family+r')|'
         r'(?:没有|未能|无法|不能|并未|未|不)[^。；;]{0,8}(?:'+family+r')')
    states=set()
    for clause in re.split(r'[.;。；]|\b(?:but|however|whereas|while)\b|但是|然而|但',text,flags=re.I):
        if not hit(family,clause):continue
        assessed=re.sub(r'\bnot only\b|不仅|不但|不光|不只是|不止','',clause,flags=re.I)
        states.add('uncertain' if hit(_UNCERTAIN,clause) or hit(_HEDGE,clause) else 'negative' if hit(neg,assessed) or 'ineffective' in family and hit(r'\bineffective\b|无效',assessed) else 'positive')
    return next(iter(states)) if len(states)==1 else 'mixed' if states else None

_NUMBER=r'[+-]?\d+(?:,\d{3})*(?:\.\d+)?(?:e[+-]?\d+)?'
_UNIT=r'(?:gt|mt|kg|mg|g)\s*(?:co2|c)(?![a-z0-9])|(?:μg|ug|mg|g)/(?:kg|l)(?![a-z0-9])|(?:kg|mg|μg|ug|ml|ppm|ppb|ms|°c|g|l|s)(?![a-z0-9])'
_MEASURE=re.compile(r'(?<![a-z0-9_.])('+_NUMBER+r')\s*('+_UNIT+r')',re.I)

def number(value):
    if len(value)>64:return None
    try:
        with localcontext() as ctx:
            ctx.prec=64;ctx.Emax=100;ctx.Emin=-100
            result=Decimal(value.replace(',',''))
            if result and abs(result.adjusted())>100:return None
            return str(result.normalize()) if result else '0'
    except DecimalException:return None

def unit(value):return re.sub(r'\s+','',value).replace('μ','u')

def measures(text):
    return [(number(m[1]),unit(m[2])) for m in _MEASURE.finditer(text)]

def unit_risk(text,quotes):
    cited={pair for q in quotes for pair in measures(q)}
    # Explicit unit assertions also occur with words between the number and unit.
    claimed=measures(text)
    for m in re.finditer(r'(?:单位(?:为|是)|unit (?:is|was))\s*('+_UNIT+r')',text,re.I):
        prior=list(re.finditer(_NUMBER,text[max(0,m.start()-30):m.start()],re.I))
        if prior:claimed.append((number(prior[-1].group()),unit(m[1])))
    return any(v is None or (v,u) not in cited for v,u in claimed)

def audit_claim_boundaries(text,cited_fragments):
    """Only own cited excerpts. Flags require review; no flag certifies support."""
    text=norm(text);quotes=[norm(q) for q in cited_fragments];signals=[]
    def add(code):
        if code not in signals:signals.append(code)
    # A complete verbatim excerpt is not a transformation of its own qualifiers.
    if quotes and text.strip() not in {q.strip() for q in quotes}:
        evidence=' '.join(quotes)
        for family in _FAMILIES:
            stated=polarity(text,family);observed=[polarity(q,family) for q in quotes if hit(family,q)]
            if stated in ('positive','negative') and observed and all(v in ('positive','negative') and v!=stated for v in observed):add('polarity_requires_review')
            if stated in ('positive','negative') and observed and all(v=='uncertain' for v in observed) and not hit(_HEDGE,text):add('certainty_requires_review')
        universal=r'\b(?:all (?:patients|populations|tasks|settings|species|clinical)|every (?:patient|population|task|setting|species|city)|any population)\b|所有(?:人群|患者|任务|条件|临床|城市|地区)|任何(?:人群|年龄)|全部(?:人群|患者)'
        restricted=r'(?:不能|不可|无法|不应|不足以|未必)[^。;.]{0,16}(?:所有|任何|全部)|\b(?:not|cannot|not necessarily)\b[^.;]{0,35}\b(?:all|every|any)\b'
        if hit(universal,text) and not hit(restricted,text) and (not hit(universal,evidence) or hit(r'non-european|older people|children|adults|specific|小样本|非欧洲|老年|儿童|特定',evidence)):add('scope_requires_review')
        certainty=r'\b(?:proves?|proven|definitely|certainly|guarantees?)\b|证明|证实|绝对|必然|完全确定|百分之百'
        if hit(certainty,text) and not hit(_HEDGE,text) and hit(_HEDGE+'|'+_UNCERTAIN,evidence):add('certainty_requires_review')
        null_claim=r'\b(?:no effect|no association|ineffective in all|zero effect)\b|没有任何效应|完全无效|绝对无效|绝对没有'
        if hit(null_claim,text) and not hit(r'not (?:prove|establish)|不能(?:证明|认定)|并不(?:证明|代表)',text) and hit(r'not significant|non-significant|no evidence|'+_UNCERTAIN+r'|不显著|未发现|缺乏证据',evidence):add('null_requires_review')
        if hit(r'\b(?:causes?|causally proves?)\b|证明[^。;]{0,12}因果|导致',text) and hit(r'\b(?:association|correlation|associated|observational)\b|相关|关联|观察性',evidence) and not hit(r'\b(?:randomized|randomised|causal|intervention)\b|随机|因果|干预',evidence) and not hit(_HEDGE,text):add('causality_requires_review')
        if hit(r'\b(?:measured|observed|recorded)\b|实测|观测到',text) and hit(r'\b(?:preliminary|estimated?|projection|projected|forecast)\b|初步|估计|预测|预估',evidence) and not hit(_HEDGE+r'|not (?:measured|observed)|并非实测|不是实测',text):add('projection_requires_review')
        retract=r'retract\w*|撤稿|撤回'
        retract_denial=r'not (?:a )?retract|does not (?:imply|prove)|不(?:是|代表|能证明)|不能[^。;]{0,10}(?:证明|认定)|未证实'
        source_status=any(hit(retract,q) and not hit(retract_denial+r'|'+_HEDGE+r'|\bif\b|如果|假如|no evidence|没有.*撤稿',q) for q in quotes)
        if hit(retract,text) and not hit(retract_denial,text) and (not source_status or hit(r'\bnever\b|从未|未曾',text)):add('status_requires_review')
        if unit_risk(text,quotes):add('physical_unit_requires_review')
    return dict(version=VERSION,review_required=bool(signals),signals=[dict(code=c,label=LABELS[c]) for c in signals],semantic_entailment_verified=False,
        boundary='有界风险模式，只检查本项引用；触发不等于学术错误，未触发不等于语义支持。')
