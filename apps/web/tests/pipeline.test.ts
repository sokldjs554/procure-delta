import assert from "node:assert/strict";
import test from "node:test";

import { nextReplayIndex } from "../lib/pipeline.ts";
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
