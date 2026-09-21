import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const web = process.env.E2E_STATIC_WEB_URL ?? "http://localhost:13001";
if (!["localhost", "127.0.0.1"].includes(new URL(web).hostname)) {
  throw Error("Static demo E2E targets local verification only");
}
const output = resolve(root, "artifacts/e2e/static");
mkdirSync(output, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
});

async function openPage(context, path) {
  const page = await context.newPage();
  const errors = [];
  const apiRequests = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/v1/")) {
      apiRequests.push(request.url());
    }
  });
  page.setDefaultTimeout(30000);
  await page.goto(`${web}${path}`);
  return { page, errors, apiRequests };
}

try {
  const desktop = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  const view = await openPage(desktop, "/inbox");
  await view.page.getByRole("heading", { name: "공고함", exact: true }).waitFor();
  assert.equal(await view.page.locator(".card").count(), 3);

  await view.page.getByLabel("발주기관").fill("공공데이터지원원");
  await view.page.getByRole("button", { name: "필터 적용", exact: true }).click();
  await view.page.getByText("AI 문서분류·OCR 자동화 플랫폼 고도화", { exact: true }).waitFor();
  assert.equal(await view.page.locator(".card").count(), 1);

  await view.page.getByRole("link", { name: "기업 프로필", exact: true }).click();
  await view.page.getByLabel("활동 지역").fill("부산");
  await view.page.getByRole("button", { name: "변경 저장", exact: true }).click();
  await view.page.getByText(/필수 조건 게이트를 현재 프로필로 다시 계산/).waitFor();

  await view.page.goto(`${web}/opportunities/opp-ai-contact-center`);
  await view.page.getByText("필수 조건 불일치", { exact: true }).first().waitFor();
  await view.page.getByText("추천 기준 미충족", { exact: true }).waitFor();
  assert.equal(
    await view.page.getByRole("link", { name: "인증된 원문 다운로드" }).count(),
    0,
  );
  await view.page
    .getByText("합성 static 데모에서는 원문 파일 다운로드를 제공하지 않습니다.")
    .waitFor();

  await view.page.getByRole("link", { name: "파이프라인", exact: true }).click();
  await view.page.getByRole("button", { name: /정정으로 조건 변경/ }).click();
  await view.page.locator('button[data-stage-id="delta"]').click();
  await view.page.getByText("high 영향", { exact: true }).waitFor();
  await view.page.screenshot({
    path: resolve(output, "pipeline.png"),
    fullPage: true,
  });

  assert.deepEqual(view.apiRequests, []);
  assert.deepEqual(view.errors, []);

  await view.page.getByRole("button", { name: "데모 종료", exact: true }).click();
  await view.page.getByRole("link", { name: "제품 둘러보기", exact: true }).click();
  await view.page.getByRole("link", { name: "기업 프로필", exact: true }).click();
  assert.equal(await view.page.getByLabel("활동 지역").inputValue(), "서울, 경기");
  await desktop.close();

  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const mobileView = await openPage(mobile, "/opportunities/opp-ai-contact-center");
  await mobileView.page.locator(".detail-head h1").waitFor();
  assert.equal(
    await mobileView.page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
    false,
  );
  const nestedValue = mobileView.page.locator(".json .json dd").first();
  if (await nestedValue.count()) {
    const box = await nestedValue.boundingBox();
    assert.ok(box && box.width >= 80, "nested evidence values must remain readable");
  }
  assert.deepEqual(mobileView.apiRequests, []);
  assert.deepEqual(mobileView.errors, []);
  await mobile.close();

  console.log("static demo E2E: filters, profile gate, detail, pipeline, reset and mobile passed");
} finally {
  await browser.close();
}
