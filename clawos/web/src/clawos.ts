/** Namespace only this app's API/resource URLs; never patch global fetch. */
export const integrated = () => location.pathname.startsWith('/academy/vision');
export function visionApiUrl(value: string) {
  return integrated() && value.startsWith('/api/') && !value.startsWith('/api/vision/')
    ? '/api/vision/service/' + value.slice(5) : value;
}
export function visionPayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(visionPayload);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, v]) => [key,
    typeof v === 'string' && /(?:url|uri|href)$/i.test(key) ? visionApiUrl(v) : visionPayload(v)]));
  return value;
}
export const domains = {
  rag: {name:'检索增强生成', question:'固定语料与预算，分别比较检索质量、回答依据和运行成本。'},
  peft: {name:'参数高效微调', question:'固定基础模型与任务，记录可训练参数、峰值显存、耗时和任务指标。'},
  diffusion: {name:'扩散生成模型', question:'固定数据与分辨率，比较采样步数、耗时和质量；模拟指标不代表真实生成效果。'},
};
export function researchContext() {
  const key = new URLSearchParams(location.search).get('domain');
  return key && Object.hasOwn(domains,key) ? {id:key,...domains[key as keyof typeof domains]} : undefined;
}
