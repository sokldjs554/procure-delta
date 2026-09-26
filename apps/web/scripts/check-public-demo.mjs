import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { setTimeout } from "node:timers/promises";
import { demoPaths, hasProductTitle, verifySiteAssets } from "./site-assets.mjs";

// Fixed, public synthetic demo only. No API credentials or user data are sent.
const origin = "https://procure-delta-demo.onrender.com";
const output = resolve("../../artifacts/public-demo/http-assets.json");
const report = {
  scope: "public_demo_http_assets", origin, checked_at: new Date().toISOString(),
  // This identifies the checker, not the revision deployed by Render.
  verifier_revision: process.env.CHECKER_REVISION ?? null,
  status: "failed", warmup_attempts: 0, pages: [], assets: [],
};

try {
  // Free Render instances may return a 200 startup interstitial. Never count it
  // as product readiness. Waiting is bounded and only applies before the check.
  const deadline = Date.now() + 150000;
  let ready = false;
  let lastError = "Product HTML not ready";
  while (Date.now() < deadline) {
    report.warmup_attempts += 1;
    try {
      const response = await fetch(origin, { redirect: "error", signal: AbortSignal.timeout(15000) });
      const html = await response.text();
      if (response.status === 200 && hasProductTitle(html)) { ready = true; break; }
      lastError = `HTTP ${response.status}; product HTML not ready`;
    } catch (error) { lastError = error.message; }
    console.log(`Waiting for public demo: ${lastError}`);
    await setTimeout(5000);
  }
  if (!ready) throw new Error(`Public demo startup deadline exceeded: ${lastError}`);
  await verifySiteAssets(origin, demoPaths, report);
  report.status = "passed";
  console.log(`Public demo HTTP check passed: ${report.pages.length} routes, ${report.assets.length} unique JS/CSS assets`);
} catch (error) {
  report.error = error.message;
  console.error(error.message);
  process.exitCode = 1;
} finally {
  report.finished_at = new Date().toISOString();
  await mkdir(resolve(output, ".."), { recursive: true });
  await writeFile(output, `${JSON.stringify(report, null, 2)}\n`);
}
