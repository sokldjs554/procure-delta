import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("production start command uses the standalone Next.js server", () => {
  const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.equal(pkg.scripts.start, "HOSTNAME=0.0.0.0 node .next/standalone/server.js");
});
