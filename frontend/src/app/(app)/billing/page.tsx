"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Card, ClinicBadge, DataTable, ExportButtons, Field, Input, PageHeader, Pagination, Select, StatusBadge } from "@/components/ui";
import { openFile } from "@/lib/api";
import { useApi, useDebounced } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

export default function BillingPage() {
  const { t } = useI18n();
  const router = useRouter();
  const { clinicParam, can, fmt } = useSession();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [payment, setPayment] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const dq = useDebounced(q);
  const params = { q: dq, status, payment_status: payment, from, to, clinic: clinicParam, page };
  const { data, loading } = useApi<any>("/invoices", params);
  const reset = (fn: (v: string) => void) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { fn(e.target.value); setPage(1); };

  return (
    <>
      <PageHeader title={t("inv.title")} actions={can("billing.create") && <Button variant="primary" onClick={() => router.push("/billing/new")}>+ {t("inv.new")}</Button>} />
      <Card padded={false}>
        <div className="grid grid-cols-2 items-end gap-3 border-b border-slate-200 p-3 dark:border-slate-700 md:grid-cols-6">
          <Field label={t("common.search")} className="col-span-2"><Input type="search" value={q} onChange={reset(setQ)} /></Field>
          <Field label={t("common.status")}>
            <Select value={status} onChange={reset(setStatus)}>
              <option value="">{t("common.all")}</option>{["Draft", "Posted", "Void"].map((s) => <option key={s} value={s}>{t(`inv.status.${s}`)}</option>)}
            </Select>
          </Field>
          <Field label={t("inv.paid")}>
            <Select value={payment} onChange={reset(setPayment)}>
              <option value="">{t("common.all")}</option>{["Unpaid", "Partial", "Paid", "Credit"].map((s) => <option key={s} value={s}>{t(`pay.${s}`)}</option>)}
            </Select>
          </Field>
          <Field label={t("common.from")}><Input type="date" value={from} onChange={reset(setFrom)} /></Field>
          <Field label={t("common.to")}><Input type="date" value={to} onChange={reset(setTo)} /></Field>
        </div>
        <div className="flex justify-end border-b border-slate-200 px-3 py-2 dark:border-slate-700">
          <ExportButtons onExport={(f) => openFile("/invoices", { ...params, page: undefined, format: f })} />
        </div>
        <DataTable rows={data?.items} loading={loading} onRowClick={(i: any) => router.push(`/billing/${i.id}`)} columns={[
          { key: "number", header: t("inv.number"), className: "whitespace-nowrap tabular-nums font-medium" },
          { key: "date", header: t("common.date"), render: (i: any) => fmt.date(i.date) },
          { key: "patient_name", header: t("common.patient") },
          { key: "doctor_name", header: t("common.doctor"), render: (i: any) => i.doctor_name ?? "—" },
          { key: "clinic", header: t("common.clinic"), render: (i: any) => <ClinicBadge clinic={i.clinic} /> },
          { key: "status", header: t("common.status"), render: (i: any) => <span className="flex gap-1"><StatusBadge status={i.status} prefix="inv.status." />{i.status !== "Void" && <StatusBadge status={i.payment_status} prefix="pay." />}</span> },
          { key: "total", header: t("common.total"), align: "end", render: (i: any) => fmt.money(i.total) },
          { key: "balance", header: t("inv.balance"), align: "end", render: (i: any) => fmt.money(i.balance) },
        ]} />
        {data && <Pagination page={page} total={data.total} pageSize={data.page_size} onPage={setPage} />}
      </Card>
    </>
  );
}
