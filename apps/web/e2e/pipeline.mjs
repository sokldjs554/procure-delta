import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const web = process.env.E2E_WEB_URL ?? "http://localhost:13000";
if (!["localhost", "127.0.0.1"].includes(new URL(web).hostname)) {
  throw Error("Pipeline E2E targets local verification only");
}
const output = resolve(root, "artifacts/e2e/pipeline");
mkdirSync(output, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
});

function stageButton(page, id) {
  return page.locator(`button[data-stage-id="${id}"]`);
}

async function openPipeline(context) {
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.setDefaultTimeout(30000);
  await page.goto(`${web}/pipeline`);
  await page
    .getByRole("heading", { name: "파이프라인을 직접 재생해보세요" })
    .waitFor();
  return { page, errors };
}

try {
  const desktop = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  const landing = await desktop.newPage();
  landing.setDefaultTimeout(30000);
  await landing.goto(`${web}/`);
  await landing.locator(".hero h1").waitFor();
  await landing.screenshot({
    path: resolve(output, "landing.png"),
    fullPage: true,
  });
  await landing.close();

  const { page, errors } = await openPipeline(desktop);

  await page.getByRole("button", { name: /정정으로 조건 변경/ }).click();
  await stageButton(page, "delta").waitFor();
  await page.getByRole("button", { name: "재생", exact: true }).click();
  await page
    .locator("button.pipeline-stage.current")
    .filter({ hasText: "Delta" })
    .waitFor({ timeout: 15000 });

  await stageButton(page, "delta").click();
  await page.getByText("high 영향", { exact: true }).waitFor();
  await page.getByText(/region_restriction_changed/).waitFor();
  await page.screenshot({
    path: resolve(output, "pipeline-amendment-delta.png"),
    fullPage: true,
  });

  await stageButton(page, "eligibility").click();
  await page.getByText("참여 불가 · 관련도와 별개", { exact: true }).waitFor();
  await page
    .getByText("필수 조건 불일치는 관련도 점수로 뒤집지 않습니다.", { exact: true })
    .waitFor();

  await page.getByRole("button", { name: /장애와 복구/ }).click();
  await stageButton(page, "collect").waitFor();
  const failureCases = page.locator(".failure-case-list");
  await failureCases.getByText("timeout-recovery", { exact: true }).waitFor();
  await failureCases.getByText("rate-limit-recovery", { exact: true }).waitFor();
  await failureCases.getByText("server-error-terminal", { exact: true }).waitFor();
  await failureCases.getByText("forbidden-not-retried", { exact: true }).waitFor();

  await page.getByRole("link", { name: "평가·한계" }).click();
  await page.getByRole("heading", { name: "추출 경로 비교" }).waitFor();
  const hostedAll = page.locator(".evaluation-route-row").filter({ hasText: "hosted all" });
  await hostedAll.getByText("미실행", { exact: true }).first().waitFor();
  assert.deepEqual(errors, []);
  await desktop.close();

  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const mobileView = await openPipeline(mobile);
  assert.equal(
    await mobileView.page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
    false,
  );
  await mobileView.page.getByRole("button", { name: /정정으로 조건 변경/ }).click();
  await stageButton(mobileView.page, "delta").waitFor();
  await stageButton(mobileView.page, "delta").click();
  await mobileView.page.locator(".stage-inspector").waitFor();
  assert.equal(
    await mobileView.page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
    false,
  );
  assert.deepEqual(mobileView.errors, []);
  await mobile.close();

  const reduced = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    reducedMotion: "reduce",
  });
  const reducedView = await openPipeline(reduced);
  await reducedView.page.getByRole("button", { name: /정정으로 조건 변경/ }).click();
  await stageButton(reducedView.page, "delta").waitFor();
  await reducedView.page.getByRole("button", { name: "재생", exact: true }).click();
  await reducedView.page.waitForTimeout(1200);
  assert.equal(await reducedView.page.locator(".pipeline-stage.current").count(), 1);
  assert.equal(await reducedView.page.locator(".pipeline-stage.complete").count(), 0);
  assert.deepEqual(reducedView.errors, []);
  await reduced.close();

  console.log("pipeline reviewer E2E: desktop, mobile and reduced-motion passed");
} finally {
  await browser.close();
}
