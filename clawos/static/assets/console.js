// Composition and legacy inline-action bridge for the console modules.
import * as core from './console/core.js';
import * as shell from './console/shell.js';
import * as chat from './console/chat.js';
import * as knowledge from './console/knowledge.js';
import * as deliveries from './console/deliveries.js';
import * as review from './console/review.js';
import * as memory from './console/memory.js';
import * as operations from './console/operations.js';
import * as evolution from './console/evolution.js';
import * as tasks from './console/tasks.js';
import * as security from './console/security.js';
import * as feishu from './console/feishu.js';
import * as skills from './console/skills.js';
import * as office from './console/office.js';
import { $, consoleState, initialView } from './console/core.js';
import { loadSessions, newChat, switchSession } from './console/chat.js';
import { applyProviderPreset, closeCommandDrawer, closeModelSettings, setAutonomyMode, setView, toggleChatProgress } from './console/shell.js';
import { closeKnowledgeGraphExplorer, closeKnowledgeOrganizer, renderKnowledgeWorkspaceShell } from './console/knowledge.js';
import { closeEmbeddedOfficeEditor } from './console/office.js';
import { applyReportPreset } from './console/review.js';
import { loadTasks, startTaskStream } from './console/tasks.js';
import { loadHealth } from './console/operations.js';

shell.configure({
  sendMessage: chat.sendMessage,
  handlePickedFiles: chat.handlePickedFiles,
  ensureProfessionalBoard: tasks.ensureProfessionalBoard,
  loadTools: tasks.loadTools,
  loadToolExecutions: tasks.loadToolExecutions,
  loadTasks: tasks.loadTasks,
  loadBenchmarks: tasks.loadBenchmarks,
  loadCapabilities: tasks.loadCapabilities,
  loadHealth: operations.loadHealth,
  loadDash: operations.loadDash,
  loadOps: operations.loadOps,
  refreshOfflineReadiness: operations.refreshOfflineReadiness,
  loadLocalAcceptanceHistory: operations.loadLocalAcceptanceHistory,
  renderKnowledgeWorkspaceShell: knowledge.renderKnowledgeWorkspaceShell,
  loadKnowledge: knowledge.loadKnowledge,
  loadKnowledgeDocuments: knowledge.loadKnowledgeDocuments,
  loadKnowledgeGraph: knowledge.loadKnowledgeGraph,
  loadOcrQueue: knowledge.loadOcrQueue,
  loadRoutingStrategy: security.loadRoutingStrategy,
  loadSecurityCenter: security.loadSecurityCenter,
  loadMemory: memory.loadMemory,
  loadReflection: evolution.loadReflection,
  loadEvolution: evolution.loadEvolution,
  loadCompetitionReadiness: evolution.loadCompetitionReadiness,
  loadSkills: skills.loadSkills,
  loadFeishuCenter: feishu.loadFeishuCenter,
});

chat.configure({
  renderLastTools: evolution.renderLastTools,
  renderLastReflection: evolution.renderLastReflection,
  refreshAll: shell.refreshAll,
  setView: shell.setView,
  startTaskStream: tasks.startTaskStream,
  renderKnowledgeSessionSelect: knowledge.renderKnowledgeSessionSelect,
});

knowledge.configure({
  sessionTitle: chat.sessionTitle,
  uploadDocuments: chat.uploadDocuments,
  setView: shell.setView,
  toggleCommandDrawer: shell.toggleCommandDrawer,
});

deliveries.configure({
  loadKnowledge: knowledge.loadKnowledge,
  loadKnowledgeGraph: knowledge.loadKnowledgeGraph,
  setView: shell.setView,
});

review.configure({
  loadKnowledge: knowledge.loadKnowledge,
  loadKnowledgeGraph: knowledge.loadKnowledgeGraph,
  enterpriseDeliveryPayload: deliveries.enterpriseDeliveryPayload,
  setView: shell.setView,
});

operations.configure({
  loadRoutingStrategy: security.loadRoutingStrategy,
  loadWorkerStatus: tasks.loadWorkerStatus,
  renderOpsDocuments: tasks.renderOpsDocuments,
  loadTasks: tasks.loadTasks,
  loadKnowledgeDocuments: knowledge.loadKnowledgeDocuments,
  refreshAll: shell.refreshAll,
});

evolution.configure({
  loadTasks: tasks.loadTasks,
});

tasks.configure({
  renderWorkbenchTasks: shell.renderWorkbenchTasks,
  setView: shell.setView,
});

Object.assign(window, {
  api: core.api,
  usePrompt: core.usePrompt,
  useWorkbenchPrompt: shell.useWorkbenchPrompt,
  setAutonomyMode: shell.setAutonomyMode,
  workbenchProgress: core.workbenchProgress,
  workbenchStatusLabel: core.workbenchStatusLabel,
  renderWorkbenchTasks: shell.renderWorkbenchTasks,
  toggleChatProgress: shell.toggleChatProgress,
  openWorkbenchTask: shell.openWorkbenchTask,
  projectPromptText: shell.projectPromptText,
  prepareProjectPrompt: shell.prepareProjectPrompt,
  sendPreparedProjectPrompt: shell.sendPreparedProjectPrompt,
  handleProjectFiles: shell.handleProjectFiles,
  statusBadge: core.statusBadge,
  table: core.table,
  setView: shell.setView,
  toggleSidebar: shell.toggleSidebar,
  md: core.md,
  enhanceMarkdown: core.enhanceMarkdown,
  addMessage: chat.addMessage,
  addAssistantStream: chat.addAssistantStream,
  formatArtifactBytes: core.formatArtifactBytes,
  appendArtifactsToLastAssistant: chat.appendArtifactsToLastAssistant,
  appendCodingEvidenceToLastAssistant: chat.appendCodingEvidenceToLastAssistant,
  attachFeedbackControls: chat.attachFeedbackControls,
  submitTaskFeedback: chat.submitTaskFeedback,
  sendMessage: chat.sendMessage,
  readChatStream: chat.readChatStream,
  submitMessage: chat.submitMessage,
  stopGeneration: chat.stopGeneration,
  confirmPending: chat.confirmPending,
  cancelPending: chat.cancelPending,
  emptyConversation: chat.emptyConversation,
  newChat: chat.newChat,
  switchSession: chat.switchSession,
  renderHistoryControls: chat.renderHistoryControls,
  loadOlderHistory: chat.loadOlderHistory,
  loadSessions: chat.loadSessions,
  cleanSessionTitle: chat.cleanSessionTitle,
  sessionTitle: chat.sessionTitle,
  sessionTags: chat.sessionTags,
  sessionSummary: chat.sessionSummary,
  renderSessions: chat.renderSessions,
  renderSessionSearch: chat.renderSessionSearch,
  searchSessionHistory: chat.searchSessionHistory,
  chooseLocalFile: chat.chooseLocalFile,
  renderAttachmentTray: chat.renderAttachmentTray,
  removeAttachment: chat.removeAttachment,
  uploadDocuments: chat.uploadDocuments,
  handlePickedFiles: chat.handlePickedFiles,
  setMemoryType: knowledge.setMemoryType,
  setKnowledgeCategory: knowledge.setKnowledgeCategory,
  knowledgeCategoryLabel: knowledge.knowledgeCategoryLabel,
  renderKnowledgeWorkspaceShell: knowledge.renderKnowledgeWorkspaceShell,
  toggleKnowledgeAdminTools: knowledge.toggleKnowledgeAdminTools,
  updateKnowledgeFrontstageStats: knowledge.updateKnowledgeFrontstageStats,
  renderKnowledgeSessionSelect: knowledge.renderKnowledgeSessionSelect,
  formatTags: core.formatTags,
  loadKnowledge: knowledge.loadKnowledge,
  loadKnowledgeGovernance: knowledge.loadKnowledgeGovernance,
  reviewMemoryCandidate: knowledge.reviewMemoryCandidate,
  promoteMemoryCandidate: knowledge.promoteMemoryCandidate,
  openKnowledgeGovernance: knowledge.openKnowledgeGovernance,
  closeKnowledgeGovernance: knowledge.closeKnowledgeGovernance,
  resolveKnowledgeConflict: knowledge.resolveKnowledgeConflict,
  backfillKnowledgeV2: knowledge.backfillKnowledgeV2,
  rebuildKnowledgeIndex: knowledge.rebuildKnowledgeIndex,
  renderKnowledgeMap: knowledge.renderKnowledgeMap,
  loadKnowledgeItem: knowledge.loadKnowledgeItem,
  clearKnowledgeEditor: knowledge.clearKnowledgeEditor,
  inferKnowledgeTags: knowledge.inferKnowledgeTags,
  saveKnowledge: knowledge.saveKnowledge,
  searchKnowledge: knowledge.searchKnowledge,
  clearKnowledgeSearch: knowledge.clearKnowledgeSearch,
  focusKnowledgeSearch: knowledge.focusKnowledgeSearch,
  openKnowledgeOrganizer: knowledge.openKnowledgeOrganizer,
  closeKnowledgeOrganizer: knowledge.closeKnowledgeOrganizer,
  handleKnowledgeFiles: knowledge.handleKnowledgeFiles,
  draftKnowledgeFromSelectedSession: knowledge.draftKnowledgeFromSelectedSession,
  appendKnowledgeToPrompt: knowledge.appendKnowledgeToPrompt,
  deleteKnowledgeItem: knowledge.deleteKnowledgeItem,
  renderObsidianCheck: knowledge.renderObsidianCheck,
  checkObsidianVault: knowledge.checkObsidianVault,
  exportObsidianVault: knowledge.exportObsidianVault,
  reportReadyDocuments: knowledge.reportReadyDocuments,
  renderDocumentReportSelect: knowledge.renderDocumentReportSelect,
  loadKnowledgeDocuments: knowledge.loadKnowledgeDocuments,
  renderKnowledgeReportResult: knowledge.renderKnowledgeReportResult,
  reportGenerationError: knowledge.reportGenerationError,
  generateKnowledgeReport: knowledge.generateKnowledgeReport,
  saveGeneratedReportToKnowledge: knowledge.saveGeneratedReportToKnowledge,
  renderEnterpriseDeliveryResult: deliveries.renderEnterpriseDeliveryResult,
  enterpriseDeliveryPayload: deliveries.enterpriseDeliveryPayload,
  runEnterpriseDeliveryRoom: deliveries.runEnterpriseDeliveryRoom,
  saveEnterpriseDeliveryToKnowledge: deliveries.saveEnterpriseDeliveryToKnowledge,
  askEnterpriseDeliveryQuestion: deliveries.askEnterpriseDeliveryQuestion,
  formatMs: core.formatMs,
  renderComplexAcceptanceReport: review.renderComplexAcceptanceReport,
  loadComplexAcceptanceReport: review.loadComplexAcceptanceReport,
  renderLiveSearchReport: review.renderLiveSearchReport,
  loadLiveSearchReport: review.loadLiveSearchReport,
  renderMeetingAudioResult: review.renderMeetingAudioResult,
  runMeetingAudioUpload: review.runMeetingAudioUpload,
  committeePayload: review.committeePayload,
  renderCommitteeTimeline: review.renderCommitteeTimeline,
  roleAvatar: review.roleAvatar,
  renderRoleSwimlanes: review.renderRoleSwimlanes,
  renderAuditTimeline: review.renderAuditTimeline,
  renderDisputeCards: review.renderDisputeCards,
  renderArtifactDiff: review.renderArtifactDiff,
  renderBuilderExecution: review.renderBuilderExecution,
  renderCommitteeAuditBoard: review.renderCommitteeAuditBoard,
  renderRubricMatrix: review.renderRubricMatrix,
  renderSelfReviewCommitteeResult: review.renderSelfReviewCommitteeResult,
  runSelfReviewCommittee: review.runSelfReviewCommittee,
  saveSelfReviewCommitteeToKnowledge: review.saveSelfReviewCommitteeToKnowledge,
  askSelfReviewCommitteeQuestion: review.askSelfReviewCommitteeQuestion,
  reportPresetInfo: review.reportPresetInfo,
  applyReportPreset: review.applyReportPreset,
  useReportStylePrompt: review.useReportStylePrompt,
  saveMemory: memory.saveMemory,
  loadMemory: memory.loadMemory,
  searchMemory: memory.searchMemory,
  toggleMemory: memory.toggleMemory,
  resolveMemoryReview: memory.resolveMemoryReview,
  loadHealth: operations.loadHealth,
  loadDash: operations.loadDash,
  loadModelHealth: operations.loadModelHealth,
  refreshOfflineReadiness: operations.refreshOfflineReadiness,
  loadLocalRemediationGuide: operations.loadLocalRemediationGuide,
  markLocalRemediationAction: operations.markLocalRemediationAction,
  recheckLocalRemediationAction: operations.recheckLocalRemediationAction,
  loadLocalWorkbenchTimeline: operations.loadLocalWorkbenchTimeline,
  openLocalTimelineEvent: operations.openLocalTimelineEvent,
  loadLocalAcceptanceHistory: operations.loadLocalAcceptanceHistory,
  runDailyLocalAcceptance: operations.runDailyLocalAcceptance,
  runLocalQwenSmokeCheck: operations.runLocalQwenSmokeCheck,
  exportLocalMaintenanceReport: operations.exportLocalMaintenanceReport,
  loadLocalMaintenanceReports: operations.loadLocalMaintenanceReports,
  openLocalMaintenanceReport: operations.openLocalMaintenanceReport,
  copyDailyLocalAcceptanceSummary: operations.copyDailyLocalAcceptanceSummary,
  loadToolAccuracy: operations.loadToolAccuracy,
  renderLastTools: evolution.renderLastTools,
  renderLastReflection: evolution.renderLastReflection,
  loadReflection: evolution.loadReflection,
  triggerReflection: evolution.triggerReflection,
  transitionReflection: evolution.transitionReflection,
  validateReflection: evolution.validateReflection,
  publishReflection: evolution.publishReflection,
  rollbackReflection: evolution.rollbackReflection,
  evolutionActions: evolution.evolutionActions,
  loadEvolution: evolution.loadEvolution,
  loadCompetitionReadiness: evolution.loadCompetitionReadiness,
  exportCompetitionReadiness: evolution.exportCompetitionReadiness,
  queueEvolutionRun: evolution.queueEvolutionRun,
  shadowEvolutionRun: evolution.shadowEvolutionRun,
  canaryEvolutionRun: evolution.canaryEvolutionRun,
  activateEvolutionRun: evolution.activateEvolutionRun,
  searchEvolutionCandidates: evolution.searchEvolutionCandidates,
  queueSearchedCandidate: evolution.queueSearchedCandidate,
  loadEvolutionExperiments: evolution.loadEvolutionExperiments,
  freezeEvolutionExperiment: evolution.freezeEvolutionExperiment,
  replayEvolutionExperiment: evolution.replayEvolutionExperiment,
  controlEvolutionExperiment: evolution.controlEvolutionExperiment,
  selectEvolutionReview: evolution.selectEvolutionReview,
  importEvolutionReview: evolution.importEvolutionReview,
  renderEvolutionReviewSummary: evolution.renderEvolutionReviewSummary,
  evolutionReviewId: evolution.evolutionReviewId,
  loadEvolutionCapture: evolution.loadEvolutionCapture,
  startEvolutionCapture: evolution.startEvolutionCapture,
  pauseEvolutionCapture: evolution.pauseEvolutionCapture,
  exportEvolutionReceipts: evolution.exportEvolutionReceipts,
  loadEvolutionReviewUsers: evolution.loadEvolutionReviewUsers,
  grantEvolutionReview: evolution.grantEvolutionReview,
  copyEvolutionReviewLink: evolution.copyEvolutionReviewLink,
  loadEvolutionReviewSummary: evolution.loadEvolutionReviewSummary,
  exportEvolutionReview: evolution.exportEvolutionReview,
  nominateEvolutionExperiment: evolution.nominateEvolutionExperiment,
  exportEvolutionExperiment: evolution.exportEvolutionExperiment,
  benchmarkEvolutionRun: evolution.benchmarkEvolutionRun,
  rollbackEvolutionRun: evolution.rollbackEvolutionRun,
  snapshotEvolutionQuality: evolution.snapshotEvolutionQuality,
  loadTools: tasks.loadTools,
  renderTools: tasks.renderTools,
  loadToolExecutions: tasks.loadToolExecutions,
  taskActions: tasks.taskActions,
  loadTasks: tasks.loadTasks,
  loadTaskQueue: tasks.loadTaskQueue,
  claimTask: tasks.claimTask,
  cancelTask: tasks.cancelTask,
  retryTask: tasks.retryTask,
  recoverTasks: tasks.recoverTasks,
  showTask: tasks.showTask,
  startTaskStream: tasks.startTaskStream,
  loadBenchmarks: tasks.loadBenchmarks,
  runScenarioBenchmark: tasks.runScenarioBenchmark,
  loadCapabilities: tasks.loadCapabilities,
  ensureProfessionalBoard: tasks.ensureProfessionalBoard,
  activateScenarioBoard: tasks.activateScenarioBoard,
  renderOpsDocuments: tasks.renderOpsDocuments,
  loadWorkerStatus: tasks.loadWorkerStatus,
  loadOps: operations.loadOps,
  runConfigCheck: operations.runConfigCheck,
  createBackup: operations.createBackup,
  restoreBackup: operations.restoreBackup,
  startWorker: operations.startWorker,
  stopWorker: operations.stopWorker,
  tickWorker: operations.tickWorker,
  queueReportJob: operations.queueReportJob,
  queueOcrJob: operations.queueOcrJob,
  queueBatchIngestJob: operations.queueBatchIngestJob,
  loadKnowledgeGraph: knowledge.loadKnowledgeGraph,
  openKnowledgeBackstage: knowledge.openKnowledgeBackstage,
  openKnowledgeGraphExplorer: knowledge.openKnowledgeGraphExplorer,
  closeKnowledgeGraphExplorer: knowledge.closeKnowledgeGraphExplorer,
  graphNodeColor: knowledge.graphNodeColor,
  graphTypeLabel: knowledge.graphTypeLabel,
  graphRelationLabel: knowledge.graphRelationLabel,
  isPrivateKnowledgePath: knowledge.isPrivateKnowledgePath,
  publicKnowledgeNodeLabel: knowledge.publicKnowledgeNodeLabel,
  publicKnowledgeNodeDescription: knowledge.publicKnowledgeNodeDescription,
  renderKnowledgeGraphExplorer: knowledge.renderKnowledgeGraphExplorer,
  selectKnowledgeGraphNode: knowledge.selectKnowledgeGraphNode,
  loadOcrQueue: knowledge.loadOcrQueue,
  openDocumentReview: knowledge.openDocumentReview,
  runDocumentOcr: knowledge.runDocumentOcr,
  askCitationAnswer: knowledge.askCitationAnswer,
  loadRoutingStrategy: security.loadRoutingStrategy,
  loadSecurityCenter: security.loadSecurityCenter,
  saveSecurityGrant: security.saveSecurityGrant,
  revokeSecurityGrant: security.revokeSecurityGrant,
  loadFeishuCenter: feishu.loadFeishuCenter,
  feishuRequest: feishu.feishuRequest,
  feishuCreateSummary: feishu.feishuCreateSummary,
  feishuCreateApproval: feishu.feishuCreateApproval,
  feishuSyncApproval: feishu.feishuSyncApproval,
  feishuSendApproved: feishu.feishuSendApproved,
  loadSkills: skills.loadSkills,
  renderSkillsWorkbench: skills.renderSkillsWorkbench,
  selectSkill: skills.selectSkill,
  runSelectedSkill: skills.runSelectedSkill,
  renderSkillVersionTables: skills.renderSkillVersionTables,
  signSkill: skills.signSkill,
  auditSkill: skills.auditSkill,
  canarySkill: skills.canarySkill,
  promoteSkill: skills.promoteSkill,
  reviewSkill: skills.reviewSkill,
  toggleCommandDrawer: shell.toggleCommandDrawer,
  closeCommandDrawer: shell.closeCommandDrawer,
  openDrawerView: shell.openDrawerView,
  openModelSettings: shell.openModelSettings,
  closeModelSettings: shell.closeModelSettings,
  providerPreset: shell.providerPreset,
  modelModeText: shell.modelModeText,
  applyProviderPreset: shell.applyProviderPreset,
  loadModelSettings: shell.loadModelSettings,
  saveModelSettings: shell.saveModelSettings,
  chooseFirstRunModel: shell.chooseFirstRunModel,
  refreshAll: shell.refreshAll,
  refreshView: shell.refreshView,
  loadOfficeEditorScript: office.loadOfficeEditorScript,
  openEmbeddedOfficeEditor: office.openEmbeddedOfficeEditor,
  closeEmbeddedOfficeEditor: office.closeEmbeddedOfficeEditor,
});

try { consoleState.chat.currentSession = localStorage.getItem('clawos-last-session') || 'default'; } catch (_) {}
document.querySelectorAll("button[data-view]").forEach(button => {
  button.onclick = () => {
    if (button.dataset.action === "new-chat") {
      newChat();
      return;
    }
    setView(button.dataset.view);
  };
});
if ($("cfgProvider")) $("cfgProvider").addEventListener("change", () => applyProviderPreset(true));
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if ($("knowledgeOrganizer")?.classList.contains("on")) closeKnowledgeOrganizer();
  else if ($("knowledgeGraphExplorer")?.classList.contains("on")) closeKnowledgeGraphExplorer();
  else if ($("chatProgressPanel")?.classList.contains("on")) toggleChatProgress(false);
  else if ($("modelSettings")?.classList.contains("on")) closeModelSettings();
  else if ($("commandDrawer")?.classList.contains("on")) closeCommandDrawer();
  else if ($("officeEditorModal")?.classList.contains("on")) closeEmbeddedOfficeEditor();
});
applyReportPreset();
renderKnowledgeWorkspaceShell();
setAutonomyMode(localStorage.getItem("clawos-autonomy-mode") || "approve");
loadSessions().then(() => { if (!initialView || initialView === 'chat') switchSession(consoleState.chat.currentSession); });
startTaskStream();
setView(initialView);
setInterval(loadHealth, 30000);
setInterval(() => {
  if (!consoleState.tasks.taskStream) loadTasks();
}, 5000);
