import assert from "node:assert/strict";
import { chromium } from "playwright";

const web = process.env.E2E_WEB_URL ?? "http://localhost:3000";
if (!["localhost", "127.0.0.1"].includes(new URL(web).hostname)) {
  throw Error("Product browser regression targets local verification only");
}
const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
});
const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));

try {
  await page.goto(`${web}/inbox`, { waitUntil: "networkidle" });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);

  let requests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/v1/opportunities") requests += 1;
  });
  await page.getByRole("button", { name: "필터 적용" }).click();
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "필터 적용" }).click();
  await page.waitForLoadState("networkidle");
  assert.ok(requests >= 2, "repeated identical filters must refetch");

  await page.getByRole("link", { name: "기업 프로필" }).click();
  await page.getByLabel("활동 지역").fill("Seoul, ");
  assert.equal(await page.getByLabel("활동 지역").inputValue(), "Seoul, ");
  await page.getByLabel("기업 표시 이름").fill("Synthetic Browser QA Company");
  const profile = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/company-profile" && response.request().method() === "PATCH");
  await page.getByRole("button", { name: "변경 저장" }).click();
  assert.equal((await profile).status(), 200, "profile payload must contain only writable fields");

  await page.getByRole("link", { name: "공고함" }).click();
  await page.waitForLoadState("networkidle");
  await page.locator(".card h2 a").first().click();
  await page.waitForLoadState("networkidle");
  const watch = page.waitForResponse((response) => /\/watch$/.test(new URL(response.url()).pathname));
  await page.getByRole("button", { name: /관심 공고로 추적|관심 공고 해제/ }).click();
  assert.ok([200, 204].includes((await watch).status()));

  const lifecycleTarget = page.locator(".timeline a").first();
  assert.ok((await lifecycleTarget.count()) > 0, "fixture must expose a lifecycle navigation target");
  const target = await lifecycleTarget.getAttribute("href");
  let releaseWatch;
  const watchRelease = new Promise((resolve) => { releaseWatch = resolve; });
  await page.route("**/api/v1/opportunities/*/watch", async (route) => {
    await watchRelease;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ opportunity_id: "delayed", watched: true }) });
  });
  await page.getByRole("button", { name: /관심 공고로 추적|관심 공고 해제/ }).click();
  await lifecycleTarget.click();
  await page.waitForURL(`**${target}`);
  const targetHeading = await page.locator(".detail-head h1").innerText();
  releaseWatch();
  await page.waitForTimeout(100);
  assert.equal(await page.locator(".detail-head h1").innerText(), targetHeading, "delayed watch response must not restore prior opportunity content");
  await page.unroute("**/api/v1/opportunities/*/watch");

  await page.getByRole("link", { name: "알림" }).click();
  await page.waitForLoadState("networkidle");
  const preferences = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/notifications/preferences" && response.request().method() === "PUT");
  await page.getByRole("button", { name: "설정 저장" }).click();
  assert.equal((await preferences).status(), 200);

  await page.getByRole("link", { name: "ProcureDelta" }).click();
  await page.waitForURL(`${web}/`);
  const ordinaryCompletedVisit = await page.evaluate(() => localStorage.getItem("procureDeltaLastVisit"));
  assert.ok(ordinaryCompletedVisit, "ordinary SPA landing departure must persist the completed visit");
  await page.getByRole("link", { name: "제품 둘러보기" }).click();
  await page.waitForURL(`${web}/inbox`);
  assert.equal(await page.evaluate(() => sessionStorage.getItem("procureDeltaPreviousVisit")), ordinaryCompletedVisit);

  await page.getByRole("button", { name: "데모 종료" }).click();
  await page.waitForURL(`${web}/`);
  assert.equal(new URL(page.url()).pathname, "/");
  const completedVisit = await page.evaluate(() => localStorage.getItem("procureDeltaLastVisit"));
  assert.ok(completedVisit, "SPA departure must persist the completed visit timestamp");
  await page.getByRole("link", { name: "제품 둘러보기" }).click();
  await page.waitForURL(`${web}/inbox`);
  assert.equal(await page.evaluate(() => sessionStorage.getItem("procureDeltaPreviousVisit")), completedVisit);
  assert.deepEqual(errors, []);

  const outage = await browser.newContext();
  const outagePage = await outage.newPage();
  let loginAttempts = 0;
  await outagePage.route("**/api/v1/auth/session", (route) => route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"unavailable"}' }));
  await outagePage.route("**/api/v1/auth/demo-login", (route) => { loginAttempts += 1; return route.continue(); });
  await outagePage.goto(`${web}/inbox`);
  await outagePage.getByRole("heading", { name: "데모를 시작할 수 없습니다" }).waitFor();
  assert.equal(loginAttempts, 0, "session 503 must not create a replacement owner");
  await outage.close();
  console.log("browser regression: profile/watch/preferences/reload/logout/mobile/session-503 passed");
} finally {
  await context.close();
  await browser.close();
}
