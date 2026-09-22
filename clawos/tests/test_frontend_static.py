from pathlib import Path
import re
import unittest


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
REPO_ROOT = Path(__file__).resolve().parents[2]


class FrontendStaticTests(unittest.TestCase):
    def test_console_real_evidence_surface_excludes_mock_success(self):
        html = (STATIC_DIR / "console.html").read_text(encoding="utf-8")
        script = (STATIC_DIR / "assets" / "evidence-chains.js").read_text(encoding="utf-8")
        self.assertIn("evidence-chains.js", html)
        self.assertIn("/api/runtime/evidence-chains", script)
        self.assertIn("等待真实运行", script)
        self.assertNotIn("100%", script)

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
        self.assertNotIn("console-product-nav", console)
        self.assertNotIn('id="spaceSwitcher"', console)
        self.assertIn("workbench-shell", console)
        self.assertIn("chatTaskSidebarList", console)
        self.assertIn("autonomy-options", console)
        self.assertIn("execution-settings", console)
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
        self.assertIn("Champion workbench", console_css)
        self.assertIn("--workbench-canvas", console_css)
        self.assertIn(".aether-console .workbench-shell", console_css)
        self.assertIn(".aether-console .delivery-table", console_css)

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
        self.assertIn("academyPaperTimeline", paper)
        self.assertIn("academyPaperTimelineDetail", paper)
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
            "academyLoadPaperTimeline",
            "academyOpenPaperTimelineEvent",
            "/api/academy/paper/timeline",
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
            "academyLoadLearningDashboard",
            "/api/academy/learning/dashboard",
            "/api/academy/learning/quiz",
            "/api/academy/learning/questions/",
        ):
            self.assertIn(token, academy_js)
        self.assertNotIn("clawos_academy_completed", academy_js)
        self.assertNotIn("completed.add(node)", academy_js)
        for endpoint in (
            "/api/academy/learning/dashboard",
            "/api/academy/learning/quiz",
            "/api/academy/learning/questions/{question_id}/answers",
            "/api/academy/learning/mistakes",
            "/api/academy/learning/project-evidence",
            "/api/academy/learning/courses/{course_id}/publish",
        ):
            self.assertIn(endpoint, server)
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
            ".academy-paper-timeline-list",
            ".academy-paper-timeline-detail",
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
        self.assertIn('@app.get("/api/academy/paper/timeline")', server)
        self.assertIn('academy_citation_answer', server)
        self.assertIn('@app.get("/api/academy/paper/offline-audit")', server)

    def test_console_prevents_vertical_compressed_table_text(self):
        html = self.read_page("console.html")
        css = self.read_page("assets/console.css")

        self.assertNotIn("space-group work-front", html)
        self.assertNotIn("space-group system-back", html)
        self.assertIn("task-workspace", html)
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
        self.assertIn("workbench-new", html)
        self.assertIn("useWorkbenchPrompt", html + js)
        self.assertIn("renderWorkbenchTasks", js)
        self.assertIn("refreshView(viewName)", js)
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
        self.assertIn("证据策略", html)
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
        self.assertNotIn('id="spaceSwitcher"', html)
        self.assertNotIn("console-product-nav", html)
        self.assertNotIn("floating-actions", html)
        self.assertIn('document.querySelectorAll("button[data-view]")', js)
        self.assertIn("VIEW_META", js)
        self.assertIn("aria-current", js)
        self.assertIn("history.replaceState", js)
        self.assertIn("location.hash", js)
        self.assertIn("webSearchToggle", js)
        self.assertIn('"web_search"', js)
        self.assertIn('"web_fetch"', js)
        self.assertIn("clawos_web_search_mode", js)
        self.assertIn('id="webSearchToggle" type="checkbox" checked', html)
        self.assertNotIn("按需联网：仅在时效性", js)
        self.assertNotIn("请先联网搜索可验证来源", js)
        self.assertIn("appendArtifactsToLastAssistant", js)
        self.assertIn("appendCodingEvidenceToLastAssistant", js)
        self.assertIn("chat-artifact-card", js)
        self.assertIn("chat-coding-evidence", js)
        self.assertIn("download_url", js)
        self.assertIn("preview_url", js)
        self.assertIn('target="_blank"', js)
        self.assertNotIn('document.querySelectorAll(".side-nav button[data-view]")', js)

    def test_console_adopts_calm_enterprise_workbench_style(self):
        css = self.read_page("assets/console.css")

        for token in (
            "Champion workbench",
            "--workbench-canvas",
            "--workbench-surface",
            "--workbench-ink",
            "--workbench-blue",
            ".aether-console .workbench-columns",
            ".aether-console .active-task-row",
            ".aether-console .autonomy-options",
            ".aether-console .delivery-table",
            "@media(max-width:760px)",
        ):
            self.assertIn(token, css)

    def test_console_is_conversation_first_and_renders_safe_markdown(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        clean_css = self.read_page("assets/console.clean.css")

        chat = html.split('<section class="view on" id="view-chat">', 1)[1].split('<section class="view" id="view-search">', 1)[0]
        self.assertNotIn("delivery-center", chat)
        self.assertNotIn("agent-roster", chat)
        self.assertIn("chat-progress-panel", chat)
        self.assertIn("execution-settings", chat)
        self.assertIn("markdown-it-14.1.0.min.js", html)
        self.assertIn("window.ClawChatContent.render(text)", js)
        self.assertIn("function enhanceMarkdown", js)
        self.assertIn('rel="noopener noreferrer"', js)
        self.assertIn("Conversation-first P0-P1 closure", clean_css)
        self.assertIn("height:calc(100vh - 124px)", clean_css)
        self.assertIn(".md-table-wrap", clean_css)

    def test_console_remediation_removes_legacy_overlay_and_restores_site_navigation(self):
        html = self.read_page("console.html")
        css = self.read_page("assets/console.css")
        clean_css = self.read_page("assets/console.clean.css")

        self.assertIn('href="/assets/console.clean.css?', html)
        for href in ('href="/"', 'href="/product"', 'href="/academy"'):
            self.assertIn(href, html)
        self.assertIn("console-site-links", html)
        self.assertIn("side-site-links", html)
        intent = html.split('<section class="intent-panel"', 1)[1].split("</section>", 1)[0]
        self.assertIn('class="composer"', intent)
        self.assertEqual(html.count('id="prompt"'), 1)
        self.assertEqual(html.count('class="composer"'), 1)
        for token in (
            "Screenshot remediation",
            ".aether-console .workbench-shell:before",
            "background-image:none!important",
            ".aether-console .intent-panel .composer",
            "position:static",
            ".aether-console .intent-panel .compose-inner",
            ".aether-console .side:before",
            "content:none!important",
        ):
            self.assertIn(token, css)
        for token in (
            "ClawOS Console Clean UI",
            "Absolute legacy kill-switches",
            ".aether-console .panel-view:before",
            ".aether-console .knowledge-workspace:before",
            ".aether-console .runtime-record-grid>*",
            ".aether-console .session-results",
            ".aether-console .command-sheet",
            "background-image:none!important",
        ):
            self.assertIn(token, clean_css)

    def test_console_has_readable_history_and_expandable_knowledge_graph(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.clean.css")

        for token in (
            "knowledgeGraphExplorer",
            "graphExplorerStage",
            "graphExplorerNodes",
            "graphExplorerEdges",
            "graphInspector",
            "graphTypeFilter",
            "graphRelationFilter",
            "graphNodeQuery",
            "openKnowledgeGraphExplorer",
        ):
            self.assertIn(token, html)
        for token in (
            "lastKnowledgeGraph",
            "renderKnowledgeGraphExplorer",
            "selectKnowledgeGraphNode",
            "graphNodeColor",
            "visibleEdges",
            "graph-explorer-open",
        ):
            self.assertIn(token, js)
        for token in (
            "Championship readability and density pass",
            "Recent history is navigation",
            "Knowledge graph explorer",
            ".aether-console .graph-explorer-shell",
            ".aether-console .graph-node",
            ".aether-console .graph-inspector",
            ".aether-console .session-result",
            "font-size:13px",
        ):
            self.assertIn(token, css)

    def test_console_final_legibility_contract_covers_loaded_chat_and_knowledge(self):
        css = self.read_page("assets/console.clean.css")
        for token in (
            "Final legibility contract",
            ".workbench-chat .msg .message-body",
            "border-left:3px solid var(--c-blue)",
            ".sessions .session b",
            "grid-template-columns:1.18fr 1fr 1fr",
            ".knowledge-admin-entry{grid-column:1/-1",
            "--c-muted:#536071",
        ):
            self.assertIn(token, css)

    def test_console_mobile_knowledge_and_accessibility_contract(self):
        html = self.read_page("console.html")
        css = self.read_page("assets/console.clean.css")

        self.assertIn('aria-label="菜单"', html)
        self.assertIn("padding:92px 13px 24px!important", css)
        self.assertIn("min-width:max-content;white-space:nowrap;word-break:keep-all", css)
        for color in ("#626b78", "#4f5968", "#5f6876", "#5f6875"):
            self.assertIn(color, css)

    def test_console_codex_reduction_contract(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.clean.css")
        self.assertIn("后台中心", html)
        self.assertIn("openKnowledgeBackstage()", html)
        self.assertIn("开始一个新任务", js)
        self.assertNotIn("检查 MemoryOS", js)
        self.assertIn("Codex-like reduction", css)
        self.assertIn(".workbench-chat .msg.user{justify-content:flex-end", css)
        self.assertIn(".command-drawer.on,.aether-console .settings-modal.on{display:grid", css)
        self.assertIn(".section-block:has(#ocrQueueTable)", css)

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
            "knowledgeGraphSummary",
            "knowledge-admin-toggle",
            "knowledgeFrontstageMetrics",
            "knowledgeActiveLibrary",
            "knowledgeBackendState",
            "knowledge-backstage-label",
            "knowledge-primary-search",
            "knowledgeTableHeading",
            "knowledgeResultCount",
            "knowledgeOrganizer",
        ):
            self.assertIn(token, html)
        for token in (
            "KNOWLEDGE_MODES",
            "renderKnowledgeWorkspaceShell",
            "toggleKnowledgeAdminTools",
            "updateKnowledgeFrontstageStats",
            "openKnowledgeOrganizer",
            "closeKnowledgeOrganizer",
            "publicKnowledgeNodeLabel",
            "科研资料",
            "学习资料",
            "写作资料",
            "项目资料",
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

    def test_console_exposes_evidence_knowledge_health_and_governance(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.clean.css")

        for marker in (
            "knowledgeHealthSummary",
            "knowledgeHealthGrid",
            "knowledgeGovernance",
            "knowledgeConflictTable",
            "knowledgeGovernanceStatus",
        ):
            self.assertIn(marker, html)
        for marker in (
            "loadKnowledgeGovernance",
            "openKnowledgeGovernance",
            "resolveKnowledgeConflict",
            "backfillKnowledgeV2",
            "/api/knowledge/v2/stats",
            "/api/knowledge/v2/conflicts",
            "/api/knowledge/v2/backfill",
        ):
            self.assertIn(marker, js)
        self.assertIn(".knowledge-health-card", css)
        self.assertIn(".knowledge-governance-sheet", css)

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

    def test_launcher_keeps_local_qwen_opt_in_and_never_auto_downloads(self):
        launcher = (REPO_ROOT / "start_clawos.bat").read_text(encoding="utf-8")
        qwen_starter = (REPO_ROOT / "clawos" / "scripts" / "start_qwen_llama_server.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("configuration-first mode", launcher)
        self.assertIn("No model weights or llama.cpp runtime will be downloaded", launcher)
        self.assertIn('if /I "%~1"=="--local" set "LOCAL_PROFILE=1"', launcher)
        self.assertIn('set "CLAWOS_CONFIG_PATH=%CLAWOS_DIR%\\config.local.json"', launcher)
        self.assertIn('set "EMBEDDING_PROVIDER=qwen3"', launcher)
        self.assertIn('set "RERANKER_PROVIDER=none"', launcher)
        self.assertIn('set "NO_PROXY=127.0.0.1,localhost,::1', launcher)
        self.assertIn('if defined LOCAL_PROFILE (', launcher)
        self.assertIn('start_qwen_llama_server.ps1', launcher)
        self.assertNotIn('start_qwen_llama_server.ps1" -Download', launcher)
        self.assertIn("[switch]$Download", qwen_starter)
        self.assertIn("rerun this script with -Download", qwen_starter)
        self.assertIn("[int]$Parallel = 1", qwen_starter)
        self.assertIn("-np $Parallel", qwen_starter)
        self.assertIn('[string]$GpuLayers = "20"', qwen_starter)

    def test_llama_cpp_downloader_ignores_cudart_only_archives(self):
        downloader = (REPO_ROOT / "clawos" / "scripts" / "download_llama_cpp.ps1").read_text(encoding="utf-8-sig")
        model_downloader = (REPO_ROOT / "clawos" / "scripts" / "download_qwen_model.ps1").read_text(encoding="utf-8-sig")

        self.assertIn('^llama-.*bin-win-(cuda|cu12).*x64\\.zip$', downloader)
        self.assertIn('$_.name -notmatch "(?i)^cudart-"', downloader)
        self.assertIn('-L -C - --retry 8', downloader)
        self.assertIn('cudart-llama-bin-win-cuda-', downloader)
        self.assertIn('ggml-cuda.dll', downloader)
        self.assertIn('cudart64*.dll', downloader)
        self.assertIn('if ($curl)', model_downloader)
        self.assertIn('$curlArgs = @("-L")', model_downloader)
        self.assertIn('$curlArgs += @("-C", "-")', model_downloader)
        self.assertIn('"--retry", "20", "--retry-all-errors"', model_downloader)

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
            "失败样本",
            "服务边界",
            "最近运行",
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
            "专业场景工作流",
            "professionalBoardGrid",
            "科研工作流",
            "学习工作流",
            "开发工作流",
            "办公工作流",
            "activateScenarioBoard",
            "引用完整 · 复现可审计",
            "格式有效 · 视觉验收",
        ):
            self.assertIn(token, js)
        self.assertIn(".professional-board-grid", css)
        self.assertIn(".board-card", css)

    def test_brand_mark_is_consistent_across_primary_surfaces(self):
        brand_dir = STATIC_DIR / "assets" / "brand"
        for asset in (
            "clawos-logo-dark.png",
            "clawos-logo-light.png",
            "favicon-16.png",
            "favicon-32.png",
            "favicon-48.png",
            "apple-touch-icon.png",
            "clawos-app-icon.png",
            "clawos-app.ico",
        ):
            self.assertTrue((brand_dir / asset).is_file(), asset)
        self.assertTrue((STATIC_DIR / "site.webmanifest").is_file())
        self.assertTrue((REPO_ROOT / "clawos" / "BRAND_GUIDELINES.md").is_file())
        for page in (
            "index.html",
            "product.html",
            "academy.html",
            "academy-code.html",
            "academy-ingest.html",
            "academy-notes.html",
            "academy-paper.html",
            "academy-path.html",
            "academy-quiz.html",
            "console.html",
        ):
            html = self.read_page(page)
            self.assertIn('/assets/brand/clawos-logo-dark.png', html)
            self.assertIn('/site.webmanifest', html)

    def test_academy_reader_atlas_and_studios_have_production_contracts(self):
        paper = self.read_page("academy-paper.html")
        path = self.read_page("academy-path.html")
        academy_js = self.read_page("assets/academy.js")
        site_css = self.read_page("assets/site.css")

        for token in (
            "paper-reader-workspace",
            "academyPdfFrame",
            "academyPenToggle",
            "academyHighlightToggle",
            "academyTextNoteToggle",
            "academyReaderNotes",
            "academyResearchOps",
        ):
            self.assertIn(token, paper)
        for token in (
            "academyLayerSearch",
            "atlas-view-switch",
            "atlas-rail",
            "academyLayerDetail",
            'data-atlas-view="map"',
            "history",
            "practice",
        ):
            self.assertIn(token, path)
        for token in (
            "academyFilterLayers",
            "academySetAtlasView",
            "academyFilterDomain",
            "academySwitchReaderTab",
            "academyToggleResearchOps",
            "academyExportReaderNotes",
            "academySetPdfSource",
            "academyToggleReaderFullscreen",
            "academyJumpPaperSection",
            "academySetupReaderNoteDraft",
            "academyDeleteReaderNote",
            "academySetupReaderControls",
            "frame.style.transform",
            "requestFullscreen",
            "history:",
            "domain:",
            "era:",
        ):
            self.assertIn(token, academy_js)
        for token in (
            ".paper-reader-workspace",
            ".atlas-rail",
            ".atlas-inspector",
            ".code-studio",
            ".notes-studio",
            ".ingest-studio",
            ".quiz-studio",
            ".fluent-icon",
            ".paper-empty-state[hidden]",
            ".reader-note-delete",
        ):
            self.assertIn(token, site_css)

        empty_state = paper.split('id="academyReaderEmpty"', 1)[1].split('</div>', 1)[0]
        self.assertNotIn("clawos-logo", empty_state)
        self.assertIn('id="academyReaderFullscreen"', paper)
        self.assertIn('id="academyZoomFit"', paper)
        self.assertIn('id="academySaveReaderNote"', paper)
        self.assertIn('id="academyReaderNoteStatus"', paper)
        self.assertNotIn('id="academyZoomIn" type="button" onclick=', paper)

        combined = "\n".join(
            self.read_page(name)
            for name in (
                "index.html",
                "product.html",
                "console.html",
                "academy.html",
                "academy-paper.html",
                "academy-path.html",
                "assets/console.js",
            )
        )
        for legacy_symbol in ("▶", "↺", "⟳"):
            self.assertNotIn(legacy_symbol, combined)

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
        self.assertIn("localAcceptanceHistoryTable", html)
        self.assertIn("localAcceptanceTrendGrid", html)
        self.assertIn("localRemediationGuide", html)
        self.assertIn("Local Acceptance History", html)
        self.assertIn("Run daily check", html)
        self.assertIn("Daily + Qwen", html)
        self.assertIn("Qwen smoke", html)
        self.assertIn("Export report", html)
        self.assertIn("refreshOfflineReadiness", js)
        self.assertIn("/api/workbench/offline-readiness", js)
        self.assertIn("/api/workbench/daily-local-acceptance", js)
        self.assertIn("/api/workbench/local-qwen-smoke", js)
        self.assertIn("/api/workbench/local-acceptance-history", js)
        self.assertIn("/api/workbench/local-acceptance-trends", js)
        self.assertIn("/api/workbench/local-remediation-guide", js)
        self.assertIn("/api/workbench/local-remediation-actions", js)
        self.assertIn("/api/workbench/local-maintenance-report", js)
        self.assertIn("exportLocalMaintenanceReport", js)
        self.assertIn("loadLocalRemediationGuide", js)
        self.assertIn("markLocalRemediationAction", js)
        self.assertIn("Mark reviewed", js)
        self.assertIn("Mark resolved", js)
        self.assertIn("loadLocalAcceptanceHistory", js)
        self.assertIn("runLocalQwenSmokeCheck", js)
        self.assertIn("include_qwen_smoke", js)
        self.assertIn("runDailyLocalAcceptance", js)
        self.assertIn("copyDailyLocalAcceptanceSummary", js)
        self.assertIn(".offline-readiness-panel", css)
        self.assertIn(".daily-acceptance-summary", css)
        self.assertIn(".local-acceptance-history", css)
        self.assertIn(".local-acceptance-trend-grid", css)
        self.assertIn(".local-remediation-guide", css)
        self.assertIn(".local-remediation-actions", css)
        self.assertIn(".local-remediation-card.resolved", css)
        self.assertIn("@app.get(\"/api/workbench/offline-readiness\")", server)
        self.assertIn("@app.post(\"/api/workbench/daily-local-acceptance\")", server)
        self.assertIn("@app.post(\"/api/workbench/local-qwen-smoke\")", server)
        self.assertIn("@app.get(\"/api/workbench/local-acceptance-history\")", server)
        self.assertIn("@app.get(\"/api/workbench/local-acceptance-trends\")", server)
        self.assertIn("@app.get(\"/api/workbench/local-remediation-guide\")", server)
        self.assertIn("@app.post(\"/api/workbench/local-remediation-actions\")", server)
        self.assertIn("@app.post(\"/api/workbench/local-maintenance-report\")", server)
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
        self.assertIn("enforced_scenario_routing", self.read_page("../clawos_server.py"))
        self.assertIn("lastRoutingStrategy", self.read_page("assets/console.js"))
        self.assertIn("场景路由", self.read_page("assets/console.js"))


if __name__ == "__main__":
    unittest.main()
