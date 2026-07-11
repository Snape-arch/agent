# ClawOS Console Design QA

- source visual truth: `C:\Users\34712\.codex\generated_images\019f4efa-6a16-7b03-bab1-5635b52255fa\exec-72d74261-b5f9-4994-8897-32013f57c87d.png` with the workbench/data-delivery structure from `exec-c0dfaa5c-50c9-473c-a1b3-be815c7e6675.png`
- implementation target: `http://127.0.0.1:18790/console`
- viewport: 1440 × 1024
- state: default workbench (`#chat`)
- implementation screenshot: unavailable

## 2026-07-11 screenshot remediation

- user evidence: `C:\Users\34712\AppData\Local\Temp\codex-clipboard-a58f4872-4796-4f11-b3e0-65e923893710.png`
- observed P1 issues: legacy dark workspace overlay remained behind the light workbench; sticky composer covered the delivery table; decorative traffic lights and old button highlights leaked into the new theme; global product navigation had been removed.
- fixes: removed legacy workspace pseudo-layers and dark backgrounds from the active shell, disabled inherited highlight pseudo-elements, moved the composer into the intent panel, restored desktop and narrow-screen links to Home/Product/Academy, and added regression contracts for unique composer IDs and overlay removal.
- post-fix browser screenshot: still unavailable through the in-app browser loopback surface, so the final result remains honestly blocked pending one user-visible reload/capture.

## 2026-07-11 full-view residual removal

- user evidence: four screenshots covering Workbench, Task Trace, Search and Knowledge Library.
- observed P1 issue: legacy selectors continued to leak into every non-workbench view, including diagonal `panel-view` overlays, white-on-grey text, dark runtime cards and glass-form controls.
- structural fix: `console.clean.css` is now loaded last as the sole final presentation contract. It resets every legacy pseudo-layer, dynamic runtime card, search result, knowledge mode, project/scenario surface, backend table, drawer and modal to one light editorial token system. It also enforces auto-height document flow, local table overflow and responsive grid collapse.
- automated evidence: clean-style contract tests, JavaScript syntax, 36 frontend tests and 258 full tests pass.
- post-fix browser capture: still requires a user-visible reload because the in-app browser cannot reach the host loopback service.

**Findings**

- [P1] Browser-rendered comparison unavailable
  - Evidence: the local service returned HTTP 200 from the workspace, but the in-app browser surface could not reach the host loopback service and displayed `ERR_CONNECTION_REFUSED`.
  - Impact: typography, spacing, overflow and final visual fidelity cannot be truthfully certified from source code or static tests alone.
  - Fix: reopen the running console in an accessible browser surface and capture the 1440 × 1024 default workbench before final visual acceptance.

**Static and interaction checks completed**

- Fonts and typography: explicit Inter/PingFang SC/Microsoft YaHei stack, controlled Chinese wrapping, 10–42 px hierarchy.
- Spacing and layout rhythm: single 224 px rail, 76 px contextual header, 1240 px workbench frame, responsive 1100/760/480 px breakpoints.
- Colors and visual tokens: warm canvas, white surfaces, ink text, cobalt active state, semantic green/amber, restrained elevation.
- Image quality and assets: no new raster asset is required by the selected document-centric console target; robot/mascot imagery is removed from the core working surface.
- Copy and content: task-first Chinese copy, explicit approval language, honest sample labeling for delivery preview.
- Primary interactions: static contracts cover navigation, quick prompts, dynamic task rendering, autonomy persistence, task progress links, command drawer and existing backend views.
- Console errors checked: blocked because the implementation could not be loaded in the in-app browser.

**Comparison history**

- Initial implementation review found duplicated navigation, fake task progress, an incorrectly closed task-list container, global API refresh on every navigation, and glass/HUD styling.
- Fixes applied: one primary rail, dynamic `/api/tasks` rendering, corrected DOM structure, per-view refresh, persistent accessible autonomy control, restrained workbench tokens, backstage drawer consolidation.
- User screenshot then exposed remaining legacy overlay and composer stacking; these were fixed structurally rather than by adding another theme.
- Post-fix visual evidence: blocked by browser loopback isolation; static frontend tests and JavaScript syntax checks pass.

**Implementation Checklist**

- [x] Single task-first navigation and contextual header.
- [x] Dynamic workbench task progress.
- [x] Office delivery quality surface and subagent visibility.
- [x] Accessible autonomy mode with persisted selection.
- [x] Responsive layout and horizontal data-table protection.
- [ ] Browser screenshot comparison at 1440 × 1024.

final result: blocked
