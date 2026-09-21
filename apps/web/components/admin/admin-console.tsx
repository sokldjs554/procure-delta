"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ApiError,
  getAdminFailures,
  getAdminPipeline,
  getAdminSources,
  getRelease,
  operatorLogin,
  retryAdminFailure,
  session,
  type AdminFailure,
  type AdminPipeline,
  type AdminSource,
  type Release,
} from "../../lib/api";
type Load<T> = {
  status: "loading" | "ready" | "error";
  data?: T;
  message?: string;
};
type FailureList = { items: AdminFailure[]; nextCursor: string | null };
const staticDemo = process.env.NEXT_PUBLIC_STATIC_DEMO === "true";
const loading = <T,>(): Load<T> => ({ status: "loading" });
const errorText = (error: unknown) =>
  error instanceof ApiError && error.status === 403
    ? "운영자 권한이 필요합니다. 운영자 비밀값으로 다시 로그인하세요."
    : error instanceof ApiError && error.status === 401
      ? "운영자 세션이 만료되었습니다. 다시 로그인하세요."
      : "데이터를 불러오지 못했습니다.";
const when = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat("ko-KR", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "UTC",
      }).format(new Date(value)) + " UTC"
    : "미확인";
function Panel<T>({
  title,
  state,
  reload,
  children,
}: {
  title: string;
  state: Load<T>;
  reload: () => void;
  children: (data: T) => ReactNode;
}) {
  return (
    <section className="panel admin-panel">
      <header>
        <h2>{title}</h2>
      </header>
      {state.status === "loading" ? (
        <p role="status">불러오는 중…</p>
      ) : state.status === "error" ? (
        <div role="alert">
          <p>{state.message}</p>
          <button onClick={reload}>다시 시도</button>
        </div>
      ) : (
        children(state.data as T)
      )}
    </section>
  );
}
export function AdminConsole() {
  const [actor, setActor] = useState<"checking" | "login" | "operator">(
      staticDemo ? "operator" : "checking",
    ),
    [secret, setSecret] = useState(""),
    [authError, setAuthError] = useState("");
  const [pipeline, setPipeline] = useState<Load<AdminPipeline>>(loading),
    [sources, setSources] = useState<Load<AdminSource[]>>(loading),
    [failures, setFailures] = useState<Load<FailureList>>(loading),
    [release, setRelease] = useState<Load<Release>>(loading);
  const [retrying, setRetrying] = useState<string | null>(null),
    [retryNotice, setRetryNotice] = useState("");
  const failureGeneration = useRef(0);
  const continuationPending = useRef(false);
  const [continuationLoading, setContinuationLoading] = useState(false);
  const [continuationError, setContinuationError] = useState("");
  useEffect(() => {
    if (staticDemo) return;
    session()
      .then((a) => setActor(a.role === "operator" ? "operator" : "login"))
      .catch(() => setActor("login"));
  }, []);
  const loadPipeline = () => {
    setPipeline(loading());
    getAdminPipeline()
      .then((data) => setPipeline({ status: "ready", data }))
      .catch((e) => setPipeline({ status: "error", message: errorText(e) }));
  };
  const loadSources = () => {
    setSources(loading());
    getAdminSources()
      .then((data) => setSources({ status: "ready", data }))
      .catch((e) => setSources({ status: "error", message: errorText(e) }));
  };
  const loadFailures = () => {
    failureGeneration.current += 1;
    continuationPending.current = false;
    setContinuationLoading(false);
    setContinuationError("");
    setFailures(loading());
    getAdminFailures()
      .then((data) =>
        setFailures({
          status: "ready",
          data: { items: data.items, nextCursor: data.next_cursor },
        }),
      )
      .catch((e) => setFailures({ status: "error", message: errorText(e) }));
  };
  const loadMoreFailures = () => {
    const cursor = failures.data?.nextCursor;
    if (!cursor || continuationPending.current) return;
    const generation = failureGeneration.current;
    continuationPending.current = true;
    setContinuationLoading(true);
    setContinuationError("");
    getAdminFailures(cursor)
      .then((data) => {
        if (failureGeneration.current !== generation) return;
        setFailures((current) => {
          const items = [...(current.data?.items ?? []), ...data.items];
          return {
            status: "ready",
            data: {
              items: [
                ...new Map(items.map((item) => [item.id, item])).values(),
              ],
              nextCursor: data.next_cursor,
            },
          };
        });
      })
      .catch((e) => {
        if (failureGeneration.current === generation)
          setContinuationError(errorText(e));
      })
      .finally(() => {
        if (failureGeneration.current !== generation) return;
        continuationPending.current = false;
        setContinuationLoading(false);
      });
  };
  const loadRelease = () => {
    setRelease(loading());
    getRelease()
      .then((data) => setRelease({ status: "ready", data }))
      .catch((e) => setRelease({ status: "error", message: errorText(e) }));
  };
  useEffect(() => {
    if (actor === "operator") {
      void Promise.resolve().then(() => {
        loadPipeline();
        loadSources();
        loadFailures();
        loadRelease();
      });
    }
  }, [actor]);
  async function enter(e: React.FormEvent) {
    e.preventDefault();
    setAuthError("");
    try {
      const a = await operatorLogin(secret);
      setSecret("");
      if (a.role !== "operator") throw new Error();
      setActor("operator");
    } catch (e) {
      setSecret("");
      setAuthError(
        e instanceof ApiError && e.status === 401
          ? "비밀값이 올바르지 않습니다."
          : "운영자 로그인을 완료하지 못했습니다.",
      );
    }
  }
  async function retry(item: AdminFailure) {
    if (retrying) return;
    setRetrying(item.id);
    setRetryNotice("");
    try {
      const r = await retryAdminFailure(item.id);
      setRetryNotice(
        r.queue_published
          ? "재시도 작업을 큐에 게시했습니다."
          : "복구 상태는 저장됐지만 큐 게시를 확인하지 못했습니다. 작업자가 복구 상태를 다시 확인합니다.",
      );
      loadFailures();
      loadPipeline();
    } catch (e) {
      setRetryNotice(
        e instanceof ApiError && e.status === 429
          ? "재시도 요청이 너무 많습니다. 잠시 후 다시 시도하세요."
          : e instanceof ApiError && e.status === 409
            ? "현재 상태에서는 재시도할 수 없습니다. 목록을 새로고침하세요."
            : errorText(e),
      );
    } finally {
      setRetrying(null);
    }
  }
  if (actor === "checking")
    return (
      <main className="state" role="status">
        운영자 세션 확인 중…
      </main>
    );
  if (actor === "login")
    return (
      <main className="admin-login">
        <form className="panel" onSubmit={enter}>
          <p className="eyebrow">SYNTHETIC DEMO · NON-PRODUCTION AUTH</p>
          <h1>운영자 로그인</h1>
          <p>운영 지표와 실패 복구 작업은 운영자 세션에서만 볼 수 있습니다.</p>
          <label>
            운영자 비밀값
            <input
              type="password"
              autoComplete="current-password"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              required
            />
          </label>
          {authError && (
            <p role="alert" className="danger-copy">
              {authError}
            </p>
          )}
          <button>운영 콘솔 열기</button>
        </form>
      </main>
    );
  return (
    <main className="product admin">
      <header className="page-head">
        <div>
          <p className="eyebrow">
            {staticDemo ? "SYNTHETIC OPERATOR SNAPSHOT" : "OBSERVABILITY · ACTUAL API"}
          </p>
          <h1>파이프라인 운영 현황</h1>
          <p>
            {staticDemo
              ? "공개 Render에서는 저장된 합성 운영 스냅샷을 보여줍니다. 실제 DB·Redis·worker 현재값은 Docker/API 검증에서 별도로 확인합니다."
              : "오늘은 UTC 00:00부터 집계합니다. 문서·추출 값은 누적 DB 합계이며 작업 활동은 현재 프로세스 수명 동안의 카운터입니다."}
          </p>
        </div>
      </header>
      <section className="operator-pipeline-strip" aria-label="운영 파이프라인 개요">
        <div>
          <p className="eyebrow">CURRENT PIPELINE</p>
          <strong>collect → parse → extract → delta → eligibility → rank → notify</strong>
        </div>
        <span className={pipeline.status === "ready" && pipeline.data?.worker_heartbeat && pipeline.data?.scheduler_heartbeat ? "success" : "pending"}>
          {staticDemo
            ? "저장된 합성 지표"
            : pipeline.status === "ready"
              ? pipeline.data?.worker_heartbeat && pipeline.data?.scheduler_heartbeat
                ? "현재 지표 연결"
                : "현재 지표 경고"
              : "현재 지표 미확인"}
        </span>
      </section>
      <Panel title="오늘의 수집 · UTC" state={pipeline} reload={loadPipeline}>
        {(p) => (
          <>
            <div className="kpi-grid">
              {[
                ["가져온 레코드", p.records_fetched_today],
                ["신규 레코드", p.new_records_today],
                ["변경 버전", p.changed_versions_today],
                ["중복 건너뜀", p.duplicates_skipped_today],
              ].map(([l, v]) => (
                <article key={l}>
                  <small>{l}</small>
                  <strong>{v}</strong>
                </article>
              ))}
            </div>
            <p className="observed">관측 시각 {when(p.observed_at)}</p>
          </>
        )}
      </Panel>
      <div className="admin-columns">
        <Panel
          title="처리 · 누적 DB 합계"
          state={pipeline}
          reload={loadPipeline}
        >
          {(p) => (
            <div className="metric-list">
              <span>
                파싱 실패 <b>{p.parsing_failures}</b>
              </span>
              <span>
                OCR 폴백 <b>{p.ocr_fallbacks}</b>
              </span>
              <span>
                구조화 추출 <b>{p.structured_extraction_count}</b>
              </span>
              <span>
                스키마 검증 실패 <b>{p.schema_validation_failures}</b>
              </span>
              {p.parsing.map((x) => (
                <small key={x.kind + x.status}>
                  {x.kind} / {x.status}: {x.count}
                </small>
              ))}
              {p.extraction.map((x) => (
                <small key={x.kind + x.status}>
                  {x.kind} / {x.status}: {x.count}
                </small>
              ))}
            </div>
          )}
        </Panel>
        <Panel title="큐와 작업 활동" state={pipeline} reload={loadPipeline}>
          {(p) => (
            <div className="metric-list">
              <span>
                작업 큐 깊이 <b>{p.worker_queue_depth}</b>
              </span>
              <span>
                스케줄러 큐 깊이 <b>{p.scheduler_queue_depth}</b>
              </span>
              <span>
                재시도 대기 <b>{p.retry_queue_count}</b>
              </span>
              <span>
                DLQ <b>{p.dlq_count}</b>
              </span>
              <small>
                작업자{" "}
                {p.worker_heartbeat ? "heartbeat 정상" : "heartbeat 없음"}
              </small>
              {p.worker_activity ? (
                <small>
                  완료 {p.worker_activity.completed} · 실패{" "}
                  {p.worker_activity.failed} · 재시도{" "}
                  {p.worker_activity.retried} · 실행 중{" "}
                  {p.worker_activity.ongoing}
                </small>
              ) : (
                <small>프로세스 활동 미확인</small>
              )}
              <small>
                스케줄러{" "}
                {p.scheduler_heartbeat ? "heartbeat 정상" : "heartbeat 없음"}
              </small>
              <small>
                {p.scheduler_activity
                  ? `완료 ${p.scheduler_activity.completed} · 실패 ${p.scheduler_activity.failed} · 재시도 ${p.scheduler_activity.retried} · 실행 중 ${p.scheduler_activity.ongoing}`
                  : "프로세스 활동 미확인"}
              </small>
            </div>
          )}
        </Panel>
      </div>
      <Panel title="소스 상태와 신선도" state={sources} reload={loadSources}>
        {(rows) => (
          <div className="admin-table">
            {rows.length ? (
              rows.map((s) => (
                <article key={s.id}>
                  <div>
                    <strong>{s.display_name}</strong>
                    <small>
                      {s.code} · {s.enabled ? "활성" : "비활성"} · 폴링{" "}
                      {s.polling_interval_seconds}초
                    </small>
                  </div>
                  <span>
                    마지막 성공 {when(s.last_success_at)}
                    <br />
                    마지막 실패 {when(s.last_failure_at)}
                  </span>
                </article>
              ))
            ) : (
              <p>등록된 소스가 없습니다.</p>
            )}
          </div>
        )}
      </Panel>
      {retryNotice && (
        <p className="notice" role="status">
          {retryNotice}
        </p>
      )}
      <Panel
        title="실패 복구 · 재시도 / DLQ"
        state={failures}
        reload={loadFailures}
      >
        {(list) => (
          <div className="admin-table">
            {list.items.length ? (
              list.items.map((f) => (
                <article key={f.id}>
                  <div>
                    <strong>{f.job_type}</strong>
                    <small>
                      {f.error_code} · 시도 {f.attempts}회 ·{" "}
                      {f.dead_lettered ? "DLQ" : "재시도 대기"}
                    </small>
                    <small>
                      마지막 오류 {when(f.last_error_at)} · 다음 재시도{" "}
                      {when(f.next_retry_at)}
                    </small>
                  </div>
                  {f.dead_lettered && (
                    <button
                      disabled={retrying !== null}
                      onClick={() => retry(f)}
                    >
                      {retrying === f.id ? "요청 중…" : "작업 재시도"}
                    </button>
                  )}
                </article>
              ))
            ) : (
              <p>대기 중이거나 DLQ에 있는 실패가 없습니다.</p>
            )}
            {list.nextCursor && (
              <>
                {continuationError && (
                  <p className="danger-copy" role="alert">
                    {continuationError}
                  </p>
                )}
                <button
                  disabled={continuationLoading}
                  onClick={loadMoreFailures}
                >
                  {continuationLoading
                    ? "페이지 불러오는 중…"
                    : continuationError
                      ? "페이지 다시 시도"
                      : "실패 더 보기"}
                </button>
              </>
            )}
          </div>
        )}
      </Panel>
      <Panel title="릴리스와 런타임" state={release} reload={loadRelease}>
        {(r) => (
          <dl className="release-grid">
            <div>
              <dt>서비스</dt>
              <dd>{r.name}</dd>
            </div>
            <div>
              <dt>버전</dt>
              <dd>{r.version}</dd>
            </div>
            <div>
              <dt>리비전</dt>
              <dd>{r.revision}</dd>
            </div>
            <div>
              <dt>인증</dt>
              <dd>{r.authentication}</dd>
            </div>
            <div>
              <dt>추출 모드</dt>
              <dd>{r.extraction_mode}</dd>
            </div>
          </dl>
        )}
      </Panel>
    </main>
  );
}
