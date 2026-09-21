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

  assert.equal(staticDocumentUrl("doc-spec"), "#synthetic-document");
});

test("static demo honors full inbox filters and recomputes the eligibility gate after profile edits", async () => {
  const filtered = await staticDemoRequest<{ items: Opportunity[]; next_cursor: string | null }>(
    "/opportunities?buyer=%EC%84%9C%EC%9A%B8%20%EB%94%94%EC%A7%80%ED%84%B8%ED%96%89%EC%A0%95%EC%9B%90&amount_min=250000000&amount_max=300000000",
  );
  assert.deepEqual(filtered.items.map((item) => item.id), ["opp-ai-contact-center"]);

  const original = await staticDemoRequest<Profile>("/company-profile");
  try {
    await staticDemoRequest<Profile>("/company-profile", {
      method: "PATCH",
      body: JSON.stringify({ regions: ["부산"] }),
    });
    const eligible = await staticDemoRequest<{ items: Opportunity[]; next_cursor: string | null }>(
      "/opportunities?eligible_only=true",
    );
    assert.equal(eligible.items.length, 0);
    const detail = await staticDemoRequest<OpportunityDetail>("/opportunities/opp-ai-contact-center");
    assert.equal(detail.eligibility?.eligible, false);
    assert.equal(detail.ranking?.recommended, false);
  } finally {
    await staticDemoRequest<Profile>("/company-profile", {
      method: "PATCH",
      body: JSON.stringify({ regions: original.regions }),
    });
  }
});


test("static operator snapshot does not invent live worker activity", async () => {
  const pipeline = await staticDemoRequest<import("../lib/api.ts").AdminPipeline>(
    "/admin/pipeline",
  );
  assert.equal(pipeline.records_fetched_today, 3);
  assert.equal(pipeline.changed_versions_today, 1);
  assert.equal(pipeline.worker_heartbeat, false);
  assert.equal(pipeline.scheduler_heartbeat, false);
  assert.equal(pipeline.worker_activity, null);
  assert.equal(pipeline.scheduler_activity, null);
});
