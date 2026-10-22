"""Public service exports are lazy so optional Office/audio dependencies do not block recovery."""
from importlib import import_module

_EXPORTS = {
    "knowledge_service": ["KnowledgeService"],
    "maintenance_service": ["MaintenanceService"],
    "meeting_audio_service": ["MeetingAudioService"],
    "model_service": ["ModelService"],
    "security_service": ["SecurityService"],
    "task_service": ["TaskService"],
    "tool_service": ["ToolService"],
    "agent_orchestration_service": ["AgentOrchestrationService"],
    "artifact_storage": ["ArtifactStorage"],
    "evaluation_service": ["EvaluationService"],
    "workflow_engine": ["WorkflowEngine"],
    "paper_intelligence_service": ["PaperIntelligenceService", "ScholarlySearchService"],
    "coding_workflow_service": ["CodingWorkflowService"],
    "coding_context_service": ["CodingContextService"],
    "coding_workspace_service": ["CodingWorkspaceService"],
    "agentic_coding_loop_service": ["AgenticCodingLoopService"],
    "lsp_bridge_service": ["LanguageServerBridge", "LanguageServerManager"],
    "advanced_policy_learning": ["CounterfactualTraceAudit", "OfflinePolicySandbox", "RobustOffPolicyEvaluator", "TrajectoryPreferenceRanker"],
    "execution_governance": ["CodingAgentReadiness", "ExecutionBudget", "IdentityContext", "NetworkEgressPolicy", "PolicyHookRegistry"],
    "office_productivity_service": ["OfficeProductivityService"],
    "office_visual_quality_service": ["OfficeVisualQualityService"],
    "autonomous_subagent_service": ["AutonomousSubagentService", "SubagentRoleSpec"],
}
_MODULES={name:module for module,names in _EXPORTS.items() for name in names}
__all__=list(_MODULES)


def __getattr__(name):
    if name not in _MODULES:
        raise AttributeError(name)
    value=getattr(import_module('.'+_MODULES[name],__name__),name)
    globals()[name]=value
    return value
