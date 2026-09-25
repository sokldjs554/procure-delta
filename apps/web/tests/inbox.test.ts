import assert from "node:assert/strict";
import test from "node:test";
import type { Opportunity } from "../lib/api.ts";
import { filterInbox, scorePercent, sortInbox, toggleComparison, type InboxView } from "../lib/inbox.ts";

const base: Opportunity = {
  id: "base", title: "기본 공고", buyer_name: "시청", procurement_type: null,
  lifecycle_stage: "tender", estimated_amount: "100", currency: "KRW",
  published_at: null, closes_at: "2026-10-01T00:00:00Z", status: null,
  current_version_id: "v1", watched: false, changed_at: null,
  decision_status: "ready", eligibility: {
    id: "e", eligible: true, hard_failures: [], warnings: [], ruleset_version: "v1",
  },
  ranking: {
    id: "r", recommended: true, final_score: "0.8", features: {}, explanation: null,
    as_of: "2026-09-25T00:00:00Z", evaluation_epoch: "e", ranking_version: "v1",
  },
};
const opportunity = (id: string, overrides: Partial<Opportunity> = {}): Opportunity => ({ ...base, id, ...overrides });

test("strict eligible excludes warnings, hard failures and pending decisions", () => {
  const rows = [
    opportunity("strict"),
    opportunity("warning", { eligibility: { ...base.eligibility!, warnings: [{ code: "review", field: "f", message: "review", evidence: [] }] } }),
    opportunity("failed", { eligibility: { ...base.eligibility!, eligible: false, hard_failures: [{ code: "fail", field: "f", message: "fail", evidence: [] }] } }),
    opportunity("failed-with-warning", { eligibility: { ...base.eligibility!, eligible: false, hard_failures: [{ code: "fail", field: "f", message: "fail", evidence: [] }], warnings: [{ code: "review", field: "f", message: "review", evidence: [] }] } }),
    opportunity("pending", { decision_status: "documents_pending" }),
  ];
  assert.deepEqual(filterInbox(rows, "strict").map(item => item.id), ["strict"]);
  assert.deepEqual(filterInbox(rows, "review").map(item => item.id), ["warning", "pending"]);
});

test("quick view amendment is a loaded-item stage filter and all leaves data intact", () => {
  const rows = [opportunity("normal"), opportunity("changed", { lifecycle_stage: "amendment" })];
  assert.deepEqual(filterInbox(rows, "amendment").map(item => item.id), ["changed"]);
  assert.deepEqual(filterInbox(rows, "all" as InboxView).map(item => item.id), ["normal", "changed"]);
});

test("recommendation sort preserves unknown scores last without inventing eligibility", () => {
  const rows = [
    opportunity("unknown", { ranking: null }),
    opportunity("unrecommended", { ranking: { ...base.ranking!, recommended: false, final_score: "0.99" } }),
    opportunity("recommended", { ranking: { ...base.ranking!, final_score: "0.55" } }),
  ];
  assert.deepEqual(sortInbox(rows, "recommendation").map(item => item.id), ["recommended", "unrecommended", "unknown"]);
  assert.deepEqual(rows.map(item => item.id), ["unknown", "unrecommended", "recommended"]);
});

test("deadline sort moves null and invalid dates last", () => {
  const rows = [
    opportunity("unknown", { closes_at: null }), opportunity("later", { closes_at: "2026-11-01T00:00:00Z" }),
    opportunity("invalid", { closes_at: "not-a-date" }), opportunity("soon", { closes_at: "2026-09-26T00:00:00Z" }),
  ];
  assert.deepEqual(sortInbox(rows, "deadline").map(item => item.id), ["soon", "later", "unknown", "invalid"]);
});

test("budget sort groups currencies and puts unknown amounts last", () => {
  const rows = [
    opportunity("krw-low", { estimated_amount: "100" }),
    opportunity("usd-low", { currency: "USD", estimated_amount: "20" }),
    opportunity("krw-high", { estimated_amount: "500" }),
    opportunity("usd-high", { currency: "USD", estimated_amount: "40" }),
    opportunity("unknown", { estimated_amount: null }),
  ];
  assert.deepEqual(sortInbox(rows, "budget").map(item => item.id), ["krw-high", "krw-low", "usd-high", "usd-low", "unknown"]);
});

test("comparison toggle caps at three, deselects, and ignores unavailable IDs", () => {
  const available = ["a", "b", "c", "d"];
  assert.deepEqual(toggleComparison(["a", "b", "c"], "d", available), ["a", "b", "c"]);
  assert.deepEqual(toggleComparison(["a", "b"], "missing", available), ["a", "b"]);
  assert.deepEqual(toggleComparison(["a", "b"], "a", available), ["b"]);
  assert.deepEqual(toggleComparison(["a", "b"], "c", available), ["a", "b", "c"]);
});

test("display score distinguishes zero from missing and malformed ranking values", () => {
  assert.equal(scorePercent(base.ranking), 80);
  assert.equal(scorePercent({ ...base.ranking!, final_score: "0" }), 0);
  assert.equal(scorePercent({ ...base.ranking!, final_score: "" }), null);
  assert.equal(scorePercent({ ...base.ranking!, final_score: "n/a" }), null);
  assert.equal(scorePercent(null), null);
});
