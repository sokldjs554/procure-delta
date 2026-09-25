import type { JsonValue } from "./api";

export type DisplayRow = { key: string; label: string; text: string };
export type EvidenceRow = { field: string; label: string; quote: string | null; page: string | null; attachmentSha: string | null; source: string | null };
export type DeltaRow = { key: string; label: string; before: string; after: string; beforeEvidence: JsonValue; afterEvidence: JsonValue };
export type DocumentChangeRow = { kind: string; before: string; after: string; beforeSha: string | null; afterSha: string | null };
export function documentLink(url: string): { href: string | null; label: string } {
  return url.startsWith("#")
    ? { href: null, label: "합성 문서 예시 · 실제 파일 없음" }
    : { href: url, label: "인증된 원문 다운로드" };
}
export function hasEvaluatedEligibility(status: string, eligibility: { eligible: boolean } | null): boolean {
  return status === "ready" && eligibility !== null;
}

const labels: Record<string, string> = {
  title: "공고명", buyer_name: "발주 기관", procurement_type: "계약 유형",
  lifecycle_stage: "공고 단계", estimated_amount: "예산", currency: "통화",
  closes_at: "마감일", deadline: "마감일", published_at: "게시일",
  budget: "예산", regions: "참여 가능 지역", region_restriction: "지역 제한",
  required_certifications: "필수 인증", required_capabilities: "필수 기술",
  participation_constraints: "참여 조건", contract_period: "계약 기간",
};

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function describeField(key: string): string {
  return labels[key] ?? key.replaceAll("_", " ");
}

function formatAmount(value: unknown, currency: unknown): string {
  const amount = Number(value);
  if (!Number.isFinite(amount) || value === "") return String(value);
  const code = str(currency);
  if (code) {
    try {
      return new Intl.NumberFormat(code === "KRW" ? "ko-KR" : "en-US", {
        style: "currency", currency: code, maximumFractionDigits: 20,
      }).format(amount);
    } catch { return `${new Intl.NumberFormat("ko-KR").format(amount)} ${code}`; }
  }
  return `${new Intl.NumberFormat("ko-KR").format(amount)} (통화 미확인)`;
}

export function describeValue(value: unknown, field?: string, currency?: unknown): string {
  if (value === null || value === undefined) return "확인되지 않음";
  if (Array.isArray(value)) return value.length ? value.map((item) => describeValue(item)).join(" · ") : "없음";
  const valueRecord = record(value);
  if (valueRecord) {
    if ("estimated_amount" in valueRecord && "currency" in valueRecord) {
      return valueRecord.estimated_amount == null
        ? "확인되지 않음"
        : formatAmount(valueRecord.estimated_amount, valueRecord.currency);
    }
    return "상세 값은 기술 데이터 참조";
  }
  if (field === "estimated_amount" && Number.isFinite(Number(value)) && value !== "") {
    return formatAmount(value, currency);
  }
  if (typeof value === "boolean") return value ? "예" : "아니오";
  return String(value);
}

export function normalizedRows(value: JsonValue): DisplayRow[] {
  const fields = record(value);
  return fields ? Object.entries(fields).map(([key, item]) => ({
    key, label: describeField(key), text: describeValue(item, key, fields.currency),
  })) : [];
}

export function evidenceRows(value: JsonValue): EvidenceRow[] {
  const fields = record(value);
  if (!fields) return [];
  return Object.entries(fields).flatMap(([field, entries]) =>
    (Array.isArray(entries) ? entries : [entries]).map((entry) => {
      const item = record(entry);
      return {
        field, label: describeField(field), quote: str(item?.quote),
        page: item?.page_number != null ? String(item.page_number) : item?.page != null ? String(item.page) : null,
        attachmentSha: str(item?.attachment_sha256) ?? str(item?.sha256),
        source: str(item?.source) ?? str(item?.source_record_id),
      };
    }),
  );
}

export function deltaRows(value: JsonValue): DeltaRow[] {
  const fields = record(value);
  if (!fields) return [];
  return Object.entries(fields).map(([key, raw]) => {
    const change = record(raw);
    const before = change && "before" in change ? describeValue(change.before, key) :
      change && Array.isArray(change.removed) ? `${describeValue(change.removed, key)} 제외` : "기록 없음";
    const after = change && "after" in change ? describeValue(change.after, key) :
      change && Array.isArray(change.added) ? `${describeValue(change.added, key)} 추가` : describeValue(raw, key);
    return {
      key, label: describeField(key), before, after,
      beforeEvidence: (change?.before_evidence ?? []) as JsonValue,
      afterEvidence: (change?.after_evidence ?? []) as JsonValue,
    };
  });
}

export function documentChangeRows(value: JsonValue): DocumentChangeRow[] {
  const data = record(value);
  if (!data) return [];
  const changes = Array.isArray(data.attachments) ? data.attachments :
    Object.entries(data).flatMap(([kind, values]) =>
      Array.isArray(values) ? values.map((item) => ({ kind, after: item })) : [],
    );
  return changes.map((raw) => {
    const entry = record(raw);
    const previous = record(entry?.before);
    const next = record(entry?.after);
    const kind = entry?.kind === "added" ? "추가" : entry?.kind === "removed" ? "제거" : entry?.kind === "replaced" ? "교체" : describeValue(entry?.kind);
    return {
      kind,
      before: previous ? str(previous.filename) ?? str(previous.source_url) ?? "파일명 없음" : "기록 없음",
      after: next ? str(next.filename) ?? str(next.source_url) ?? "파일명 없음" : entry?.after ? describeValue(entry.after) : "기록 없음",
      beforeSha: str(previous?.sha256), afterSha: str(next?.sha256),
    };
  });
}
