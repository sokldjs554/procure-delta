"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { logout } from "../lib/api";
import { UiIcon } from "./ui-icon";
const links = [
  ["/inbox", "공고함"],
  ["/pipeline", "파이프라인"],
  ["/watchlist", "관심 공고"],
  ["/notifications", "알림"],
  ["/profile", "기업 프로필"],
  ["/about", "평가·한계"],
];
export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const active = links.find(([href]) => path.startsWith(href))?.[1] ?? "공고 상세";
  const icons = ["inbox", "pipeline", "watch", "bell", "profile", "chart"];
  function completeVisit() {
    const completedAt = new Date().toISOString();
    localStorage.setItem("procureDeltaLastVisit", completedAt);
    sessionStorage.setItem("procureDeltaPreviousVisit", completedAt);
  }
  async function leave() {
    await logout();
    completeVisit();
    router.push("/");
  }
  return (
    <div className="workspace-shell">
      <a className="skip-link" href="#workspace-content">본문으로 건너뛰기</a>
      <aside className="workspace-sidebar">
        <Link className="brand" href="/" onClick={completeVisit}>
          Procure<span>Delta</span>
        </Link>
        <div className="workspace-caption">PROCUREMENT WORKSPACE</div>
        <nav aria-label="주요 메뉴">
          {links.map(([href, label], index) => (
            <Link
              className={path.startsWith(href) ? "active" : ""}
              key={href}
              href={href}
              aria-current={path.startsWith(href) ? "page" : undefined}
            >
              <UiIcon name={icons[index]} /><span>{label}</span>
            </Link>
          ))}
        </nav>
        <div className="workspace-guide"><span className="guide-mark">Δ</span><strong>변경이 판단을 바꾸는 순간</strong><p>공고를 찾고, 바뀐 조건과 판단 근거를 함께 확인하세요.</p><Link href="/pipeline">3가지 시나리오 체험 <span aria-hidden="true">↗</span></Link></div>
        <div className="sidebar-bottom"><span className="status-dot" />합성 데이터 워크스페이스</div>
      </aside>
      <div className="workspace-body">
        <header className="workspace-topbar"><div><span>워크스페이스</span><span aria-hidden="true">/</span><strong>{active}</strong></div><div><span className="demo-chip">합성 데모</span><button className="ghost leave-demo" onClick={leave}>데모 종료</button></div></header>
        <div id="workspace-content" tabIndex={-1}>{children}</div>
        <footer>ProcureDelta · 합성 기업 데이터로 작동하는 비운영 데모</footer>
      </div>
    </div>
  );
}
