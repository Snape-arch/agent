# ClawOS Console Design QA

## Current desktop/mobile audit — 2026-07-17

- implementation: `http://127.0.0.1:18790/console`
- current-run states: desktop workbench, desktop knowledge, 390 × 844 mobile knowledge, mobile workbench, mobile model settings
- evidence method: Chrome accessibility snapshots plus current-run inline screenshots; Chrome DevTools MCP refused all requested workspace save paths, so this run does not claim durable local screenshot files
- automated snapshot after the approved P1 repairs: Lighthouse mobile accessibility 100, best practices 100; screenshot evidence alone does not establish full WCAG compliance

### Step health

1. Desktop workbench — healthy. Task entry, attachment, network toggle, approval mode, active tasks and truthful empty delivery/agent states are visible.
2. Desktop knowledge — healthy with minor polish risk. Upload, search, graph and recent sources are easy to find; the sidebar brand is visibly truncated.
3. Mobile knowledge — healthy after repair. The fixed header has a reliable content offset and category labels remain single-line in a horizontal scroller at 390 × 844.
4. Mobile workbench — healthy with minor density risk. Primary task flow remains usable; the textarea, attachment, network and send controls are compressed into a narrow row.
5. Mobile model settings — healthy. API/local/offline choices, local Qwen model and loopback Base URL are explicit; the modal fits the viewport and keeps save/cancel visible.

### Current findings

| Severity | Surface | Evidence | Recommendation | Code change |
| --- | --- | --- | --- | --- |
| Resolved P1 | Mobile knowledge header | 390 × 844 repair screenshot starts below the fixed header with normal spacing | Mobile main offset increased to 92 px | Done |
| Resolved P1 | Mobile knowledge filters | All five category labels remain horizontal; overflow scrolls instead of wrapping characters | No-wrap, fixed-width pills in horizontal scroller | Done |
| Resolved P1 | Accessibility contrast | Lighthouse accessibility increased from 96 to 100; contrast audit now passes | Darkened affected secondary text and table-header colors | Done |
| Resolved P1 | Mobile menu accessible name | Accessibility snapshot exposes the visible and accessible name as `菜单` | Aligned `aria-label` with visible text | Done |
| P2 | Mobile task composer | Textarea, attachment, network and send controls are tightly packed | Stack secondary controls below the textarea below 420 px | Optional CSS |
| P2 | Desktop sidebar brand | `ClawOS 工作台` is truncated to `ClawOS 工…` | Allow the title one more line or adjust brand block width | Optional CSS |

### Confirmed strengths and limits

- No P0 overlap, horizontal overflow, blocked primary action or misleading generated-delivery state was seen in the accepted screenshots.
- Model mode clearly distinguishes API, local and offline; current local Qwen configuration is visible without exposing a secret.
- Approval mode is visible on the workbench, and the tested settings modal did not silently perform a write.
- Accessibility score is a useful signal, not a compliance claim. Keyboard order, screen-reader announcements, zoom above 200% and error recovery still require direct interaction tests.

current result: the 4 user-approved P1 findings are repaired and re-verified; 2 optional P2 findings remain intentionally unchanged

- visual references: `codex-clipboard-adff59f0-83d7-43bd-ae63-f8b310c5dd82.png`, `codex-clipboard-1f98c037-a223-4e37-8c02-f23beb23ca27.png`
- implementation: `http://127.0.0.1:18790/console`
- viewport: 1440 x 1024
- inspected states: workbench, history/search, knowledge library, full-screen knowledge explorer
- evidence: `tmp/ui-qa/knowledge-explorer.png` and `tmp/ui-qa/history.png` (local QA only; intentionally excluded from Git)

## Final visual review — 2026-07-11

The implementation and the two accepted references were reviewed together at the same desktop viewport. The console now uses the same restrained enterprise workspace language: warm white canvas, one navigation rail, clear typographic hierarchy, thin borders, cobalt interaction states and content-first density. Legacy dark glass, diagonal overlays, duplicated navigation and floating composer obstruction are absent from the tested states.

### Findings resolved

- [P1] History entries resembled oversized chat bubbles and reduced scanability. They are now compact, border-separated navigation rows with readable titles and metadata.
- [P1] Low-contrast microcopy and inherited small type made tables and controls difficult to read. Base copy, labels, controls, tables and metadata now use an explicit 11–16 px hierarchy with higher ink contrast and Chinese font fallbacks.
- [P1] The embedded knowledge graph was too small for analysis. It now opens into a dedicated explorer with type/relation/search filters, a multi-band relationship canvas, legend, counts and a node inspector.
- [P1] Legacy theme layers obscured search, task and knowledge views. The final stylesheet resets those inherited pseudo-layers and keeps all views in normal document flow.
- [P2] Product navigation was previously lost in the console. Home, Product and AI Academy links are present in the contextual header and remain visually subordinate to work controls.

### Interaction and quality checks

- Sidebar navigation changed URL state and loaded the knowledge view successfully.
- “展开图谱” opened the standalone explorer; close, refresh and filter controls are present and keyboard-focusable.
- Knowledge counts, node labels, relationship lines, legend and inspector fit within 1440 x 1024 without overlap.
- Workbench composer, quick actions, active work, autonomy control and delivery table remain visible without sticky obstruction.
- History/sidebar entries remain readable and no longer use translucent conversation-card styling.
- Browser console was checked during the workbench pass and contained no errors.
- JavaScript syntax, frontend static contracts and the full Python regression suite are recorded in `PROJECT_CONTEXT.md`.

### Implementation checklist

- [x] One coherent console design system across every view.
- [x] Readable Chinese/English typography and dense enterprise tables.
- [x] Lightweight history navigation instead of chat bubbles.
- [x] Expandable, filterable knowledge graph workspace.
- [x] Product-level navigation and responsive overflow protection.
- [x] Browser-rendered visual acceptance at 1440 x 1024.

final result: passed

## Academy document reader and learning atlas - 2026-07-14

- implementation: `http://127.0.0.1:18790/academy`, `/academy/paper`, `/academy/path`, `/academy/code`, `/academy/notes`, `/academy/ingest`, `/academy/quiz`
- local evidence: `tmp/ui-qa/academy-redesign/` (intentionally excluded from Git)
- tested viewports: 1440 x 1024, 1280 x 720, 390 x 844

Resolved findings:

- [P0] The paper page is now a document-first reader rather than a form dashboard: original PDF canvas, outline, zoom/fit, pen, highlighter, text notes, evidence questions and guided writing share one workspace.
- [P0] Operational audit, timeline, checkpoints, project board and exports remain available but are consolidated behind one secondary disclosure, protecting the primary reading task.
- [P1] The learning path now exposes 14 connected layers with domain and difficulty filters plus knowledge, history and practice views. Every node includes concepts, development history, representative material, experiments and mastery evidence.
- [P1] Code, guided notes, ingest and quiz use the same typography, navigation, cards, controls and truthful states as the Academy reader and atlas.
- [P1] Remaining text-symbol icons were replaced by the formal Fluent icon font, and brand assets now cover browser, desktop, light/dark and minimum-size applications.

Interaction and responsive verification:

- Reader note tab, research-operations disclosure and highlighter states changed correctly.
- Atlas development-history view and professional difficulty filter reduced the visible graph to the expected seven nodes.
- All seven Academy pages had document width less than or equal to viewport width at 1440 and 390; paper/path also passed 1280 x 720.
- Desktop and mobile contact sheets were reviewed together. No overlapping panels, clipped primary actions or fake progress counters remained.

final result: passed - visual/product score 93/100

## Brand identity and professional workflow polish — 2026-07-13

- source screenshots: `codex-clipboard-afbba9de-cd35-4383-8597-124ef830abbb.png`, `codex-clipboard-a1955c10-4477-4741-9f73-27e372ab4f0c.png`
- implementation: `http://127.0.0.1:18790/console#scenes`, `http://127.0.0.1:18790/console#tasks`
- paired comparison: `tmp/ui-qa/brand-runtime-comparison.png` (local QA only; excluded from Git)
- tested viewports: 1440 x 1024, 1280 x 720, 760 x 900

Resolved findings:

- [P1] Replaced the uneven four-board form layout with a reusable Academy-aligned card system: numbered header, Chinese title and summary, three capabilities, an explicit quality gate and one primary next action.
- [P1] Replaced raw English runtime keys with readable Chinese labels while retaining original service identifiers as title metadata. Normalized all card titles, supporting copy, metrics and failure samples to one hierarchy.
- [P1] Added a unique ClawOS mark and applied it across Overview, Product, Academy and Console. Added restrained hover motion and a reduced-motion fallback.
- [P2] Added four-to-two-to-one column reflow for scenarios and three-to-two-to-one reflow for runtime evidence. No overlap or horizontal overflow appeared at the tested states.

Interaction verification:

- The research scenario CTA resolved uniquely, switched to the workbench and inserted the expected research workflow prompt.
- Runtime cards rendered real schema/run/failure counts from the existing APIs; no placeholder metrics were introduced.
- The final 1280 x 720 and narrow screenshots retained readable type, complete card actions and unobstructed scrolling.

final result: passed

## Truthful console and responsive closure — 2026-07-13

- reference: `codex-clipboard-adff59f0-83d7-43bd-ae63-f8b310c5dd82.png`
- implementation: `http://127.0.0.1:18790/console`
- tested viewports: 1280 × 720, 1440 × 1024, 390 × 844
- tested states: truthful workbench empty state, loaded conversation, compact history, knowledge foreground, centered organizer, full-screen graph explorer, mobile navigation and collapsible task progress

Resolved findings:

- [P0] Removed the model/tool counters, sample deliveries and invented 100% progress. Active work now filters to real running states and only renders progress supplied by the backend; otherwise it shows a truthful state label or empty state.
- [P0] Reduced the knowledge foreground to upload, search, graph entry and recent sources. Session capture and editing now live in a centered secondary dialog. Graph labels and inspector descriptions sanitize local paths.
- [P1] Standardized the foreground to 14 px body copy and 12–13 px supporting copy, removed unnecessary English micro-labels and kept high-contrast neutral text.
- [P1] Rebuilt history as compact title/summary/time/continue rows. Loaded chats keep user turns right and Agent turns left; real task progress is available in a keyboard-closeable side panel.
- [P2] Fixed the mobile navigation state mismatch and added a visible menu trigger. Verified no page-level horizontal overflow at 390 px, centered modal geometry at 1440 px, focus-visible states and Escape dismissal.

Browser verification:

- Knowledge recent rows span the full content width; organizer measured 760 px wide and centered at x=340 in a 1440 px viewport.
- Graph explorer contained no Windows drive, Users or Desktop path fragments.
- Loaded conversation geometry placed user content on the right and Agent content at the left reading edge.
- Browser warning/error log was empty after the final pass.

final result: passed

## Codex-style foreground/backstage reduction — 2026-07-11

- source screenshots: `codex-clipboard-0ec35122-2888-4869-a8df-4b66a04a25cf.png`, `codex-clipboard-c18fc990-5152-445d-81ce-ae507aaf076e.png`, `codex-clipboard-bd1a51d7-2544-4488-a054-1910cae6dd55.png`, `codex-clipboard-4215613e-8980-45d7-80ff-e35151c613c8.png`
- implementation evidence: `tmp/ui-qa/codex-reduced-new-task.png`, `codex-reduced-chat.png`, `codex-reduced-knowledge.png`, `codex-reduced-backstage.png`, `codex-reduced-settings.png`
- paired comparison: `tmp/ui-qa/codex-reduction-comparison.png` (local QA only; excluded from Git)

Resolved findings:

- [P1] New-task state inherited the old oversized glass surface and shortcut cards. It is now a compact task empty state with one instruction and the existing composer.
- [P1] Conversation roles were visually ambiguous. User turns are right-aligned in restrained neutral bubbles; Agent turns remain left-aligned in the reading column.
- [P1] Knowledge mixed foreground creation with reporting, OCR, validation and delivery administration. The visible page now retains upload, session capture, editor, graph, search and knowledge items; operational detail is consolidated behind one Backstage entry.
- [P1] Model settings inherited viewport offsets and horizontal overflow. Both settings and Backstage now use centered, bounded modal geometry with local scrolling.
- [P2] Backstage exposed ten equally weighted low-frequency pages. It now presents four product-level groups: runtime, capabilities, governance and model configuration.
- [P2] Knowledge item tables exposed raw source paths, tags and visit counters. The foreground table now keeps only title, library and primary actions.

Browser verification:

- New task, loaded conversation, knowledge foreground, Backstage and model settings were exercised in the in-app browser.
- Backstage center measured `760 x 305` with center `(633, 360)` in a `1280 x 720` effective viewport.
- Model settings measured `720 x 441` with the same centered Y axis; no page-level horizontal overflow appeared.
- Browser warning/error log was empty after the final reload.

final result: passed

## Final residual legibility review — 2026-07-11

- new user evidence: `codex-clipboard-fc4f11dd-cd26-452d-accc-95a0783b9492.png` and `codex-clipboard-71925e72-1dad-4bbf-8b20-2295b5450cdc.png`
- implementation evidence: `tmp/ui-qa/final-knowledge-top.png` and `tmp/ui-qa/final-history-conversation.png`
- combined comparison: `tmp/ui-qa/final-comparison.png` (local QA only; excluded from Git)

Resolved findings:

- [P1] Loaded conversation messages still inherited the former translucent bubble geometry, producing oversized white cards and unreadable white text. The workbench now renders both roles as compact, full-width document rows with dark 13 px copy, restrained role rails, normal content height and no glass effects.
- [P1] Knowledge typography mixed 9–26 px labels with low-contrast grey. The view now follows a fixed 24 px page title, 16 px card title, 13 px body/control and 11–12 px metadata hierarchy with WCAG-oriented darker neutral tokens.
- [P1] The knowledge hero used four uneven columns and isolated the admin state in a narrow card. It is now a balanced three-column capability grid with the admin control consolidated into one compact horizontal row.
- [P2] Backend state text switched to English after JavaScript initialization. Open/closed state and its action now remain consistently Chinese.

Browser validation:

- Rechecked live knowledge and loaded-history states at 1440 x 1024.
- Measured loaded message rows at 78 px rather than the former oversized floating cards; backgrounds are transparent, radii are zero and text is dark.
- Verified knowledge title/body/metric hierarchy from computed styles and inspected the full visual comparison alongside the supplied screenshots.
- Browser warning/error log: empty.

final result: passed
