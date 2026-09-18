import assert from "node:assert/strict";
import test from "node:test";
import { staticDemoRequest, staticDocumentUrl } from "../lib/static-demo.ts";

test("static demo serves the core product journey without an API", async () => {
  const actor = await staticDemoRequest("/auth/demo-login", { method: "POST" });
  assert.equal(actor.role, "user");

  const page = await staticDemoRequest("/opportunities?q=AI");
  assert.ok(page.items.length >= 2);
  assert.equal(page.next_cursor, null);

  const detail = await staticDemoRequest(`/opportunities/${page.items[0].id}`);
  assert.equal(detail.id, page.items[0].id);
  assert.ok(detail.versions.length >= 2);
  assert.ok(detail.deltas.items.length >= 1);

  await staticDemoRequest(`/opportunities/${detail.id}/watch`, { method: "POST" });
  const watchlist = await staticDemoRequest("/watchlist");
  assert.ok(watchlist.items.some((item: { id: string }) => item.id === detail.id));

  const profile = await staticDemoRequest("/company-profile");
  assert.equal(profile.synthetic_demo, true);

  const notifications = await staticDemoRequest("/notifications");
  assert.ok(notifications.items.length >= 1);

  const evaluation = await staticDemoRequest("/evaluation/summary");
  assert.equal(evaluation.status, "measured");
  assert.equal(evaluation.synthetic, true);

  assert.equal(staticDocumentUrl("doc-spec"), "#synthetic-document");
});