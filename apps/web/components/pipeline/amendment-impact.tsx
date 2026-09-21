import type { PipelineStage } from "../../lib/api";
import { decisionHeadline } from "../../lib/pipeline";

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function text(value: unknown) {
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return value === null || value === undefined ? "없음" : String(value);
}

export function AmendmentImpact({ stage }: { stage: PipelineStage }) {
  if (stage.id === "delta") {
    const changed = object(stage.output.changed_fields);
    const reasons = Array.isArray(stage.decision.reason_codes)
      ? stage.decision.reason_codes
      : [];
    return (
      <section className="amendment-impact">
        <header>
          <span className="impact-badge">{text(stage.decision.impact)} 영향</span>
          <strong>정정 전후 변경</strong>
        </header>
        <div className="impact-change-list">
          {Object.entries(changed).map(([field, value]) => {
            const row = object(value);
            return (
              <article key={field}>
                <b>{field}</b>
                <span>{text(row.before)}</span>
                <span aria-hidden="true">→</span>
                <span>{text(row.after)}</span>
              </article>
            );
          })}
        </div>
        <p className="impact-reasons">
          reason code: {reasons.length ? reasons.map(String).join(" · ") : "없음"}
        </p>
      </section>
    );
  }

  if (stage.id === "eligibility") {
    const before = object(stage.output.before);
    const after = object(stage.output.after);
    const afterHard = Array.isArray(after.hard_failure_codes)
      ? after.hard_failure_codes.map(String)
      : [];
    const headline = decisionHeadline({
      allows_recommendation:
        typeof after.allows_recommendation === "boolean"
          ? after.allows_recommendation
          : undefined,
      hard_failure_codes: afterHard,
    });
    return (
      <section className="amendment-impact">
        <header>
          <strong>{headline}</strong>
        </header>
        <div className="eligibility-compare">
          <article>
            <small>이전 판단</small>
            <b>
              {before.allows_recommendation === true ? "참여 가능" : "확인 필요"}
            </b>
          </article>
          <span aria-hidden="true">→</span>
          <article>
            <small>변경 후 판단</small>
            <b>{after.allows_recommendation === false ? "참여 불가" : "참여 가능"}</b>
            <p>{afterHard.length ? afterHard.join(", ") : "hard failure 없음"}</p>
          </article>
        </div>
        <p className="honesty">
          필수 조건 불일치는 관련도 점수로 뒤집지 않습니다.
        </p>
      </section>
    );
  }

  if (stage.id === "ranking") {
    const before = object(stage.output.before);
    const after = object(stage.output.after);
    return (
      <section className="amendment-impact">
        <header>
          <strong>관련도는 유지돼도 추천은 차단됩니다</strong>
        </header>
        <div className="ranking-compare">
          <article>
            <small>이전</small>
            <b>{text(before.score)}</b>
            <span>{before.recommended === true ? "추천" : "미추천"}</span>
          </article>
          <article>
            <small>변경 후</small>
            <b>{text(after.score)}</b>
            <span>{after.recommended === true ? "추천" : "미추천"}</span>
          </article>
        </div>
      </section>
    );
  }

  if (stage.id === "notification") {
    return (
      <section className="amendment-impact">
        <header>
          <strong>watched material change → notification decision</strong>
        </header>
        <p>
          트리거: {text(stage.output.trigger)} · 공개 데모에서는 로컬/합성 판단만
          재생하며 외부 발송을 수행하지 않습니다.
        </p>
      </section>
    );
  }

  return null;
}
