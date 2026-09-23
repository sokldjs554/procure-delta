// Actual API + PostgreSQL/Redis demo. No request interception, fake response or timer-driven UI.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const web = process.env.E2E_WEB_URL ?? "http://localhost:13000";
// Browser sessions must work through the web origin, including proxied Set-Cookie.
const api = web;
const project = process.env.COMPOSE_PROJECT_NAME ?? "procure-delta-verify";
if (!/^procure-delta-verify(?:-[a-z0-9-]+)?$/.test(project)) throw Error("Use an isolated verification project");
for (const url of [web]) {
  if (!["localhost", "127.0.0.1"].includes(new URL(url).hostname)) throw Error("Local E2E targets only");
}
const secret = process.env.VERIFY_OPERATOR_SECRET;
if (!secret) throw Error("VERIFY_OPERATOR_SECRET must be provided by the local verification runner");
const runId = `e2e-${Date.now()}`;
const output = resolve(root, "artifacts/e2e");
mkdirSync(output, { recursive: true });
const checks = [];
const apiRequestOrigins = new Set();
function observeApiRequests(context) {
  context.on("request", request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/v1/")) apiRequestOrigins.add(url.origin);
  });
}
function seed(phase) {
  const text = execFileSync("docker", ["compose", "--env-file", process.platform === "win32" ? "NUL" : "/dev/null", "-p", project, "-f", "compose.verify.yml",
    "exec", "-T", "api", "python", "-m", "app.demo.seed", "--run-id", runId, "--phase", phase],
    { cwd: root, encoding: "utf8", timeout: 180000, env: process.env });
  const result = JSON.parse(text);
  assert.equal(result.synthetic, true);
  return result;
}
const base = seed("base");
const tender = base.versions.find(item => item.stage === "tender");
assert.ok(tender);
let browser;
let page;
let passed = false;
try {
  browser = await chromium.launch({ headless: true,
    ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  observeApiRequests(context);
  page = await context.newPage();
  page.setDefaultTimeout(30000);
  await page.goto(`${web}/inbox`);
  await page.getByRole("heading", { name: "공고함", exact: true }).waitFor();
  const actorResponse = await context.request.get(`${api}/api/v1/auth/session`);
  assert.equal(actorResponse.status(), 200);
  const actor = await actorResponse.json();
  const sessionCookie = (await context.cookies(web)).find(item => item.name === "procure_delta_session");
  assert.ok(sessionCookie);
  assert.equal(sessionCookie.domain, new URL(web).hostname);
  assert.equal(sessionCookie.httpOnly, true);
  assert.equal(sessionCookie.sameSite, "Lax");
  const rejectedOrigin = await context.request.patch(`${api}/api/v1/company-profile`, {
    headers: { Origin: "https://untrusted.example", "X-CSRF-Token": actor.csrf_token },
    data: { display_name: "Rejected" },
  });
  assert.equal(rejectedOrigin.status(), 403);
  const rejectedCsrf = await context.request.patch(`${api}/api/v1/company-profile`, {
    headers: { Origin: web, "X-CSRF-Token": "invalid" }, data: { display_name: "Rejected" },
  });
  assert.equal(rejectedCsrf.status(), 403);
  checks.push("same-origin session cookie / proxy preserves Origin and CSRF rejection");
  const update = await context.request.patch(`${api}/api/v1/company-profile`, {
    headers: { "X-CSRF-Token": actor.csrf_token }, data: {
      regions: ["Seoul"], industries: ["services"],
      capabilities: ["cloud migration", "document processing"], certifications: ["ISO 27001"],
      min_contract_amount: "10000000", max_contract_amount: "500000000", contract_currency: "KRW",
    },
  });
  assert.equal(update.status(), 200);
  await page.getByLabel("검색", { exact: true }).fill(runId);
  await page.getByRole("combobox", { name: "생애주기", exact: true }).selectOption("tender");
  await page.getByRole("button", { name: "필터 적용", exact: true }).click();
  await page.locator(`a[href="/opportunities/${tender.opportunity_id}"]`).first().click();
  await page.locator(".detail-head h1").waitFor();
  let detail = await (await context.request.get(`${api}/api/v1/opportunities/${tender.opportunity_id}`)).json();
  assert.equal(detail.eligibility.eligible, true);
  assert.equal(detail.eligibility.warnings.length, 0);
  assert.equal(detail.extraction.status, "validated");
  assert.ok(detail.documents.some(doc => /^[a-f0-9]{64}$/.test(doc.sha256)));
  const document = detail.documents.find(doc => /^[a-f0-9]{64}$/.test(doc.sha256));
  const original = await context.request.get(`${api}/api/v1/documents/${document.id}/original`);
  assert.equal(original.status(), 200);
  assert.equal(createHash("sha256").update(await original.body()).digest("hex"), document.sha256);
  checks.push("original attachment bytes retain their checksum through the web proxy");
  await page.getByRole("button", { name: "관심 공고로 추적", exact: true }).click();
  await page.getByRole("button", { name: "관심 공고 해제", exact: true }).waitFor();
  checks.push("real inbox / eligibility / evidence / watch mutation");
  await page.screenshot({ path: resolve(output, "01-tender.png"), fullPage: true });
  seed("amendment");
  await page.reload();
  await page.locator("article.delta").getByText("high 영향", { exact: true }).first().waitFor();
  detail = await (await context.request.get(`${api}/api/v1/opportunities/${tender.opportunity_id}`)).json();
  assert.equal(detail.lifecycle_stage, "amendment");
  assert.equal(detail.versions.length, 2);
  assert.equal(Number(detail.estimated_amount), 280000000);
  assert.ok(detail.deltas.items.some(item => item.impact_level === "high" && item.applicable_now));
  checks.push("amendment persisted on same opportunity / actual high-impact delta");
  await page.screenshot({ path: resolve(output, "02-delta.png"), fullPage: true });
  await page.goto(`${web}/notifications`);
  let notices = await (await context.request.get(`${api}/api/v1/notifications?limit=100`)).json();
  assert.ok(notices.items.some(item => item.opportunity_id === tender.opportunity_id &&
    item.template_key === "watched_material_change" && item.status === "sent" && item.receipt_id));
  checks.push("durable outbox / local delivery receipt / notification history");
  await page.screenshot({ path: resolve(output, "03-notifications.png"), fullPage: true });
  const outcomes = seed("outcome");
  const contract = outcomes.versions.find(item => item.stage === "contract");
  assert.ok(contract);
  const chain = await (await context.request.get(`${api}/api/v1/opportunities/${contract.opportunity_id}`)).json();
  assert.ok(chain.timeline.active_links.length >= 3);
  assert.ok(chain.timeline.opportunity_ids.includes(tender.opportunity_id));
  notices = await (await context.request.get(`${api}/api/v1/notifications?limit=100`)).json();
  assert.ok(notices.items.some(item => item.template_key === "outcome_published"));
  await page.goto(`${web}/opportunities/${contract.opportunity_id}`);
  await page.locator(".detail-head h1").waitFor();
  checks.push("prespec → tender/amendment → award → contract active graph");
  await page.screenshot({ path: resolve(output, "04-contract.png"), fullPage: true });
  const operatorContext = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  observeApiRequests(operatorContext);
  const operatorPage = await operatorContext.newPage();
  await operatorPage.goto(`${web}/admin`);
  await operatorPage.getByLabel("운영자 비밀값", { exact: true }).fill(secret);
  await operatorPage.getByRole("button", { name: "운영 콘솔 열기", exact: true }).click();
  await operatorPage.getByRole("heading", { name: "파이프라인 운영 현황" }).waitFor();
  const pipeline = await operatorContext.request.get(`${api}/api/v1/admin/pipeline`);
  assert.equal(pipeline.status(), 200);
  const stats = await pipeline.json();
  for (const key of ["records_fetched_today", "parsing_failures", "ocr_fallbacks",
    "structured_extraction_count", "schema_validation_failures", "retry_queue_count", "dlq_count",
    "worker_queue_depth", "scheduler_queue_depth"]) {
    assert.equal(typeof stats[key], "number");
    assert.ok(stats[key] >= 0);
  }
  assert.ok(stats.structured_extraction_count >= 5);
  assert.ok(Array.isArray(stats.parsing) && Array.isArray(stats.extraction));
  const statsText = JSON.stringify(stats);
  assert.ok(!statsText.includes(secret));
  await operatorPage.screenshot({ path: resolve(output, "05-admin.png"), fullPage: true });
  checks.push("operator console / real pipeline aggregates / no operator secret exposure");
  await page.goto(`${web}/about`);
  await page.getByText(/합성 회귀 평가 ·/).waitFor();
  await page.screenshot({ path: resolve(output, "06-evaluation.png"), fullPage: true });
  checks.push("evaluation page reads committed artifact through actual API");
  assert.deepEqual([...apiRequestOrigins], [new URL(web).origin]);
  const logout = await context.request.post(`${api}/api/v1/auth/logout`, {
    headers: { Origin: web, "X-CSRF-Token": actor.csrf_token },
  });
  assert.equal(logout.status(), 204);
  assert.equal((await context.request.get(`${api}/api/v1/auth/session`)).status(), 401);
  assert.ok(!(await context.cookies(web)).some(item => item.name === "procure_delta_session"));
  checks.push("all browser API requests stay on the web origin / logout clears the session");
  passed = true;
} catch (error) {
  if (page) await page.screenshot({ path: resolve(output, "failure.png") }).catch(() => {});
  // No trace/HAR/cookie storage is saved, so credentials are not included in artifacts.
  throw error;
} finally {
  writeFileSync(resolve(output, "result.json"), JSON.stringify({
    passed, synthetic: true, run_id: runId, checks, network_mocking: false,
    browser_api_same_origin: passed && apiRequestOrigins.size === 1 &&
      apiRequestOrigins.has(new URL(web).origin),
    created_at: new Date().toISOString(), external_llm_verified: false,
  }, null, 2));
  if (browser) await browser.close();
}
console.log(`Lifecycle E2E passed (${checks.length} gates).`);
