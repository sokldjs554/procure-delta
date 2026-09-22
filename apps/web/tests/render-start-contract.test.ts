import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("production start command uses the standalone Next.js server", () => {
  const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.equal(pkg.scripts.start, "HOSTNAME=0.0.0.0 node .next/standalone/server.js");
});


test("Docker build exposes both public Next.js configuration values", () => {
  const dockerfile = readFileSync(new URL("../Dockerfile", import.meta.url), "utf8");
  assert.match(dockerfile, /ARG NEXT_PUBLIC_API_URL=/);
  assert.match(dockerfile, /ENV NEXT_PUBLIC_API_URL=\$NEXT_PUBLIC_API_URL/);
  assert.match(dockerfile, /ARG NEXT_PUBLIC_STATIC_DEMO=false/);
  assert.match(dockerfile, /ENV NEXT_PUBLIC_STATIC_DEMO=\$NEXT_PUBLIC_STATIC_DEMO/);
});
