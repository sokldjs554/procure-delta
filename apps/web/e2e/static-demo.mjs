import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const web = process.env.E2E_WEB_URL ?? "http://127.0.0.1:3100";
if (!["localhost", "127.0.0.1"].includes(new URL(web).hostname)) {
  throw Error("Static public demo E2E targets local verification only");
}
const output = resolve(root, "artifacts/e2e/static-public");
mkdirSync(output, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
const page = await context.newPage();
const errors = [];
let apiRequests = 0;
page.on("pageerror", (error) => errors.push(error.message));
page.on("request", (request) => {
  if (new URL(request.url()).pathname.startsWith("/api/v1/")) apiRequests += 1;
});
page.setDefaultTimeout(30000);

try {
  await page.goto(web);
  await page.locator(".hero h1").waitFor();
  await page.screenshot({ path: resolve(output, "01-landing.png"), fullPage: true });

  await page.getByRole("link", { name: "제품 둘러보기" }).click();
  await page.getByRole("heading", { name: "공고함", exact: true }).waitFor();
  await page.getByLabel("발주기관").fill("서울 디지털행정원");
  await page.getByLabel("최소 금액").fill("250000000");
  await page.getByLabel("최대 금액").fill("300000000");
  await page.getByRole("button", { name: "필터 적용", exact: true }).click();
  const card = page.locator(".card").filter({ hasText: "AI 기반 민원상담 시스템 구축" });
  await card.waitFor();
  assert.equal(await page.locator(".card").count(), 1, "static filters must honor buyer and amount");

  await card.locator("h2 a").click();
  await page.getByRole("heading", { name: "AI 기반 민원상담 시스템 구축" }).waitFor();
  await page.getByText("공개 합성 데모에서는 원문 파일을 제공하지 않습니다.").waitFor();
  await page.screenshot({ path: resolve(output, "02-detail.png"), fullPage: true });
  const overflow = await page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const offenders = [...document.querySelectorAll("*")]
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.right > width + 1 || rect.left < -1;
      })
      .slice(0, 12)
      .map((element) => ({
        tag: element.tagName,
        className: String(element.className ?? ""),
        left: Math.round(element.getBoundingClientRect().left),
        right: Math.round(element.getBoundingClientRect().right),
        scrollWidth: element.scrollWidth,
        clientWidth: element.clientWidth,
      }));
    return {
      overflows: document.documentElement.scrollWidth > innerWidth,
      viewport: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      offenders,
    };
  });
  if (overflow.overflows) console.error("detail overflow diagnostics", JSON.stringify(overflow));
  assert.equal(overflow.overflows, false, "detail page must not overflow horizontally");

  await page.getByRole("link", { name: "기업 프로필" }).click();
  await page.getByLabel("활동 지역").fill("부산");
  await page.getByRole("button", { name: "변경 저장" }).click();
  await page.getByText("프로필을 저장했습니다. 다음 공고 조회부터 반영됩니다.").waitFor();

  await page.getByRole("link", { name: "공고함" }).click();
  await page.getByLabel("경고 없는 참여 가능 공고만").check();
  await page.getByRole("button", { name: "필터 적용", exact: true }).click();
  await page.getByRole("heading", { name: "조건에 맞는 공고가 없습니다" }).waitFor();

  await page.getByRole("link", { name: "기업 프로필" }).click();
  await page.getByLabel("활동 지역").fill("서울, 경기");
  await page.getByRole("button", { name: "변경 저장" }).click();

  await page.getByRole("link", { name: "파이프라인" }).click();
  await page.getByRole("heading", { name: "파이프라인을 직접 재생해보세요" }).waitFor();
  await page.getByRole("button", { name: /정정으로 조건 변경/ }).click();
  await page.locator('button[data-stage-id="delta"]').click();
  await page.getByText("high 영향", { exact: true }).waitFor();
  await page.getByText(/region_restriction_changed/).waitFor();
  await page.getByText("HTTP 부하", { exact: true }).waitFor();
  await page.screenshot({ path: resolve(output, "03-pipeline.png"), fullPage: true });

  await page.getByRole("link", { name: "알림" }).click();
  await page.getByText("전달 완료", { exact: true }).first().waitFor();
  await page.screenshot({ path: resolve(output, "04-notifications.png"), fullPage: true });

  assert.equal(apiRequests, 0, "static public demo must not call /api/v1");
  assert.deepEqual(errors, []);

  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const mobilePage = await mobile.newPage();
  const mobileErrors = [];
  mobilePage.on("pageerror", (error) => mobileErrors.push(error.message));
  await mobilePage.goto(`${web}/pipeline`);
  await mobilePage.getByRole("heading", { name: "파이프라인을 직접 재생해보세요" }).waitFor();
  assert.equal(
    await mobilePage.evaluate(() => document.documentElement.scrollWidth > innerWidth),
    false,
  );
  assert.deepEqual(mobileErrors, []);
  await mobile.close();

  console.log("static public demo E2E passed: filters, profile gate, detail, pipeline, notifications, mobile");
} finally {
  await context.close();
  await browser.close();
}
