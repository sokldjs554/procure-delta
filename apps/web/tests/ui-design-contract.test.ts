import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../app/styles.css", import.meta.url), "utf8");

test("landing uses the structured procurement visual system", () => {
  assert.match(page, /맞는 공고만/);
  assert.match(page, /hero-console/);
  assert.match(page, /procurement-rail/);
  assert.match(page, /hero-data-note/);
  assert.match(styles, /\.hero-console/);
  assert.match(styles, /\.procurement-rail/);
  assert.match(styles, /repeating-linear-gradient/);
  assert.doesNotMatch(styles, /linear-gradient\(120deg,#f5f0e5,#e3eee4\)/);
});

test("product and admin pages share the refreshed structured surfaces", () => {
  assert.match(styles, /\.product::before/);
  assert.match(styles, /\.filters::before/);
  assert.match(styles, /\.admin \.panel/);
  assert.match(styles, /box-shadow:0 18px 50px/);
});
