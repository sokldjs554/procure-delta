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
  assert.equal(evaluation.routes.hosted_all.field_accuracy, 0.6);
  assert.equal(evaluation.hosted_optimization.all_tokens, 15654);
  assert.equal(evaluation.hosted_optimization.gated_tokens, 7317);
  assert.equal(evaluation.hosted_optimization.reported_cost_reduction_rate, null);
  assert.match(evaluation.routes.hosted_gated.notice ?? "", /로컬 규칙/);

  assert.equal(staticDocumentUrl("doc-spec"), "#synthetic-document");
});
