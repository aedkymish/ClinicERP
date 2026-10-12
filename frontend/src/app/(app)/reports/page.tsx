"use client";
import { useState } from "react";
import { useLookups } from "@/components/forms";
import { Card, DataTable, ExportButtons, Field, Input, PageHeader, Select, Stat, Tabs } from "@/components/ui";
import { openFile } from "@/lib/api";
import { todayISO, useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

const ids = (rows: any[] | undefined) => rows?.map((r, i) => ({ ...r, id: i }));

export default function ReportsPage() {
  const { t } = useI18n();
  const { can, clinicParam, fmt } = useSession();
  const lookups = useLookups();
  const full = can("reports.full");
  const available = full ? ["summary", "revenue", "commission", "cash", "aging", "expenses"]
    : [...(can("reports.commission_own") ? ["commission"] : []), ...(can("reports.cash") ? ["cash"] : [])];
  const [name, setName] = useState(available[0]);
  const today = todayISO();
  const [from, setFrom] = useState(available[0] === "cash" ? today : today.slice(0, 8) + "01");
  const [to, setTo] = useState(today);
  const [doctor, setDoctor] = useState("");
  const params = { from, to, clinic: clinicParam, doctor: name === "commission" && doctor ? doctor : undefined };
  const { data: r, loading } = useApi<any>(`/reports/${name}`, params);
  const money = (k: string) => (row: any) => fmt.money(row[k]);

  return (
    <>
      <PageHeader title={t("rep.title")} actions={<ExportButtons pdf onExport={(f) => openFile(`/reports/${name}`, { ...params, format: f })} />} />
      <Tabs tabs={available.map((n) => ({ id: n, label: t(`rep.${n}`) }))} active={name} onChange={setName} />
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Field label={name === "aging" ? t("common.date") : t("common.from")}>{name === "aging" ? <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} /> : <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
        {name !== "aging" && <Field label={t("common.to")}><Input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>}
        {name === "commission" && full && (
          <Field label={t("common.doctor")}>
            <Select value={doctor} onChange={(e) => setDoctor(e.target.value)}><option value="">{t("common.all")}</option>{lookups.doctors.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select>
          </Field>
        )}
      </div>

      {loading && !r ? null : r && r.name === name && (
        <div className="space-y-4">
          {name === "summary" && <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {Object.entries<number>(r.kpis).map(([k, v]) => <Stat key={k} label={t(`rep.kpi.${k}`)} value={fmt.money(v)} tone={k === "net_profit" ? (v < 0 ? "red" : "green") : undefined} />)}
            </div>
            <Breakdowns r={r} />
            <Card title={t("rep.expenses")} padded={false}>
              <DataTable rows={ids(r.expenses_by_category)} columns={[{ key: "category", header: t("common.category") }, { key: "count", header: "#", align: "end" }, { key: "amount", header: t("common.amount"), align: "end", render: money("amount") }]} />
            </Card>
          </>}
          {name === "revenue" && <Breakdowns r={r} />}
          {name === "commission" && <>
            <Card title={t("rep.commission")} padded={false}>
              <DataTable rows={ids(r.per_doctor)} columns={[{ key: "doctor", header: t("common.doctor") }, { key: "lines", header: t("inv.lines"), align: "end" }, { key: "commission", header: t("payroll.commission"), align: "end", render: money("commission") }]} />
            </Card>
            <Card padded={false}>
              <DataTable rows={ids(r.lines)} columns={[
                { key: "doctor", header: t("common.doctor") }, { key: "invoice", header: t("inv.number") }, { key: "patient", header: t("common.patient") },
                { key: "description", header: t("common.service") }, { key: "qty", header: t("common.qty"), align: "end" },
                { key: "unit_price", header: t("common.price"), align: "end", render: money("unit_price") }, { key: "discount", header: t("inv.discount"), align: "end", render: money("discount") },
                { key: "lab_cost", header: t("inv.lab"), align: "end", render: money("lab_cost") }, { key: "share_pct", header: t("inv.share"), align: "end" },
                { key: "base", header: t("rep.base"), align: "end", render: money("base") }, { key: "paid_pct", header: t("rep.paidPct"), align: "end" },
                { key: "commission", header: t("payroll.commission"), align: "end", render: money("commission") },
              ]} />
            </Card>
          </>}
          {name === "cash" && <>
            <Card title={t("rep.cash")} padded={false}>
              <DataTable rows={ids(r.totals)} columns={[
                { key: "date", header: t("common.date") }, { key: "user", header: t("common.user") }, { key: "method", header: t("common.method") },
                { key: "received", header: t("rep.received"), align: "end", render: money("received") }, { key: "refunded", header: t("inv.refunded"), align: "end", render: money("refunded") },
                { key: "net", header: t("rep.net"), align: "end", render: money("net") },
              ]} />
              <div className="border-t border-slate-200 px-3 py-2 text-end font-semibold dark:border-slate-700">{t("rep.net")}: {fmt.money(r.net)}</div>
            </Card>
            <Card padded={false}>
              <DataTable rows={ids(r.rows)} columns={[
                { key: "date", header: t("common.date") }, { key: "user", header: t("common.user") }, { key: "invoice", header: t("inv.number") },
                { key: "patient", header: t("common.patient") }, { key: "method", header: t("common.method") }, { key: "amount", header: t("common.amount"), align: "end", render: money("amount") },
              ]} />
            </Card>
          </>}
          {name === "aging" && <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              {Object.entries<number>(r.buckets).map(([b, v]) => <Stat key={b} label={t("rep.days", { b })} value={fmt.money(v)} tone={b === "90+" && v ? "red" : undefined} />)}
              <Stat label={t("common.total")} value={fmt.money(r.total)} />
            </div>
            <Card padded={false}>
              <DataTable rows={ids(r.rows)} columns={[
                { key: "invoice", header: t("inv.number") }, { key: "date", header: t("common.date") }, { key: "patient", header: t("common.patient") },
                { key: "phone", header: t("common.phone") }, { key: "age_days", header: "Days", align: "end" }, { key: "balance", header: t("inv.balance"), align: "end", render: money("balance") },
              ]} />
            </Card>
          </>}
          {name === "expenses" && (
            <Card title={`${t("rep.expenses")} · ${fmt.money(r.total)}`} padded={false}>
              <DataTable rows={ids(r.by_category)} columns={[{ key: "category", header: t("common.category") }, { key: "count", header: "#", align: "end" }, { key: "amount", header: t("common.amount"), align: "end", render: money("amount") }]} />
            </Card>
          )}
        </div>
      )}
    </>
  );
}

function Breakdowns({ r }: { r: any }) {
  const { t } = useI18n();
  const { fmt, settings } = useSession();
  const blocks: [string, string, (row: any) => string][] = [
    ["by_clinic", "rep.byClinic", (x) => settings.clinics[x.clinic as "dental"]?.name ?? x.clinic],
    ["by_doctor", "rep.byDoctor", (x) => x.doctor],
    ["by_method", "rep.byMethod", (x) => x.method],
    ["by_service", "rep.byService", (x) => x.service],
  ];
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {blocks.map(([key, label, name]) => (
        <Card key={key} title={t(label)} padded={false}>
          <DataTable rows={ids(r[key])} columns={[{ key: "name", header: t("common.name"), render: name }, { key: "amount", header: t("common.amount"), align: "end", render: (x: any) => fmt.money(x.amount) }]} />
        </Card>
      ))}
    </div>
  );
}
