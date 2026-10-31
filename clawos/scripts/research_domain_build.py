"""Build short-quote reading packs from hash-checked public captures, not model outputs."""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone


def sha(value): return hashlib.sha256(value).hexdigest()
def packed(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


# Curator-selected method fragments. Whole abstracts remain in ignored evidence only.
QUOTES = {
    'realm':'we augment language model pre-training with a latent knowledge retriever',
    'dpr':'embeddings are learned from a small number of questions and passages by a simple dual-encoder framework',
    'rag-original':'models which combine pre-trained parametric and non-parametric memory for language generation',
    'fid':'generative models are good at aggregating and combining evidence from multiple passages',
    'retro':'conditioning on document chunks retrieved from a large corpus',
    'hyde':'generate a hypothetical document',
    'ragas':'a framework for reference-free evaluation of Retrieval Augmented Generation (RAG) pipelines',
    'self-rag':'adaptively retrieves passages on-demand',
    'adapters':'we propose transfer with adapter modules',
    'prefix':'keeps language model parameters frozen, but optimizes a small continuous task-specific vector',
    'prompt':'learning "soft prompts" to condition frozen language models',
    'bitfit':'only the bias-terms of the model (or a subset of them) are being modified',
    'lora':'freezes the pre-trained model weights and injects trainable rank decomposition matrices',
    'ia3':'scales activations by learned vectors',
    'adalora':'adaptively allocates the parameter budget among weight matrices according to their importance score',
    'qlora':'backpropagates gradients through a frozen, 4-bit quantized pretrained language model into Low Rank Adapters',
    'diffusion-2015':'learn a reverse diffusion process that restores structure in data',
    'score':'samples are produced via Langevin dynamics using gradients of the data distribution estimated with score matching',
    'ddpm':'a novel connection between diffusion probabilistic models and denoising score matching with Langevin dynamics',
    'ddim':'the same training procedure as DDPMs',
    'sde':'this framework encapsulates previous approaches in score-based generative modeling and diffusion probabilistic modeling',
    'ldm':'we apply them in the latent space of powerful pretrained autoencoders',
    'dpm-solver':'a fast dedicated high-order solver for diffusion ODEs',
    'controlnet':'add spatial conditioning controls to large, pretrained text-to-image diffusion models',
    'knnlm':'by linearly interpolating it with a',
    'rest':'REST harnesses the power of retrieval to generate draft tokens',
    'unipelt':'incorporates different PELT methods as submodules',
    'spot':'first learns a prompt on one or more source tasks',
    'improved-ddpm':'competitive log-likelihoods while maintaining high sample quality',
    'd3pm':'diffusion-like generative models for discrete data',
}

# Judgments are assistant-curated coverage assessments, NOT scholarly gold labels.
CHECKS = {
    'rag': [
        ('输入融合', 'covered', 'Query-Based RAG', '3.1.1', ['rag-original','self-rag'], [], '初稿有输入侧检索生成与按需检索入口。'),
        ('隐表示融合', 'covered', 'Latent Representation-Based RAG', '3.1.2', ['fid','retro'], [], 'FiD与RETRO提供代表性入口，未穷尽变体。'),
        ('概率层融合', 'gap', 'Logit-Based RAG', '3.1.3', [], ['knnlm'], '初稿缺少这一融合位置，补读kNN-LM；代表篇目不等于覆盖整类。'),
        ('检索式解码加速', 'gap', 'Speculative RAG', '3.1.4', [], ['rest'], '初稿没有检索草稿解码，补读REST。'),
        ('增强流水线', 'partial', 'RAG Enhancements', '3.2', ['hyde','self-rag','ragas'], [], '已有查询、决策和评估，但生成器优化、结果改写等仍不完整。'),
        ('跨模态应用', 'out_of_scope', 'Applications', '4', [], [], '初稿主要选文本任务，不能代表综述的代码、音频、图像等应用。'),
    ],
    'peft': [
        ('新增参数', 'covered', 'Additive PEFT', '3.1', ['adapters','prefix','prompt','ia3'], [], '初稿把软提示单列作教学入口，综述把它纳入新增参数，属于分类粒度差异。'),
        ('重参数化', 'covered', 'Reparameterized PEFT', '3.2', ['lora','adalora'], [], '已有低秩表示与预算分配，不能代表全部重参数化方法。'),
        ('选择性更新', 'covered', 'Selective PEFT', '3.3', ['bitfit'], [], '偏置更新是代表样本；稀疏结构搜索仍欠缺。'),
        ('混合方法', 'gap', 'Hybrid PEFT', '3.4', [], ['unipelt'], '补读UniPELT，避免把单种适配方式视为互斥选择。'),
        ('量化适配', 'partial', 'Quantization PEFT', '3.5', ['qlora'], [], '已有QLoRA，但量化技术不能压缩成一篇方法的全部结论。'),
        ('任务间迁移', 'gap', 'Multi-task PEFT', '3.6', [], ['spot'], '补读SPoT作为提示迁移入口，多任务领域仍有大量未覆盖工作。'),
    ],
    'diffusion': [
        ('生成基础', 'covered', 'Foundations of Diffusion Models', '2', ['diffusion-2015','score','ddpm','sde'], [], '扩散、分数和SDE入口已列入。'),
        ('高效采样', 'partial', 'Efficient Sampling', '3', ['ddim','dpm-solver'], [], '已有免训练采样路线，未收集蒸馏等学习式采样。'),
        ('训练与似然', 'partial', 'Improved Likelihood', '4', ['ddpm','sde'], ['improved-ddpm'], '初稿提到训练目标和SDE，但未专门组织似然改进，补读Improved DDPM。'),
        ('特殊数据结构', 'gap', 'Special Structures', '5', [], ['d3pm'], '补读离散状态D3PM；不因此覆盖不变性、流形等所有结构。'),
        ('潜空间', 'covered', 'Latent Representations', '8', ['ldm'], [], '已有LDM作为潜空间入口。'),
        ('应用', 'partial', 'Applications', '7', ['controlnet','ldm'], [], '有图像条件控制；视频、三维、时间序列及科学应用仍未系统整理。'),
    ],
}

# Relations are narrowly attributed to the target authors, not endorsed lineage.
DECLARED = {
    'rag': [],
    'peft': [
        ('prefix', 'prompt', 'author_described_simplification', 'simplification of the recently proposed "prefix tuning" of Li and Liang (2021)'),
        ('prompt', 'spot', 'author_described_builds_on', 'Building on the Prompt Tuning approach of Lester et al. (2021)'),
    ],
    'diffusion': [('ddpm', 'ddim', 'author_described_shared_training', 'the same training procedure as DDPMs')],
}


def material(pack):
    keys = ('id','name','categories','prerequisites','paths','overview','limits')
    pkeys = ('id','arxiv_id','name','category','summary')
    return [dict({k:d[k] for k in keys}, papers=[{k:p[k] for k in pkeys} for p in d['papers']]) for d in pack['domains']]


def load_captures(root):
    records = json.loads((root/'captures.json').read_text(encoding='utf-8'))['records']
    for r in records:
        if not r['verified'] or sha((root/(r['id']+'.html')).read_bytes()) != r['raw_sha256']:
            raise ValueError('unverified or changed capture')
        if sha((root/(r['id']+'.text')).read_bytes()) != r['text_sha256']:
            raise ValueError('changed normalized capture')
    return {r['id']:r for r in records}


def fragment(text, quote, capture, url, field):
    start = text.find(quote)
    if start < 0 or len(quote.split()) > 24: raise ValueError('missing or excessive short quote: '+quote)
    return dict(quote=quote, start=start, end=start+len(quote), field=field,
                quote_sha256=sha(quote.encode()), text_sha256=sha(text.encode()),
                raw_sha256=capture['raw_sha256'], source_url=url, captured=capture['captured'],
                verified=True, verification='exact_excerpt_in_captured_source_not_semantic_certification')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ('pack','initial','primary','supplements','surveys','publications','output'): ap.add_argument('--'+key, type=Path, required=True)
    a = ap.parse_args()
    if a.output.exists(): raise SystemExit('Use a new pack path')
    pack = json.loads(a.pack.read_text(encoding='utf-8')); initial = json.loads((a.initial/'initial-pack.json').read_text(encoding='utf-8'))
    if material(pack) != material(initial): raise ValueError('initial overview/taxonomy was changed after survey inspection')
    freeze = json.loads((a.initial/'freeze.json').read_text(encoding='utf-8'))
    if freeze['sha256'] != sha((a.initial/'initial-pack.json').read_bytes()): raise ValueError('initial freeze changed')
    sources = load_captures(a.primary) | load_captures(a.supplements)
    surveys = load_captures(a.surveys); publications = load_captures(a.publications)
    for d in pack['domains']:
        for p in d['papers'] + d['supplements']:
            r = sources[p['id']]; row = r['paper']; version = row['arxiv_id']
            if version.split('v')[0] != p['arxiv_id']: raise ValueError('wrong primary identifier')
            p.update(title=row['title'], authors=row['authors'], date=row['published'], version=version, url='https://arxiv.org/abs/'+version,
                     evidence=fragment(row['abstract'], QUOTES[p['id']], r, 'https://arxiv.org/abs/'+version, 'abstract'),
                     basis='author_abstract_only', phase='initial' if p in d['papers'] else 'after_survey')
        r = surveys[d['id']+'-survey']; text = (a.surveys/(r['id']+'.text')).read_text(encoding='utf-8')
        pub = publications[d['id']+'-publication']; info = pub['publication']
        if info['DOI'].lower() != d['survey']['doi']: raise ValueError('survey publication mismatch')
        if d['survey']['title'].casefold() != info['title'][0].casefold(): raise ValueError('survey title mismatch')
        d['survey'].update(publication=info, publication_raw_sha256=pub['raw_sha256'], publication_captured=pub['captured'],
                           body_raw_sha256=r['raw_sha256'], body_text_sha256=r['text_sha256'], captured=r['captured'],
                           status='published_record_verified', body_basis='revised_arxiv_v15_not_publisher_version' if d['id']=='diffusion' else 'publisher_open_full_text')
        checks = []
        if sum(len(x[2].split()) for x in CHECKS[d['id']]) > 25: raise ValueError('survey quote budget')
        for axis, status, quote, section, ids, additions, note in CHECKS[d['id']]:
            checks.append(dict(axis=axis, initial_status=status, papers=ids, supplements=additions, assessment=note,
                               judgment='assistant_curated_not_expert_gold', section=section,
                               evidence=fragment(text, quote, r, d['survey']['url'], 'normalized_full_page')))
        d['validation'] = checks
        d['declared_relations'] = []
        for source, target, kind, quote in DECLARED[d['id']]:
            r = sources[target]; row = r['paper']
            d['declared_relations'].append(dict(source=source, target=target, kind=kind,
                status='author_statement_not_independently_proven',
                evidence=fragment(row['abstract'], quote, r, 'https://arxiv.org/abs/'+row['arxiv_id'], 'abstract')))
        for p in d['papers'] + d['supplements']:
            quotes = {p['evidence']['quote']} | {r['evidence']['quote'] for r in d['declared_relations'] if r['target']==p['id']}
            if sum(len(q.split()) for q in quotes) > 25: raise ValueError('primary quote budget')
    pack['audit'] = dict(built=datetime.now(timezone.utc).isoformat(), initial_freeze=freeze,
        initial_material_sha256=sha(packed(material(initial))), primary_papers=24, supplemental_papers=6, surveys=3,
        real_model_calls=0, independent_human_reviews=0, semantic_validation_passed=False,
        boundary='原摘要+外部综述结构对照；覆盖判断为助手拟定，非盲评、专家金标准、统一实验或综述一致率。')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(pack, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(primary=24, supplements=6, surveys=3, declared_author_relations=3, output_sha256=sha(a.output.read_bytes()))))


if __name__ == '__main__': main()
