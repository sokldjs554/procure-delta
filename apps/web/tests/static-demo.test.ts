import assert from "node:assert/strict";
import test from "node:test";

import type {
  Actor,
  EvaluationSummary,
  NotificationItem,
  Opportunity,
  OpportunityDetail,
  Profile,
} from "../lib/api.ts";
import { staticDemoRequest, staticDocumentUrl } from "../lib/static-demo.ts";

test("static demo serves the core product journey without an API", async () => {
  await staticDemoRequest("/auth/logout", { method: "POST" });
  const actor = await staticDemoRequest<Actor>("/auth/demo-login", { method: "POST" });
  assert.equal(actor.role, "user");

  const page = await staticDemoRequest<{
    items: Opportunity[];
    next_cursor: string | null;
  }>("/opportunities?q=AI");
  assert.ok(page.items.length >= 2);
  assert.equal(page.next_cursor, null);

  const detail = await staticDemoRequest<OpportunityDetail>(
    `/opportunities/${page.items[0].id}`,
  );
  assert.equal(detail.id, page.items[0].id);
  assert.ok(detail.versions.length >= 2);
  assert.ok(detail.deltas.items.length >= 1);
  assert.equal(detail.timeline.active_links.length, 0);
  assert.equal(detail.eligibility?.warnings.length, 0);
  assert.equal(detail.ranking?.recommended, true);

  await staticDemoRequest(`/opportunities/${detail.id}/watch`, {
    method: "POST",
  });
  const watchlist = await staticDemoRequest<{
    items: Opportunity[];
    next_cursor: string | null;
  }>("/watchlist");
  assert.ok(watchlist.items.some((item) => item.id === detail.id));

  const profile = await staticDemoRequest<Profile>("/company-profile");
  assert.equal(profile.synthetic_demo, true);

  const notifications = await staticDemoRequest<{
    items: NotificationItem[];
    next_cursor: string | null;
  }>("/notifications");
  assert.ok(notifications.items.length >= 1);
  assert.ok(notifications.items.every((item) => item.status === "sent"));

  const evaluation = await staticDemoRequest<EvaluationSummary>("/evaluation/summary");
  assert.equal(evaluation.status, "measured");
  assert.equal(evaluation.synthetic, true);

  assert.equal(staticDocumentUrl("doc-spec"), null);
});

test("static demo applies every visible inbox filter", async () => {
  await staticDemoRequest("/auth/logout", { method: "POST" });

  const buyer = await staticDemoRequest<{ items: Opportunity[] }>(
    "/opportunities?buyer=%EA%B3%B5%EA%B3%B5%EB%8D%B0%EC%9D%B4%ED%84%B0%EC%A7%80%EC%9B%90%EC%9B%90",
  );
  assert.deepEqual(buyer.items.map((item) => item.id), ["opp-ai-document"]);

  const amount = await staticDemoRequest<{ items: Opportunity[] }>(
    "/opportunities?amount_min=400000000",
  );
  assert.deepEqual(amount.items.map((item) => item.id), ["opp-data-platform"]);

  const deadline = await staticDemoRequest<{ items: Opportunity[] }>(
    "/opportunities?deadline_to=2026-09-30T23%3A59%3A59Z",
  );
  assert.deepEqual(deadline.items.map((item) => item.id), ["opp-ai-document"]);

  const changed = await staticDemoRequest<{ items: Opportunity[] }>(
    "/opportunities?changed_since=2026-09-16T12%3A00%3A00Z",
  );
  assert.deepEqual(changed.items.map((item) => item.id), ["opp-data-platform"]);

  const category = await staticDemoRequest<{ items: Opportunity[] }>(
    "/opportunities?category=%EC%9A%A9%EC%97%AD",
  );
  assert.equal(category.items.length, 3);
});

test("static profile changes recalculate the hard gate and logout resets state", async () => {
  await staticDemoRequest("/auth/logout", { method: "POST" });

  const before = await staticDemoRequest<OpportunityDetail>(
    "/opportunities/opp-ai-contact-center",
  );
  assert.equal(before.eligibility?.eligible, true);
  assert.equal(before.ranking?.recommended, true);

  await staticDemoRequest("/company-profile", {
    method: "PATCH",
    body: JSON.stringify({ regions: ["부산"] }),
  });
  const after = await staticDemoRequest<OpportunityDetail>(
    "/opportunities/opp-ai-contact-center",
  );
  assert.equal(after.eligibility?.eligible, false);
  assert.ok(
    after.eligibility?.hard_failures.some(
      (reason) => reason.code === "region_not_served",
    ),
  );
  assert.equal(after.ranking?.recommended, false);

  const eligible = await staticDemoRequest<{ items: Opportunity[] }>(
    "/opportunities?eligible_only=true",
  );
  assert.equal(eligible.items.length, 0);

  await staticDemoRequest("/opportunities/opp-ai-contact-center/watch", {
    method: "DELETE",
  });
  assert.equal(
    (
      await staticDemoRequest<{ items: Opportunity[] }>("/watchlist")
    ).items.some((item) => item.id === "opp-ai-contact-center"),
    false,
  );

  await staticDemoRequest("/auth/logout", { method: "POST" });
  const resetProfile = await staticDemoRequest<Profile>("/company-profile");
  assert.deepEqual(resetProfile.regions, ["서울", "경기"]);
  const resetDetail = await staticDemoRequest<OpportunityDetail>(
    "/opportunities/opp-ai-contact-center",
  );
  assert.equal(resetDetail.eligibility?.eligible, true);
  assert.equal(resetDetail.ranking?.recommended, true);
  assert.equal(
    (
      await staticDemoRequest<{ items: Opportunity[] }>("/watchlist")
    ).items.some((item) => item.id === "opp-ai-contact-center"),
    true,
  );
});
