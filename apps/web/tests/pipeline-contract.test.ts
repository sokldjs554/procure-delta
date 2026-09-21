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
