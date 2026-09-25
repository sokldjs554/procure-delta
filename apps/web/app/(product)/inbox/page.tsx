/* eslint-disable react-hooks/set-state-in-effect, react-hooks/exhaustive-deps -- request generations intentionally invalidate cleanup */
"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { getOpportunities, type Opportunity } from "../../../lib/api";
import { appendUniquePage, buildOpportunityQuery } from "../../../lib/product";
import { filterInbox, sortInbox, toggleComparison, type InboxSort, type InboxView } from "../../../lib/inbox";
import { OpportunityCard } from "../../../components/opportunities/opportunity-card";
import { InboxComparison } from "../../../components/opportunities/inbox-comparison";

const initial = { q: "", lifecycle_stage: "", buyer: "", category: "", amount_min: "", amount_max: "", deadline_from: "", deadline_to: "", eligible_only: false, changed_since: "" };
const views: { key: InboxView; label: string }[] = [
  { key: "all", label: "전체" }, { key: "strict", label: "참여 조건 충족" },
  { key: "review", label: "확인 필요" }, { key: "amendment", label: "정정 공고" },
];
export default function Inbox() {
  const [filters, setFilters] = useState(initial), [query, setQuery] = useState(""), [reload, setReload] = useState(0);
  const [localDates, setLocalDates] = useState({ deadline_from: "", deadline_to: "" });
  const [items, setItems] = useState<Opportunity[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true), [more, setMore] = useState(false), [error, setError] = useState("");
  const [view, setView] = useState<InboxView>("all"), [sort, setSort] = useState<InboxSort>("recommendation");
  const [selected, setSelected] = useState<string[]>([]);
  const generation = useRef(0);
  useEffect(() => {
    const request = ++generation.current;
    setMore(false);
    getOpportunities(query).then(page => {
      if (request === generation.current) { setItems(page.items); setCursor(page.next_cursor); setError(""); }
    }).catch((e: Error) => { if (request === generation.current) setError(e.message); })
      .finally(() => { if (request === generation.current) setLoading(false); });
    return () => { generation.current++; };
  }, [query, reload]);
  function refresh(nextFilters = filters) {
    generation.current++; // Reject an older request even before the next effect starts.
    setLoading(true); setMore(false); setItems([]); setCursor(null); setError(""); setSelected([]);
    setQuery(buildOpportunityQuery(nextFilters)); setReload(value => value + 1);
  }
  function submit(event: FormEvent) { event.preventDefault(); refresh(); }
  function clearFilters() { setFilters(initial); setLocalDates({ deadline_from: "", deadline_to: "" }); setView("all"); refresh(initial); }
  async function loadMore() {
    if (!cursor || more || loading) return;
    const request = generation.current;
    setMore(true); setError("");
    try {
      const suffix = new URLSearchParams(query); suffix.set("cursor", cursor);
      const page = await getOpportunities(suffix.toString());
      if (request !== generation.current) return;
      setItems(current => appendUniquePage(current, page.items)); setCursor(page.next_cursor);
    } catch (e) { if (request === generation.current) setError((e as Error).message); }
    finally { if (request === generation.current) setMore(false); }
  }
  function date(key: "deadline_from" | "deadline_to", value: string) {
    setLocalDates(current => ({ ...current, [key]: value }));
    const parsed = value ? new Date(value) : null;
    setFilters(current => ({ ...current, [key]: parsed && !Number.isNaN(parsed.getTime()) ? parsed.toISOString() : "" }));
  }
  const visible = sortInbox(filterInbox(items, view), sort);
  const compared = selected.map(id => items.find(item => item.id === id)).filter((item): item is Opportunity => Boolean(item));
  return <main className="product inbox-page">
    <header className="page-head"><div><p className="eyebrow">OPPORTUNITY INBOX</p><h1>공고함</h1><p>참여 조건을 확인하고 관련도에 따라 공고를 살펴보세요.</p></div>
      <span className="result-count">{loading ? "…" : items.length}건 불러옴{cursor && !loading ? " · 다음 페이지 있음" : ""}</span></header>
    <form className="filters inbox-filters" onSubmit={submit}>
      <div className="inbox-search-row"><label className="search">검색<input type="search" value={filters.q} onChange={e => setFilters({ ...filters, q: e.target.value })} placeholder="공고명 또는 발주기관" /></label>
        <label>생애주기<select name="lifecycle_stage" aria-label="생애주기" value={filters.lifecycle_stage} onChange={e => setFilters({ ...filters, lifecycle_stage: e.target.value })}>
          <option value="">전체</option><option value="pre-specification">사전 규격</option><option value="tender">입찰 공고</option><option value="amendment">정정 공고</option><option value="award">낙찰</option><option value="contract">계약</option></select></label>
        <div className="filter-actions"><button type="submit">필터 적용</button><button type="button" className="ghost" onClick={clearFilters}>필터 초기화</button></div></div>
      <details className="advanced-filters"><summary>상세 조건</summary><div className="advanced-filter-grid">
        <label>분류<input value={filters.category} onChange={e => setFilters({ ...filters, category: e.target.value })} /></label>
        <label>발주기관<input value={filters.buyer} onChange={e => setFilters({ ...filters, buyer: e.target.value })} /></label>
        <label>최소 금액<input type="number" min="0" value={filters.amount_min} onChange={e => setFilters({ ...filters, amount_min: e.target.value })} /></label>
        <label>최대 금액<input type="number" min="0" value={filters.amount_max} onChange={e => setFilters({ ...filters, amount_max: e.target.value })} /></label>
        <label>마감 시작<input type="datetime-local" value={localDates.deadline_from} onChange={e => date("deadline_from", e.target.value)} /></label>
        <label>마감 종료<input type="datetime-local" value={localDates.deadline_to} onChange={e => date("deadline_to", e.target.value)} /></label>
        <label className="check"><input type="checkbox" checked={Boolean(filters.changed_since)} onChange={e => setFilters({ ...filters, changed_since: e.target.checked ? (localStorage.getItem("procureDeltaLastVisit") ?? new Date().toISOString()) : "" })} /> 지난 방문 후 변경</label>
        <label className="check"><input type="checkbox" checked={filters.eligible_only} onChange={e => setFilters({ ...filters, eligible_only: e.target.checked })} /> 경고 없는 참여 가능 공고만</label>
      </div></details>
    </form>
    <div className="inbox-toolbar"><div className="quick-views" role="group" aria-label="불러온 공고 빠른 보기">{views.map(option =>
      <button type="button" key={option.key} className={`quick-view${view === option.key ? " active" : ""}`} aria-pressed={view === option.key} onClick={() => setView(option.key)}>
        {option.label} <span>{filterInbox(items, option.key).length}</span></button>)}</div>
      <label className="inbox-sort">정렬 <select value={sort} onChange={e => setSort(e.target.value as InboxSort)}><option value="recommendation">추천 · 관련도순</option><option value="deadline">마감 임박순</option><option value="budget">예산 높은순 · 통화별</option></select></label></div>
    <p className="inbox-scope">현재 불러온 {items.length}건 중 {visible.length}건 표시 · 빠른 보기와 정렬은 불러온 공고에만 적용됩니다.</p>
    <InboxComparison items={compared} onRemove={id => setSelected(current => current.filter(value => value !== id))} onClear={() => setSelected([])} />
    {loading ? <div className="state" role="status"><span className="spinner" />공고를 불러오는 중입니다.</div>
      : error && !items.length ? <div className="state error" role="alert"><p>{error}</p><button type="button" onClick={() => refresh()}>다시 시도</button></div>
      : items.length ? <>{visible.length ? <section className="cards" aria-label="공고 목록">{visible.map(item =>
        <OpportunityCard key={item.id} item={item} selected={selected.includes(item.id)} selectionDisabled={selected.length >= 3} onSelect={id => setSelected(current => toggleComparison(current, id, items.map(row => row.id)))} />)}</section>
        : <div className="state"><h2>선택한 빠른 보기에 해당하는 공고가 없습니다</h2><p>다른 보기를 선택하거나 공고를 더 불러오세요.</p></div>}
        {error && <p role="alert" className="load-error">{error} <button type="button" onClick={loadMore}>다시 시도</button></p>}
        {cursor && <div className="load-more"><button type="button" disabled={more} onClick={loadMore}>{more ? "불러오는 중…" : "공고 더 보기"}</button></div>}</>
      : <div className="state"><h2>조건에 맞는 공고가 없습니다</h2><p>필터 범위를 넓히거나 기업 프로필을 확인해 보세요.</p></div>}
  </main>;
}
