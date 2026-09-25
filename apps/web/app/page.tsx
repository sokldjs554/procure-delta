import Link from "next/link";
import { UiIcon } from "../components/ui-icon";

export default function Home() {
  return <main className="landing">
    <nav className="landing-nav" aria-label="제품 메뉴">
      <Link className="brand" href="/">Procure<span>Delta</span><small>조달 변화 인텔리전스</small></Link>
      <div className="landing-nav-links"><Link href="/inbox">공고 탐색</Link><Link href="/pipeline">변경 추적 체험</Link><Link href="/about">평가·한계</Link></div>
      <Link className="landing-demo-link" href="/inbox">워크스페이스 열기 <UiIcon name="arrow" /></Link>
    </nav>
    <section className="hero">
      <div className="hero-copy">
        <p className="eyebrow"><span className="status-dot" />PROCUREMENT, WITH CONTEXT</p>
        <h1>맞는 공고만,<br /><em>바뀐 조건까지.</em></h1>
        <p className="lead">어제의 추천이 오늘도 유효할까요?<br />공고를 비교하고, 달라진 조건과 판단의 근거를<br className="desktop-break" /> 한곳에서 확인하세요.</p>
        <div className="hero-actions"><Link className="button primary" href="/inbox">제품 둘러보기 <UiIcon name="arrow" /></Link><Link className="button ghost" href="/pipeline">파이프라인 데모 보기</Link></div>
        <p className="demo-note">별도 가입 없이 체험 · 모든 공고와 기업 정보는 합성 데이터</p>
        <div className="hero-proof" aria-label="ProcureDelta 핵심 흐름"><span><b>탐색</b><small>조건에 맞는 후보 찾기</small></span><span><b>비교</b><small>예산·마감·참여 조건</small></span><span><b>추적</b><small>바뀐 판단과 원문 근거</small></span></div>
      </div>
      <div className="hero-visual">
        <div className="hero-data-note"><span>CHANGE INTELLIGENCE</span><strong>공고의 변화가 한눈에 보이도록</strong></div>
        <div className="hero-console" aria-label="합성 공고 화면 미리보기">
          <header><span className="preview-dots" aria-hidden="true"><i /><i /><i /></span><span>공고 변경 브리핑</span><span className="preview-synthetic">합성 예시</span></header>
          <div className="preview-body">
            <div className="preview-heading"><span className="preview-stage">정정 공고</span><span className="preview-id">R26BK-AI-001</span></div>
            <h2>AI 기반 민원상담 시스템 구축</h2><p className="preview-buyer">서울 디지털행정원 · 원문 v1 → v2</p>
            <div className="preview-change"><div><small>예산 변경</small><span>3억 2,000만원</span><strong>2억 8,000만원 <b>−4,000만원</b></strong></div><span className="preview-delta" aria-hidden="true">Δ</span></div>
            <div className="preview-lines"><div><span>마감일</span><s>09.30</s><b>10.02</b></div><div><span>필수 역량</span><span>LLM</span><b>LLM + STT</b></div><div><span>참가 조건</span><span>확인되지 않음</span><b>서울 소재 확인</b></div></div>
            <div className="preview-insight"><span>!</span><div><strong>관련도가 높아도, 조건 확인은 별개</strong><p>달라진 참가 조건을 확인한 뒤 검토하세요.</p></div></div>
          </div>
          <ol className="procurement-rail"><li className="done"><span>01</span><b>공고</b></li><li className="active"><span>02</span><b>정정·변경</b></li><li><span>03</span><b>조건 판단</b></li><li><span>04</span><b>알림</b></li></ol>
        </div>
        <div className="preview-caption"><span className="status-dot" /><span>원문 근거와 변경 이력을 함께 보존합니다.</span></div>
      </div>
    </section>
    <section className="product-path" aria-labelledby="path-heading">
      <div className="path-heading"><div><p className="eyebrow">YOUR NEXT DECISION</p><h2 id="path-heading">이 순서로 직접 확인해 보세요.</h2></div><p>후보를 찾는 순간부터<br />변경의 의미를 이해할 때까지.</p></div>
      <div className="path-cards">
        <Link href="/inbox"><span className="path-number">01 / DISCOVER</span><UiIcon name="inbox" /><h3>우리 기업에 맞는 공고 찾기</h3><p>필터로 후보를 좁히고 최대 3건의 예산, 마감, 참여 조건을 나란히 비교하세요.</p><b>공고함 열기 <span aria-hidden="true">↗</span></b></Link>
        <Link href="/pipeline"><span className="path-number">02 / UNDERSTAND</span><UiIcon name="pipeline" /><h3>추천이 바뀌는 이유 이해하기</h3><p>정정·장애·복구 시나리오를 한 단계씩 넘기며 입력부터 판단까지 따라가세요.</p><b>처리 과정 체험 <span aria-hidden="true">↗</span></b></Link>
        <Link href="/about"><span className="path-number">03 / VERIFY</span><UiIcon name="chart" /><h3>어디까지 검증했는지 확인하기</h3><p>저장된 실험 결과와 실제 실행 범위, 아직 검증하지 못한 한계를 확인하세요.</p><b>측정 결과 보기 <span aria-hidden="true">↗</span></b></Link>
      </div>
    </section>
    <section className="landing-principle"><div><p className="eyebrow">EVIDENCE BEFORE CONFIDENCE</p><h2>높은 점수보다 중요한 건,<br />판단할 수 있는 근거입니다.</h2></div><p>관련도와 참여 가능성을 구분합니다. 자료가 부족하거나 조건이 충돌하면 확인이 필요한 상태로 남깁니다. 공개 데모는 합성 시나리오이며 실제 입찰 판단이나 외부 알림 발송을 수행하지 않습니다.</p></section>
    <footer className="landing-footer"><span className="brand">Procure<span>Delta</span></span><p>공고의 발견부터 변경의 이해까지.</p><Link href="/about">평가와 제품 한계 ↗</Link></footer>
  </main>;
}
