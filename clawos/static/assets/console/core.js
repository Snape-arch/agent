// core behavior for the ClawOS workbench.

export const consoleState = {
  chat: {
    currentSession: "default",
    historyRequest: 0,
    historyPage: null,
    sessionSearchRequest: 0,
    sessionSearchTimer: undefined,
    sessionSearchRows: null,
    busy: false,
    lastToolCalls: [],
    pendingConfirmation: null,
    lastTaskId: null,
    chatAttachments: [],
  },
  tasks: {
    lastRoutingStrategy: null,
    allTools: [],
    taskEventCursor: 0,
    taskStream: null,
    benchmarkSuites: [],
  },
  operations: {
    dailyLocalAcceptanceSummary: "",
    localWorkbenchTimelineItems: [],
  },
  knowledge: {
    knowledgeCategory: "",
    knowledgeItems: [],
    knowledgeDocuments: [],
    lastGeneratedReport: null,
    lastSavedReportKnowledgeId: null,
    editingKnowledgeId: null,
    lastKnowledgeGraph: { nodes: [], edges: [], category: "all" },
    knowledgeOrganizerReturnFocus: null,
  },
  deliveries: {
    lastEnterpriseDelivery: null,
    lastEnterpriseKnowledgeIds: [],
  },
  review: {
    lastSelfReviewCommittee: null,
    lastCommitteeKnowledgeIds: [],
    lastComplexAcceptanceReport: null,
    lastLiveSearchReport: null,
  },
  skills: {
    allSkills: [],
    skillVersions: [],
    skillRuns: [],
    skillReviews: [],
    selectedSkillName: "",
  },
  evolution: {
    evolutionCandidateSearch: null,
    evolutionExperimentLoadGeneration: 0,
  },
  office: {
    embeddedOfficeInstance: null,
  },
};

export const API = location.origin;

export const $ = id => document.getElementById(id);

export const VIEW_META = {
  chat: ["工作台", "对话、文件和任务"],
  search: ["搜索聊天", "查找历史会话并继续上下文"],
  knowledge: ["知识库", "管理资料、文档和检索来源"],
  dash: ["状态总览", "查看模型、工具、任务和记忆系统的运行状态"],
  memory: ["记忆治理", "管理画像、偏好、项目、经验和技能等系统记忆"],
  projects: ["项目", "进入本地项目、科研目录和交付任务"],
  reflection: ["反思循环", "审查任务复盘、改进建议、验证结果和回滚记录"],
  evolution: ["策略演进实验室", "候选比较、成对回放与独立任务证据"],
  skills: ["技能", "查找、预演和管理可复用工作流"],
  tools: ["工具路由", "查看本地函数清单、参数结构和调用轨迹"],
  tasks: ["任务与进度", "查看执行状态、任务记录与待处理事项"],
  ops: ["运行维护", "备份与恢复、配置检查及后台任务"],
  benchmarks: ["冻结基准", "运行离线基准套件，查看通过率和 P95 延迟"],
  scenes: ["场景工作台", "核对会议、科研、办公、学习、Git 和技能治理的交付边界"],
  feishu: ["飞书连接器", "消息、纪要、审批与回执"],
  security: ["权限中心", "查看审批、授权、风险策略和安全审计"]
};

export const esc = value => {
  const node = document.createElement("div");
  node.textContent = value ?? "";
  return node.innerHTML;
};

export async function api(path, opts) {
  const response = await fetch(API + path, opts || {});
  if (!response.ok) throw new Error(`${path} ${response.status}`);
  return await response.json();
}

export function usePrompt(text) {
  const prompt = $("prompt");
  if (!prompt) return;
  prompt.value = text;
  prompt.focus();
}

export const WORKBENCH_PROMPTS = {
  "编写与开发": "请分析当前项目，给出可执行的开发计划，完成编码、测试、审查与交付闭环。",
  "会议纪要": "请处理会议材料，输出结构化纪要、决策、行动项、负责人和日历跟进建议。",
  "数据分析": "请分析所附数据，完成清洗、统计、公式、图表、洞察和高质量工作簿交付。",
  "论文精读": "请精读所附论文，提取方法、实验、发现、局限与引用证据，并沉淀到知识库。"
};

export function workbenchProgress(task) {
  const raw = task.progress_percent ?? task.progress;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  return Math.max(0, Math.min(100, value));
}

export function workbenchStatusLabel(status) {
  const labels = {
    succeeded: "已完成", running: "进行中", in_progress: "进行中", processing: "处理中",
    queued: "排队中", pending: "待开始", waiting: "等待中", failed: "需处理",
    canceled: "已取消", cancelled: "已取消", interrupted: "可恢复"
  };
  return labels[String(status || "").toLowerCase()] || "已记录";
}

export function statusBadge(status) {
  const raw = String(status ?? "pending").trim().toLowerCase() || 'pending';
  const labels = {ok:"正常",success:"成功",succeeded:"已完成",ready:"就绪",true:"通过",passed:"通过",allow:"允许",
    error:"异常",failed:"失败",false:"未通过",deny:"拒绝",canceled:"已取消",cancelled:"已取消",pending:"待处理",
    running:"进行中",queued:"排队中",active:"已启用",candidate:"候选",validated:"已验证",needs_changes:"需修改",
    rejected:"已拒绝",canary:"灰度中",paused:"已暂停",blocked:"受阻",completed:"已完成",published:"已发布"};
  const ok = ["ok","success","succeeded","ready","true","passed","allow","active","validated","completed","published"].includes(raw);
  const bad = ["error","failed","false","deny","rejected","blocked"].includes(raw);
  return `<span class="state ${ok ? "ok" : bad ? "err" : "wait"}" title="${esc(raw)}">${esc(labels[raw] || String(status ?? "待处理"))}</span>`;
}

export function table(headers, rows) {
  const head = `<thead><tr>${headers.map(h => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead>`;
  const body = `<tbody>${(rows || []).map(row => `<tr>${row.map(cell => {
    if (cell && typeof cell === "object" && "html" in cell) return `<td>${cell.html}</td>`;
    if (cell && typeof cell === "object") return `<td><details class="cell-details"><summary>查看详细信息</summary><pre>${esc(JSON.stringify(cell,null,2))}</pre></details></td>`;
    return `<td>${esc(cell ?? "—")}</td>`;
  }).join("")}</tr>`).join("") || `<tr><td class="table-empty" colspan="${Math.max(1,headers.length)}">暂无记录</td></tr>`}</tbody>`;
  return head + body;
}

export function md(text) {
  return window.ClawChatContent.render(text);
}

export function enhanceMarkdown(container) {
  container?.querySelectorAll(".md-copy").forEach(button => {
    button.onclick = async () => {
      const code = button.closest(".md-code")?.querySelector("code")?.textContent || "";
      try {
        let copied = false;
        if (navigator.clipboard?.writeText) {
          try {
            await navigator.clipboard.writeText(code);
            copied = true;
          } catch (_) {
            copied = false;
          }
        }
        if (!copied) {
          const fallback = document.createElement("textarea");
          fallback.value = code;
          fallback.setAttribute("readonly", "");
          fallback.style.position = "fixed";
          fallback.style.opacity = "0";
          document.body.appendChild(fallback);
          fallback.select();
          const succeeded = document.execCommand("copy");
          fallback.remove();
          if (!succeeded) throw new Error("copy unavailable");
        }
        button.textContent = "已复制";
        window.setTimeout(() => { button.textContent = "复制"; }, 1400);
      } catch (_) {
        button.textContent = "复制失败";
      }
    };
  });
}

export function formatArtifactBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export const KNOWLEDGE_MODES = {
  all: {
    eyebrow: "Personal Knowledge Graph",
    title: "全部知识库",
    desc: "统一查看你的资料节点、图谱关系、上传入口和最近沉淀内容。",
    upload: "论文、课程笔记、项目文档、会议纪要都会进入当前库，并生成可检索节点。",
    actions: [["上传资料", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["检索资料", "focusKnowledgeSearch()", "secondary"]],
  },
  research: {
    eyebrow: "科研资料",
    title: "科研库",
    desc: "面向论文、实验、引用和研究问题，优先展示论文节点、证据关系和可复现材料。",
    upload: "上传论文 PDF、arXiv 笔记、实验记录或引用材料，自动沉淀为研究节点。",
    actions: [["上传论文", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["检索资料", "focusKnowledgeSearch()", "secondary"]],
  },
  learning: {
    eyebrow: "学习资料",
    title: "学习库",
    desc: "面向课程、路线、概念卡片和自测复盘，帮助你从资料走向掌握。",
    upload: "上传课程讲义、学习笔记、术语表或练习材料，形成学习路径节点。",
    actions: [["上传课程资料", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["检索资料", "focusKnowledgeSearch()", "secondary"]],
  },
  writing: {
    eyebrow: "写作资料",
    title: "写作库",
    desc: "面向博客、答辩稿、商业计划书和表达素材，突出草稿、论点和引用。",
    upload: "上传草稿、素材、会议结论或参考文章，沉淀为可复用写作节点。",
    actions: [["上传写作素材", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["整理资料", "openKnowledgeOrganizer()", "secondary"]],
  },
  project: {
    eyebrow: "项目资料",
    title: "项目库",
    desc: "面向本地项目、交付包、runbook、验收报告和风险清单，服务真实交付。",
    upload: "上传项目文档、架构图说明、验收报告或 runbook，形成交付节点。",
    actions: [["上传项目资料", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["检索资料", "focusKnowledgeSearch()", "secondary"]],
  },
};

export function formatTags(raw) {
  try {
    const tags = Array.isArray(raw) ? raw : JSON.parse(raw || "[]");
    return tags.slice(0, 4).join(" / ");
  } catch (err) {
    return String(raw || "");
  }
}

export function formatMs(value) {
  const number = Number(value || 0);
  return `${Math.round(number)} ms`;
}

export const initialView = (location.hash || "").replace("#", "") || new URLSearchParams(location.search).get('view');
