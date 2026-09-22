import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(
  new URL("../app/(product)/pipeline/page.tsx", import.meta.url),
  "utf8",
);
const control = readFileSync(
  new URL("../components/pipeline/pipeline-control-room.tsx", import.meta.url),
  "utf8",
);

test("pipeline page has reviewer-first controls and honesty copy", () => {
  const source = page + control;
  assert.match(source, /파이프라인을 직접 재생해보세요/);
  assert.match(source, /합성 시나리오/);
  assert.match(source, /재생/);
  assert.match(source, /초기화/);
});

const inspector = readFileSync(
  new URL("../components/pipeline/stage-inspector.tsx", import.meta.url),
  "utf8",
);

test("stage inspector keeps raw JSON available but collapsed behind reviewer-first copy", () => {
  assert.match(inspector, /기술 세부 JSON 보기/);
  assert.match(inspector, /입력 · 출력 · 근거 · 판단 원문/);
  assert.match(inspector, /<details className="pipeline-technical-details">/);
});

const shell = readFileSync(
  new URL("../components/app-shell.tsx", import.meta.url),
  "utf8",
);
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


const about = readFileSync(
  new URL("../app/(product)/about/page.tsx", import.meta.url),
  "utf8",
);

test("evaluation page compares deterministic hosted and OCR routes honestly", () => {
  assert.match(about, /추출 경로 비교/);
  assert.match(about, /hosted all/);
  assert.match(about, /hosted gated/);
  assert.match(about, /OCR/);
  assert.match(about, /미실행/);
});


const mobile = readFileSync(
  new URL("../app/mobile-fixes.css", import.meta.url),
  "utf8",
);

test("pipeline mobile styles include vertical rail and reduced motion safeguards", () => {
  assert.match(mobile, /\.pipeline-stage-map/);
  assert.match(mobile, /prefers-reduced-motion:\s*reduce/);
  assert.match(mobile, /\.stage-inspector/);
});


const pipelineE2E = readFileSync(
  new URL("../e2e/pipeline.mjs", import.meta.url),
  "utf8",
);

test("pipeline E2E uses the shared stage selector helper in every viewport", () => {
  assert.doesNotMatch(pipelineE2E, /mobileView\.stageButton|reducedView\.stageButton/);
  assert.match(pipelineE2E, /stageButton\(mobileView\.page, "delta"\)/);
  assert.match(pipelineE2E, /stageButton\(reducedView\.page, "delta"\)/);
});


const evidencePanels = readFileSync(
  new URL("../components/pipeline/evidence-panels.tsx", import.meta.url),
  "utf8",
);

test("engineering evidence cards surface measured queue HTTP and query-plan scope", () => {
  assert.match(evidencePanels, /Redis · ARQ · PostgreSQL/);
  assert.match(evidencePanels, /HTTP 부하/);
  assert.match(evidencePanels, /후보 인덱스는 채택하지 않음/);
  assert.match(evidencePanels, /p95/);
});


const styles = readFileSync(new URL("../app/styles.css", import.meta.url), "utf8");

test("measured service evidence has dedicated compact list styling", () => {
  assert.match(styles, /\.http-endpoint-list/);
  assert.match(styles, /\.query-evidence/);
});
