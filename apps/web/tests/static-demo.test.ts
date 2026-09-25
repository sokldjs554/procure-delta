import assert from "node:assert/strict";
import test from "node:test";
import { staticDemoRequest, staticDocumentUrl } from "../lib/static-demo.ts";
import type { Actor, EvaluationSummary, NotificationItem, Opportunity, OpportunityDetail, Profile } from "../lib/api.ts";

test("static demo serves the core product journey without an API", async () => {
  const actor = await staticDemoRequest<Actor>("/auth/demo-login", { method: "POST" });
  assert.equal(actor.role, "user");

  const page = await staticDemoRequest<{ items: Opportunity[]; next_cursor: string | null }>("/opportunities?q=AI");
  assert.ok(page.items.length >= 2);
  assert.equal(page.next_cursor, null);

  const detail = await staticDemoRequest<OpportunityDetail>(`/opportunities/${page.items[0].id}`);
  assert.equal(detail.id, page.items[0].id);
  assert.ok(detail.versions.length >= 2);
  assert.ok(detail.deltas.items.length >= 1);

  await staticDemoRequest(`/opportunities/${detail.id}/watch`, { method: "POST" });
  const watchlist = await staticDemoRequest<{ items: Opportunity[]; next_cursor: string | null }>("/watchlist");
  assert.ok(watchlist.items.some((item: { id: string }) => item.id === detail.id));

  const profile = await staticDemoRequest<Profile>("/company-profile");
  assert.equal(profile.synthetic_demo, true);

  const notifications = await staticDemoRequest<{ items: NotificationItem[]; next_cursor: string | null }>("/notifications");
  assert.ok(notifications.items.length >= 1);

  const evaluation = await staticDemoRequest<EvaluationSummary>("/evaluation/summary");
  assert.equal(evaluation.status, "measured");
  assert.equal(evaluation.synthetic, true);
  assert.equal(evaluation.routes.ocr_korean.status, "measured");
  assert.equal(evaluation.routes.ocr_korean.support, 18);
  assert.equal(evaluation.routes.ocr_korean.field_accuracy, 1);
  assert.equal(evaluation.routes.ocr_korean.language, "kor+eng");
  assert.equal(evaluation.hosted_evaluated, true);
  assert.equal(evaluation.routes.hosted_all.field_accuracy, 1);
  assert.equal(evaluation.hosted_optimization.all_tokens, 22343);
  assert.equal(evaluation.hosted_optimization.gated_tokens, 10149);
  assert.equal(evaluation.hosted_optimization.reported_cost_reduction_rate, null);
  assert.match(evaluation.routes.hosted_gated.notice ?? "", /로컬 규칙/);

  assert.equal(staticDocumentUrl("doc-spec"), "#synthetic-document");
});

test("static inbox applies buyer, category, amount and date filters instead of ignoring them", async () => {
  const cases: [string, string[]][] = [
    ["buyer=공공데이터", ["opp-ai-document"]],
    ["category=물품", []],
    ["amount_min=200000000&amount_max=300000000", ["opp-ai-contact-center"]],
    ["deadline_to=2026-09-30T00:00:00Z", ["opp-ai-document"]],
    ["deadline_from=2026-10-03T00:00:00Z", ["opp-data-platform"]],
    ["changed_since=2026-09-16T23:00:00Z", ["opp-data-platform"]],
    ["q=AI&buyer=공공데이터&amount_max=200000000", ["opp-ai-document"]],
  ];
  for (const [query, expected] of cases) {
    const result = await staticDemoRequest<{ items: Opportunity[] }>(`/opportunities?${query}`);
    assert.deepEqual(result.items.map(item => item.id), expected, query);
  }
});

test("static inbox rejects malformed filter values rather than silently broadening results", async () => {
  for (const query of ["amount_min=nope", "amount_min=-1", "amount_min=3&amount_max=2", "deadline_from=not-a-date", "deadline_from=2026-10-02&deadline_to=2026-09-01"]) {
    await assert.rejects(staticDemoRequest(`/opportunities?${query}`), /필터/);
  }
});
