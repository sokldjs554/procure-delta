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
  ...(process.env.CHROME_PATH
    ? { executablePath: process.env.CHROME_PATH }
    : {}),
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
  const desktop = await browser.newContext({
    viewport: { width: 1440, height: 960 },
  });
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

  await page.getByText("1 / 12 단계", { exact: true }).waitFor();
  await page.getByRole("button", { name: "다음 단계" }).click();
  assert.equal(
    await stageButton(page, "dedupe").getAttribute("aria-pressed"),
    "true",
  );
  await page.getByRole("button", { name: "이전 단계" }).click();
  assert.equal(
    await stageButton(page, "collect").getAttribute("aria-pressed"),
    "true",
  );
  await page.getByLabel("재생 속도").selectOption("1000");
  assert.equal(await page.getByLabel("재생 속도").inputValue(), "1000");

  await page.getByRole("button", { name: /정정으로 조건 변경/ }).click();
  await stageButton(page, "delta").waitFor();
  await page.getByRole("button", { name: "재생", exact: true }).click();
  await page
    .locator("button.pipeline-stage.current")
    .filter({ hasText: "Delta" })
    .waitFor({ timeout: 15000 });

  await stageButton(page, "delta").click();
  assert.equal(
    await page.getByRole("button", { name: "일시정지" }).isDisabled(),
    true,
  );
  await page.getByText("high 영향", { exact: true }).waitFor();
  await page.getByText(/region_restriction_changed/).waitFor();
  const technicalDetails = page.locator("details.pipeline-technical-details");
  await technicalDetails.waitFor();
  assert.equal(await technicalDetails.getAttribute("open"), null);
  await technicalDetails.locator("summary").click();
  assert.notEqual(await technicalDetails.getAttribute("open"), null);
  await technicalDetails
    .getByRole("tab", { name: "출력", exact: true })
    .waitFor();
  await technicalDetails.locator("summary").click();
  assert.equal(await technicalDetails.getAttribute("open"), null);
  await page.screenshot({
    path: resolve(output, "pipeline-amendment-delta.png"),
    fullPage: true,
  });

  await stageButton(page, "eligibility").click();
  await page.getByText("참여 불가 · 관련도와 별개", { exact: true }).waitFor();
  await page
    .getByText("필수 조건 불일치는 관련도 점수로 뒤집지 않습니다.", {
      exact: true,
    })
    .waitFor();

  await page.getByRole("button", { name: /장애와 복구/ }).click();
  await stageButton(page, "collect").waitFor();
  const failureCases = page.locator(".failure-case-list");
  await failureCases.getByText("timeout-recovery", { exact: true }).waitFor();
  await failureCases
    .getByText("rate-limit-recovery", { exact: true })
    .waitFor();
  await failureCases
    .getByText("server-error-terminal", { exact: true })
    .waitFor();
  await failureCases
    .getByText("forbidden-not-retried", { exact: true })
    .waitFor();
  await stageButton(page, "eligibility").click();
  assert.equal(
    await page.locator(".eligibility-compare, .eligibility-single").count(),
    0,
  );
  await page
    .getByText(/후속 처리를 실행하지 않습니다/)
    .first()
    .waitFor();
  await page.getByRole("button", { name: /신규 공고/ }).click();
  await stageButton(page, "eligibility").click();
  assert.match(
    await page.locator(".stage-result").innerText(),
    /참여 가능 · 필수 조건 불일치 없음/,
  );
  assert.equal(await page.locator(".eligibility-compare").count(), 0);
  await stageButton(page, "ranking").click();
  const scenarioResponse = await desktop.request.get(`${web}/api/v1/demo/pipeline/scenarios/new-opportunity`);
  assert.equal(scenarioResponse.status(), 200);
  const measuredScenario = await scenarioResponse.json();
  const ranking = measuredScenario.stages.find(stage => stage.id === "ranking").output;
  assert.ok(Number.isFinite(Number(ranking.score)));
  assert.ok((await page.locator(".stage-result").innerText()).includes(`관련도 ${ranking.score} · ${ranking.recommended ? "추천 가능" : "추천 안 함"}`));
  assert.equal(await page.locator(".ranking-compare").count(), 0);

  await page.getByRole("link", { name: "평가·한계" }).click();
  await page.getByRole("heading", { name: "추출 경로 비교" }).waitFor();
  const hostedAll = page
    .locator(".evaluation-route-row")
    .filter({ hasText: "hosted all" });
  await hostedAll.getByText("과거 측정", { exact: true }).waitFor();
  assert.equal(await hostedAll.getByText("측정됨", { exact: true }).count(), 0);
  await page.getByText("현재 계약 미측정", { exact: true }).waitFor();
  await hostedAll.getByText("100.0%", { exact: true }).waitFor();
  const hostedEvidence = page.getByLabel("외부 Claude 실측");
  await hostedEvidence.getByText(/22,343 → 10,149/).waitFor();
  await hostedEvidence.getByText(/54.6% 감소/).waitFor();
  await hostedEvidence.getByText(/로컬 규칙 처리 5건/).waitFor();
  await page.screenshot({
    path: resolve(output, "hosted-evidence-desktop.png"),
    fullPage: true,
  });
  assert.deepEqual(errors, []);
  await desktop.close();

  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  const mobileView = await openPipeline(mobile);
  await mobileView.page.goto(`${web}/about`);
  await mobileView.page.getByText("현재 계약 미측정", { exact: true }).waitFor();
  await mobileView.page
    .getByLabel("외부 Claude 실측")
    .getByText(/22,343 → 10,149/)
    .waitFor();
  assert.equal(
    await mobileView.page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  await mobileView.page.screenshot({
    path: resolve(output, "hosted-evidence-mobile.png"),
    fullPage: true,
  });
  await mobileView.page.goto(`${web}/pipeline`);
  await mobileView.page
    .getByRole("heading", { name: "파이프라인을 직접 재생해보세요" })
    .waitFor();
  assert.equal(
    await mobileView.page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  await mobileView.page
    .getByRole("button", { name: /정정으로 조건 변경/ })
    .click();
  await stageButton(mobileView.page, "delta").waitFor();
  await stageButton(mobileView.page, "delta").click();
  await mobileView.page.locator(".stage-inspector").waitFor();
  assert.equal(
    await mobileView.page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  assert.deepEqual(mobileView.errors, []);
  await mobile.close();

  const reduced = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    reducedMotion: "reduce",
  });
  const reducedView = await openPipeline(reduced);
  await reducedView.page
    .getByRole("button", { name: /정정으로 조건 변경/ })
    .click();
  await stageButton(reducedView.page, "delta").waitFor();
  await reducedView.page
    .getByRole("button", { name: "재생", exact: true })
    .click();
  await reducedView.page.waitForTimeout(1200);
  assert.equal(
    await reducedView.page.locator(".pipeline-stage.current").count(),
    1,
  );
  assert.equal(
    await reducedView.page.locator(".pipeline-stage.complete").count(),
    0,
  );
  assert.deepEqual(reducedView.errors, []);
  await reduced.close();

  console.log(
    "pipeline reviewer E2E: desktop, mobile and reduced-motion passed",
  );
} finally {
  await browser.close();
}
