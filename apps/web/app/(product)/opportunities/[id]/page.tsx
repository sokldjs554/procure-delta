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
import {
  deltaRows,
  describeField,
  describeValue,
  documentLink,
  documentChangeRows,
  evidenceRows,
  hasEvaluatedEligibility,
  normalizedRows,
} from "../../../../lib/detail-presentation";
export default function Detail() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<OpportunityDetail | null>(null),
    [error, setError] = useState(""),
    [actionError, setActionError] = useState(""),
    [busy, setBusy] = useState(false),
    [reload, setReload] = useState(0),
    [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const requestId = useRef(0);
  useEffect(() => {
    const request = ++requestId.current;
    setData(null);
    setError("");
    setActionError("");
    setBusy(false);
    setSelectedVersionId(null);
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
  const selectedVersion = data.versions.find((version) => version.id === selectedVersionId) ?? current;
  const showingHistoricalVersion = selectedVersion !== null && selectedVersion.id !== data.current_version_id;
  const trustedExtraction = data.extraction.status === "validated" && current !== null && !showingHistoricalVersion;
  const trustedRows = trustedExtraction ? normalizedRows(data.extraction.trusted_fields) : [];
  const citations = trustedExtraction ? evidenceRows(data.extraction.evidence) : [];
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
      <nav className="detail-breadcrumb" aria-label="현재 위치">
        <Link href="/inbox">공고함으로 돌아가기</Link><span aria-hidden="true">/</span><span>공고 상세</span>
      </nav>
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
      <nav className="detail-jump" aria-label="상세 항목 바로가기">
        <a href="#overview">공고 요약</a>
        <a href="#changes">변경 전후</a>
        <a href="#evidence">원문 근거</a>
        <a href="#documents">첨부 문서</a>
      </nav>
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
          value={data.ranking ? data.ranking.recommended ? "검토 추천" : "추천 기준 미충족" : "계산 대기"}
        />
      </section>
      <div className="detail-grid">
        <div>
          <Section
            id="overview"
            title="참여 조건 판단"
            subtitle="관련도 점수와 별개의 결정입니다."
          >
            {!hasEvaluatedEligibility(data.decision_status, data.eligibility) ? (
              <p className="notice">
                참여 조건 평가 결과가 준비되지 않아 참여 가능으로 확정하지 않습니다.
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
          <Section title="공고 내용">
            {selectedVersion ? (
              <>
                <label className="detail-version-select">확인할 공고 버전
                  <select value={selectedVersion.id} onChange={(event) => setSelectedVersionId(event.target.value)}>
                    {data.versions.map((version) => <option value={version.id} key={version.id}>
                      v{version.version_number} · {version.id === data.current_version_id ? "현재" : "이전"} · {formatDate(version.effective_at)}
                    </option>)}
                  </select>
                </label>
                {showingHistoricalVersion && <p className="notice">이전 버전의 공고 내용입니다. 위 참여 조건 판단은 현재 버전에 대한 결과이며, 이 버전에 대해 다시 계산한 결과가 아닙니다.</p>}
                <dl className="detail-facts">
                  {normalizedRows(selectedVersion.normalized_json).map((row) =>
                    <div key={row.key}><dt>{row.label}</dt><dd>{row.text}</dd></div>,
                  )}
                </dl>
                {!normalizedRows(selectedVersion.normalized_json).length && <p>표시할 정규화 항목이 없습니다.</p>}
                <TechnicalData title="정규화 원본 데이터" value={selectedVersion.normalized_json} />
              </>
            ) : (
              <p>현재 버전이 없습니다.</p>
            )}
          </Section>
          <Section id="evidence" title="요구사항과 원문 근거">
            <p className="notice">
              구조화 추출 상태: <b>{data.extraction.status}</b>. 검증된 현재 버전의
              추출만 신뢰할 수 있는 요구사항으로 표시합니다.
            </p>
            {showingHistoricalVersion && <p>이전 버전을 선택했습니다. 현재 버전으로 돌아오면 검증된 요구사항과 근거를 볼 수 있습니다.</p>}
            {trustedExtraction && <>
              <h3>검증된 요구사항</h3>
              {trustedRows.length ? <dl className="detail-facts">
                {trustedRows.map((row) => <div key={row.key}><dt>{row.label}</dt><dd>{row.text}</dd></div>)}
              </dl> : <p>검증된 요구사항이 없습니다.</p>}
              <h3>원문 인용</h3>
              {citations.length ? <div className="detail-evidence">
                {citations.map((citation, index) => {
                  const matchingDocument = data.documents.find((document) => document.sha256 && document.sha256 === citation.attachmentSha);
                  return <article className="detail-evidence-card" key={`${citation.field}-${index}`}>
                    <b>{citation.label}</b>
                    {citation.quote ? <blockquote>{citation.quote}</blockquote> : <p>원문 인용이 제공되지 않았습니다.</p>}
                    <small>
                      {matchingDocument ? <DocumentReference id={matchingDocument.id} filename={matchingDocument.filename} /> : citation.source ? `출처 ${citation.source}` : "출처 문서 확인 필요"}
                      {citation.page ? ` · ${citation.page}쪽` : ""}
                    </small>
                    {citation.attachmentSha && <small title={citation.attachmentSha}>SHA-256 {citation.attachmentSha}</small>}
                  </article>;
                })}
              </div> : <p>연결된 원문 인용이 없습니다.</p>}
            </>}
            {trustedExtraction && data.extraction.conflicts !== null && typeof data.extraction.conflicts === "object" && !Array.isArray(data.extraction.conflicts) && Object.keys(data.extraction.conflicts).length > 0 && (
              <>
                <h3>상충 정보</h3>
                <p className="notice">원문끼리 서로 다른 내용을 제시한 항목입니다. 아래 기술 데이터를 확인하세요.</p>
                <TechnicalData title="상충 정보 원본" value={data.extraction.conflicts} />
              </>
            )}
            {data.extraction.validation_errors.length > 0 && <p className="notice">검증 오류 {data.extraction.validation_errors.length}건이 기록되었습니다.</p>}
            <TechnicalData title="추출·근거 원본 데이터" value={{ trusted_fields: data.extraction.trusted_fields, evidence: data.extraction.evidence, conflicts: data.extraction.conflicts, validation_errors: data.extraction.validation_errors }} />
          </Section>
          <Section id="changes" title="변경 전후">
            <p>
              {data.deltas.current_inputs_ready
                ? "현재 비교 입력 준비 완료"
                : "현재 비교 입력 준비 중"}
            </p>
            {data.deltas.items.length ? (
              data.deltas.items.map((delta) => (
                <article className="delta" key={delta.id}>
                  <header>
                    <b>{delta.impact_level === "HIGH" ? "중요 변경" : delta.impact_level === "LOW" ? "경미한 변경" : `${delta.impact_level} 영향`}</b>
                    <span>
                      {delta.applicable_now ? "현재 적용" : "과거 비교"}
                    </span>
                  </header>
                  <p className="muted">{data.versions.find((version) => version.id === delta.from_version_id)?.version_number ?? "?"} → {data.versions.find((version) => version.id === delta.to_version_id)?.version_number ?? "?"} 버전 비교</p>
                  {deltaRows(delta.field_changes_json).length ? <div className="detail-change-table" role="table" aria-label="필드 변경 전후">
                    <div className="detail-change-head" role="row"><span role="columnheader">항목</span><span role="columnheader">변경 전</span><span role="columnheader">변경 후</span></div>
                    {deltaRows(delta.field_changes_json).map((row) => <div className="detail-change-row" role="row" key={row.key}>
                      <b role="cell">{row.label}</b><span role="cell">{row.before}</span><strong role="cell">{row.after}</strong>
                    </div>)}
                  </div> : <p>변경된 필드가 없습니다.</p>}
                  {documentChangeRows(delta.document_changes_json).length > 0 && <>
                    <h3>문서 변경</h3>
                    <div className="detail-doc-change">{documentChangeRows(delta.document_changes_json).map((change, index) =>
                      <div key={index}><b>{change.kind}</b><span>{change.before} → {change.after}</span>
                        {change.beforeSha && <small>이전 SHA-256 {change.beforeSha}</small>}
                        {change.afterSha && <small>변경 SHA-256 {change.afterSha}</small>}
                      </div>,
                    )}</div>
                  </>}
                  {Array.isArray(delta.impact_reasons_json) && delta.impact_reasons_json.length > 0 &&
                    <p className="muted">변경 사유: {delta.impact_reasons_json.map((reason) => describeValue(reason)).join(" · ")}</p>}
                  {!Array.isArray(delta.impact_reasons_json) && delta.impact_reasons_json !== null && typeof delta.impact_reasons_json === "object" && Array.isArray(delta.impact_reasons_json.codes) &&
                    <p className="muted">변경 사유: {delta.impact_reasons_json.codes.map((code) => describeField(String(code))).join(" · ") || "분류 사유 없음"}</p>}
                  <TechnicalData title="변경 상세·판정 근거 원본" value={{ fields: delta.field_changes_json, documents: delta.document_changes_json, impact_reasons: delta.impact_reasons_json }} />
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
          <Section id="documents" title="원문 문서" subtitle="현재 버전의 첨부 문서입니다.">
            {showingHistoricalVersion && <p className="notice">위에서 이전 버전을 선택해도 이 목록은 현재 버전의 문서입니다. 이전 첨부 파일을 제공하는 목록이 아닙니다.</p>}
            {data.documents.length ? (
              data.documents.map((document) => (
                <article className="document" key={document.id}>
                  <b>{document.filename}</b>
                  <small>SHA-256 {document.sha256 ?? "확인 전"}</small>
                  <small>다운로드 상태 {document.download_status}</small>
                  <DocumentReference id={document.id} />
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
  id,
  title,
  subtitle,
  children,
}: {
  id?: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="panel detail-section">
      <header>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </header>
      {children}
    </section>
  );
}
function TechnicalData({ title, value }: { title: string; value: import("../../../../lib/api").JsonValue }) {
  return <details className="detail-technical"><summary>{title}</summary><JsonView value={value} /></details>;
}
function DocumentReference({ id, filename }: { id: string; filename?: string }) {
  const link = documentLink(documentUrl(id));
  return link.href
    ? <a href={link.href}>{filename ?? link.label}</a>
    : <span className="document-unavailable">{filename ? `${filename} · ` : ""}{link.label}</span>;
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
              <b>{describeField(reason.field)}</b>
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
