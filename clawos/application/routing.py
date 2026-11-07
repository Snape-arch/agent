"""Compose domain adapters from explicit application bindings.

The runtime view is used only here. Each domain receives its own narrow providers.
"""
from collections.abc import Callable
from typing import Any, Protocol
from api.task_queries import create_task_query_router


class ApplicationBindings(Protocol):
    background_worker_status: Callable[..., Any]
    g_task_service: Any
    run_tool_loop: Callable[..., Any]
    start_background_worker: Callable[..., Any]
    stop_background_worker: Callable[..., Any]
    _academy_count_run_records: Callable[..., Any]
    _academy_offline_audit_payload: Callable[..., Any]
    _collaboration: Callable[..., Any]
    _competition_hardware_evidence: Callable[..., Any]
    _evolution_json: Callable[..., Any]
    _feishu_service: Callable[..., Any]
    _learning_product: Callable[..., Any]
    _local_qwen_smoke_check: Callable[..., Any]
    _provider_candidates: Callable[..., Any]
    _rag_workshop: Callable[..., Any]
    _system_readiness_payload: Callable[..., Any]
    apply_model_config_updates: Callable[..., Any]
    call_routing_llm: Callable[..., Any]
    cancel_runtime_task: Callable[..., Any]
    claim_runtime_task: Callable[..., Any]
    collect_deliverable_artifacts: Callable[..., Any]
    create_runtime_task: Callable[..., Any]
    enqueue_runtime_task: Callable[..., Any]
    execute_python_tool: Callable[..., Any]
    execute_tool_call: Callable[..., Any]
    finish_runtime_task: Callable[..., Any]
    get_artifact_delivery_service: Callable[..., Any]
    get_autonomous_subagent_service: Callable[..., Any]
    get_coding_workflow_service: Callable[..., Any]
    get_document_index_worker: Callable[..., Any]
    get_document_review_service: Callable[..., Any]
    get_evaluation_service: Callable[..., Any]
    get_knowledge_service: Callable[..., Any]
    get_maintenance_service: Callable[..., Any]
    get_office_productivity_service: Callable[..., Any]
    get_paper_intelligence_service: Callable[..., Any]
    get_reliable_collaboration_service: Callable[..., Any]
    get_scholarly_search_service: Callable[..., Any]
    get_security_service: Callable[..., Any]
    get_task_service: Callable[..., Any]
    get_workflow_engine: Callable[..., Any]
    has_api_key: Callable[..., Any]
    list_memory_items: Callable[..., Any]
    local_asr_capability: Callable[..., Any]
    local_model_assets_status: Callable[..., Any]
    model_config_payload: Callable[..., Any]
    model_mode_label: Callable[..., Any]
    model_provider_status: Callable[..., Any]
    proxy_upstream: Callable[..., Any]
    resolve_obsidian_output_dir: Callable[..., Any]
    retry_runtime_task: Callable[..., Any]
    run_background_worker_once: Callable[..., Any]
    save_memory_item: Callable[..., Any]
    set_memory_item_enabled: Callable[..., Any]
    sse_from_text: Callable[..., Any]
    store_assistant_response: Callable[..., Any]
    BASE_DIR: Any
    DATA_DIR: Any
    MEMORY_DB: Any
    OUTPUT_ROOT: Any
    RUNTIME_RELEASE: Any
    SCENARIO_ROUTING_KEYWORDS: Any
    SCENARIO_ROUTING_POLICY: Any
    STATIC_DIR: Any
    TOOLS_REQUIRING_CONFIRMATION: Any
    UPLOAD_DIR: Any
    WEB_RESEARCH_SYNTHESIS_PROMPT: Any
    WEB_RESEARCH_TOOLS: Any
    _pdf_page_renderer: Any
    config: Any
    g_context_builder: Any
    g_document_index_worker: Any
    g_memory_store: Any
    g_mtclaw_adapter: Any
    g_policy_optimizer: Any
    g_reflection_engine: Any
    g_routing_provider: Any
    g_runtime_policy_controller: Any
    g_scenario_benchmark: Any
    g_secret_manager: Any
    g_security_policy: Any
    g_skill_evolution: Any
    g_upstream_provider: Any
    g_vector_store: Any
    g_workspace_services: Any
    http_client: Any
    logger: Any
    tools_def: Any


def register_domain_routes(app, runtime: ApplicationBindings) -> dict[str, Callable[..., Any]]:
    from api.chat import ChatAPI
    chat_api = ChatAPI(
        apply_web_search_policy=lambda *args, **kwargs: execution_api.apply_web_search_policy(*args, **kwargs),
        build_openai_response=lambda *args, **kwargs: execution_api.build_openai_response(*args, **kwargs),
        build_routing_strategy=lambda *args, **kwargs: execution_api.build_routing_strategy(*args, **kwargs),
        collect_deliverable_artifacts=runtime.collect_deliverable_artifacts,
        create_runtime_task=runtime.create_runtime_task,
        evaluate_shadow_policies=lambda *args, **kwargs: execution_api.evaluate_shadow_policies(*args, **kwargs),
        extract_assistant_text=lambda *args, **kwargs: execution_api.extract_assistant_text(*args, **kwargs),
        finish_runtime_task=runtime.finish_runtime_task,
        get_paper_intelligence_service=runtime.get_paper_intelligence_service,
        has_api_key=lambda *args, **kwargs: runtime.has_api_key(*args, **kwargs),
        model_provider_status=runtime.model_provider_status,
        proxy_upstream=lambda *args, **kwargs: runtime.proxy_upstream(*args, **kwargs),
        resolve_runtime_policies=lambda *args, **kwargs: execution_api.resolve_runtime_policies(*args, **kwargs),
        run_tool_loop=lambda *args, **kwargs: runtime.run_tool_loop(*args, **kwargs),
        runtime_policy_trace=lambda *args, **kwargs: execution_api.runtime_policy_trace(*args, **kwargs),
        sse_from_text=runtime.sse_from_text,
        store_assistant_response=runtime.store_assistant_response,
        tool_result_for_model=lambda *args, **kwargs: execution_api.tool_result_for_model(*args, **kwargs),
        web_search_prompt_policy=lambda *args, **kwargs: execution_api.web_search_prompt_policy(*args, **kwargs),
        output_root_provider=lambda: runtime.OUTPUT_ROOT,
        web_research_tools_provider=lambda: runtime.WEB_RESEARCH_TOOLS,
        config_provider=lambda: runtime.config,
        context_builder_provider=lambda: runtime.g_context_builder,
        memory_store_provider=lambda: runtime.g_memory_store,
        mtclaw_adapter_provider=lambda: runtime.g_mtclaw_adapter,
        policy_optimizer_provider=lambda: runtime.g_policy_optimizer,
        reflection_engine_provider=lambda: runtime.g_reflection_engine,
        runtime_policy_controller_provider=lambda: runtime.g_runtime_policy_controller,
        vector_store_provider=lambda: runtime.g_vector_store,
        logger_provider=lambda: runtime.logger,
    )
    app.include_router(chat_api.router)

    from application.execution import ExecutionRuntime
    execution_api = ExecutionRuntime(
        _provider_candidates=lambda *args, **kwargs: runtime._provider_candidates(*args, **kwargs),
        call_routing_llm=lambda *args, **kwargs: runtime.call_routing_llm(*args, **kwargs),
        execute_python_tool=lambda *args, **kwargs: runtime.execute_python_tool(*args, **kwargs),
        execute_tool_call=lambda *args, **kwargs: runtime.execute_tool_call(*args, **kwargs),
        get_coding_workflow_service=runtime.get_coding_workflow_service,
        has_api_key=lambda *args, **kwargs: runtime.has_api_key(*args, **kwargs),
        output_root_provider=lambda: runtime.OUTPUT_ROOT,
        scenario_routing_keywords_provider=lambda: runtime.SCENARIO_ROUTING_KEYWORDS,
        scenario_routing_policy_provider=lambda: runtime.SCENARIO_ROUTING_POLICY,
        tools_requiring_confirmation_provider=lambda: runtime.TOOLS_REQUIRING_CONFIRMATION,
        web_research_synthesis_prompt_provider=lambda: runtime.WEB_RESEARCH_SYNTHESIS_PROMPT,
        web_research_tools_provider=lambda: runtime.WEB_RESEARCH_TOOLS,
        config_provider=lambda: runtime.config,
        context_builder_provider=lambda: runtime.g_context_builder,
        memory_store_provider=lambda: runtime.g_memory_store,
        runtime_policy_controller_provider=lambda: runtime.g_runtime_policy_controller,
        security_policy_provider=lambda: runtime.g_security_policy,
        skill_evolution_provider=lambda: runtime.g_skill_evolution,
        upstream_provider_provider=lambda: runtime.g_upstream_provider,
        vector_store_provider=lambda: runtime.g_vector_store,
        http_client_provider=lambda: runtime.http_client,
        logger_provider=lambda: runtime.logger,
        tools_def_provider=lambda: runtime.tools_def,
    )

    from api.pages import PagesAPI
    pages_api = PagesAPI(
        static_dir_provider=lambda: runtime.STATIC_DIR,
    )
    app.include_router(pages_api.router)

    from api.system import SystemAPI
    system_api = SystemAPI(
        _system_readiness_payload=runtime._system_readiness_payload,
        get_maintenance_service=runtime.get_maintenance_service,
        model_mode_label=runtime.model_mode_label,
        model_provider_status=runtime.model_provider_status,
        data_dir_provider=lambda: runtime.DATA_DIR,
        memory_db_provider=lambda: runtime.MEMORY_DB,
        output_root_provider=lambda: runtime.OUTPUT_ROOT,
        runtime_release_provider=lambda: runtime.RUNTIME_RELEASE,
        config_provider=lambda: runtime.config,
        memory_store_provider=lambda: runtime.g_memory_store,
        mtclaw_adapter_provider=lambda: runtime.g_mtclaw_adapter,
        policy_optimizer_provider=lambda: runtime.g_policy_optimizer,
        reflection_engine_provider=lambda: runtime.g_reflection_engine,
        secret_manager_provider=lambda: runtime.g_secret_manager,
        security_policy_provider=lambda: runtime.g_security_policy,
        skill_evolution_provider=lambda: runtime.g_skill_evolution,
        vector_store_provider=lambda: runtime.g_vector_store,
        workspace_services_provider=lambda: runtime.g_workspace_services,
        tools_def_provider=lambda: runtime.tools_def,
    )
    app.include_router(system_api.router)

    from api.runtime import RuntimeAPI
    runtime_api = RuntimeAPI(
        _competition_hardware_evidence=runtime._competition_hardware_evidence,
        get_evaluation_service=runtime.get_evaluation_service,
        get_task_service=runtime.get_task_service,
        get_workflow_engine=runtime.get_workflow_engine,
        output_root_provider=lambda: runtime.OUTPUT_ROOT,
        runtime_release_provider=lambda: runtime.RUNTIME_RELEASE,
        memory_store_provider=lambda: runtime.g_memory_store,
    )
    app.include_router(runtime_api.router)

    from api.config import ConfigAPI
    config_api = ConfigAPI(
        apply_model_config_updates=runtime.apply_model_config_updates,
        model_config_payload=runtime.model_config_payload,
        config_provider=lambda: runtime.config,
    )
    app.include_router(config_api.router)

    from api.model import ModelAPI
    model_api = ModelAPI(
        _provider_candidates=lambda *args, **kwargs: runtime._provider_candidates(*args, **kwargs),
        local_model_assets_status=runtime.local_model_assets_status,
        http_client_provider=lambda: runtime.http_client,
    )
    app.include_router(model_api.router)

    from api.reflection import ReflectionAPI
    reflection_api = ReflectionAPI(
        memory_store_provider=lambda: runtime.g_memory_store,
        reflection_engine_provider=lambda: runtime.g_reflection_engine,
        vector_store_provider=lambda: runtime.g_vector_store,
    )
    app.include_router(reflection_api.router)

    from api.self_evolution import SelfEvolutionAPI
    self_evolution_api = SelfEvolutionAPI(
        _collaboration=lambda *args, **kwargs: runtime._collaboration(*args, **kwargs),
        _evolution_json=runtime._evolution_json,
        enqueue_runtime_task=runtime.enqueue_runtime_task,
        memory_store_provider=lambda: runtime.g_memory_store,
        routing_provider_provider=lambda: runtime.g_routing_provider,
        http_client_provider=lambda: runtime.http_client,
    )
    app.include_router(self_evolution_api.router)

    from api.evolution_review import EvolutionReviewAPI
    evolution_review_api = EvolutionReviewAPI(
        _collaboration=lambda *args, **kwargs: runtime._collaboration(*args, **kwargs),
        _evolution_json=runtime._evolution_json,
        memory_store_provider=lambda: runtime.g_memory_store,
    )
    app.include_router(evolution_review_api.router)

    from api.policy import PolicyAPI
    policy_api = PolicyAPI(
        build_routing_strategy=lambda *args, **kwargs: execution_api.build_routing_strategy(*args, **kwargs),
        score_scenarios=lambda *args, **kwargs: execution_api.score_scenarios(*args, **kwargs),
        scenario_routing_policy_provider=lambda: runtime.SCENARIO_ROUTING_POLICY,
        policy_optimizer_provider=lambda: runtime.g_policy_optimizer,
    )
    app.include_router(policy_api.router)

    from api.agent_learning import AgentLearningAPI
    agent_learning_api = AgentLearningAPI(
        output_root_provider=lambda: runtime.OUTPUT_ROOT,
        memory_store_provider=lambda: runtime.g_memory_store,
    )
    app.include_router(agent_learning_api.router)

    from api.coding_agent import CodingAgentAPI
    coding_agent_api = CodingAgentAPI(
        _competition_hardware_evidence=runtime._competition_hardware_evidence,
        base_dir_provider=lambda: runtime.BASE_DIR,
        output_root_provider=lambda: runtime.OUTPUT_ROOT,
        memory_store_provider=lambda: runtime.g_memory_store,
    )
    app.include_router(coding_agent_api.router)

    from api.security import SecurityAPI
    security_api = SecurityAPI(
        get_security_service=runtime.get_security_service,
        output_root_provider=lambda: runtime.OUTPUT_ROOT,
    )
    app.include_router(security_api.router)

    from api.workspace import WorkspaceAPI
    workspace_api = WorkspaceAPI(
        local_asr_capability=runtime.local_asr_capability,
        security_policy_provider=lambda: runtime.g_security_policy,
        workspace_services_provider=lambda: runtime.g_workspace_services,
    )
    app.include_router(workspace_api.router)

    from api.workspace_office import WorkspaceOfficeAPI
    workspace_office_api = WorkspaceOfficeAPI(
        get_office_productivity_service=lambda *args, **kwargs: runtime.get_office_productivity_service(*args, **kwargs),
        workspace_services_provider=lambda: runtime.g_workspace_services,
    )
    app.include_router(workspace_office_api.router)

    from api.feishu import FeishuAPI
    feishu_api = FeishuAPI(
        _collaboration=lambda *args, **kwargs: runtime._collaboration(*args, **kwargs),
        _feishu_service=runtime._feishu_service,
        _learning_product=lambda *args, **kwargs: runtime._learning_product(*args, **kwargs),
    )
    app.include_router(feishu_api.router)

    from api.workspace_meetings import WorkspaceMeetingsAPI
    workspace_meetings_api = WorkspaceMeetingsAPI(
        upload_dir_provider=lambda: runtime.UPLOAD_DIR,
        vector_store_provider=lambda: runtime.g_vector_store,
        workspace_services_provider=lambda: runtime.g_workspace_services,
    )
    app.include_router(workspace_meetings_api.router)

    from api.workspace_research import WorkspaceResearchAPI
    workspace_research_api = WorkspaceResearchAPI(
        call_model_with_fallback=lambda *args, **kwargs: execution_api.call_model_with_fallback(*args, **kwargs),
        get_artifact_delivery_service=runtime.get_artifact_delivery_service,
        get_paper_intelligence_service=runtime.get_paper_intelligence_service,
        memory_store_provider=lambda: runtime.g_memory_store,
        vector_store_provider=lambda: runtime.g_vector_store,
        workspace_services_provider=lambda: runtime.g_workspace_services,
    )
    app.include_router(workspace_research_api.router)

    from api.research import ResearchAPI
    research_api = ResearchAPI(
        get_paper_intelligence_service=runtime.get_paper_intelligence_service,
        get_scholarly_search_service=runtime.get_scholarly_search_service,
        upload_dir_provider=lambda: runtime.UPLOAD_DIR,
        memory_store_provider=lambda: runtime.g_memory_store,
        security_policy_provider=lambda: runtime.g_security_policy,
        vector_store_provider=lambda: runtime.g_vector_store,
    )
    app.include_router(research_api.router)

    from api.workspace_learning import WorkspaceLearningAPI
    workspace_learning_api = WorkspaceLearningAPI(
        workspace_services_provider=lambda: runtime.g_workspace_services,
    )
    app.include_router(workspace_learning_api.router)

    from api.academy_learning import AcademyLearningAPI
    academy_learning_api = AcademyLearningAPI(
        _learning_product=lambda *args, **kwargs: runtime._learning_product(*args, **kwargs),
        _rag_workshop=lambda *args, **kwargs: runtime._rag_workshop(*args, **kwargs),
        call_routing_llm=lambda *args, **kwargs: runtime.call_routing_llm(*args, **kwargs),
        logger_provider=lambda: runtime.logger,
    )
    app.include_router(academy_learning_api.router)

    from api.workspace_git import WorkspaceGitAPI
    workspace_git_api = WorkspaceGitAPI(
        workspace_services_provider=lambda: runtime.g_workspace_services,
    )
    app.include_router(workspace_git_api.router)

    from api.workspace_coding import WorkspaceCodingAPI
    workspace_coding_api = WorkspaceCodingAPI(
        get_coding_workflow_service=runtime.get_coding_workflow_service,
        output_root_provider=lambda: runtime.OUTPUT_ROOT,
        context_builder_provider=lambda: runtime.g_context_builder,
        memory_store_provider=lambda: runtime.g_memory_store,
        security_policy_provider=lambda: runtime.g_security_policy,
        upstream_provider_provider=lambda: runtime.g_upstream_provider,
        workspace_services_provider=lambda: runtime.g_workspace_services,
    )
    app.include_router(workspace_coding_api.router)

    from api.subagents import SubagentsAPI
    subagents_api = SubagentsAPI(
        get_autonomous_subagent_service=runtime.get_autonomous_subagent_service,
        get_reliable_collaboration_service=lambda *args, **kwargs: runtime.get_reliable_collaboration_service(*args, **kwargs),
    )
    app.include_router(subagents_api.router)

    from api.memory import MemoryAPI
    memory_api = MemoryAPI(
        list_memory_items=runtime.list_memory_items,
        save_memory_item=runtime.save_memory_item,
        set_memory_item_enabled=runtime.set_memory_item_enabled,
        memory_store_provider=lambda: runtime.g_memory_store,
        vector_store_provider=lambda: runtime.g_vector_store,
    )
    app.include_router(memory_api.router)

    from api.knowledge import KnowledgeAPI
    knowledge_api = KnowledgeAPI(
        get_knowledge_service=lambda *args, **kwargs: runtime.get_knowledge_service(*args, **kwargs),
        resolve_obsidian_output_dir=runtime.resolve_obsidian_output_dir,
        output_root_provider=lambda: runtime.OUTPUT_ROOT,
        memory_store_provider=lambda: runtime.g_memory_store,
        vector_store_provider=lambda: runtime.g_vector_store,
    )
    app.include_router(knowledge_api.router)

    from api.documents import DocumentsAPI
    documents_api = DocumentsAPI(
        get_document_index_worker=runtime.get_document_index_worker,
        get_document_review_service=lambda *args, **kwargs: runtime.get_document_review_service(*args, **kwargs),
        get_knowledge_service=lambda *args, **kwargs: runtime.get_knowledge_service(*args, **kwargs),
        get_paper_intelligence_service=runtime.get_paper_intelligence_service,
        data_dir_provider=lambda: runtime.DATA_DIR,
        output_root_provider=lambda: runtime.OUTPUT_ROOT,
        upload_dir_provider=lambda: runtime.UPLOAD_DIR,
        _pdf_page_renderer_provider=lambda: runtime._pdf_page_renderer,
        document_index_worker_provider=lambda: runtime.g_document_index_worker,
        memory_store_provider=lambda: runtime.g_memory_store,
        vector_store_provider=lambda: runtime.g_vector_store,
    )
    app.include_router(documents_api.router)

    from api.academy_paper import AcademyPaperAPI
    academy_paper_api = AcademyPaperAPI(
        _academy_offline_audit_payload=runtime._academy_offline_audit_payload,
        output_root_provider=lambda: runtime.OUTPUT_ROOT,
        memory_store_provider=lambda: runtime.g_memory_store,
    )
    app.include_router(academy_paper_api.router)

    from api.workbench import WorkbenchAPI
    workbench_api = WorkbenchAPI(
        _academy_count_run_records=runtime._academy_count_run_records,
        _academy_offline_audit_payload=runtime._academy_offline_audit_payload,
        _local_qwen_smoke_check=lambda *args, **kwargs: runtime._local_qwen_smoke_check(*args, **kwargs),
        _system_readiness_payload=runtime._system_readiness_payload,
        local_model_assets_status=runtime.local_model_assets_status,
        base_dir_provider=lambda: runtime.BASE_DIR,
        output_root_provider=lambda: runtime.OUTPUT_ROOT,
        memory_store_provider=lambda: runtime.g_memory_store,
    )
    app.include_router(workbench_api.router)

    from api.artifacts import ArtifactsAPI
    artifacts_api = ArtifactsAPI(
        get_artifact_delivery_service=runtime.get_artifact_delivery_service,
    )
    app.include_router(artifacts_api.router)

    from api.coding import CodingAPI
    coding_api = CodingAPI(
        get_artifact_delivery_service=runtime.get_artifact_delivery_service,
        output_root_provider=lambda: runtime.OUTPUT_ROOT,
    )
    app.include_router(coding_api.router)

    from api.office import OfficeAPI
    office_api = OfficeAPI(
        get_artifact_delivery_service=runtime.get_artifact_delivery_service,
        logger_provider=lambda: runtime.logger,
    )
    app.include_router(office_api.router)

    from api.tasks import TasksAPI
    tasks_api = TasksAPI(
        start_background_worker=runtime.start_background_worker,
        stop_background_worker=runtime.stop_background_worker,
        cancel_runtime_task=runtime.cancel_runtime_task,
        claim_runtime_task=runtime.claim_runtime_task,
        enqueue_runtime_task=runtime.enqueue_runtime_task,
        get_task_service=runtime.get_task_service,
        retry_runtime_task=runtime.retry_runtime_task,
        run_background_worker_once=runtime.run_background_worker_once,
    )
    app.include_router(tasks_api.router)

    from api.benchmarks import BenchmarksAPI
    benchmarks_api = BenchmarksAPI(
        create_runtime_task=runtime.create_runtime_task,
        execute_tool_call=lambda *args, **kwargs: runtime.execute_tool_call(*args, **kwargs),
        finish_runtime_task=runtime.finish_runtime_task,
        scenario_benchmark_provider=lambda: runtime.g_scenario_benchmark,
    )
    app.include_router(benchmarks_api.router)

    from api.skills import SkillsAPI
    skills_api = SkillsAPI(
        memory_store_provider=lambda: runtime.g_memory_store,
        skill_evolution_provider=lambda: runtime.g_skill_evolution,
    )
    app.include_router(skills_api.router)

    from api.tools import ToolsAPI
    tools_api = ToolsAPI(
        memory_store_provider=lambda: runtime.g_memory_store,
        tools_def_provider=lambda: runtime.tools_def,
    )
    app.include_router(tools_api.router)

    app.include_router(create_task_query_router(
        runtime.get_task_service,
        memory_available=lambda: bool(runtime.g_memory_store),
        events_available=lambda: bool(runtime.g_task_service or runtime.g_memory_store),
        worker_status=runtime.background_worker_status,
    ))
    return {
        'api_tasks_worker_start': tasks_api.api_tasks_worker_start,
        'api_tasks_worker_stop': tasks_api.api_tasks_worker_stop,
        '_record_mtclaw_task_steps': chat_api._record_mtclaw_task_steps,
        '_confirmed_tools_from_request': chat_api._confirmed_tools_from_request,
        'list_models': chat_api.list_models,
        '_build_attachment_context': chat_api._build_attachment_context,
        '_build_uploaded_document_context': chat_api._build_uploaded_document_context,
        'chat_completions': chat_api.chat_completions,
        '_tool_service': execution_api._tool_service,
        'call_model_with_fallback': execution_api.call_model_with_fallback,
        'classify_scenario': execution_api.classify_scenario,
        'score_scenarios': execution_api.score_scenarios,
        'build_routing_strategy': execution_api.build_routing_strategy,
        'apply_web_search_policy': execution_api.apply_web_search_policy,
        'web_search_prompt_policy': execution_api.web_search_prompt_policy,
        'execute_coding_agent_call': execution_api.execute_coding_agent_call,
        'tool_result_for_model': execution_api.tool_result_for_model,
        'resolve_runtime_policies': execution_api.resolve_runtime_policies,
        'runtime_policy_trace': execution_api.runtime_policy_trace,
        'evaluate_shadow_policies': execution_api.evaluate_shadow_policies,
        'tools_for_routing_strategy': execution_api.tools_for_routing_strategy,
        'rule_based_tool': execution_api.rule_based_tool,
        'run_tool_loop': execution_api.run_tool_loop,
        'build_openai_response': execution_api.build_openai_response,
        'extract_assistant_text': execution_api.extract_assistant_text,
        'root': pages_api.root,
        'product_page': pages_api.product_page,
        'academy_page': pages_api.academy_page,
        'academy_path_page': pages_api.academy_path_page,
        'academy_paper_page': pages_api.academy_paper_page,
        'academy_code_page': pages_api.academy_code_page,
        'academy_rag_page': pages_api.academy_rag_page,
        'academy_notes_page': pages_api.academy_notes_page,
        'academy_ingest_page': pages_api.academy_ingest_page,
        'academy_quiz_page': pages_api.academy_quiz_page,
        'console_page': pages_api.console_page,
        'evolution_review_page': pages_api.evolution_review_page,
        'academy_lab_page': pages_api.academy_lab_page,
        'research_watch_page': pages_api.research_watch_page,
        'data_lab_page': pages_api.data_lab_page,
        'meetings_page': pages_api.meetings_page,
        'academy_materials_page': pages_api.academy_materials_page,
        'health': system_api.health,
        'api_system_config_check': system_api.api_system_config_check,
        'api_system_migrations': system_api.api_system_migrations,
        'api_system_migrations_apply': system_api.api_system_migrations_apply,
        'api_system_backup': system_api.api_system_backup,
        'api_system_restore': system_api.api_system_restore,
        'api_system_backup_bundle': system_api.api_system_backup_bundle,
        'api_system_restore_drill': system_api.api_system_restore_drill,
        'api_system_readiness': system_api.api_system_readiness,
        'architecture_chain': system_api.architecture_chain,
        'runtime_release': runtime_api.runtime_release,
        '_competition_readiness_snapshot': runtime_api._competition_readiness_snapshot,
        'api_competition_readiness': runtime_api.api_competition_readiness,
        'api_competition_hardware_evidence_validate': runtime_api.api_competition_hardware_evidence_validate,
        'api_competition_readiness_export': runtime_api.api_competition_readiness_export,
        'api_latest_deepseek_qwen_acceptance': runtime_api.api_latest_deepseek_qwen_acceptance,
        'api_latest_search_live_acceptance': runtime_api.api_latest_search_live_acceptance,
        'api_runtime_schema': runtime_api.api_runtime_schema,
        'api_runtime_runs_latest': runtime_api.api_runtime_runs_latest,
        'api_runtime_failure_cases': runtime_api.api_runtime_failure_cases,
        'api_runtime_evidence_chains': runtime_api.api_runtime_evidence_chains,
        'api_runtime_evidence_chain_verify': runtime_api.api_runtime_evidence_chain_verify,
        'get_model_config': config_api.get_model_config,
        'update_model_config': config_api.update_model_config,
        'api_model_health': model_api.api_model_health,
        'trigger_reflection': reflection_api.trigger_reflection,
        'list_reflections': reflection_api.list_reflections,
        'reflection_card_detail': reflection_api.reflection_card_detail,
        'reflection_card_feedback': reflection_api.reflection_card_feedback,
        'reflection_improvements': reflection_api.reflection_improvements,
        'reflection_improvement_transition': reflection_api.reflection_improvement_transition,
        'reflection_improvement_validate': reflection_api.reflection_improvement_validate,
        'reflection_improvement_publish': reflection_api.reflection_improvement_publish,
        'reflection_improvement_rollback': reflection_api.reflection_improvement_rollback,
        'reflection_stats': reflection_api.reflection_stats,
        'api_self_evolution_runs': self_evolution_api.api_self_evolution_runs,
        'api_self_evolution_board': self_evolution_api.api_self_evolution_board,
        'api_evolution_experiments': self_evolution_api.api_evolution_experiments,
        'api_evolution_experiment_detail': self_evolution_api.api_evolution_experiment_detail,
        'api_evolution_experiment_freeze': self_evolution_api.api_evolution_experiment_freeze,
        'api_evolution_experiment_replay': self_evolution_api.api_evolution_experiment_replay,
        'api_evolution_experiment_nominate': self_evolution_api.api_evolution_experiment_nominate,
        'api_evolution_experiment_control': self_evolution_api.api_evolution_experiment_control,
        'api_evolution_review_outputs': self_evolution_api.api_evolution_review_outputs,
        'api_evolution_review_submit': self_evolution_api.api_evolution_review_submit,
        'api_evolution_review_get': self_evolution_api.api_evolution_review_get,
        'api_evolution_capture_plan': self_evolution_api.api_evolution_capture_plan,
        'api_evolution_capture_execute': self_evolution_api.api_evolution_capture_execute,
        'api_evolution_capture_pause': self_evolution_api.api_evolution_capture_pause,
        'api_evolution_capture_receipts': self_evolution_api.api_evolution_capture_receipts,
        'api_evolution_review_users': self_evolution_api.api_evolution_review_users,
        'api_evolution_review_grant': self_evolution_api.api_evolution_review_grant,
        'api_self_evolution_create_run': self_evolution_api.api_self_evolution_create_run,
        'api_self_evolution_candidate': self_evolution_api.api_self_evolution_candidate,
        'api_self_evolution_evaluate': self_evolution_api.api_self_evolution_evaluate,
        'api_self_evolution_publish': self_evolution_api.api_self_evolution_publish,
        'api_self_evolution_quality_signal': self_evolution_api.api_self_evolution_quality_signal,
        'api_self_evolution_quality_snapshot': self_evolution_api.api_self_evolution_quality_snapshot,
        'api_self_evolution_canary': self_evolution_api.api_self_evolution_canary,
        'api_self_evolution_activate': self_evolution_api.api_self_evolution_activate,
        'api_self_evolution_rollback': self_evolution_api.api_self_evolution_rollback,
        '_evolution_review_access': evolution_review_api._evolution_review_access,
        'api_evolution_assigned_packet': evolution_review_api.api_evolution_assigned_packet,
        'api_evolution_assigned_ratings': evolution_review_api.api_evolution_assigned_ratings,
        'api_evolution_assigned_adjudication': evolution_review_api.api_evolution_assigned_adjudication,
        'api_policy_group_register': policy_api.api_policy_group_register,
        'api_policy_select': policy_api.api_policy_select,
        'api_policy_reward': policy_api.api_policy_reward,
        'api_policy_stats': policy_api.api_policy_stats,
        'api_policy_promote': policy_api.api_policy_promote,
        'api_policy_promotion_rollback': policy_api.api_policy_promotion_rollback,
        'api_routing_policy': policy_api.api_routing_policy,
        'api_agent_learning_trajectories': agent_learning_api.api_agent_learning_trajectories,
        'api_agent_learning_trajectory': agent_learning_api.api_agent_learning_trajectory,
        'api_agent_learning_dataset': agent_learning_api.api_agent_learning_dataset,
        'api_agent_learning_preference': agent_learning_api.api_agent_learning_preference,
        'api_agent_learning_feedback': agent_learning_api.api_agent_learning_feedback,
        'api_agent_learning_data_quality': agent_learning_api.api_agent_learning_data_quality,
        'api_agent_learning_reward_calibrations': agent_learning_api.api_agent_learning_reward_calibrations,
        'api_agent_learning_reward_calibration_train': agent_learning_api.api_agent_learning_reward_calibration_train,
        'api_agent_learning_reward_calibration_evaluate': agent_learning_api.api_agent_learning_reward_calibration_evaluate,
        'api_agent_learning_reward_calibration_activate': agent_learning_api.api_agent_learning_reward_calibration_activate,
        'api_agent_learning_preference_ranker_readiness': agent_learning_api.api_agent_learning_preference_ranker_readiness,
        'api_agent_learning_preference_ranker_models': agent_learning_api.api_agent_learning_preference_ranker_models,
        'api_agent_learning_preference_ranker_train': agent_learning_api.api_agent_learning_preference_ranker_train,
        'api_agent_learning_preference_ranker_evaluate': agent_learning_api.api_agent_learning_preference_ranker_evaluate,
        'api_agent_learning_preference_ranker_activate': agent_learning_api.api_agent_learning_preference_ranker_activate,
        'api_agent_learning_preference_ranker_rank': agent_learning_api.api_agent_learning_preference_ranker_rank,
        'api_agent_learning_advanced_readiness': agent_learning_api.api_agent_learning_advanced_readiness,
        'api_agent_learning_ope_evaluate': agent_learning_api.api_agent_learning_ope_evaluate,
        'api_agent_learning_trajectory_ranker_train': agent_learning_api.api_agent_learning_trajectory_ranker_train,
        'api_agent_learning_offline_policy_sandbox': agent_learning_api.api_agent_learning_offline_policy_sandbox,
        'api_agent_learning_artifacts': agent_learning_api.api_agent_learning_artifacts,
        'api_agent_learning_artifact_transition': agent_learning_api.api_agent_learning_artifact_transition,
        'api_agent_learning_models': agent_learning_api.api_agent_learning_models,
        'api_agent_learning_train': agent_learning_api.api_agent_learning_train,
        'api_agent_learning_evaluate': agent_learning_api.api_agent_learning_evaluate,
        'api_agent_learning_activate': agent_learning_api.api_agent_learning_activate,
        'api_agent_learning_rollback': agent_learning_api.api_agent_learning_rollback,
        'api_coding_agent_readiness': coding_agent_api.api_coding_agent_readiness,
        'api_coding_agent_evidence': coding_agent_api.api_coding_agent_evidence,
        'api_coding_agent_evidence_record': coding_agent_api.api_coding_agent_evidence_record,
        'api_security_audit': security_api.api_security_audit,
        'api_secret_register': security_api.api_secret_register,
        'api_secret_list': security_api.api_secret_list,
        'api_security_policy_check': security_api.api_security_policy_check,
        'api_security_policy_grants': security_api.api_security_policy_grants,
        'api_security_policy_grant_create': security_api.api_security_policy_grant_create,
        'api_security_policy_grant_revoke': security_api.api_security_policy_grant_revoke,
        'api_appcontainer_status': security_api.api_appcontainer_status,
        'api_appcontainer_change': security_api.api_appcontainer_change,
        'api_workspace_capabilities': workspace_api.api_workspace_capabilities,
        'api_templates_list': workspace_api.api_templates_list,
        'api_template_register': workspace_api.api_template_register,
        'api_template_instantiate': workspace_api.api_template_instantiate,
        'api_office_spreadsheet_create': workspace_office_api.api_office_spreadsheet_create,
        'api_office_spreadsheet_edit': workspace_office_api.api_office_spreadsheet_edit,
        'api_office_presentation_create': workspace_office_api.api_office_presentation_create,
        'api_office_presentation_edit': workspace_office_api.api_office_presentation_edit,
        'api_office_productivity': workspace_office_api.api_office_productivity,
        '_feishu_status_for': feishu_api._feishu_status_for,
        '_feishu_validate': feishu_api._feishu_validate,
        'api_feishu_health': feishu_api.api_feishu_health,
        'api_feishu_events': feishu_api.api_feishu_events,
        'api_feishu_messages': feishu_api.api_feishu_messages,
        'api_feishu_summaries_create': feishu_api.api_feishu_summaries_create,
        'api_feishu_summaries_update': feishu_api.api_feishu_summaries_update,
        'api_feishu_summaries_list': feishu_api.api_feishu_summaries_list,
        'api_feishu_approvals_create': feishu_api.api_feishu_approvals_create,
        'api_feishu_approvals_sync': feishu_api.api_feishu_approvals_sync,
        'api_feishu_approvals_send': feishu_api.api_feishu_approvals_send,
        'api_feishu_dispatches': feishu_api.api_feishu_dispatches,
        'api_feishu_approvals_list': feishu_api.api_feishu_approvals_list,
        'feishu_permissions': feishu_api.feishu_permissions,
        'feishu_document_draft': feishu_api.feishu_document_draft,
        'api_meeting_create': workspace_meetings_api.api_meeting_create,
        'api_meeting_transcript': workspace_meetings_api.api_meeting_transcript,
        'api_meeting_audio_import': workspace_meetings_api.api_meeting_audio_import,
        'api_meeting_audio_upload': workspace_meetings_api.api_meeting_audio_upload,
        'api_meeting_connector_drafts': workspace_meetings_api.api_meeting_connector_drafts,
        'api_meeting_detail': workspace_meetings_api.api_meeting_detail,
        'api_research_import': workspace_research_api.api_research_import,
        'api_research_search': workspace_research_api.api_research_search,
        'api_research_citations_validate': workspace_research_api.api_research_citations_validate,
        'api_research_compare_matrix': workspace_research_api.api_research_compare_matrix,
        'api_research_repro_workflow': workspace_research_api.api_research_repro_workflow,
        'api_research_learning_analysis': workspace_research_api.api_research_learning_analysis,
        'api_paper_structure': research_api.api_paper_structure,
        'api_claim_citation_alignment': research_api.api_claim_citation_alignment,
        'api_paper_comparison': research_api.api_paper_comparison,
        'api_paper_readiness': research_api.api_paper_readiness,
        'api_scholarly_search': research_api.api_scholarly_search,
        'api_scholarly_open_access': research_api.api_scholarly_open_access,
        'api_scholarly_download': research_api.api_scholarly_download,
        'api_learning_goal_create': workspace_learning_api.api_learning_goal_create,
        'api_learning_goal_detail': workspace_learning_api.api_learning_goal_detail,
        'api_learning_review': workspace_learning_api.api_learning_review,
        'api_learning_dependency': workspace_learning_api.api_learning_dependency,
        'api_learning_mistake': workspace_learning_api.api_learning_mistake,
        'api_learning_graph': workspace_learning_api.api_learning_graph,
        'api_learning_assessment': workspace_learning_api.api_learning_assessment,
        'api_academy_learning_courses': academy_learning_api.api_academy_learning_courses,
        'api_academy_create_course': academy_learning_api.api_academy_create_course,
        'api_academy_learning_enroll': academy_learning_api.api_academy_learning_enroll,
        'api_academy_learning_dashboard': academy_learning_api.api_academy_learning_dashboard,
        'api_academy_learning_quiz': academy_learning_api.api_academy_learning_quiz,
        '_academy_studio': academy_learning_api._academy_studio,
        'api_academy_rag': academy_learning_api.api_academy_rag,
        'api_academy_rag_action': academy_learning_api.api_academy_rag_action,
        'api_academy_rag_export': academy_learning_api.api_academy_rag_export,
        'api_academy_studio': academy_learning_api.api_academy_studio,
        'api_academy_studio_start': academy_learning_api.api_academy_studio_start,
        'api_academy_studio_save': academy_learning_api.api_academy_studio_save,
        'api_academy_learning_answer': academy_learning_api.api_academy_learning_answer,
        'api_academy_learning_mistakes': academy_learning_api.api_academy_learning_mistakes,
        'api_academy_resolve_mistake': academy_learning_api.api_academy_resolve_mistake,
        'api_academy_explain_mastery': academy_learning_api.api_academy_explain_mastery,
        'api_academy_learning_project_evidence': academy_learning_api.api_academy_learning_project_evidence,
        'api_academy_add_question': academy_learning_api.api_academy_add_question,
        'api_academy_course_publish_validation': academy_learning_api.api_academy_course_publish_validation,
        'api_academy_publish_course': academy_learning_api.api_academy_publish_course,
        'api_git_snapshot': workspace_git_api.api_git_snapshot,
        'api_git_commit_plan': workspace_git_api.api_git_commit_plan,
        'api_git_change_request': workspace_git_api.api_git_change_request,
        'api_git_change_request_approve': workspace_git_api.api_git_change_request_approve,
        'api_git_change_request_rollback': workspace_git_api.api_git_change_request_rollback,
        'api_coding_workflow': workspace_coding_api.api_coding_workflow,
        'api_coding_strategy': workspace_coding_api.api_coding_strategy,
        'api_autonomous_coding': workspace_coding_api.api_autonomous_coding,
        'api_coding_ide_context': workspace_coding_api.api_coding_ide_context,
        'api_coding_repository_intelligence': workspace_coding_api.api_coding_repository_intelligence,
        'api_coding_lsp_probe': workspace_coding_api.api_coding_lsp_probe,
        'api_coding_lsp_discovery': workspace_coding_api.api_coding_lsp_discovery,
        'api_coding_lsp_semantic_graph': workspace_coding_api.api_coding_lsp_semantic_graph,
        'api_coding_multilanguage_benchmark': workspace_coding_api.api_coding_multilanguage_benchmark,
        'api_coding_oss_corpus_benchmark': workspace_coding_api.api_coding_oss_corpus_benchmark,
        'api_coding_outcome_benchmark': workspace_coding_api.api_coding_outcome_benchmark,
        'api_coding_review_gate': workspace_coding_api.api_coding_review_gate,
        'api_coding_worktree_create': workspace_coding_api.api_coding_worktree_create,
        'api_coding_worktree_status': workspace_coding_api.api_coding_worktree_status,
        'api_coding_worktree_merge_plan': workspace_coding_api.api_coding_worktree_merge_plan,
        'api_coding_worktree_remove': workspace_coding_api.api_coding_worktree_remove,
        'api_coding_workspace_commit': workspace_coding_api.api_coding_workspace_commit,
        'api_autonomous_subagents': subagents_api.api_autonomous_subagents,
        'api_collaboration_progress': subagents_api.api_collaboration_progress,
        'api_collaboration_delivery': subagents_api.api_collaboration_delivery,
        'api_collaboration_delivery_approve': subagents_api.api_collaboration_delivery_approve,
        'memory_stats': memory_api.memory_stats,
        'api_memory_items': memory_api.api_memory_items,
        'api_memory_item_save': memory_api.api_memory_item_save,
        'api_memory_item_enabled': memory_api.api_memory_item_enabled,
        'api_memory_items_search': memory_api.api_memory_items_search,
        'api_selective_memory_propose': memory_api.api_selective_memory_propose,
        'api_selective_memory_list': memory_api.api_selective_memory_list,
        'api_selective_memory_review': memory_api.api_selective_memory_review,
        'api_selective_memory_promote': memory_api.api_selective_memory_promote,
        'api_memory_versions': memory_api.api_memory_versions,
        'api_memory_evidence': memory_api.api_memory_evidence,
        'api_memory_reviews': memory_api.api_memory_reviews,
        'api_memory_review_resolve': memory_api.api_memory_review_resolve,
        'api_memory_acl': memory_api.api_memory_acl,
        'api_memory_acl_grant': memory_api.api_memory_acl_grant,
        'api_memory_evaluation_run': memory_api.api_memory_evaluation_run,
        'api_memory_profiles': memory_api.api_memory_profiles,
        'api_memory_profile_set': memory_api.api_memory_profile_set,
        'api_memory_preferences': memory_api.api_memory_preferences,
        'api_memory_preference_set': memory_api.api_memory_preference_set,
        'api_memory_experiences': memory_api.api_memory_experiences,
        'api_mtclaw_traces': memory_api.api_mtclaw_traces,
        'memory_context': memory_api.memory_context,
        'get_history': memory_api.get_history,
        'api_list_sessions': memory_api.api_list_sessions,
        'api_export_history': memory_api.api_export_history,
        'api_memory_search': memory_api.api_memory_search,
        'api_memory_refresh': memory_api.api_memory_refresh,
        'api_knowledge_list': knowledge_api.api_knowledge_list,
        'api_knowledge_save': knowledge_api.api_knowledge_save,
        'api_knowledge_update': knowledge_api.api_knowledge_update,
        'api_knowledge_delete': knowledge_api.api_knowledge_delete,
        'api_knowledge_search': knowledge_api.api_knowledge_search,
        'api_knowledge_context_pack': knowledge_api.api_knowledge_context_pack,
        'api_knowledge_answer': knowledge_api.api_knowledge_answer,
        'api_knowledge_v2_stats': knowledge_api.api_knowledge_v2_stats,
        'api_knowledge_v2_index_rebuild': knowledge_api.api_knowledge_v2_index_rebuild,
        'api_knowledge_v2_quality_latest': knowledge_api.api_knowledge_v2_quality_latest,
        'api_knowledge_v2_conflicts': knowledge_api.api_knowledge_v2_conflicts,
        'api_knowledge_v2_conflict_resolve': knowledge_api.api_knowledge_v2_conflict_resolve,
        'api_knowledge_v2_backfill': knowledge_api.api_knowledge_v2_backfill,
        'api_knowledge_v2_usage': knowledge_api.api_knowledge_v2_usage,
        'api_answer_quality_validate': knowledge_api.api_answer_quality_validate,
        'api_answer_quality_feedback': knowledge_api.api_answer_quality_feedback,
        'api_answer_quality_feedback_list': knowledge_api.api_answer_quality_feedback_list,
        'api_answer_quality_latest': knowledge_api.api_answer_quality_latest,
        'api_knowledge_graph': knowledge_api.api_knowledge_graph,
        'api_knowledge_obsidian_check': knowledge_api.api_knowledge_obsidian_check,
        'api_knowledge_obsidian_export': knowledge_api.api_knowledge_obsidian_export,
        'api_document_upload': documents_api.api_document_upload,
        'api_document_indexing_status': documents_api.api_document_indexing_status,
        'api_document_indexing_retry': documents_api.api_document_indexing_retry,
        'api_documents': documents_api.api_documents,
        'api_documents_ocr_queue': documents_api.api_documents_ocr_queue,
        'api_document_run_ocr': documents_api.api_document_run_ocr,
        'api_document_review': documents_api.api_document_review,
        'api_document_review_crop': documents_api.api_document_review_crop,
        'api_document_review_submit': documents_api.api_document_review_submit,
        'api_document_review_publish': documents_api.api_document_review_publish,
        'api_document_source': documents_api.api_document_source,
        'api_document_page': documents_api.api_document_page,
        'api_document_semantic_graph': documents_api.api_document_semantic_graph,
        'api_document_chunks': documents_api.api_document_chunks,
        'api_document_search': documents_api.api_document_search,
        'api_document_citation_answer': documents_api.api_document_citation_answer,
        'api_academy_paper_annotation_save': academy_paper_api.api_academy_paper_annotation_save,
        '_latest_academy_run_for_document': academy_paper_api._latest_academy_run_for_document,
        '_academy_knowledge_for_document': academy_paper_api._academy_knowledge_for_document,
        '_academy_paper_status_payload': academy_paper_api._academy_paper_status_payload,
        'api_academy_paper_status': academy_paper_api.api_academy_paper_status,
        'api_academy_paper_checkpoint_save': academy_paper_api.api_academy_paper_checkpoint_save,
        '_academy_checkpoint_artifact_path': academy_paper_api._academy_checkpoint_artifact_path,
        '_academy_checkpoint_summary': academy_paper_api._academy_checkpoint_summary,
        'api_academy_paper_checkpoints': academy_paper_api.api_academy_paper_checkpoints,
        'api_academy_paper_checkpoint_detail': academy_paper_api.api_academy_paper_checkpoint_detail,
        '_academy_project_item_summary': academy_paper_api._academy_project_item_summary,
        'api_academy_paper_project_board': academy_paper_api.api_academy_paper_project_board,
        'api_academy_paper_project_item_save': academy_paper_api.api_academy_paper_project_item_save,
        'api_academy_paper_project_item_status': academy_paper_api.api_academy_paper_project_item_status,
        'api_academy_paper_project_board_export': academy_paper_api.api_academy_paper_project_board_export,
        '_academy_project_export_artifact_path': academy_paper_api._academy_project_export_artifact_path,
        '_academy_project_export_summary': academy_paper_api._academy_project_export_summary,
        'api_academy_paper_project_exports': academy_paper_api.api_academy_paper_project_exports,
        '_academy_event_time': academy_paper_api._academy_event_time,
        '_academy_run_document_id': academy_paper_api._academy_run_document_id,
        '_academy_timeline_event': academy_paper_api._academy_timeline_event,
        '_academy_checkpoint_citation_payload': academy_paper_api._academy_checkpoint_citation_payload,
        '_academy_paper_timeline_payload': academy_paper_api._academy_paper_timeline_payload,
        'api_academy_paper_timeline': academy_paper_api.api_academy_paper_timeline,
        'api_academy_paper_offline_audit': academy_paper_api.api_academy_paper_offline_audit,
        'api_academy_paper_project_export_detail': academy_paper_api.api_academy_paper_project_export_detail,
        'api_academy_paper_knowledge_capture': academy_paper_api.api_academy_paper_knowledge_capture,
        '_workbench_offline_readiness_payload': workbench_api._workbench_offline_readiness_payload,
        'api_workbench_offline_readiness': workbench_api.api_workbench_offline_readiness,
        '_daily_local_acceptance_summary': workbench_api._daily_local_acceptance_summary,
        '_daily_acceptance_run_summary': workbench_api._daily_acceptance_run_summary,
        '_workbench_timeline_item': workbench_api._workbench_timeline_item,
        '_workbench_timeline_payload': workbench_api._workbench_timeline_payload,
        '_save_daily_acceptance_run': workbench_api._save_daily_acceptance_run,
        '_save_qwen_smoke_run': workbench_api._save_qwen_smoke_run,
        '_daily_local_acceptance_payload': workbench_api._daily_local_acceptance_payload,
        'api_workbench_daily_local_acceptance': workbench_api.api_workbench_daily_local_acceptance,
        'api_workbench_local_qwen_smoke': workbench_api.api_workbench_local_qwen_smoke,
        '_local_acceptance_runs': workbench_api._local_acceptance_runs,
        '_local_acceptance_trends': workbench_api._local_acceptance_trends,
        'api_workbench_local_timeline': workbench_api.api_workbench_local_timeline,
        'api_workbench_local_acceptance_history': workbench_api.api_workbench_local_acceptance_history,
        'api_workbench_local_acceptance_trends': workbench_api.api_workbench_local_acceptance_trends,
        '_remediation_action_for_gap': workbench_api._remediation_action_for_gap,
        '_remediation_action_key': workbench_api._remediation_action_key,
        '_remediation_action_statuses': workbench_api._remediation_action_statuses,
        '_local_remediation_payload': workbench_api._local_remediation_payload,
        'api_workbench_local_remediation_guide': workbench_api.api_workbench_local_remediation_guide,
        '_save_remediation_action_run': workbench_api._save_remediation_action_run,
        '_run_local_remediation_recheck': workbench_api._run_local_remediation_recheck,
        'api_workbench_local_remediation_action': workbench_api.api_workbench_local_remediation_action,
        'api_workbench_local_remediation_recheck': workbench_api.api_workbench_local_remediation_recheck,
        '_maintenance_report_markdown': workbench_api._maintenance_report_markdown,
        '_export_local_maintenance_report': workbench_api._export_local_maintenance_report,
        'api_workbench_local_maintenance_report': workbench_api.api_workbench_local_maintenance_report,
        '_maintenance_artifact_root': workbench_api._maintenance_artifact_root,
        '_maintenance_report_artifact_path': workbench_api._maintenance_report_artifact_path,
        '_read_maintenance_artifact': workbench_api._read_maintenance_artifact,
        '_maintenance_report_summary': workbench_api._maintenance_report_summary,
        'api_workbench_local_maintenance_reports': workbench_api.api_workbench_local_maintenance_reports,
        'api_workbench_local_maintenance_report_detail': workbench_api.api_workbench_local_maintenance_report_detail,
        'api_artifact_metadata': artifacts_api.api_artifact_metadata,
        'api_artifact_download': artifacts_api.api_artifact_download,
        'api_artifact_preview': artifacts_api.api_artifact_preview,
        'api_coding_workspaces': coding_api.api_coding_workspaces,
        'api_coding_workspace_rollback': coding_api.api_coding_workspace_rollback,
        'api_coding_workspaces_prune': coding_api.api_coding_workspaces_prune,
        'api_office_editor_capabilities': office_api.api_office_editor_capabilities,
        'api_office_editor_session': office_api.api_office_editor_session,
        'api_onlyoffice_editor_callback': office_api.api_onlyoffice_editor_callback,
        'api_tasks_queue_claim': tasks_api.api_tasks_queue_claim,
        'api_tasks_recover': tasks_api.api_tasks_recover,
        'api_tasks_worker_tick': tasks_api.api_tasks_worker_tick,
        'api_tasks_job_report': tasks_api.api_tasks_job_report,
        'api_tasks_job_ocr_queue': tasks_api.api_tasks_job_ocr_queue,
        'api_tasks_job_batch_ingest': tasks_api.api_tasks_job_batch_ingest,
        'api_task_events_prune': tasks_api.api_task_events_prune,
        'api_task_cancel': tasks_api.api_task_cancel,
        'api_task_retry': tasks_api.api_task_retry,
        'api_scenario_benchmark_suites': benchmarks_api.api_scenario_benchmark_suites,
        'api_scenario_benchmark_create_suite': benchmarks_api.api_scenario_benchmark_create_suite,
        'api_scenario_benchmark_runs': benchmarks_api.api_scenario_benchmark_runs,
        'api_scenario_benchmark_run': benchmarks_api.api_scenario_benchmark_run,
        'skills_list': skills_api.skills_list,
        'skills_execute': skills_api.skills_execute,
        'skills_stats': skills_api.skills_stats,
        'skill_evolution_versions': skills_api.skill_evolution_versions,
        'skill_evolution_runs': skills_api.skill_evolution_runs,
        'skill_evolution_review_inbox': skills_api.skill_evolution_review_inbox,
        'skill_evolution_candidate': skills_api.skill_evolution_candidate,
        'skill_evolution_suite': skills_api.skill_evolution_suite,
        'skill_evolution_evaluate': skills_api.skill_evolution_evaluate,
        'skill_evolution_promote': skills_api.skill_evolution_promote,
        'skill_evolution_review': skills_api.skill_evolution_review,
        'skill_evolution_manifest': skills_api.skill_evolution_manifest,
        'skill_evolution_sign': skills_api.skill_evolution_sign,
        'skill_evolution_fresh_audit': skills_api.skill_evolution_fresh_audit,
        'skill_evolution_canary': skills_api.skill_evolution_canary,
        'skill_evolution_rollback': skills_api.skill_evolution_rollback,
        'skill_evolution_library_health': skills_api.skill_evolution_library_health,
        'skill_evolution_library_compact': skills_api.skill_evolution_library_compact,
        'api_tools_list': tools_api.api_tools_list,
        'api_tool_executions': tools_api.api_tool_executions,
        'api_tools_accuracy': tools_api.api_tools_accuracy,
    }
