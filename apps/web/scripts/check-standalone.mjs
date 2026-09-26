import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { setTimeout } from "node:timers/promises";
import { verifySiteAssets } from "./site-assets.mjs";

const port = process.env.STANDALONE_CHECK_PORT ?? "13225";
const origin = `http://127.0.0.1:${port}`;
const child = spawn(process.execPath, [".next/standalone/server.js"], {
  env: { ...process.env, HOSTNAME: "127.0.0.1", PORT: port },
  stdio: ["ignore", "pipe", "pipe"],
});
let output = "";
child.stdout.on("data", (data) => { output = (output + data).slice(-4000); });
child.stderr.on("data", (data) => { output = (output + data).slice(-4000); });
const exited = once(child, "exit");
try {
  let response;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    assert.equal(child.exitCode, null, `Standalone exited: ${output}`);
    try {
      response = await fetch(`${origin}/about`, { signal: AbortSignal.timeout(1000) });
      break;
    } catch {
      await setTimeout(100);
    }
  }
  assert.ok(response, `Standalone did not become ready: ${output}`);
  await response.arrayBuffer();
  const report = await verifySiteAssets(origin, ["/about"]);
  assert.equal(child.exitCode, null, `Standalone exited during asset checks: ${output}`);
  console.log(`Standalone HTTP check passed: /about + ${report.assets.length} JS/CSS assets`);
} finally {
  child.kill("SIGTERM");
  await exited;
}
