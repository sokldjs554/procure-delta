"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { logout } from "../lib/api";
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
    <>
      <header className="topbar">
        <Link className="brand" href="/" onClick={completeVisit}>
          Procure<span>Delta</span>
        </Link>
        <nav aria-label="주요 메뉴">
          {links.map(([href, label]) => (
            <Link
              className={path.startsWith(href) ? "active" : ""}
              key={href}
              href={href}
            >
              {label}
            </Link>
          ))}
        </nav>
        <span className="demo-chip">합성 데모</span>
        <button onClick={leave}>데모 종료</button>
      </header>
      {children}
      <footer>ProcureDelta · 합성 기업 데이터로 작동하는 비운영 데모</footer>
    </>
  );
}
