import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("inbox lifecycle filters use the actual backend stage identifiers", () => {
  const page = readFileSync(new URL("../app/(product)/inbox/page.tsx", import.meta.url), "utf8");
  assert.match(page, /value="pre-specification"/);
  assert.match(page, /value="tender"/);
  assert.doesNotMatch(page, /value="pre_notice"|value="notice"/);
});


test("inbox lifecycle select has a stable explicit accessible name", () => {
  const page = readFileSync(new URL("../app/(product)/inbox/page.tsx", import.meta.url), "utf8");
  assert.match(page, /<select[^>]*name="lifecycle_stage"[^>]*aria-label="생애주기"/);
});


test("lifecycle E2E uses the explicit combobox accessible name", () => {
  const e2e = readFileSync(new URL("../e2e/lifecycle.mjs", import.meta.url), "utf8");
  assert.match(e2e, /getByRole\("combobox", \{ name: "생애주기", exact: true \}\)/);
  assert.doesNotMatch(e2e, /getByLabel\("생애주기", \{ exact: true \}\)/);
});
