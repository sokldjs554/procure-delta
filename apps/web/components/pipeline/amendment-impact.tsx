import type { PipelineStage } from "../../lib/api";
import { decisionHeadline, stageOutputLayout } from "../../lib/pipeline";
import { describeField, describeValue } from "../../lib/detail-presentation";

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
  if (stage.status === "blocked" || stage.status === "not_run") return null;
  if (stage.id === "delta") {
    const changed = object(stage.output.changed_fields);
    if (!Object.keys(changed).length) return null;
    const reasons = Array.isArray(stage.decision.reason_codes)
      ? stage.decision.reason_codes
      : [];
    return (
      <section className="amendment-impact">
        <header>
          <span className="impact-badge">
            {text(stage.decision.impact)} 영향
          </span>
          <strong>정정 전후 변경</strong>
        </header>
        <div className="impact-change-list">
          {Object.entries(changed).map(([field, value]) => {
            const row = object(value);
            return (
              <article key={field}>
                <b>{describeField(field)}</b>
                <span>{describeValue(row.before, field)}</span>
                <span aria-hidden="true">→</span>
                <span>{describeValue(row.after, field)}</span>
              </article>
            );
          })}
        </div>
        <p className="impact-reasons">
          reason code:{" "}
          {reasons.length ? reasons.map(String).join(" · ") : "없음"}
        </p>
      </section>
    );
  }

  if (stage.id === "eligibility") {
    const layout = stageOutputLayout(stage);
    if (layout === "unavailable") return null;
    if (layout === "single") {
      const hard = Array.isArray(stage.output.hard_failure_codes)
        ? stage.output.hard_failure_codes.map(String)
        : [];
      return (
        <section className="amendment-impact eligibility-single">
          <header>
            <strong>
              {decisionHeadline({
                allows_recommendation: stage.output
                  .allows_recommendation as boolean,
                hard_failure_codes: hard,
              })}
            </strong>
          </header>
          <p>
            {hard.length
              ? `필수 조건 불일치: ${hard.join(", ")}`
              : "필수 조건 불일치 없음"}
          </p>
        </section>
      );
    }
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
              {before.allows_recommendation === true ? "참여 가능" : "참여 불가"}
            </b>
          </article>
          <span aria-hidden="true">→</span>
          <article>
            <small>변경 후 판단</small>
            <b>
              {after.allows_recommendation === true ? "참여 가능" : "참여 불가"}
            </b>
            <p>
              {afterHard.length ? afterHard.join(", ") : "필수 조건 불일치 없음"}
            </p>
          </article>
        </div>
        <p className="honesty">
          필수 조건 불일치는 관련도 점수로 뒤집지 않습니다.
        </p>
      </section>
    );
  }

  if (stage.id === "ranking") {
    const layout = stageOutputLayout(stage);
    if (layout === "unavailable") return null;
    if (layout === "single")
      return (
        <section className="amendment-impact ranking-single">
          <header>
            <strong>
              {stage.output.recommended === true
                ? "추천 가능"
                : "추천하지 않음"}
            </strong>
          </header>
          <p>관련도: {text(stage.output.score)}</p>
        </section>
      );
    const before = object(stage.output.before);
    const after = object(stage.output.after);
    return (
      <section className="amendment-impact">
        <header>
          <strong>정정 전후 관련도와 추천 판단</strong>
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
    if (typeof stage.output.trigger !== "string") return null;
    return (
      <section className="amendment-impact">
        <header>
          <strong>알림 조건 판단</strong>
        </header>
        <p>
          트리거: {text(stage.output.trigger)} · 공개 데모에서는 로컬/합성
          판단만 재생하며 외부 발송을 수행하지 않습니다.
        </p>
      </section>
    );
  }

  return null;
}
