import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  decisionHeadline,
  displayMetric,
  nextReplayIndex,
} from "../lib/pipeline.ts";
import type { EngineeringEvidence } from "../lib/api.ts";
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
    (stages.get("eligibility")?.output.after as { allows_recommendation: boolean })
      .allows_recommendation,
    false,
  );
  assert.equal(stages.get("ranking")?.decision.eligibility_overrides_rank, true);
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
      new URL("../../api/app/evaluation/results/engineering.json", import.meta.url),
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
    (staticEvidence.http.metrics.endpoints as Record<string, { p95_ms: number }>).inbox.p95_ms,
    (packaged.http.metrics.endpoints as Record<string, { p95_ms: number }>).inbox.p95_ms,
  );
  assert.equal(
    staticEvidence.query_plans.metrics.improvement_ratio,
    packaged.query_plans.metrics.improvement_ratio,
  );
  assert.equal(
    staticEvidence.release.gates.some((gate) => gate.gate === "pipeline-demo-e2e"),
    true,
  );
});
