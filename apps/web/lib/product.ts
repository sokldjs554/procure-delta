export type DecisionTone = "success" | "danger" | "pending" | "neutral";

type EligibilityLike = { eligible: boolean; hard_failures: { code: string }[]; warnings: unknown[] };

export function buildOpportunityQuery(filters: Record<string, string | boolean | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== "" && value !== undefined) query.set(key, String(value));
  }
  return query.toString();
}

export function describeDecision(status: string, eligibility: EligibilityLike | null) {
  if (status !== "ready") {
    const labels: Record<string, string> = {
      profile_required: "기업 정보 필요",
      missing_version: "공고 버전 준비 중",
      documents_pending: "문서 처리 중",
      future_version: "시행 전 버전",
    };
    return { tone: "pending" as const, label: labels[status] ?? "판단 대기" };
  }
  if (!eligibility) return { tone: "pending" as const, label: "판단 대기" };
  if (eligibility.hard_failures.length) return { tone: "danger" as const, label: "필수 조건 불일치" };
  if (eligibility.warnings.length) return { tone: "pending" as const, label: "확인 필요" };
  return eligibility.eligible
    ? { tone: "success" as const, label: "필수 조건 충족" }
    : { tone: "neutral" as const, label: "참여 비추천" };
}

export function formatMoney(amount: string | null, currency: string) {
  if (amount === null) return "금액 미공개";
  const value = Number(amount);
  if (!Number.isFinite(value)) return `${amount} ${currency}`;
  return new Intl.NumberFormat("ko-KR", { style: "currency", currency, maximumFractionDigits: 20 }).format(value);
}

export function formatDate(value: string | null) {
  return value ? new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "미정";
}

export function appendUniquePage<T extends { id: string }>(current: T[], next: T[]) {
  const seen = new Set(current.map((item) => item.id));
  return [...current, ...next.filter((item) => !seen.has(item.id))];
}

export function getCurrentVersion<T extends { id: string }>(versions: T[], currentId: string | null) {
  return versions.find((version) => version.id === currentId) ?? null;
}

export function opportunityVisitState(changedAt: string | null, lastVisitedAt: string | null) {
  if (!lastVisitedAt) return "new" as const;
  if (changedAt && new Date(changedAt) > new Date(lastVisitedAt)) return "changed" as const;
  return null;
}

export function writableProfile<T extends { id: string; owner_user_id: string }>(profile: T) {
  const writable = { ...profile } as Partial<T>;
  delete writable.id;
  delete writable.owner_user_id;
  return writable;
}
