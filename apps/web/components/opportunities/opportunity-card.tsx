/* eslint-disable react-hooks/set-state-in-effect -- browser visit state is read after hydration */
"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { Opportunity } from "../../lib/api";
import { describeDecision, formatDate, formatMoney, opportunityVisitState } from "../../lib/product";
import { scorePercent } from "../../lib/inbox";

const stages: Record<string, string> = {
  "pre-specification": "사전 규격", tender: "입찰 공고", amendment: "정정 공고", award: "낙찰", contract: "계약",
};
const featureNames: Record<string, string> = {
  capability_overlap: "역량 일치", budget_fit: "예산 적합", recency: "공고 최신성",
  region_fit: "지역 적합", industry_fit: "업종 적합", certification_fit: "인증 적합",
};
export function OpportunityCard({ item, selected = false, onSelect, selectionDisabled = false }: {
  item: Opportunity; selected?: boolean; onSelect?: (id: string) => void; selectionDisabled?: boolean;
}) {
  const decision = describeDecision(item.decision_status, item.eligibility);
  const score = scorePercent(item.ranking);
  const [visit, setVisit] = useState<"new" | "changed" | null>(null);
  useEffect(() => { setVisit(opportunityVisitState(item.changed_at, sessionStorage.getItem("procureDeltaPreviousVisit"))); }, [item.changed_at]);
  const reasons = item.ranking ? Object.entries(item.ranking.features)
    .filter(([, value]) => Number.isFinite(Number(value)))
    .sort((a, b) => Number(b[1]) - Number(a[1])).slice(0, 2) : [];
  return <article className="card opportunity-card">
    <div className="card-top"><div className="card-headline">
      <div className="badges"><span>{stages[item.lifecycle_stage ?? ""] ?? "단계 미분류"}</span>
        {visit && <span className="changed">{visit === "new" ? "새 공고" : "방문 후 변경"}</span>}
        <span className={decision.tone}>{decision.label}</span></div>
      <h2><Link href={`/opportunities/${item.id}`}>{item.title}</Link></h2>
      <p className="muted">{item.buyer_name}</p>
    </div>{score !== null && <div className="score"><strong>{score}</strong><small>관련도 점수</small></div>}</div>
    {reasons.length > 0 && <div className="match-reasons"><b>주요 관련도 요인</b>{reasons.map(([name, value]) =>
      <span key={name}>{featureNames[name] ?? name.replaceAll("_", " ")} {Math.round(Number(value) * 100)}%</span>)}</div>}
    <dl className="facts"><div><dt>예산</dt><dd>{formatMoney(item.estimated_amount, item.currency)}</dd></div>
      <div><dt>마감</dt><dd>{formatDate(item.closes_at)}</dd></div>
      <div><dt>추천 판단</dt><dd>{item.ranking ? (item.ranking.recommended ? "검토 추천" : "추천 기준 미충족") : "평가 대기"}</dd></div></dl>
    {onSelect && <label className="compare-select"><input type="checkbox" checked={selected} disabled={selectionDisabled && !selected} onChange={() => onSelect(item.id)} /> 비교 목록에 담기</label>}
  </article>;
}
