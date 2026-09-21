/* eslint-disable react-hooks/set-state-in-effect -- browser visit state is read after hydration */
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { Opportunity } from "../../lib/api";
import {
  describeDecision,
  formatDate,
  formatMoney,
  opportunityVisitState,
} from "../../lib/product";

export function OpportunityCard({ item }: { item: Opportunity }) {
  const decision = describeDecision(item.decision_status, item.eligibility);
  const score = item.ranking
    ? Math.round(Number(item.ranking.final_score) * 100)
    : null;
  const [visit, setVisit] = useState<"new" | "changed" | null>(null);

  useEffect(() => {
    setVisit(
      opportunityVisitState(
        item.changed_at,
        sessionStorage.getItem("procureDeltaPreviousVisit"),
      ),
    );
  }, [item.changed_at]);

  const reasons = item.ranking
    ? Object.entries(item.ranking.features)
        .sort((a, b) => Number(b[1]) - Number(a[1]))
        .slice(0, 2)
    : [];

  return (
    <article className="card">
      <div className="card-top">
        <div>
          <div className="badges">
            <span>{item.lifecycle_stage ?? "단계 미분류"}</span>
            {visit && (
              <span className="changed">
                {visit === "new" ? "새 공고" : "방문 후 변경"}
              </span>
            )}
            <span className={decision.tone}>{decision.label}</span>
          </div>
          <h2>
            <Link href={`/opportunities/${item.id}`}>{item.title}</Link>
          </h2>
          <p className="muted">{item.buyer_name}</p>
        </div>
        {score !== null && (
          <div className="score">
            <strong>{score}</strong>
            <small>관련도</small>
          </div>
        )}
      </div>

      {reasons.length > 0 && (
        <div className="match-reasons">
          <b>주요 관련도 요인</b>
          {reasons.map(([name, value]) => (
            <span key={name}>
              {name} {Number(value).toFixed(2)}
            </span>
          ))}
        </div>
      )}

      <dl className="facts">
        <div>
          <dt>예산</dt>
          <dd>{formatMoney(item.estimated_amount, item.currency)}</dd>
        </div>
        <div>
          <dt>마감</dt>
          <dd>{formatDate(item.closes_at)}</dd>
        </div>
        <div>
          <dt>추천</dt>
          <dd>
            {item.ranking?.recommended ? "검토 추천" : "추천 기준 미충족"}
          </dd>
        </div>
      </dl>
    </article>
  );
}
