import Link from "next/link";
import { AdminConsole } from "../../components/admin/admin-console";
export default function AdminPage() {
  const staticDemo = process.env.NEXT_PUBLIC_STATIC_DEMO === "true";
  return (
    <>
      <header className="topbar">
        <Link className="brand" href="/">
          Procure<span>Delta</span>
        </Link>
        <span className="demo-chip">
          {staticDemo ? "합성 운영 스냅샷" : "운영자 콘솔"}
        </span>
      </header>
      <AdminConsole />
      <footer>
        {staticDemo
          ? "공개 데모의 운영 값은 저장된 합성 스냅샷입니다."
          : "운영 값은 ProcureDelta API에서 직접 조회합니다."}
      </footer>
    </>
  );
}
