"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Card, DataTable, Field, Input, PageHeader, StatusBadge, useFeedback } from "@/components/ui";
import { api } from "@/lib/api";
import { monthISO, useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

export default function PayrollPage() {
  const { t } = useI18n();
  const fb = useFeedback();
  const router = useRouter();
  const { fmt } = useSession();
  const { data, loading } = useApi<any[]>("/payroll/runs");
  const [month, setMonth] = useState(monthISO());
  const [busy, setBusy] = useState(false);

  const generate = async () => {
    setBusy(true);
    try {
      const run = await api.post("/payroll/runs", { month });
      router.push(`/payroll/${run.id}`);
    } catch (e) {
      fb.error(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title={t("payroll.title")} actions={
        <div className="flex items-end gap-2">
          <Field label={t("payroll.month")}><Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} /></Field>
          <Button variant="primary" loading={busy} onClick={generate}>{t("payroll.generate")}</Button>
        </div>
      } />
      <Card padded={false}>
        <DataTable rows={data} loading={loading} onRowClick={(r: any) => router.push(`/payroll/${r.id}`)} columns={[
          { key: "month", header: t("payroll.month"), className: "font-medium tabular-nums" },
          { key: "status", header: t("common.status"), render: (r: any) => <StatusBadge status={r.status} prefix="payroll.st." /> },
          { key: "employees", header: t("payroll.employees"), align: "end" },
          { key: "total_net", header: t("payroll.net"), align: "end", render: (r: any) => fmt.money(r.total_net) },
          { key: "approved_by", header: t("payroll.approve"), render: (r: any) => r.approved_by ?? "—" },
          { key: "paid_on", header: t("payroll.paidOn"), render: (r: any) => (r.paid_on ? `${fmt.date(r.paid_on)} · ${r.method}` : "—") },
        ]} />
      </Card>
    </>
  );
}
