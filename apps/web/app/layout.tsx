import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./styles.css";
import "./mobile-fixes.css";

export const metadata: Metadata = {
  title: "ProcureDelta | 조달 변화 인텔리전스",
  description: "공고부터 정정, 낙찰, 계약까지 이어지는 조달 변화 인텔리전스",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
