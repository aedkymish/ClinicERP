"use client";
import { AttendanceSheet } from "@/components/AttendanceSheet";
import { ChangePasswordForm } from "@/components/ChangePasswordForm";
import { Button, Card, DataTable, PageHeader, StatusBadge } from "@/components/ui";
import { openFile } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

export default function ProfilePage() {
  const { t } = useI18n();
  const { me, fmt } = useSession();
  const staff = useApi<any>(me.staff_id ? `/staff/${me.staff_id}` : null);
  const slips = useApi<any[]>("/payroll/my");
  const s = staff.data;

  return (
    <>
      <PageHeader title={t("prof.title")} subtitle={`${me.name} · ${t(`role.${me.role}`)} · ${me.username}`} />
      <div className="grid gap-4 lg:grid-cols-2">
        {s && (
          <Card title={t("nav.staff")}>
            <dl className="grid grid-cols-3 gap-y-1.5 text-sm">
              <dt className="text-slate-500">{t("common.clinic")}</dt><dd className="col-span-2">{t(`clinic.${s.clinic_scope}`)}</dd>
              <dt className="text-slate-500">{t("staff.specialty")}</dt><dd className="col-span-2">{s.specialty ?? "—"}</dd>
              <dt className="text-slate-500">{t("common.phone")}</dt><dd className="col-span-2">{s.phone ?? "—"}</dd>
              <dt className="text-slate-500">{t("common.email")}</dt><dd className="col-span-2">{s.email ?? "—"}</dd>
              <dt className="text-slate-500">{t("staff.hireDate")}</dt><dd className="col-span-2">{s.hire_date ? fmt.date(s.hire_date) : "—"}</dd>
            </dl>
          </Card>
        )}
        <Card title={t("auth.change")}><ChangePasswordForm onDone={() => {}} /></Card>
        <Card title={t("payroll.my")} padded={false} className="lg:col-span-2">
          <DataTable rows={slips.data} loading={slips.loading} columns={[
            { key: "month", header: t("payroll.month") },
            { key: "status", header: t("common.status"), render: (l: any) => <StatusBadge status={l.status} prefix="payroll.st." /> },
            { key: "commission", header: t("payroll.commission"), align: "end", render: (l: any) => fmt.money(l.commission) },
            { key: "net", header: t("payroll.net"), align: "end", render: (l: any) => fmt.money(l.net) },
            { key: "pdf", header: "", render: (l: any) => <Button size="sm" variant="ghost" onClick={() => openFile(`/payroll/lines/${l.id}/payslip`)}>{t("payroll.payslip")}</Button> },
          ]} />
        </Card>
      </div>
      {me.staff_id && <div className="mt-4"><AttendanceSheet own /></div>}
    </>
  );
}
