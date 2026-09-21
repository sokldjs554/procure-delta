/* eslint-disable react-hooks/set-state-in-effect, react-hooks/exhaustive-deps -- request generations intentionally invalidate cleanup */
"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { OpportunityCard } from "../../../components/opportunities/opportunity-card";
import { getOpportunities, type Opportunity } from "../../../lib/api";
import { appendUniquePage, buildOpportunityQuery } from "../../../lib/product";

const initial = {
  q: "",
  lifecycle_stage: "",
  buyer: "",
  category: "",
  amount_min: "",
  amount_max: "",
  deadline_from: "",
  deadline_to: "",
  eligible_only: false,
  changed_since: "",
};

export default function Inbox() {
  const [filters, setFilters] = useState(initial);
  const [query, setQuery] = useState("");
  const [reload, setReload] = useState(0);
  const [items, setItems] = useState<Opportunity[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);

  useEffect(() => {
    const request = ++generation.current;
    setMore(false);
    getOpportunities(query)
      .then((page) => {
        if (request === generation.current) {
          setItems(page.items);
          setCursor(page.next_cursor);
          setError("");
        }
      })
      .catch((caught: Error) => {
        if (request === generation.current) setError(caught.message);
      })
      .finally(() => {
        if (request === generation.current) setLoading(false);
      });

    return () => {
      generation.current++;
    };
  }, [query, reload]);

  function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setItems([]);
    setCursor(null);
    setError("");
    setQuery(buildOpportunityQuery(filters));
    setReload((value) => value + 1);
  }

  async function loadMore() {
    if (!cursor || more) return;
    const request = generation.current;
    setMore(true);
    try {
      const suffix = new URLSearchParams(query);
      suffix.set("cursor", cursor);
      const page = await getOpportunities(suffix.toString());
      if (request !== generation.current) return;
      setItems((current) => appendUniquePage(current, page.items));
      setCursor(page.next_cursor);
    } catch (caught) {
      if (request === generation.current) setError((caught as Error).message);
    } finally {
      if (request === generation.current) setMore(false);
    }
  }

  function setDate(
    key: "deadline_from" | "deadline_to",
    value: string,
  ) {
    setFilters({
      ...filters,
      [key]: value ? new Date(value).toISOString() : "",
    });
  }

  return (
    <main className="product">
      <header className="page-head">
        <div>
          <p className="eyebrow">OPPORTUNITY INBOX</p>
          <h1>공고함</h1>
          <p>현재 기업 프로필을 기준으로 참여 조건과 관련도를 확인하세요.</p>
        </div>
        <span className="result-count">{loading ? "…" : items.length}건 표시</span>
      </header>

      <form className="filters" onSubmit={submit}>
        <label className="search">
          검색
          <input
            value={filters.q}
            onChange={(event) =>
              setFilters({ ...filters, q: event.target.value })
            }
            placeholder="공고명 또는 발주기관"
          />
        </label>

        <label>
          생애주기
          <select
            name="lifecycle_stage"
            aria-label="생애주기"
            value={filters.lifecycle_stage}
            onChange={(event) =>
              setFilters({ ...filters, lifecycle_stage: event.target.value })
            }
          >
            <option value="">전체</option>
            <option value="pre-specification">사전 규격</option>
            <option value="tender">공고</option>
            <option value="amendment">정정</option>
            <option value="award">낙찰</option>
            <option value="contract">계약</option>
          </select>
        </label>

        <label>
          분류
          <input
            value={filters.category}
            onChange={(event) =>
              setFilters({ ...filters, category: event.target.value })
            }
          />
        </label>

        <label>
          발주기관
          <input
            value={filters.buyer}
            onChange={(event) =>
              setFilters({ ...filters, buyer: event.target.value })
            }
          />
        </label>

        <label>
          최소 금액
          <input
            inputMode="numeric"
            value={filters.amount_min}
            onChange={(event) =>
              setFilters({ ...filters, amount_min: event.target.value })
            }
          />
        </label>

        <label>
          최대 금액
          <input
            inputMode="numeric"
            value={filters.amount_max}
            onChange={(event) =>
              setFilters({ ...filters, amount_max: event.target.value })
            }
          />
        </label>

        <label>
          마감 시작
          <input
            type="datetime-local"
            onChange={(event) => setDate("deadline_from", event.target.value)}
          />
        </label>

        <label>
          마감 종료
          <input
            type="datetime-local"
            onChange={(event) => setDate("deadline_to", event.target.value)}
          />
        </label>

        <label className="check">
          <input
            type="checkbox"
            checked={Boolean(filters.changed_since)}
            onChange={(event) =>
              setFilters({
                ...filters,
                changed_since: event.target.checked
                  ? (localStorage.getItem("procureDeltaLastVisit") ??
                    new Date().toISOString())
                  : "",
              })
            }
          />
          지난 방문 후 변경
        </label>

        <label className="check">
          <input
            type="checkbox"
            checked={filters.eligible_only}
            onChange={(event) =>
              setFilters({ ...filters, eligible_only: event.target.checked })
            }
          />
          경고 없는 참여 가능 공고만
        </label>

        <button>필터 적용</button>
      </form>

      {loading ? (
        <div className="state">
          <span className="spinner" />
          공고를 불러오는 중입니다.
        </div>
      ) : error && !items.length ? (
        <div className="state error">
          <p>{error}</p>
          <button
            onClick={() => {
              setLoading(true);
              setReload((value) => value + 1);
            }}
          >
            다시 시도
          </button>
        </div>
      ) : items.length ? (
        <>
          <section className="cards">
            {items.map((item) => (
              <OpportunityCard key={item.id} item={item} />
            ))}
          </section>
          {error && <p role="alert">{error}</p>}
          {cursor && (
            <div className="load-more">
              <button disabled={more} onClick={loadMore}>
                {more ? "불러오는 중…" : "공고 더 보기"}
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="state">
          <h2>조건에 맞는 공고가 없습니다</h2>
          <p>필터 범위를 넓히거나 기업 프로필을 확인해 보세요.</p>
        </div>
      )}
    </main>
  );
}
