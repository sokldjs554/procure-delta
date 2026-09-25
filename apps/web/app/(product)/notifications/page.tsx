"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  getNotifications,
  getPreferences,
  setPreferences,
  type NotificationItem,
  type Preferences,
} from "../../../lib/api";
import { appendUniquePage, formatDate } from "../../../lib/product";
const labels = {
  new_high_relevance: "관련도 높은 새 공고",
  watched_material_change: "관심 공고 중요 변경",
  deadline_changed: "마감일 변경",
  eligibility_changed: "참여 조건 변경",
  outcome_published: "낙찰·계약 결과",
} as const;
const statusLabels: Record<string, string> = { delivered: "전달 완료", pending: "전달 대기", retry: "재시도 대기", failed: "전달 실패", sending: "전달 중", suppressed: "발송 제외" };
export default function Notifications() {
  const [items, setItems] = useState<NotificationItem[] | null>(null),
    [cursor, setCursor] = useState<string | null>(null),
    [historyError, setHistoryError] = useState(""),
    [historyLoading, setHistoryLoading] = useState(true),
    [more, setMore] = useState(false);
  const [prefs, setPrefs] = useState<Preferences | null>(null),
    [prefsError, setPrefsError] = useState(""),
    [prefsLoading, setPrefsLoading] = useState(true),
    [message, setMessage] = useState("");
  const generation = useRef(0);
  const loadHistory = useCallback(() => {
    const request = ++generation.current;
    setHistoryLoading(true);
    setHistoryError("");
    getNotifications()
      .then((page) => {
        if (request === generation.current) {
          setItems(page.items);
          setCursor(page.next_cursor);
        }
      })
      .catch((e: Error) => {
        if (request === generation.current) setHistoryError(e.message);
      })
      .finally(() => {
        if (request === generation.current) setHistoryLoading(false);
      });
  }, []);
  const loadPrefs = useCallback(() => {
    setPrefsLoading(true);
    setPrefsError("");
    getPreferences()
      .then(setPrefs)
      .catch((e: Error) => setPrefsError(e.message))
      .finally(() => setPrefsLoading(false));
  }, []);
  useEffect(() => {
    loadHistory();
    loadPrefs();
    return () => {
      generation.current++;
    };
  }, [loadHistory, loadPrefs]);
  async function loadMore() {
    if (!cursor || more) return;
    const request = generation.current;
    setMore(true);
    try {
      const page = await getNotifications(cursor);
      if (request === generation.current) {
        setItems((current) => appendUniquePage(current ?? [], page.items));
        setCursor(page.next_cursor);
      }
    } catch (e) {
      if (request === generation.current) setHistoryError((e as Error).message);
    } finally {
      if (request === generation.current) setMore(false);
    }
  }
  async function save() {
    if (!prefs) return;
    setMessage("저장 중…");
    try {
      setPrefs(await setPreferences(prefs));
      setMessage("알림 설정을 저장했습니다.");
    } catch (e) {
      setMessage((e as Error).message);
    }
  }
  return (
    <main className="product">
      <header className="page-head">
        <div>
          <p className="eyebrow">NOTIFICATIONS</p>
          <h1>알림 기록과 설정</h1>
          <p>{process.env.NEXT_PUBLIC_STATIC_DEMO === "true" ? "합성 변경 알림을 살펴보세요. 공개 데모에서는 외부 메시지를 발송하지 않습니다." : "변경 이벤트와 실제 전달 상태를 확인합니다."}</p>
        </div>
      </header>
      <div className="detail-grid">
        <section className="panel">
          <h2>알림 기록</h2>
          {historyLoading ? (
            <p>불러오는 중…</p>
          ) : historyError && !items ? (
            <ErrorState message={historyError} retry={loadHistory} />
          ) : items?.length ? (
            <>
              {items.map((item) => (
                <article className="notification" key={item.id}>
                  <div>
                    <b>
                      {labels[item.template_key as keyof typeof labels] ??
                        item.template_key}
                    </b>
                    <small>
                      {formatDate(item.received_at ?? item.sent_at)}
                    </small>
                  </div>
                  <span
                    className={
                      item.status === "delivered" ? "success" : "pending"
                    }
                  >
                    {statusLabels[item.status] ?? item.status}
                  </span>
                  <p>
                    채널 {item.channel === "local" ? "제품 내 알림" : item.channel} · 시도 {item.attempt_count}회
                  </p>
                  {item.payload && typeof item.payload === "object" && !Array.isArray(item.payload) && typeof item.payload.title === "string" && <p>{item.payload.title}</p>}
                  <Link href={`/opportunities/${encodeURIComponent(item.opportunity_id)}`}>변경된 공고 확인 →</Link>
                </article>
              ))}
              {historyError && <p role="alert">{historyError}</p>}
              {cursor && (
                <div className="load-more">
                  <button disabled={more} onClick={loadMore}>
                    {more ? "불러오는 중…" : "알림 더 보기"}
                  </button>
                </div>
              )}
            </>
          ) : (
            <div className="state">
              <h3>알림 기록이 없습니다</h3>
              <p>관심 공고의 변경이 생기면 표시됩니다.</p>
            </div>
          )}
        </section>
        <section className="panel preferences">
          <h2>알림 설정</h2>
          {process.env.NEXT_PUBLIC_STATIC_DEMO === "true" && <p className="notice">이 화면의 설정은 현재 탭에서만 유지됩니다. 예시 알림 기록은 설정과 관계없이 표시됩니다.</p>}
          {prefsLoading ? (
            <p>불러오는 중…</p>
          ) : prefsError && !prefs ? (
            <ErrorState message={prefsError} retry={loadPrefs} />
          ) : (
            prefs && (
              <>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={prefs.enabled}
                    onChange={(e) =>
                      setPrefs({ ...prefs, enabled: e.target.checked })
                    }
                  />
                  알림 사용
                </label>
                <h3>채널</h3>
                {(["local", "webhook", "email"] as const).map((channel) => (
                  <label className="check" key={channel}>
                    <input
                      type="checkbox"
                      checked={prefs.channels.includes(channel)}
                      onChange={(e) =>
                        setPrefs({
                          ...prefs,
                          channels: e.target.checked
                            ? [...prefs.channels, channel]
                            : prefs.channels.filter((item) => item !== channel),
                        })
                      }
                    />
                    {channel === "local" ? "제품 내 알림" : channel}
                  </label>
                ))}
                <h3>알림 조건</h3>
                {Object.entries(labels).map(([key, label]) => (
                  <label className="check" key={key}>
                    <input
                      type="checkbox"
                      checked={prefs.triggers.includes(
                        key as keyof typeof labels,
                      )}
                      onChange={(e) =>
                        setPrefs({
                          ...prefs,
                          triggers: e.target.checked
                            ? [...prefs.triggers, key as keyof typeof labels]
                            : prefs.triggers.filter((item) => item !== key),
                        })
                      }
                    />
                    {label}
                  </label>
                ))}
                <button onClick={save}>설정 저장</button>
                <p aria-live="polite">{message}</p>
              </>
            )
          )}
        </section>
      </div>
    </main>
  );
}
function ErrorState({
  message,
  retry,
}: {
  message: string;
  retry: () => void;
}) {
  return (
    <div className="state error">
      <p>{message}</p>
      <button onClick={retry}>다시 시도</button>
    </div>
  );
}
