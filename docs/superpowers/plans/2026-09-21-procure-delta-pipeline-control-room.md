# ProcureDelta Pipeline Control Room Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reviewer-first Pipeline Control Room that replays three deterministic ProcureDelta scenarios, exposes honest scale/failure/evaluation evidence, and makes the existing end-to-end data/LLM architecture understandable within 30–60 seconds.

**Architecture:** Keep the current product and persistence model intact. Add a read-only demo projection in the FastAPI backend that composes existing production functions into allowlisted synthetic scenarios, mirror those responses in static-demo mode, then build a Next.js pipeline page with stage replay, inspector, scale/failure evidence, and evaluation links. No new database tables are introduced; committed benchmark/release artifacts are exposed only through sanitized, typed projections.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, SQLAlchemy domain models, Redis/ARQ contracts, Next.js 16, React, TypeScript, Node 22, Playwright, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-21-procure-delta-pipeline-control-room-design.md`

## Global Constraints

- Public demo data remains synthetic and must be labeled as synthetic.
- Real KONEPS integration scope remains service tender notices and observed changes only.
- Full five-stage procurement lifecycle remains a synthetic demonstration unless separate live evidence exists.
- Hosted LLM evaluation remains `not_run` until an actual hosted evaluation artifact is produced.
- CPU benchmark values must be labeled CPU-only and must not be presented as DB/queue/API/SaaS throughput.
- Presentation animation timing must never be reported as backend latency.
- Public static demo must not claim live KONEPS polling, live OCR, hosted LLM calls, Redis queue processing, or external notifications.
- No generic chatbot/RAG UI, autonomous purchasing agent, Kafka, Kubernetes, new vector database, or payment/subscription scope is added.
- No new database schema is introduced unless a task proves it is required; this plan requires none.
- All public metrics must originate from committed artifacts or the same measured verification run.
- Existing frontend/backend/release-contract gates must remain green.

## Review Focus

1. **Unknown or tampered scenario id** — API must return 404 and never interpret an arbitrary file path or run arbitrary code; Task 2 tests this.
2. **Scenario replay accidentally performs external I/O** — scenario construction must remain packaged-fixture/pure-function only; Task 1 tests that source URLs are descriptive values and no network client is invoked.
3. **Hard eligibility becomes visually overridden by ranking** — response and UI must preserve separate eligibility and relevance decisions; Tasks 1 and 5 test a high relevance score that still remains blocked after amendment.
4. **Missing measurement is rendered as zero/success** — absent hosted metrics and absent sanitized performance artifacts must render `미측정`/`미실행`; Tasks 4 and 7 test this.
5. **Replay UI breaks mobile/reduced-motion users** — no horizontal overflow at 390px, all stages keyboard-selectable, and autoplay disabled under reduced motion; Task 9 browser tests this.

---

## File Structure

### Backend

- `apps/api/app/demo/control_room.py` — pure scenario assembly using existing production functions and packaged fixtures.
- `apps/api/app/api/demo.py` — read-only scenario list/detail endpoints and public response models.
- `apps/api/app/api/performance.py` — sanitized read-only projection for committed performance/release artifacts.
- `apps/api/app/main.py` — include demo/performance routers.
- `apps/api/tests/demo/test_control_room.py` — production-function scenario behavior.
- `apps/api/tests/api/test_demo_pipeline.py` — API contracts, 404, provenance boundaries.
- `apps/api/tests/api/test_performance_projection.py` — measured/missing artifact handling.

### Frontend

- `apps/web/app/(product)/pipeline/page.tsx` — route composition and async state.
- `apps/web/components/pipeline/pipeline-control-room.tsx` — scenario switching and replay state machine.
- `apps/web/components/pipeline/pipeline-stage-map.tsx` — accessible stage map.
- `apps/web/components/pipeline/stage-inspector.tsx` — input/output/evidence/decision tabs.
- `apps/web/components/pipeline/evidence-panels.tsx` — scale/failure/release/evaluation summary.
- `apps/web/lib/api.ts` — pipeline/performance TypeScript contracts and API calls.
- `apps/web/lib/static-demo.ts` — static-demo parity payloads.
- `apps/web/components/app-shell.tsx` — add Pipeline nav.
- `apps/web/app/page.tsx` — landing CTA.
- `apps/web/app/(product)/about/page.tsx` — route-comparison evaluation table.
- `apps/web/components/admin/admin-console.tsx` — compact operator pipeline strip.
- `apps/web/app/styles.css`, `apps/web/app/mobile-fixes.css` — visual states/responsive/reduced-motion.
- `apps/web/tests/pipeline.test.ts` — pure replay helpers and static contract.
- `apps/web/tests/pipeline-contract.test.ts` — route/nav/label source contract.
- `apps/web/e2e/pipeline.mjs` — desktop/mobile reviewer path.

### Verification / Docs

- `scripts/verify_containers.py` — execute pipeline E2E and publish sanitized performance summaries.
- `artifacts/performance/queue.json`, `http.json`, `query-plans.json` — generated only from successful isolated verification.
- `docs/evaluation.md`, `docs/performance.md`, `docs/verification.md` — explain public projections and limits.
- `README.md` — updated only after the implementation and final screenshots are verified.

---

### Task 1: Build the Pure Control-Room Scenario Engine

**Files:**
- Create: `apps/api/app/demo/control_room.py`
- Test: `apps/api/tests/demo/test_control_room.py`

**Interfaces:**
- Consumes:
  - `demo_records(run_id: str, anchor: datetime, source_id: UUID) -> list[RawSourceRecord]`
  - `normalize_raw_record(...)`
  - `compute_delta(before: DeltaSnapshot, after: DeltaSnapshot) -> OpportunityDelta`
  - `evaluate_eligibility(...)`
  - `rank_opportunity(...)`
- Produces:
  - `ScenarioSummary`
  - `PipelineStage`
  - `PipelineScenario`
  - `list_scenarios() -> tuple[ScenarioSummary, ...]`
  - `build_scenario(scenario_id: str) -> PipelineScenario`

- [ ] **Step 1: Write the failing scenario-order test**

Create `apps/api/tests/demo/test_control_room.py` with:

```python
from app.demo.control_room import build_scenario, list_scenarios

EXPECTED_ORDER = [
    "collect",
    "dedupe",
    "normalize",
    "documents",
    "ocr-route",
    "extract",
    "validate",
    "lifecycle",
    "delta",
    "eligibility",
    "ranking",
    "notification",
]


def test_scenario_catalog_is_fixed_and_reviewer_facing() -> None:
    rows = list_scenarios()
    assert [row.id for row in rows] == [
        "new-opportunity",
        "amendment-eligibility-change",
        "failure-recovery",
    ]


def test_amendment_scenario_exposes_stable_pipeline_order() -> None:
    scenario = build_scenario("amendment-eligibility-change")
    assert scenario.synthetic is True
    assert scenario.source_scope == "packaged_fixture"
    assert [stage.id for stage in scenario.stages] == EXPECTED_ORDER
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
cd apps/api
pytest tests/demo/test_control_room.py -q
```

Expected: import failure for `app.demo.control_room`.

- [ ] **Step 3: Add the typed scenario models and fixed catalog**

Implement in `control_room.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

StageKind = Literal["system", "deterministic", "ocr", "llm", "notification"]
StageStatus = Literal["passed", "warning", "blocked", "not_run"]


@dataclass(frozen=True)
class ScenarioSummary:
    id: str
    title: str
    description: str


@dataclass(frozen=True)
class PipelineStage:
    id: str
    label: str
    kind: StageKind
    status: StageStatus
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[dict[str, Any], ...] = ()
    decision: dict[str, Any] = field(default_factory=dict)
    measured_duration_ms: float | None = None
    notice: str | None = None


@dataclass(frozen=True)
class PipelineScenario:
    scenario_id: str
    title: str
    description: str
    synthetic: bool
    source_scope: str
    stages: tuple[PipelineStage, ...]


CATALOG = (
    ScenarioSummary("new-opportunity", "신규 공고", "수집부터 추천·알림 판단까지"),
    ScenarioSummary(
        "amendment-eligibility-change",
        "정정으로 조건 변경",
        "버전 변경이 Delta와 참여 가능 여부에 미치는 영향",
    ),
    ScenarioSummary(
        "failure-recovery",
        "장애와 복구",
        "재시도·비재시도·종료 실패 경계를 확인",
    ),
)


def list_scenarios() -> tuple[ScenarioSummary, ...]:
    return CATALOG
```

Add a private `_base_stage_map()` that always yields the 12 ids in `EXPECTED_ORDER`.

- [ ] **Step 4: Add failing amendment decision-chain test**

Append:

```python
def test_amendment_scenario_keeps_delta_eligibility_and_ranking_separate() -> None:
    scenario = build_scenario("amendment-eligibility-change")
    stages = {stage.id: stage for stage in scenario.stages}

    assert stages["delta"].output["changed_fields"]
    assert stages["delta"].decision["impact"] == "high"
    assert "region_restriction" in " ".join(stages["delta"].decision["reason_codes"])

    assert stages["eligibility"].output["before"]["allows_recommendation"] is True
    assert stages["eligibility"].output["after"]["allows_recommendation"] is False
    assert "region_not_served" in stages["eligibility"].output["after"]["hard_failure_codes"]

    assert stages["ranking"].output["after"]["recommended"] is False
    assert stages["ranking"].decision["eligibility_overrides_rank"] is True
```

Run the targeted test; expect failure because `build_scenario` does not yet create decisions.

- [ ] **Step 5: Implement amendment scenario using production functions**

Use a fixed aware anchor, e.g. `datetime(2026, 9, 16, tzinfo=UTC)`, and `demo_records("control-room", anchor, UUID(int=1))`.

Create SQLAlchemy model instances in memory only for `RawRecord`, `OpportunityVersion`, and `Attachment` with deterministic UUIDs. Do not create a session and do not commit.

Normalize tender/amendment payloads with the production normalizer, then build two `DeltaSnapshot` objects and call `compute_delta`.

For the reviewer company profile use:

```python
EligibilityProfile(
    regions=("Seoul",),
    certifications=("ISO 27001",),
    min_contract_amount=Decimal("10000000"),
    max_contract_amount=Decimal("500000000"),
    contract_currency="KRW",
    excluded_keywords=(),
    industries=("services",),
    capabilities=("cloud migration", "document processing"),
)
```

For the amendment fixture, construct the **after** stage input so the production eligibility logic sees a Busan-only region restriction while title/capability relevance remains high. This deliberately demonstrates that hard eligibility blocks recommendation even when relevance remains high.

Call `evaluate_eligibility` before and after. Feed each result into `rank_opportunity` with an explicit aware `as_of`.

Populate:
- `delta.output.changed_fields` from `OpportunityDelta.field_changes_json`
- `delta.decision.reason_codes` from `impact_reasons_json["codes"]`
- eligibility before/after hard failures and warnings
- ranking before/after score and recommendation
- notification stage as a deterministic consequence of a watched material change, labeled as a **decision**, not an actual external delivery

- [ ] **Step 6: Add failure-scenario test before implementation**

Append:

```python
def test_failure_scenario_exposes_verified_retry_classification_without_network_io() -> None:
    scenario = build_scenario("failure-recovery")
    failure = {stage.id: stage for stage in scenario.stages}["collect"]
    cases = failure.output["transport_cases"]

    assert [(row["name"], row["attempts"], row["succeeded"]) for row in cases] == [
        ("timeout-recovery", 3, True),
        ("rate-limit-recovery", 2, True),
        ("server-error-terminal", 3, False),
        ("forbidden-not-retried", 1, False),
    ]
    assert failure.notice == "합성 HTTP transport 주입 결과"
```

Run it and verify failure until the failure scenario is implemented.

- [ ] **Step 7: Implement the failure scenario from the committed failure artifact semantics**

The scenario must be a static projection of the verified classifications already represented by `artifacts/failures/http.json`; it must not make HTTP requests. Keep all other stages `not_run` or explanatory `blocked` as appropriate so the UI does not pretend a failed collection continued through the pipeline.

- [ ] **Step 8: Add new-opportunity scenario**

Use the tender fixture and production normalization + eligibility + ranking functions. Delta is `not_run` with notice `최초 관측 버전에는 비교 대상이 없습니다.`.

The OCR route stage must say `not_run` for the HTML fixture and explain that native parsing is sufficient; do not claim OCR executed.

The extraction stage may use the deterministic/demo extractor contract but must label `kind="deterministic"`, not `llm`.

- [ ] **Step 9: Add no-network invariant test**

Monkeypatch common network constructors used by the app to raise if called:

```python
def test_control_room_scenarios_do_not_require_external_network(monkeypatch) -> None:
    import httpx

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network forbidden")),
    )
    for row in list_scenarios():
        build_scenario(row.id)
```

If import-time code makes this patch inappropriate, patch the ProcureDelta `ResilientHttpClient.request` method instead. The test must fail if scenario assembly attempts external I/O.

- [ ] **Step 10: Run the full task test**

```bash
cd apps/api
pytest tests/demo/test_control_room.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add apps/api/app/demo/control_room.py apps/api/tests/demo/test_control_room.py
git commit -m "feat: add deterministic pipeline control room scenarios"
```

---

### Task 2: Expose Read-Only Pipeline Scenario APIs

**Files:**
- Create: `apps/api/app/api/demo.py`
- Modify: `apps/api/app/main.py`
- Test: `apps/api/tests/api/test_demo_pipeline.py`

**Interfaces:**
- Consumes: `list_scenarios()`, `build_scenario(scenario_id)`
- Produces:
  - `GET /api/v1/demo/pipeline/scenarios`
  - `GET /api/v1/demo/pipeline/scenarios/{scenario_id}`

- [ ] **Step 1: Write failing API contract tests**

Create:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_pipeline_scenario_list_is_public_read_only() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/demo/pipeline/scenarios")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [
        "new-opportunity",
        "amendment-eligibility-change",
        "failure-recovery",
    ]


@pytest.mark.asyncio
async def test_unknown_pipeline_scenario_returns_404_without_path_interpretation() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/demo/pipeline/scenarios/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_pipeline_scenario_always_exposes_honesty_boundary() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/demo/pipeline/scenarios/amendment-eligibility-change"
        )
    body = response.json()
    assert body["synthetic"] is True
    assert body["source_scope"] == "packaged_fixture"
    assert all("measured_duration_ms" in stage for stage in body["stages"])
```

- [ ] **Step 2: Verify RED**

Run:

```bash
cd apps/api
pytest tests/api/test_demo_pipeline.py -q
```

Expected: 404 for all routes because router does not exist.

- [ ] **Step 3: Implement strict public DTOs and router**

In `apps/api/app/api/demo.py`, define Pydantic DTOs with `extra="forbid"`:

```python
class ScenarioSummaryDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    description: str


class PipelineStageDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    kind: Literal["system", "deterministic", "ocr", "llm", "notification"]
    status: Literal["passed", "warning", "blocked", "not_run"]
    input: dict[str, Any]
    output: dict[str, Any]
    evidence: list[dict[str, Any]]
    decision: dict[str, Any]
    measured_duration_ms: float | None
    notice: str | None


class PipelineScenarioDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    title: str
    description: str
    synthetic: Literal[True]
    source_scope: Literal["packaged_fixture", "committed_verification_artifact"]
    stages: list[PipelineStageDTO]
```

Map dataclasses with `asdict`.

For detail:

```python
try:
    scenario = build_scenario(scenario_id)
except KeyError as exc:
    raise HTTPException(status_code=404, detail="Unknown pipeline scenario") from exc
```

Do not inspect filesystem paths from `scenario_id`.

- [ ] **Step 4: Include router in `main.py`**

Import `demo` and include `demo.router` in the existing router tuple.

- [ ] **Step 5: Run targeted tests**

```bash
cd apps/api
pytest tests/api/test_demo_pipeline.py tests/demo/test_control_room.py -q
```

Expected: PASS.

- [ ] **Step 6: Run backend lint/types for changed code**

```bash
cd apps/api
ruff check app/demo/control_room.py app/api/demo.py tests/demo/test_control_room.py tests/api/test_demo_pipeline.py
mypy app
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/api/demo.py apps/api/app/main.py apps/api/tests/api/test_demo_pipeline.py
git commit -m "feat: expose pipeline replay API"
```

---

### Task 3: Add Static-Demo Parity and TypeScript Contracts

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/lib/static-demo.ts`
- Create: `apps/web/tests/pipeline.test.ts`

**Interfaces:**
- Consumes backend JSON contract from Task 2.
- Produces TypeScript:
  - `PipelineStage`
  - `PipelineScenarioSummary`
  - `PipelineScenario`
  - `getPipelineScenarios()`
  - `getPipelineScenario(id: string)`

- [ ] **Step 1: Write failing static-demo parity test**

Create `apps/web/tests/pipeline.test.ts`:

```typescript
import assert from "node:assert/strict";
import test from "node:test";

import {
  staticPipelineScenario,
  staticPipelineScenarios,
} from "../lib/static-demo.ts";

test("static control-room catalog matches the backend public ids", () => {
  assert.deepEqual(
    staticPipelineScenarios().map((row) => row.id),
    ["new-opportunity", "amendment-eligibility-change", "failure-recovery"],
  );
});

test("static amendment replay preserves hard eligibility boundary", () => {
  const scenario = staticPipelineScenario("amendment-eligibility-change");
  const stages = new Map(scenario.stages.map((stage) => [stage.id, stage]));
  assert.equal(stages.get("eligibility")?.output.after.allows_recommendation, false);
  assert.equal(stages.get("ranking")?.decision.eligibility_overrides_rank, true);
});

test("unknown static scenario ids fail closed", () => {
  assert.throws(() => staticPipelineScenario("../../secret"));
});
```

- [ ] **Step 2: Run and verify RED**

```bash
cd apps/web
npm test
```

Expected: missing exports.

- [ ] **Step 3: Add TypeScript contracts in `api.ts`**

Define:

```typescript
export type PipelineStageKind =
  | "system"
  | "deterministic"
  | "ocr"
  | "llm"
  | "notification";

export type PipelineStageStatus =
  | "passed"
  | "warning"
  | "blocked"
  | "not_run";

export type PipelineStage = {
  id: string;
  label: string;
  kind: PipelineStageKind;
  status: PipelineStageStatus;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  evidence: Array<Record<string, unknown>>;
  decision: Record<string, unknown>;
  measured_duration_ms: number | null;
  notice: string | null;
};

export type PipelineScenarioSummary = {
  id: string;
  title: string;
  description: string;
};

export type PipelineScenario = {
  scenario_id: string;
  title: string;
  description: string;
  synthetic: true;
  source_scope: "packaged_fixture" | "committed_verification_artifact";
  stages: PipelineStage[];
};
```

Add API functions following the existing `request` / static-mode pattern already used in `api.ts`.

- [ ] **Step 4: Implement static fixtures without inventing metrics**

In `static-demo.ts`, export:
- `staticPipelineScenarios()`
- `staticPipelineScenario(id)`

Mirror the backend stage ids and truth labels. Use the same synthetic amendment narrative but keep `measured_duration_ms: null` for scenario stages.

For failure recovery, use exactly the committed cases:
- timeout 3 attempts succeeded
- 429 2 attempts succeeded
- 500 3 attempts terminal
- 403 1 attempt not retried

No random values and no `Date.now()` generated metrics.

- [ ] **Step 5: Wire `getPipelineScenarios` and `getPipelineScenario`**

When `NEXT_PUBLIC_STATIC_DEMO=true`, return the static functions; otherwise call the Task 2 endpoints.

- [ ] **Step 6: Run unit/type tests**

```bash
cd apps/web
npm test
npm run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/web/lib/api.ts apps/web/lib/static-demo.ts apps/web/tests/pipeline.test.ts
git commit -m "feat: add pipeline demo client contracts"
```

---

### Task 4: Build the Pipeline Page and Replay State Machine

**Files:**
- Create: `apps/web/app/(product)/pipeline/page.tsx`
- Create: `apps/web/components/pipeline/pipeline-control-room.tsx`
- Create: `apps/web/components/pipeline/pipeline-stage-map.tsx`
- Create: `apps/web/components/pipeline/stage-inspector.tsx`
- Create: `apps/web/tests/pipeline-contract.test.ts`

**Interfaces:**
- Consumes `getPipelineScenarios()` and `getPipelineScenario(id)`.
- Produces reviewer-facing replay UI at `/pipeline`.

- [ ] **Step 1: Add failing source-contract test**

Create `pipeline-contract.test.ts`:

```typescript
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(
  new URL("../app/(product)/pipeline/page.tsx", import.meta.url),
  "utf8",
);

test("pipeline page has reviewer-first controls and honesty copy", () => {
  assert.match(page, /파이프라인을 직접 재생해보세요/);
  assert.match(page, /합성 시나리오/);
  assert.match(page, /재생/);
  assert.match(page, /초기화/);
});
```

Run `npm test`; expect file-not-found or assertion failure.

- [ ] **Step 2: Create route page**

The page fetches scenario summaries through client-side state and renders `PipelineControlRoom`.

Use error/loading states consistent with the existing product pages; do not render stale fallback data when fetch fails.

- [ ] **Step 3: Add a pure replay helper before the component implementation**

In `pipeline-control-room.tsx`, export a testable helper:

```typescript
export function nextReplayIndex(current: number, length: number): number {
  if (length <= 0) return -1;
  return Math.min(current + 1, length - 1);
}
```

Add unit tests in `pipeline.test.ts` for start, end clamp, and empty stages.

- [ ] **Step 4: Implement component state**

Required state:
- active scenario id
- loaded scenario
- selected stage id
- replay index
- `playing` boolean

Controls:
- `재생`
- `일시정지`
- `초기화`

Use an interval only for presentation. Never display interval duration as latency.

When `prefers-reduced-motion: reduce` matches, the Play button advances one stage per click instead of auto-running.

- [ ] **Step 5: Implement `PipelineStageMap`**

Render all stages as actual `button` elements with:
- `aria-pressed={selected}`
- text kind/status badge
- completed/current/future state based on replay index
- no status communicated only by color

- [ ] **Step 6: Implement `StageInspector`**

Tabs:
- 입력
- 출력
- 근거
- 판단

Use a safe JSON renderer or the existing `JsonView` component. When arrays/objects are empty, render `표시할 값이 없습니다.`.

Show:
- `측정 지연: 미측정` when `measured_duration_ms === null`
- stage notice visibly

Do not render HTML from payloads.

- [ ] **Step 7: Run frontend unit/type/lint**

```bash
cd apps/web
npm test
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/web/app/'(product)'/pipeline/page.tsx apps/web/components/pipeline apps/web/tests/pipeline-contract.test.ts apps/web/tests/pipeline.test.ts
git commit -m "feat: add pipeline replay experience"
```

---

### Task 5: Make the Amendment Story Visually Unmissable

**Files:**
- Modify: `apps/web/components/pipeline/stage-inspector.tsx`
- Create: `apps/web/components/pipeline/amendment-impact.tsx`
- Test: `apps/web/tests/pipeline.test.ts`

**Interfaces:**
- Consumes the Task 1 amendment stage output.
- Produces a reviewer-readable before/after chain.

- [ ] **Step 1: Add failing formatter tests**

In `pipeline.test.ts`:

```typescript
import { decisionHeadline } from "../components/pipeline/amendment-impact.tsx";

test("eligibility decision headline does not call a blocked item recommended", () => {
  assert.equal(
    decisionHeadline({
      allows_recommendation: false,
      hard_failure_codes: ["region_not_served"],
      score: 0.88,
      recommended: false,
    }),
    "참여 불가 · 관련도와 별개",
  );
});
```

- [ ] **Step 2: Implement `AmendmentImpact`**

For Delta:
- list each changed field
- show before → after
- show impact level
- show deterministic reason codes

For eligibility:
- two columns: 이전 판단 / 변경 후 판단
- hard failures above relevance score
- visible note: `필수 조건 불일치는 관련도 점수로 뒤집지 않습니다.`

For ranking:
- score may remain high
- recommendation state remains false when blocked

For notification:
- show `watched material change → notification decision`
- label public demo delivery as `로컬/합성 판단`, never an external send

- [ ] **Step 3: Integrate into inspector**

When selected stage id is `delta`, `eligibility`, `ranking`, or `notification`, show `AmendmentImpact` above raw JSON tabs.

- [ ] **Step 4: Run tests**

```bash
cd apps/web
npm test
npm run typecheck
npm run lint
```

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/pipeline/amendment-impact.tsx apps/web/components/pipeline/stage-inspector.tsx apps/web/tests/pipeline.test.ts
git commit -m "feat: explain amendment impact chain"
```

---

### Task 6: Expose Sanitized Scale, Failure, and Release Evidence

**Files:**
- Create: `apps/api/app/api/performance.py`
- Modify: `apps/api/app/main.py`
- Test: `apps/api/tests/api/test_performance_projection.py`

**Interfaces:**
- Produces `GET /api/v1/evaluation/engineering-evidence`.

Response:
- CPU benchmark summary
- failure-drill cases
- release gate statuses
- optional queue/http/query summaries when public artifacts exist
- explicit scope/limitation strings

- [ ] **Step 1: Write failing projection test**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_engineering_evidence_exposes_measured_values_and_scope() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/evaluation/engineering-evidence")
    assert response.status_code == 200
    body = response.json()

    assert body["cpu"]["synthetic"] is True
    assert body["cpu"]["normalized_records"] == 50000
    assert body["cpu"]["delta_pairs"] == 5000
    assert body["cpu"]["scope"] == "cpu_only_production_functions"

    assert body["failure_drill"]["scope"] == "http_transport_injection"
    assert body["release"]["passed"] is True
    assert body["release"]["readiness"] == "ready"
```

- [ ] **Step 2: Add missing-artifact test**

Use monkeypatch to redirect artifact root to a temporary directory containing only the core committed artifacts or none.

Expected public behavior:
- core file missing → field `status="not_run"`
- no invented zero
- endpoint itself remains 200 if optional artifacts are missing

- [ ] **Step 3: Implement a strict allowlisted reader**

In `performance.py`, resolve only fixed filenames relative to repository/app paths. Never accept a filename/path query parameter.

Define Pydantic response models. Parse only fields needed by UI.

Core fixed files:
- `artifacts/performance/cpu.json`
- `artifacts/failures/http.json`
- `artifacts/verification/release-gate.json`

Optional fixed files:
- `artifacts/performance/queue.json`
- `artifacts/performance/http.json`
- `artifacts/performance/query-plans.json`

If optional files are absent, return `{"status": "not_run"}`.

- [ ] **Step 4: Include router and run tests**

```bash
cd apps/api
pytest tests/api/test_performance_projection.py -q
ruff check app/api/performance.py tests/api/test_performance_projection.py
mypy app
```

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/api/performance.py apps/api/app/main.py apps/api/tests/api/test_performance_projection.py
git commit -m "feat: expose sanitized engineering evidence"
```

---

### Task 7: Add Engineering Evidence and Honest LLM/OCR Comparison to the UI

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/lib/static-demo.ts`
- Create: `apps/web/components/pipeline/evidence-panels.tsx`
- Modify: `apps/web/app/(product)/pipeline/page.tsx`
- Modify: `apps/web/app/(product)/about/page.tsx`
- Test: `apps/web/tests/pipeline.test.ts`

**Interfaces:**
- Consumes Task 6 engineering-evidence endpoint and existing evaluation summary.
- Produces scale/failure/release cards and route comparison table.

- [ ] **Step 1: Add failing missing-hosted metric test**

```typescript
import { displayMetric } from "../components/pipeline/evidence-panels.tsx";

test("missing hosted metrics render as unmeasured instead of zero", () => {
  assert.equal(displayMetric(null), "미측정");
  assert.equal(displayMetric(undefined), "미측정");
});
```

- [ ] **Step 2: Add EngineeringEvidence types and API/static methods**

In `api.ts`, type:
- `cpu`
- `failure_drill`
- `release`
- optional `queue`, `http`, `query_plans`

Static demo must use exactly the committed CPU/failure/release values and mark optional absent summaries `not_run`.

- [ ] **Step 3: Build `EvidencePanels`**

Cards:

**Scale**
- 50,000 normalized
- 50,000 ranked
- 5,000 delta pairs
- 7,148 records/s
- visible label: `CPU-only production-function benchmark`

**Failure**
- 4 verified synthetic transport cases with attempt counts

**Release**
- DB+Redis
- backend integration
- readiness
- lifecycle E2E
- queue scale
- query plans
- HTTP load

Only show pass/duration fields actually in release artifact.

**Optional service measurements**
- if `status=not_run`, display `미측정` and no chart.

- [ ] **Step 4: Extend evaluation page with route comparison**

Use existing evaluation summary plus types needed from the committed evaluation projection.

Rows:
- deterministic extraction
- hosted all
- hosted gated
- OCR

Current hosted rows must display `미실행`.

Do not fill prompt token/cost values when null.

Add caveat card:
- synthetic regression set
- real public records: 0
- OCR: English synthetic images
- hosted LLM: not run
- hashes remain visible under details

- [ ] **Step 5: Run tests/type/lint**

```bash
cd apps/web
npm test
npm run typecheck
npm run lint
```

- [ ] **Step 6: Commit**

```bash
git add apps/web/lib/api.ts apps/web/lib/static-demo.ts apps/web/components/pipeline/evidence-panels.tsx apps/web/app/'(product)'/pipeline/page.tsx apps/web/app/'(product)'/about/page.tsx apps/web/tests/pipeline.test.ts
git commit -m "feat: surface verified scale and evaluation evidence"
```

---

### Task 8: Integrate Pipeline Story into Landing, Navigation, and Admin

**Files:**
- Modify: `apps/web/components/app-shell.tsx`
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/components/admin/admin-console.tsx`
- Modify: `apps/web/app/styles.css`
- Test: `apps/web/tests/pipeline-contract.test.ts`

**Interfaces:**
- Produces navigation/landing entry points and compact operator pipeline strip.

- [ ] **Step 1: Extend source-contract test**

Add:

```typescript
const shell = readFileSync(new URL("../components/app-shell.tsx", import.meta.url), "utf8");
const landing = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const admin = readFileSync(
  new URL("../components/admin/admin-console.tsx", import.meta.url),
  "utf8",
);

test("pipeline differentiator is visible from landing and product nav", () => {
  assert.match(shell, /\/pipeline/);
  assert.match(shell, /파이프라인/);
  assert.match(landing, /파이프라인 데모 보기/);
});

test("admin keeps operator pipeline overview separate from reviewer replay", () => {
  assert.match(admin, /collect/);
  assert.match(admin, /notify/);
  assert.doesNotMatch(admin, /파이프라인을 직접 재생해보세요/);
});
```

Run and verify failure.

- [ ] **Step 2: Add Product nav item**

Order:

```typescript
[
  ["/inbox", "공고함"],
  ["/pipeline", "파이프라인"],
  ["/watchlist", "관심 공고"],
  ["/notifications", "알림"],
  ["/profile", "기업 프로필"],
  ["/about", "평가·한계"],
]
```

- [ ] **Step 3: Add landing CTA**

Add secondary/tertiary CTA `파이프라인 데모 보기` to `/pipeline`.

Keep `맞는 공고만, 끝까지.` unchanged.

Add a compact stage strip in the hero preview:
`수집 → 문서 → 추출 → Delta → 판단`.

- [ ] **Step 4: Add compact Admin pipeline strip**

Above KPI cards, render fixed stage labels:
`collect → parse → extract → delta → eligibility → rank → notify`.

Use current pipeline data only for broad health/status, not invented per-stage throughput.

If metrics are unavailable, label the strip `현재 지표 미확인` rather than showing green.

- [ ] **Step 5: Add structured CSS**

Use existing green/ivory/orange design language.

Required class groups:
- `.pipeline-hero`
- `.scenario-switcher`
- `.pipeline-stage-map`
- `.pipeline-stage`
- `.stage-inspector`
- `.evidence-grid`
- `.operator-pipeline-strip`

LLM badge color may use indigo only when a stage kind is actually `llm`.

- [ ] **Step 6: Run unit/type/lint/build**

```bash
cd apps/web
npm test
npm run typecheck
npm run lint
npm run build
```

- [ ] **Step 7: Commit**

```bash
git add apps/web/components/app-shell.tsx apps/web/app/page.tsx apps/web/components/admin/admin-console.tsx apps/web/app/styles.css apps/web/tests/pipeline-contract.test.ts
git commit -m "feat: make pipeline demo a primary product entry"
```

---

### Task 9: Accessibility, Mobile, and Browser Reviewer Flow

**Files:**
- Modify: `apps/web/app/mobile-fixes.css`
- Create: `apps/web/e2e/pipeline.mjs`
- Modify: `apps/web/tests/product.browser.mjs` only if shared navigation assumptions require it

**Interfaces:**
- Validates the 60-second reviewer path in both static/live product modes.

- [ ] **Step 1: Write desktop pipeline E2E**

`pipeline.mjs` should:

1. open `/pipeline`
2. assert heading `파이프라인을 직접 재생해보세요`
3. choose `정정으로 조건 변경`
4. click `재생`
5. wait until Delta is reached
6. click Delta stage
7. assert before/after values and `high`
8. click Eligibility stage
9. assert `참여 불가 · 관련도와 별개`
10. choose `장애와 복구`
11. assert timeout/429/500/403 rows
12. navigate to `평가·한계`
13. assert hosted LLM `미실행`
14. assert `pageerror` list is empty

Use robust role/text selectors, not fragile nth-child selectors.

- [ ] **Step 2: Add 390px mobile E2E**

Create a second context with `viewport: { width: 390, height: 844 }`.

Assert:

```javascript
assert.equal(
  await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
  false,
);
```

Select stage buttons using roles and verify inspector remains visible.

- [ ] **Step 3: Add reduced-motion E2E**

Emulate reduced motion:

```javascript
const context = await browser.newContext({
  reducedMotion: "reduce",
  viewport: { width: 1280, height: 800 },
});
```

Click `재생` once and assert only one stage advances automatically; there must be no ongoing interval-based autoplay.

- [ ] **Step 4: Add mobile/reduced-motion CSS**

In `mobile-fixes.css`:
- convert stage map to vertical rail under 800px
- ensure inspector `min-width: 0`
- wrap long evidence hashes/JSON
- no fixed widths > viewport
- add `@media (prefers-reduced-motion: reduce)` disabling transition/animation for pipeline elements

- [ ] **Step 5: Run browser test against local app**

Start static demo locally:

```bash
cd apps/web
NEXT_PUBLIC_STATIC_DEMO=true npm run build
NEXT_PUBLIC_STATIC_DEMO=true npm start -- -p 3000
```

In a second shell:

```bash
cd apps/web
node e2e/pipeline.mjs
```

Expected: desktop/mobile/reduced-motion gates pass.

- [ ] **Step 6: Commit**

```bash
git add apps/web/app/mobile-fixes.css apps/web/e2e/pipeline.mjs
git commit -m "test: verify pipeline reviewer flow and accessibility"
```

---

### Task 10: Publish Sanitized Verification Evidence and Add Pipeline E2E to Release Gate

**Files:**
- Modify: `scripts/verify_containers.py`
- Modify: `.github/workflows/ci.yml` only if artifact paths change
- Create/update generated:
  - `artifacts/performance/queue.json`
  - `artifacts/performance/http.json`
  - `artifacts/performance/query-plans.json`
- Modify: `docs/performance.md`
- Modify: `docs/verification.md`
- Modify: `docs/evaluation.md`

**Interfaces:**
- Turns existing isolated benchmark outputs into committed sanitized summaries only after successful verification.
- Adds `pipeline-demo-e2e` gate.

- [ ] **Step 1: Add a failing verification-contract test or source assertion**

Add a small source contract test under `apps/api/contract_tests/test_release_delivery.py` asserting `scripts/verify_containers.py` contains:
- `pipeline-demo-e2e`
- public summary destinations under `artifacts/performance/`

Do not assert exact timing values.

- [ ] **Step 2: Modify verification runner**

After `real-lifecycle-e2e`, run:

```python
execute('pipeline-demo-e2e', ['node', 'e2e/pipeline.mjs'], ROOT / 'apps/web')
```

After queue/query/http gates pass, copy sanitized JSON from:
- `artifacts/container/queue-load.json`
- `artifacts/container/http-load.json`
- `artifacts/container/query-plans.json`

to public artifact paths only after validation.

Validation requirements:
- parsed JSON object
- explicit `synthetic` or verification scope
- no key names matching `secret|password|cookie|authorization|token` case-insensitively
- no URL containing credentials
- output size bounded to a small summary; strip raw rows/request payloads

Implement a helper `publish_public_summary(source: Path, destination: Path, allowed_keys: set[str])` so only explicit fields are copied.

- [ ] **Step 3: Run isolated verification**

```bash
python scripts/verify_containers.py --scale-records 1000
```

Expected gates:
- existing gates pass
- `pipeline-demo-e2e` pass
- generated performance summaries exist

- [ ] **Step 4: Inspect generated summaries before committing**

Verify:
- queue summary is clearly synthetic/isolated
- HTTP summary includes actual measured fields from the run
- query plan summary includes measured plans only
- no secrets/raw request bodies

If a script does not produce a safe useful metric, keep that public artifact absent and the UI will show `미측정`. Do not invent a substitute.

- [ ] **Step 5: Update docs to match actual generated artifacts**

`docs/performance.md` must state exact measured scope from the new files.

`docs/verification.md` must list `pipeline-demo-e2e`.

`docs/evaluation.md` must explicitly distinguish pipeline replay from hosted LLM evaluation.

- [ ] **Step 6: Run full repository verification**

Backend:

```bash
cd apps/api
ruff check .
mypy app
pytest
python -m unittest discover -s contract_tests -v
```

Frontend:

```bash
cd apps/web
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

Root:

```bash
python scripts/verify_containers.py --scale-records 1000
```

All must pass before merge.

- [ ] **Step 7: Commit**

```bash
git add scripts/verify_containers.py .github/workflows/ci.yml artifacts/performance docs
git commit -m "test: verify pipeline demo and publish sanitized evidence"
```

---

### Task 11: Final Visual Capture, README, and Portfolio Story Update

**Files:**
- Modify: `README.md`
- Replace/update: `docs/images/landing.png`
- Create: `docs/images/pipeline-control-room.png`
- Create: `docs/images/pipeline-amendment.png`
- Update other screenshots only if their UI changed materially.

**Interfaces:**
- Uses only the already verified implementation.
- No product behavior changes are allowed in this task.

- [ ] **Step 1: Capture verified screenshots**

From the verified app:
- landing with Pipeline CTA
- pipeline amendment scenario at Delta/eligibility transition
- Admin compact pipeline strip if visually useful

No mockup/image-gen screenshot may be substituted for the actual product screenshot.

- [ ] **Step 2: Update README project narrative**

The first technical section should show this flow:

`collect → normalize → document/OCR → structured extraction → validation → lifecycle → Delta → eligibility → ranking → notify`

Lead with Pipeline Control Room before implementation details.

Include:
- public demo URL
- screenshot
- measured evidence
- explicit limitations

Do not claim hosted LLM comparison as measured.

- [ ] **Step 3: Add a 60-second reviewer path**

README section:

```markdown
## 60초 데모
1. 파이프라인 → 정정으로 조건 변경
2. 재생
3. Delta에서 before/after + reason code 확인
4. Eligibility에서 필수 조건 실패 확인
5. Scale/Failure에서 측정 범위 확인
6. 평가·한계에서 synthetic/not-run 범위 확인
```

- [ ] **Step 4: Verify README source contract**

Search for prohibited overclaims:
- `실시간 KONEPS`
- `한국어 OCR 정확도`
- `hosted LLM 정확도`
- production/customer traffic claims

Any such phrase must be removed or explicitly bounded.

- [ ] **Step 5: Final commit**

```bash
git add README.md docs/images
git commit -m "docs: present pipeline control room reviewer path"
```

---

## Final Self-Review

### Spec coverage

- Reviewer-first `/pipeline`: Tasks 3–5.
- Three scenarios: Tasks 1–5.
- Production-function reuse and no DB mutation: Task 1.
- Static demo parity: Task 3.
- Honest scale/failure evidence: Tasks 6–7 and 10.
- LLM/OCR comparison and missing metrics: Task 7.
- Admin/landing integration: Task 8.
- Accessibility/mobile/reduced-motion: Task 9.
- Existing release gate plus pipeline E2E: Task 10.
- README/screenshots only after verification: Task 11.
- No chatbot/new DB/Kafka/etc.: enforced by Global Constraints and no task introduces them.

### Placeholder scan

The plan contains no `TBD`, no unspecified "add tests", and no implementation step depends on an undefined later interface.

### Type consistency

- Backend scenario ids and TypeScript static ids are identical.
- Stage ids are fixed in Task 1 and consumed by Tasks 3–9.
- `measured_duration_ms` remains nullable end-to-end.
- Hard eligibility output is separate from ranking output throughout.
- Optional engineering artifacts use `status="not_run"` rather than null-as-zero.

### Review-focus coverage

- Unknown scenario id: Task 2.
- External I/O: Task 1.
- Eligibility vs ranking: Tasks 1 and 5.
- Missing measurement: Tasks 6 and 7.
- Mobile/reduced motion: Task 9.
