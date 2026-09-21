/* eslint-disable react-hooks/set-state-in-effect, react-hooks/exhaustive-deps -- route changes synchronously clear stale detail state */
"use client";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useParams } from "next/navigation";
import {
  documentUrl,
  getOpportunity,
  setWatch,
  type Link as LifecycleLink,
  type OpportunityDetail,
} from "../../../../lib/api";
import {
  describeDecision,
  formatDate,
  formatMoney,
  getCurrentVersion,
} from "../../../../lib/product";
import { JsonView } from "../../../../components/json-view";
export default function Detail() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<OpportunityDetail | null>(null),
    [error, setError] = useState(""),
    [actionError, setActionError] = useState(""),
    [busy, setBusy] = useState(false),
    [reload, setReload] = useState(0);
  const requestId = useRef(0);
  useEffect(() => {
    const request = ++requestId.current;
    setData(null);
    setError("");
    setActionError("");
    setBusy(false);
    getOpportunity(id)
      .then((value) => {
        if (request === requestId.current) setData(value);
      })
      .catch((e: Error) => {
        if (request === requestId.current) setError(e.message);
      });
    return () => {
      requestId.current++;
    };
  }, [id, reload]);
  if (error)
    return (
      <main className="state error">
        <h1>공고를 불러오지 못했습니다</h1>
        <p>{error}</p>
        <button onClick={() => setReload((value) => value + 1)}>
          다시 시도
        </button>
      </main>
    );
  if (!data)
    return (
      <main className="state">
        <span className="spinner" />
        공고와 근거를 불러오는 중입니다.
      </main>
    );
  const decision = describeDecision(data.decision_status, data.eligibility),
    current = getCurrentVersion(data.versions, data.current_version_id);
  async function toggle() {
    const request = requestId.current;
    const opportunityId = data!.id;
    const watched = !data!.watched;
    setBusy(true);
    setActionError("");
    try {
      await setWatch(opportunityId, watched);
      if (request === requestId.current && id === opportunityId) {
        setData((currentData) =>
          currentData?.id === opportunityId ? { ...currentData, watched } : currentData,
        );
      }
    } catch (e) {
      if (request === requestId.current && id === opportunityId) {
        setActionError((e as Error).message);
      }
    } finally {
      if (request === requestId.current && id === opportunityId) setBusy(false);
    }
  }
  return (
    <main className="product detail">
      <header className="detail-head">
        <div>
          <div className="badges">
            <span>{data.lifecycle_stage ?? "단계 미분류"}</span>
            <span className={decision.tone}>{decision.label}</span>
            {data.extraction.status !== "validated" && (
              <span className="pending">추출 {data.extraction.status}</span>
            )}
          </div>
          <h1>{data.title}</h1>
          <p>{data.buyer_name}</p>
        </div>
        <div>
          <button disabled={busy} onClick={toggle}>
            {busy
              ? "처리 중…"
              : data.watched
                ? "관심 공고 해제"
                : "관심 공고로 추적"}
          </button>
          {actionError && (
            <p role="alert" className="danger-text">
              {actionError}
            </p>
          )}
        </div>
      </header>
      <section className="summary-grid">
        <Fact
          label="예산"
          value={formatMoney(data.estimated_amount, data.currency)}
        />
        <Fact label="마감" value={formatDate(data.closes_at)} />
        <Fact
          label="관련도"
          value={
            data.ranking
              ? `${Math.round(Number(data.ranking.final_score) * 100)}점`
              : "계산 대기"
          }
        />
        <Fact
          label="추천 게이트"
          value={data.ranking?.recommended ? "검토 추천" : "추천 기준 미충족"}
        />
      </section>
      <div className="detail-grid">
        <div>
          <Section
            title="참여 조건 판단"
            subtitle="관련도 점수와 별개의 결정입니다."
          >
            {data.decision_status !== "ready" ? (
              <p className="notice">
                현재 입력이 준비되지 않아 참여 가능으로 확정하지 않습니다.
              </p>
            ) : (
              <>
                <ReasonList
                  title="필수 조건 불일치"
                  reasons={data.eligibility?.hard_failures ?? []}
                />
                <ReasonList
                  title="확인 필요"
                  reasons={data.eligibility?.warnings ?? []}
                />
              </>
            )}
          </Section>
          <Section title="현재 정규화 요약">
            {current ? (
              <>
                <p>
                  현재 버전 v{current.version_number} ·{" "}
                  {formatDate(current.effective_at)}
                </p>
                <JsonView value={current.normalized_json} />
              </>
            ) : (
              <p>현재 버전이 없습니다.</p>
            )}
          </Section>
          <Section title="요구사항과 근거">
            <p className="notice">
              구조화 추출 상태: <b>{data.extraction.status}</b>. 검증된 현재
              추출만 판단에 사용합니다.
            </p>
            <JsonView value={data.extraction.trusted_fields} />
            <h3>근거 인용</h3>
            <JsonView value={data.extraction.evidence} />
            {Object.keys(data.extraction.conflicts as object).length > 0 && (
              <>
                <h3>상충 정보</h3>
                <JsonView value={data.extraction.conflicts} />
              </>
            )}
          </Section>
          <Section title="Delta — 변경 전후">
            <p>
              {data.deltas.current_inputs_ready
                ? "현재 비교 입력 준비 완료"
                : "현재 비교 입력 준비 중"}
            </p>
            {data.deltas.items.length ? (
              data.deltas.items.map((delta) => (
                <article className="delta" key={delta.id}>
                  <header>
                    <b>{delta.impact_level} 영향</b>
                    <span>
                      {delta.applicable_now ? "현재 적용" : "과거 비교"}
                    </span>
                  </header>
                  <h3>필드 변경</h3>
                  <JsonView value={delta.field_changes_json} />
                  <h3>문서 변경</h3>
                  <JsonView value={delta.document_changes_json} />
                  <h3>판정 근거</h3>
                  <JsonView value={delta.impact_reasons_json} />
                </article>
              ))
            ) : (
              <p>변경 이력이 없습니다.</p>
            )}
          </Section>
        </div>
        <aside>
          <Section title="생애주기">
            <h3>현재 연결</h3>
            <LifecycleLinks links={data.timeline.active_links} />
            <h3>과거·철회 연결</h3>
            <LifecycleLinks links={data.timeline.historical_links} />
          </Section>
          <Section title="버전 기록">
            <ol className="timeline">
              {data.versions.map((version) => (
                <li key={version.id}>
                  <b>
                    v{version.version_number}
                    {version.id === data.current_version_id ? " · 현재" : ""}
                  </b>
                  <span>{version.transition_kind}</span>
                  <small>{formatDate(version.effective_at)}</small>
                </li>
              ))}
            </ol>
          </Section>
          <Section title="관련도 설명">
            {data.ranking ? (
              <>
                <p>
                  최종 점수 {data.ranking.final_score} · 추천{" "}
                  {data.ranking.recommended ? "예" : "아니오"}
                </p>
                <JsonView value={data.ranking.features} />
                <JsonView value={data.ranking.explanation} />
              </>
            ) : (
              <p>현재 순위 판단이 없습니다.</p>
            )}
          </Section>
          <Section title="원문 문서">
            {data.documents.length ? (
              data.documents.map((document) => (
                <article className="document" key={document.id}>
                  <b>{document.filename}</b>
                  <small>SHA-256 {document.sha256 ?? "확인 전"}</small>
                  <small>다운로드 상태 {document.download_status}</small>
                  {documentUrl(document.id).startsWith("#") ? (
                    <small>공개 합성 데모에서는 원문 파일을 제공하지 않습니다.</small>
                  ) : (
                    <a href={documentUrl(document.id)}>인증된 원문 다운로드</a>
                  )}
                </article>
              ))
            ) : (
              <p>연결된 문서가 없습니다.</p>
            )}
          </Section>
        </aside>
      </div>
    </main>
  );
}
function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <header>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </header>
      {children}
    </section>
  );
}
function Fact({ label, value }: { label: string; value: string }) {
  return (
    <article>
      <small>{label}</small>
      <strong>{value}</strong>
    </article>
  );
}
function ReasonList({
  title,
  reasons,
}: {
  title: string;
  reasons: { code: string; field: string; message: string }[];
}) {
  return (
    <div>
      <h3>{title}</h3>
      {reasons.length ? (
        <ul className="reasons">
          {reasons.map((reason, index) => (
            <li key={`${reason.code}-${index}`}>
              <b>{reason.field}</b>
              {reason.message}
            </li>
          ))}
        </ul>
      ) : (
        <p>해당 항목 없음</p>
      )}
    </div>
  );
}
function LifecycleLinks({ links }: { links: LifecycleLink[] }) {
  return links.length ? (
    <ol className="timeline">
      {links.map((link) => (
        <li key={link.id}>
          <b>
            {link.relation_type} · {link.status}
          </b>
          <span>
            <Link href={`/opportunities/${link.parent_opportunity_id}`}>
              이전 공고
            </Link>{" "}
            →{" "}
            <Link href={`/opportunities/${link.child_opportunity_id}`}>
              다음 공고
            </Link>
          </span>
          <small>
            {formatDate(link.created_at)} · 신뢰도 {link.confidence} ·{" "}
            {link.link_method}
          </small>
          <JsonView value={link.evidence_json} />
        </li>
      ))}
    </ol>
  ) : (
    <p>연결 없음</p>
  );
}
