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

        self.assertIn('href="/assets/site.css"', html)
        self.assertIn('href="/assets/console.css"', html)
        self.assertIn('data-view="chat"', html)
        self.assertIn('data-view="search"', html)
        self.assertIn('data-view="knowledge"', html)
        self.assertIn('data-view="projects"', html)
        self.assertIn("view-knowledge", html)
        self.assertIn("view-memory", html)
        self.assertIn("filePicker", html)
        self.assertIn("commandDrawer", html)

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

    def test_chat_file_picker_uses_attachment_context_not_prompt_paste(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")

        self.assertIn("attachmentTray", html)
        self.assertIn("Agent 会作为上下文自动阅读", html)
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

        for fragment in ("闁", "闂", "鐎", "閿", "鏉", "鐠", "閹"):
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
        self.assertIn("Local Qwen 模式", js)
        self.assertIn("Mock/offline test 模式", js)
        self.assertIn("localModelNote", html)
        self.assertIn("不会自动下载本地模型权重", html)
        self.assertIn("手动下载/启动", js)

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
        self.assertIn("generateKnowledgeReport", js)
        self.assertIn("saveGeneratedReportToKnowledge", js)
        self.assertIn("lastGeneratedReport", js)
        self.assertIn("lastSavedReportKnowledgeId", js)
        self.assertIn("report-flow", js)
        self.assertIn("report-flow-steps", js)
        self.assertIn("报告已生成", js)
        self.assertIn("继续追问", js)
        self.assertIn("appendKnowledgeToPrompt(${Number(lastSavedReportKnowledgeId)})", js)
        self.assertIn("library_document_id", js)
        self.assertIn("/api/workspace/research/learning-analysis", js)
        self.assertIn("business_brief", js)
        self.assertIn(".report-style-panel", css)
        self.assertIn(".report-result", css)
        self.assertIn(".report-flow", css)
        self.assertIn(".report-flow-steps", css)

    def test_console_user_facing_copy_avoids_internal_demo_terms(self):
        combined = "\n".join(
            self.read_page(name)
            for name in ("console.html", "assets/console.js")
        )

        for token in ("\u672c\u6b21\u6f14\u793a", "\u6bd4\u8d5b\u9a8c\u6536", "\u6f14\u793a\u68c0\u67e5", "\u6f14\u793a\u963b\u788d"):
            self.assertNotIn(token, combined)
        self.assertIn("firstRunModelCard", combined)
        self.assertIn("Obsidian \u68c0\u67e5\u4e0e\u5bfc\u51fa", combined)
        self.assertIn("\u6700\u8fd1\u8fd0\u884c\u7ed3\u679c", combined)

    def test_console_chat_uses_streaming_and_stop_control(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn('id="stop"', html)
        self.assertIn("readChatStream", js)
        self.assertIn("stream:true", js)
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
