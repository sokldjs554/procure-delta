import assert from "node:assert/strict";
import test from "node:test";

import { appendUniquePage, buildOpportunityQuery, describeDecision, formatMoney, getCurrentVersion, opportunityVisitState, writableProfile } from "../lib/product.ts";

test("buildOpportunityQuery excludes empty filters and serializes booleans", () => {
  assert.equal(
    buildOpportunityQuery({ q: "드론", buyer: "", eligible_only: true, amount_min: "1000000" }),
    "q=%EB%93%9C%EB%A1%A0&eligible_only=true&amount_min=1000000",
  );
});

test("decision copy keeps pending and hard failures distinct", () => {
  assert.deepEqual(describeDecision("documents_pending", null), {
    tone: "pending",
    label: "문서 처리 중",
  });
  assert.deepEqual(
    describeDecision("ready", { eligible: false, hard_failures: [{ code: "region" }], warnings: [] }),
    { tone: "danger", label: "필수 조건 불일치" },
  );
});

test("formatMoney handles unknown amounts without inventing a value", () => {
  assert.equal(formatMoney(null, "KRW"), "금액 미공개");
  assert.equal(formatMoney("125000000", "KRW"), "₩125,000,000");
});

test("money displays retain fractional changes rather than rounding them away", () => {
  assert.notEqual(formatMoney("1200.40", "USD"), formatMoney("1200.49", "USD"));
  assert.match(formatMoney("1200.125", "USD"), /1,200\.125/);
});

test("appendUniquePage keeps order while removing repeated cursor-boundary rows", () => {
  const current = [{ id: "a" }, { id: "b" }];
  const next = [{ id: "b" }, { id: "c" }];
  assert.deepEqual(appendUniquePage(current, next), [{ id: "a" }, { id: "b" }, { id: "c" }]);
});

test("writableProfile removes server-owned fields", () => {
  const value = writableProfile({ id:"profile", owner_user_id:"owner", display_name:"Demo", synthetic_demo:true, regions:[], industries:[], capabilities:[], certifications:[], employee_band:null, min_contract_amount:null, max_contract_amount:null, contract_currency:"KRW", excluded_keywords:[] });
  assert.equal("id" in value, false); assert.equal("owner_user_id" in value, false); assert.equal(value.display_name,"Demo");
});

test("getCurrentVersion follows current_version_id rather than array position", () => {
  const versions=[{id:"current",version_number:3},{id:"old",version_number:1}];
  assert.equal(getCurrentVersion(versions,"current")?.version_number,3);
});

test("visit state distinguishes unseen and changed opportunities", () => {
  assert.equal(opportunityVisitState("2026-09-16T10:00:00Z",null),"new");
  assert.equal(opportunityVisitState("2026-09-16T10:00:00Z","2026-09-16T09:00:00Z"),"changed");
  assert.equal(opportunityVisitState("2026-09-16T10:00:00Z","2026-09-16T11:00:00Z"),null);
});
