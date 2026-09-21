# ProcureDelta Pipeline Control Room Design

**Date:** 2026-09-21  
**Status:** Written design for review; implementation has not started.  
**Target role:** StepAI — AI Full-Stack Developer (LLM pipeline · large-scale data collection)

## 1. Why this expansion exists

ProcureDelta already implements a broad procurement-data pipeline, but the public demo currently makes a reviewer infer too much from separate pages.

The next version should make one thing obvious within 30–60 seconds:

> "This candidate built an end-to-end data/LLM service, not a single LLM feature."

The project therefore becomes broader in **pipeline visibility**, not by adding unrelated features.

The public demo should expose the path from external data acquisition to a business-facing decision:

`collect → dedupe → normalize → document parse/OCR → structured extraction → schema/evidence validation → lifecycle link → Delta → eligibility → ranking → notification`

The demo must preserve the current project's strongest distinction:

- not a generic RAG chatbot,
- not a one-shot document summarizer,
- not a scraper that ends at a dashboard,
- but a lifecycle/change intelligence system with replayable evidence and operational boundaries.

## 2. Success criteria

A reviewer who opens the demo should be able to answer these questions without reading the README first:

1. What data enters the system?
2. Which processing stages run?
3. Where does LLM/OCR fit, and where does deterministic logic take over?
4. What changed between two procurement versions?
5. Why did company eligibility/recommendation change?
6. What happens when upstream/processing fails?
7. What has actually been measured versus simulated or not run?
8. Can the entire stack be verified rather than only the happy-path UI?

The implementation is successful only if all of those can be understood from the product UI itself.

## 3. Chosen approach

### Approach A — add more product features
Examples: chatbot, extra recommendation features, billing, more notification channels.

**Rejected.** This increases surface area but does not improve comprehension of the existing engineering depth. It also pushes the project toward the same generic AI SaaS shape seen in many portfolios.

### Approach B — build a separate technical microsite
Create a second demo dedicated to diagrams and benchmark screenshots.

**Rejected.** It separates the technical story from the actual product and risks looking like documentation rather than a working service.

### Approach C — integrate a Pipeline Control Room into ProcureDelta
Add a reviewer-facing interactive pipeline demo backed by existing production modules and committed verification artifacts.

**Chosen.**

This preserves one product, one repository, one public demo, and one engineering story.

## 4. Product information architecture

### 4.1 New primary page: `/pipeline`

The top navigation gains a **파이프라인** item.

The landing page adds a visible CTA to the same page. The existing "제품 둘러보기" path remains available.

The page has five sections:

1. Scenario switcher
2. Pipeline stage map
3. Stage inspector
4. Scale / failure evidence
5. Evaluation / limitations

The page should be understandable as a demo before the reviewer opens the existing inbox.

### 4.2 Existing pages remain

- `/` — product landing
- `/inbox` — opportunity inbox
- `/opportunities/[id]` — evidence, timeline, Delta
- `/profile` — company conditions
- `/watchlist`
- `/notifications`
- `/about` — evaluation and limitations
- `/admin` — operator metrics / failures

The expansion should connect these pages rather than replace them.

## 5. Pipeline Control Room UX

### 5.1 Scenario switcher

The first screen exposes three deterministic scenarios.

#### Scenario 1 — 신규 공고
Purpose: show the ordinary end-to-end flow.

Stages:

1. source payload discovered
2. checksum / duplicate decision
3. normalization
4. attachment discovery
5. native parse
6. OCR routing decision
7. structured extraction
8. schema/evidence validation
9. hard eligibility
10. relevance ranking
11. notification decision

#### Scenario 2 — 정정으로 조건 변경
Purpose: show ProcureDelta's uncommon lifecycle/delta value.

The reviewer sees:

- before version,
- after version,
- machine-readable field changes,
- evidence,
- deterministic impact reason codes,
- old eligibility,
- new eligibility,
- ranking consequence,
- notification trigger.

The demonstration should make the chain visually obvious:

`amendment → delta → eligibility changed → recommendation changed → alert`

#### Scenario 3 — 장애와 복구
Purpose: show production thinking rather than only a happy path.

The view shows existing verified behaviors:

- timeout retries,
- 429 retry,
- repeated 5xx terminal failure,
- 403 no-retry,
- retry queue,
- DLQ boundary.

It must clearly label synthetic transport injection and must not imply a real public API outage occurred.

### 5.2 Stage map

Desktop: horizontal/zig-zag pipeline map.  
Mobile: vertical stage rail.

Each stage displays:

- stage label,
- status,
- deterministic/LLM/OCR/system badge,
- optional measured duration,
- input/output counts only when sourced from an artifact,
- warning/failure state.

Selecting a stage opens the inspector.

### 5.3 Replay interaction

A **재생** action advances through the selected scenario.

This is a visualization of a deterministic scenario execution, not fake real-time processing.

The UI must say:

- `재생 중` rather than `실시간 처리 중`,
- `합성 시나리오` when the source is synthetic,
- `저장된 검증 결과` for committed artifacts,
- `미실행` for metrics that do not exist.

The animation may use client timing for presentation, but that timing must never be presented as backend latency.

### 5.4 Stage inspector

The right-side inspector shows four tabs where available:

- 입력
- 출력
- 근거
- 판단

Example for structured extraction:

**Input**
- parsed text excerpt
- parser kind
- source/evidence reference

**Output**
- extracted fields
- schema version
- validation state

**Evidence**
- field → source pointer
- page/record/checksum identifiers when available

**Decision**
- accepted / rejected
- validation reason

Example for Delta:

- field name
- before value
- after value
- impact
- deterministic reason code
- evidence pointers

Example for eligibility:

- hard failure list
- warnings
- relevance score separately
- explicit note that ranking cannot override a hard failure

## 6. Reviewer-first visual hierarchy

The page should prioritize comprehension over raw dashboard density.

Top area:

- title: **파이프라인을 직접 재생해보세요**
- one-line explanation
- three scenario buttons
- one visible play/reset control

Second area:

- pipeline map

Third area:

- selected stage inspector

Fourth area:

- verified evidence cards

A reviewer should not need to scroll through a long admin dashboard before seeing the core flow.

## 7. Backend architecture

No new database tables are required for the first implementation.

### 7.1 Reuse existing production modules

The replay layer should call or project from existing domain modules rather than reimplement logic:

- source mapping / ingestion contract
- normalization
- document parser and OCR routing
- extraction validation
- lifecycle linking
- Delta engine
- eligibility
- ranking
- notification trigger logic
- historical replay utilities

The replay API must not mutate the user's production-like demo data.

### 7.2 Synthetic scenario boundary

Create a dedicated module:

`apps/api/app/demo/control_room.py`

Responsibilities:

- define allowlisted scenario ids,
- load packaged synthetic fixtures,
- run pure/deterministic production functions,
- build a stage-by-stage response,
- attach provenance and limitation labels,
- never perform external paid/network calls by default,
- never write production DB state.

### 7.3 New API endpoints

Under the existing versioned API:

- `GET /api/v1/demo/pipeline/scenarios`
- `GET /api/v1/demo/pipeline/scenarios/{scenario_id}`

The detail endpoint returns a fully replayable scenario result.

No POST mutation is needed for the public demo. Client replay is presentation state.

Unknown scenario ids return 404.

### 7.4 Response model

Conceptual response:

```json
{
  "scenario_id": "amendment-eligibility-change",
  "title": "정정으로 참여 가능 여부 변경",
  "synthetic": true,
  "source_scope": "packaged_fixture",
  "stages": [
    {
      "id": "delta",
      "label": "Delta",
      "kind": "deterministic",
      "status": "passed",
      "measured_duration_ms": null,
      "input": {},
      "output": {},
      "evidence": [],
      "decision": {},
      "notice": null
    }
  ]
}
```

The model must distinguish:

- `measured_duration_ms`
- presentation animation timing

The latter must never be returned as a metric.

## 8. Static public demo

The current Render demo uses `NEXT_PUBLIC_STATIC_DEMO=true`.

That must remain supported.

### 8.1 Static parity

`apps/web/lib/static-demo.ts` receives the same three pipeline scenario payloads.

The static payloads should be generated from or contract-tested against the backend scenario schema so the public demo does not drift from the real API shape.

### 8.2 No false live behavior

The public static demo must not claim that it is currently:

- polling KONEPS,
- calling a hosted LLM,
- running OCR,
- processing a live Redis queue,
- sending real external notifications.

The UI should instead make the boundary visible:

**합성 시나리오 · 실제 파이프라인 계약 기반 재생**

## 9. Scale and data-collection evidence

The project needs to communicate large-scale processing without fabricating production traffic.

### 9.1 Current committed measurements to expose

From committed artifacts:

#### CPU pipeline
- 50,000 synthetic normalized records
- 50,000 ranking executions
- 5,000 Delta comparisons
- approximately 6.995 s total
- approximately 7,148 records/s

Must be labeled:

**CPU-only production-function benchmark**

It is not DB throughput, queue throughput, public API throughput, OCR throughput, or SaaS capacity.

#### Release gate
Expose pass/fail state for:

- PostgreSQL + Redis
- backend integration
- readiness
- browser lifecycle E2E
- queue scale
- query plans
- HTTP load

Where the public artifact contains only gate success/duration, show only that. Do not invent throughput or p95 values.

#### HTTP failure drill
Expose:

- timeout recovery after 3 attempts
- 429 recovery after 2 attempts
- repeated 500 terminal after 3 attempts
- 403 no retry

Label it as synthetic HTTP transport injection.

### 9.2 New sanitized measurement artifacts

During implementation, update the verification pipeline so successful queue/load/query scripts publish small, sanitized JSON summaries into:

- `artifacts/performance/queue.json`
- `artifacts/performance/http.json`
- `artifacts/performance/query-plans.json`

Only expose metrics after those files are actually produced and verified.

No secret URLs, credentials, cookies, HAR files, or raw sensitive payloads may be committed.

### 9.3 Funnel presentation

A funnel/card visualization may show:

`raw → unique → normalized → documents → extraction → usable decision`

only when every displayed count comes from the same measured run.

Until such a run exists, use stage names without invented counts.

## 10. LLM / OCR evaluation presentation

The current evaluation page already exposes honest stored metrics.

The expansion should make the evaluation easier to understand at a glance.

### 10.1 Route comparison table

Rows:

- deterministic extraction
- hosted all
- hosted gated
- OCR

Columns where measured:

- status
- support
- field accuracy
- schema failures
- grounded acceptance
- p50 latency
- p95 latency
- calls
- prompt tokens
- completion tokens
- reported cost

Missing metrics stay **미측정**.

Current hosted routes are `not_run`; the UI must show that rather than simulate an LLM comparison.

### 10.2 Evaluation caveat card

Always show:

- synthetic regression set
- real public records count
- OCR language/scope
- hosted evaluation status
- data/source hashes

This prevents a polished UI from making the evidence look stronger than it is.

## 11. Admin integration

The existing Admin console remains an operator page.

Add a compact pipeline overview above the current KPI cards:

`collect → parse → extract → delta → eligibility → rank → notify`

It should use current database/worker metrics when available.

The public `/pipeline` page and operator `/admin` page serve different purposes:

- `/pipeline`: reviewer comprehension and deterministic replay
- `/admin`: current operational state and failure recovery

Do not merge them into one overloaded page.

## 12. Landing page integration

Keep the current product identity and headline.

Add a visible secondary CTA:

**파이프라인 데모 보기**

The hero product preview may include a small pipeline strip so the reviewer understands the project before entering the app.

Do not add marketing metrics that are not measured.

## 13. Navigation

Product navigation becomes:

- 공고함
- 파이프라인
- 관심 공고
- 알림
- 기업 프로필
- 평가·한계

This puts the technical differentiator near the front without hiding the actual product.

## 14. Visual language

Continue the current ProcureDelta design system:

- forest green / ivory / orange,
- structured data grid,
- asymmetric technical panels,
- restrained shadows,
- no generic glowing AI orb,
- no chatbot bubble as the main interaction,
- no fake real-time charts.

Pipeline stage colors should encode meaning consistently:

- system/data: neutral green
- deterministic decision: deep green
- OCR: amber
- optional LLM: violet/indigo accent only where actually used
- warning/retry: amber
- terminal failure/DLQ: red
- not run/not measured: gray

Color cannot be the only status signal; labels/icons/text are required.

## 15. Accessibility and mobile

Requirements:

- every stage is keyboard-selectable,
- selected state has text/ARIA state,
- replay can be paused/reset,
- no auto-animation on reduced-motion preference,
- stage details remain readable at 390 px viewport,
- no horizontal overflow,
- charts have textual summaries,
- all critical evidence is available without hover.

## 16. Honest boundaries

The following must remain visible in UI/docs:

- public demo uses synthetic data,
- real KONEPS integration currently covers service tender notices and observed changes only,
- full five-stage lifecycle is demonstrated synthetically,
- live KONEPS credential smoke is separate,
- Korean production OCR is not validated,
- hosted LLM evaluation is not currently run,
- CPU benchmark does not equal service throughput,
- public static demo does not run the real queue or external notifications,
- Render public web demo does not prove full cloud backend deployment.

## 17. Testing strategy

### 17.1 Backend unit tests

- scenario ids are allowlisted
- stage order is stable
- each scenario uses production functions rather than duplicated outcome constants
- amendment scenario produces a material Delta
- changed Delta changes eligibility as expected
- hard failure cannot be overridden by rank
- failure scenario correctly exposes retry/non-retry distinctions
- no scenario performs external network calls

### 17.2 API tests

- scenario list
- valid scenario detail
- unknown scenario 404
- synthetic/provenance labels always present
- measured vs non-measured durations remain distinct

### 17.3 Frontend unit/contract tests

- pipeline navigation exists
- all three scenarios render
- replay controls advance/reset
- selected stage inspector changes
- `미측정` is rendered for absent hosted metrics
- static demo shape matches API types

### 17.4 Browser tests

Desktop and mobile:

1. open landing
2. enter pipeline demo
3. run amendment scenario
4. select Delta stage
5. verify before/after values
6. select eligibility stage
7. verify changed eligibility
8. open failure scenario
9. verify retry/DLQ explanation
10. navigate to evaluation

No page errors and no horizontal overflow.

### 17.5 Release verification

Existing gates must remain green:

- frontend lint/typecheck/test/build
- backend lint/types/tests
- PostgreSQL/Redis integration
- runtime/readiness
- browser lifecycle E2E
- queue scale
- query plan
- HTTP load

Add a new pipeline-demo browser contract to the release gate.

## 18. Files expected to change

Likely frontend:

- `apps/web/app/(product)/pipeline/page.tsx`
- `apps/web/components/pipeline/*`
- `apps/web/components/app-shell.tsx`
- `apps/web/app/page.tsx`
- `apps/web/app/(product)/about/page.tsx`
- `apps/web/app/styles.css`
- `apps/web/app/mobile-fixes.css`
- `apps/web/lib/api.ts`
- `apps/web/lib/static-demo.ts`
- tests under `apps/web/tests` and `apps/web/e2e`

Likely backend:

- `apps/api/app/demo/control_room.py`
- `apps/api/app/api/demo.py`
- `apps/api/app/api/schemas.py` or dedicated demo schemas
- `apps/api/app/main.py`
- evaluation public projection updates
- tests under `apps/api/tests/demo` and `apps/api/tests/api`

Verification/artifacts:

- `scripts/verify_containers.py`
- performance/load scripts only as needed for sanitized output
- `artifacts/performance/*.json`
- `docs/evaluation.md`
- `docs/performance.md`
- `docs/verification.md`
- README screenshots/section after implementation is verified

## 19. Explicit non-goals

Do not add in this phase:

- generic chatbot
- RAG chat interface
- autonomous purchasing agent
- payment/subscription
- Kafka
- Kubernetes
- another vector database
- fabricated "real-time" monitoring
- unmeasured hosted-model claims
- new database schema unless implementation proves it is necessary
- additional public-data sources solely for feature count

## 20. Delivery sequence

The implementation should be divided into independently verifiable slices:

1. backend scenario contract
2. static-demo parity
3. pipeline page / stage inspector
4. amendment replay
5. failure mode
6. evaluation comparison
7. scale evidence projection
8. admin/landing integration
9. browser accessibility/mobile checks
10. full release gate
11. screenshots / README / portfolio update only after final verification

## 21. Final reviewer experience

Ideal 60-second path:

1. Open ProcureDelta.
2. Click **파이프라인 데모 보기**.
3. Select **정정으로 조건 변경**.
4. Press **재생**.
5. Watch the stage map advance.
6. Open **Delta** and see before/after + reason codes.
7. Open **Eligibility** and see why the company moved from allowed to blocked.
8. Open **Scale / Failure** and see measured evidence plus honest scope.
9. Open **평가·한계** and see what was measured, synthetic, or not run.
10. Optionally enter the normal inbox to inspect the product.

The intended reviewer takeaway is:

> "The project covers collection, async processing, document/LLM extraction, validation, lifecycle change detection, deterministic decision logic, ranking, failure recovery, evaluation, and a real product UI — and the candidate made the evidence inspectable rather than hiding it in README text."
