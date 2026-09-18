import Link from "next/link";
import { AdminConsole } from "../../components/admin/admin-console";
export default function AdminPage() {
  return (
    <>
      <header className="topbar">
        <Link className="brand" href="/">
          Procure<span>Delta</span>
        </Link>
        <span className="demo-chip">운영자 콘솔</span>
      </header>
      <AdminConsole />
      <footer>운영 값은 ProcureDelta API에서 직접 조회합니다.</footer>
    </>
  );
}
