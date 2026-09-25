import Link from "next/link";
import type { Opportunity } from "../../lib/api";
import { describeDecision, formatDate, formatMoney } from "../../lib/product";
import { scorePercent } from "../../lib/inbox";

export function InboxComparison({ items, onRemove, onClear }: {
  items: Opportunity[]; onRemove: (id: string) => void; onClear: () => void;
}) {
  if (!items.length) return null;
  return <section className="compare-section" aria-labelledby="comparison-heading">
    <div className="compare-bar"><div><p className="eyebrow">SIDE BY SIDE</p><h2 id="comparison-heading">공고 비교 <small>{items.length}/3</small></h2>
      <p>불러온 공고 중 선택한 항목을 비교합니다. 참여 조건과 관련도 점수는 별개입니다.</p></div>
      <button type="button" className="ghost" onClick={onClear}>비교 초기화</button></div>
    <div className="compare-table-wrap"><table className="compare-table">
      <caption className="sr-only">선택한 공고의 참여 조건, 관련도, 예산 및 마감일 비교</caption>
      <thead><tr><th scope="col">비교 항목</th>{items.map(item => <th scope="col" key={item.id}><Link href={`/opportunities/${item.id}`}>{item.title}</Link><br /><button type="button" className="compare-remove" onClick={() => onRemove(item.id)} aria-label={`${item.title} 비교에서 제외`}>제외</button></th>)}</tr></thead>
      <tbody>
        <tr><th scope="row">발주기관</th>{items.map(item => <td key={item.id}>{item.buyer_name}</td>)}</tr>
        <tr><th scope="row">참여 조건</th>{items.map(item => <td key={item.id}>{describeDecision(item.decision_status, item.eligibility).label}</td>)}</tr>
        <tr><th scope="row">관련도 점수</th>{items.map(item => { const score = scorePercent(item.ranking); return <td key={item.id}>{score !== null ? `${score}점` : "평가 대기"}</td>; })}</tr>
        <tr><th scope="row">추천 판단</th>{items.map(item => <td key={item.id}>{item.ranking ? (item.ranking.recommended ? "검토 추천" : "추천 기준 미충족") : "평가 대기"}</td>)}</tr>
        <tr><th scope="row">예산</th>{items.map(item => <td key={item.id}>{formatMoney(item.estimated_amount, item.currency)}</td>)}</tr>
        <tr><th scope="row">마감일</th>{items.map(item => <td key={item.id}>{formatDate(item.closes_at)}</td>)}</tr>
      </tbody></table></div>
  </section>;
}
