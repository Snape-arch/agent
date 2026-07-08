from pathlib import Path
import re
import unittest


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
REPO_ROOT = Path(__file__).resolve().parents[2]


class FrontendStaticTests(unittest.TestCase):
    def read_page(self, name: str) -> str:
        return (STATIC_DIR / name).read_text(encoding="utf-8")

    def test_frontend_is_split_into_layered_pages(self):
        home = self.read_page("index.html")
        product = self.read_page("product.html")
        academy = self.read_page("academy.html")
        console = self.read_page("console.html")

        self.assertIn('href="/product"', home)
        self.assertIn('href="/academy"', home)
        self.assertIn("magazine-backdrop", home)
        self.assertIn('href="/console"', product)
        self.assertIn("Evidence Grid", product)
        self.assertIn("Runtime Map", product)
        self.assertIn("ClawOS AI Academy", academy)
        self.assertIn("academy.js", academy)
        self.assertIn('class="console-page aether-console"', console)

    def test_product_shell_unifies_navigation_tokens_and_console_links(self):
        home = self.read_page("index.html")
        product = self.read_page("product.html")
        academy = self.read_page("academy.html")
        console = self.read_page("console.html")
        site_css = self.read_page("assets/site.css")
        console_css = self.read_page("assets/console.css")

        self.assertIn("claw-layer-nav", home)
        self.assertIn("Personal Agent OS", home)
        self.assertIn('href="/academy"', home)
        self.assertIn(">首页</a>", home)
        self.assertIn(">产品</a>", home)
        self.assertIn(">控制台</a>", home)
        home_nav = home.split('<div class="claw-home-links">', 1)[1].split("</div>", 1)[0]
        self.assertEqual(home_nav.count("<a "), 4)
        self.assertNotIn('href="#technology"', home_nav)
        self.assertNotIn('href="#developers"', home_nav)

        self.assertIn("claw-layer-nav", product)
        self.assertIn("Personal Agent OS", product)
        self.assertIn("Product Map", product)
        self.assertIn("AI Academy", product)
        self.assertIn("Console", product)

        self.assertNotIn("console-layer-strip", console)
        self.assertIn("console-product-nav", console)
        self.assertIn("前台工作", console)
        self.assertIn("后台系统", console)
        self.assertIn("Console", console)
        self.assertIn('href="/"', console)
        self.assertIn('href="/product"', console)
        self.assertIn('href="/academy"', console)
        self.assertIn("首页", console)
        self.assertIn("产品页", console)
        for token in (
            "--claw-card-radius",
            "--claw-pill-radius",
            "--claw-glass",
            ".claw-layer-nav",
            ".capability-index-grid",
            ".capability-link-card",
            ".academy-page",
            ".academy-card-index",
            ".academy-layer-graph",
        ):
            self.assertIn(token, site_css)
        self.assertIn(".aether-console .console-product-nav", console_css)
        self.assertIn(".aether-console .space-group", console_css)
        self.assertIn(".aether-console .work-front", console_css)
        self.assertIn(".aether-console .system-back", console_css)

        expected_links = {
            "/console#memory": "MemoryOS",
            "/console#tools": "Tool Router",
            "/console#tasks": "Task Trace",
            "/console#skills": "Skill Evolution",
            "/console#security": "Security",
            "/console#ops": "Ops",
        }
        for href, label in expected_links.items():
            self.assertIn(f'href="{href}"', product)
            self.assertIn(label, product)
        self.assertIn('href="/academy"', product)
        self.assertIn("AI Academy", academy)
        self.assertIn('href="/academy/path"', academy)
        self.assertIn('href="/academy/paper"', academy)
        self.assertIn('href="/academy/code"', academy)
        self.assertIn('href="/academy/notes"', academy)
        self.assertIn('href="/academy/ingest"', academy)
        self.assertIn('href="/academy/quiz"', academy)
        self.assertNotIn('class="tab-bar"', product)

        self.assertIn("product-console-visual", product)
        self.assertIn("console-preview-frame", product)
        self.assertIn("clawos-console-product.jpg", product)
        self.assertIn(".product-page .product-console-visual", site_css)
        self.assertIn(".product-page .visual-glyph", site_css)
        hero_section = product.split('<section class="product-hero">', 1)[1].split("</section>", 1)[0]
        self.assertNotIn("217661e1279b044bf39afd172106ea06.jpg", hero_section)

    def test_ai_academy_exposes_learning_workflows(self):
        academy = self.read_page("academy.html")
        path = self.read_page("academy-path.html")
        paper = self.read_page("academy-paper.html")
        code = self.read_page("academy-code.html")
        notes = self.read_page("academy-notes.html")
        ingest = self.read_page("academy-ingest.html")
        quiz = self.read_page("academy-quiz.html")
        academy_js = self.read_page("assets/academy.js")
        site_css = self.read_page("assets/site.css")
        server = (REPO_ROOT / "clawos" / "clawos_server.py").read_text(encoding="utf-8")

        for token in (
            "ClawOS AI Academy",
            "academy-module-card",
            "academyLayerStrip",
            "/academy/path",
            "/academy/paper",
            "/academy/code",
            "/academy/notes",
            "/academy/ingest",
            "/academy/quiz",
        ):
            self.assertIn(token, academy)
        self.assertIn("academyLayerGraph", path)
        self.assertIn("academyLayerDetail", path)
        self.assertIn("paperDeepReadOutput", paper)
        self.assertIn("academyPaperFile", paper)
        self.assertIn("academyUploadPaper", paper)
        self.assertIn("academyRunPaperWorkflow", paper)
        self.assertIn("academySavePaperKnowledge", paper)
        self.assertIn("academySavePaperCheckpoint", paper)
        self.assertIn("academyPaperViewer", paper)
        self.assertIn("academyInkCanvas", paper)
        self.assertIn("academyPaperAssistant", paper)
        self.assertIn("academyCitationEvidence", paper)
        self.assertIn("academyPaperReportCard", paper)
        self.assertIn("academyCodeBlock", code)
        self.assertIn("academyNoteOutput", notes)
        self.assertIn("academyIngestStatus", ingest)
        self.assertIn("academyQuizGrid", quiz)
        for token in (
            "AI_LAYERS",
            "基础支撑层",
            "传统 AI / 机器学习层 ML",
            "深度学习层 DL",
            "计算机视觉层 CV",
            "NLP 与 LLM 层",
            "VLM / 多模态层",
            "生成式 AI 层",
            "AI Agent 层",
            "AI Coding / 软件工程智能体层",
            "AI Infra / MLOps / LLMOps 层",
            "Evaluation / Safety / Governance 层",
            "强化学习层 RL",
            "AI 应用层",
            "前沿拓展层",
            "academyRenderLayerGraph",
            "academyGeneratePaperRead",
            "academyPaperState",
            "academyUploadPaper",
            "academyRunPaperWorkflow",
            "academySavePaperKnowledge",
            "academySavePaperCheckpoint",
            "academyLoadPaperCheckpoints",
            "academyOpenPaperCheckpoint",
            "academyLoadPaperProjectBoard",
            "academyAddPaperProjectItem",
            "academyUpdatePaperProjectItem",
            "academyExportPaperProject",
            "academyLoadPaperProjectPackages",
            "academyOpenPaperProjectPackage",
            "academyRefreshPaperAudit",
            "academyAskPaperCitation",
            "academySetupInk",
            "/api/academy/paper/annotations",
            "annotationArtifact",
            "/api/documents/upload",
            "/api/workspace/research/learning-analysis",
            "/api/knowledge",
            "/api/documents/citation-answer",
            "/api/knowledge/graph",
            "academyGenerateNote",
            "academyQueueKnowledge",
            "academyGenerateQuiz",
            "academyAnswerQuiz",
            "clawos_academy_completed",
        ):
            self.assertIn(token, academy_js)
        for token in (
            ".academy-page",
            ".academy-hero",
            ".academy-visual",
            ".academy-card-index",
            ".academy-layer-node",
            ".academy-layer-detail",
            ".paper-output-card",
            ".paper-reader-shell",
            ".academy-ink-canvas",
            ".paper-assistant-panel",
            ".academy-citation-list",
            ".academy-report-card",
            ".quiz-grid article.answered",
        ):
            self.assertIn(token, site_css)
        self.assertIn('@app.get("/academy")', server)
        self.assertIn('@app.get("/academy/path")', server)
        self.assertIn('@app.get("/academy/paper")', server)
        self.assertIn('@app.get("/academy/code")', server)
        self.assertIn('@app.get("/academy/notes")', server)
        self.assertIn('@app.get("/academy/ingest")', server)
        self.assertIn('@app.get("/academy/quiz")', server)
        self.assertIn('@app.get("/api/documents/{document_id}/source")', server)
        self.assertIn('@app.post("/api/academy/paper/checkpoint")', server)
        self.assertIn('@app.get("/api/academy/paper/checkpoints")', server)
        self.assertIn('@app.get("/api/academy/paper/checkpoints/{run_id}")', server)
        self.assertIn('@app.get("/api/academy/paper/project-board")', server)
        self.assertIn('@app.post("/api/academy/paper/project-board")', server)
        self.assertIn('@app.post("/api/academy/paper/project-board/{run_id}/status")', server)
        self.assertIn('@app.post("/api/academy/paper/project-board/export")', server)
        self.assertIn('@app.get("/api/academy/paper/project-board/exports")', server)
        self.assertIn('@app.get("/api/academy/paper/project-board/exports/{run_id}")', server)
        self.assertIn('@app.get("/api/academy/paper/offline-audit")', server)

    def test_console_prevents_vertical_compressed_table_text(self):
        html = self.read_page("console.html")
        css = self.read_page("assets/console.css")

        self.assertIn("space-group work-front", html)
        self.assertIn("space-group system-back", html)
        self.assertIn("工作前台", html)
        self.assertIn("系统后台", html)
        for token in (
            "Anti-compression layer",
            "writing-mode:horizontal-tb",
            "text-orientation:mixed",
            "word-break:normal",
            "table-layout:auto",
            "#view-tasks .table",
            "min-width:920px",
            "overflow-x:auto",
        ):
            self.assertIn(token, css)

    def test_console_project_workspace_and_admin_entry_are_user_clear(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")

        for token in (
            "项目工作台",
            "projectFilePicker",
            "projectRootInput",
            "projectGoalInput",
            "projectStatus",
            "projectRequestCard",
            "projectRequestPreview",
            "上传项目资料",
            "后台管理",
        ):
            self.assertIn(token, html)
        for token in (
            "projectPromptText",
            "prepareProjectPrompt",
            "sendPreparedProjectPrompt",
            "handleProjectFiles",
        ):
            self.assertIn(token, js)
        for token in (
            ".project-intake",
            ".project-upload-drop",
            ".project-path-card",
            ".project-status",
            ".project-request-card",
            ".project-request-card.ready",
            "button[data-view=\"dash\"]:after",
            "max-width:104px",
        ):
            self.assertIn(token, css)

    def test_home_scan_wall_uses_lifestyle_narrative_labels(self):
        home = self.read_page("index.html")
        css = self.read_page("assets/site.css")

        for label in (
            "Urban Signal",
            "Archive Mode",
            "Study Drift",
            "Memory Club",
            "Patch Culture",
            "Desk Ritual",
            "Skill Drop",
        ):
            self.assertIn(label, home)
        for old_label in (
            "Meeting Agent",
            "Research Agent",
            "Learning Agent",
            "Knowledge Agent",
            "Code Agent",
            "Workspace Agent",
            "Skill Agent",
        ):
            self.assertNotIn(old_label, home)
        self.assertIn("transform:translateX(14vw)", css)
        self.assertIn("padding-top:62px", css)
        self.assertIn("opacity:.26", css)

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
        self.assertIn("webSearchToggle", html)
        self.assertIn("联网搜索", html)
        self.assertIn("commandDrawer", html)

    def test_console_spaces_are_real_navigation_targets(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")

        expected_spaces = {
            "chat",
            "search",
            "knowledge",
            "projects",
            "dash",
            "memory",
            "tools",
            "tasks",
            "reflection",
            "evolution",
            "skills",
            "benchmarks",
            "scenes",
            "security",
            "ops",
        }
        view_ids = set(re.findall(r'id="view-([^"]+)"', html))
        data_views = set(re.findall(r'data-view="([^"]+)"', html))

        self.assertTrue(expected_spaces <= view_ids)
        self.assertTrue(expected_spaces <= data_views)
        self.assertFalse(data_views - view_ids)
        self.assertIn('id="spaceSwitcher"', html)
        self.assertIn(".aether-console .space-switcher", css)
        self.assertIn('document.querySelectorAll("button[data-view]")', js)
        self.assertIn("VIEW_META", js)
        self.assertIn("aria-current", js)
        self.assertIn("history.replaceState", js)
        self.assertIn("location.hash", js)
        self.assertIn("webSearchToggle", js)
        self.assertIn('"web_search"', js)
        self.assertIn('target="_blank"', js)
        self.assertNotIn('document.querySelectorAll(".side-nav button[data-view]")', js)

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
            "knowledgeFrontStage",
            "knowledgeModeTitle",
            "knowledgeUploadHint",
            "knowledgeGraphSummary",
            "knowledge-admin-toggle",
            "knowledgeFrontstageMetrics",
            "knowledgeActiveLibrary",
            "knowledgeBackendState",
            "knowledge-backstage-label",
        ):
            self.assertIn(token, html)
        for token in (
            "KNOWLEDGE_MODES",
            "renderKnowledgeWorkspaceShell",
            "toggleKnowledgeAdminTools",
            "updateKnowledgeFrontstageStats",
            "Research Library",
            "Learning Library",
            "Writing Library",
            "Project Library",
        ):
            self.assertIn(token, js)
        for token in (
            ".knowledge-front-stage",
            ".knowledge-mode-card",
            ".knowledge-upload-hero",
            ".knowledge-graph-card",
            ".knowledge-frontstage-metrics",
            ".knowledge-zone-label",
            ".knowledge-admin-entry",
            ".knowledge-backstage-label",
            ".show-knowledge-admin",
            ".section-block:has(#ocrQueueTable)",
            ".space-switcher .system-back button:not([data-view=\"dash\"])",
        ):
            self.assertIn(token, css)
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
            "acceptanceReportStatus",
            "acceptanceReportResult",
            "liveSearchReportStatus",
            "liveSearchReportResult",
            "联网搜索 Live 验收",
            "多 Agent 执行编队",
            "评分门禁",
            "runEnterpriseDeliveryRoom",
            "saveEnterpriseDeliveryToKnowledge",
            "runSelfReviewCommittee",
            "saveSelfReviewCommitteeToKnowledge",
            "loadComplexAcceptanceReport",
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
            "renderCommitteeAuditBoard",
            "renderRoleSwimlanes",
            "renderDisputeCards",
            "renderArtifactDiff",
            "renderBuilderExecution",
            "roleAvatar",
            "Multi-Agent Audit Board",
            "Builder Execution",
            "renderRubricMatrix",
            "Enterprise Rubric",
            "quality_gate",
            "arbitration_rounds",
            "disagreement_log",
            "rework_loop",
            "v2_artifacts",
            "reviewer_diff",
            "judge_decision",
            "Rework",
            "V2 Artifacts",
            "Dispute",
            "Objector",
            "Opposes",
            "V1 / V2 产物对比",
            "Blocker / Next",
            "Required rework",
            "lastComplexAcceptanceReport",
            "lastLiveSearchReport",
            "/api/acceptance/deepseek-qwen/latest",
            "/api/search/live/latest",
            "citation_hit_rate",
            "provider_success_rate",
            "latency_p95_ms",
            "loadComplexAcceptanceReport",
            "renderComplexAcceptanceReport",
            "loadLiveSearchReport",
            "renderLiveSearchReport",
            "askEnterpriseDeliveryQuestion",
            "askSelfReviewCommitteeQuestion",
            "模拟评委视角",
        ):
            self.assertIn(token, js)

        self.assertIn(".enterprise-delivery-panel", css)
        self.assertIn(".self-review-committee-panel", css)
        self.assertIn(".acceptance-report-panel", css)
        self.assertIn(".live-search-report-panel", css)
        self.assertIn("#liveSearchReportBlock", css)
        self.assertIn(".acceptance-report-card", css)
        self.assertIn(".acceptance-metric-grid", css)
        self.assertIn(".committee-timeline", css)
        self.assertIn(".committee-audit-board", css)
        self.assertIn(".audit-swimlanes", css)
        self.assertIn(".audit-timeline-rail", css)
        self.assertIn(".audit-builder-execution", css)
        self.assertIn(".audit-builder-grid", css)
        self.assertIn(".audit-builder-task", css)
        self.assertIn(".audit-dispute-card", css)
        self.assertIn(".audit-artifact-diff", css)
        self.assertIn(".audit-diff-pair", css)
        self.assertIn(".rubric-summary", css)
        self.assertIn(".aether-console #view-knowledge .enterprise-delivery-panel", css)

    def test_console_runtime_modules_are_split_from_main_bundle(self):
        html = self.read_page("console.html")
        css = self.read_page("assets/console.css")
        module_js = self.read_page("assets/console.modules.js")

        for token in (
            "runtimeRecordPanel",
            "runtimeRecordGrid",
            "/assets/console.modules.js",
        ):
            self.assertIn(token, html)
        for token in (
            "ClawOSConsoleModules",
            "runtime-records",
            "/api/runtime/schema",
            "/api/runtime/runs/latest",
            "/api/runtime/failure-cases",
            "loadRuntimeRecords",
            "Failure Library",
            "Run / Artifact / Evidence",
        ):
            self.assertIn(token, module_js)
        self.assertIn(".runtime-record-panel", css)
        self.assertIn(".runtime-record-grid", css)

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
        css = self.read_page("assets/console.css")
        server = (REPO_ROOT / "clawos" / "clawos_server.py").read_text(encoding="utf-8")

        self.assertIn("capabilityTable", html)
        self.assertIn("sceneBoundaryTable", html)
        self.assertIn("meetingAsrTitle", html)
        self.assertIn("meetingAudioPicker", html)
        self.assertIn("meetingTranscriptPicker", html)
        self.assertIn("meetingAsrResult", html)
        self.assertIn("modelHealthTable", html)
        self.assertIn("offlineReadinessPanel", html)
        self.assertIn("offlineReadinessGrid", html)
        self.assertIn("dailyAcceptanceSummary", html)
        self.assertIn("Run daily check", html)
        self.assertIn("Daily + Qwen", html)
        self.assertIn("Qwen smoke", html)
        self.assertIn("refreshOfflineReadiness", js)
        self.assertIn("/api/workbench/offline-readiness", js)
        self.assertIn("/api/workbench/daily-local-acceptance", js)
        self.assertIn("/api/workbench/local-qwen-smoke", js)
        self.assertIn("runLocalQwenSmokeCheck", js)
        self.assertIn("include_qwen_smoke", js)
        self.assertIn("runDailyLocalAcceptance", js)
        self.assertIn("copyDailyLocalAcceptanceSummary", js)
        self.assertIn(".offline-readiness-panel", css)
        self.assertIn(".daily-acceptance-summary", css)
        self.assertIn("@app.get(\"/api/workbench/offline-readiness\")", server)
        self.assertIn("@app.post(\"/api/workbench/daily-local-acceptance\")", server)
        self.assertIn("@app.post(\"/api/workbench/local-qwen-smoke\")", server)
        self.assertIn("toolAccuracyTable", html)
        self.assertIn("routingPolicyTable", html)
        self.assertIn("/api/workspace/capabilities", js)
        self.assertIn("/api/workspace/meetings/audio/upload", js)
        self.assertIn("runMeetingAudioUpload", js)
        self.assertIn("renderMeetingAudioResult", js)
        self.assertIn("new FormData", js)
        self.assertIn("/api/model/health", js)
        self.assertIn("local_model_assets", js)
        self.assertIn("local qwen assets", js)
        self.assertIn("/api/tools/accuracy", js)
        self.assertIn("/api/routing/policy", js)
        self.assertIn("联网搜索/网页抓取", js)
        self.assertIn("web_fetch", self.read_page("../functions.jsonl"))
        self.assertIn("web_citation_check", self.read_page("../functions.jsonl"))
        self.assertIn("web_search_benchmark", self.read_page("../functions.jsonl"))
        self.assertIn("搜索证据引擎", js)
        self.assertIn("web_research", js)
        self.assertIn("引用门禁", js)
        self.assertIn("document_understanding", js)
        self.assertIn("office_artifacts", js)
        self.assertIn("meeting_audio", js)
        self.assertIn(".meeting-asr-panel", css)
        self.assertIn(".meeting-asr-form", css)

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
