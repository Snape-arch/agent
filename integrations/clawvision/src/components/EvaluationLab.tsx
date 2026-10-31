import { useEffect, useState, type ChangeEvent } from 'react';
import { fetchRunPage, type RunPage } from '../api';
import { ScenarioWorkbench } from './ScenarioWorkbench';
import { TrainingComparisonWorkbench } from './TrainingComparisonWorkbench';
import {
  compareEvaluations, createEvaluation, createTestSet, exportTestSet, fetchEvaluation, fetchEvaluations, fetchFailureCases, fetchTestSets,
  type ErrorGroup, type EvaluationComparison, type EvaluationPage, type EvaluationReport, type FailureCase, type Prediction, type TestSet, type TestSetInput,
} from '../evaluationApi';

const percent = (value: number | null) => value === null ? '—' : `${(value * 100).toFixed(1)}%`;
const delta = (value: number) => `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)} 个百分点`;
const messageOf = (error: unknown) => error instanceof Error ? error.message : '操作失败';
function download(name: string, value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function Pager({ pagination, busy, onPage, label }: { pagination?: EvaluationPage<unknown>['pagination']; busy?: boolean; onPage: (page: number) => void; label: string }) {
  if (!pagination) return null;
  return <div className="evaluation-pager" aria-label={label}><span>{pagination.total} 条 · 第 {pagination.page} / {Math.max(1, pagination.pages)} 页</span>
    <button disabled={busy || !pagination.hasPrevious} onClick={() => onPage(pagination.page - 1)}>上一页</button>
    <button disabled={busy || !pagination.hasNext} onClick={() => onPage(pagination.page + 1)}>下一页</button></div>;
}

export function EvaluationLab({ canWrite }: { canWrite: boolean }) {
  const [sets, setSets] = useState<EvaluationPage<TestSet>>();
  const [setPage, setSetPage] = useState(1);
  const [testSet, setTestSet] = useState<TestSet>();
  const [reports, setReports] = useState<EvaluationPage<EvaluationReport>>();
  const [reportPage, setReportPage] = useState(1);
  const [reportId, setReportId] = useState('');
  const [report, setReport] = useState<EvaluationReport>();
  const [cases, setCases] = useState<EvaluationPage<FailureCase>>();
  const [casePage, setCasePage] = useState(1);
  const [sceneFailure, setSceneFailure] = useState<FailureCase>();
  const [group, setGroup] = useState<Pick<ErrorGroup, 'dimension' | 'value'>>();
  const [baseline, setBaseline] = useState<EvaluationReport>();
  const [candidate, setCandidate] = useState<EvaluationReport>();
  const [comparison, setComparison] = useState<EvaluationComparison>();
  const [runs, setRuns] = useState<RunPage>();
  const [runPage, setRunPage] = useState(1);
  const [runSearch, setRunSearch] = useState('');
  const [runId, setRunId] = useState('');
  const [artifactId, setArtifactId] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [setsLoading, setSetsLoading] = useState(true);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [casesLoading, setCasesLoading] = useState(false);
  const [runsLoading, setRunsLoading] = useState(false);

  const selectSet = (next: TestSet) => {
    if (testSet?.id === next.id) return;
    setNotice(''); setError('');
    setTestSet(next); setReportPage(1); setReportId(''); setReport(undefined); setReports(undefined);
    setCases(undefined); setBaseline(undefined); setCandidate(undefined); setComparison(undefined); setGroup(undefined); setCasePage(1);
  };
  useEffect(() => {
    const controller = new AbortController(); setSetsLoading(true); setSets(undefined);
    fetchTestSets(setPage, controller.signal).then((response) => {
      setSets(response); setTestSet((current) => current ?? response.data[0]);
    }).catch((reason) => { if (!controller.signal.aborted) setError(messageOf(reason)); })
      .finally(() => { if (!controller.signal.aborted) setSetsLoading(false); });
    return () => controller.abort();
  }, [setPage, refresh]);
  useEffect(() => {
    if (!testSet) return;
    const controller = new AbortController(); setReportsLoading(true); setReports(undefined);
    fetchEvaluations(testSet.id, reportPage, controller.signal).then((response) => {
      setReports(response); setReportId((current) => current || response.data[0]?.id || '');
    }).catch((reason) => { if (!controller.signal.aborted) setError(messageOf(reason)); })
      .finally(() => { if (!controller.signal.aborted) setReportsLoading(false); });
    return () => controller.abort();
  }, [testSet?.id, reportPage, refresh]);
  useEffect(() => {
    setReport(undefined); setGroup(undefined); setCasePage(1); setSceneFailure(undefined);
    if (!reportId) return;
    const controller = new AbortController();
    fetchEvaluation(reportId, controller.signal).then(({ data }) => setReport(data))
      .catch((reason) => { if (!controller.signal.aborted) setError(messageOf(reason)); });
    return () => controller.abort();
  }, [reportId]);
  useEffect(() => {
    setCases(undefined);
    if (!report) return;
    const controller = new AbortController(); setCasesLoading(true);
    fetchFailureCases(report.id, casePage, group, controller.signal).then(setCases)
      .catch((reason) => { if (!controller.signal.aborted) setError(messageOf(reason)); })
      .finally(() => { if (!controller.signal.aborted) setCasesLoading(false); });
    return () => controller.abort();
  }, [report, casePage, group]);
  useEffect(() => {
    if (!canWrite) return;
    const controller = new AbortController(); setRunsLoading(true); setRuns(undefined);
    const timer = window.setTimeout(() => {
      fetchRunPage(runPage, runSearch, controller.signal).then(setRuns)
        .catch((reason) => { if (!controller.signal.aborted) setError(messageOf(reason)); })
        .finally(() => { if (!controller.signal.aborted) setRunsLoading(false); });
    }, 200);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [canWrite, runPage, runSearch]);
  useEffect(() => { setComparison(undefined); }, [baseline?.id, candidate?.id]);

  const importFile = async (event: ChangeEvent<HTMLInputElement>, kind: 'set' | 'predictions') => {
    const file = event.target.files?.[0]; event.target.value = '';
    if (!file || !canWrite) return;
    setBusy(true); setError(''); setNotice('');
    try {
      if (file.size > 8 * 1024 * 1024) throw new Error('JSON 文件不能超过 8 MB');
      const input = JSON.parse(await file.text());
      if (kind === 'set') {
        const result = await createTestSet(input as TestSetInput); selectSet(result.data); setSetPage(1);
        setNotice(`已冻结测试集：${result.data.name} · ${result.data.sampleCount} 个样本`);
      } else {
        if (!testSet || !runId) throw new Error('请先选择测试集和真实 Run');
        const predictions: Prediction[] = Array.isArray(input) ? input : input.predictions;
        const result = await createEvaluation({ testSetId: testSet.id, runId, predictions, ...(artifactId.trim() ? { modelArtifactId: artifactId.trim() } : {}) });
        setReportId(result.data.id); setReportPage(1); setNotice(`评估已保存：${result.data.summary.errors} / ${result.data.summary.total} 个错误`);
      }
      setRefresh((value) => value + 1);
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  };
  const compare = async () => {
    if (!baseline || !candidate) return;
    setBusy(true); setError(''); setComparison(undefined);
    try { setComparison((await compareEvaluations(baseline.id, candidate.id)).data); }
    catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  };
  const exportManifest = async () => {
    if (!testSet) return;
    setBusy(true); setError('');
    try { download(`${testSet.id}.json`, (await exportTestSet(testSet.id)).data); }
    catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  };
  return <div className="evaluation-lab">
    <div className="evaluation-intro"><span className="eyebrow">VISION EVALUATION</span><h1>视觉评估与失败分析</h1>
      <p>在同一份固定测试集上，查看分类错误、场景分组和两个 Run 的改善与退化。</p>
      <p className="evaluation-note">当前评估上传的单标签分类预测。测试集冻结样本清单和标签；图片按 URI 引用，内容哈希用于后续核验。</p></div>
    {error && <div role="alert" className="evaluation-error">{error}<button onClick={() => { setError(''); setRefresh((value) => value + 1); }}>重试加载</button></div>}
    {notice && <div role="status" className="evaluation-notice">{notice}</div>}
    <div className="evaluation-columns">
      <section className="card"><div className="card-head"><h2>1. 固定测试集</h2></div>
        {canWrite && <label className="evaluation-upload">导入测试集 JSON<input aria-label="测试集 JSON 文件" type="file" accept=".json,application/json" disabled={busy} onChange={(event) => void importFile(event, 'set')} /></label>}
        {setsLoading ? <p role="status">正在加载测试集…</p> : !sets?.data.length ? <p>尚无测试集。导入带标签和场景条件的样本清单后开始评估。</p> :
          <div className="evaluation-list">{sets.data.map((item) => <button key={item.id} disabled={busy} aria-pressed={testSet?.id === item.id} onClick={() => selectSet(item)}><strong>{item.name}</strong><small>{item.sampleCount} 个样本 · {item.classes.length} 类</small></button>)}</div>}
        <Pager label="测试集分页" pagination={sets?.pagination} busy={busy || setsLoading} onPage={setSetPage} />
        {testSet && <div className="evaluation-selected"><strong>当前：{testSet.name}</strong><code title={testSet.digest}>SHA-256 {testSet.digest.slice(0, 16)}…</code>
          <small>{testSet.datasetVersionId ? `数据版本：${testSet.datasetVersionId}` : '独立导入的测试清单'}</small><button disabled={busy} onClick={() => void exportManifest()}>导出冻结清单</button></div>}
        <details><summary>测试集格式示例</summary><pre>{JSON.stringify({ name: '零件视角测试', classes: ['gear', 'bolt'], samples: [{ id: 'part-001', label: 'gear', conditions: { lighting: 'reflection', angle: 'side' } }] }, null, 2)}</pre></details>
      </section>
      <section className="card"><div className="card-head"><h2>2. 上传 Run 预测</h2></div>
        {canWrite ? <>
          <label>搜索真实 Run<input aria-label="搜索评估 Run" value={runSearch} disabled={busy} onChange={(event) => { setRunSearch(event.target.value); setRunPage(1); }} /></label>
          {runsLoading && <p role="status">正在加载 Run…</p>}
          <label>选择 Run<select aria-label="评估 Run" value={runId} disabled={busy || runsLoading} onChange={(event) => { setRunId(event.target.value); setArtifactId(''); }}>
            <option value="">请选择</option>{runId && !runs?.data.some((run) => run.id === runId) && <option value={runId}>{runId}</option>}
            {runs?.data.map((run) => <option key={run.id} value={run.id}>{run.name} · {run.id}</option>)}
          </select></label>
          {!runsLoading && runs?.data.length === 0 && <p>尚无匹配的 Run。请先创建真实实验，或更换搜索条件。</p>}
          <Pager label="评估 Run 分页" pagination={runs?.pagination} busy={busy || runsLoading} onPage={setRunPage} />
          <label>模型产物 ID（可选）<input aria-label="模型产物 ID" value={artifactId} disabled={busy} onChange={(event) => setArtifactId(event.target.value)} placeholder="关联此 Run 的 checkpoint / 模型产物" /></label>
          <label className="evaluation-upload">上传预测 JSON<input aria-label="预测 JSON 文件" type="file" accept=".json,application/json" disabled={busy || !testSet || !runId} onChange={(event) => void importFile(event, 'predictions')} /></label>
          <p>每个测试样本须有且只有一条预测。新上传会保存为独立评估记录。</p>
        </> : <p>当前权限可查看与对比评估。上传测试集和预测需要研究员角色及写入权限。</p>}
        <details><summary>预测格式示例</summary><pre>{JSON.stringify([{ sampleId: 'part-001', label: 'bolt', confidence: 0.83 }], null, 2)}</pre></details>
      </section>
    </div>
    {testSet && <section className="card"><div className="card-head"><h2>3. 评估记录</h2></div>
      {reportsLoading ? <p role="status">正在加载评估记录…</p> : !reports?.data.length ? <p>此测试集尚无评估记录。</p> : <div className="evaluation-table-scroll"><table><thead><tr><th>Run / 评估</th><th>准确率</th><th>错误数</th><th>操作</th></tr></thead><tbody>{reports.data.map((item) => <tr key={item.id}>
        <td><strong>{item.name}</strong><small>{item.runId} · {new Date(item.createdAt).toLocaleString()}</small></td><td>{percent(item.summary.accuracy)}</td><td>{item.summary.errors} / {item.summary.total}</td>
        <td><div className="evaluation-actions"><button disabled={busy} aria-pressed={reportId === item.id} onClick={() => setReportId(item.id)}>查看错误</button><button disabled={busy} onClick={() => setBaseline(item)}>设为基线</button><button disabled={busy} onClick={() => setCandidate(item)}>设为候选</button></div></td>
      </tr>)}</tbody></table></div>}
      <Pager label="评估记录分页" pagination={reports?.pagination} busy={busy || reportsLoading} onPage={setReportPage} />
    </section>}
    {report && <section className="card"><div className="card-head"><h2>失败分析：{report.name}</h2><button onClick={() => download(`${report.id}.json`, report)}>导出评估报告</button></div>
      <div className="evaluation-metrics"><div><span>准确率</span><strong>{percent(report.summary.accuracy)}</strong></div><div><span>错误率</span><strong>{percent(report.summary.errorRate)}</strong></div><div><span>Macro F1</span><strong>{percent(report.summary.macroF1)}</strong></div><div><span>失败样本</span><strong>{report.summary.errors} / {report.summary.total}</strong></div></div>
      <p className="evaluation-note">Run 快照 revision {report.provenance.run.revision} · {report.provenance.modelArtifact ? `模型产物：${report.provenance.modelArtifact.name}` : '未关联模型产物；预测来源为用户上传'}</p>
      <h3>按场景条件分组</h3><p>分组展示错误分布，同一样本可以属于多个分组。</p>
      <div className="evaluation-table-scroll"><table><thead><tr><th>条件</th><th>样本数</th><th>错误数</th><th>错误率</th><th>操作</th></tr></thead><tbody>{report.summary.groups.map((item) => <tr key={JSON.stringify([item.dimension, item.value])}><td>{item.dimension} = {item.value}</td><td>{item.total}</td><td>{item.errors}</td><td>{percent(item.errorRate)}</td><td><button onClick={() => { setGroup(item); setCasePage(1); }}>查看分组</button></td></tr>)}</tbody></table></div>
      {!report.summary.groups.length && <p>样本未提供场景条件。</p>}
      <details><summary>分类指标与混淆计数</summary><div className="evaluation-table-scroll"><table><thead><tr><th>类别</th><th>真实样本数</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>{report.summary.classMetrics.map((item) => <tr key={item.label}><td>{item.label}</td><td>{item.support}</td><td>{percent(item.precision)}</td><td>{percent(item.recall)}</td><td>{percent(item.f1)}</td></tr>)}</tbody></table></div><pre>{JSON.stringify(report.summary.confusion, null, 2)}</pre></details>
      <div className="evaluation-actions"><h3>{group ? `失败样本：${group.dimension} = ${group.value}` : '全部失败样本'}</h3>{group && <button onClick={() => { setGroup(undefined); setCasePage(1); }}>清除分组</button>}</div>
      {casesLoading ? <p role="status">正在加载失败样本…</p> : cases?.data.length ? <div className="evaluation-table-scroll"><table><thead><tr><th>样本</th><th>真实标签</th><th>预测标签</th><th>置信度</th><th>场景</th>{canWrite && <th>3D 关联</th>}</tr></thead><tbody>{cases.data.map((item) => <tr key={item.sampleId}><td>{item.sampleId}{item.imageUri && <small title={item.imageUri}>{item.imageUri}</small>}</td><td>{item.label}</td><td>{item.predictedLabel}</td><td>{percent(item.confidence)}</td><td>{Object.entries(item.conditions).map(([key, value]) => `${key}=${value}`).join(' · ') || '—'}</td>{canWrite && <td><button disabled={busy} onClick={() => { setSceneFailure(item); document.getElementById('evaluation-scene-workbench')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }); }}>关联 3D 场景</button></td>}</tr>)}</tbody></table></div> : <p>当前范围没有失败样本。</p>}
      <Pager label="失败样本分页" pagination={cases?.pagination} busy={casesLoading} onPage={setCasePage} />
    </section>}
    <section className="card"><div className="card-head"><h2>4. 两个 Run 对比</h2></div>
      <div className="evaluation-actions"><span>基线：{baseline?.name ?? '尚未选择'}</span><span>候选：{candidate?.name ?? '尚未选择'}</span><button disabled={busy || !baseline || !candidate || baseline.runId === candidate.runId} onClick={() => void compare()}>比较两个 Run</button></div>
      {baseline && candidate && baseline.runId === candidate.runId && <p>请选择两个不同 Run 的评估。</p>}
      {comparison && <div data-testid="evaluation-comparison"><div className="evaluation-metrics"><div><span>准确率变化</span><strong>{delta(comparison.accuracyDelta)}</strong></div><div><span>修复样本</span><strong>{comparison.fixed}</strong></div><div><span>新增退化</span><strong>{comparison.regressed}</strong></div><div><span>仍然错误</span><strong>{comparison.bothWrong}</strong></div></div>
        <div className="evaluation-table-scroll"><table><thead><tr><th>条件</th><th>样本数</th><th>基线错误</th><th>候选错误</th><th>错误率变化</th></tr></thead><tbody>{comparison.groups.map((item) => <tr key={JSON.stringify([item.dimension, item.value])}><td>{item.dimension} = {item.value}</td><td>{item.total}</td><td>{item.baselineErrors}</td><td>{item.errors}</td><td>{delta(item.errorRateDelta)}</td></tr>)}</tbody></table></div>
        <p>结果衡量这份测试集上的变化，分组差异不能直接证明错误原因。</p><button onClick={() => download('evaluation-comparison.json', comparison)}>导出对比报告</button></div>}
    </section>
    {report && <ScenarioWorkbench key={report.id} reportId={report.id} failure={sceneFailure} canWrite={canWrite} onBusyChange={setBusy} />}
    <TrainingComparisonWorkbench canWrite={canWrite} />
  </div>;
}
