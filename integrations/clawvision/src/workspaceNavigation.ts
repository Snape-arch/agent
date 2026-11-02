/** One route vocabulary for education, visual tools and the legacy experiment views. */
export const workspaceRoutes = [
  {id:'visuals',title:'可视化课堂',group:'学习与探索',description:'看见机制，理解每一步',worker:false},
  {id:'teaching',title:'实验手册与记录',group:'学习与探索',description:'预测、实验与学习反思',worker:false},
  {id:'data',title:'数据与图表',group:'分析与空间',description:'导入、联动、保存与导出',worker:true},
  {id:'three',title:'三维与空间',group:'分析与空间',description:'模型、点云与轨迹',worker:true},
  {id:'evaluation',title:'视觉评估',group:'分析与空间',description:'诊断、评估与失败分析',worker:true},
  {id:'assets',title:'模型与资产',group:'分析与空间',description:'资源、版本与交付',worker:true},
  {id:'ai-studio',title:'三维创作',group:'分析与空间',description:'场景、合成与几何工具',worker:true},
  {id:'overview',title:'运行与参数',group:'实验追踪',description:'配置并追踪运行',worker:true},
  {id:'compare',title:'对照比较',group:'实验追踪',description:'对齐配置与指标',worker:true},
  {id:'artifacts',title:'诊断与产物',group:'实验追踪',description:'混淆矩阵、特征与日志',worker:true},
  {id:'settings',title:'工作区设置',group:'实验追踪',description:'本机运行服务',worker:false},
] as const;
export type WorkspaceView = typeof workspaceRoutes[number]['id'];
export type LegacyView = 'home' | Exclude<WorkspaceView,'visuals'>;
export const routeEvent = 'clawos-vision:navigate';
export function currentWorkspaceView():WorkspaceView {
  const id=location.hash.slice(1);return workspaceRoutes.find(r=>r.id===id)?.id || 'visuals';
}
export function navigateWorkspace(view:WorkspaceView, updates:Record<string,string|null>={}) {
  const url=new URL(location.href);
  for(const [key,value] of Object.entries(updates))value===null?url.searchParams.delete(key):url.searchParams.set(key,value);
  url.hash=view;
  history.pushState({view},'',url.pathname+url.search+url.hash);
  window.dispatchEvent(new Event(routeEvent));
}
