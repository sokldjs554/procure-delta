import type {ReactNode} from "react";import {AppShell} from "../../components/app-shell";import {SessionGate} from "../../components/session-gate";
export default function ProductLayout({children}:{children:ReactNode}){return <AppShell><SessionGate>{children}</SessionGate></AppShell>}
