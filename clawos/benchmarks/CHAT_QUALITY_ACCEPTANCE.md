# Chat invocation and rendering acceptance — 2026-09-23

## Corrected paths

- A completed tool-loop answer is delivered directly, without a second model rewriting it or rebuilding retrieval context. Fast paths that have only tool results still use the answer provider, with properly paired assistant/tool messages.
- Provider fallback expands environment references inside lists, uses each fallback's own model name and can run when only the fallback is configured. Explicit empty per-section fallback lists remain empty.
- Reasoning-only, blank, filtered and length-truncated completions are not reported as successful final answers. Content blocks are normalized consistently for routing and delivery. Public provider metadata omits the raw model envelope.
- Request-supplied multi-turn history is honored. Attachment context does not duplicate the current user question. Full assistant messages persist, while the existing context budget controls what is sent back to models.
- Shared response instructions favor direct, specific prose and purposeful Markdown instead of compulsory headings, stock introductions and repeated summaries. They preserve code and technical terminology.
- Locally vendored markdown-it 14.1.0 replaces the handwritten parser. Nested lists, continuation paragraphs, escaped table pipes, reference/balanced links, code fences and code copying share one renderer in live and reopened messages. Raw HTML is disabled; image syntax does not trigger remote image requests.
- The SSE reader handles fragmented UTF-8, CRLF, multi-line data and a trailing frame. Malformed, interrupted, empty and truncated responses surface errors. An interrupted answer retains the text already received.

## Verification

Run from repository root:

```powershell
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos/tests
node --test clawos/tests/chat_content.test.cjs
```

Final complete regression: **610/610**, 296.917 seconds; Node Markdown/SSE **7/7**, routing **34/34**. An intermediate run exposed an older success fixture without an answer provider; the fixture now configures a mock provider, while a separate regression verifies missing-provider failure. Existing FastAPI/openpyxl/SWIG warnings remain non-blocking.

Real-provider synthetic acceptance:

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/chat_quality_acceptance.py --live --output clawos/output/chat-quality-live-20260923
```

The explicit `--live` flag uses configured credentials and may incur charges. It loads an isolated SQLite store, not production memories or documents. Without that flag the script uses mock mode. Reports and databases stay ignored under output. MTClaw, vectors and reflection are not enabled by this harness; this is acceptance of the configured direct-provider chat path.

Five real DeepSeek requests returned answers without fallback: a two-sentence explanation, a table plus Python dictionary from supplied values, fact recording and retrieval across two turns, and a calculator result. Manually checked values: both plans retained 10/3 and 20/1; follow-up retained 青禾/37; calculation returned 3973. These are synthetic development checks, not an independent quality benchmark.

The actual console was opened on an isolated loopback preview. A further real model request converted the saved table into two numbered items with nested cost/time bullets. Table, code block and nested list rendered; refreshing and reopening restored them. Desktop and 390×844 layouts were visually checked; measured page scroll width equaled the 390px viewport. Code-copy UI was exercised. Node tests check protocol failure handling independently.

## Boundaries

SSE currently delivers buffered model results; this change does not add native token streaming or prove cancellation of a provider request already in flight. General factual accuracy, arbitrary LaTeX/Mermaid rendering, target-MTT performance and separate live MTClaw acceptance are not claimed. Production services were not restarted by the QA harness. Restart an existing ClawOS process to load the Python changes; versioned console asset URLs load the new renderer.

The pre-existing competition architecture script still reports 75/100: upstream provenance is unresolved and its literal-text/handler-only checks do not reflect the current stream condition and dedicated coding-agent dispatch. This change does not waive those release checks.
