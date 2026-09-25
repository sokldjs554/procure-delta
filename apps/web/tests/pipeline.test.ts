import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  decisionHeadline,
  displayMetric,
  nextReplayIndex,
  stageOutputLayout,
  stageSummary,
} from "../lib/pipeline.ts";
import type { EngineeringEvidence } from "../lib/api.ts";
import type { PipelineStage } from "../lib/api.ts";
import {
  staticDemoRequest,
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

  assert.equal(
    (
      stages.get("eligibility")?.output.after as {
        allows_recommendation: boolean;
      }
    ).allows_recommendation,
    false,
  );
  assert.equal(
    stages.get("ranking")?.decision.eligibility_overrides_rank,
    true,
  );
});

test("unknown static scenario ids fail closed", () => {
  assert.throws(() => staticPipelineScenario("../../secret"));
});

test("replay helper advances once and clamps at the final stage", () => {
  assert.equal(nextReplayIndex(-1, 3), 0);
  assert.equal(nextReplayIndex(0, 3), 1);
  assert.equal(nextReplayIndex(2, 3), 2);
  assert.equal(nextReplayIndex(0, 0), -1);
});

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

test("unknown eligibility is never presented as an allowed decision", () => {
  assert.equal(decisionHeadline({}), "판단 정보 없음");
  assert.equal(decisionHeadline({ allows_recommendation: true }), "참여 가능");
});

test("new opportunity has single decisions while an amendment has comparisons", () => {
  const newStages = new Map(
    staticPipelineScenario("new-opportunity").stages.map((stage) => [
      stage.id,
      stage,
    ]),
  );
  const amendedStages = new Map(
    staticPipelineScenario("amendment-eligibility-change").stages.map(
      (stage) => [stage.id, stage],
    ),
  );
  for (const id of ["eligibility", "ranking"]) {
    assert.equal(stageOutputLayout(newStages.get(id)!), "single");
    assert.equal(stageOutputLayout(amendedStages.get(id)!), "comparison");
  }
  assert.equal(
    stageSummary(newStages.get("eligibility")!).result,
    "참여 가능 · 필수 조건 불일치 없음",
  );
  assert.equal(
    stageSummary(newStages.get("ranking")!).result,
    "관련도 0.88 · 추천 가능",
  );
});

test("blocked or unrun stages never invent outcome, score, or change", () => {
  const blocked = staticPipelineScenario("failure-recovery").stages;
  for (const stage of blocked.slice(1)) {
    const summary = stageSummary(stage);
    assert.equal(stageOutputLayout(stage), "unavailable");
    assert.match(summary.result, /실행하지 않/);
    assert.doesNotMatch(summary.result, /참여 가능|추천 가능|관련도 0/);
  }
  const unrun = staticPipelineScenario("new-opportunity").stages.find(
    (stage) => stage.id === "delta",
  )!;
  assert.equal(stageOutputLayout(unrun), "unavailable");
  assert.equal(
    stageSummary(unrun).result,
    "최초 관측 버전에는 비교 대상이 없습니다.",
  );
});

test("missing or incomplete eligibility does not imply approval", () => {
  const stage = staticPipelineScenario("new-opportunity").stages.find(
    (item) => item.id === "eligibility",
  )!;
  const incomplete: PipelineStage = { ...stage, output: { eligible: true } };
  assert.equal(stageOutputLayout(incomplete), "unavailable");
  assert.equal(
    stageSummary(incomplete).result,
    "참여 가능 여부를 판단할 정보가 없습니다.",
  );
});

test("every stage offers a Korean explanation and an honest observed result", () => {
  for (const id of [
    "new-opportunity",
    "amendment-eligibility-change",
    "failure-recovery",
  ]) {
    for (const stage of staticPipelineScenario(id).stages) {
      const summary = stageSummary(stage);
      assert.ok(summary.description.length > 12, `${id}/${stage.id} 설명`);
      assert.ok(summary.result.length > 8, `${id}/${stage.id} 결과`);
      assert.doesNotMatch(summary.result, /undefined|NaN/);
    }
  }
});

test("missing hosted metrics render as unmeasured instead of zero", () => {
  assert.equal(displayMetric(null), "미측정");
  assert.equal(displayMetric(undefined), "미측정");
  assert.equal(displayMetric(0), "0");
});

test("static engineering evidence mirrors committed isolated measurements", async () => {
  const evidence = await staticDemoRequest<EngineeringEvidence>(
    "/evaluation/engineering-evidence",
  );

  assert.equal(evidence.queue.status, "measured");
  assert.equal(evidence.queue.metrics.records, 1000);
  assert.equal(evidence.queue.metrics.completed_records, 1000);

  assert.equal(evidence.http.status, "measured");
  assert.equal(evidence.http.metrics.requests, 200);
  assert.equal(evidence.http.metrics.failed_requests, 0);

  assert.equal(evidence.query_plans.status, "measured");
  assert.equal(evidence.query_plans.metrics.candidate_adopted, false);
  assert.equal(evidence.query_plans.metrics.candidate_rolled_back, true);
});

test("static engineering evidence stays aligned with packaged API snapshot", async () => {
  const packaged = JSON.parse(
    readFileSync(
      new URL(
        "../../api/app/evaluation/results/engineering.json",
        import.meta.url,
      ),
      "utf8",
    ),
  ) as EngineeringEvidence;
  const staticEvidence = await staticDemoRequest<EngineeringEvidence>(
    "/evaluation/engineering-evidence",
  );

  assert.equal(
    staticEvidence.queue.metrics.records_per_second,
    packaged.queue.metrics.records_per_second,
  );
  assert.equal(
    (
      staticEvidence.http.metrics.endpoints as Record<
        string,
        { p95_ms: number }
      >
    ).inbox.p95_ms,
    (packaged.http.metrics.endpoints as Record<string, { p95_ms: number }>)
      .inbox.p95_ms,
  );
  assert.equal(
    staticEvidence.query_plans.metrics.improvement_ratio,
    packaged.query_plans.metrics.improvement_ratio,
  );
  assert.equal(
    staticEvidence.release.gates.some(
      (gate) => gate.gate === "pipeline-demo-e2e",
    ),
    true,
  );
});

test("static release evidence does not add later gates to the frozen reference", async () => {
  const reference = JSON.parse(
    readFileSync(
      new URL(
        "../../../artifacts/verification/release-gate.json",
        import.meta.url,
      ),
      "utf8",
    ),
  ) as { gates: { gate: string; passed: boolean }[] };
  const evidence = await staticDemoRequest<EngineeringEvidence>(
    "/evaluation/engineering-evidence",
  );
  for (const gate of evidence.release.gates) {
    assert.ok(
      reference.gates.some(
        (original) =>
          original.gate === gate.gate && original.passed === gate.passed,
      ),
      `Gate ${gate.gate} has no evidence in the frozen release reference`,
    );
  }
  assert.equal(evidence.backfill.metrics.records, 2000);
  assert.equal(evidence.backfill.metrics.resumed_from_checkpoint, true);
});
