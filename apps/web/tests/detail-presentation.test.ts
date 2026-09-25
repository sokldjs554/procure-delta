import assert from "node:assert/strict";
import test from "node:test";

import {
  describeField,
  describeValue,
  normalizedRows,
  evidenceRows,
  deltaRows,
  documentChangeRows,
  documentLink,
  hasEvaluatedEligibility,
} from "../lib/detail-presentation.ts";

test("normalized summary translates known fields and retains unfamiliar source fields", () => {
  assert.deepEqual(normalizedRows({ estimated_amount: "280000000", required_capabilities: ["LLM", "STT"], custom_field: "원문" }), [
    { key: "estimated_amount", label: "예산", text: "280,000,000 (통화 미확인)" },
    { key: "required_capabilities", label: "필수 기술", text: "LLM · STT" },
    { key: "custom_field", label: "custom field", text: "원문" },
  ]);
  assert.equal(describeField("required_certifications"), "필수 인증");
  assert.equal(describeValue(null), "확인되지 않음");
  assert.equal(describeValue([]), "없음");
});

test("evidence rows preserve an exact quote and its document hash and page", () => {
  assert.deepEqual(evidenceRows({ required_capabilities: [
    { quote: "필수 기술: LLM, STT", page_number: 3, attachment_sha256: "abc123" },
  ] }), [
    { field: "required_capabilities", label: "필수 기술", quote: "필수 기술: LLM, STT", page: "3", attachmentSha: "abc123", source: null },
  ]);
  assert.equal(evidenceRows({ required_capabilities: [{ page: 2 }] }).length, 1);
});

test("delta rows distinguish explicit unknown, absent, and added and removed sets", () => {
  assert.deepEqual(deltaRows({
    region_restriction: { before: null, after: "서울 소재 기업" },
    required_capabilities: { added: ["STT"], removed: ["OCR"] },
    deadline: { after: "2026-10-02" },
  }).map(({ label, before, after }) => ({ label, before, after })), [
    { label: "지역 제한", before: "확인되지 않음", after: "서울 소재 기업" },
    { label: "필수 기술", before: "OCR 제외", after: "STT 추가" },
    { label: "마감일", before: "기록 없음", after: "2026-10-02" },
  ]);
});

test("unexpected delta structures retain a readable fallback without pretending to be a comparison", () => {
  assert.deepEqual(deltaRows({ scope: "updated", regions: { changed: true } }).map(({ before, after }) => ({ before, after })), [
    { before: "기록 없음", after: "updated" },
    { before: "기록 없음", after: "상세 값은 기술 데이터 참조" },
  ]);
});

test("document changes distinguish attachment replacement and compact demo summaries", () => {
  assert.deepEqual(documentChangeRows({ attachments: [
    { kind: "replaced", before: { filename: "요청서.pdf", sha256: "old" }, after: { filename: "요청서_v2.pdf", sha256: "new" } },
  ] }).map(({ kind, before, after }) => ({ kind, before, after })), [
    { kind: "교체", before: "요청서.pdf", after: "요청서_v2.pdf" },
  ]);
  assert.deepEqual(documentChangeRows({ replaced: ["제안요청서_v2.pdf"] }).map(({ kind, after }) => ({ kind, after })), [
    { kind: "교체", after: "제안요청서_v2.pdf" },
  ]);
});

test("budget changes display the provided currency rather than assuming KRW", () => {
  assert.equal(describeValue({ estimated_amount: "1200", currency: "USD" }, "budget"), "$1,200.00");
  assert.equal(normalizedRows({ estimated_amount: "1200", currency: "USD" })[0].text, "$1,200.00");
  assert.equal(deltaRows({ budget: { before: { estimated_amount: "1200", currency: "USD" }, after: { estimated_amount: "1300", currency: "KRW" } } })[0].before, "$1,200.00");
  assert.equal(describeValue("1200", "estimated_amount"), "1,200 (통화 미확인)");
});

test("synthetic document placeholders never produce a working download link", () => {
  assert.deepEqual(documentLink("#synthetic-document"), { href: null, label: "합성 문서 예시 · 실제 파일 없음" });
  assert.deepEqual(documentLink("/api/v1/documents/123/original"), { href: "/api/v1/documents/123/original", label: "인증된 원문 다운로드" });
});

test("fractional budget changes remain visible in the before and after values", () => {
  const [row] = deltaRows({ budget: { before: { estimated_amount: "1200.40", currency: "USD" }, after: { estimated_amount: "1200.49", currency: "USD" } } });
  assert.notEqual(row.before, row.after);
  assert.match(row.before, /1,200\.40/);
  assert.match(row.after, /1,200\.49/);
});

test("eligibility reasons render only when a result was evaluated", () => {
  assert.equal(hasEvaluatedEligibility("documents_pending", { eligible: true }), false);
  assert.equal(hasEvaluatedEligibility("ready", null), false);
  assert.equal(hasEvaluatedEligibility("ready", { eligible: false }), true);
});
