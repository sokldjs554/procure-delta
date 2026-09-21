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
