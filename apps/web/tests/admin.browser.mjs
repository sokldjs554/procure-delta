import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({ channel: "chrome", headless: true });
const baseUrl = process.env.WEB_BASE_URL ?? "http://localhost:3000";
const context = await browser.newContext();
const page = await context.newPage();
const requests = [];
let pipelineRequests = 0;
let continuationRequests = 0;
let releaseContinuation;

await page.route("**/api/v1/**", async (route) => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  requests.push(`${request.method()} ${path}`);
  if (path.endsWith("/auth/session"))
    return route.fulfill({ status: 401, body: "{}" });
  if (path.endsWith("/auth/demo-login")) {
    if (request.postDataJSON().operator_secret === "wrong")
      return route.fulfill({ status: 401, body: "{}" });
    assert.deepEqual(request.postDataJSON(), {
      operator_secret: "entered-once",
    });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        owner_id: "operator",
        role: "operator",
        csrf_token: "csrf",
        synthetic_demo: true,
      }),
    });
  }
  if (path.endsWith("/admin/pipeline")) {
    pipelineRequests += 1;
    if (pipelineRequests === 1)
      return route.fulfill({ status: 503, body: "{}" });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        observed_at: "2026-09-16T12:00:00Z",
        records_fetched_today: 12,
        new_records_today: 7,
        changed_versions_today: 3,
        duplicates_skipped_today: 2,
        parsing_failures: 1,
        ocr_fallbacks: 4,
        structured_extraction_count: 9,
        schema_validation_failures: 2,
        retry_queue_count: 1,
        dlq_count: 1,
        worker_queue_depth: 5,
        scheduler_queue_depth: 0,
        worker_heartbeat: true,
        scheduler_heartbeat: true,
        worker_activity: { completed: 20, failed: 2, retried: 3, ongoing: 1 },
        scheduler_activity: null,
        parsing: [
          { kind: "native", status: "completed", count: 8 },
          { kind: "ocr", status: "completed", count: 4 },
        ],
        extraction: [
          { kind: "deterministic-v1", status: "trusted", count: 7 },
          { kind: "deterministic-v1", status: "rejected", count: 2 },
        ],
      }),
    });
  }
  if (path.endsWith("/admin/sources"))
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "source",
          code: "mock",
          display_name: "Synthetic procurement fixture",
          enabled: true,
          polling_interval_seconds: 300,
          last_success_at: "2026-09-16T11:59:00Z",
          last_failure_at: null,
        },
      ]),
    });
  if (path.endsWith("/admin/failures")) {
    const cursor = new URL(request.url()).searchParams.get("cursor");
    if (cursor) {
      continuationRequests += 1;
      if (continuationRequests === 1)
        return route.fulfill({ status: 503, body: "{}" });
      await new Promise((resolve) => {
        releaseContinuation = resolve;
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        cursor
          ? {
              items: [
                {
                  id: "00000000-0000-0000-0000-000000000002",
                  job_type: "extract_version",
                  attempts: 2,
                  error_code: "ValidationError",
                  last_error_at: "2026-09-16T11:30:00Z",
                  dead_lettered: true,
                  next_retry_at: null,
                },
              ],
              next_cursor: null,
            }
          : {
              items: [
                {
                  id: "00000000-0000-0000-0000-000000000001",
                  job_type: "parse_documents",
                  attempts: 3,
                  error_code: "ValidationError",
                  last_error_at: "2026-09-16T11:00:00Z",
                  dead_lettered: true,
                  next_retry_at: null,
                },
              ],
              next_cursor: "00000000-0000-0000-0000-000000000001",
            },
      ),
    });
  }
  if (path.endsWith("/release"))
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        name: "ProcureDelta",
        version: "0.1.0",
        revision: "abc123",
        authentication: "synthetic-demo-nonproduction",
        extraction_mode: "deterministic",
      }),
    });
  if (path.endsWith("/retry"))
    return route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        failure_id: "00000000-0000-0000-0000-000000000001",
        status: "retry_pending",
        queue_published: false,
      }),
    });
  return route.abort();
});

try {
  await page.goto(`${baseUrl}/admin`);
  await page.getByRole("heading", { name: "운영자 로그인" }).waitFor();
  await page.getByLabel("운영자 비밀값").fill("wrong");
  await page.getByRole("button", { name: "운영 콘솔 열기" }).click();
  await page.getByText("비밀값이 올바르지 않습니다.").waitFor();
  await page.getByLabel("운영자 비밀값").fill("entered-once");
  await page.getByRole("button", { name: "운영 콘솔 열기" }).click();
  await page.getByRole("heading", { name: "파이프라인 운영 현황" }).waitFor();
  assert.equal(
    await page.getByText("Synthetic procurement fixture").count(),
    1,
    "independent source panel remains usable",
  );
  await page.getByRole("button", { name: "다시 시도" }).first().click();
  await page.getByText("12", { exact: true }).waitFor();
  assert.equal(await page.getByText("12", { exact: true }).count(), 1);
  assert.match(
    await page.getByText("프로세스 활동 미확인").innerText(),
    /미확인/,
  );
  await page.getByRole("button", { name: "실패 더 보기" }).click();
  await page.getByRole("button", { name: "페이지 다시 시도" }).waitFor();
  assert.equal(
    await page.getByText("parse_documents").count(),
    1,
    "continuation error preserves loaded failures",
  );
  await page.getByRole("button", { name: "페이지 다시 시도" }).click();
  await page.locator(".admin-table button").last().click({ force: true });
  assert.equal(continuationRequests, 2, "continuation remains single-flight");
  await page.getByRole("button", { name: "작업 재시도" }).first().click();
  await page
    .getByText(/복구 상태는 저장됐지만 큐 게시를 확인하지 못했습니다/)
    .waitFor();
  releaseContinuation();
  await page.waitForTimeout(50);
  assert.equal(
    await page.getByText("extract_version").count(),
    0,
    "late continuation cannot restore refreshed failures",
  );
  assert.equal(
    requests.filter((value) => value.endsWith("/retry")).length,
    1,
    "one click publishes at most one retry request",
  );
  assert.equal(
    await page.locator('input[type="password"]').count(),
    0,
    "credential leaves the rendered tree after login",
  );
  console.log(
    "admin browser: operator auth, measured KPIs, unknown activity and bounded retry passed",
  );
} finally {
  await context.close();
  await browser.close();
}
