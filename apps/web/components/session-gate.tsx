"use client";
import { useEffect, useState, type ReactNode } from "react";
import { bootstrapSession } from "../lib/api";
export function SessionGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  useEffect(() => {
    let active = true;
    let started = false;
    const startedAt = new Date().toISOString();
    const remember = () => {
      if (started) localStorage.setItem("procureDeltaLastVisit", startedAt);
    };
    bootstrapSession()
      .then(() => {
        if (active) {
          started = true;
          const previous = localStorage.getItem("procureDeltaLastVisit");
          if (previous)
            sessionStorage.setItem("procureDeltaPreviousVisit", previous);
          window.addEventListener("pagehide", remember);
          setState("ready");
        }
      })
      .catch(() => {
        if (active) setState("error");
      });
    return () => {
      active = false;
      window.removeEventListener("pagehide", remember);
    };
  }, []);
  if (state === "loading")
    return (
      <main className="state" aria-live="polite">
        <span className="spinner" />
        합성 데모 세션을 준비하고 있습니다.
      </main>
    );
  if (state === "error")
    return (
      <main className="state error">
        <h1>데모를 시작할 수 없습니다</h1>
        <p>API와 세션 서비스 상태를 확인한 뒤 다시 시도해 주세요.</p>
        <button onClick={() => location.reload()}>다시 시도</button>
      </main>
    );
  return children;
}
