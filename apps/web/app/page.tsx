import Link from "next/link";

export default function Home() {
  return (
    <main className="landing">
      <nav className="landing-nav">
        <Link className="brand" href="/">
          Procure<span>Delta</span>
        </Link>
        <div className="landing-nav-links" aria-label="제품 메뉴">
          <Link href="/inbox">공고함</Link>
          <Link href="/watchlist">관심 공고</Link>
          <Link href="/notifications">알림</Link>
          <Link href="/about">평가·한계</Link>
        </div>
        <Link className="landing-demo-link" href="/inbox">
          합성 데모 시작 <span aria-hidden="true">→</span>
        </Link>
      </nav>

      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">B2B PROCUREMENT INTELLIGENCE</p>
          <h1>
            맞는 공고만,
            <br />
            <em>끝까지.</em>
          </h1>
          <p className="lead">
            기업 조건에 맞는 공고를 찾고, 정정·변경·낙찰·계약 결과까지 하나의
            흐름으로 추적합니다.
          </p>
          <div className="hero-actions">
            <Link className="button primary" href="/inbox">
              제품 둘러보기 <span aria-hidden="true">→</span>
            </Link>
            <Link className="button ghost" href="/about">
              평가와 한계 보기
            </Link>
          </div>
          <p className="demo-note">
            실제 기업 정보를 사용하지 않는 합성 데이터 데모입니다.
          </p>
          <div className="hero-proof" aria-label="ProcureDelta 핵심 흐름">
            <span>
              <b>5단계</b>
              <small>조달 lifecycle</small>
            </span>
            <span>
              <b>Delta</b>
              <small>변경 추적</small>
            </span>
            <span>
              <b>Evidence</b>
              <small>근거 연결</small>
            </span>
          </div>
        </div>

        <div className="hero-visual">
          <div className="hero-data-note">
            <span>PUBLIC PROCUREMENT DATA</span>
            <strong>발견 → 변경 → 결과를 하나의 흐름으로</strong>
          </div>
          <div className="hero-console" aria-label="합성 공고 화면 미리보기">
            <header>
              <span className="brand">
                Procure<span>Delta</span>
              </span>
              <span>OPPORTUNITY FLOW</span>
            </header>
            <div className="console-body">
              <ol className="procurement-rail">
                <li className="done">
                  <span>01</span>
                  <b>사전규격</b>
                </li>
                <li className="done">
                  <span>02</span>
                  <b>공고</b>
                </li>
                <li className="active">
                  <span>03</span>
                  <b>정정·변경</b>
                </li>
                <li>
                  <span>04</span>
                  <b>낙찰</b>
                </li>
                <li>
                  <span>05</span>
                  <b>계약</b>
                </li>
              </ol>
              <div className="console-panel">
                <div className="console-toolbar">
                  <div>
                    <small>현재 기업 프로필 기준</small>
                    <strong>공고함</strong>
                  </div>
                  <span>합성 데이터</span>
                </div>
                <article className="console-opportunity">
                  <div className="console-tags">
                    <span>tender</span>
                    <span className="alert">필수 조건 불일치</span>
                  </div>
                  <h2>Synthetic cloud migration tender</h2>
                  <p>Synthetic Seoul Digital Agency</p>
                  <dl>
                    <div>
                      <dt>예산</dt>
                      <dd>₩125,000,000</dd>
                    </div>
                    <div>
                      <dt>마감</dt>
                      <dd>2026. 9. 30.</dd>
                    </div>
                    <div>
                      <dt>관련도</dt>
                      <dd>68</dd>
                    </div>
                  </dl>
                </article>
                <article className="console-opportunity compact">
                  <div className="console-tags">
                    <span>amendment</span>
                    <span className="success">변경 감지</span>
                  </div>
                  <h2>Synthetic cloud migration amendment</h2>
                  <p>예산·마감·조건 차이를 이전 버전과 비교합니다.</p>
                </article>
              </div>
            </div>
          </div>
          <div className="hero-signal" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </div>
        </div>
      </section>

      <section className="lifecycle">
        <div className="lifecycle-intro">
          <p className="eyebrow">PROCUREMENT LIFECYCLE</p>
          <h2>발견 이후까지 이어지는 조달 인텔리전스</h2>
          <p>
            기업 조건에 맞는 공고를 찾는 데서 끝나지 않고, 바뀐 조건과 결과를
            같은 조달 건의 흐름으로 연결합니다.
          </p>
        </div>
        <article>
          <b>01</b>
          <h2>발견</h2>
          <p>기업 조건에 맞는 공고를 모아 참여 가능성과 관련도를 분리해 판단합니다.</p>
        </article>
        <article>
          <b>02</b>
          <h2>변경 추적</h2>
          <p>정정 전후의 금액, 일정, 자격 조건과 문서 변경을 근거 단위로 비교합니다.</p>
        </article>
        <article>
          <b>03</b>
          <h2>결과 연결</h2>
          <p>공고에서 낙찰·계약까지 같은 조달 건의 현재 흐름과 과거 연결을 보존합니다.</p>
        </article>
      </section>
    </main>
  );
}
