// Runs against the production static-demo build used by the public Render demo.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { setTimeout } from "node:timers/promises";
import { chromium } from "playwright";

const port = "13226";
const origin = `http://127.0.0.1:${port}`;
const output = resolve("../../artifacts/e2e/demo-workspace");
mkdirSync(output, { recursive: true });
const server = spawn(process.execPath, [".next/standalone/server.js"], {
  env: { ...process.env, HOSTNAME: "127.0.0.1", PORT: port },
  stdio: ["ignore", "pipe", "pipe"],
});
let serverLog = "";
for (const stream of [server.stdout, server.stderr]) {
  stream.on("data", chunk => { serverLog = (serverLog + chunk).slice(-4000); });
}
const exited = once(server, "exit");
let browser;
let activePage;
const errors = [];
const titles = {
  contact: "AI 기반 민원상담 시스템 구축",
  document: "AI 문서분류·OCR 자동화 플랫폼 고도화",
  data: "공공 데이터 수집·추천 플랫폼 운영",
};
async function visibleCards(page, expected) {
  await page.waitForFunction(count => document.querySelectorAll(".cards .card").length === count, expected);
  return page.locator(".cards .card");
}
async function noOverflow(page) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${page.url()} overflows the viewport`);
}
async function screenshot(page, name, fullPage = true) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: resolve(output, `${name}.png`), fullPage });
}
try {
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    assert.equal(server.exitCode, null, serverLog);
    try {
      const response = await fetch(origin, { signal: AbortSignal.timeout(1000) });
      if (response.ok) { ready = true; break; }
    } catch { /* Server is still binding. */ }
    await setTimeout(100);
  }
  assert.ok(ready, serverLog);
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, timezoneId: "Asia/Seoul" });
  const page = await context.newPage();
  activePage = page;
  page.setDefaultTimeout(20000);
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(origin);
  await page.locator(".hero h1").waitFor();
  await noOverflow(page);
  await screenshot(page, "landing-desktop");
  await page.getByRole("link", { name: "제품 둘러보기" }).click();
  await visibleCards(page, 3);
  await page.keyboard.press("Tab");
  await page.getByRole("link", { name: "본문으로 건너뛰기" }).focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.locator("#workspace-content").evaluate(element => document.activeElement === element), true);
  await page.getByRole("button", { name: /^참여 조건 충족/ }).click();
  assert.match(await (await visibleCards(page, 1)).innerText(), /OCR 자동화/);
  await page.getByRole("button", { name: /^확인 필요/ }).click();
  assert.match(await (await visibleCards(page, 1)).innerText(), /민원상담/);
  await page.getByRole("button", { name: /^전체/ }).click();
  await visibleCards(page, 3);
  await page.getByLabel("정렬", { exact: true }).selectOption("deadline");
  assert.equal(await page.locator(".cards h2 a").first().textContent(), titles.document);
  await page.getByLabel("정렬", { exact: true }).selectOption("budget");
  assert.equal(await page.locator(".cards h2 a").first().textContent(), titles.data);
  for (const title of Object.values(titles)) {
    await page.locator(".cards .card").filter({ hasText: title }).getByRole("checkbox", { name: "비교 목록에 담기" }).check();
  }
  assert.equal(await page.locator(".compare-table thead th").count(), 4);
  await noOverflow(page);
  await screenshot(page, "inbox-comparison-desktop");
  await page.getByRole("button", { name: `${titles.data} 비교에서 제외` }).click();
  assert.equal(await page.locator(".compare-table thead th").count(), 3);
  await page.getByRole("button", { name: "비교 초기화" }).click();
  assert.equal(await page.locator(".compare-section").count(), 0);
  await page.locator(".advanced-filters summary").click();
  await page.getByLabel("발주기관", { exact: true }).fill("공공데이터");
  await page.getByRole("button", { name: "필터 적용", exact: true }).click();
  assert.match(await (await visibleCards(page, 1)).innerText(), /OCR 자동화/);
  await page.getByRole("checkbox", { name: "비교 목록에 담기" }).check();
  await page.getByRole("button", { name: "필터 초기화", exact: true }).click();
  await visibleCards(page, 3);
  assert.equal(await page.locator(".compare-section").count(), 0);
  await page.getByLabel("최소 금액", { exact: true }).fill("200000000");
  await page.getByLabel("최대 금액", { exact: true }).fill("300000000");
  await page.getByRole("button", { name: "필터 적용", exact: true }).click();
  assert.match(await (await visibleCards(page, 1)).innerText(), /민원상담/);
  await page.getByRole("button", { name: "필터 초기화", exact: true }).click();
  await visibleCards(page, 3);
  await page.getByLabel("검색", { exact: true }).fill("없는 공고");
  await page.getByRole("button", { name: "필터 적용", exact: true }).click();
  await page.getByRole("heading", { name: "조건에 맞는 공고가 없습니다" }).waitFor();
  await page.getByRole("button", { name: "필터 초기화", exact: true }).click();
  await visibleCards(page, 3);
  await page.locator(".cards h2 a").filter({ hasText: titles.contact }).click();
  await page.locator(".detail-head h1").waitFor();
  await page.getByLabel("공고 버전").selectOption("ver-ai-1");
  await page.getByText(/이전 버전의 공고 내용입니다/).waitFor();
  await page.getByLabel("공고 버전").selectOption("ver-ai-2");
  await page.getByRole("table", { name: "필드 변경 전후" }).waitFor();
  assert.equal(await page.locator('a[href="#synthetic-document"]').count(), 0);
  await page.getByText(/합성 문서 예시 · 실제 파일 없음/).first().waitFor();
  await screenshot(page, "detail-desktop");
  await page.getByRole("link", { name: "공고함으로 돌아가기" }).click();
  await visibleCards(page, 3);
  await page.locator(".cards h2 a").filter({ hasText: titles.document }).click();
  await page.getByRole("button", { name: "관심 공고로 추적", exact: true }).click();
  await page.getByRole("button", { name: "관심 공고 해제", exact: true }).waitFor();
  await page.getByRole("navigation", { name: "주요 메뉴" }).getByRole("link", { name: "관심 공고", exact: true }).click();
  await visibleCards(page, 2);
  await page.getByRole("navigation", { name: "주요 메뉴" }).getByRole("link", { name: "알림", exact: true }).click();
  await page.getByText("참가 조건과 예산이 변경되었습니다.", { exact: true }).waitFor();
  await screenshot(page, "notifications-desktop");
  await page.getByRole("link", { name: "변경된 공고 확인 →" }).first().click();
  assert.equal(await page.locator(".detail-head h1").textContent(), titles.contact);
  await page.getByRole("navigation", { name: "주요 메뉴" }).getByRole("link", { name: "파이프라인", exact: true }).click();
  await page.getByText("1 / 12 단계", { exact: true }).waitFor();
  await page.getByRole("button", { name: "다음 단계", exact: true }).click();
  await page.getByText("2 / 12 단계", { exact: true }).waitFor();
  await page.getByRole("button", { name: /정정으로 조건 변경/ }).click();
  await page.locator('button[data-stage-id="delta"]').click();
  await page.locator(".impact-change-list").waitFor();
  assert.match(await page.locator(".impact-change-list").innerText(), /₩320,000,000/);
  assert.match(await page.locator(".impact-change-list").innerText(), /₩280,000,000/);
  assert.ok(!(await page.locator(".impact-change-list").innerText()).includes("estimated_amount"));
  await screenshot(page, "pipeline-desktop", false);
  assert.deepEqual(errors, []);
  await context.close();

  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
  const mobilePage = await mobile.newPage();
  activePage = mobilePage;
  mobilePage.setDefaultTimeout(20000);
  mobilePage.on("pageerror", error => errors.push(error.message));
  for (const route of ["/", "/inbox", "/opportunities/opp-ai-contact-center", "/pipeline", "/notifications", "/profile", "/about"]) {
    await mobilePage.goto(`${origin}${route}`);
    await mobilePage.locator("h1").waitFor();
    if (route === "/inbox") {
      await visibleCards(mobilePage, 3);
      for (const title of Object.values(titles)) {
        await mobilePage.locator(".cards .card").filter({ hasText: title }).getByRole("checkbox", { name: "비교 목록에 담기" }).check();
      }
      assert.equal(await mobilePage.locator(".compare-table thead th").count(), 4);
    }
    if (route === "/pipeline") {
      await mobilePage.getByRole("button", { name: /정정으로 조건 변경/ }).click();
      await mobilePage.locator('button[data-stage-id="delta"]').click();
      await mobilePage.locator(".impact-change-list").waitFor();
    }
    await noOverflow(mobilePage);
    await screenshot(mobilePage, `${route === "/" ? "landing" : route.split("/")[1]}-mobile`);
  }
  assert.deepEqual(errors, []);
  await mobile.close();
  console.log("Static demo workspace E2E passed: filters, quick views, sorts, comparison, version selection, watch, notifications, replay, seven mobile routes.");
} catch (error) {
  if (activePage && !activePage.isClosed()) await screenshot(activePage, "failure").catch(() => {});
  throw error;
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
  await exited;
}
