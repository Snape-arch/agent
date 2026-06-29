from pathlib import Path
import unittest


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
REPO_ROOT = Path(__file__).resolve().parents[2]


class FrontendStaticTests(unittest.TestCase):
    def read_page(self, name: str) -> str:
        return (STATIC_DIR / name).read_text(encoding="utf-8")

    def test_frontend_is_split_into_layered_pages(self):
        home = self.read_page("index.html")
        product = self.read_page("product.html")
        console = self.read_page("console.html")

        self.assertIn('href="/product"', home)
        self.assertIn("magazine-backdrop", home)
        self.assertIn('href="/console"', product)
        self.assertIn("Evidence Grid", product)
        self.assertIn("Runtime Map", product)
        self.assertIn('class="console-page aether-console"', console)

    def test_pages_use_clawos_assets_and_motion(self):
        home = self.read_page("index.html")
        product = self.read_page("product.html")

        self.assertIn("d55c96717921508cafd61730a1623e08.jpg", home)
        self.assertIn("starfield", home)
        self.assertIn("layer", home)
        self.assertIn("evidence", product.lower())
        self.assertIn("runtime", product.lower())

    def test_console_has_chat_first_information_architecture(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")

        self.assertIn('href="/assets/site.css"', html)
        self.assertIn('href="/assets/console.css"', html)
        self.assertIn('data-view="chat"', html)
        self.assertIn('data-action="new-chat"', html)
        self.assertIn("toggleSidebar", html + js)
        self.assertIn(".aether-console.sidebar-collapsed .side", css)
        self.assertIn("width:52px", css)
        self.assertIn(".aether-console.sidebar-collapsed .side-nav", css)
        self.assertIn('data-view="search"', html)
        self.assertIn('data-view="knowledge"', html)
        self.assertIn('data-view="projects"', html)
        self.assertIn("view-knowledge", html)
        self.assertIn("view-memory", html)
        self.assertIn("filePicker", html)
        self.assertIn("commandDrawer", html)

    def test_console_adopts_desktop_liquid_glass_reference_style(self):
        css = self.read_page("assets/console.css")

        for token in (
            "Sarito-style desktop console pass",
            "--glass-ink",
            "--glass-inner",
            "AI Action Dock",
            ".aether-console .floating-actions",
            ".aether-console .header-orbit",
            "backdrop-filter:blur(28px)",
            "rgba(18,19,20,.66)",
            "#ff5f57",
            "#ffbd2e",
            "#28c840",
            "mix-blend-mode:screen",
            "background-attachment:fixed",
            "@media(max-width:980px)",
        ):
            self.assertIn(token, css)

    def test_console_chat_uses_clean_chatgpt_like_message_layout(self):
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")

        self.assertIn("message-body", js)
        self.assertNotIn('class="avatar"', js)
        self.assertNotIn('class="mh"', js)
        self.assertNotIn('?"C":"U"', js.replace(" ", ""))
        for token in (
            ".aether-console .msg.user",
            "justify-content:flex-end",
            ".aether-console .msg.agent .message-body",
            "background:transparent",
            ".aether-console .msg.agent .mc",
        ):
            self.assertIn(token, css)

    def test_console_knowledge_workspace_uses_readable_glass_layout(self):
        css = self.read_page("assets/console.css")

        for token in (
            ".aether-console #view-knowledge .library-head",
            ".aether-console #view-knowledge .knowledge-layout",
            ".aether-console #view-knowledge .knowledge-editor",
            ".aether-console #view-knowledge .knowledge-map",
            ".aether-console #view-knowledge .table th",
            "color:rgba(255,255,255,.86)",
            ".aether-console #view-knowledge .compact-block",
        ):
            self.assertIn(token, css)

    def test_console_has_dedicated_mobile_more_entry(self):
        html = self.read_page("console.html")
        css = self.read_page("assets/console.css")

        self.assertIn('class="mobile-more-entry"', html)
        self.assertIn("toggleCommandDrawer()", html)
        self.assertIn("\u66f4\u591a\u5e94\u7528", html)
        self.assertIn(".aether-console .mobile-more-entry", css)
        self.assertIn("display:none", css)
        mobile_css = css.split("@media(max-width:760px)", 1)[1]
        self.assertIn(".aether-console .mobile-more-entry", mobile_css)
        self.assertIn("display:flex", mobile_css)
        self.assertIn("width:100%", mobile_css)

    def test_console_exposes_knowledge_library_as_user_rag_surface(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")

        for token in (
            "knowledgeTable",
            "knowledgeSearchTable",
            "knowledgeMap",
            "knowledgeEdges",
            "knowledgeFilePicker",
            "knowledgeSessionSelect",
            "knowledgeStatus",
            "obsidianStatus",
            "obsidianExportDir",
            "obsidianCheckTable",
            "attachmentTray",
            ):
            self.assertIn(token, html)

        for token in (
            "/api/knowledge",
            "handleKnowledgeFiles",
            "draftKnowledgeFromSelectedSession",
            "renderKnowledgeSessionSelect",
            "saveKnowledge",
            "searchKnowledge",
            "renderKnowledgeMap",
            "appendKnowledgeToPrompt",
            "deleteKnowledgeItem",
            "editingKnowledgeId",
            "checkObsidianVault",
            "exportObsidianVault",
            "renderObsidianCheck",
            "/api/knowledge/obsidian/check",
            "/api/knowledge/obsidian/export",
        ):
            self.assertIn(token, js)

        self.assertIn(".knowledge-toolbar", css)
        self.assertIn(".obsidian-panel", css)
        self.assertIn(".compact-block", css)
        self.assertIn(".import-drop", css)
        self.assertIn(".session-import", css)
        self.assertIn("Overflow safety layer", css)
        self.assertIn(".aether-console #view-knowledge .section-block", css)
        self.assertIn("max-height:min(42vh,420px)", css)
        self.assertIn("overflow-y:auto", css)
        self.assertIn("display:block", css)
        self.assertIn("cleanSessionTitle", js)
        self.assertIn("未命名会话", js)
        self.assertIn(".aether-console .sessions .session-tags", css)
        self.assertIn("text-overflow:ellipsis", css)
        self.assertIn(".aether-console [hidden]", css)

    def test_chat_file_picker_uses_attachment_context_not_prompt_paste(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")

        self.assertIn("attachmentTray", html)
        self.assertIn("Agent 会作为上下文自动读取", html)
        self.assertIn("chatAttachments", js)
        self.assertIn("clawos_attachments", js)
        self.assertIn("/api/documents/upload", js)
        self.assertIn("new FormData", js)
        self.assertIn("document_id", js)
        self.assertIn("renderAttachmentTray", js)
        self.assertIn("attachment-chip", css)
        file_handler = js.split("async function handlePickedFiles", 1)[1].split("function setMemoryType", 1)[0]
        self.assertNotIn('prompt").value=($("prompt").value', file_handler)
        self.assertNotIn(".text()", file_handler)

    def test_pages_have_no_common_mojibake_fragments(self):
        combined = "\n".join(
            self.read_page(name)
            for name in ("console.html", "assets/console.js", "assets/console.css")
        )

        for fragment in ("\u95c2", "\u95bb", "\u95c1", "\u95ba", "\u934f", "\u93b5", "\u93c2", "\u59af", "\u8133", "\ufffd"):
            self.assertNotIn(fragment, combined)

    def test_console_exposes_tool_trace_and_confirmation_ui(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("/api/tools/executions", js)
        self.assertIn("needs_confirmation", js)
        self.assertIn("confirmPending", html + js)
        self.assertIn("toolExecTable", html)

    def test_console_exposes_model_api_settings(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("cfgProvider", html)
        self.assertIn("cfgApiKey", html)
        self.assertIn("modelModePanel", html)
        self.assertIn('value="qwen"', html)
        self.assertIn('value="qwen_api"', html)
        self.assertIn('value="glm"', html)
        self.assertIn("/api/config/model", js)
        self.assertIn("saveModelSettings", js)
        self.assertIn("modelModeText", js)
        self.assertIn("providerPreset", js)
        self.assertIn("API \u6a21\u5f0f", html + js)
        self.assertIn("\u672c\u5730\u6a21\u5f0f", html + js)
        self.assertIn("\u79bb\u7ebf\u6a21\u5f0f", html + js)
        self.assertIn("localModelNote", html)
        self.assertIn("modelChoiceActions", html)
        self.assertIn("model-mode-card", html)
        self.assertIn("\u9009\u62e9\u5f53\u524d\u5de5\u4f5c\u53f0\u4f7f\u7528\u7684\u6a21\u578b\u6765\u6e90", html)
        self.assertIn("chooseFirstRunModel", html + js)
        self.assertNotIn("firstRunModelCard", html)
        self.assertIn("\u4e0d\u4f1a\u81ea\u52a8\u4e0b\u8f7d\u6a21\u578b\u6743\u91cd", html + js)
        self.assertIn("\u624b\u52a8\u4e0b\u8f7d\u5e76\u542f\u52a8\u672c\u5730\u670d\u52a1", html + js)

    def test_launcher_does_not_auto_download_or_start_local_qwen(self):
        launcher = (REPO_ROOT / "start_clawos.bat").read_text(encoding="utf-8")
        qwen_starter = (REPO_ROOT / "clawos" / "scripts" / "start_qwen_llama_server.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("configuration-first mode", launcher)
        self.assertIn("No model weights or llama.cpp runtime will be downloaded", launcher)
        self.assertNotIn("Starting local Qwen fallback", launcher)
        self.assertNotIn("start_qwen_llama_server.ps1", launcher)
        self.assertIn("[switch]$Download", qwen_starter)
        self.assertIn("rerun this script with -Download", qwen_starter)

    def test_console_exposes_report_style_presets(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")

        self.assertIn("reportDocumentSelect", html)
        self.assertIn("reportStylePreset", html)
        self.assertIn("reportDepthPreset", html)
        self.assertIn("reportOutputDir", html)
        self.assertIn("reportResult", html)
        self.assertIn("generateKnowledgeReport", html)
        self.assertNotIn('onclick="useReportStylePrompt()"', html)
        self.assertIn("applyReportPreset", js)
        self.assertIn("loadKnowledgeDocuments", js)
        self.assertIn("renderDocumentReportSelect", js)
        self.assertIn("reportReadyDocuments", js)
        self.assertIn("loadKnowledgeDocuments(pdfDocs[0]?.id)", js)
        self.assertIn("已自动选中 PDF", js)
        self.assertIn("reportGenerationError", js)
        self.assertIn("请确认资料是可读取的 PDF", js)
        self.assertIn("generateKnowledgeReport", js)
        self.assertIn("saveGeneratedReportToKnowledge", js)
        self.assertIn("lastGeneratedReport", js)
        self.assertIn("lastSavedReportKnowledgeId", js)
        self.assertIn("sourceLink", js)
        self.assertIn("Related source: [[${sourceTitle} #1]]", js)
        self.assertIn("report-flow", js)
        self.assertIn("report-flow-steps", js)
        self.assertIn("报告已生成", js)
        self.assertIn("继续追问", js)
        self.assertIn("appendKnowledgeToPrompt(${Number(lastSavedReportKnowledgeId)})", js)
        self.assertIn("library_document_id", js)
        self.assertIn("/api/workspace/research/learning-analysis", js)
        self.assertIn("business_brief", js)
        self.assertIn(".model-mode-card", css)
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", css)
        self.assertIn(".report-style-panel", css)
        self.assertIn(".report-result", css)
        self.assertIn(".report-flow", css)
        self.assertIn(".report-flow-steps", css)
        self.assertIn("grid-template-columns:minmax(180px,1.1fr)", css)
        self.assertIn(".report-style-panel .primary", css)
        self.assertIn("@media(max-width:1280px)", css)

    def test_console_exposes_enterprise_delivery_room_workflow(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")

        for token in (
            "enterpriseDeliveryStatus",
            "enterpriseProjectName",
            "enterpriseScenario",
            "enterpriseOutputDir",
            "enterpriseDeliveryResult",
            "committeeStatus",
            "committeeFocus",
            "committeeOutputDir",
            "committeeResult",
            "多 Agent 执行编队",
            "评分门禁",
            "runEnterpriseDeliveryRoom",
            "saveEnterpriseDeliveryToKnowledge",
            "runSelfReviewCommittee",
            "saveSelfReviewCommitteeToKnowledge",
        ):
            self.assertIn(token, html)

        for token in (
            "lastEnterpriseDelivery",
            "lastEnterpriseKnowledgeIds",
            "lastSelfReviewCommittee",
            "lastCommitteeKnowledgeIds",
            "clawos_enterprise_delivery_room",
            "clawos_self_review_committee",
            "/api/skills/execute",
            "plan_only: false",
            "knowledge_items",
            "enterprise-delivery",
            "multi-agent",
            "execution_trace",
            "timeline",
            "rubric_matrix",
            "renderCommitteeTimeline",
            "renderRubricMatrix",
            "Enterprise Rubric",
            "quality_gate",
            "arbitration_rounds",
            "rework_loop",
            "Rework",
            "Blocker / Next",
            "Required rework",
            "askEnterpriseDeliveryQuestion",
            "askSelfReviewCommitteeQuestion",
            "模拟评委视角",
        ):
            self.assertIn(token, js)

        self.assertIn(".enterprise-delivery-panel", css)
        self.assertIn(".self-review-committee-panel", css)
        self.assertIn(".committee-timeline", css)
        self.assertIn(".rubric-summary", css)
        self.assertIn(".aether-console #view-knowledge .enterprise-delivery-panel", css)

    def test_console_user_facing_copy_avoids_internal_demo_terms(self):
        combined = "\n".join(
            self.read_page(name)
            for name in ("console.html", "assets/console.js")
        )

        for token in ("\u672c\u6b21\u6f14\u793a", "\u6bd4\u8d5b\u9a8c\u6536", "\u6f14\u793a\u68c0\u67e5", "\u6f14\u793a\u963b\u788d"):
            self.assertNotIn(token, combined)
        self.assertNotIn("firstRunModelCard", combined)
        self.assertIn("modelChoiceActions", combined)
        self.assertIn("笔记库检查与导出", combined)
        self.assertIn("导出笔记库", combined)
        self.assertNotIn("Obsidian 检查与导出", combined)
        self.assertNotIn("导出 Obsidian", combined)
        self.assertNotIn("Obsidian Vault", combined)
        self.assertIn("\u6700\u8fd1\u8fd0\u884c\u7ed3\u679c", combined)

    def test_console_chat_uses_streaming_and_stop_control(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn('id="stop"', html)
        self.assertIn("readChatStream", js)
        self.assertIn("stream: true", js)
        self.assertIn("AbortController", js)
        self.assertIn("stopGeneration", js)
        self.assertIn("console stop generation", js)

    def test_console_exposes_unified_memory_governance(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("/api/memory/items", js)
        self.assertIn("memType", html)
        self.assertIn("memKey", html)
        self.assertIn("memValue", html)
        self.assertIn("toggleMemory", js)
        self.assertIn("memoryTable", html)
        self.assertIn("memoryReviewTable", html)
        self.assertIn("/api/memory/reviews", js)
        self.assertIn("resolveMemoryReview", js)

    def test_console_exposes_memory_and_reflection_review_actions(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("reflectionReviewTable", html)
        self.assertIn("/api/reflection/improvements", js)
        self.assertIn("transitionReflection", js)
        self.assertIn("validateReflection", js)
        self.assertIn("publishReflection", js)
        self.assertIn("rollbackReflection", js)

    def test_console_exposes_self_evolution_board(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")
        server = self.read_page("../clawos_server.py")

        for token in (
            "view-evolution",
            "Self-Evolution Board",
            "evolutionRunTable",
            "evolutionGateTable",
            "evolutionQualityTable",
            "queueEvolutionRun",
            "shadow → canary → active",
        ):
            self.assertIn(token, html)
        for token in (
            "/api/self-evolution/board",
            "/api/self-evolution/runs",
            "/api/self-evolution/runs/${id}/canary",
            "/api/self-evolution/runs/${id}/activate",
            "snapshotEvolutionQuality",
            "evolutionActions",
            "loadEvolution",
        ):
            self.assertIn(token, js)
        for token in (
            "worker_self_evolution_benchmark",
            "self_evolution_benchmark",
            "api_self_evolution_board",
            "api_self_evolution_activate",
        ):
            self.assertIn(token, server)
        self.assertIn(".evolution-workspace", css)

    def test_console_exposes_task_trace_panel(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("/api/tasks", js)
        self.assertIn("/api/tasks/stream", js)
        self.assertIn("/api/tasks/recover", js)
        self.assertIn("/api/tasks/queue", js)
        self.assertIn("/api/tasks/queue/claim", js)
        self.assertIn("/cancel", js)
        self.assertIn("/retry", js)
        self.assertIn("taskTable", html)
        self.assertIn("taskQueueTable", html)
        self.assertIn("taskStepTable", html)
        self.assertIn("taskEventTable", html)
        self.assertIn("claimTask", js)
        self.assertIn("loadTaskQueue", js)
        self.assertIn("loadTasks", js)
        self.assertIn("task_id", js)

    def test_console_exposes_ops_center_and_business_worker_jobs(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")
        server = self.read_page("../clawos_server.py")

        for token in (
            "view-ops",
            "opsReadinessTable",
            "opsConfigTable",
            "opsWorkerTable",
            "opsReportDocumentSelect",
            "opsBatchFiles",
            "Ops Center",
        ):
            self.assertIn(token, html)
        for token in (
            "loadOps",
            "runConfigCheck",
            "createBackup",
            "restoreBackup",
            "startWorker",
            "tickWorker",
            "queueReportJob",
            "queueOcrJob",
            "queueBatchIngestJob",
            "/api/system/readiness",
            "/api/tasks/jobs/report",
            "/api/tasks/jobs/ocr-queue",
            "/api/tasks/jobs/batch-ingest",
        ):
            self.assertIn(token, js)
        for token in (
            "worker_generate_report",
            "worker_process_ocr_queue",
            "worker_batch_ingest_documents",
            "api_system_readiness",
            "api_tasks_job_report",
        ):
            self.assertIn(token, server)
        self.assertIn(".ops-workspace", css)
        self.assertIn(".job-grid", css)

    def test_console_exposes_professional_template_board(self):
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")

        for token in (
            "Professional Template Board",
            "professionalBoardGrid",
            "Research Board",
            "Learning Board",
            "Code Board",
            "Office Board",
            "activateScenarioBoard",
            "reproducibility gate",
            "export quality gate",
        ):
            self.assertIn(token, js)
        self.assertIn(".professional-board-grid", css)
        self.assertIn(".board-card", css)

    def test_console_exposes_skill_workbench_controls(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")

        for token in (
            "skillQuery",
            "skillCategory",
            "skillStatusFilter",
            "skillDetail",
            "skillParams",
            "skillRunResult",
            "skillVersionTable",
            "skillRunTable",
        ):
            self.assertIn(token, html)

        for token in (
            "/api/skills/execute",
            "/api/skills/evolution/versions",
            "/api/skills/evolution/runs",
            "runSelectedSkill",
            "renderSkillsWorkbench",
            "selectSkill",
            "renderSkillVersionTables",
        ):
            self.assertIn(token, js)

        self.assertIn("Skills workbench", css)
        self.assertIn(".skill-card-list", css)
        self.assertIn(".skill-grid", css)
    def test_console_exposes_benchmark_and_skill_review_inbox(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("benchmarkSuiteTable", html)
        self.assertIn("benchmarkRunTable", html)
        self.assertIn("/api/benchmarks/scenarios/run", js)
        self.assertIn("/api/skills/evolution/review-inbox", js)
        self.assertIn("promoteSkill", js)
        self.assertIn("reviewSkill", js)

    def test_console_exposes_scene_capability_check(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("capabilityTable", html)
        self.assertIn("sceneBoundaryTable", html)
        self.assertIn("modelHealthTable", html)
        self.assertIn("toolAccuracyTable", html)
        self.assertIn("routingPolicyTable", html)
        self.assertIn("/api/workspace/capabilities", js)
        self.assertIn("/api/model/health", js)
        self.assertIn("/api/tools/accuracy", js)
        self.assertIn("/api/routing/policy", js)
        self.assertIn("联网搜索/网页抓取", js)
        self.assertIn("web_fetch", self.read_page("../functions.jsonl"))
        self.assertIn("document_understanding", js)
        self.assertIn("office_artifacts", js)
        self.assertIn("meeting_audio", js)

    def test_console_exposes_permission_center_and_graph_backplane(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("view-security", html)
        self.assertIn("securityPolicyTable", html)
        self.assertIn("securityBoundaryTable", html)
        self.assertIn("securityAuditTable", html)
        self.assertIn("securityGrantTable", html)
        self.assertIn("securityGrantScopeType", html)
        self.assertIn("loadSecurityCenter", js)
        self.assertIn("saveSecurityGrant", js)
        self.assertIn("revokeSecurityGrant", js)
        self.assertIn("/api/security/policy/check", js)
        self.assertIn("/api/security/policy/grants", js)
        self.assertIn("/api/security/audit", js)
        self.assertIn("/api/knowledge/graph", js)
        self.assertIn("loadKnowledgeGraph", js)
        self.assertIn("ocrQueueTable", html)
        self.assertIn("citationAnswerTable", html)
        self.assertIn("/api/documents/ocr-queue", js)
        self.assertIn("/api/documents/${Number(id)}/ocr", js)
        self.assertIn("/api/documents/citation-answer", js)
        self.assertIn("loadRoutingStrategy", js)
        self.assertIn("scored_policy_routing", self.read_page("../clawos_server.py"))


if __name__ == "__main__":
    unittest.main()
