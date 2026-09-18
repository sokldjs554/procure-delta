import assert from "node:assert/strict";
import test from "node:test";

import { getApiStatus } from "../lib/health.ts";

test("reports available for a successful liveness response", async () => {
  const fetchHealth = async () => new Response(null, { status: 200 });

  assert.equal(await getApiStatus("http://api", fetchHealth), "Available");
});

test("reports unavailable for a non-success response", async () => {
  const fetchHealth = async () => new Response(null, { status: 503 });

  assert.equal(await getApiStatus("http://api", fetchHealth), "Unavailable");
});

test("reports unavailable when the liveness request throws", async () => {
  const fetchHealth = async () => {
    throw new Error("connection refused");
  };

  assert.equal(await getApiStatus("http://api", fetchHealth), "Unavailable");
});
